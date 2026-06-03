import threading
import numpy as np
from typing import Tuple, List, Optional

from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtCore import Qt
import pyqtgraph as pg
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


_CZB_BUILT_TOOLBARS: set = set()


def center_zero_beam_setup(
    toolbar: RoundedToolBar,
    action_name: str = "Center Zero Beam",
    *args,
    **kwargs,
):
    """
    Augment the YAML-created CaretParams with a Manual tab on first toggle.

    The CaretParams (with its RectangleSelector ROI) is created at PlotState
    init time from the YAML parameters.  This function, called on first trigger,
    adds a Manual tab to it and wires the map window show/hide logic.
    """
    tid = id(toolbar)
    if tid in _CZB_BUILT_TOOLBARS:
        return
    _CZB_BUILT_TOOLBARS.add(tid)

    caret_params = toolbar.action_widgets.get(action_name, {}).get("widget")
    if caret_params is None:
        return

    main_window = toolbar.plot.main_window
    manual_state = {"map_window": [None], "toolbar_ref": toolbar}

    def _on_czb_tab_changed(idx):
        mw = manual_state["map_window"][0]
        if idx == 1:  # Manual tab selected
            if mw is None:
                mw = _czb_create_map_window(toolbar, manual_state, main_window)
            mw.show()
            _czb_install_click_hook(toolbar, manual_state)
        else:
            if mw is not None:
                mw.hide()
            _czb_remove_click_hook(manual_state)

    manual_page = _czb_build_manual_page(caret_params, toolbar, manual_state, 220)
    caret_params.add_extra_tab("Manual", manual_page, on_tab_changed=_on_czb_tab_changed)

    # Store state on toolbar to prevent GC
    toolbar._czb_state = manual_state

    # Wire action toggle: hide map window when the action is closed
    action = toolbar._find_action(action_name)
    if action is not None:
        action.toggled.connect(
            lambda checked: _czb_on_action_toggled(checked, manual_state)
        )

    # Reposition after Qt has processed the resize from finalize_layout.
    pos_fn = toolbar.action_widgets.get(action_name, {}).get("position_fn")
    if pos_fn is not None:
        QtCore.QTimer.singleShot(0, pos_fn)


def _czb_on_action_toggled(checked: bool, manual_state: dict):
    """When the action is closed, hide the map window and remove the click hook."""
    if not checked:
        mw = manual_state["map_window"][0]
        if mw is not None:
            mw.hide()
        _czb_remove_click_hook(manual_state)


def _czb_create_map_window(toolbar, manual_state, main_window):
    """Create the floating X-shift / Y-shift map using a styled PlotWindow."""
    import pyqtgraph as _pg
    from spyde.drawing.plots.plot_window import PlotWindow
    from PySide6.QtCore import Qt as _Qt

    pw = PlotWindow(main_window=main_window)
    pw.setWindowTitle("Manual Beam Centers")
    side = main_window.screen_size.height() // 6  # half the default plot height
    pw.resize(side * 2, side)
    main_window.mdi_area.addSubWindow(pw)
    try:
        pw.setWindowFlags(pw.windowFlags() | _Qt.WindowType.FramelessWindowHint)
        pw.setStyleSheet("QMdiSubWindow { border: none; }")
    except Exception:
        pass

    glw = pw.plot_widget

    x_plot = glw.addPlot(row=0, col=0, title="X Shift (px)")
    x_plot.setAspectLocked(True)
    x_img = _pg.ImageItem(colorMap="CET-D1")
    x_plot.addItem(x_img)
    x_scatter = _pg.ScatterPlotItem(
        size=10, symbol="+",
        pen=_pg.mkPen("y", width=2), brush=_pg.mkBrush(None)
    )
    x_scatter.setZValue(10)
    x_plot.addItem(x_scatter)
    x_plot.getViewBox().setMenuEnabled(False)

    y_plot = glw.addPlot(row=0, col=1, title="Y Shift (px)")
    y_plot.setAspectLocked(True)
    y_img = _pg.ImageItem(colorMap="CET-D1")
    y_plot.addItem(y_img)
    y_scatter = _pg.ScatterPlotItem(
        size=10, symbol="+",
        pen=_pg.mkPen("y", width=2), brush=_pg.mkBrush(None)
    )
    y_scatter.setZValue(10)
    y_plot.addItem(y_scatter)
    y_plot.getViewBox().setMenuEnabled(False)

    x_scatter.sigClicked.connect(
        lambda sc, pts: _czb_on_scatter_clicked(pts, manual_state)
    )
    y_scatter.sigClicked.connect(
        lambda sc, pts: _czb_on_scatter_clicked(pts, manual_state)
    )

    manual_state["x_img"] = x_img
    manual_state["y_img"] = y_img
    manual_state["x_scatter"] = x_scatter
    manual_state["y_scatter"] = y_scatter

    # Install Delete key filter on the map window's graphics viewport
    class _MapKeyFilter(QtCore.QObject):
        def eventFilter(self, obj, event):
            if event.type() == QtCore.QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_Delete:
                    fn = manual_state.get("delete_fn")
                    if fn:
                        fn()
                    return True
            return False

    key_filt = _MapKeyFilter(pw)
    # Install on the plot_widget viewport so it catches keys when the map has focus
    glw.viewport().installEventFilter(key_filt)
    manual_state["map_key_filter"] = key_filt

    pw.show()
    manual_state["map_window"][0] = pw
    # Draw any points already recorded before the map window was opened
    _czb_refresh(toolbar, manual_state)
    return pw


