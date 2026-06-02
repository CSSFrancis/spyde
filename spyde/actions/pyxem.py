import numpy as np
from typing import Tuple

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


def _compute_reciprocal_radius(signal) -> float:
    """Derive max reciprocal radius from signal axes calibration."""
    sig_axes = signal.axes_manager.signal_axes
    half_extents = [ax.scale * ax.size / 2.0 for ax in sig_axes]
    return min(half_extents)


def orientation_mapping(
    toolbar: RoundedToolBar,
    action_name: str = "Orientation Mapping",
    *args,
    **kwargs,
):
    """5-step wizard for template-matching orientation mapping of 4D-STEM data."""

    plot = toolbar.parent_toolbar.plot
    signal = plot.plot_state.current_signal
    main_window = plot.main_window
    client = main_window.dask_manager.client

    # ── Closure state ──────────────────────────────────────────────────────────
    _phases = []
    _sim = [None]
    _gamma = [0.5]
    _min_intensity = [0.1]
    _scale = [None]
    _max_radius = [_compute_reciprocal_radius(signal)]
    _refit_timer = [None]
    _scatter_item = [None]
    _refine_plot_window = [None]

    # ── Step-gating widget handles ─────────────────────────────────────────────
    _step3_widgets = []
    _step4_widgets = []
    _step5_widgets = []

    def _on_cif_loaded(files):
        """Parse CIF files into orix Phase objects and unlock Step 3."""
        from orix.crystal_map import Phase
        _phases.clear()
        for path in files:
            try:
                phase = Phase.from_cif(path)
                _phases.append(phase)
            except Exception as e:
                print(f"Failed to load CIF {path}: {e}")
        if _phases:
            for w in _step3_widgets:
                w.setEnabled(True)
            label_w = params_caret_box.get_parameter_widget("_phase_list_label")
            if label_w is not None:
                label_w.setText(", ".join(p.name for p in _phases))

    # Placeholder callbacks — filled in later tasks
    def _on_generate_clicked():
        if not _phases:
            print("No phases loaded. Drop a CIF file first.")
            return
        voltage_w = params_caret_box.get_parameter_widget("accelerating_voltage")
        resolution_w = params_caret_box.get_parameter_widget("resolution")
        min_intensity_w = params_caret_box.get_parameter_widget("minimum_intensity")
        voltage       = float((voltage_w.text() if voltage_w else "") or 200.0)
        resolution    = float((resolution_w.text() if resolution_w else "") or 1.0)
        min_intensity = float((min_intensity_w.text() if min_intensity_w else "") or 0.05)
        reciprocal_radius = _compute_reciprocal_radius(signal)
        try:
            _sim[0] = _generate_library_from_phases(
                phases=_phases,
                accelerating_voltage=voltage,
                resolution=resolution,
                minimum_intensity=min_intensity,
                reciprocal_radius=reciprocal_radius,
            )
            for w in _step4_widgets:
                w.setEnabled(True)
        except Exception as e:
            print(f"Library generation failed: {e}")

    def _on_open_refine_clicked():
        pass

    def _on_run_fit_clicked():
        pass

    params = {
        "cif_files": {
            "name": "CIF Files",
            "type": "file_drop",
            "extensions": [".cif"],
        },
        "accelerating_voltage": {
            "name": "Voltage (kV)",
            "type": "float",
            "default": 200.0,
        },
        "_phase_list_label": {
            "name": "Phases",
            "type": "str",
            "default": "(none loaded)",
        },
        "_step2_header": {
            "name": "── Step 2 (optional): Center DP ──",
            "type": "str",
            "default": "",
        },
        "already_centered": {
            "name": "Already Centered",
            "type": "button",
            "label": "✓ Already centered",
            "callback": lambda: None,
        },
        "_step3_header": {
            "name": "── Step 3: Generate Library ──",
            "type": "str",
            "default": "",
        },
        "resolution": {
            "name": "Angle Density (°)",
            "type": "float",
            "default": 1.0,
        },
        "minimum_intensity": {
            "name": "Min Intensity",
            "type": "float",
            "default": 0.05,
        },
        "generate_library_row": {
            "name": "",
            "type": "button_row",
            "buttons": [
                {"key": "generate_btn", "label": "Generate Library",
                 "callback": lambda: _on_generate_clicked()},
            ],
        },
        "_step4_header": {
            "name": "── Step 4: Refine Parameters ──",
            "type": "str",
            "default": "",
        },
        "open_refine_row": {
            "name": "",
            "type": "button_row",
            "buttons": [
                {"key": "open_refine_btn", "label": "Open Refine Preview",
                 "callback": lambda: _on_open_refine_clicked()},
            ],
        },
        "_step5_header": {
            "name": "── Step 5: Run Fit ──",
            "type": "str",
            "default": "",
        },
        "run_fit_row": {
            "name": "",
            "type": "button_row",
            "buttons": [
                {"key": "run_fit_btn", "label": "Run Fit",
                 "callback": lambda: _on_run_fit_clicked()},
            ],
        },
    }

    action, params_caret_box = toolbar.add_action(
        name=action_name,
        icon_path=resolve_icon_path("drawing/toolbars/icons/orientation_mapping.svg"),
        function=lambda *a, **kw: None,
        toggle=True,
        parameters=params,
    )

    # Collect step-gated widgets and disable them
    for key in ["resolution", "minimum_intensity", "generate_btn"]:
        w = params_caret_box.get_parameter_widget(key)
        if w is not None:
            w.setEnabled(False)
            _step3_widgets.append(w)

    for key in ["open_refine_btn"]:
        w = params_caret_box.get_parameter_widget(key)
        if w is not None:
            w.setEnabled(False)
            _step4_widgets.append(w)

    for key in ["run_fit_btn"]:
        w = params_caret_box.get_parameter_widget(key)
        if w is not None:
            w.setEnabled(False)
            _step5_widgets.append(w)

    # Wire CIF drop widget
    cif_widget = params_caret_box.get_parameter_widget("cif_files")
    if cif_widget is not None and hasattr(cif_widget, "filesChanged"):
        cif_widget.filesChanged.connect(_on_cif_loaded)
