from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtCore import Qt

from spyde.drawing.toolbars.rounded_toolbar import RoundedToolBar
from spyde.drawing.selector import RectangleSelector
from typing import Tuple

from spyde.drawing.toolbars.plot_control_toolbar import resolve_icon_path


def center_zero_beam(toolbar: RoundedToolBar,
                     make_flat_field: bool = False,
                     method: str = "com",
                     signal_slice: Tuple[int, int, int, int] = None,
                     action_name: str = "Center zero-beam",
                     *args, **kwargs
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

    sl = (signal_slice[0], signal_slice[0] + signal_slice[2], signal_slice[1], signal_slice[1] + signal_slice[3])

    shifts = signal.get_direct_beam_position(method=method, signal_slice=sl, **kwargs)

    print(make_flat_field)
    if make_flat_field:
        if shifts._lazy:
            shifts.compute()
        shifts.get_linear_plane()

    new_signal = toolbar.plot.signal_tree.add_transformation(parent_signal=signal,
                                                             node_name="Centered",
                                                             method="center_direct_beam",
                                                             shifts=shifts,
                                                             inplace=False)
    new_signal.calibration.center = None
    toolbar.plot.set_plot_state(new_signal)


def virtual_imaging(toolbar: RoundedToolBar,
                    selector: RectangleSelector,
                    action_name: str = "Create Virtual Image",
                    *args, **kwargs
                    ):
    """
    Create a virtual image from a 4D STEM dataset by integrating over a selected region.

    Parameters
    ----------
    toolbar : spyde.plugins.toolbar.Toolbar
        The toolbar instance from which to get the current signal.
    selector : spyde.plugins.selector.Selector
        The selector instance from which to get the current signal.

    """
    pass


def add_virtual_image(toolbar: RoundedToolBar,
                      action_name: str = "Add Virtual Image",
                      *args, **kwargs
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

    icon = QIcon()
    icon.addPixmap(colored_pixmap)

    params = {
        "type": {
            "name": "Detector Type",
            "type": "enum",
            "default": "annular",
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
    action, params_caret_box = toolbar.add_action(
        name=f"Virtual Image ({color})",
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

    def on_type_change(new_type: str) -> None:
        print("Type changed to:", new_type)
        # ...future logic for changing selectors / rows based on new_type...

    if hasattr(type_widget, "currentTextChanged"):
        type_widget.currentTextChanged.connect(on_type_change)


def compute_virtual_image(toolbar: RoundedToolBar,
                          action_name: str = "Compute Virtual Image",
                          *args, **kwargs
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
