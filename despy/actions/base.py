
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from despy.drawing.toolbars.rounded_toolbar import RoundedToolBar
from despy.drawing.toolbars.floating_button_trees import RoundedButton, ButtonTree
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
        group = CaretGroup(title="",
                           toolbar=toolbar,
                           action_name=action_name,
                           auto_attach=True)
        layout = group.layout()
        toolbar.add_action_widget(action_name, group, layout)
    else:
        group = toolbar.action_widgets[action_name]["widget"]
        layout = toolbar.action_widgets[action_name]["layout"]

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

    # add final button for adding a new navigation plot using a system dialog
    #add_button_name = "+ Add Plot"
    #if add_button_name not in current_buttons:
    #    add_button = RoundedButton(text=add_button_name, parent=group)
    #    add_button.clicked.connect(lambda _: toolbar.plot.nav_plot_manager.add_navigation_plot_via_dialog())
    #    layout.addWidget(add_button)
    #    current_buttons[add_button_name] = add_button

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


def toggle_signal_tree(toolbar: "RoundedToolBar",
                        action_name="",
                        toggle=None,
                        *args,
                        **kwargs):
    """Makes a series of buttons to the side of the action bar for switching between different signal plots.

    This is similar to toggle_navigation_plots, but for signal plots and instead of creating a list
    of buttons it creates a tree of buttons representing different signals in the signal tree.

    Parameters
    ----------
    toolbar : RoundedToolBar
        The plot to toggle navigation plots.
    """

    signal_tree = toolbar.plot.signal_tree._tree


    # we can can simplify this tree into just buttons
    # [root]: {child1: {..}, child2: {..}, ...}

    def node2button(key, node):
        button = RoundedButton(text=key, parent=None)
        button.clicked.connect(lambda _, n=node: toolbar.plot.set_plot_state(n["signal"]))
        return button

    def tree2buttons(tree):
        new_tree = {}
        if not tree:
            return None
        for key, node in tree.items():
            button = node2button(key, node)
            if "children" in node and node["children"]:
                new_tree[button] = tree2buttons(node["children"])
            else:
                new_tree[button] = {}
        return new_tree
    button_tree_dict = tree2buttons(signal_tree)

    if action_name not in toolbar.action_widgets or toolbar.action_widgets[action_name].get("widget", None) is None:
        group = CaretGroup(title="",
                           toolbar=toolbar,
                           action_name=action_name,
                           auto_attach=True)
        layout = group.layout()
        toolbar.add_action_widget(action_name, group, layout)


        button_tree = ButtonTree("Signal Tree",
                                 button_tree_dict,
                                 )

        layout.addWidget(button_tree)

    else:
        group = toolbar.action_widgets[action_name]["widget"]
        layout = toolbar.action_widgets[action_name]["layout"]

    if toolbar.action_widgets.get(action_name, None) is None:
        print(f"Adding toolbar action widget: {action_name}")
        toolbar.add_action_widget(action_name, group, layout)

    if toggle is not None:
        group.setVisible(toggle)
