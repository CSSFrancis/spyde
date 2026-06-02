import threading
import numpy as np
from typing import Tuple

from PySide6 import QtCore
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtCore import Qt
from pyqtgraph import RectROI, CircleROI, mkPen

from spyde.drawing.toolbars.toolbar import RoundedToolBar
from spyde.drawing.toolbars.plot_control_toolbar import resolve_icon_path
from spyde.external.pyqtgraph.ring_roi import RingROI
from diffsims.generators.simulation_generator import SimulationGenerator
from orix.sampling import get_sample_reduced_fundamental


def roi_to_mask(roi, signal) -> np.ndarray:
    """Convert a PyQtGraph ROI to a float32 mask matching signal.data's last two axes.

    HyperSpy Signal2D stores data as (..., slow_k, fast_k) where:
      signal_axes[0] = fast_k (innermost, kx)
      signal_axes[1] = slow_k (next-innermost, ky)

    pyqtgraph renders ImageItem in col-major order: data[i, j] lands at scene
    position (x=i, y=j).  With data shape (ky_size, kx_size), axis 0 (ky) maps
    to scene-x and axis 1 (kx) maps to scene-y.

    Therefore ROI coordinates from the scene have:
      roi.pos().x() / roi.size().x()  → ky coordinate (scene-x = ky)
      roi.pos().y() / roi.size().y()  → kx coordinate (scene-y = kx)

    The mask returned has shape (ky_size, kx_size) = (slow_k, fast_k), matching
    data[..., ky, kx] so that da.tensordot(..., axes=([-2,-1],[0,1])) is correct.
    """
    sig_axes = signal.axes_manager.signal_axes
    # sig_axes[0] = fast/innermost = kx;  sig_axes[1] = slow/next = ky
    ky_axis = sig_axes[1]
    kx_axis = sig_axes[0]

    ky_size = ky_axis.size
    kx_size = kx_axis.size

    # Build coordinate grids over (ky_size, kx_size) — matching data shape
    ky_pixels = np.arange(ky_size)
    kx_pixels = np.arange(kx_size)
    # kx_grid[ky_idx, kx_idx] = kx_idx,  ky_grid[ky_idx, kx_idx] = ky_idx
    kx_grid, ky_grid = np.meshgrid(kx_pixels, ky_pixels)

    # Scene-x = ky coordinate;  scene-y = kx coordinate  (pyqtgraph col-major)
    scene_x = ky_grid * ky_axis.scale + ky_axis.offset
    scene_y = kx_grid * kx_axis.scale + kx_axis.offset

    if isinstance(roi, RingROI):
        outer_roi = roi.rois[1]
        outer_pos = outer_roi.pos()
        outer_size = outer_roi.size()
        cx = outer_pos.x() + outer_size.x() / 2
        cy = outer_pos.y() + outer_size.y() / 2
        inner_r = roi.rois[0].size().x() / 2
        outer_r = outer_size.x() / 2
        dist2 = (scene_x - cx) ** 2 + (scene_y - cy) ** 2
        mask_bool = (dist2 >= inner_r ** 2) & (dist2 <= outer_r ** 2)

    elif isinstance(roi, CircleROI):
        pos = roi.pos()
        size = roi.size()
        cx = pos.x() + size.x() / 2
        cy = pos.y() + size.y() / 2
        r = size.x() / 2
        dist2 = (scene_x - cx) ** 2 + (scene_y - cy) ** 2
        mask_bool = dist2 <= r ** 2

    elif isinstance(roi, RectROI):
        pos = roi.pos()
        size = roi.size()
        x0, x1 = pos.x(), pos.x() + size.x()
        y0, y1 = pos.y(), pos.y() + size.y()
        # Use half-open interval [x0, x1) so the ROI covers exactly
        # the pixels whose left edges fall within the rectangle, matching
        # pyqtgraph's convention that pos+size is the exclusive right edge.
        mask_bool = (
            (scene_x >= x0) & (scene_x < x1) &
            (scene_y >= y0) & (scene_y < y1)
        )

    else:
        raise TypeError(f"Unsupported ROI type: {type(roi)}")

    return mask_bool.astype(np.float32)


def _roi_metadata(roi) -> dict:
    """Extract ROI geometry as a plain dict for signal metadata storage."""
    if isinstance(roi, RingROI):
        return {
            "type": "ring",
            "center": (roi.rois[1].pos().x() + roi.rois[1].size().x() / 2,
                       roi.rois[1].pos().y() + roi.rois[1].size().y() / 2),
            "inner_radius": roi.rois[0].size().x() / 2,
            "outer_radius": roi.rois[1].size().x() / 2,
        }
    elif isinstance(roi, CircleROI):
        return {
            "type": "disk",
            "center": (roi.pos().x() + roi.size().x() / 2,
                       roi.pos().y() + roi.size().y() / 2),
            "radius": roi.size().x() / 2,
        }
    elif isinstance(roi, RectROI):
        return {
            "type": "rectangle",
            "pos": (roi.pos().x(), roi.pos().y()),
            "size": (roi.size().x(), roi.size().y()),
        }
    return {}


def _start_progress_poll(future, indicator, client, timer_holder: list):
    """Poll dask task progress every 200 ms; update indicator; stop when done."""
    from PySide6 import QtCore as _QtCore

    try:
        graph = dict(future.__dask_graph__()) if hasattr(future, '__dask_graph__') else {}
        task_keys = list(graph.keys())
    except Exception:
        task_keys = []

    total = max(len(task_keys), 1)
    indicator.set_computing(total_tasks=total)

    timer = _QtCore.QTimer()
    timer.setInterval(200)
    timer_holder.append(timer)

    def _poll():
        if future.done():
            timer.stop()
            indicator.set_done()
            return
        if not task_keys:
            return
        try:
            info = client.scheduler_info()
            all_tasks = info.get("tasks", {})
            completed = sum(
                1 for k in task_keys
                if all_tasks.get(str(k), {}).get("state") in ("memory", "released", "forgotten")
            )
            indicator.update_progress(completed)
        except Exception:
            pass

    timer.timeout.connect(_poll)
    timer.start()


