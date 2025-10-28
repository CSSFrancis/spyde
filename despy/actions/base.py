
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from despy.drawing.toolbars.rounded_toolbar import RoundedToolBar
from despy.drawing.toolbars.floating_button_trees import RoundedButton
from despy.drawing.toolbars.caret_group import CaretGroup

from PySide6 import QtWidgets

ZOOM_STEP = 0.8


def zoom_in(toolbar: "RoundedToolBar", *args, **kwargs):
    """
    Zoom in action for the plot.

    Parameters
    ----------
    toolbar : RoundedToolBar
        The plot to zoom in.
    """
    vb = toolbar.plot.plot_item.getViewBox()
    vb.scaleBy((ZOOM_STEP, ZOOM_STEP))


def zoom_out(toolbar: "RoundedToolBar", *args, **kwargs):
    """
    Zoom out action for the plot.

    Parameters
    ----------
    toolbar : RoundedToolBar
        The plot to zoom out.
    """
    vb = toolbar.plot.plot_item.getViewBox()
    factor = 1.0 / ZOOM_STEP
    vb.scaleBy((factor, factor))


def reset_view(toolbar: "RoundedToolBar", *args, **kwargs):
    """
    Reset view action for the plot.

    Parameters
    ----------
    toolbar : RoundedToolBar
        The plot to reset the view.
    """
    vb = toolbar.plot.plot_item.getViewBox()
    vb.autoRange()


def add_selector(toolbar: "RoundedToolBar", toggled=None,  *args, **kwargs):
    """
    Add selector action for the plot.

    Parameters
    ----------
    toolbar : RoundedToolBar
        The plot to add the selector.
    """
    toolbar.plot.nav_plot_manager.add_navigation_selector_and_signal_plot()


def add_fft_selector(toolbar: "RoundedToolBar", *args, **kwargs):
    """
    Add FFT selector action for the plot.

    Parameters
    ----------
    toolbar : RoundedToolBar
        The plot to add the FFT selector.
    """
    toolbar.plot.add_fft_selector()


def toggle_navigation_plots(toolbar: "RoundedToolBar",
                        action_name="",
                        toggle=None,
                        *args,
                        **kwargs):
    """
    Makes a series of buttons to the side of the action bar for toggling/ adding
    additional navigation plots.

    Parameters
    ----------
    toolbar : RoundedToolBar
        The plot to toggle navigation plots.
    """
    if toolbar.plot.nav_plot_manager is None:
        raise RuntimeError("Plot does not have a navigation plot manager.")

    signal_options = toolbar.plot.nav_plot_manager.navigation_signals.keys()

    if action_name not in toolbar.action_widgets or toolbar.action_widgets[action_name].get("widget", None) is None:

        if toolbar.position == "left":
            caret_position = "right"
        elif toolbar.position == "right":
            caret_position = "left"
        elif toolbar.position == "bottom":
            caret_position = "top"
        else:
            caret_position = "bottom"

        group = CaretGroup("",
                           side=caret_position)
        layout = QtWidgets.QVBoxLayout()
        group.setLayout(layout)
        # group.setFlat(True) # needs be to set to True to avoid background (but adds wierd line in MacOS)
        # Ensure the parent has a layout and add the group to it
        parent = toolbar.parent()
        parent_layout = parent.layout()
        if parent_layout is None:
            parent_layout = QtWidgets.QVBoxLayout(parent)
            parent.setLayout(parent_layout)
        parent_layout.addWidget(group)
    else:
        group = toolbar.action_widgets[action_name]["widget"]
        layout = toolbar.action_widgets[action_name]["layout"]
    group.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)

    # Collect existing RoundedButton widgets in the layout keyed by their text
    current_buttons = {}
    for i in range(layout.count()):
        item = layout.itemAt(i)
        w = item.widget()
        if isinstance(w, RoundedButton):
            current_buttons[w.text()] = w

    for signal_name in signal_options:
        if signal_name not in current_buttons:
            button = RoundedButton(text=signal_name, parent=group)
            button.clicked.connect(lambda _,
                                   sn=signal_name: toolbar.plot.nav_plot_manager.set_navigation_manager_state(sn))
            layout.addWidget(button)
            current_buttons[signal_name] = button

    # Remove buttons that are no longer needed
    for btn_text, btn_widget in list(current_buttons.items()):
        if btn_text not in signal_options:
            layout.removeWidget(btn_widget)
            btn_widget.setParent(None)

    if toolbar.action_widgets.get(action_name, None) is None:
        print(f"Adding toolbar action widget: {action_name}")
        toolbar.add_action_widget(action_name, group, layout)

    if toggle is not None:
        group.setVisible(toggle)


def rebin2d(toolbar: "RoundedToolBar",
            scale_x:int,
            scale_y:int,
            *args,
            **kwargs):
    """
    Rebin 2D action for the plot.

    Parameters
    ----------
    toolbar : RoundedToolBar
        The plot to rebin.
    """

    current_selected_signal = toolbar.plot.plot_state.current_signal

    num_nav_axes = current_selected_signal.axes_manager.navigation_dimension
    if current_selected_signal.axes_manager.signal_dimension != 2:
        raise RuntimeError("Current signal is not 2D, cannot rebin2d.")

    scale = [1] * num_nav_axes + [scale_x, scale_y]

    return toolbar.plot.signal_tree.add_transformation(parent_signal=current_selected_signal,
                                                method="rebin",
                                                node_name=f"Rebin (x{scale_x}, y{scale_y})",
                                                scale=scale)
