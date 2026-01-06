from functools import partial
from typing import TYPE_CHECKING

import numpy as np
import hyperspy.api as hs
from spyde.drawing.update_functions import get_fft


if TYPE_CHECKING:
    from spyde.drawing.toolbars.toolbar import RoundedToolBar
from spyde.drawing.toolbars.floating_button_trees import RoundedButton, ButtonTree
from spyde.drawing.toolbars.caret_group import CaretGroup

from spyde.drawing.selectors import RectangleSelector

from PySide6 import QtWidgets, QtCore, QtGui

ZOOM_STEP = 0.8
NAVIGATOR_DRAG_MIME = "application/x-spyde-navigator"


def zoom_in(toolbar: "RoundedToolBar", *args, **kwargs):
    """
    Zoom in action for the plot.

    Parameters
    ----------
    toolbar : RoundedToolBar
        The plot to zoom in.
    """
    vb = toolbar.plot.getViewBox()
    vb.scaleBy((ZOOM_STEP, ZOOM_STEP))


def zoom_out(toolbar: "RoundedToolBar", *args, **kwargs):
    """
    Zoom out action for the plot.

    Parameters
    ----------
    toolbar : RoundedToolBar
        The plot to zoom out.
    """
    vb = toolbar.plot.getViewBox()
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
    vb = toolbar.plot.getViewBox()
    vb.autoRange()


def add_selector(toolbar: "RoundedToolBar", toggled=None, *args, **kwargs):
    """
    Add selector action for the plot.

    Parameters
    ----------
    toolbar : RoundedToolBar
        The plot to add the selector.
    """
    toolbar.plot.multiplot_manager.add_navigation_selector_and_signal_plot(
        toolbar.plot_window
    )


def add_fft_selector(toolbar: "RoundedToolBar",
                     action_name="",
                     *args, **kwargs):
    """
    Add FFT selector action for the plot.

    The FFT selector allows selecting a region in the navigation plot to compute and display its FFT. It
    is toggled on and off via the toolbar.


    toolbar --> register_action_plot_item
    toolbar --> register_action_plot_window



    Parameters
    ----------
    toolbar : RoundedToolBar
        The plot to add the FFT selector.

    """

    # initialize a new plot window for the FFT when first clicked...
    print("Action widgets:", toolbar.action_widgets)
    print(action_name)

    if (action_name in toolbar.action_widgets and
        "plot_windows" in toolbar.action_widgets[action_name] and
        "FFT_Plot_Window" in toolbar.action_widgets[action_name]["plot_windows"]):
        print("FFT selector already initialized.")
        return
    else:
        plot = toolbar.plot
        m_window = plot.main_window
        signal_tree = plot.signal_tree
        plot_window = m_window.add_plot_window(
            is_navigator=False, signal_tree=signal_tree)

        fft_plot = plot_window.add_new_plot()
        place_holder_signal = hs.signals.Signal2D(
            data=np.zeros((10, 10)),)

        selector = RectangleSelector(
            parent=plot,
            children=fft_plot,
            multi_selector=False,
            update_function=get_fft,

        )

        # Connect parent plot updates to trigger FFT updates
        if hasattr(plot, 'image_item'):
            up_force = partial(selector.delayed_update_data, force=True)
            plot.image_item.sigImageChanged.connect(up_force)

        fft_plot.add_plot_state(signal=place_holder_signal,
                                dimensions=2,
                                dynamic=True,
                                )
        toolbar.register_action_plot_item(action_name=action_name,
                                          item=selector.roi,
                                          key="RectangleSelector_FFT")

        toolbar.register_action_plot_window(action_name=action_name,
                                           plot_window=plot_window,
                                            key="FFT_Plot_Window")

    print("Action widgets after FFT init:", toolbar.action_widgets)


