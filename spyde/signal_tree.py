from functools import partial

import numpy as np
from hyperspy.signal import BaseSignal

from typing import TYPE_CHECKING, Union, List, Iterator

from spyde.signal_node import SignalNode

from spyde.drawing.plots.plot_window import PlotWindow

if TYPE_CHECKING:
    from spyde.drawing.plots.plot_states import PlotState
    from spyde.__main__ import MainWindow

from spyde.drawing.plots.plot import Plot
from spyde.drawing.plots.multiplot_manager import MultiplotManager


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

    def __init__(
        self,
        root_signal: BaseSignal,
        main_window: "MainWindow",
        distributed_client=None,
        selector_type=None,
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
        self.root_node = SignalNode(signal=root_signal, name="root", parent=None)
        self.client = distributed_client
        self._selector_type = selector_type

        # set up the navigator plots:
        print("Initializing navigator for root signal: ", root_signal)
        navigator = self._initialize_navigator(root_signal)
        print("Navigator initialized: ", navigator)
        self.navigator_signals["base"] = navigator

        self.signal_plots = []  # type: Union[List[Plot], None]

        self.navigator_plot_manager = None  # type: Union[MultiplotManager, None]
        # setting up plots

        self._initialize_initial_plots()
        print("Created Signal Tree with root signal: ", self.root)

    def _initialize_initial_plots(self):
        """
        Initialize the initial plots based on the root signal.
        """
        if (
            self.root.axes_manager.navigation_dimension > 0
        ):  # pass to NavigationPlotManager
            self.navigator_plot_manager = MultiplotManager(
                main_window=self.main_window, signal_tree=self,
                selector_type=self._selector_type,
            )
        else:
            self.navigator_plot_manager = None
            self.add_signal_plot()

    def add_signal_plot(self):
        """
        Add a new signal plot for the root signal.
        """
        pw = self.main_window.add_plot_window(
            is_navigator=False, signal_tree=self, plot_manager=None
        )

        plot = pw.add_new_plot()
        self.create_plot_states(plot=plot)
        plot.set_plot_state(list(plot.plot_states.keys())[0])
        self.signal_plots.append(plot)
        plot.update()

    @property
    def plot_windows(self) -> List["PlotWindow"]:
        """Return all plot windows in the signal tree."""
        if self.navigator_plot_manager is None:
            return []
        return self.navigator_plot_manager.plot_windows



    def _preprocess_navigator(self, signal: BaseSignal) -> List[BaseSignal]:
        """
        Preprocess the navigator signal before adding it to the navigator plot manager.

        If the signal has a navigator then it will be split into two!
        """
        if (
            signal.axes_manager.navigation_shape + signal.axes_manager.signal_shape
        ) != self.root.axes_manager.navigation_shape:
            raise ValueError(
                "Navigator signal must have the same total number of dimensions as the root signal."
                "and the same shape"
            )

        if signal.axes_manager.signal_dimension == 0:
            signal = signal.T
        if (
            signal.axes_manager.signal_dimension > 0
            and signal.axes_manager.navigation_dimension > 0
        ):
            navigator = signal.sum(signal.axes_manager.signal_axes).T
            if navigator._lazy:
                navigator.data = self.client.compute(navigator.data,
                                                     priority=-10,
                                                     workers=self.main_window.dask_manager.heavy_workers)  # creates a ndarray from setting...
            if signal._lazy:
                signal.data = self.client.compute(signal.data,
                                                  priority=-10,
                                                  workers=self.main_window.dask_manager.heavy_workers
                                                  )
            print("Preprocessing navigator: ", navigator, signal)
            return [navigator, signal]

        elif signal.axes_manager.signal_dimension > 2:
            signal = signal.transpose(2)
            navigator = signal.sum(signal.axes_manager.signal_axes).T
            if navigator._lazy:
                navigator.data = self.client.compute(navigator.data,
                                                     priority=-10,
                                                     workers=self.main_window.dask_manager.heavy_workers)
            if signal._lazy:
                signal.data = self.client.compute(signal.data, priority=-10,
                                                  workers=self.main_window.dask_manager.heavy_workers)
            print("Preprocessing navigator: ", navigator, signal)

            return [navigator, signal]

        if signal._lazy:
            signal.data = self.client.compute(signal.data,
                                                     priority=-10,
                                                     workers=self.main_window.dask_manager.heavy_workers)
        return [signal]

    def add_navigator_signal(self, name: str, signal: BaseSignal):
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
        self.navigator_plot_manager.add_plot_states_for_navigation_signals(signal)

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
                if navigation_signal._lazy:
                    navigation_signal.compute()
            else:  # sum over signal axes to compute the navigation signal
                navigation_signal = signal.sum(signal.axes_manager.signal_axes)
            if not isinstance(navigation_signal, BaseSignal):  # if numpy array
                navigation_signal = BaseSignal(navigation_signal)

        # handle lazy computation and setting up the axes properly...
        navigation_signal = self._preprocess_navigator(navigation_signal)
        return navigation_signal

    def walk(self) -> Iterator[SignalNode]:
        """Depth-first generator over all nodes."""
        stack = [self.root_node]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(node.children.values())

    def signals(self) -> List[BaseSignal]:
        """Return a list of all signals in the tree, including the root."""
        return [node.signal for node in self.walk()]

    def create_plot_states(self, plot: "Plot" = None) -> dict:
        """
        Create plot states for each signal plot in the tree.
        """

        plot_states = {}
        for signal in self.signals():
            if signal.axes_manager.navigation_dimension == 0:
                plot.add_plot_state(
                    signal=signal,
                    dynamic=False,
                    dimensions=signal.axes_manager.signal_dimension,
                )
            else:
                plot.add_plot_state(
                    signal=signal,
                    dynamic=True,
                    dimensions=signal.axes_manager.signal_dimension,
                )
        return plot_states

    def update_plot_states(self, new_signal: BaseSignal):
        """
        Update all plot states in the signal tree.
        """
        from spyde.drawing.plots.plot_states import PlotState

        for plot in self.signal_plots:
            if new_signal not in plot.plot_states:
                if new_signal.axes_manager.navigation_dimension == 0:
                    plot.plot_states[new_signal] = PlotState(
                        signal=new_signal, plot=plot, dynamic=False
                    )
                else:
                    plot.plot_states[new_signal] = PlotState(
                        signal=new_signal, plot=plot, dynamic=True
                    )

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
        self.navigator_plot_manager = MultiplotManager(
            main_window=self.main_window, signal_tree=self
        )

    def get_nested_attr(self, attr_path: str):
        """
        Get a nested attribute from `self` following a dot-separated path.

        Parameters
        ----------
        attr_path : str
            Dot-separated path of attributes (e.g., "root.axes_manager.navigation_shape").

        Returns
        -------
        Any
            The resolved attribute value or `None` if any segment is missing or `None`.
        """
        if not attr_path:
            return self
        attrs = [p for p in attr_path.split(".") if p]
        current_obj = self
        for attr in attrs:
            current_obj = getattr(current_obj, attr, None)
            if current_obj is None:
                return None
        return current_obj

    def get_node(self, signal) -> SignalNode | None:
        """Get the node in the tree corresponding to the given signal."""
        for node in self.walk():
            if node.signal is signal:
                return node
        return None

    def add_node(self, parent_signal, new_signal, transformation: str):
        """Add a new node to the signal tree."""
        parent_node = self.get_node(parent_signal)
        if parent_node is None:
            raise ValueError("Parent node not found in the tree.")
        # Handle name collision
        final_name = transformation
        if final_name in parent_node.children:
            count = 1
            candidate = f"{transformation}_{count}"
            while candidate in parent_node.children:
                count += 1
                candidate = f"{transformation}_{count}"
            final_name = candidate
        child = SignalNode(
            signal=new_signal,
            name=final_name,
            parent=parent_node,
            transformation=transformation,
        )
        parent_node.children[final_name] = child

    def add_transformation(
        self,
        parent_signal,
        method: str = None,
        function: callable = None,
        node_name: str = None,
        *args,
        **kwargs,
    ):
        """
        Add a transformation to the tree.

        Parameters
        ----------
        parent_signal : Signal
            The parent signal to which the transformation is applied.
        method : str, optional
            The method of the signal to call as a method.
        function : callable, optional
            The function to apply to the parent signal.
        node_name : str, optional
            The name of the new node in the tree.
        *args
            Positional arguments to pass to the function or method.
        **kwargs
            Keyword arguments to pass to the function or method.
        """
        if method is not None:
            try:
                new_signal = getattr(parent_signal, method)(*args, **kwargs)
            except Exception as e:
                from PySide6 import QtWidgets
                QtWidgets.QMessageBox.critical(
                    self.main_window,
                    "Transformation error",
                    f"An error occurred while applying transformation "
                    f"'{method or (function.__name__ if function else '')}':\n{e}",
                )
                return
        else:
            new_signal = function(parent_signal, *args, **kwargs)

        parent_node = self.get_node(parent_signal)
        if parent_node is None:
            raise ValueError("Parent signal not found in the tree.")

        transformation_name = method if method is not None else function.__name__
        if node_name is None:
            node_name = transformation_name

        # Handle name collision
        final_name = node_name
        if final_name in parent_node.children:
            count = 1
            candidate = f"{node_name}_{count}"
            while candidate in parent_node.children:
                count += 1
                candidate = f"{node_name}_{count}"
            final_name = candidate

        child = SignalNode(
            signal=new_signal,
            name=final_name,
            parent=parent_node,
            transformation=transformation_name,
            args=args,
            kwargs=kwargs,
        )
        parent_node.children[final_name] = child
        print(f"Added transformation '{final_name}' to the tree under parent signal.")
        self.update_plot_states(new_signal)
        return new_signal

    def close(self):
        """Clean up resources associated with the signal tree."""
        signals = self.signals()
        for s in signals:
            del s
