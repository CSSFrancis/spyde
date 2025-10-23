from functools import partial

from PySide6 import QtWidgets
from PySide6.QtCore import Qt
from hyperspy.signal import BaseSignal


from typing import TYPE_CHECKING, Union, List

if TYPE_CHECKING:
    from despy.drawing.plot_states import PlotState
    from despy.main_window import MainWindow

from despy.drawing.multiplot import NavigationPlotManager, Plot
from despy.external.qt.labels import EditableLabel
from despy import METADATA_WIDGET_CONFIG

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

    def _on_axis_field_edit(self,
                            signal,
                            axis,
                            field: str,
                            line_edit: QtWidgets.QLineEdit,
                            is_nav: bool,
                            text: str = ""):
        """
        Slot called when an axis field is edited. Updates the corresponding axis property.
        If the is_nav flag is True, updates __all__ the signals in the signal tree.
        """

        if is_nav:
            for sig in self.signals():
                # maybe just use the index?
                print(f"Updating nav axis {axis.name} field {field} to {line_edit.text()} for signal {sig}")
                sig.axes_manager[axis.name].__setattr__(field, line_edit.text())
            for plot in self.navigator_plot_manager.plots:
                print("Updating navigator plot image rectangle for: ", plot)
                plot.update_image_rectangle()
        else:
            signal.axes_manager[axis.name].__setattr__(field, line_edit.text())
            for signal in self.signal_plots:
                if signal.plot_state.current_signal == signal:
                    signal.update_image_rectangle()


    def build_axes_groups(self, signal: Union[BaseSignal, None],
                          plot: "Plot") -> list[QtWidgets.QGroupBox]:
        """
        Build two QGroupBoxes ("Navigation Axes", "Signal Axes") with editable
        scale, offset, and units fields for each axis. Edits call update_axes().
        """
        groups: list[QtWidgets.QGroupBox] = []

        def _make_group(title: str, axes_list, is_nav=False) -> QtWidgets.QGroupBox:
            group = QtWidgets.QGroupBox(title)
            group.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)

            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
            scroll.setMaximumHeight(160)

            container = QtWidgets.QWidget()
            grid = QtWidgets.QGridLayout(container)
            grid.setContentsMargins(4, 4, 4, 4)
            grid.setHorizontalSpacing(6)
            grid.setVerticalSpacing(2)

            # column headers
            header_style = "font-size: 9px; font-weight: 600;"
            h_axis = QtWidgets.QLabel("Axis")
            h_axis.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            h_axis.setStyleSheet(header_style)
            h_scale = QtWidgets.QLabel("Scale")
            h_scale.setStyleSheet(header_style)
            h_offset = QtWidgets.QLabel("Offset")
            h_offset.setStyleSheet(header_style)
            h_units = QtWidgets.QLabel("Units")
            h_units.setStyleSheet(header_style)

            grid.addWidget(h_axis, 0, 0)
            grid.addWidget(h_scale, 0, 1)
            grid.addWidget(h_offset, 0, 2)
            grid.addWidget(h_units, 0, 3)

            for row, axis in enumerate(axes_list, start=1):
                name_label = QtWidgets.QLabel(f"{axis.name}:")
                name_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                name_label.setStyleSheet("font-size: 9px;")

                scale_edit = EditableLabel(str(axis.scale))
                offset_edit = EditableLabel(str(axis.offset))
                units_edit = EditableLabel(str(axis.units))

                for w in (scale_edit, offset_edit, units_edit):
                    w.setStyleSheet("font-size: 8px;")
                    w.setFixedWidth(72)
                    w.setFixedHeight(18)

                scale_edit.editingFinished.connect(
                    partial(self._on_axis_field_edit, signal, axis, "scale", scale_edit, is_nav)
                )
                offset_edit.editingFinished.connect(
                    partial(self._on_axis_field_edit, signal, axis, "offset", offset_edit, is_nav)
                )
                units_edit.editingFinished.connect(
                    partial(self._on_axis_field_edit, signal, axis, "units", units_edit, is_nav)
                )

                grid.addWidget(name_label, row, 0)
                grid.addWidget(scale_edit, row, 1)
                grid.addWidget(offset_edit, row, 2)
                grid.addWidget(units_edit, row, 3)

            grid.setColumnStretch(0, 0)
            grid.setColumnStretch(1, 1)
            grid.setColumnStretch(2, 1)
            grid.setColumnStretch(3, 1)

            scroll.setWidget(container)
            v = QtWidgets.QVBoxLayout(group)
            v.setContentsMargins(4, 4, 4, 4)
            v.addWidget(scroll)
            return group

        groups.append(_make_group("Navigation Axes",
                                  self.root.axes_manager.navigation_axes,
                                  is_nav=True))
        if signal is not None and not plot.is_navigator:
            groups.append(_make_group("Signal Axes", signal.axes_manager.signal_axes))
        return groups

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
        Return a list of all signals in the tree, including the root.
        """
        signals: List[BaseSignal] = [self.root]

        def _traverse_children(node):
            for child in node["children"].values():
                signals.append(child["signal"])
                _traverse_children(child)

        _traverse_children(self._tree["root"])
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

    def get_metadata_widget(self) -> dict:
        """
        Get the metadata widget for the signal tree.

        Returns
        -------
        metadata : dict
            A dictionary containing metadata for each signal in the tree.
        """
        print("Getting metadata widget")
        subsections = {}
        for subsection in METADATA_WIDGET_CONFIG["metadata_widget"]:
            print(f"Processing subsection: {subsection}")
            subsections[subsection] = {}
            for prop, value in METADATA_WIDGET_CONFIG["metadata_widget"][subsection].items():
                print(f"Processing property: {prop} with value: {value}")
                if "key" in value:
                    current_value = self.root.metadata.get_item(item_path=value["key"],
                                                default=value.get("default", "--"))
                elif "attr" in value:
                    current_value = self.get_nested_attr(value["attr"])
                elif "function" in value:
                    print(f"Calling function for property {prop}: {value['function']}")
                    fun = self.get_nested_attr(value["function"])
                    if fun is None or not callable(fun):
                        print(f"Function {value['function']} not found.")
                        current_value = "--"
                    else:
                        current_value = self.get_nested_attr(value["function"])()
                else:
                    current_value = "--"
                current_value_string = f"{current_value} {value.get('units', '')}".strip()
                print(f"Resolved value for {prop}: {current_value_string}")
                subsections[subsection][prop] = current_value_string
        print("Final Subsections:", subsections)
        return subsections


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
