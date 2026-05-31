"""Line profile action for any 2D plot.

Two cases:
- Signal plot (is_navigator=False): LineROI on the image → 1D profile → Signal1D commit
- Navigator plot (is_navigator=True): two previews (implemented in Task 7)
"""
import math
import numpy as np
import dask.array as da

import pyqtgraph as pg
from pyqtgraph import mkPen
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtCore import Qt
from PySide6 import QtCore

from spyde.drawing.toolbars.toolbar import RoundedToolBar
from spyde.drawing.toolbars.plot_control_toolbar import resolve_icon_path
from spyde.actions.pyxem import _start_progress_poll


COLORS = ["red", "green", "blue", "yellow", "cyan", "magenta"]


def line_profile_action(*args, **kwargs):
    """Placeholder for the Line Profile toolbar toggle."""
    pass


def _make_pen_and_icon(toolbar):
    """Return (color_str, pen, QIcon) cycling through COLORS based on action count."""
    num = toolbar.num_actions()
    color = COLORS[num % len(COLORS)]
    pen = mkPen(color=color, width=3)
    icon_path = resolve_icon_path("drawing/toolbars/icons/virtual_imaging.svg")
    base_icon = QIcon(icon_path)
    icon_size = toolbar.iconSize()
    dpr = getattr(toolbar, "devicePixelRatioF", lambda: 1.0)()
    req_w = max(1, int(icon_size.width() * dpr))
    req_h = max(1, int(icon_size.height() * dpr))
    base_pixmap = base_icon.pixmap(req_w, req_h)
    colored = QPixmap(base_pixmap.size())
    colored.setDevicePixelRatio(dpr)
    colored.fill(Qt.GlobalColor.transparent)
    p = QPainter(colored)
    p.drawPixmap(0, 0, base_pixmap)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(colored.rect(), QColor(color))
    p.end()
    icon = QIcon()
    icon.addPixmap(colored)
    return color, pen, icon


def _get_line_nav_coords(roi, image_item, nav_shape):
    """Extract pixel coords along the line centre and all strip pixels.

    Parameters
    ----------
    roi : pyqtgraph.LineROI
    image_item : pyqtgraph.ImageItem
    nav_shape : tuple (ny, nx) — shape of the navigation image

    Returns
    -------
    line_ys : np.ndarray shape (N,)  — row indices of the N line-centre points
    line_xs : np.ndarray shape (N,)  — col indices of the N line-centre points
    strip_ys : np.ndarray shape (M,) — all row indices inside the full strip
    strip_xs : np.ndarray shape (M,) — all col indices inside the full strip
    N : int                          — number of points along the line
    coords : np.ndarray shape (2, N, W) — raw coords for per-column slicing
    """
    dummy = np.zeros(nav_shape, dtype=np.float32)
    _, coords = roi.getArrayRegion(dummy, image_item, returnMappedCoords=True)
    # coords shape: (2, length_px, width_px)
    # coords[0] = x (column) indices, coords[1] = y (row) indices
    mid_w = coords.shape[2] // 2
    line_xs = np.clip(np.round(coords[0, :, mid_w]).astype(int), 0, nav_shape[1] - 1)
    line_ys = np.clip(np.round(coords[1, :, mid_w]).astype(int), 0, nav_shape[0] - 1)
    strip_xs = np.clip(np.round(coords[0]).astype(int).ravel(), 0, nav_shape[1] - 1)
    strip_ys = np.clip(np.round(coords[1]).astype(int).ravel(), 0, nav_shape[0] - 1)
    N = line_ys.shape[0]
    return line_ys, line_xs, strip_ys, strip_xs, N, coords


