from hyperspy.signal import BaseSignal

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from despy.drawing.multiplot import NavigationPlotManager, Plot


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

    def __init__(self,
                 signal: BaseSignal,
                 dimensions: int = None,
                 dynamic: bool = True,
                 ):
        self.current_signal = signal

        # Visualization parameters
        self.brightness_max = 1
        self.brightness_min = 0
        self.dynamic = dynamic  # if the image/plot will update based on some selector.

        # Selectors which are tied to this particular "State" of the signal...
        # When the state is changed these selectors should be removed from the plot
        # And the children plots should be hidden. When the state is restored these
        # selectors and children plots should be restored/shown.
        self.plot_selectors = []
        self.signal_tree_selectors = []

        self.plot_selectors_children = []  # child plots spawned from the plot selectors
        self.signal_tree_selectors_children = []  # child plots spawned from the signal tree selectors

        # for navigation plots make sure we transpose to get the plot dimensions correct...
        if dimensions is not None:
            self.dimensions = dimensions
        else:
            self.dimensions = self.current_signal.axes_manager.signal_dimension

    def __repr__(self):
        return (f"<PlotState signal={self.current_signal}, "
                f"dimensions={self.dimensions},"
                f" dynamic={self.dynamic}>")


class NavigationManagerState:
    """
    A class to manage the state of a navigation manager in the signal tree.

    This is a little bit of an abstraction to separate the `NavigationManager` class from the plots associated with
    it.  Each state is tied to a particular signal and Navigation Manager.
    """

    def __init__(self,
                 signal: BaseSignal,
                 plot_manager: "NavigationPlotManager",
                 ):
        # only up to 4 navigation dimensions supported for now...
        dimensions = signal.axes_manager.signal_dimension + signal.axes_manager.navigation_dimension
        if dimensions > 4:
            raise ValueError("NavigationManagerState only supports up to 4D signals for now.")

        if signal.axes_manager.signal_dimension > 2 or signal.axes_manager.navigation_dimension > 2:
            #  Force it to be 2D signals for now...
            signal = signal.transpose(2)

        self.current_signal = signal  # the navigation signal for the current "state"
        self.plot_manager = plot_manager

        self.dimensions = [signal.axes_manager.signal_dimension, signal.axes_manager.navigation_dimension]

        # The list of plot states for each plot in the navigation manager
        self.plot_states = [PlotState(signal=signal, dimensions=dim) for dim in self.dimensions if dim > 0]


