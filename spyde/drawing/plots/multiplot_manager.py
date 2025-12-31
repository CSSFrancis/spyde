from typing import TYPE_CHECKING, List, Dict, Tuple, Optional

if TYPE_CHECKING:
    from spyde.signal_tree import BaseSignalTree
    from spyde.__main__ import MainWindow
    from spyde.drawing.selectors import BaseSelector, IntegratingSelector2D
    from spyde.drawing.plots.plot import Plot
    from spyde.drawing.plots.plot_window import PlotWindow

from hyperspy.signal import BaseSignal
from spyde.drawing.update_functions import update_from_navigation_selection

import logging

logger = logging.getLogger(__name__)


class MultiplotManager:
    """
    A class to manage multiple `Plot` instances for navigation plots.

    There is only one `NavigationPlotManager` per `BaseSignalTree`. If we want to suplex
    multiple navigation plots. For example Time and Temperature in an in situ experiment,
    the selectors remain linked.

    Parameters
    ----------
    main_window : MainWindow
        The main window of the application.
    """

    def __init__(self, main_window: "MainWindow", signal_tree: "BaseSignalTree"):
        self.main_window = main_window  # type: MainWindow

        # For managing the navigation plots and the associated plot windows...
        self.plots = {}  # type: Dict["PlotWindow":List[Plot]]
        self.plot_windows = {}  # type: Dict["PlotWindow":Dict["PlotWindow"]]
        # all the navigation selectors on some plot window
        # Navigation selectors are linked across all navigation plots on the same Plot Window
        self.navigation_selectors = {}  # type: Dict["PlotWindow", List[BaseSelector]]

        self.signal_tree = signal_tree  # type: BaseSignalTree

        self.navigation_depth = 1  # type: int # depth of navigation signals

        if self.nav_dim < 1:
            raise ValueError(
                "NavigationPlotManager requires at least 1 navigation dimension."
            )
        elif self.nav_dim < 3:
            nav_plot_window = self.main_window.add_plot_window(
                is_navigator=True, plot_manager=self, signal_tree=self.signal_tree
            )
            nav_plot = nav_plot_window.add_new_plot()
            self.plot_windows[nav_plot_window] = (
                {}
            )  # single plot window with no children...
            self.plots[nav_plot_window] = [
                nav_plot,
            ]
            self.navigation_selectors[nav_plot_window] = []
            # Add navigation manager states for each navigation signal
            for signal in self.signal_tree.navigator_signals.values():
                self.add_plot_states_for_navigation_signals(signal)
            # create plot states for the nav plot
            self.add_navigation_selector_and_signal_plot(nav_plot_window)

        elif self.nav_dim < 5:
            # create two plot windows
            self.navigation_depth = 2
            plot_window = self.main_window.add_plot_window(
                is_navigator=True, plot_manager=self, signal_tree=self.signal_tree
            )
            nav_plot_1d = plot_window.add_new_plot()
            self.plot_windows[plot_window] = {}
            self.plots[plot_window] = [nav_plot_1d]
            self.navigation_selectors[plot_window] = []
            # Add navigation manager states for each navigation signal
            for signal in self.signal_tree.navigator_signals.values():
                self.add_plot_states_for_navigation_signals(signal)

            new_window = self.add_navigation_selector_and_signal_plot(plot_window)

            self.add_navigation_selector_and_signal_plot(new_window)

    @property
    def all_navigation_selectors(self) -> List["BaseSelector"]:
        """Return a list of all navigation selectors managed by this NavigationPlotManager."""
        selectors = []
        for sel_list in self.navigation_selectors.values():
            selectors.extend(sel_list)
        return selectors

    def add_plot_states_for_navigation_signals(self, signals: List[BaseSignal]):
        """Add navigation plot states for a list of signals.
        Parameters
        ----------
        signals : List[BaseSignal]
            The signals for which to add the navigation states.
        """
        # go level by level adding states
        print("Adding navigation plot states for signals:", signals)
        print(self.plot_windows)
        for plot_window in self.plot_windows:
            for plot in self.plots[plot_window]:
                print("Adding navigation plot state for plot:", plot)
                dim = signals[0].axes_manager.navigation_dimension
                plot.add_plot_state(
                    signal=signals[0],
                    dimensions=dim,
                    dynamic=False,
                )
            if len(signals) > 1:
                for sub_plot_windows in self.plot_windows[plot_window]:
                    for plot in self.plots[sub_plot_windows]:
                        dim = signals[1].axes_manager.signal_dimension
                        plot.add_plot_state(
                            signal=signals[1],
                            dimensions=dim,
                            dynamic=True,
                        )

    @property
    def navigation_signals(self) -> dict[str:BaseSignal]:
        """Return a list of navigation signals managed by this NavigationPlotManager."""
        return self.signal_tree.navigator_signals

    @property
    def nav_dim(self) -> int:
        """
        Get the number of navigation dimensions in the signal tree.
        """
        return self.signal_tree.nav_dim

    def get_plot_window_level(
        self, plot_window: "PlotWindow"
    ) -> Tuple[int, Optional[dict]]:
        """
        Get the level of a PlotWindow in the navigation hierarchy and return its immediate
        parent's children dictionary so it can be edited.

        Returns
        -------
        (level, parent_children_dict)
            level : int
                0 for top-level, 1 for first child, etc.
            parent_children_dict : dict or None
                The nested dictionary in `self.plot_windows` whose keys include `plot_window`
                (i.e. the immediate parent's children mapping), or None if `plot_window` is top-level.
        """
        level = 1
        current_window = plot_window
        children_dictionary = self.plot_windows.get(
            plot_window, None
        )  # type: Optional[dict]
        while True:
            parent_found = False
            for pw, children in self.plot_windows.items():
                if current_window in children:
                    level += 1
                    if children_dictionary is None:
                        children_dictionary = children
                    current_window = pw
                    parent_found = True
                    break
            if not parent_found:
                break
        return level, children_dictionary

    def add_navigation_selector_and_signal_plot(
        self, plot_window: "PlotWindow", selector_type=None
    ) -> "PlotWindow":
        """
        Add a Selector (or Multi-selector) to a PlotWindow.  This will add a selector to all the
        Plots in one PlotWindow. Creating one Child Plot.

        """
        from spyde.drawing.selectors import (
            IntegratingSelector1D,
            IntegratingSelector2D,
            BaseSelector,
        )

        # if the plot is a navigator then all the Plots in the window have to have the same
        # size...
        dim = plot_window.dimensions

        print(
            "Adding navigation selector to plot window:", plot_window, " with dim:", dim
        )
        if dim == 1 and selector_type is None:
            selector_type = IntegratingSelector1D
        elif dim == 2 and selector_type is None:
            selector_type = IntegratingSelector2D
        elif not isinstance(selector_type, BaseSelector):
            raise ValueError("Type must be a BaseSelector class.")

        window_level, children_dict = self.get_plot_window_level(
            plot_window=plot_window
        )
        print("Plot window level:", window_level, " children dict:", children_dict)
        print(self.plot_windows)
        print(self.navigation_depth)
        if window_level < self.navigation_depth:
            is_navigator = True
        else:
            is_navigator = False

        if plot_window not in self.navigation_selectors:
            self.navigation_selectors[plot_window] = []

        window = self.main_window.add_plot_window(
            is_navigator=is_navigator,
            plot_manager=self,
            signal_tree=self.signal_tree,
        )

        # add a new level to the children dictionary
        children_dict[window] = {}

        child = window.add_new_plot()
        # create plot states for the child plot
        if window not in self.plots:
            self.plots[window] = []
        self.plots[window].append(child)

        # Parent should be all the plots in the plot window
        parent = plot_window.current_plot_item

        selector = selector_type(
            parent=plot_window,
            children=child,
            multi_selector=True,
            update_function=update_from_navigation_selection,
        )

        self.navigation_selectors[plot_window].append(selector)
        plot_window.last_used_selector = selector

        if is_navigator:
            for signal in self.signal_tree.navigator_signals.values():
                self.add_plot_states_for_navigation_signals(signal)
        else:
            self.signal_tree.create_plot_states(plot=child)

        logger.info("Added Child plot states: ", child.plot_states)
        # Auto range...
        selector.update_data()
        child.update_data(child.current_data, force=False)
        logger.info("Auto-ranging child plot")
        child.getViewBox().autoRange()
        self.signal_tree.signal_plots.append(child)
        child.needs_auto_level = True
        logger.info("Added navigation selector and signal plot:", selector, child)
        return window
