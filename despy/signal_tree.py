from hyperspy.signal import BaseSignal


from typing import TYPE_CHECKING, Union, List

if TYPE_CHECKING:
    from despy.drawing.plot_states import PlotState
    from despy.main_window import MainWindow

from despy.drawing.toolbars import SIGNAL_TOOLBARS
from despy.drawing.multiplot import NavigationPlotManager, Plot


class BaseSignalTree:
    """
    A class to manage the signal tree. This class manages the tree of different signals
    after some transformation has been applied.  The idea is that you can toggle between
    the different signals to see the effects of transformations such as filtering, centering
    the direct beam, azimuthal integration, etc.

    For example, you might have a tree like this:
                                              -/-> [FEM Variance]
                                            /
               --> [denoise filter] --> [centered] --> [azimuthal integration]
             /
    [root signal]
             \
              --> [centered] --> [get_diffraction_vectors] --> [strain matrix] -/-> [strain maps]
                        \
                         -/-> [get_virtual_image]

    -----------------------------------------------------------------------------------------------

                                           -/-> [Bright-field](toggle visible/not visible)
                                         /
       [navigator] --> [signal] --> [Centered]
                                         \
                                          -/-> [Dark-field] (toggle visible/not visible)

    -----------------------------------------------------------------------------------------------
    -----------------------------------------------------------------------------------------------
    Then you can select the different steps in the tree to see the data computed at that point.

    The idea is that a lot of the `map` like transformations are non-breaking.  These are transformations
    where the navigator is still valid. For example.

    In contrast, a non-breaking function will
    just update the current "signal" plot with the new data. Toggling back to the previous fork in the tree will
    allow you to see the data along the way.


    Each

    Parameters
    ----------
    root_signal : BaseSignal
        The root signal of the tree.
    main_window : MainWindow
        The main window of the application.
    distributed_client : distributed.Client, optional
        The Dask client to use for computations.

    """

    def __init__(self,
                 root_signal: BaseSignal,
                 main_window: "MainWindow",
                 distributed_client=None
                 ):

        # The root signal of the tree
        self.root = root_signal  # type: BaseSignal
        self.main_window = main_window  # type: MainWindow

        # There is only one navigator.  Currently, having more than one navigator makes things very complicated.
        # I want to try to minimize the number of plots.  If for example someone has a 5D STEM signal, and they want
        # to play with the time axis then they should use the virtual imaging tools and do it that way.
        self.navigator_signals = dict()  # type: dict[str:BaseSignal] # only 1

        # The tree structure. This defines the relationship between signals.
        # i.e. parent -> child.  Broken transformations create new seeds and
        # spawn new trees.
        self._tree = {"root": {"signal": root_signal, "children": {}}}  # type: dict

        # set up the navigator plots:
        navigator = self._initialize_navigator(root_signal)
        self.navigator_signals["base"] = navigator

        self.client = distributed_client
        self.signal_plots = []  # type: Union[List[Plot], None]

        # setting up plots
        self.navigator_plot_manager = NavigationPlotManager(main_window=main_window,
                                                            signal_tree=self)  # type: NavigationPlotManager

    def _preprocess_navigator(self,
                              signal: BaseSignal) -> BaseSignal:
        """
        Preprocess the navigator signal before adding it to the navigator plot manager.
        """
        if ((signal.axes_manager.navigation_shape + signal.axes_manager.signal_shape) !=
                self.root.axes_manager.navigation_shape):
            raise ValueError("Navigator signal must have the same total number of dimensions as the root signal."
                             "and the same shape")
        if signal.axes_manager.signal_dimension == 0:
            signal = signal.T
        return signal

    def add_navigator_signal(self,
                             name: str,
                             signal: BaseSignal):
        """
        This adds a navigator plot to the signal tree.  The idea being that a signal tree can have multiple
        navigator signals but only 1 navigator plot (or multi-plot).  Eventually it would be nice to add the
        ability to multi-plex navigator plots. For example temp and time in an in-situ experiment.

        Parameters
        ----------
        name : str
            The name of the navigator signal.
        signal : BaseSignal
            The navigator signal to add.
        """
        signal = self._preprocess_navigator(signal)
        self.navigator_signals[name] = signal
        self.navigator_plot_manager.add_state(signal)

    def _initialize_navigator(self, signal: BaseSignal):
        """
        Populate the navigator plots based on the root signal.

        Recursively create navigator plots to account for dimensions greater than 2. Eventually this should
        support things like EELS line spectra.

        Parameters
        ----------
        nav_signal : BaseSignal
            The signal to populate the navigator plots for.
        """
        if signal.axes_manager.navigation_dimension == 0:
            # single image or spectrum... self.navigator_plots is empty
            return
        else:  # root_signal.axes_manager.navigation_dimension >= 1:
            if signal._lazy and signal.navigator is not None:
                navigation_signal = signal.navigator
            else:  # sum over signal axes to compute the navigation signal
                navigation_signal = signal.sum(signal.axes_manager.signal_axes)
                if navigation_signal._lazy:
                    navigation_signal.compute()
            if not isinstance(navigation_signal, BaseSignal):  # if numpy array
                navigation_signal = BaseSignal(navigation_signal)

        navigation_signal = self._preprocess_navigator(navigation_signal)
        return navigation_signal

    def signals(self) -> List[BaseSignal]:
        """
        Return a list of all signals in the tree.
        """
        signals = []

        def _traverse(node):
            signals.append(node["signal"])
            for child in node["children"].values():
                _traverse(child)

        _traverse(self._tree["root"])
        return signals

    def create_plot_states(self):
        """
        Create plot states for each signal plot in the tree.
        """
        from despy.drawing.plot_states import PlotState
        plot_states = {}
        for signal in self.signals():
            plot_state = PlotState(signal=signal)
            plot_states[signal] = plot_state
        return plot_states

    @property
    def nav_dim(self) -> int:
        """
        The number of navigation dimensions in the root signal.
        """
        return self.root.axes_manager.navigation_dimension

    def create_navigator_plots(self):
        """
        Create navigator plots based on the root signal.
        """
        self.navigator_plot_manager = NavigationPlotManager(main_window=self.main_window,
                                                            signal_tree=self)

    def add_transformation(self,
                           parent_signal: BaseSignal,
                           transformation: str,
                           new_signal: BaseSignal,):
        """
        Add a transformation to the tree.

        Parameters
        ----------
        parent_signal : Signal
            The parent signal to which the transformation is applied.
        transformation : str
            The name of the transformation.
        new_signal : Signal
            The new signal created by applying the transformation.
        """
        pass
