from PySide6 import QtCore
from hyperspy.signal import BaseSignal

from typing import TYPE_CHECKING, Optional

from spyde.drawing.toolbars.plot_control_toolbar import get_toolbar_actions_for_plot
from spyde.drawing.toolbars.rounded_toolbar import RoundedToolBar

if TYPE_CHECKING:
    from spyde.drawing.multiplot import NavigationPlotManager, Plot

class PlotState:
    """
    A class to manage the state of a plot in the signal tree.  This includes things like
    brightness/contrast, current signal, colormap, number of dimensions.

    This is a little bit of an abstraction to separate the `Plot` class from the signals and save things like
    brightness/contrast settings for each signal independently.

    For Example if I select a different signal in the signal tree for some `Plot`, then plot.set_plot_state(new_state)
    will be called.  This will hide any children plots, remove any selectors, set the current_signal to the new signal,
    adjust the contrast/brightness, and then re-draw the plot.

    When set_plot_state is called a 1D plot can also be converted to a 2D plot or vice versa depending on the
    dimensionality of the new signal.

    """

    def __init__(
        self,
        signal: BaseSignal,
        plot: "Plot",
        dimensions: int = None,
        dynamic: bool = True,
    ):
        # Each PlotState is tied to a particular signal and a particular Plot instance
        # This allows us a unique state monitor for each signal/plot combination and
        # allows us to save things like brightness/contrast settings as well as the
        # current toolbars/selectors and child plots associated with this state.

        # This is ultimately what needs to be saved/restored when switching signals in a plot
        # and what needs to be serialized when (eventually) saving/loading a project.

        self.current_signal = signal
        self.plot = plot # type: "Plot"


        # Visualization parameters. The min/max percentile are used to determine the contrast/brightness
        self.min_percentile = 100
        self.max_percentile = 0
        self.min_level = 0
        self.max_level = 1
        self.colormap = "gray"  # default colormap

        self.dynamic = dynamic  # if the image/plot will update based on some selector.

        # Selectors which are tied to this particular "State" of the signal...
        # When the state is changed these selectors should be removed from the plot
        # And the children plots should be hidden. When the state is restored these
        # selectors and children plots should be restored/shown.
        # plot_selectors include things like Virtual Images.

        self.plot_selectors = []
        self.signal_tree_selectors = []

        self.toolbar_top = None  # type: Optional["RoundedToolBar"]
        self.toolbar_bottom = None  # type: Optional["RoundedToolBar"]
        self.toolbar_left = None  # type: Optional["RoundedToolBar"]
        self.toolbar_right = None  # type: Optional["RoundedToolBar"]

        self.plot_selectors_children = []  # child plots spawned from the plot selectors
        self.signal_tree_selectors_children = (
            []
        )  # child plots spawned from the signal tree selectors

        # for navigation plots make sure we transpose to get the plot dimensions correct...
        if dimensions is not None:
            self.dimensions = dimensions
        else:
            self.dimensions = self.current_signal.axes_manager.signal_dimension

        # Initialize toolbars for this plot state so that we can add actions to them
        self._initialize_toolbars()
        print("Initialized PlotState:", self)

    def __repr__(self):
        return (
            f"<PlotState signal={self.current_signal}, "
            f"dimensions={self.dimensions},"
            f" dynamic={self.dynamic}>"
        )

    def _initialize_toolbars(self):
        """
        Create a toolbar for this plot state if it doesn't already exist.
        """
        self.toolbar_right = RoundedToolBar(
            title="Plot Controls",
            plot_state=self,
            parent=self.plot.main_window,
            position="right",
        )
        self.toolbar_left = RoundedToolBar(
            title="Plot Controls",
            plot_state=self,
            parent=self.plot.main_window,
            position="left",
        )
        self.toolbar_top = RoundedToolBar(
            title="Plot Controls",
            plot_state=self,
            parent=self.plot.main_window,
            position="top",
        )
        self.toolbar_bottom = RoundedToolBar(
            title="Plot Controls",
            plot_state=self,
            parent=self.plot.main_window,
            position="bottom",
        )

        # Ensure they are visible
        for tb in (
            self.toolbar_right,
            self.toolbar_left,
            self.toolbar_top,
            self.toolbar_bottom,
        ):
            tb.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
            tb.show()

        functions, icons, names, toolbar_sides, toggles, params,  sub_functions = (
            get_toolbar_actions_for_plot(self)
        )

        # Add actions to the appropriate toolbars
        for func, icon, name, side, toggle, param, sub_function in zip(
                functions, icons, names, toolbar_sides, toggles, params, sub_functions
        ):
            print(f"Adding toolbar action: {name} to {side} toolbar")
            print(f"Function: {func}, Icon: {icon}, Toggle: {toggle}, Params: {param}")
            if side == "right":
                self.toolbar_right.add_action(name, icon, func, toggle, param, sub_function)
            elif side == "left":
                self.toolbar_left.add_action(name, icon, func, toggle, param, sub_function)
            elif side == "top":
                self.toolbar_top.add_action(name, icon, func, toggle, param, sub_function)
            elif side == "bottom":
                self.toolbar_bottom.add_action(name, icon, func, toggle, param, sub_function)

        for tb in [
            self.toolbar_right,
            self.toolbar_left,
            self.toolbar_top,
            self.toolbar_bottom,
        ]:
            tb.set_size()
            # if there are no actions hide the toolbar
            if tb.num_actions() == 0:
                tb.hide()
            else:
                tb.show()
            tb.raise_()
        # start with toolbars hidden
        self.hide_toolbars()

    def show_toolbars(self):
        for tb in [
            self.toolbar_right,
            self.toolbar_left,
            self.toolbar_top,
            self.toolbar_bottom,
        ]:
            if tb.num_actions() == 0:
                tb.hide()
            else:
                tb.show()
            tb.raise_()

    def update_toolbars(self):
        """
        Update the toolbars for this plot state.

        This is mostly useful for "refreshing" the toolbars after some change in state.
        """
        for tb in [
            self.toolbar_right,
            self.toolbar_left,
            self.toolbar_top,
            self.toolbar_bottom,
        ]:
            tb.set_size()
            # if there are no actions hide the toolbar
            if tb.num_actions() == 0:
                tb.hide()
            else:
                tb.show()
            tb.raise_()

    def hide_toolbars(self):
        for tb in [
            self.toolbar_right,
            self.toolbar_left,
            self.toolbar_top,
            self.toolbar_bottom,
        ]:
            #TODO: This should be handled better...
            if tb: # check if toolbar exists
                tb.hide()

