"""
Module for managing multiple plots, specifically navigation plots, but also handling Virtual Images
and other multi-plot scenarios.

The idea is that there are cases where you have multiple images which represent
things like different Virtual Images, different channels, etc.  These images
can be toggled between in the same plot area. In addition, you might want to overlay
multiple image at once, adjusting their opacities independently. Or you might want
to create a grid of images.

In the case of 1D Spectra this could be multiple spectra overlaid, or stacked, etc.
In the case of 2D images this could be multiple images in a grid.

This functionality is shared between multiple classes. The most common
use case is the NavigationPlotManager, but it is also used to manage multiple Virtual
Images.
"""

from typing import TYPE_CHECKING, List, Union

from hyperspy.signal import BaseSignal

from spyde.drawing.plot import Plot, PlotWindow
from spyde.drawing.plot_states import PlotState
from spyde.drawing.update_functions import update_from_navigation_selection

if TYPE_CHECKING:
    from spyde.__main__ import MainWindow
    from spyde.signal_tree import BaseSignalTree

class MultiplotManager:
    """
    A class to manage multiple `Plot` instances for general multi-plot scenarios.

    Parameters
    ----------
    main_window : MainWindow
        The main window of the application.
    dimensions : List[int]
        The dimensions of the plots to be managed. For example [2,] is a 2D plot, [1,2] is a 1D and 2D plot.
    signal_tree : BaseSignalTree
        The signal tree associated with the plots. Every plot needs to have a "signal tree" and be associated
        with a `BaseSignalTree` instance.

    """

    def __init__(self,
                 main_window: "MainWindow",
                 dimensions:List[int],
                 signal_tree: "BaseSignalTree"):

        self.main_window = main_window  # type: MainWindow
        self.plots = []  # type: List[Plot]
        self.dimensions = dimensions  # type: List[int]
        self.signal_tree = signal_tree # type: BaseSignalTree
        for dim in self.dimensions:
            plot = Plot(
                signal_tree=signal_tree,
                is_navigator=True, # this should be changed to something else
                dimensions=dim,
            )
            self.plots.append(plot)


class NavigationPlotManager:
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
        self.plots = []  # type: List[PlotWindow]

        self.navigation_selectors = []  # type: List[BaseSelector]
        self.signal_tree = signal_tree  # type: BaseSignalTree
        self.navigation_manager_states = (
            dict()
        )  # type: dict[BaseSignal:NavigationManagerState]
        self.navigation_manager_state = None  # type: NavigationManagerState | None

        print(f"NavigationPlotManager: dim:{self.nav_dim}")
        if self.nav_dim < 1:
            raise ValueError(
                "NavigationPlotManager requires at least 1 navigation dimension."
            )
        elif self.nav_dim < 3:
            # create the navigation plot
            plot_window = PlotWindow(is_navigator=True,
                                     plot_manager=self,
                                     signal_tree=self.signal_tree,
                                     main_window=self.main_window)
            nav_plot = Plot(
                signal_tree=self.signal_tree,
                is_navigator=True,
                nav_plot_manager=self,
            )
            plot_window.plot_widget.addItem(nav_plot)
            self.plots.append(plot_window)
            # create plot states for the nav plot
        for signal in self.signal_tree.navigator_signals.values():
            self.add_state(signal)

        print("Setting initial navigation manager state")
        print(list(self.signal_tree.navigator_signals.values())[0])
        self.set_navigation_manager_state(
            list(self.signal_tree.navigator_signals.values())[0]
        )

        # Add the navigation selector and signal plot
        self.add_navigation_selector_and_signal_plot()

    def add_state(self, signal: BaseSignal):
        """Add a navigation manager state for some signal.
        Parameters
        ----------
        signal : BaseSignal
            The signal for which to add the navigation state.
        """
        self.navigation_manager_states[BaseSignal] = NavigationManagerState(
            signal=signal, plot_manager=self
        )

        dim = self.navigation_manager_states[BaseSignal].dimensions
        print("Adding navigation state for signal:", signal, " with dimensions:", dim)
        dim = [d for d in dim if d > 0]
        for plot, d in zip(self.plots, dim):
            plot.plot_states[signal] = PlotState(
                signal=signal,
                plot=plot,
                dimensions=d,
                dynamic=False,  # False for anything under 2?
            )

    @property
    def navigation_signals(self) -> dict[str:BaseSignal]:
        """Return a list of navigation signals managed by this NavigationPlotManager."""
        return self.signal_tree.navigator_signals

    def set_navigation_manager_state(self, signal: Union[BaseSignal, str]):
        """Set the navigation state to the state for some signal.

        Parameters
        ----------
        signal : BaseSignal | str
            The signal for which to set the navigation state.
        """
        print(self.navigation_manager_states)
        print("Setting navigation manager state for signal:", signal)
        if isinstance(signal, str):
            signal = self.navigation_signals[signal]
        self.navigation_manager_state = self.navigation_manager_states.get(
            signal, NavigationManagerState(signal=signal, plot_manager=self)
        )
        for plot in self.plots:
            # create plot states for the child plot if it does not exist
            plot.set_plot_state(signal)

    @property
    def nav_dim(self) -> int:
        """
        Get the number of navigation dimensions in the signal tree.
        """
        return self.signal_tree.nav_dim

    def add_navigation_selector_and_signal_plot(self, selector_type=None):
        """
        Add a Selector (or Multi-selector) to the navigation plots. For 2+ dimensional
        navigation signals, multiple-linked selectors will be created.
        """
        from spyde.drawing.selector import (
            IntegratingLinearRegionSelector,
            IntegratingRectangleSelector,
            BaseSelector,
        )

        if self.nav_dim == 1 and selector_type is None:
            selector_type = IntegratingLinearRegionSelector
        elif self.nav_dim == 2 and selector_type is None:
            selector_type = IntegratingRectangleSelector
        elif not isinstance(selector_type, BaseSelector):
            raise ValueError("Type must be a BaseSelector class.")
        # need to add an N-D Selector

        if self.nav_dim > 2:
            raise NotImplementedError(
                "Navigation selectors for >2D navigation not implemented yet."
            )
        else:
            child = Plot(
                signal_tree=self.signal_tree,
                is_navigator=False,
            )
            # create plot states for the child plot
            self.signal_tree.create_plot_states(plot=child)

            logger.info("Added Child plot states: ", child.plot_states)
            selector = selector_type(
                parent=self.plots[0],
                children=child,
                update_function=update_from_navigation_selection,
            )
            child.set_plot_state(list(child.plot_states.keys())[0])
            self.navigation_selectors.append(selector)
            # Auto range...
            selector.update_data()
            child.update_data(child.current_data, force=True)
            logger.info("Auto-ranging child plot")
            child.plot_item.getViewBox().autoRange()
            self.signal_tree.signal_plots.append(child)
            child.needs_auto_level = True
            logger.info("Added navigation selector and signal plot:", selector, child)