def center_zero_beam(
    toolbar: RoundedToolBar,
    make_flat_field: bool = False,
    method: str = "com",
    signal_slice: Tuple[int, int, int, int] = None,
    action_name: str = "Center zero-beam",
    *args,
    **kwargs,
):
    """
    Center the zero-beam of a 4D STEM dataset by a couple of different methods.

    Parameters
    ----------
    toolbar : spyde.plugins.toolbar.Toolbar
        The toolbar instance from which to get the current signal.
    selector : spyde.plugins.selector.Selector
        The selector instance from which to get the current signal.

    """

    print("Centering zero-beam...")
    print("arguments:", make_flat_field, method)
    print("kwargs", kwargs)
    print("args", args)

    signal = toolbar.plot.plot_state.current_signal
    if signal is None:
        print("No signal selected.")
        return

    signal.set_signal_type("electron_diffraction")

    sl = (
        signal_slice[0],
        signal_slice[0] + signal_slice[2],
        signal_slice[1],
        signal_slice[1] + signal_slice[3],
    )

    shifts = signal.get_direct_beam_position(method=method, signal_slice=sl, **kwargs)

    print(make_flat_field)
    if make_flat_field:
        if shifts._lazy:
            shifts.compute()
        shifts.get_linear_plane()

    new_signal = toolbar.plot.signal_tree.add_transformation(
        parent_signal=signal,
        node_name="Centered",
        method="center_direct_beam",
        shifts=shifts,
        inplace=False,
    )
    new_signal.calibration.center = None
    toolbar.plot.set_plot_state(new_signal)


def virtual_imaging(*args, **kwargs):
    """
    Placeholder for virtual imaging action.

    """
    print("Virtual imaging action triggered.")
    pass