def add_line_profile(
    toolbar: RoundedToolBar,
    action_name: str = "Add Line Profile",
    *args,
    **kwargs,
):
    """Add a LineROI to the current 2D plot and wire live preview + title-bar commit."""
    from spyde.qt.compute_status_indicator import ComputeStatusIndicator

    color, pen, icon = _make_pen_and_icon(toolbar)
    action_name = f"Line Profile ({color})"

    plot = toolbar.parent_toolbar.plot
    signal = plot.plot_state.current_signal
    main_window = plot.main_window
    client = main_window.client
    gpu_worker = getattr(main_window, "_gpu_worker_address", None)

    _live_enabled = [True]
    _timer_holder = []
    _cached_profile = [None]  # last computed 1D profile (numpy array)

    def _on_compute_clicked():
        _trigger_computation()

    params = {
        "width": {
            "name": "Width (px)",
            "type": "int",
            "default": 1,
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
        function=line_profile_action,
        toggle=True,
        parameters=params,
    )
    try:
        if hasattr(params_caret_box, "finalize_layout"):
            params_caret_box.finalize_layout()
    except Exception:
        pass

    # ── Place LineROI ────────────────────────────────────────────────────────
    img_item = plot.image_item
    transform = img_item.transform()
    img_w = img_item.width()
    img_h = img_item.height()
    center = transform.map(QtCore.QPointF(img_w / 2, img_h / 2))
    cx, cy = center.x(), center.y()
    if signal is not None and signal.axes_manager.signal_axes:
        ax0 = signal.axes_manager.signal_axes[1]  # x-axis (columns)
        data_width = ax0.size * abs(ax0.scale)
    else:
        data_width = img_w
    half_len = data_width * 0.3
    pos1 = [cx - half_len, cy]
    pos2 = [cx + half_len, cy]
    roi = pg.LineROI(pos1, pos2, width=1, pen=pen)
    toolbar.parent_toolbar.register_action_plot_item(
        action_name="Line Profile", item=roi, key=action_name
    )

    # ── Branch: signal plot vs navigator plot ────────────────────────────────
    if not plot.is_navigator:
        # Signal plot: 1 preview window, Signal1D commit
        preview_window = main_window.add_plot_window(is_navigator=False, signal_tree=None)
        preview_plot = preview_window.add_new_plot()
        if preview_plot.line_item not in preview_plot.items:
            preview_plot.addItem(preview_plot.line_item)
        indicator = ComputeStatusIndicator(color=color)
        preview_window.set_compute_indicator(indicator)
        toolbar.parent_toolbar.register_action_plot_window(
            action_name="Line Profile", plot_window=preview_window, key=action_name
        )

        def _trigger_computation():
            from spyde.drawing.update_functions import compute_line_profile_kernel
            image = plot.image_item.image
            if image is None:
                return
            _timer_holder.clear()
            future = compute_line_profile_kernel(image, roi, plot.image_item, client)
            preview_plot.current_data = future
            _start_progress_poll(future, indicator, client, _timer_holder)
            preview_window.set_commit_enabled(False)

            def _on_done(fut):
                try:
                    result = fut.result()
                    _cached_profile[0] = result
                except Exception:
                    pass
                QtCore.QMetaObject.invokeMethod(
                    preview_window, "set_commit_enabled",
                    QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(bool, True),
                )

            future.add_done_callback(_on_done)

        def _on_roi_finished(_roi=None):
            if not _live_enabled[0]:
                return
            _trigger_computation()

        roi.sigRegionChangeFinished.connect(_on_roi_finished)

        def _do_commit_signal():
            import hyperspy.api as hs
            profile = _cached_profile[0]
            if profile is None:
                return
            preview_window.set_commit_enabled(False)
            sig = hs.signals.Signal1D(profile.copy())
            handles = roi.getHandles()
            p1 = roi.mapToParent(handles[0].pos())
            p2 = roi.mapToParent(handles[1].pos())
            line_len = math.sqrt((p2.x() - p1.x())**2 + (p2.y() - p1.y())**2)
            n_points = len(profile)
            sig.axes_manager.signal_axes[0].scale = line_len / n_points if n_points > 0 else 1.0
            if signal is not None and signal.axes_manager.signal_axes:
                sig.axes_manager.signal_axes[0].units = signal.axes_manager.signal_axes[0].units
            main_window._pending_signal_queue.append(sig)
            QtCore.QMetaObject.invokeMethod(
                main_window, "_flush_pending_signals",
                QtCore.Qt.ConnectionType.QueuedConnection,
            )
            QtCore.QMetaObject.invokeMethod(
                preview_window, "set_commit_enabled",
                QtCore.Qt.ConnectionType.QueuedConnection,
                QtCore.Q_ARG(bool, True),
            )

        preview_window.set_commit_fn(_do_commit_signal)

    else:
        # Navigator plot case — will be implemented in Task 7
        # For now, raise to make Task 7 tests fail clearly
        raise NotImplementedError("Navigator-plot line profile not yet implemented")

    def _toggle_live():
        live_btn = params_caret_box.get_parameter_widget("live_button")
        _live_enabled[0] = not _live_enabled[0]
        if live_btn is not None:
            live_btn.setText("Live (ON)" if _live_enabled[0] else "Live (OFF)")