class _ShiftClickViewFilter(QtCore.QObject):
    """
    Event filter installed on the QGraphicsView that owns the signal plot.

    Intercepts Shift+Left click (MouseButtonPress with ShiftModifier) before
    pyqtgraph processes it, so ROIs and other items cannot consume it first.
    Returns True to consume the event so pyqtgraph does not also act on it.
    """

    def __init__(self, view, callback, parent=None):
        super().__init__(parent)
        self._view = view
        self._callback = callback

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Type.MouseButtonPress:
            if (event.button() == Qt.MouseButton.LeftButton and
                    event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                # event.pos() is in viewport coordinates; map to scene.
                scene_pos = self._view.mapToScene(event.position().toPoint())
                self._callback(scene_pos)
                return True  # consume — prevent pyqtgraph from panning/selecting
        return False


def _czb_install_click_hook(toolbar, manual_state):
    """Install viewport event filter for Shift+click and wire navigator-change crosshair."""
    _czb_remove_click_hook(manual_state)
    plot = toolbar.plot
    if plot is None:
        return

    scene = plot.vb.scene() if plot.vb is not None else None
    if scene is None:
        return
    views = scene.views()
    if not views:
        return
    view = views[0]
    viewport = view.viewport()

    def _on_shift_click(scene_pos):
        vb = plot.vb
        view_pos = vb.mapSceneToView(scene_pos)
        img_transform, ok = plot.image_item.transform().inverted()
        if not ok:
            return
        local_pos = img_transform.map(view_pos)
        cx_px = local_pos.x()
        cy_px = local_pos.y()

        nav_idx = _czb_get_nav_indices(plot)
        if nav_idx is None:
            return
        nav_x, nav_y = nav_idx

        # Replace existing point at this nav position, or append a new one.
        pts = manual_state.get("control_points", [])
        for i, (nx, ny, *_) in enumerate(pts):
            if nx == nav_x and ny == nav_y:
                pts[i] = (nav_x, nav_y, cx_px, cy_px)
                break
        else:
            pts.append((nav_x, nav_y, cx_px, cy_px))
        manual_state["control_points"] = pts
        manual_state["selected_idx"] = None
        _czb_update_signal_crosshair(plot, manual_state)
        _czb_refresh(toolbar, manual_state)

    filt = _ShiftClickViewFilter(view, _on_shift_click)
    viewport.installEventFilter(filt)
    manual_state["click_filter"] = filt
    manual_state["click_view"] = viewport

    # Wire axes_manager indices_changed — only once per signal.
    # _czb_remove_click_hook disconnects the old handler before we reconnect.
    signal = plot.plot_state.current_signal if plot.plot_state else None
    if signal is not None and manual_state.get("nav_signal") is not signal:
        def _on_nav_changed():
            _czb_update_signal_crosshair(plot, manual_state)
            current_nav = _czb_get_nav_indices(plot)
            _czb_refresh_scatter(manual_state, current_nav)

        signal.axes_manager.events.indices_changed.connect(_on_nav_changed, kwargs=[])
        manual_state["nav_handler"] = _on_nav_changed
        manual_state["nav_signal"] = signal

    # Show crosshair for current position immediately
    _czb_update_signal_crosshair(plot, manual_state)


def _czb_remove_click_hook(manual_state):
    filt = manual_state.get("click_filter")
    viewport = manual_state.get("click_view")
    if filt is not None and viewport is not None:
        try:
            viewport.removeEventFilter(filt)
        except Exception:
            pass
    manual_state["click_filter"] = None
    manual_state["click_view"] = None

    # Disconnect navigator change handler
    handler = manual_state.get("nav_handler")
    nav_signal = manual_state.get("nav_signal")
    if handler is not None and nav_signal is not None:
        try:
            nav_signal.axes_manager.events.indices_changed.disconnect(handler)
        except Exception:
            pass
    manual_state["nav_handler"] = None
    manual_state["nav_signal"] = None

    # Remove signal-plot crosshair
    _czb_remove_signal_crosshair(manual_state)


def _czb_update_signal_crosshair(plot, manual_state):
    """
    Remove any existing crosshair lines, then place fresh draggable InfiniteLine
    crosshairs if the current navigator position has a recorded control point.

    Two InfiniteLine objects (H + V) are used instead of CrosshairROI because
    InfiniteLine is always visible regardless of zoom level and is always centered
    on the specified position.
    """
    import pyqtgraph as _pg

    _czb_remove_signal_crosshair(manual_state)

    nav_idx = _czb_get_nav_indices(plot)
    if nav_idx is None:
        return

    nav_x, nav_y = nav_idx

    cx_px, cy_px = None, None
    for nx, ny, cx, cy in manual_state.get("control_points", []):
        if nx == nav_x and ny == nav_y:
            cx_px, cy_px = cx, cy
            break

    if cx_px is None:
        return

    # Map image pixel coords → scene/data coords via image_item transform.
    img_transform = plot.image_item.transform()
    data_pos = img_transform.map(QtCore.QPointF(cx_px, cy_px))
    dx, dy = data_pos.x(), data_pos.y()

    pen = _pg.mkPen("y", width=2)
    h_line = _pg.InfiniteLine(pos=dy, angle=0, pen=pen, movable=True)
    v_line = _pg.InfiniteLine(pos=dx, angle=90, pen=pen, movable=True)
    plot.addItem(h_line)
    plot.addItem(v_line)
    manual_state["signal_crosshair"] = (h_line, v_line)

    bound_nav_x, bound_nav_y = nav_x, nav_y

    def _on_line_moved():
        if manual_state.get("signal_crosshair") is not (h_line, v_line):
            return
        # Current intersection in data coords
        cur_dx = v_line.value()
        cur_dy = h_line.value()
        inv, ok = plot.image_item.transform().inverted()
        if not ok:
            return
        px_pos = inv.map(QtCore.QPointF(cur_dx, cur_dy))
        pts = manual_state.get("control_points", [])
        for i, (nx, ny, *_) in enumerate(pts):
            if nx == bound_nav_x and ny == bound_nav_y:
                pts[i] = (nx, ny, px_pos.x(), px_pos.y())
                break
        _czb_refresh(manual_state["toolbar_ref"], manual_state)

    h_line.sigPositionChanged.connect(_on_line_moved)
    v_line.sigPositionChanged.connect(_on_line_moved)


def _czb_remove_signal_crosshair(manual_state):
    crosshair = manual_state.get("signal_crosshair")
    plot = manual_state.get("toolbar_ref").plot if manual_state.get("toolbar_ref") else None
    if crosshair is not None and plot is not None:
        h_line, v_line = crosshair
        for line in (h_line, v_line):
            try:
                plot.removeItem(line)
            except Exception:
                pass
    manual_state["signal_crosshair"] = None


def _czb_get_nav_indices(plot) -> Optional[tuple]:
    """Return (nav_x_idx, nav_y_idx) from the navigator crosshair selector.

    axes_manager.indices is NOT updated by navigator crosshair movement in SpyDE —
    the selector owns the current position. We read it from the signal_tree's
    navigator_plot_manager selectors.
    """
    if plot is None:
        return None
    signal_tree = getattr(plot, "signal_tree", None)
    if signal_tree is None:
        return None
    npm = getattr(signal_tree, "navigator_plot_manager", None)
    if npm is None:
        return None
    selectors = npm.all_navigation_selectors
    if not selectors:
        return None

    def _read_indices(sel):
        """Extract current_indices from a selector, handling IntegratingSelector2D."""
        # IntegratingSelector2D wraps a CrosshairSelector
        inner = getattr(sel, "_crosshair_selector", None)
        if inner is not None:
            return getattr(inner, "current_indices", None)
        return getattr(sel, "current_indices", None)

    for sel in reversed(selectors):
        indices = _read_indices(sel)
        if indices is None:
            continue
        flat = np.asarray(indices).flatten()
        if len(flat) >= 2:
            return (int(flat[0]), int(flat[1]))
        if len(flat) == 1:
            return (int(flat[0]), 0)
    return None


def _czb_on_scatter_clicked(points, manual_state):
    if not points:
        manual_state["selected_idx"] = None
    else:
        pos = points[0].pos()
        px, py = pos.x(), pos.y()
        for i, (nx, ny, *_) in enumerate(manual_state.get("control_points", [])):
            if abs(nx - px) < 0.5 and abs(ny - py) < 0.5:
                manual_state["selected_idx"] = i
                break
    _czb_refresh_scatter(manual_state)


def _czb_fit_plane(control_points, nav_shape):
    nav_y_size, nav_x_size = nav_shape
    ys, xs = np.mgrid[0:nav_y_size, 0:nav_x_size]
    if not control_points:
        return np.zeros(nav_shape), np.zeros(nav_shape)
    pts = np.array(control_points)
    nx, ny, cx, cy = pts[:, 0], pts[:, 1], pts[:, 2], pts[:, 3]
    A = np.column_stack([nx, ny, np.ones(len(nx))])
    ax, *_ = np.linalg.lstsq(A, cx, rcond=None)
    ay, *_ = np.linalg.lstsq(A, cy, rcond=None)
    x_plane = ax[0] * xs + ax[1] * ys + ax[2]
    y_plane = ay[0] * xs + ay[1] * ys + ay[2]
    return x_plane, y_plane


def _czb_refresh(toolbar, manual_state):
    count_lbl = manual_state.get("count_label")
    if count_lbl is not None:
        count_lbl.setText(f"Points: {len(manual_state.get('control_points', []))}")

    x_img = manual_state.get("x_img")
    y_img = manual_state.get("y_img")
    if x_img is None or y_img is None:
        return

    plot = toolbar.plot
    if plot is None or plot.plot_state is None:
        return
    signal = plot.plot_state.current_signal
    if signal is None:
        return
    nav_axes = signal.axes_manager.navigation_axes
    if len(nav_axes) < 2:
        return
    nav_shape = (nav_axes[1].size, nav_axes[0].size)
    x_plane, y_plane = _czb_fit_plane(manual_state.get("control_points", []), nav_shape)
    x_img.setImage(x_plane.T, autoLevels=True)
    y_img.setImage(y_plane.T, autoLevels=True)
    current_nav = _czb_get_nav_indices(plot)
    _czb_refresh_scatter(manual_state, current_nav)


def _czb_refresh_scatter(manual_state, current_nav=None):
    """Redraw scatter dots on both maps. Yellow = control point, cyan = current nav position."""
    x_scatter = manual_state.get("x_scatter")
    y_scatter = manual_state.get("y_scatter")
    if x_scatter is None:
        return
    pts = manual_state.get("control_points", [])
    if not pts:
        x_scatter.setData([], [])
        y_scatter.setData([], [])
        return
    import pyqtgraph as _pg
    arr = np.array(pts)
    nx, ny = arr[:, 0], arr[:, 1]
    brushes = []
    for i, (px, py, *_) in enumerate(pts):
        if current_nav is not None and px == current_nav[0] and py == current_nav[1]:
            brushes.append(_pg.mkBrush("c"))   # cyan = current position
        else:
            brushes.append(_pg.mkBrush("y"))   # yellow = other control point
    x_scatter.setData(x=nx, y=ny, brush=brushes)
    y_scatter.setData(x=nx, y=ny, brush=brushes)


def _czb_build_manual_page(caret, toolbar, manual_state, width):
    """Build the Manual tab page widget."""
    manual_state.setdefault("control_points", [])
    manual_state.setdefault("selected_idx", None)

    page = QtWidgets.QWidget(caret)
    page.setFixedWidth(width)
    vlay = QtWidgets.QVBoxLayout(page)
    vlay.setContentsMargins(4, 4, 4, 4)
    vlay.setSpacing(4)

    info = QtWidgets.QLabel(
        "Shift+click on the diffraction pattern\n"
        "to record the beam center at the current\n"
        "navigator position.\n"
        "Click a point on the map, then click\n"
        "'Delete Selected' to remove it."
    )
    info.setStyleSheet("color: white; font-size: 10px;")
    info.setWordWrap(True)
    vlay.addWidget(info)

    count_lbl = QtWidgets.QLabel("Points: 0")
    count_lbl.setStyleSheet("color: white; font-size: 10px;")
    vlay.addWidget(count_lbl)
    manual_state["count_label"] = count_lbl

    def _delete_selected():
        idx = manual_state.get("selected_idx")
        pts = manual_state.get("control_points", [])
        if idx is not None and 0 <= idx < len(pts):
            pts.pop(idx)
            manual_state["selected_idx"] = None
            _czb_refresh(toolbar, manual_state)

    delete_btn = QtWidgets.QPushButton("Delete Selected")
    delete_btn.setStyleSheet(
        "QPushButton { color: white; background: rgba(255,255,255,30); border: 1px solid black; }"
    )
    delete_btn.clicked.connect(_delete_selected)
    vlay.addWidget(delete_btn)

    clear_btn = QtWidgets.QPushButton("Clear All Points")
    clear_btn.setStyleSheet(
        "QPushButton { color: white; background: rgba(255,255,255,30); border: 1px solid black; }"
    )

    def _clear():
        manual_state["control_points"] = []
        manual_state["selected_idx"] = None
        _czb_refresh(toolbar, manual_state)

    clear_btn.clicked.connect(_clear)
    vlay.addWidget(clear_btn)

    submit_btn = QtWidgets.QPushButton("Submit")
    submit_btn.setStyleSheet(
        "QPushButton { color: white; background: rgba(255,255,255,30); border: 1px solid black; }"
    )
    submit_btn.clicked.connect(lambda: _czb_submit(toolbar, manual_state))
    vlay.addWidget(submit_btn)

    # Store delete function so it can also be triggered from a key filter on the map viewport
    manual_state["delete_fn"] = _delete_selected

    return page


def _czb_submit(toolbar, manual_state):
    pts = manual_state.get("control_points", [])
    if not pts:
        print("No control points defined; nothing to apply.")
        return
    import hyperspy.api as hs
    signal = toolbar.plot.plot_state.current_signal
    if signal is None:
        return
    signal.set_signal_type("electron_diffraction")
    nav_axes = signal.axes_manager.navigation_axes
    nav_shape = (nav_axes[1].size, nav_axes[0].size)
    x_plane, y_plane = _czb_fit_plane(pts, nav_shape)
    data = np.stack([x_plane, y_plane], axis=-1)
    shifts = hs.signals.Signal1D(data)
    for i, ax in enumerate(nav_axes):
        out_ax = shifts.axes_manager.navigation_axes[i]
        out_ax.scale = ax.scale
        out_ax.offset = ax.offset
        out_ax.units = ax.units
        out_ax.name = ax.name
    new_signal = toolbar.plot.signal_tree.add_transformation(
        parent_signal=signal,
        node_name="Centered (Manual)",
        method="center_direct_beam",
        shifts=shifts,
        inplace=False,
    )
    new_signal.calibration.center = None
    toolbar.plot.set_plot_state(new_signal)


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
    print("Virtual imaging action triggered.")


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

    OrientationMap.data has shape (nav..., n_best, 4) with column_names
    ['index', 'correlation', 'rotation', 'factor'].  Best match = n_best index 0.

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

    # Orientation map itself (contains IPF + crystal map info)
    results.append((orientation_map, "Orientation Map"))

    # Extract best-match correlation (column index 1) at n_best=0
    try:
        col_names = getattr(orientation_map, "column_names", [])
        corr_col = col_names.index("correlation") if "correlation" in col_names else 1
        corr_data = orientation_map.data[..., 0, corr_col]  # (nav_y, nav_x)
        corr = hs.signals.Signal2D(corr_data)
        _copy_nav_axes(corr, nav_axes)
        corr.metadata.General.title = "Correlation Score"
        results.append((corr, "Correlation Score"))
    except Exception as e:
        print(f"Could not extract Correlation Score: {e}")

    # Phase map: column index 0 ('index') for multi-phase
    if n_phases > 1:
        try:
            idx_col = col_names.index("index") if "index" in col_names else 0
            phase_data = orientation_map.data[..., 0, idx_col].astype(float)
            phase_map = hs.signals.Signal2D(phase_data)
            _copy_nav_axes(phase_map, nav_axes)
            phase_map.metadata.General.title = "Phase Map"
            results.append((phase_map, "Phase Map"))
        except Exception as e:
            print(f"Could not extract Phase Map: {e}")

    return results


def _filter_sim_by_radius(coords, intensities, max_radius):
    """Return coords and intensities for spots within max_radius."""
    r = np.sqrt(coords[:, 0] ** 2 + coords[:, 1] ** 2)
    mask = r <= max_radius
    return coords[mask], intensities[mask]


def _get_current_nav_indices(plot):
    """Return current navigation indices as a flat tuple of ints (HyperSpy axis order).

    Tries get_selected_indices() first (BaseSelector subclasses), then falls back to
    _get_selected_indices() (IntegratingSelectorMixin subclasses like IntegratingSelector2D).
    """
    selector = getattr(plot, "parent_selector", None)
    if selector is None:
        selector = getattr(getattr(plot, "plot_window", None), "parent_selector", None)
    if selector is not None:
        # Prefer the clipped method to keep indices in bounds.
        # IntegratingSelector2D only has _get_selected_indices (unclipped),
        # so clip manually using the signal's navigation shape.
        for method_name in ("get_selected_indices", "_get_selected_indices"):
            method = getattr(selector, method_name, None)
            if method is not None:
                try:
                    indices = np.asarray(method())
                    flat = np.mean(indices, axis=0).ravel()
                    # CrosshairSelector returns [[col, row]] (x, y in image space).
                    # Clip col to x-nav size and row to y-nav size.
                    nav_axes = plot.plot_state.current_signal.axes_manager.navigation_axes
                    # nav_axes[0]=x(col, innermost), nav_axes[1]=y(row, outermost)
                    clipped = tuple(
                        int(np.clip(flat[i], 0, nav_axes[i].size - 1))
                        for i in range(len(flat))
                    )
                    return clipped
                except Exception:
                    continue
    nav_axes = plot.plot_state.current_signal.axes_manager.navigation_axes
    return tuple(ax.size // 2 for ax in nav_axes)


def _update_refine_pattern(refine_plot, signal, nav_indices):
    """Load the diffraction pattern at nav_indices into refine_plot."""
    idx = tuple(int(i) for i in reversed(nav_indices))
    pattern_data = np.array(signal.data[idx])
    refine_plot.update_data(pattern_data)


def _build_matching_cache(signal, sim):
    """
    Pre-compute slices and templates that only depend on signal geometry and library.
    With numba cache=True in pyxem, get_slices2d is ~0.1 s and JIT compiles are
    skipped after the first run, so this is cheap after a fresh install.
    """
    from pyxem.utils.indexation_utils import _get_integrated_polar_templates, _norm_rows

    NR, NA = 100, 360

    slices, factors, factors_slice, radial_range = signal.calibration.get_slices2d(NR, NA)

    r0, r1 = float(radial_range[0]), float(radial_range[1])
    radial_axis = r0 + (r1 - r0) / NR * np.arange(NR)
    azim_axis   = np.linspace(-np.pi, np.pi, NA, endpoint=False)

    r_templates, theta_templates, intensities_templates = sim.polar_flatten_simulations(
        radial_axes=radial_axis, azimuthal_axes=azim_axis,
    )
    integrated = _get_integrated_polar_templates(NR, r_templates, intensities_templates, True)
    intensities_raw  = intensities_templates.copy().astype(float)
    intensities_norm = _norm_rows(intensities_raw.copy())

    return {
        "slices": slices,
        "factors": factors,
        "factors_slice": factors_slice,
        "r_templates": r_templates,
        "theta_templates": theta_templates,
        "intensities_norm": intensities_norm,
        "intensities_raw": intensities_raw,
        "integrated": integrated,
        "NR": NR, "NA": NA,
    }


def _ipf_xy_for_rotation(rotation, phases):
    """Return stereographic (x, y) of rotation*z projected into the fundamental sector."""
    from orix.vector import Vector3d
    from orix.projections import StereographicProjection
    # phases may be a single Phase or a list — always use first
    phase = phases[0] if hasattr(phases, '__len__') else phases
    vec = rotation * Vector3d.zvector()
    vec = vec.in_fundamental_sector(phase.point_group)
    s = StereographicProjection()
    x, y = s.vector2xy(vec)
    return float(np.atleast_1d(x)[0]), float(np.atleast_1d(y)[0])


def _ipf_triangle_xy(phase):
    """Return (xy_edges, label_xy, label_texts) for the IPF fundamental sector outline."""
    from orix.projections import StereographicProjection
    from pyxem.signals.indexation_results import _closed_edges_in_hemisphere, _get_ipf_axes_labels
    s = StereographicProjection()
    sector = phase.point_group.fundamental_sector
    edges = _closed_edges_in_hemisphere(sector.edges, sector)
    ex, ey = s.vector2xy(edges)
    xy_edges = np.vstack((ex, ey)).T
    try:
        raw_labels = _get_ipf_axes_labels(sector.vertices, symmetry=phase.point_group)
        # Strip LaTeX delimiters ($) — pyqtgraph can't render them
        labels = [l.replace("$", "") for l in raw_labels]
        lx, ly = s.vector2xy(sector.vertices)
        lx = np.atleast_1d(np.array(lx, dtype=float))
        ly = np.atleast_1d(np.array(ly, dtype=float))
        center_x = float(np.mean(lx))
        center_y = float(np.mean(ly))
        # Displace each label away from the triangle centroid
        DISPLACE = 0.25
        label_xy = np.vstack([
            lx + DISPLACE * (lx - center_x),
            ly + DISPLACE * (ly - center_y),
        ]).T
    except Exception:
        labels, label_xy = [], np.empty((0, 2))
    return xy_edges, label_xy, labels


def _get_best_fit_spots(signal, sim, nav_indices, gamma, max_radius, min_intensity=0.0,
                        scale_override=None, matching_cache=None, pattern_override=None,
                        normalize_templates=False, rot_mask=None):
    """
    Run orientation matching on a single diffraction pattern and return
    (coords_data, intensities, ipf_xy) for the best-match simulation spots.

    coords_data : ndarray shape (N, 2) in Å⁻¹ centered at the direct beam.
    intensities : ndarray shape (N,)
    ipf_xy      : (x, y) tuple in stereographic coords for the best-match rotation.

    matching_cache : dict from _build_matching_cache — holds pre-computed slices
        and templates so this function only does ~5 ms of work per call.
        If None, falls back to the slow HyperSpy path (~7 s per call).
    """
    original_scale = signal.axes_manager.signal_axes[0].scale
    from pyxem.utils.indexation_utils import _mixed_matching_lib_to_polar
    from pyxem.utils._azimuthal_integrations import _slice_radial_integrate

    if pattern_override is not None:
        pattern_data = np.asarray(pattern_override).astype(float)
    else:
        # nav_indices are (x, y) HyperSpy order (innermost first).
        # Reverse to (y, x) numpy order for data indexing.
        idx = tuple(int(i) for i in reversed(nav_indices))
        pattern_data = np.array(signal.data[idx]).astype(float)

    if matching_cache is not None:
        # Fast path: raw numpy, no HyperSpy Signal overhead
        slices        = matching_cache["slices"]
        factors       = matching_cache["factors"]
        factors_slice = matching_cache["factors_slice"]
        r_tmpl        = matching_cache["r_templates"]
        theta_tmpl    = matching_cache["theta_templates"]
        int_norm      = matching_cache["intensities_norm"]
        integrated    = matching_cache["integrated"]
        NR, NA        = matching_cache["NR"], matching_cache["NA"]

        polar = _slice_radial_integrate(
            pattern_data, factors, factors_slice, slices, NR, NA, mean=True
        )
        # Apply gamma, convert to (azim, radial) for _mixed_matching_lib_to_polar
        polar = np.nan_to_num(polar ** gamma).T.astype(float)  # (NA, NR)

        int_templates = int_norm if normalize_templates else matching_cache["intensities_raw"]

        # Apply rotation mask: subset templates to only those inside IPF mask circles
        if rot_mask is not None and rot_mask.any():
            mask_idx = np.where(rot_mask)[0]
            integrated_use    = integrated[mask_idx]
            r_tmpl_use        = r_tmpl[mask_idx]
            theta_tmpl_use    = theta_tmpl[mask_idx]
            int_templates_use = int_templates[mask_idx]
        else:
            mask_idx          = None
            integrated_use    = integrated
            r_tmpl_use        = r_tmpl
            theta_tmpl_use    = theta_tmpl
            int_templates_use = int_templates

        n_templates = integrated_use.shape[0]
        result = _mixed_matching_lib_to_polar(
            polar,
            integrated_templates=integrated_use,
            r_templates=r_tmpl_use,
            theta_templates=theta_tmpl_use,
            intensities_templates=int_templates_use,
            n_keep=None, frac_keep=1.0, n_best=n_templates, transpose=False,
        )
        # result shape (n_templates, 4): [library_index, correlation, rotation_idx, mirror]
        # lib_idx values are indices into the *subset* if mask_idx is set; remap to global.
        if mask_idx is not None:
            result[:, 0] = mask_idx[result[:, 0].astype(int)].astype(result.dtype)

        # Best match is result[0] (sorted descending by correlation).
        row = result[0]
        lib_idx = int(row[0])
        rot_idx = int(row[2])
        mirror  = float(row[3])

        # Get the raw simulation coordinates for the best-match entry
        _rot, _phase_idx, coords_dv = sim.get_simulation(lib_idx)
        raw_coords  = coords_dv.data[:, :2].copy().astype(float)
        intensities = np.array(coords_dv.intensity, dtype=float)

        # Replicate vectors_from_orientation_map (pyxem/signals/indexation_results.py):
        #   1. flip y, 2. rotate by mirror*angle, 3. negate, 4. mirror*y
        NA_full   = NA
        angle_deg = rot_idx / NA_full * 360.0 - 180.0
        angle_rad = np.deg2rad(mirror * angle_deg)
        cos_a, sin_a = np.cos(angle_rad), np.sin(angle_rad)
        rx = raw_coords[:, 0];  ry = -raw_coords[:, 1]
        kx = rx * cos_a - ry * sin_a;  ky = rx * sin_a + ry * cos_a
        kx, ky = -kx, -ky;  ky = mirror * ky
        raw_coords = np.stack([kx, ky], axis=1)

        # IPF heatmap: project every template rotation * z into the fundamental
        # sector, weighted by normalised correlation score.
        try:
            from orix.vector import Vector3d as _V3
            from orix.projections import StereographicProjection as _SP
            _phase = sim.phases if not hasattr(sim.phases, '__len__') else sim.phases
            if hasattr(_phase, '__len__'):
                _phase = _phase[0]
            _sp = _SP()
            # All rotations in the simulation library
            all_rots = sim.rotations if not hasattr(sim.rotations, '__len__') else sim.rotations
            if hasattr(all_rots, '__len__'):
                all_rots = all_rots[0] if len(all_rots) == 1 else all_rots
            vecs = all_rots * _V3.zvector()
            vecs_fs = vecs.in_fundamental_sector(_phase.point_group)
            ipf_xs, ipf_ys = _sp.vector2xy(vecs_fs)
            ipf_xs = np.atleast_1d(np.array(ipf_xs, dtype=float))
            ipf_ys = np.atleast_1d(np.array(ipf_ys, dtype=float))

            # Map result rows back to rotation indices (result[:,0] = lib_idx into sim)
            # Correlations are already sorted best-first; normalise to [0,1]
            all_cors = result[:, 1].astype(float)
            cor_max = float(all_cors[0]) if all_cors[0] > 0 else 1.0
            all_cors_norm = np.clip(all_cors / cor_max, 0.0, 1.0)
            all_lib_idxs = result[:, 0].astype(int)

            # Build per-rotation correlation array (some rotations may not appear
            # in result if frac_keep filtered them; leave those as 0)
            cor_per_rot = np.zeros(len(ipf_xs), dtype=float)
            for i, li in enumerate(all_lib_idxs):
                if 0 <= li < len(cor_per_rot):
                    cor_per_rot[li] = all_cors_norm[i]

            ipf_heatmap = (ipf_xs, ipf_ys, cor_per_rot)
            ipf_xy = _ipf_xy_for_rotation(_rot, sim.phases)
        except Exception as e:
            print(f"IPF heatmap failed: {e}")
            ipf_heatmap = None
            ipf_xy = (0.0, 0.0)

        # Apply scale override before radius filtering: the library was generated
        # assuming the signal's calibrated scale, but the real data may be
        # miscalibrated.  scale_override is the user's corrected Å⁻¹/px value,
        # so the template coords (in Å⁻¹) need to be rescaled by
        # scale_override / original_scale to match where spots actually land.
        if scale_override is not None:
            raw_coords = raw_coords * (scale_override / original_scale)

    else:
        # Slow fallback: full HyperSpy Signal path
        import hyperspy.api as hs
        pat = hs.signals.Signal2D(pattern_data)
        for i, ax in enumerate(signal.axes_manager.signal_axes):
            pat.axes_manager.signal_axes[i].scale = ax.scale
            pat.axes_manager.signal_axes[i].offset = ax.offset
            pat.axes_manager.signal_axes[i].units = ax.units
        pat.set_signal_type("electron_diffraction")
        polar_hs = pat.get_azimuthal_integral2d(npt=100, npt_azim=360, inplace=False, mean=True)
        polar_hs = polar_hs ** gamma
        orientation = polar_hs.get_orientation(sim)
        vectors_signal = orientation.to_vectors(n_best_index=0, return_object=False)
        spot_array = vectors_signal.data[()]
        if spot_array.ndim == 1 and spot_array.dtype == object:
            spot_array = spot_array[0]
        raw_coords  = spot_array[:, :2].astype(float)
        intensities = spot_array[:, 3].astype(float)

        if scale_override is not None:
            raw_coords = raw_coords * (scale_override / original_scale)

        try:
            best_rot = orientation.data[0, 0]
            from orix.quaternion import Rotation as _Rotation
            ipf_xy = _ipf_xy_for_rotation(_Rotation(best_rot), sim.phases)
        except Exception:
            ipf_xy = (0.0, 0.0)
        ipf_heatmap = None  # not available in slow path

    # Normalize intensities to [0, 1] relative to the brightest spot in the
    # full (pre-filter) simulation, then threshold by min_intensity percentage.
    i_max_all = float(np.max(intensities)) if len(intensities) > 0 else 1.0
    i_max_all = i_max_all if i_max_all > 0 else 1.0
    intensities_norm_display = intensities / i_max_all

    coords_filtered, intensities_filtered = _filter_sim_by_radius(
        raw_coords, intensities_norm_display, max_radius
    )

    if min_intensity > 0.0 and len(intensities_filtered) > 0:
        keep = intensities_filtered >= min_intensity
        coords_filtered      = coords_filtered[keep]
        intensities_filtered = intensities_filtered[keep]

    return coords_filtered, intensities_filtered, ipf_xy, ipf_heatmap


def _compute_reciprocal_radius(signal) -> float:
    """Derive max reciprocal radius from signal axes calibration."""
    sig_axes = signal.axes_manager.signal_axes
    half_extents = [ax.scale * ax.size / 2.0 for ax in sig_axes]
    return min(half_extents)


def _make_slider_row(parent, label_text, min_val, max_val, default, decimals=2, suffix=""):
    """Return (row_widget, spinbox, slider) for a labelled float slider+spinbox row."""
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
    spin.setFixedWidth(72 if suffix else 64)
    if suffix:
        spin.setSuffix(suffix)
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
    return row, spin, slider


# Module-level set of toolbar ids that have already had the OM caret built.
_OM_BUILT_TOOLBARS: set = set()


def orientation_mapping(
    toolbar: RoundedToolBar,
    action_name: str = "Orientation Mapping",
    *args,
    **kwargs,
):
    """5-step wizard (tabbed) for template-matching orientation mapping of 4D-STEM data."""
    from PySide6 import QtWidgets as _QW, QtCore as _QC
    from spyde.drawing.toolbars.caret_group import CaretGroup, FileDropWidget

    # Guard: build the caret only once per toolbar instance.
    tid = id(toolbar)
    if tid in _OM_BUILT_TOOLBARS:
        return
    _OM_BUILT_TOOLBARS.add(tid)

    plot = toolbar.plot
    signal = plot.plot_state.current_signal
    main_window = plot.main_window
    sig_ax = signal.axes_manager.signal_axes
    sig_scale = sig_ax[0].scale  # Å⁻¹/px

    # ── State dict ─────────────────────────────────────────────────────────────
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
        "ipf_widget": [None],
        "run_status": [None],
        "run_btn": [None],
        "normalize_templates": [False],
        "ipf_mask_circles": [],   # list of [cx, cy, r] in IPF stereographic coords
        "matching_cache": [None],  # pre-computed slices+templates from _build_matching_cache
        "refit_generation": [0],   # incremented on each schedule; threads skip stale runs
        "gen_relay": [None],       # kept alive so queued signal survives until GUI thread delivers it
    }

    # ── Build a CaretGroup directly and register it with the toolbar ───────────
    # We do NOT call toolbar.add_action again (that would create a second icon).
    # Instead we build the caret widget and register it via add_action_widget,
    # which wires the existing toggle action's toggled signal to show/hide it.
    toolbar._om_state = state

    caret = CaretGroup(
        title=action_name,
        toolbar=toolbar,
        action_name=action_name,
    )
    toolbar.add_action_widget(action_name, caret, None)
    # add_action_widget/_bind_action_to_widget calls setChecked(False) which hides
    # the caret. Defer restoring the checked state until after the full widget tree
    # is built and finalize_layout() has been called, so position_fn sees real geometry.

    layout = caret.layout()

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
    def _on_om_tab_changed(idx):
        on_refine = idx == 2
        ipf_w = state["ipf_widget"][0]
        if ipf_w is not None:
            ipf_w.show() if on_refine else ipf_w.hide()
        sc = state["scatter_item"][0]
        if sc is not None:
            sc.setVisible(on_refine)
        roi = state["circle_roi"][0]
        if roi is not None:
            roi.setVisible(on_refine)

    step_bar, stack, _select_step = CaretGroup.make_tab_stack(
        ["1 Load", "2 Library", "3 Refine", "4 Run"],
        parent=caret,
        width=W,
        on_tab_changed=_on_om_tab_changed,
    )

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
    gamma_row, gamma_s, gamma_sl = _make_slider_row(p2, "Gamma", 0.1, 1.5, 1.0, decimals=2)
    # Min intensity as percentage of brightest spot (0–100%)
    min_i_row, min_i_s, min_i_sl = _make_slider_row(p2, "Min intens.", 0.0, 100.0, 10.0, decimals=1, suffix="%")
    # Scale: start at signal scale, allow ±10%
    sc_lo = round(sig_scale * 0.9, 6)
    sc_hi = round(sig_scale * 1.1, 6)
    sc_step_dec = max(2, -int(np.floor(np.log10(sig_scale * 0.01))) + 1) if sig_scale > 0 else 4
    scale_row, scale_s, scale_sl = _make_slider_row(p2, "Scale", sc_lo, sc_hi, sig_scale, decimals=sc_step_dec)
    norm_chk = _QW.QCheckBox("Normalize templates", p2)
    norm_chk.setChecked(False)
    norm_chk.setStyleSheet("QCheckBox { color: white; font-size: 10px; }")
    refine_lbl = _lbl("Generate library first.", p2)
    for r in [gamma_row, min_i_row, scale_row]:
        r.setEnabled(False)
    norm_chk.setEnabled(False)
    v2.addWidget(refine_lbl)
    v2.addWidget(gamma_row)
    v2.addWidget(min_i_row)
    v2.addWidget(scale_row)
    v2.addWidget(norm_chk)
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

    # Now that the widget tree is fully built, restore the checked state so the
    # caret shows with correct geometry on the first click.
    om_action = toolbar._find_action(action_name)
    if om_action is not None:
        om_action.setChecked(True)
    pos_fn = toolbar.action_widgets.get(action_name, {}).get("position_fn")
    if pos_fn is not None:
        pos_fn()

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
        lib_lbl.setText("Generating library…")

        from PySide6 import QtCore as _QC2
        class _GenRelay(_QC2.QObject):
            done = _QC2.Signal()
        _gen_relay = _GenRelay()
        state["gen_relay"][0] = _gen_relay  # prevent GC before queued signal is delivered

        def _on_done():
            state["gen_relay"][0] = None  # release relay now that signal has been delivered
            lib_lbl.setText("✓ Library ready")
            gen_btn.setText("✓ Regenerate")
            gen_btn.setEnabled(True)
            for r in [gamma_row, min_i_row, scale_row]:
                r.setEnabled(True)
            norm_chk.setEnabled(True)
            refine_lbl.setText("Overlay active. Adjust sliders to refine.")
            run_btn_w.setEnabled(True)
            _activate_overlay()
            _select_step(2)

        _gen_relay.done.connect(_on_done)

        # Capture widget values on the GUI thread before spawning the worker.
        _accel_kv   = voltage_s.value()
        _resolution = res_s.value()
        _min_int    = min_int_s.value()
        _recip_r    = _compute_reciprocal_radius(signal)

        def _do_generate():
            from PySide6 import QtCore as _QC2
            try:
                new_sim = _generate_library_from_phases(
                    phases=state["phases"],
                    accelerating_voltage=_accel_kv,
                    resolution=_resolution,
                    minimum_intensity=_min_int,
                    reciprocal_radius=_recip_r,
                )
                state["sim"][0] = new_sim
                _QC2.QMetaObject.invokeMethod(
                    lib_lbl, "setText",
                    _QC2.Qt.ConnectionType.QueuedConnection,
                    _QC2.Q_ARG(str, "Building matching cache…"),
                )
                state["matching_cache"][0] = _build_matching_cache(signal, new_sim)
                state["refit_generation"][0] = 0
                _gen_relay.done.emit()
            except Exception as e:
                import traceback; traceback.print_exc()
                from PySide6 import QtCore as _QC2
                _QC2.QMetaObject.invokeMethod(
                    lib_lbl, "setText",
                    _QC2.Qt.ConnectionType.QueuedConnection,
                    _QC2.Q_ARG(str, f"Failed: {e}"),
                )
                _QC2.QMetaObject.invokeMethod(
                    gen_btn, "setEnabled",
                    _QC2.Qt.ConnectionType.QueuedConnection,
                    _QC2.Q_ARG(bool, True),
                )

        threading.Thread(target=_do_generate, daemon=True).start()

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

        # scene-x = -ky (sig_ax[1]),  scene-y = kx (sig_ax[0])
        _cx_scene = sig_ax[1].size / 2.0 * sig_ax[1].scale + sig_ax[1].offset  # ky center → scene-x
        _cy_scene = sig_ax[0].size / 2.0 * sig_ax[0].scale + sig_ax[0].offset  # kx center → scene-y

        r_data = state["max_radius"][0]
        cx_data = sig_ax[1].size / 2.0 * sig_ax[1].scale + sig_ax[1].offset
        cy_data = sig_ax[0].size / 2.0 * sig_ax[0].scale + sig_ax[0].offset
        circle_roi = PgCircleROI(
            pos=(cx_data - r_data, cy_data - r_data),
            size=(2 * r_data, 2 * r_data),
            pen=mkPen("y", width=1),
        )
        plot.addItem(circle_roi)
        state["circle_roi"][0] = circle_roi

        timer = _QT()
        timer.setInterval(50)
        timer.setSingleShot(True)
        state["refit_timer"][0] = timer

        # Relay object used to marshal spot + IPF data from worker thread to GUI thread.
        from PySide6 import QtCore as _QC
        class _SpotRelay(_QC.QObject):
            spots_ready = _QC.Signal(list, float, float, object)  # spots, ipf_x, ipf_y, heatmap
        _relay = _SpotRelay()

        # ── IPF plot window in MDI area ────────────────────────────────────────
        import pyqtgraph as _pg
        from PySide6 import QtWidgets as _QW2

        ipf_plot_window = main_window.add_plot_window(
            is_navigator=False,
            signal_tree=plot.signal_tree,
        )
        ipf_plot_window.setWindowTitle("IPF — Orientation Refinement")
        _mw_size = main_window.size()
        _ipf_side = min(_mw_size.width(), _mw_size.height()) // 4
        ipf_plot_window.resize(_ipf_side, _ipf_side)
        main_window._auto_position_near_owner(ipf_plot_window)
        state["ipf_widget"][0] = ipf_plot_window
        ipf_plot_window.hide()  # shown by _select_step(2)

        # Replace the GraphicsLayoutWidget with a raw PlotWidget for full control.
        # Remove the existing plot_widget and substitute our IPF PlotWidget.
        container_layout = ipf_plot_window.container.layout()
        ipf_plot_window.plot_widget.setParent(None)
        ipf_pw = _pg.PlotWidget()
        ipf_pw.setBackground("k")
        ipf_pw.hideAxis("bottom")
        ipf_pw.hideAxis("left")
        ipf_pw.setAspectLocked(True)
        container_layout.addWidget(ipf_pw)

        # Pre-compute IPF triangle outline and grid bounds for the phase
        _ipf_img_item = _pg.ImageItem()
        _ipf_img_item.setZValue(-10)
        ipf_pw.addItem(_ipf_img_item)
        _ipf_grid_info = [None]  # will hold (xx, yy, tri, weights, vertices, outside) once set

        try:
            from scipy.spatial import Delaunay as _Delaunay
            from orix.projections import StereographicProjection as _SP2
            from orix.vector import Vector3d as _V3b

            _phase = state["sim"][0].phases
            if hasattr(_phase, '__len__'):
                _phase = _phase[0]
            _tri_xy, _lbl_xy, _lbl_texts = _ipf_triangle_xy(_phase)

            # Draw triangle outline on top
            ipf_pw.plot(_tri_xy[:, 0], _tri_xy[:, 1],
                        pen=_pg.mkPen("w", width=1.5), antialias=True)
            for (lx, ly), txt in zip(_lbl_xy, _lbl_texts):
                ti = _pg.TextItem(txt, color="w", anchor=(0.5, 0.5))
                ti.setPos(lx, ly)
                ipf_pw.addItem(ti)

            # Pre-compute Delaunay interpolation grid over the IPF triangle extent
            GRID_N = 128
            mins = _tri_xy.min(axis=0)
            maxs = _tri_xy.max(axis=0)

            # All rotation vectors projected to stereographic coords
            _sp2 = _SP2()
            _all_rots = state["sim"][0].rotations
            if hasattr(_all_rots, '__len__'):
                _all_rots = _all_rots[0] if len(_all_rots) == 1 else _all_rots
            _vecs = (_all_rots * _V3b.zvector()).in_fundamental_sector(_phase.point_group)
            _rxs, _rys = _sp2.vector2xy(_vecs)
            _rxs = np.atleast_1d(np.array(_rxs, dtype=float))
            _rys = np.atleast_1d(np.array(_rys, dtype=float))
            rot_xy = np.vstack((_rxs, _rys)).T

            # Grid for the image
            gx = np.linspace(mins[0], maxs[0], GRID_N)
            gy = np.linspace(mins[1], maxs[1], GRID_N)
            xx, yy = np.meshgrid(gx, gy)
            flat_xy = np.vstack((xx.ravel(), yy.ravel())).T

            tri = _Delaunay(rot_xy)
            simplex = tri.find_simplex(flat_xy)
            outside = simplex < 0
            vertices = np.take(tri.simplices, simplex, axis=0)
            temp = np.take(tri.transform, simplex, axis=0)
            delta = flat_xy - temp[:, -1]
            bary = np.einsum("njk,nk->nj", temp[:, :-1, :], delta)
            bary_weights = np.hstack((bary, 1 - bary.sum(axis=1, keepdims=True)))

            _ipf_grid_info[0] = (xx, yy, vertices, bary_weights, outside,
                                  mins, maxs, GRID_N, _rxs, _rys)

            # Set ImageItem transform so it spans the triangle extent
            from pyqtgraph import QtGui as _QtGui
            tr = _QtGui.QTransform()
            tr.translate(mins[0], mins[1])
            tr.scale((maxs[0] - mins[0]) / GRID_N, (maxs[1] - mins[1]) / GRID_N)
            _ipf_img_item.setTransform(tr)

        except Exception as e:
            print(f"IPF triangle/grid failed: {e}")

        # Best-match marker on top
        ipf_marker = _pg.ScatterPlotItem(
            size=14, pen=_pg.mkPen("w", width=1.5), brush=_pg.mkBrush("r")
        )
        ipf_pw.addItem(ipf_marker)

        # ── IPF mask circles (click to add, scroll to resize, Del to remove) ──
        # Each entry in state["ipf_mask_circles"] is [cx, cy, r].
        # Drawn as CircleROI-style items on ipf_pw.
        _mask_circle_items = []   # list of pg.CircleROI, parallel to state["ipf_mask_circles"]
        _selected_mask = [None]   # index of currently selected circle (for Del)

        def _redraw_mask_circles():
            for item in _mask_circle_items:
                try:
                    ipf_pw.removeItem(item)
                except Exception:
                    pass
            _mask_circle_items.clear()
            for i, (cx, cy, r) in enumerate(state["ipf_mask_circles"]):
                is_sel = (i == _selected_mask[0])
                pen = _pg.mkPen("y" if is_sel else "c", width=1.5)
                brush = _pg.mkBrush(0, 200, 255, 40 if not is_sel else 70)
                item = _pg.CircleROI(
                    pos=(cx - r, cy - r), size=(2 * r, 2 * r),
                    pen=pen, movable=False, resizable=False,
                )
                item.removeHandle(0)  # remove the default resize handle
                ipf_pw.addItem(item)
                _mask_circle_items.append(item)

        def _add_mask_circle(cx, cy):
            # Default radius = ~10% of the triangle extent
            gi = _ipf_grid_info[0]
            default_r = 0.05
            if gi is not None:
                mins, maxs = gi[5], gi[6]
                default_r = float((maxs - mins).mean()) * 0.08
            state["ipf_mask_circles"].append([cx, cy, default_r])
            _selected_mask[0] = len(state["ipf_mask_circles"]) - 1
            _redraw_mask_circles()
            _schedule()

        def _remove_selected_mask():
            idx = _selected_mask[0]
            if idx is not None and 0 <= idx < len(state["ipf_mask_circles"]):
                state["ipf_mask_circles"].pop(idx)
                _selected_mask[0] = None
                _redraw_mask_circles()
                _schedule()

        def _select_nearest_mask(cx, cy):
            best_i, best_d2 = None, float("inf")
            for i, (mcx, mcy, mr) in enumerate(state["ipf_mask_circles"]):
                d2 = (cx - mcx) ** 2 + (cy - mcy) ** 2
                if d2 < best_d2:
                    best_d2, best_i = d2, i
            _selected_mask[0] = best_i
            _redraw_mask_circles()

        def _on_ipf_click(event):
            from PySide6.QtCore import Qt as _Qt
            if event.button() == _Qt.MouseButton.LeftButton:
                pos = ipf_pw.plotItem.vb.mapSceneToView(event.scenePos())
                cx, cy = float(pos.x()), float(pos.y())
                # If click is near an existing circle centre, select it; else add new
                if state["ipf_mask_circles"]:
                    nearest_i = min(
                        range(len(state["ipf_mask_circles"])),
                        key=lambda i: (state["ipf_mask_circles"][i][0] - cx) ** 2
                                    + (state["ipf_mask_circles"][i][1] - cy) ** 2
                    )
                    mcx, mcy, mr = state["ipf_mask_circles"][nearest_i]
                    if (cx - mcx) ** 2 + (cy - mcy) ** 2 <= mr ** 2:
                        _select_nearest_mask(cx, cy)
                        return
                _add_mask_circle(cx, cy)

        def _on_ipf_scroll(event):
            # Map cursor to data coords (event.position() is in viewport coords)
            scene_pos = ipf_pw.viewport().mapToGlobal(event.position().toPoint())
            scene_pos = ipf_pw.mapFromGlobal(scene_pos)
            pos = ipf_pw.plotItem.vb.mapSceneToView(scene_pos)
            cx_cur, cy_cur = float(pos.x()), float(pos.y())
            # Find which circle the cursor is inside (if any)
            hit_idx = None
            for i, (mcx, mcy, mr) in enumerate(state["ipf_mask_circles"]):
                if (cx_cur - mcx) ** 2 + (cy_cur - mcy) ** 2 <= mr ** 2:
                    hit_idx = i
                    break
            if hit_idx is None:
                return False  # not consumed — let pyqtgraph zoom
            _selected_mask[0] = hit_idx
            delta = event.angleDelta().y()
            factor = 1.1 if delta > 0 else (1.0 / 1.1)
            state["ipf_mask_circles"][hit_idx][2] *= factor
            _redraw_mask_circles()
            _schedule()
            return True  # consumed

        def _on_ipf_key(event):
            from PySide6.QtCore import Qt as _Qt2
            if event.key() == _Qt2.Key.Key_Delete:
                _remove_selected_mask()

        ipf_pw.scene().sigMouseClicked.connect(_on_ipf_click)
        ipf_pw.keyPressEvent = _on_ipf_key
        ipf_pw.setFocusPolicy(_QC.Qt.FocusPolicy.ClickFocus)

        # Use an event filter on the viewport to catch wheel events for mask resize
        class _WheelFilter(_QC.QObject):
            def eventFilter(self, obj, event):
                if event.type() == _QC.QEvent.Type.Wheel:
                    consumed = _on_ipf_scroll(event)
                    return bool(consumed)  # consume only if cursor was inside a circle
                return False
        _wheel_filter = _WheelFilter(ipf_pw)
        ipf_pw.viewport().installEventFilter(_wheel_filter)
        state["_ipf_wheel_filter"] = _wheel_filter  # keep alive

        def _apply_spots(spots, ipf_x, ipf_y, heatmap):
            sc = state["scatter_item"][0]
            if sc is not None:
                sc.setData(spots)
            # Update heatmap image
            if heatmap is not None and _ipf_grid_info[0] is not None:
                _xs, _ys, cor_per_rot = heatmap  # cor_per_rot already indexed by lib_idx
                gi = _ipf_grid_info[0]
                verts, bw, outside, GRID_N = gi[2], gi[3], gi[4], gi[7]

                # Interpolate correlation values onto the regular grid
                safe_verts = np.clip(verts, 0, len(cor_per_rot) - 1)
                grid_vals = np.einsum("nj,nj->n", np.take(cor_per_rot, safe_verts), bw).astype(float)
                grid_vals[outside] = np.nan
                # meshgrid(gx, gy) is row=y, col=x → reshape gives (y, x).
                # pyqtgraph ImageItem expects (x, y), so transpose.
                img = grid_vals.reshape(GRID_N, GRID_N).T

                # inferno-style RGBA
                rgba = np.zeros((GRID_N, GRID_N, 4), dtype=np.uint8)
                valid = ~np.isnan(img)
                c = np.where(valid, img, 0.0)
                rgba[..., 0] = np.clip(255 * np.minimum(1.0, c * 2.0), 0, 255).astype(np.uint8)
                rgba[..., 1] = np.clip(255 * np.maximum(0.0, c * 2.0 - 1.0), 0, 255).astype(np.uint8)
                rgba[..., 2] = np.clip(80 * (1.0 - c), 0, 255).astype(np.uint8)
                rgba[..., 3] = np.where(valid, np.clip(220 * c + 30, 0, 255), 0).astype(np.uint8)
                _ipf_img_item.setImage(rgba, autoLevels=False)
            ipf_marker.setData([{"pos": (ipf_x, ipf_y)}])

        _relay.spots_ready.connect(_apply_spots)

        def _do_refit():
            if state["sim"][0] is None:
                return
            r_now = circle_roi.size().x() / 2.0
            state["max_radius"][0] = r_now
            sc_override = scale_s.value() if abs(scale_s.value() - sig_scale) > 1e-9 else None
            state["scale_override"][0] = sc_override
            nav_idx = _get_current_nav_indices(plot)
            # Grab the currently displayed pattern on the GUI thread before spawning worker
            _current_pattern = plot.current_data
            if _current_pattern is not None:
                _current_pattern = np.asarray(_current_pattern).copy()

            state["refit_generation"][0] += 1
            my_gen = state["refit_generation"][0]

            # Build rotation mask from IPF circles (done on GUI thread; arrays are read-only)
            _rot_mask = None
            gi = _ipf_grid_info[0]
            circles = list(state["ipf_mask_circles"])
            if gi is not None and circles:
                rot_xs, rot_ys = gi[8], gi[9]
                mask = np.zeros(len(rot_xs), dtype=bool)
                for cx, cy, r in circles:
                    dist2 = (rot_xs - cx) ** 2 + (rot_ys - cy) ** 2
                    mask |= dist2 <= r ** 2
                if mask.any():
                    _rot_mask = mask

            def _run():
                if state["refit_generation"][0] != my_gen:
                    return  # superseded by a newer request
                try:
                    # coords_data are (kx, ky) in Å⁻¹, centered at origin (0,0)
                    coords_data, intensities, ipf_xy, ipf_heatmap = _get_best_fit_spots(
                        signal, state["sim"][0], nav_idx,
                        state["gamma"][0], state["max_radius"][0],
                        min_intensity=state["min_intensity"][0],
                        scale_override=sc_override,
                        matching_cache=state["matching_cache"][0],
                        pattern_override=_current_pattern,
                        normalize_templates=state["normalize_templates"][0],
                        rot_mask=_rot_mask,
                    )
                    if state["refit_generation"][0] != my_gen:
                        return
                    i_max = float(np.max(intensities)) if len(intensities) > 0 else 1.0
                    i_max = i_max if i_max > 0 else 1.0
                    # scene-x = -ky + ky_center,  scene-y = kx + kx_center
                    spots = [
                        {"pos": (-float(coords_data[i][1]) + _cx_scene,
                                  float(coords_data[i][0]) + _cy_scene),
                         "size": int(5 + 10 * float(intensities[i]) / i_max)}
                        for i in range(len(coords_data))
                    ]
                    if state["refit_generation"][0] == my_gen:
                        _relay.spots_ready.emit(spots, float(ipf_xy[0]), float(ipf_xy[1]), ipf_heatmap)
                except Exception as e:
                    print(f"Refit failed: {e}")

            threading.Thread(target=_run, daemon=True).start()

        def _schedule():
            if state["refit_timer"][0] is not None:
                state["refit_timer"][0].start()

        timer.timeout.connect(_do_refit)
        circle_roi.sigRegionChangeFinished.connect(_schedule)

        nav_sel = getattr(plot, "parent_selector", None)
        if nav_sel is None:
            nav_sel = getattr(getattr(plot, "plot_window", None), "parent_selector", None)
        if nav_sel is not None and hasattr(nav_sel, "roi"):
            # sigRegionChangeFinished fires on mouse release; sigRegionChanged fires
            # continuously during drag. Connect both so position updates feel live.
            nav_sel.roi.sigRegionChangeFinished.connect(_schedule)
            nav_sel.roi.sigRegionChanged.connect(_schedule)

        def _on_slider(_v=None):
            state["gamma"][0] = gamma_s.value()
            # slider is 0–100%, convert to 0.0–1.0 fraction for _get_best_fit_spots
            state["min_intensity"][0] = min_i_s.value() / 100.0
            _schedule()

        def _on_norm_chk(checked):
            state["normalize_templates"][0] = bool(checked)
            _schedule()

        gamma_s.valueChanged.connect(_on_slider)
        gamma_sl.valueChanged.connect(_on_slider)
        min_i_s.valueChanged.connect(_on_slider)
        min_i_sl.valueChanged.connect(_on_slider)
        scale_s.valueChanged.connect(_on_slider)
        scale_sl.valueChanged.connect(_on_slider)
        norm_chk.stateChanged.connect(_on_norm_chk)

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
