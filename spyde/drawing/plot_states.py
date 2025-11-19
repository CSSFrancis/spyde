from __future__ import annotations
from PySide6 import QtCore
from hyperspy.signal import BaseSignal

from typing import TYPE_CHECKING, Optional, List

from spyde.drawing.toolbars.plot_control_toolbar import get_toolbar_actions_for_plot
from spyde.drawing.toolbars.rounded_toolbar import RoundedToolBar

if TYPE_CHECKING:
    from spyde.drawing.multiplot import NavigationPlotManager, Plot


class PlotState:
    """
    Represents the complete visualization state for a (Plot, Signal) pair.

    Stores:
      - Current signal and dimensionality
      - Contrast / brightness (levels and percentiles)
      - Colormap choice
      - Dynamic / selector-driven plotting flag
      - Active selectors and any child plots they spawned
      - Four side toolbars (top/bottom/left/right) whose actions depend on signal type & dimensionality

    A Plot holds (and switches between) multiple PlotState instances when the user changes
    the active signal. Restoring a PlotState re-applies its selectors, toolbars, and visual parameters.
    """

    def __init__(
        self,
        signal: BaseSignal,
        plot: "Plot",
        dimensions: Optional[int] = None,
        dynamic: bool = True,
    ):
        # Each PlotState is tied to a particular signal and a particular Plot instance
        # This allows us a unique state monitor for each signal/plot combination and
        # allows us to save things like brightness/contrast settings as well as the
        # current toolbars/selectors and child plots associated with this state.

        # This is ultimately what needs to be saved/restored when switching signals in a plot
        # and what needs to be serialized when (eventually) saving/loading a project.

        self.current_signal: BaseSignal = signal
        self.plot: "Plot" = plot

        # Visualization parameters. The min/max percentile are used to determine the contrast/brightness
        self.min_percentile = 100
        self.max_percentile = 0
        self.min_level = 0
        self.max_level = 1
        self.colormap = "gray"  # default colormap

        self.dynamic: bool = (
            dynamic  # if the image/plot will update based on some selector.
        )

        # Selectors which are tied to this particular "State" of the signal...
        # When the state is changed these selectors should be removed from the plot
        # And the children plots should be hidden. When the state is restored these
        # selectors and children plots should be restored/shown.
        # plot_selectors include things like Virtual Images.

        self.plot_selectors: List[object] = []
        self.signal_tree_selectors: List[object] = []

        self.toolbar_top: Optional[RoundedToolBar] = None
        self.toolbar_bottom: Optional[RoundedToolBar] = None
        self.toolbar_left: Optional[RoundedToolBar] = None
        self.toolbar_right: Optional[RoundedToolBar] = None

        self.plot_selectors_children: List["Plot"] = []
        self.signal_tree_selectors_children: List["Plot"] = []

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

    def _initialize_toolbars(self) -> None:
        """Create (or recreate) the four side toolbars for this state and populate them with actions."""
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

        functions, icons, names, toolbar_sides, toggles, params, sub_functions = (
            get_toolbar_actions_for_plot(self)
        )

        # Add actions to the appropriate toolbars
        for func, icon, name, side, toggle, param, sub_function in zip(
            functions, icons, names, toolbar_sides, toggles, params, sub_functions
        ):
            print(f"Adding toolbar action: {name} to {side} toolbar")
            print(f"Function: {func}, Icon: {icon}, Toggle: {toggle}, Params: {param}")
            if side == "right":
                self.toolbar_right.add_action(
                    name, icon, func, toggle, param, sub_function
                )
            elif side == "left":
                self.toolbar_left.add_action(
                    name, icon, func, toggle, param, sub_function
                )
            elif side == "top":
                self.toolbar_top.add_action(
                    name, icon, func, toggle, param, sub_function
                )
            elif side == "bottom":
                self.toolbar_bottom.add_action(
                    name, icon, func, toggle, param, sub_function
                )

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

    def show_toolbars(self) -> None:
        """Show all toolbars that have at least one action."""
        for tb in [
            self.toolbar_right,
            self.toolbar_left,
            self.toolbar_top,
            self.toolbar_bottom,
        ]:
            if tb is None:
                pass
            elif tb.num_actions() == 0:
                tb.hide()
            else:
                tb.show()
            tb.raise_()

    def update_toolbars(self) -> None:
        """Recompute size/visibility for each toolbar after external changes to actions."""
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

    def hide_toolbars(self) -> None:
        """Hide all toolbars for this state (used when the PlotState becomes inactive)."""
        for tb in [
            self.toolbar_right,
            self.toolbar_left,
            self.toolbar_top,
            self.toolbar_bottom,
        ]:
            # TODO: This should be handled better...
            if tb:  # check if toolbar exists
                tb.hide()

    def close(self) -> None:
        self.hide_toolbars()
        for attr in ("toolbar_right", "toolbar_left", "toolbar_top", "toolbar_bottom"):
            tb = getattr(self, attr, None)
            if tb is not None:
                try:
                    tb.plot = None
                    tb.close()
                    setattr(self, attr, None)
                except Exception:
                    pass


class NavigationManagerState:
    """State container for a NavigationPlotManager.

    Wraps a navigation-capable signal and builds the required PlotState list
    corresponding to (signal_dimension, navigation_dimension). Only up to 4D total supported.
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

        self.current_signal: BaseSignal = signal
        self.plot_manager: "NavigationPlotManager" = plot_manager

        self.dimensions: List[int] = [
            signal.axes_manager.signal_dimension,
            signal.axes_manager.navigation_dimension,
        ]

        # The list of plot states for each plot in the navigation manager

        print("this is the signal!", signal)

        # need to update for multiple dimensional navigators (5D STEM etc)
        self.plot_states: List[PlotState] = [
            PlotState(signal=signal, plot=self.plot_manager.plots[0], dimensions=dim)
            for dim in self.dimensions
            if dim > 0
        ]
