from hyperspy.signal import BaseSignal


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from despy.drawing.plot import Plot
    from despy.main_window import MainWindow

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

    Certain "broken" branches which are

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
                 distributed_client = None
                 ):
        # There is only one navigator.  Currently, having more than one navigator makes things very complicated.
        # I want to try to minimize the number of plots.  If for example someone has a 5D STEM signal, and they want
        # to play with the time axis then they should use the virtual imaging tools and do it that way.
        self.navigator_signals = dict()  # type: dict[str:BaseSignal] # only 1
        self.navigator_plot_manager = None # type: Plot | None # only 1
        self.signal_plots = [] # type: list[Plot]

        self.root = root_signal
        self.signal_plot = None
        self.key_navigator = None
        self.main_window = main_window

        # The Current displayed signal is determined in the `Plot` class.  When a plot is selected in the GUI,
        # a tree navigator will show up in the

        self._tree = {"root": {"signal": root_signal, "children": {}}}

        # set up the navigator plots:
        self._initialize_navigator(root_signal) # populate recursively

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
        if ((signal.axes_manager.navigation_shape + signal.axes_manager.signal_shape) !=
                self.root.axes_manager.navigation_shape):
            raise ValueError("Navigator signal must have the same total number of dimensions as the root signal."
                             "and the same shape")
        self.navigator_signals[name] = signal

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
        else: # root_signal.axes_manager.navigation_dimension >= 1:
            if signal._lazy and signal.navigator is not None:
                navigation_signal = signal.navigator
            else: # sum over signal axes to compute the navigation signal
                navigation_signal = signal.sum(signal.axes_manager.signal_axes)
                if navigation_signal._lazy:
                    navigation_signal.compute()
            if not isinstance(navigation_signal, BaseSignal): # if numpy array
                navigation_signal = BaseSignal(navigation_signal).T
        self.add_navigator_signal(name= "base", signal=navigation_signal)

    @property
    def nav_dim(self) -> int:
        """
        The number of navigation dimensions in the root signal.
        """
        return self.root.axes_manager.navigation_dimension

    def _create_navigator_plots(self):
        """
        Create navigator plots based on the root signal.
        """

        if self.root.axes_manager.navigation_dimension > 2:
            # create a multi-plot navigator
            pass
        else:
            # create a single navigator plot
            self.navigator_plot = Plot()


    def crop(self):
        """
        Cropping the Signal will return an entirely new signal tree that isn't connected to the
        current one.

        The idea is that cropping is a breaking transformation, so the navigator signal will be different and the
        new signal tree will be independent of the previous one.

        The crop action will
        """

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
        breaking : bool
            Whether the transformation is breaking. If the transformation is breaking, then a Plot will be created,
            and it won't be connected to the "self.key_navigator" Plot.
        """
        if breaking:
            # Create a new plot for the new signal
            pass
        else:
            # Add the new signal as a child of the parent signal
            pass


class HyperSignal:
    """
    A class to manage the plotting of hyperspy signals. This class manages the
    different plots associated with a hyperspy signal.

    Because of the 1st class nature of lazy signals there are limits to how fast this class can
    be.  Hardware optimization is very, very important to get the most out of this class.  That being
    said dask task-scheduling is always going to be somewhat of a bottleneck.

    Parameters
    ----------
    signal : hs.signals.BaseSignal
        The hyperspy signal to plot.
    main_window : MainWindow
        The main window of the application.
    client : distributed.Client
        The Dask client to use for computations.
    """

    def __init__(self,
                 signal: hs.signals.BaseSignal,
                 main_window: MainWindow,
                 parent_signal=None,
                 client: distributed.Client = None):
        self.signal = signal
        self.client = client
        self.main_window = main_window
        self.parent_signal = parent_signal

        if len(signal.axes_manager.navigation_axes) > 0 and len(signal.axes_manager.signal_axes) != 0:
            if signal._lazy and signal.navigator is not None:
                nav_sig = signal.navigator
            else:
                nav_sig = signal.sum(signal.axes_manager.signal_axes)
                if nav_sig._lazy:
                    nav_sig.compute()
            if not isinstance(nav_sig, hs.signals.BaseSignal):
                nav_sig = hs.signals.BaseSignal(nav_sig).T
            if len(nav_sig.axes_manager.navigation_axes) > 2: #
                nav_sig = nav_sig.transpose(2)

            self.nav_sig = HyperSignal(nav_sig,
                                       main_window=self.main_window,
                                       parent_signal=self,
                                       client=self.client
                                       )  # recursive...
        else:
            self.nav_sig = None

        self.navigation_plots = []
        self.signal_plots = []