class NavigatorButton(RoundedButton):
    """Rounded button that supports click-to-select and drag-to-create behavior."""

    def __init__(self, label: str, signal, toolbar: "RoundedToolBar"):
        super().__init__(text=label, parent=toolbar)
        self.signal = signal
        self.toolbar = toolbar
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._drag_origin = QtCore.QPointF()
        self._allow_click = False

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        current_plot_window = self.toolbar.plot_window
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._drag_origin = event.position()
            self._allow_click = True
            print("Saving current plot state for navigator drag...")
            current_plot_window.previous_subplots_pos = (
                current_plot_window.plot_widget.ci.items.copy()
            )  # shallow copy
            print(current_plot_window.plot_widget.ci.items)
            current_plot_window.previous_graphics_layout_widget = (
                current_plot_window.plot_widget
            )

        # on enter, save the current layout
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._allow_click and event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            delta = event.position() - self._drag_origin
            if (
                abs(delta.x()) + abs(delta.y())
                >= QtWidgets.QApplication.startDragDistance()
            ):
                self._allow_click = False
                self._start_drag()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._allow_click and event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._allow_click = False
            mw = self.toolbar.plot.main_window
            active_plot = mw._active_plot()
            if active_plot is not self.toolbar.plot:
                mw.statusBar().showMessage(
                    "Activate this plot before assigning a navigator", 4000
                )
                super().mouseReleaseEvent(event)
                return
            mw.set_pending_navigator_assignment(
                self.signal,
                self.toolbar.plot.multiplot_manager,
                target_plot=active_plot,
            )
        super().mouseReleaseEvent(event)

    def _start_drag(self) -> None:
        mw = self.toolbar.plot.main_window
        token = mw.register_navigator_drag_payload(
            self.signal, self.toolbar.plot.multiplot_manager
        )
        drag = QtGui.QDrag(self)
        mime = QtCore.QMimeData()
        mime.setData(NAVIGATOR_DRAG_MIME, token.encode("utf-8"))
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.exec(QtCore.Qt.DropAction.CopyAction)


def toggle_navigation_plots(
    toolbar: "RoundedToolBar", action_name="", toggle=None, *args, **kwargs
):
    """
    Makes a series of buttons to the side of the action bar for toggling/ adding
    additional navigation plots.

    Parameters
    ----------
    toolbar : RoundedToolBar
        The plot to toggle navigation plots.
    """
    if toolbar.plot.multiplot_manager is None:
        raise RuntimeError("Plot does not have a navigation plot manager.")

    signal_options = toolbar.plot.multiplot_manager.navigation_signals

    first_init = (
        action_name not in toolbar.action_widgets
        or toolbar.action_widgets[action_name].get("widget", None) is None
    )

    if first_init:
        group = CaretGroup(
            title="", toolbar=toolbar, action_name=action_name, auto_attach=True
        )
        layout = group.layout()
        toolbar.add_action_widget(action_name, group, layout)
        group._update_margins()
        group._update_mask()
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

    for signal_name, signal in signal_options.items():
        if signal_name not in current_buttons:
            button = NavigatorButton(signal_name, signal, toolbar)
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

    if first_init:
        navigator_action = None
        for action in toolbar.actions():
            print("Action text:", action.text())
            if action.text() == "Select Navigator":
                navigator_action = action
        if navigator_action is not None:
            # Simulate clicking the "Select Navigator" action
            navigator_action.trigger()


def rebin2d(toolbar: "RoundedToolBar", scale_x: int, scale_y: int, *args, **kwargs):
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

    return toolbar.plot.signal_tree.add_transformation(
        parent_signal=current_selected_signal,
        method="rebin",
        node_name=f"Binned",
        scale=scale,
    )


def toggle_signal_tree(
    toolbar: "RoundedToolBar", action_name="", toggle=None, *args, **kwargs
):
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
        button.clicked.connect(
            lambda _, n=node: toolbar.plot.set_plot_state(n["signal"])
        )
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

    if action_name not in toolbar.action_widgets:
        group = CaretGroup(
            title="", toolbar=toolbar, action_name=action_name, auto_attach=True
        )
        layout = group.layout()
        button_tree = ButtonTree("Signal Tree", button_tree_dict)
        layout.addWidget(button_tree)
        toolbar.add_action_widget(action_name, group, layout)
        group._update_margins()
        group._update_mask()
    else:
        group = toolbar.action_widgets[action_name]["widget"]
        layout = toolbar.action_widgets[action_name]["layout"]
        for i in range(layout.count()):
            w = layout.itemAt(i).widget()
            if isinstance(w, ButtonTree):
                layout.removeWidget(w)
                w.hide()

        button_tree = ButtonTree("Signal Tree", button_tree_dict)
        layout.addWidget(button_tree)
    if toggle is not None:
        group.setVisible(toggle)