def add_virtual_image(
    toolbar: RoundedToolBar, action_name: str = "Add Virtual Image", *args, **kwargs
):
    """
    Add a virtual image from a 4D STEM dataset by integrating over a specified region.

    Parameters
    ----------
    toolbar : spyde.plugins.toolbar.Toolbar
        The toolbar instance from which to get the current signal.

    """
    colors = ["red", "green", "blue", "yellow", "cyan", "magenta"]
    print("Adding virtual image...")

    icon_path = resolve_icon_path("drawing/toolbars/icons/virtual_imaging.svg")
    num = toolbar.num_actions()
    color = colors[num % len(colors)]

    base_icon = QIcon(icon_path)
    icon_size = toolbar.iconSize()
    dpr = getattr(toolbar, "devicePixelRatioF", lambda: 1.0)()
    req_w = max(1, int(icon_size.width() * dpr))
    req_h = max(1, int(icon_size.height() * dpr))
    base_pixmap = base_icon.pixmap(req_w, req_h)

    colored_pixmap = QPixmap(base_pixmap.size())
    colored_pixmap.setDevicePixelRatio(dpr)
    colored_pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(colored_pixmap)
    painter.drawPixmap(0, 0, base_pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(colored_pixmap.rect(), QColor(color))
    painter.end()

    pen = mkPen(color=color, width=6)
    icon = QIcon()
    icon.addPixmap(colored_pixmap)

    action_name = f"Virtual Image ({color})"

    # Per-VI mutable state
    _live_enabled = [True]
    _cached_mask = [None]
    _cached_roi = [None]
    _timer_holder = []  # progress poll timer
    _generation = [0]

    def _on_compute_clicked():
        # Compute button always fires this VI regardless of live flag.
        # _compute_one is defined below; this defers the lookup so it works.
        _compute_one(action_name)

    params = {
        "type": {
            "name": "Detector Type",
            "type": "enum",
            "default": "disk",
            "options": ["annular", "disk", "rectangle", "multiple_disks"],
        },
        "calculation": {
            "name": "Calculation",
            "type": "enum",
            "default": "mean",
            "options": ["mean", "FEM Omega", "COM"],
        },
        "live_compute_row": {
            "name": "",
            "type": "button_row",
            "buttons": [
                {"key": "live_button", "label": "Live (ON)", "callback": lambda: _toggle_live()},
                {"key": "compute_button", "label": "Compute", "callback": _on_compute_clicked},
            ],
        },
    }

    action, params_caret_box = toolbar.add_action(
        name=action_name,
        icon_path=icon,
        function=compute_virtual_image,
        toggle=True,
        parameters=params,
    )

    try:
        if hasattr(params_caret_box, "finalize_layout"):
            params_caret_box.finalize_layout()
    except Exception:
        pass

    type_widget = params_caret_box.kwargs["type"]

    # Get signal/client/GPU info
    plot = toolbar.parent_toolbar.plot
    signal = plot.plot_state.current_signal
    main_window = plot.main_window
    client = main_window.dask_manager.client
    gpu_worker = main_window.dask_manager.gpu_worker_address

    from spyde.qt.compute_status_indicator import ComputeStatusIndicator

    virtual_plot_window = main_window.add_plot_window(
        is_navigator=False,
        signal_tree=plot.signal_tree,
    )
    virtual_plot_window.owner_plot_window = plot.plot_window
    main_window._auto_position_near_owner(virtual_plot_window)
    virtual_plot = virtual_plot_window.add_new_plot()
    if virtual_plot.image_item not in virtual_plot.items:
        virtual_plot.addItem(virtual_plot.image_item)

    indicator = ComputeStatusIndicator(color=color)
    virtual_plot_window.set_compute_indicator(indicator)

    toolbar.parent_toolbar.register_action_plot_window(
        action_name="Virtual Imaging",
        plot_window=virtual_plot_window,
        key=action_name,
    )

    # ── Shared batch-recompute timer ────────────────────────────────────────
    # All VIs on this parent toolbar share a single 150 ms debounce timer stored
    # in action_widgets["Virtual Imaging"]["_batch_timer"].  Any ROI move restarts
    # the timer; when it fires one dask submit covers all active VIs together.
    vi_entry = toolbar.parent_toolbar.action_widgets.setdefault("Virtual Imaging", {})
    if "_batch_timer" not in vi_entry:
        from PySide6.QtCore import QTimer as _QTimer
        # Parent the timer to the toolbar so Qt manages its lifetime on the GUI
        # thread and it is never destroyed from a Dask worker thread.
        _batch_timer = _QTimer(toolbar.parent_toolbar)
        _batch_timer.setInterval(150)
        _batch_timer.setSingleShot(True)
        vi_entry["_batch_timer"] = _batch_timer
        vi_entry["_vi_registry"] = {}  # action_name → state dict
    batch_timer: "QTimer" = vi_entry["_batch_timer"]
    vi_registry: dict = vi_entry["_vi_registry"]

    # Register this VI's mutable state so the batch callback can reach it
    vi_registry[action_name] = {
        "roi_ref": [None],       # holds the current roi object (updated on type change)
        "virtual_plot": virtual_plot,
        "virtual_plot_window": virtual_plot_window,
        "indicator": indicator,
        "cached_mask": _cached_mask,
        "cached_roi": _cached_roi,
        "generation": _generation,
        "timer_holder": _timer_holder,
        "signal": signal,
        "live_enabled": _live_enabled,
    }

    def _compute_one(name: str):
        """Compute a single VI by its action_name, regardless of live flag."""
        from spyde.drawing.update_functions import compute_virtual_image_kernel
        entry = vi_registry.get(name)
        if entry is None:
            return
        current_roi = entry["roi_ref"][0]
        if current_roi is None:
            return
        try:
            mask = roi_to_mask(current_roi, entry["signal"])
        except Exception:
            return
        entry["cached_mask"][0] = mask
        entry["cached_roi"][0] = current_roi
        entry["generation"][0] += 1
        my_gen = entry["generation"][0]
        vp = entry["virtual_plot"]
        vpw = entry["virtual_plot_window"]
        ind = entry["indicator"]
        th = entry["timer_holder"]

        th.clear()
        future = compute_virtual_image_kernel(
            entry["signal"].data, mask, client, gpu_worker
        )
        vp.current_data = future
        _start_progress_poll(future, ind, client, th)
        vpw.set_commit_enabled(False)

        def _on_preview_done(fut, _gen=my_gen, _entry=entry, _vpw=vpw):
            from PySide6 import QtCore as _QtCore
            if _entry["generation"][0] != _gen:
                return
            _QtCore.QMetaObject.invokeMethod(
                _vpw, "set_commit_enabled",
                _QtCore.Qt.ConnectionType.QueuedConnection,
                _QtCore.Q_ARG(bool, True),
            )

        future.add_done_callback(_on_preview_done)

    def _batch_recompute_all():
        """Recompute every registered VI whose live flag is on, in one pass."""
        for name, entry in list(vi_registry.items()):
            if not entry["live_enabled"][0]:
                continue
            _compute_one(name)

    batch_timer.timeout.connect(_batch_recompute_all)

    def _schedule_batch_recompute(force: bool = False):
        """Restart the shared debounce timer (or fire immediately if force=True)."""
        if force:
            batch_timer.stop()
            _batch_recompute_all()
        else:
            batch_timer.start()  # restart debounce window

    def _cleanup():
        """Remove ROI from plot, de-register from batch registry, remove action."""
        vi_registry.pop(action_name, None)
        try:
            toolbar.parent_toolbar.unregister_action_plot_item(
                action_name="Virtual Imaging", key=action_name
            )
        except Exception:
            pass
        try:
            toolbar.remove_action(action_name)
        except Exception:
            pass

    _orig_close = virtual_plot_window.close_window
    def _close_with_cleanup():
        _cleanup()
        _orig_close()
    virtual_plot_window.close_window = _close_with_cleanup

    # Build the initial ROI
    center, inner_rad, outer_rad = plot.get_annular_roi_parameters()
    if params_caret_box.kwargs["type"].currentText() == "annular":
        roi = RingROI(center=center, inner_rad=inner_rad, outer_rad=outer_rad, pen=pen)
    elif params_caret_box.kwargs["type"].currentText() == "disk":
        roi = CircleROI(center, inner_rad, pen=pen)
    else:
        roi = RectROI(center, inner_rad, pen=pen)

    vi_registry[action_name]["roi_ref"][0] = roi

    toolbar.parent_toolbar.register_action_plot_item(
        action_name="Virtual Imaging", item=roi, key=action_name
    )

    def arrange_widgets_on_move():
        rois = list(
            toolbar.parent_toolbar.action_widgets["Virtual Imaging"].get("plot_items", {}).values()
        )
        sizes = [r.size().x() for r in rois]
        sorted_index = np.argsort(sizes)
        for i, idx in enumerate(sorted_index[::-1]):
            r = rois[idx]
            r.setZValue(10 + i)

    def _on_roi_finished(_roi=None):
        arrange_widgets_on_move()
        _schedule_batch_recompute()

    roi.sigRegionChangeFinished.connect(_on_roi_finished)

    def _toggle_live():
        live_btn = params_caret_box.get_parameter_widget("live_button")
        _live_enabled[0] = not _live_enabled[0]
        if live_btn is not None:
            live_btn.setText("Live (ON)" if _live_enabled[0] else "Live (OFF)")

    def _do_commit():
        if _cached_mask[0] is None:
            return
        from spyde.drawing.update_functions import compute_virtual_image_kernel
        from pyxem.signals import VirtualDarkFieldImage
        from PySide6 import QtCore as _QtCore

        virtual_plot_window.set_commit_enabled(False)
        indicator.set_computing()
        future = compute_virtual_image_kernel(signal.data, _cached_mask[0], client, gpu_worker)

        def _on_done(fut):
            try:
                result = fut.result()
            except Exception as e:
                print(f"Commit failed: {e}")
                _QtCore.QMetaObject.invokeMethod(
                    virtual_plot_window, "set_commit_enabled",
                    _QtCore.Qt.ConnectionType.QueuedConnection,
                    _QtCore.Q_ARG(bool, True),
                )
                return
            vdf = VirtualDarkFieldImage(result)
            nav_axes = list(signal.axes_manager.navigation_axes)
            sig_axes = list(vdf.axes_manager.signal_axes)
            for i, ax in enumerate(nav_axes):
                if i < len(sig_axes):
                    sig_axes[i].scale = ax.scale
                    sig_axes[i].offset = ax.offset
                    sig_axes[i].units = ax.units
                    sig_axes[i].name = ax.name
            vdf.metadata.Signal.virtual_detector = _roi_metadata(_cached_roi[0] or roi)
            main_window._pending_signal_queue.append(vdf)
            _QtCore.QMetaObject.invokeMethod(
                main_window, "_flush_pending_signals",
                _QtCore.Qt.ConnectionType.QueuedConnection,
            )
            _QtCore.QMetaObject.invokeMethod(
                virtual_plot_window, "set_commit_enabled",
                _QtCore.Qt.ConnectionType.QueuedConnection,
                _QtCore.Q_ARG(bool, True),
            )

        future.add_done_callback(_on_done)

    virtual_plot_window.set_commit_fn(_do_commit)

    def on_type_change(new_type: str) -> None:
        old_roi = toolbar.parent_toolbar.unregister_action_plot_item(
            action_name="Virtual Imaging", key=action_name
        )
        pos = old_roi.pos()
        size = old_roi.size()
        inner_r = min(size) / 2.0
        outer_r = inner_r * 2.0
        nonlocal roi
        if new_type == "annular":
            roi = RingROI(center=pos, inner_rad=inner_r, outer_rad=outer_r, pen=pen)
        elif new_type == "disk":
            roi = CircleROI(pos=pos, size=size, pen=pen)
        else:
            roi = RectROI(pos=pos, size=size, pen=pen)
        vi_registry[action_name]["roi_ref"][0] = roi
        toolbar.parent_toolbar.register_action_plot_item(
            action_name="Virtual Imaging", item=roi, key=action_name
        )
        roi.sigRegionChangeFinished.connect(_on_roi_finished)

    if hasattr(type_widget, "currentTextChanged"):
        type_widget.currentTextChanged.connect(on_type_change)


def compute_virtual_image(
    toolbar: RoundedToolBar, action_name: str = "Compute Virtual Image", *args, **kwargs
):
    """
    Compute the virtual image from a 4D STEM dataset.

    Parameters
    ----------
    toolbar : spyde.plugins.toolbar.Toolbar
        The toolbar instance from which to get the current signal.

    """
    print("Computing virtual image...")
    pass


def _generate_library_from_phases(phases, accelerating_voltage, resolution,
                                   minimum_intensity, reciprocal_radius,
                                   max_excitation_error=0.1):
    """Generate a diffsims Simulation2D library from a list of orix Phase objects."""
    generator = SimulationGenerator(
        accelerating_voltage, minimum_intensity=minimum_intensity
    )
    rotations = [
        get_sample_reduced_fundamental(
            resolution=resolution, point_group=phase.point_group
        )
        for phase in phases
    ]
    sim = generator.calculate_diffraction2d(
        phases if len(phases) > 1 else phases[0],
        rotation=rotations if len(rotations) > 1 else rotations[0],
        max_excitation_error=max_excitation_error,
        reciprocal_radius=reciprocal_radius,
        with_direct_beam=False,
    )
    return sim


def _extract_orientation_outputs(orientation_map, nav_axes, n_phases=1):
    """
    Extract result signals from an OrientationMap.

    Returns list of (BaseSignal, title_str) tuples.
    """
    import hyperspy.api as hs

    def _copy_nav_axes(sig, nav_axes):
        for i, ax in enumerate(nav_axes):
            if i < sig.axes_manager.navigation_dimension:
                out_ax = sig.axes_manager.navigation_axes[i]
                out_ax.scale = ax.scale
                out_ax.offset = ax.offset
                out_ax.units = ax.units
                out_ax.name = ax.name
        return sig

    results = []

    # Orientation map (IPF color) — passed through directly
    results.append((orientation_map, "Orientation Map"))

    # Correlation score
    if hasattr(orientation_map, "correlation"):
        corr = hs.signals.Signal2D(orientation_map.correlation.data)
        _copy_nav_axes(corr, nav_axes)
        corr.metadata.General.title = "Correlation Score"
        results.append((corr, "Correlation Score"))
    else:
        print("OrientationMap has no 'correlation' attribute — skipping Correlation Score output.")

    # Mirror symmetry
    if hasattr(orientation_map, "mirror_symmetry"):
        mirror = hs.signals.Signal2D(orientation_map.mirror_symmetry.data)
        _copy_nav_axes(mirror, nav_axes)
        mirror.metadata.General.title = "Mirror Symmetry"
        results.append((mirror, "Mirror Symmetry"))
    else:
        print("OrientationMap has no 'mirror_symmetry' attribute — skipping Mirror Symmetry output.")

    # Phase map — only for multi-phase
    if n_phases > 1:
        if hasattr(orientation_map, "phase_index"):
            phase_map = hs.signals.Signal2D(orientation_map.phase_index.data.astype(float))
            _copy_nav_axes(phase_map, nav_axes)
            phase_map.metadata.General.title = "Phase Map"
            results.append((phase_map, "Phase Map"))
        else:
            print("OrientationMap has no 'phase_index' attribute — skipping Phase Map output.")

    return results


def _filter_sim_by_radius(coords, intensities, max_radius):
    """Return coords and intensities for spots within max_radius."""
    r = np.sqrt(coords[:, 0] ** 2 + coords[:, 1] ** 2)
    mask = r <= max_radius
    return coords[mask], intensities[mask]


def _get_current_nav_indices(plot):
    """Return current navigation indices as a tuple of ints."""
    selector = getattr(plot, "parent_selector", None)
    if selector is not None:
        try:
            indices = selector.get_selected_indices()
            return tuple(int(i) for i in np.atleast_1d(indices))
        except Exception:
            pass
    nav_axes = plot.plot_state.current_signal.axes_manager.navigation_axes
    return tuple(ax.size // 2 for ax in nav_axes)


def _update_refine_pattern(refine_plot, signal, nav_indices):
    """Load the diffraction pattern at nav_indices into refine_plot."""
    idx = tuple(int(i) for i in nav_indices)
    pattern_data = np.array(signal.data[idx])
    refine_plot.update_data(pattern_data)


def _get_best_fit_spots(signal, sim, nav_indices, gamma, max_radius, min_intensity=0.0, scale_override=None):
    """
    Run get_orientation on a single diffraction pattern and return
    (coords_px, intensities) for the best-match simulation spots.

    coords_px : ndarray shape (N, 2) in pixel (row, col) coordinates
    intensities : ndarray shape (N,)
    """
    import hyperspy.api as hs

    idx = tuple(int(i) for i in nav_indices)
    pattern_data = np.array(signal.data[idx])
    pattern_signal = hs.signals.Signal2D(pattern_data)
    for i, ax in enumerate(signal.axes_manager.signal_axes):
        pattern_signal.axes_manager.signal_axes[i].scale = ax.scale
        pattern_signal.axes_manager.signal_axes[i].offset = ax.offset
        pattern_signal.axes_manager.signal_axes[i].units = ax.units

    pattern_signal.set_signal_type("electron_diffraction")
    polar = pattern_signal.get_azimuthal_integral2d(
        npt=100, npt_azim=360, inplace=False, mean=True
    )
    polar = polar ** gamma

    orientation = polar.get_orientation(sim)

    best_phase_idx = int(orientation.data["phase_index"].ravel()[0])
    # TODO: multi-phase — use best_phase_idx to select the correct phase from sim
    # e.g. sim[best_phase_idx].rotate_from_orientation(best_rotation)
    # For now, single-phase only (rotate_from_orientation called on full sim)
    best_rotation = orientation.data["orientation"].ravel()[0]

    sig_ax = signal.axes_manager.signal_axes
    scale = scale_override if scale_override is not None else sig_ax[0].scale
    sim_at_best = sim.rotate_from_orientation(best_rotation)
    raw_coords = sim_at_best.coordinates
    intensities = sim_at_best.intensities

    coords_filtered, intensities_filtered = _filter_sim_by_radius(
        raw_coords, intensities, max_radius
    )

    # Filter spots below minimum intensity threshold
    if min_intensity > 0.0 and len(intensities_filtered) > 0:
        keep = intensities_filtered >= min_intensity
        coords_filtered = coords_filtered[keep]
        intensities_filtered = intensities_filtered[keep]

    coords_px = coords_filtered / scale
    cx = pattern_data.shape[1] / 2.0
    cy = pattern_data.shape[0] / 2.0
    coords_px[:, 0] += cx
    coords_px[:, 1] += cy
    return coords_px, intensities_filtered


def _compute_reciprocal_radius(signal) -> float:
    """Derive max reciprocal radius from signal axes calibration."""
    sig_axes = signal.axes_manager.signal_axes
    half_extents = [ax.scale * ax.size / 2.0 for ax in sig_axes]
    return min(half_extents)


def _make_slider_row(parent, label_text, min_val, max_val, default, decimals=2):
    """Return (row_widget, spinbox) for a labelled float slider+spinbox row."""
    from PySide6 import QtWidgets as _QW, QtCore as _QC
    SCALE = 10 ** decimals
    row = _QW.QWidget(parent)
    h = _QW.QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(4)
    lbl = _QW.QLabel(label_text, row)
    lbl.setStyleSheet("color: white; font-size: 10px;")
    spin = _QW.QDoubleSpinBox(row)
    spin.setRange(min_val, max_val)
    spin.setDecimals(decimals)
    spin.setSingleStep(10 ** -decimals)
    spin.setValue(default)
    spin.setFixedWidth(64)
    spin.setStyleSheet(
        "QDoubleSpinBox { color: white; background: rgba(255,255,255,40); "
        "border: 1px solid black; font-size: 10px; }"
    )
    slider = _QW.QSlider(_QC.Qt.Orientation.Horizontal, row)
    slider.setRange(int(min_val * SCALE), int(max_val * SCALE))
    slider.setValue(int(default * SCALE))
    def _spin_to_slider(v, _s=slider, _sc=SCALE):
        _s.blockSignals(True); _s.setValue(int(v * _sc)); _s.blockSignals(False)
    def _slider_to_spin(v, _sp=spin, _sc=SCALE):
        _sp.blockSignals(True); _sp.setValue(v / _sc); _sp.blockSignals(False)
    spin.valueChanged.connect(_spin_to_slider)
    slider.valueChanged.connect(_slider_to_spin)
    h.addWidget(lbl)
    h.addWidget(slider, 1)
    h.addWidget(spin)
    return row, spin


def orientation_mapping(
    toolbar: RoundedToolBar,
    action_name: str = "Orientation Mapping",
    *args,
    **kwargs,
):
    """5-step wizard (tabbed) for template-matching orientation mapping of 4D-STEM data.

    Called once to build the UI (first call), and again by the caret submit button
    to run the fit on subsequent calls.
    """
    from PySide6 import QtWidgets as _QW, QtCore as _QC
    from spyde.drawing.toolbars.caret_group import FileDropWidget

    # ── On submit (Run Fit) calls after UI is built ────────────────────────────
    # The caret's submit button calls this function again. Check for stored state.
    _state = getattr(toolbar, "_om_state", None)
    if _state is not None:
        # Second+ call = submit → run fit
        _do_run_fit(_state)
        return

    # ── First call: build the UI inside the already-created caret ─────────────
    # toolbars.yaml has `parameters: {}` so the caret was already created by
    # _create_parameter_popout; retrieve it from action_widgets.
    caret_entry = getattr(toolbar, "action_widgets", {}).get(action_name, {})
    caret = caret_entry.get("widget")
    if caret is None:
        return

    plot = toolbar.plot
    signal = plot.plot_state.current_signal
    main_window = plot.main_window
    sig_ax = signal.axes_manager.signal_axes
    sig_scale = sig_ax[0].scale  # Å⁻¹/px

    # ── State dict stored on toolbar so submit calls can access it ─────────────
    state = {
        "plot": plot,
        "signal": signal,
        "main_window": main_window,
        "phases": [],
        "sim": [None],
        "gamma": [0.5],
        "min_intensity": [0.1],
        "scale_override": [None],
        "max_radius": [_compute_reciprocal_radius(signal)],
        "refit_timer": [None],
        "scatter_item": [None],
        "circle_roi": [None],
        "run_status": [None],
        "run_btn": [None],
    }
    toolbar._om_state = state

    # ── Remove auto-created placeholder row and submit button ──────────────────
    layout = caret.layout()
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()

    # ── Helper builders ────────────────────────────────────────────────────────
    W = 240

    def _lbl(text, parent):
        l = _QW.QLabel(text, parent)
        l.setStyleSheet("color: white; font-size: 10px;")
        l.setWordWrap(True)
        return l

    def _btn(text, parent, enabled=True):
        b = _QW.QPushButton(text, parent)
        b.setEnabled(enabled)
        b.setStyleSheet(
            "QPushButton { color: white; background: rgba(255,255,255,30); "
            "border: 1px solid rgba(255,255,255,60); padding: 3px 6px; }"
            "QPushButton:disabled { color: rgba(255,255,255,60); "
            "background: rgba(255,255,255,10); }"
        )
        return b

    def _hrow(*widgets):
        w = _QW.QWidget()
        h = _QW.QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(4)
        for wi in widgets:
            if isinstance(wi, int):
                h.addStretch(wi)
            else:
                h.addWidget(wi)
        return w

    def _spin(parent, lo, hi, val, dec, suf=""):
        s = _QW.QDoubleSpinBox(parent)
        s.setRange(lo, hi); s.setValue(val); s.setDecimals(dec)
        if suf: s.setSuffix(suf)
        s.setFixedWidth(72)
        s.setStyleSheet(
            "QDoubleSpinBox { color: white; background: rgba(255,255,255,40); "
            "border: 1px solid rgba(255,255,255,60); font-size: 10px; }"
        )
        return s

    # ── CheckButtonGroup-style step selector ───────────────────────────────────
    STEPS = ["1 Load", "2 Library", "3 Refine", "4 Run"]
    BTN_SS_OFF = (
        "QPushButton { color: rgba(255,255,255,160); background: rgba(255,255,255,15); "
        "border: 1px solid rgba(255,255,255,40); padding: 2px 4px; font-size: 9px; "
        "border-radius: 0px; }"
    )
    BTN_SS_ON = (
        "QPushButton { color: white; background: rgba(100,160,255,180); "
        "border: 1px solid rgba(120,180,255,200); padding: 2px 4px; font-size: 9px; "
        "border-radius: 0px; font-weight: bold; }"
    )
    step_bar = _QW.QWidget(caret)
    step_bar.setFixedWidth(W)
    sb_h = _QW.QHBoxLayout(step_bar); sb_h.setContentsMargins(0, 0, 0, 0); sb_h.setSpacing(1)
    step_btns = []
    for s in STEPS:
        b = _QW.QPushButton(s, step_bar)
        b.setStyleSheet(BTN_SS_OFF)
        b.setSizePolicy(_QW.QSizePolicy.Policy.Expanding, _QW.QSizePolicy.Policy.Fixed)
        sb_h.addWidget(b)
        step_btns.append(b)

    # Stacked pages
    stack = _QW.QStackedWidget(caret)
    stack.setFixedWidth(W)

    def _select_step(idx):
        for i, b in enumerate(step_btns):
            b.setStyleSheet(BTN_SS_ON if i == idx else BTN_SS_OFF)
        stack.setCurrentIndex(idx)

    for i, b in enumerate(step_btns):
        b.clicked.connect(lambda _, i=i: _select_step(i))

    # ── Page 0: Load CIF ──────────────────────────────────────────────────────
    p0 = _QW.QWidget(); v0 = _QW.QVBoxLayout(p0); v0.setContentsMargins(4, 4, 4, 4); v0.setSpacing(4)
    cif_drop = FileDropWidget(extensions=[".cif"], parent=p0)
    phase_lbl = _lbl("Phases: (none loaded)", p0)
    voltage_s = _spin(p0, 60, 300, 200, 0, " kV")
    v0.addWidget(_lbl("CIF file(s):", p0))
    v0.addWidget(cif_drop)
    v0.addWidget(phase_lbl)
    v0.addWidget(_hrow(_lbl("Voltage:", p0), voltage_s))
    stack.addWidget(p0)

    # ── Page 1: Generate Library ──────────────────────────────────────────────
    p1 = _QW.QWidget(); v1 = _QW.QVBoxLayout(p1); v1.setContentsMargins(4, 4, 4, 4); v1.setSpacing(4)
    res_s = _spin(p1, 0.1, 10.0, 1.0, 1, "°")
    min_int_s = _spin(p1, 0.0, 1.0, 0.05, 3)
    gen_btn = _btn("Generate Library", p1, enabled=False)
    lib_lbl = _lbl("", p1)
    v1.addWidget(_hrow(_lbl("Angle density:", p1), res_s))
    v1.addWidget(_hrow(_lbl("Min intensity:", p1), min_int_s))
    v1.addWidget(gen_btn)
    v1.addWidget(lib_lbl)
    stack.addWidget(p1)

    # ── Page 2: Refine ────────────────────────────────────────────────────────
    p2 = _QW.QWidget(); v2 = _QW.QVBoxLayout(p2); v2.setContentsMargins(4, 4, 4, 4); v2.setSpacing(4)
    gamma_row, gamma_s = _make_slider_row(p2, "Gamma", 0.1, 1.0, 0.5, decimals=2)
    min_i_row, min_i_s = _make_slider_row(p2, "Min intens.", 0.0, 1.0, 0.1, decimals=2)
    # Scale: start at signal scale, allow ±10%
    sc_lo = round(sig_scale * 0.9, 6)
    sc_hi = round(sig_scale * 1.1, 6)
    sc_step_dec = max(2, -int(np.floor(np.log10(sig_scale * 0.01))) + 1) if sig_scale > 0 else 4
    scale_row, scale_s = _make_slider_row(p2, "Scale", sc_lo, sc_hi, sig_scale, decimals=sc_step_dec)
    refine_lbl = _lbl("Generate library first.", p2)
    for r in [gamma_row, min_i_row, scale_row]:
        r.setEnabled(False)
    v2.addWidget(refine_lbl)
    v2.addWidget(gamma_row)
    v2.addWidget(min_i_row)
    v2.addWidget(scale_row)
    stack.addWidget(p2)

    # ── Page 3: Run ───────────────────────────────────────────────────────────
    p3 = _QW.QWidget(); v3 = _QW.QVBoxLayout(p3); v3.setContentsMargins(4, 4, 4, 4); v3.setSpacing(4)
    run_lbl = _lbl("", p3)
    run_btn_w = _btn("Submit", p3, enabled=False)
    v3.addWidget(_lbl("Run full orientation mapping on the dataset.", p3))
    v3.addWidget(run_btn_w)
    v3.addWidget(run_lbl)
    stack.addWidget(p3)
    state["run_status"][0] = run_lbl
    state["run_btn"][0] = run_btn_w

    layout.addWidget(step_bar)
    layout.addWidget(stack)
    caret.finalize_layout()
    _select_step(0)

    # ── Wire callbacks ─────────────────────────────────────────────────────────

    def _on_cif_loaded(files):
        from orix.crystal_map import Phase
        state["phases"].clear()
        for path in files:
            try:
                phase = Phase.from_cif(path)
                state["phases"].append(phase)
            except Exception as e:
                print(f"Failed to load CIF {path}: {e}")
        if state["phases"]:
            phase_lbl.setText("Phases: " + ", ".join(p.name for p in state["phases"]))
            gen_btn.setEnabled(True)
        else:
            phase_lbl.setText("Phases: (none loaded)")
            gen_btn.setEnabled(False)

    cif_drop.filesChanged.connect(_on_cif_loaded)

    def _on_generate():
        if not state["phases"]:
            return
        gen_btn.setEnabled(False)
        lib_lbl.setText("Generating…")
        try:
            state["sim"][0] = _generate_library_from_phases(
                phases=state["phases"],
                accelerating_voltage=voltage_s.value(),
                resolution=res_s.value(),
                minimum_intensity=min_int_s.value(),
                reciprocal_radius=_compute_reciprocal_radius(signal),
            )
            lib_lbl.setText("✓ Library ready")
            gen_btn.setText("✓ Regenerate")
            gen_btn.setEnabled(True)
            for r in [gamma_row, min_i_row, scale_row]:
                r.setEnabled(True)
            refine_lbl.setText("Overlay active. Adjust sliders to refine.")
            run_btn_w.setEnabled(True)
            _activate_overlay()
            _select_step(2)
        except Exception as e:
            lib_lbl.setText(f"Failed: {e}")
            gen_btn.setEnabled(True)

    gen_btn.clicked.connect(_on_generate)

    def _activate_overlay():
        """Add ScatterPlotItem + CircleROI to the signal plot (data coords)."""
        from pyqtgraph import ScatterPlotItem
        from pyqtgraph import CircleROI as PgCircleROI
        from PySide6.QtCore import QTimer as _QT

        if state["scatter_item"][0] is not None:
            return

        scatter = ScatterPlotItem(size=10, pen=mkPen("r", width=1.5), brush=None)
        plot.addItem(scatter)
        state["scatter_item"][0] = scatter

        # CircleROI in data (scene) coordinates — center of diffraction pattern
        r_data = state["max_radius"][0]
        cx_data = sig_ax[0].size / 2.0 * sig_ax[0].scale + sig_ax[0].offset
        cy_data = sig_ax[1].size / 2.0 * sig_ax[1].scale + sig_ax[1].offset
        circle_roi = PgCircleROI(
            pos=(cx_data - r_data, cy_data - r_data),
            size=(2 * r_data, 2 * r_data),
            pen=mkPen("y", width=1),
        )
        plot.addItem(circle_roi)
        state["circle_roi"][0] = circle_roi

        timer = _QT()
        timer.setInterval(150)
        timer.setSingleShot(True)
        state["refit_timer"][0] = timer

        def _do_refit():
            if state["sim"][0] is None:
                return
            r_now = circle_roi.size().x() / 2.0
            state["max_radius"][0] = r_now
            sc_override = scale_s.value() if abs(scale_s.value() - sig_scale) > 1e-9 else None
            state["scale_override"][0] = sc_override
            nav_idx = _get_current_nav_indices(plot)
            try:
                coords_px, intensities = _get_best_fit_spots(
                    signal, state["sim"][0], nav_idx,
                    state["gamma"][0], state["max_radius"][0],
                    min_intensity=state["min_intensity"][0],
                    scale_override=sc_override,
                )
                # Convert pixel coords → data/scene coords for overlay on signal plot
                sx, ox = sig_ax[0].scale, sig_ax[0].offset
                sy, oy = sig_ax[1].scale, sig_ax[1].offset
                spots = [
                    {"pos": (float(c[0]) * sx + ox, float(c[1]) * sy + oy),
                     "size": max(4, float(intensities[i]) * 14)}
                    for i, c in enumerate(coords_px)
                ]
                state["scatter_item"][0].setData(spots)
            except Exception as e:
                print(f"Refit failed: {e}")

        def _schedule():
            if state["refit_timer"][0] is not None:
                state["refit_timer"][0].start()

        timer.timeout.connect(_do_refit)
        circle_roi.sigRegionChangeFinished.connect(_schedule)

        nav_sel = getattr(plot, "parent_selector", None)
        if nav_sel is not None and hasattr(nav_sel, "roi"):
            nav_sel.roi.sigRegionChangeFinished.connect(_schedule)

        def _on_slider(_v=None):
            state["gamma"][0] = gamma_s.value()
            state["min_intensity"][0] = min_i_s.value()
            _schedule()

        gamma_s.valueChanged.connect(_on_slider)
        min_i_s.valueChanged.connect(_on_slider)
        scale_s.valueChanged.connect(_on_slider)

        _schedule()

    run_btn_w.clicked.connect(lambda: _do_run_fit(state))


def _do_run_fit(state):
    """Execute the full orientation mapping fit (called from submit or run button)."""
    if state["sim"][0] is None:
        if state["run_status"][0] is not None:
            state["run_status"][0].setText("Generate library first.")
        return

    signal = state["signal"]
    main_window = state["main_window"]
    gamma_val = state["gamma"][0]
    sim_val = state["sim"][0]
    nav_axes = list(signal.axes_manager.navigation_axes)
    n_phases = len(state["phases"]) if state["phases"] else 1

    run_btn = state["run_btn"][0]
    run_lbl = state["run_status"][0]
    if run_btn is not None:
        run_btn.setEnabled(False)
    if run_lbl is not None:
        run_lbl.setText("Running…")

    def _do_fit():
        try:
            polar = signal.get_azimuthal_integral2d(
                npt=100, npt_azim=360, inplace=False, mean=True
            )
            polar = polar ** gamma_val
            orientation_map = polar.get_orientation(sim_val, frac_keep=1)
            for i, ax in enumerate(nav_axes):
                if i < orientation_map.axes_manager.navigation_dimension:
                    out_ax = orientation_map.axes_manager.navigation_axes[i]
                    out_ax.scale = ax.scale; out_ax.offset = ax.offset
                    out_ax.units = ax.units; out_ax.name = ax.name
            results = _extract_orientation_outputs(orientation_map, nav_axes, n_phases)
            for result_signal, title in results:
                result_signal.metadata.General.title = title
                main_window._pending_signal_queue.append(result_signal)
            QtCore.QMetaObject.invokeMethod(
                main_window, "_flush_pending_signals",
                QtCore.Qt.ConnectionType.QueuedConnection,
            )
            if run_lbl is not None:
                QtCore.QMetaObject.invokeMethod(
                    run_lbl, "setText",
                    QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(str, "✓ Done"),
                )
        except Exception as e:
            print(f"Orientation mapping failed: {e}")
            if run_lbl is not None:
                QtCore.QMetaObject.invokeMethod(
                    run_lbl, "setText",
                    QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(str, f"Failed: {e}"),
                )
        finally:
            if run_btn is not None:
                QtCore.QMetaObject.invokeMethod(
                    run_btn, "setEnabled",
                    QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(bool, True),
                )

    threading.Thread(target=_do_fit, daemon=True).start()
