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
    client = main_window.dask_manager.client
    gpu_worker = main_window.dask_manager.gpu_worker_address

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
    def _remove_roi():
        """Remove the LineROI from the parent plot when any preview window closes."""
        try:
            toolbar.parent_toolbar.unregister_action_plot_item(
                action_name="Line Profile", key=action_name
            )
        except Exception:
            pass

    if not plot.is_navigator:
        # Signal plot: 1 preview window, Signal1D commit
        preview_window = main_window.add_plot_window(
            is_navigator=False, signal_tree=plot.signal_tree
        )
        preview_window.owner_plot_window = plot.plot_window
        main_window._auto_position_near_owner(preview_window)
        preview_plot = preview_window.add_new_plot()
        if preview_plot.line_item not in preview_plot.items:
            preview_plot.addItem(preview_plot.line_item)
        indicator = ComputeStatusIndicator(color=color)
        preview_window.set_compute_indicator(indicator)

        # Remove the LineROI from the parent plot when the preview window closes.
        _orig_close = preview_window.close_window
        def _close_with_roi_cleanup():
            _remove_roi()
            _orig_close()
        preview_window.close_window = _close_with_roi_cleanup

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
        # ── Navigator plot: 2 preview windows ───────────────────────────────
        # The navigator plot's current_signal is the 2D nav image (no nav dims).
        # Use the signal tree root to get the full N-D signal with nav axes + data.
        full_signal = plot.signal_tree.root

        _cached_line_info = [None]  # (line_ys, line_xs, N, coords)

        # Window 1: instant 1D profile from rendered nav image
        profile_window = main_window.add_plot_window(
            is_navigator=False, signal_tree=plot.signal_tree
        )
        profile_window.owner_plot_window = plot.plot_window
        main_window._auto_position_near_owner(profile_window)
        profile_plot = profile_window.add_new_plot()
        if profile_plot.line_item not in profile_plot.items:
            profile_plot.addItem(profile_plot.line_item)

        _orig_close_profile = profile_window.close_window
        def _close_profile_with_roi_cleanup():
            _remove_roi()
            _orig_close_profile()
        profile_window.close_window = _close_profile_with_roi_cleanup

        toolbar.parent_toolbar.register_action_plot_window(
            action_name="Line Profile", plot_window=profile_window,
            key=action_name + "_profile"
        )

        # Window 2: lazy dask sum of diffraction patterns in strip
        sum_indicator = ComputeStatusIndicator(color=color)
        sum_window = main_window.add_plot_window(
            is_navigator=False, signal_tree=plot.signal_tree
        )
        sum_window.owner_plot_window = plot.plot_window
        main_window._auto_position_near_owner(sum_window)
        sum_plot = sum_window.add_new_plot()
        if sum_plot.image_item not in sum_plot.items:
            sum_plot.addItem(sum_plot.image_item)
        sum_window.set_compute_indicator(sum_indicator)

        _orig_close_sum = sum_window.close_window
        def _close_sum_with_roi_cleanup():
            _remove_roi()
            _orig_close_sum()
        sum_window.close_window = _close_sum_with_roi_cleanup

        toolbar.parent_toolbar.register_action_plot_window(
            action_name="Line Profile", plot_window=sum_window,
            key=action_name + "_sum"
        )

        def _trigger_computation():
            from spyde.drawing.update_functions import compute_nav_line_sum_kernel
            # Instant profile from the rendered nav image (no dask needed)
            image = plot.image_item.image
            if image is not None:
                region = roi.getArrayRegion(image, plot.image_item)
                instant_profile = np.nanmean(region, axis=1)
                profile_plot.current_data = instant_profile
                profile_plot.update()

            # Lazy dask sum for window 2
            _timer_holder.clear()
            # full_signal has navigation dims (ny, nx) for a 4D STEM signal
            nav_shape = (full_signal.axes_manager.navigation_shape[1],
                         full_signal.axes_manager.navigation_shape[0])  # (ny, nx)
            line_ys, line_xs, strip_ys, strip_xs, N, coords = _get_line_nav_coords(
                roi, plot.image_item, nav_shape
            )
            _cached_line_info[0] = (line_ys, line_xs, N, coords)
            future = compute_nav_line_sum_kernel(
                full_signal.data, strip_ys, strip_xs, client, gpu_worker
            )
            sum_plot.current_data = future
            _start_progress_poll(future, sum_indicator, client, _timer_holder)
            sum_window.set_commit_enabled(False)

            def _on_sum_done(fut):
                try:
                    fut.result()
                except Exception:
                    pass
                QtCore.QMetaObject.invokeMethod(
                    sum_window, "set_commit_enabled",
                    QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(bool, True),
                )

            future.add_done_callback(_on_sum_done)

        def _on_roi_finished(_roi=None):
            if not _live_enabled[0]:
                return
            _trigger_computation()

        roi.sigRegionChangeFinished.connect(_on_roi_finished)

        def _do_commit_nav():
            import hyperspy.api as hs
            if _cached_line_info[0] is None:
                return
            line_ys, line_xs, N, coords = _cached_line_info[0]
            sum_window.set_commit_enabled(False)

            # Get current width from caret box
            width_widget = params_caret_box.get_parameter_widget("width")
            try:
                width_val = int(width_widget.text()) if width_widget else 1
            except (ValueError, TypeError):
                width_val = 1

            nav_shape = (full_signal.axes_manager.navigation_shape[1],
                         full_signal.axes_manager.navigation_shape[0])  # (ny, nx)

            # Build lazy stack: one diffraction pattern per line point
            slices = []
            for i in range(N):
                if width_val <= 1:
                    yi = int(np.clip(line_ys[i], 0, nav_shape[0] - 1))
                    xi = int(np.clip(line_xs[i], 0, nav_shape[1] - 1))
                    slices.append(full_signal.data[yi, xi])
                else:
                    col_xs = np.clip(
                        np.round(coords[0, i, :]).astype(int), 0, nav_shape[1] - 1
                    )
                    col_ys = np.clip(
                        np.round(coords[1, i, :]).astype(int), 0, nav_shape[0] - 1
                    )
                    # Dask does not support N-D fancy indexing; stack patterns
                    # individually and take the mean.
                    col_pats = da.stack(
                        [full_signal.data[int(ry), int(rx)]
                         for ry, rx in zip(col_ys, col_xs)],
                        axis=0,
                    )
                    slices.append(da.mean(col_pats, axis=0))

            result_lazy = da.stack(slices, axis=0)  # (N, nkx, nky)
            future = client.compute(result_lazy)

            def _on_done(fut):
                try:
                    arr = fut.result()
                except Exception as e:
                    print(f"Line profile commit failed: {e}")
                    QtCore.QMetaObject.invokeMethod(
                        sum_window, "set_commit_enabled",
                        QtCore.Qt.ConnectionType.QueuedConnection,
                        QtCore.Q_ARG(bool, True),
                    )
                    return
                committed_sig = hs.signals.Signal2D(arr)
                # Nav axis: position along line; use source nav pixel scale
                src_nav_ax = full_signal.axes_manager.navigation_axes[0]
                committed_sig.axes_manager.navigation_axes[0].scale = abs(src_nav_ax.scale)
                committed_sig.axes_manager.navigation_axes[0].units = src_nav_ax.units
                committed_sig.axes_manager.navigation_axes[0].name = "line position"
                # Signal axes: copy from source
                for i, ax in enumerate(full_signal.axes_manager.signal_axes):
                    committed_sig.axes_manager.signal_axes[i].scale = ax.scale
                    committed_sig.axes_manager.signal_axes[i].offset = ax.offset
                    committed_sig.axes_manager.signal_axes[i].units = ax.units
                    committed_sig.axes_manager.signal_axes[i].name = ax.name
                main_window._pending_signal_queue.append(committed_sig)
                QtCore.QMetaObject.invokeMethod(
                    main_window, "_flush_pending_signals",
                    QtCore.Qt.ConnectionType.QueuedConnection,
                )
                QtCore.QMetaObject.invokeMethod(
                    sum_window, "set_commit_enabled",
                    QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(bool, True),
                )

            future.add_done_callback(_on_done)

        sum_window.set_commit_fn(_do_commit_nav)

    def _toggle_live():
        live_btn = params_caret_box.get_parameter_widget("live_button")
        _live_enabled[0] = not _live_enabled[0]
        if live_btn is not None:
            live_btn.setText("Live (ON)" if _live_enabled[0] else "Live (OFF)")
