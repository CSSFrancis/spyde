import numpy as np
from typing import Tuple

from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtCore import Qt
from pyqtgraph import RectROI, CircleROI, mkPen

from spyde.drawing.toolbars.toolbar import RoundedToolBar
from spyde.drawing.toolbars.plot_control_toolbar import resolve_icon_path
from spyde.external.pyqtgraph.ring_roi import RingROI


def roi_to_mask(roi, signal) -> np.ndarray:
    """Convert a PyQtGraph ROI to a float32 mask over the signal axes.

    Uses the signal axes scale/offset to build a pixel coordinate grid.
    Returns shape (nkx, nky), dtype float32, values 0.0 or 1.0.
    """
    sig_axes = signal.axes_manager.signal_axes  # [kx_axis, ky_axis] — last two
    nkx = sig_axes[1].size
    nky = sig_axes[0].size
    scale_x = sig_axes[1].scale
    scale_y = sig_axes[0].scale
    offset_x = sig_axes[1].offset
    offset_y = sig_axes[0].offset

    rows = np.arange(nkx)
    cols = np.arange(nky)
    col_grid, row_grid = np.meshgrid(cols, rows)

    x_data = col_grid * scale_x + offset_x
    y_data = row_grid * scale_y + offset_y

    if isinstance(roi, RingROI):
        inner_roi = roi.rois[0]
        outer_roi = roi.rois[1]
        inner_pos = inner_roi.pos()
        inner_size = inner_roi.size()
        outer_pos = outer_roi.pos()
        outer_size = outer_roi.size()
        cx = outer_pos.x() + outer_size.x() / 2
        cy = outer_pos.y() + outer_size.y() / 2
        inner_r = inner_size.x() / 2
        outer_r = outer_size.x() / 2
        dist2 = (x_data - cx) ** 2 + (y_data - cy) ** 2
        mask_bool = (dist2 >= inner_r ** 2) & (dist2 <= outer_r ** 2)

    elif isinstance(roi, CircleROI):
        pos = roi.pos()
        size = roi.size()
        cx = pos.x() + size.x() / 2
        cy = pos.y() + size.y() / 2
        r = size.x() / 2
        dist2 = (x_data - cx) ** 2 + (y_data - cy) ** 2
        mask_bool = dist2 <= r ** 2

    elif isinstance(roi, RectROI):
        pos = roi.pos()
        size = roi.size()
        x0, x1 = pos.x(), pos.x() + size.x()
        y0, y1 = pos.y(), pos.y() + size.y()
        mask_bool = (x_data >= x0) & (x_data <= x1) & (y_data >= y0) & (y_data <= y1)

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

    # Create base icon pixmap
    base_icon = QIcon(icon_path)

    # Match the toolbar's icon size and HiDPI scaling
    icon_size = toolbar.iconSize()
    dpr = getattr(toolbar, "devicePixelRatioF", lambda: 1.0)()
    req_w = max(1, int(icon_size.width() * dpr))
    req_h = max(1, int(icon_size.height() * dpr))

    base_pixmap = base_icon.pixmap(req_w, req_h)

    # Recolor icon via SourceIn composition without changing size
    colored_pixmap = QPixmap(base_pixmap.size())
    colored_pixmap.setDevicePixelRatio(dpr)
    colored_pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(colored_pixmap)
    painter.drawPixmap(0, 0, base_pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(colored_pixmap.rect(), QColor(color))
    painter.end()

    pen = mkPen(
        color=color,
        width=6,
    )  # type: pg.mkPen

    icon = QIcon()
    icon.addPixmap(colored_pixmap)

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
    }

    # Create a parameter caret box as the action widget.
    # This returns a QAction and the associated CaretParams instance.
    # need to give each action a unique name (if the colors repeat)
    action_name = f"Virtual Image ({color})"
    action, params_caret_box = toolbar.add_action(
        name=action_name,
        icon_path=icon,
        function=compute_virtual_image,
        toggle=True,
        parameters=params,
    )

    # For some call sites (including this one), the first time the popout is
    # shown it was being clipped because sizeHint hadn't fully accounted for
    # its children yet. Force a layout finalization here as a safeguard,
    # in addition to CaretParams.finalize_layout being called in __init__.
    try:
        if hasattr(params_caret_box, "finalize_layout"):
            params_caret_box.finalize_layout()
    except Exception:
        pass

    # Access parameter widgets as before (e.g. to wire type-dependent behavior)
    type_widget = params_caret_box.kwargs["type"]

    # add a roi.  These should be based on the type selected in the caret box
    # all of them should be the same color as the icon and only the one that is
    # selected should be movable. The rest should be opaque and not movable.

    plot = toolbar.parent_toolbar.plot
    center, inner_rad, outer_rad = plot.get_annular_roi_parameters()

    if params_caret_box.kwargs["type"].currentText() == "annular":
        # make an annular roi
        roi = RingROI(center, inner_radius=inner_rad, outer_radius=outer_rad, pen=pen)
    elif params_caret_box.kwargs["type"].currentText() == "disk":
        roi = CircleROI(center, inner_rad, pen=pen)
    else:  # params_caret_box.kwargs["type"].currentText() == "rectangle":
        roi = RectROI(center, inner_rad, pen=pen)

    # add to the parent toolbar so that all the rois are shown on the same plot
    toolbar.parent_toolbar.register_action_plot_item(
        action_name="Virtual Imaging", item=roi, key=action_name
    )

    # arrange the z values of the rois based on their size
    def arrange_widgets_on_move():
        rois = list(
            toolbar.parent_toolbar.action_widgets["Virtual Imaging"][
                "plot_items"
            ].values()
        )
        sizes = [r.size().x() for r in rois]
        sorted_index = np.argsort(sizes)
        for i, idx in enumerate(sorted_index[::-1]):
            r = rois[idx]
            r.setZValue(10 + i)

    roi.sigRegionChangeFinished.connect(arrange_widgets_on_move)

    def on_type_change(new_type: str) -> None:
        print("Type changed to:", new_type)
        # Remove existing ROI
        # Create new ROI based on selected type
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
        else:  # "rectangle"
            roi = RectROI(pos=pos, size=size, pen=pen)
        # Add new ROI to the toolbar

        toolbar.parent_toolbar.register_action_plot_item(
            action_name="Virtual Imaging", item=roi, key=action_name
        )

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