class NavigationManagerState:
    """
    A class to manage the state of a navigation manager in the signal tree.

    This is a little bit of an abstraction to separate the `NavigationManager` class from the plots associated with
    it.  Each state is tied to a particular signal and Navigation Manager.
    """

    def __init__(
        self,
        signal: BaseSignal,
        plot_manager: "NavigationPlotManager",
    ):
        # only up to 4 navigation dimensions supported for now...
        dimensions = (
            signal.axes_manager.signal_dimension
            + signal.axes_manager.navigation_dimension
        )
        if dimensions > 4:
            raise ValueError(
                "NavigationManagerState only supports up to 4D signals for now."
            )

        if (
            signal.axes_manager.signal_dimension > 2
            or signal.axes_manager.navigation_dimension > 2
        ):
            #  Force it to be 2D signals for now...
            signal = signal.transpose(2)

        self.current_signal = signal  # the navigation signal for the current "state"
        self.plot_manager = plot_manager


        self.dimensions = [
            signal.axes_manager.signal_dimension,
            signal.axes_manager.navigation_dimension,
        ]

        # The list of plot states for each plot in the navigation manager

        print("this is the signal!", signal)

        # need to update for multiple dimensional navigators (5D STEM etc)
        self.plot_states = [
            PlotState(signal=signal, plot= self.plot_manager.plots[0], dimensions=dim)
            for dim in self.dimensions
            if dim > 0
        ]
