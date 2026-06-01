import numpy as np
from typing import Tuple

from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtCore import Qt
from pyqtgraph import RectROI, CircleROI, mkPen

from spyde.drawing.toolbars.toolbar import RoundedToolBar
from spyde.drawing.toolbars.plot_control_toolbar import resolve_icon_path
from spyde.external.pyqtgraph.ring_roi import RingROI


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

    # Mutable state captured in closures
    _live_enabled = [True]
    _cached_mask = [None]
    _cached_roi = [None]  # ROI that produced _cached_mask — kept in sync
    _timer_holder = []  # keeps QTimer refs alive
    _generation = [0]  # monotonically incremented each time a new computation starts;
                       # the done-callback checks its captured generation matches to
                       # avoid id()-reuse false positives from Python GC.

    action_name = f"Virtual Image ({color})"

    def _on_compute_clicked():
        _trigger_computation()

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
        # commit_button REMOVED — now lives in the PlotWindow title bar
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

    # Create the virtual image preview PlotWindow using the same factory as all other
    # plot windows — this applies FramelessWindowHint and removes the Qt border.
    from spyde.qt.compute_status_indicator import ComputeStatusIndicator

    virtual_plot_window = main_window.add_plot_window(
        is_navigator=False,
        signal_tree=plot.signal_tree,
    )
    virtual_plot_window.owner_plot_window = plot.plot_window
    main_window._auto_position_near_owner(virtual_plot_window)
    virtual_plot = virtual_plot_window.add_new_plot()
    # Add image_item to the scene so update() can render into it.
    # Normally set_plot_state() does this, but the virtual preview has no PlotState.
    if virtual_plot.image_item not in virtual_plot.items:
        virtual_plot.addItem(virtual_plot.image_item)

    indicator = ComputeStatusIndicator(color=color)
    virtual_plot_window.set_compute_indicator(indicator)

    # Register plot window with the parent toolbar so visibility toggles with "Virtual Imaging"
    toolbar.parent_toolbar.register_action_plot_window(
        action_name="Virtual Imaging",
        plot_window=virtual_plot_window,
        key=action_name,
    )

    # Build the ROI
    center, inner_rad, outer_rad = plot.get_annular_roi_parameters()
    if params_caret_box.kwargs["type"].currentText() == "annular":
        roi = RingROI(center=center, inner_rad=inner_rad, outer_rad=outer_rad, pen=pen)
    elif params_caret_box.kwargs["type"].currentText() == "disk":
        roi = CircleROI(center, inner_rad, pen=pen)
    else:
        roi = RectROI(center, inner_rad, pen=pen)

    toolbar.parent_toolbar.register_action_plot_item(
        action_name="Virtual Imaging", item=roi, key=action_name
    )

    def arrange_widgets_on_move():
        rois = list(
            toolbar.parent_toolbar.action_widgets["Virtual Imaging"]["plot_items"].values()
        )
        sizes = [r.size().x() for r in rois]
        sorted_index = np.argsort(sizes)
        for i, idx in enumerate(sorted_index[::-1]):
            r = rois[idx]
            r.setZValue(10 + i)

    roi.sigRegionChangeFinished.connect(arrange_widgets_on_move)

    def _trigger_computation(_roi=None):
        if _roi is None:
            _roi = roi
        from spyde.drawing.update_functions import compute_virtual_image_kernel
        _timer_holder.clear()
        mask = roi_to_mask(_roi, signal)
        _cached_mask[0] = mask
        _cached_roi[0] = _roi

        _generation[0] += 1
        my_generation = _generation[0]

        future = compute_virtual_image_kernel(signal.data, mask, client, gpu_worker)
        virtual_plot.current_data = future
        _start_progress_poll(future, indicator, client, _timer_holder)
        virtual_plot_window.set_commit_enabled(False)

        def _on_preview_done(fut):
            from PySide6 import QtCore as _QtCore
            # Only enable Commit if this is still the latest computation.
            # Generation counter avoids id()-reuse false positives from Python GC
            # (GC can reuse freed future addresses, making id(old) == id(new)).
            if _generation[0] != my_generation:
                return
            _QtCore.QMetaObject.invokeMethod(
                virtual_plot_window, "set_commit_enabled",
                _QtCore.Qt.ConnectionType.QueuedConnection,
                _QtCore.Q_ARG(bool, True),
            )

        future.add_done_callback(_on_preview_done)

    def _on_roi_finished(_roi=None):
        if not _live_enabled[0]:
            return
        _trigger_computation(_roi)

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
        toolbar.parent_toolbar.register_action_plot_item(
            action_name="Virtual Imaging", item=roi, key=action_name
        )
        roi.sigRegionChangeFinished.connect(arrange_widgets_on_move)
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
