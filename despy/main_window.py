import sys
import os
from typing import Union
from functools import partial
import webbrowser

from PySide6.QtGui import QAction, QIcon
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QSplashScreen, QMainWindow, QApplication, QMessageBox, QDialog, QFileDialog
from PySide6 import QtWidgets, QtCore
from PySide6.QtGui import QPixmap, QColor

from dask.distributed import Client, Future, LocalCluster
import numpy as np
import pyqtgraph as pg
import hyperspy.api as hs
import pyxem.data

from despy.misc.dialogs import DatasetSizeDialog, CreateDataDialog
from despy.drawing.multiplot import Plot
from despy.signal_tree import BaseSignalTree
from despy.external.pyqtgraph.histogram_widget import HistogramLUTWidget, HistogramLUTItem

COLORMAPS = {"gray": pg.colormap.get("CET-L1"),
             "viridis": pg.colormap.get("viridis"),
             "plasma": pg.colormap.get("plasma"),
             "cividis": pg.colormap.get("cividis"),
             "fire": pg.colormap.get("CET-L3"),
             }


class MainWindow(QMainWindow):
    """
    A class to manage the main window of the application.
    """

    def __init__(self, app=None):
        super().__init__()
        self.btn_reset = None
        self.btn_auto = None
        self.app = app
        self.metadata_group = None  # type: Union[QtWidgets.QGroupBox, None]
        self.metadata_layout = None  # type: Union[QtWidgets.QVBoxLayout, None]

        self.axes_group = None  # type: Union[QtWidgets.QGroupBox, None]
        self.axes_layout = None  # type: Union[QtWidgets.QVBoxLayout, None]

        # Test if the theme is set correctly
        cpu_count = os.cpu_count()
        threads = (cpu_count // 4) - 1
        cluster = LocalCluster(n_workers=threads, threads_per_worker=4)
        self.client = Client(cluster)  # Start a local Dask client (this should be settable eventually)
        print(f"Starting Dashboard at: {self.client.dashboard_link}")
        self.setWindowTitle("DE-Spy")
        # get screen size and set window size to 3/4 of the screen size
        # get screen size and set subwindow size to 1/4 of the screen size

        screen = QApplication.primaryScreen()
        self.screen_size = screen.size()
        self.resize(self.screen_size.width() * 3 // 4, self.screen_size.height() * 3 // 4)
        self.histogram = None
        self._histogram_image_item = None  # track bound ImageItem to avoid LUT resets

        # center the main window on the screen
        self.move(
            (self.screen_size.width() - self.width()) // 2,
            (self.screen_size.height() - self.height()) // 2
        )
        # create an MDI area
        self.mdi_area = QtWidgets.QMdiArea()
        self.setCentralWidget(self.mdi_area)

        self.plot_subwindows = []  # type: list[Plot]

        self.mdi_area.subWindowActivated.connect(self.on_subwindow_activated)
        self.create_menu()
        self.setMouseTracking(True)

        self.selectors_layout = None
        self.s_list_widget = None
        self.file_dialog = None

        self.timer = QTimer()
        self.timer.setInterval(10)  # Every 10ms we will check to update the plots??
        self.timer.timeout.connect(self.update_plots_loop)
        self.timer.start()

        self.mdi_area.setStyleSheet("background-color: #2b2b2b;")  # Dark gray background

        self.signal_trees = []  # type: list[BaseSignalTree]

        self.add_plot_control_widget()
        self.current_selected_signal_tree = None  # type: Union[BaseSignalTree, None]

        self.cursor_readout = QtWidgets.QLabel("x: -, y: -, value: -")
        self.statusBar().addPermanentWidget(self.cursor_readout)

    @property
    def navigation_selectors(self):
        selectors = []
        for s in self.signal_trees:
            selectors.extend(s.navigator_plot_manager.navigation_selectors)
        return selectors

    def update_plots_loop(self):
        """This is a simple loop to check if the plots need to be updated. Currently, this
        is running on the main event loop, but it could be moved to a separate thread if it
        starts to slow down the GUI.
        """
        for p in self.plot_subwindows:
            if isinstance(p.current_data, Future) and p.current_data.done():
                print("Updating Plot in loop...")
                p.current_data = p.current_data.result()
                p.update()

    def create_menu(self):
        """
        Create the menu bar for the main window.
        """
        menubar = self.menuBar()

        # Add File Menu
        file_menu = menubar.addMenu("File")
        open_action = QAction("Open", self)
        open_action.triggered.connect(self.open_file)
        file_menu.addAction(open_action)
        open_create_data_dialog = QAction("Create Data...", self)

        open_create_data_dialog.triggered.connect(self.create_data)
        file_menu.addAction(open_create_data_dialog)

        example_data = file_menu.addMenu("Load Example Data...")

        names = ["mgo_nanocrystals", "small_ptychography", "zrnb_precipitate", "pdcusi_insitu"]
        for n in names:
            action = example_data.addAction(n)
            action.triggered.connect(partial(self.load_example_data, n))

        # Add View Menu
        view_menu = menubar.addMenu("View")

        # Add a view to open the dask dashboard
        view_dashboard_action = QAction("Open Dask Dashboard", self)
        view_dashboard_action.triggered.connect(self.open_dask_dashboard)
        view_menu.addAction(view_dashboard_action)

    def open_dask_dashboard(self):
        """
        Open the Dask dashboard in a new window.
        """
        if self.client:
            dashboard_url = self.client.dashboard_link
            webbrowser.open(dashboard_url)
        else:
            QMessageBox.warning(self, "Error", "Dask client is not initialized.")

    def create_data(self):
        dialog = CreateDataDialog(self)
        print("Creating Data")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            print("Dialog accepted")
            data = dialog.get_data()
            print("Data created")
            if data is not None:
                self.add_signal(data)

    def _create_signals(self, file_paths):
        for file_path in file_paths:
            kwargs = {"lazy": True}
            if file_path.endswith(".mrc"):
                dialog = DatasetSizeDialog(self, filename=file_path)
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    x_size = dialog.x_input.value()
                    y_size = dialog.y_input.value()
                    time_size = dialog.time_input.value()
                    kwargs["navigation_shape"] = tuple([val for val in (x_size, y_size, time_size) if val > 1])
                    print(f"{kwargs['navigation_shape']}")
                else:
                    print("Dialog cancelled")
                    return
                # .mrc always have 2 signal axes.  Maybe needs changed for eels.
                if len(kwargs["navigation_shape"]) == 3:
                    kwargs["chunks"] = ((1,) + ("auto",) * (len(kwargs["navigation_shape"]) - 1)) + (-1, -1)
                else:
                    kwargs["chunks"] = (("auto",) * len(kwargs["navigation_shape"])) + (-1, -1)

                print(f"chunks: {kwargs['chunks']}")
                kwargs["distributed"] = True

            signal = hs.load(file_path, **kwargs)
            hyper_signal = BaseSignalTree(root_signal=signal,
                                          main_window=self,
                                          distributed_client=self.client)

            plot = Plot(hyper_signal,
                        is_signal=False,
                        key_navigator=True
                        , main_window=self)
            plot.main_window = self
            plot.titleColor = QColor("lightgray")
            self.add_plot(plot)
            print("Adding selector and plot")
            plot.add_selector_and_new_plot()

    def open_file(self):
        self.file_dialog = QFileDialog()
        self.file_dialog.setFileMode(QtWidgets.QFileDialog.FileMode.ExistingFiles)
        self.file_dialog.setNameFilter("Hyperspy Files (*.hspy), mrc Files (*.mrc)")

        if self.file_dialog.exec():
            file_paths = self.file_dialog.selectedFiles()
            if file_paths:
                self._create_signals(file_paths)

    def add_signal(self, signal):
        """Add a signal to the main window.

        This will "plant" a new seed for a signal tree and set up the associated plots.

        Parameters
        ----------
        signal : hs.signals.BaseSignal
            The hyperspy signal to add.

        """

        self.signal_trees.append(BaseSignalTree(root_signal=signal,
                                                main_window=self,
                                                distributed_client=self.client)
                                 )
        print("Signal Tree Created")

    def load_example_data(self, name):
        """
        Load example data for testing purposes.
        """
        signal = getattr(pyxem.data, name)(allow_download=True, lazy=True)
        self.add_signal(signal)
        print("Example data loaded:", name)

    def add_plot(self, plot: Plot):
        """Add a plot to the MDI area.

        Parameters
        ----------
        plot : Plot
            The plot to add.

        """
        plot.resize(self.screen_size.height() // 2, self.screen_size.height() // 2)

        plot.setWindowTitle("Test")
        plot.titleColor = QColor("green")
        self.mdi_area.addSubWindow(plot)
        plot.show()
        self.plot_subwindows.append(plot)
        plot.mdi_area = self.mdi_area
        return

    def update_metadata_widget(self, window):
        # Clear existing layout (including spacers)
        if self.metadata_layout is None:
            return
        while self.metadata_layout.count():
            item = self.metadata_layout.takeAt(0)
            widget_to_remove = item.widget()
            if widget_to_remove is not None:
                widget_to_remove.deleteLater()
            else:
                del item

        # Add new metadata
        if hasattr(window, "signal_tree"):
            signal_tree = window.signal_tree
            metadata_dict = signal_tree.get_metadata_widget()
            for subsection, items in metadata_dict.items():
                group = QtWidgets.QGroupBox(str(subsection))

                # Keep each group a constant height and allow scrolling inside
                group.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                                    QtWidgets.QSizePolicy.Policy.Fixed)
                group.setFixedHeight(120)

                # Group layout that holds the scroll area
                group_layout = QtWidgets.QVBoxLayout(group)
                group_layout.setContentsMargins(6, 6, 6, 6)
                group_layout.setSpacing(0)

                # Scroll area inside the group
                scroll = QtWidgets.QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

                # Container for the metadata rows
                container = QtWidgets.QWidget()
                grid = QtWidgets.QGridLayout(container)
                grid.setContentsMargins(0, 0, 0, 0)
                grid.setHorizontalSpacing(12)
                grid.setVerticalSpacing(4)

                for row, (key, value) in enumerate((items or {}).items()):
                    key_label = QtWidgets.QLabel(f"{key}:")
                    value_label = QtWidgets.QLabel(f"{value}")
                    key_label.setStyleSheet("font-size: 10px;")
                    value_label.setStyleSheet("font-size: 10px;")
                    key_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    grid.addWidget(key_label, row, 0)
                    grid.addWidget(value_label, row, 1)

                grid.setColumnStretch(0, 0)
                grid.setColumnStretch(1, 1)

                scroll.setWidget(container)
                group_layout.addWidget(scroll)

                self.metadata_layout.addWidget(group)

    def update_axes_widget(self, window: "Plot"):
        """
        Update the axes widget based on the active window.

        The Axes widget displays the navigation axes for the entire
        Signal Tree (as they are shared) and the signal axes for the
        current active signal in the window.
        """
        # Clear existing layout (including spacers)
        if self.axes_layout is None:
            return
        while self.axes_layout.count():
            item = self.axes_layout.takeAt(0)
            widget_to_remove = item.widget()
            if widget_to_remove is not None:
                widget_to_remove.deleteLater()
            else:
                del item

        # Add new axes information
        if hasattr(window, "signal_tree"):
            plot_state = window.plot_state
            print("Updating axes widget, plot state:", plot_state)
            if plot_state is None:
                current_signal = None
            else:
                current_signal = window.plot_state.current_signal
            groups = window.signal_tree.build_axes_groups(current_signal, window)
            for group in groups:
                self.axes_layout.addWidget(group)

    def set_cursor_readout(self, x=None, y=None, xpix=None, ypix=None, value=None):
        def _fmt(v):
            if v is None:
                return "-"
            try:
                return f"{float(v):.4g}"
            except Exception:
                return str(v)

        txt = f"x: {_fmt(x)} ({xpix}), y: {_fmt(y)} ({ypix}), value: {_fmt(value)}"
        if hasattr(self, "cursor_readout") and self.cursor_readout is not None:
            self.cursor_readout.setText(txt)

    def on_subwindow_activated(self, window: "Plot"):
        if hasattr(window, "show_selector_control_widget"):
            window.show_selector_control_widget()

        if hasattr(window, "show_toolbars"):
            window.show_toolbars()

        if hasattr(window, "plot_state") and window.plot_state is not None:
            self.update_axes_widget(window)

        if hasattr(window, "plot_state") and window.plot_state is not None and hasattr(window.plot_state, "toolbar"):
            window.plot_state.toolbar.setVisible(True)

        for plot in self.plot_subwindows:
            if window != plot:
                if hasattr(plot, "hide_toolbars"):
                    plot.hide_toolbars()
                if hasattr(plot, "hide_selector_control_widget"):
                    plot.hide_selector_control_widget()

        # Only rebind the histogram if the ImageItem actually changed
        if window is not None and getattr(window, "image_item", None) is not None:
            print("Active window has image item:", window.image_item)
            print("Current histogram image item:", self._histogram_image_item)
            if self._histogram_image_item != window.image_item:
                print("Setting histogram to image", window.image_item)
                try:
                    print("Setting histogram image item")
                    self.histogram.setImageItem(window.image_item)
                    print("Histogram set")
                    self._histogram_image_item = window.image_item
                    print("Setting histogram levels")
                    self.histogram.setLevels(window.plot_state.min_level,
                                             window.plot_state.max_level)

                except Exception:
                    pass

        if (window is not None and
                hasattr(window, "signal_tree") and
                window.signal_tree != self.current_selected_signal_tree):
            self.current_selected_signal_tree = window.signal_tree
            self.update_metadata_widget(window)

    def add_plot_control_widget(self):
        """
        This is the right-hand side docked widget the contains the plot controls, image metadata
        and the selector controls.

        It updates with the current active plot in the MDI area.

        """
        dock_widget = QtWidgets.QDockWidget("Plot Control", self)
        dock_widget.setBaseSize(self.width() // 6, self.height() // 6)

        # Create a main widget and layout
        main_widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(main_widget)

        # Creating the display group box
        # ------------------------------
        display_group = QtWidgets.QGroupBox("Plot Display Controls")
        display_group.setMaximumHeight(250)
        display_layout = QtWidgets.QVBoxLayout(display_group)

        # Create a Histogram plot LUT widget
        self.histogram = HistogramLUTWidget(orientation="horizontal",
                                            autoLevel=False,
                                            constantLevel=True)  # type: HistogramLUTWidget
        self.histogram.setMinimumWidth(200)
        self.histogram.setMinimumHeight(100)
        self.histogram.setMaximumHeight(150)
        self.histogram.item.sigLevelChangeFinished.connect(self.on_histogram_levels_finished)
        display_layout.addWidget(self.histogram)

        # Add a color map selector inside a group box
        self.cmap_selector = QtWidgets.QComboBox()
        self.cmap_selector.addItems(list(COLORMAPS.keys()))
        self.cmap_selector.setCurrentText("grays")
        self.cmap_selector.currentTextChanged.connect(self.on_cmap_changed)
        cmap_layout = QtWidgets.QHBoxLayout()
        cmap_layout.addWidget(QtWidgets.QLabel("Colormap"))
        cmap_layout.addWidget(self.cmap_selector, 1)
        display_layout.addLayout(cmap_layout)
        layout.addWidget(display_group)

        buttons_layout = QtWidgets.QHBoxLayout()
        self.btn_auto = QtWidgets.QPushButton("auto")
        self.btn_reset = QtWidgets.QPushButton("reset")
        self.btn_auto.clicked.connect(self.on_contrast_auto_click)
        self.btn_reset.clicked.connect(self.on_contrast_reset_click)
        buttons_layout.addWidget(self.btn_auto)
        buttons_layout.addWidget(self.btn_reset)
        display_layout.addLayout(buttons_layout)

        # Create a Group for the metadata
        # ----------------------------------------
        self.metadata_group = QtWidgets.QGroupBox("Metadata")
        self.metadata_layout = QtWidgets.QHBoxLayout(self.metadata_group)
        layout.addWidget(self.metadata_group)

        # Create a Group for the axes
        # ----------------------------------------
        self.axes_group = QtWidgets.QGroupBox("Plot Axes")
        self.axes_layout = QtWidgets.QVBoxLayout(self.axes_group)
        layout.addWidget(self.axes_group)

        # Create a Group for the Selector Controls
        # ----------------------------------------
        # The when a plot is selected we will populate self.selectors_layout with a
        # selector control layout...
        selectors_group = QtWidgets.QGroupBox("Selectors Controls")
        self.selectors_layout = QtWidgets.QVBoxLayout(selectors_group)

        layout.addWidget(selectors_group)
        dock_widget.setWidget(main_widget)

        self.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, dock_widget)

    def _active_plot_window(self) -> Union[Plot, None]:
        # The active subwindow is the Plot (subclass of QMdiSubWindow)
        sub = self.mdi_area.activeSubWindow()
        return sub if sub is not None else None

    def on_contrast_auto_click(self):
        """
        Set image contrast to [1st, 99th] percentile for 2D; y-range percentiles for 1D.
        Persist on PlotState, so it remains constant when data changes.
        """
        w = self._active_plot_window()
        if w is None or not hasattr(w, "plot_state") or w.plot_state is None:
            return

        if getattr(w.plot_state, "dimensions", 0) == 2:
            mn, mx = self.histogram.levels2percentile(0.01, 99.0)
            self.histogram.setLevels(mn, mx)

    def on_contrast_reset_click(self):
        """
        Reset contrast to full range for 2D; re-enable y auto-range for 1D.
        Persist on PlotState.
        """
        w = self._active_plot_window()
        if w is None or not hasattr(w, "plot_state") or w.plot_state is None:
            return
        if getattr(w.plot_state, "dimensions", 0) == 2:
            mn, mx = w.image_item.quickMinMax()
            self.histogram.setLevels(mn, mx)

    def on_cmap_changed(self, cmap_name: str):
        # Apply colormap to the active plot and sync the histogram widget
        sub = self.mdi_area.activeSubWindow()
        if sub is None:
            return
        w = sub.widget()
        cm = COLORMAPS[cmap_name]
        if hasattr(w, "set_colormap"):
            w.set_colormap(cm)
        if hasattr(self.histogram, "setColorMap"):
            self.histogram.setColorMap(cm)
        elif hasattr(self.histogram, "gradient"):
            self.histogram.gradient.setColorMap(cm)

    def on_histogram_levels_finished(self, signal: HistogramLUTItem):
        """
        On histogram level change, update the active plot's contrast via PlotState
        and apply immediately. Guard against missing histogram data.
        """
        # Guard: histogram not ready yet
        if signal is None or getattr(signal, "bins", None) is None or getattr(signal, "counts", None) is None:
            return
        percentiles = signal.get_percentile_levels()
        levels = signal.getLevels()
        w = self._active_plot_window()
        if w is None or not hasattr(w, "plot_state") or w.plot_state is None:
            return
        else:
            w.plot_state.max_level = levels[1]
            w.plot_state.min_level = levels[0]
            w.plot_state.max_percentile = percentiles[1]
            w.plot_state.min_percentile = percentiles[0]
        print("Setting levels:", levels, "percentiles:", percentiles, "on plot:", w)

    def close(self):
        self.client.close()
        super().close()


if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("DeSpy")  # Set the application name
    # Create and show the splash screen
    logo_path = "SpydeDark.png"  # Replace with the actual path to your logo
    pixmap = QPixmap(logo_path).scaled(300, 300,
                                       Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)

    splash = QSplashScreen(pixmap,
                           Qt.WindowType.FramelessWindowHint)
    splash.show()
    splash.raise_()  # Bring the splash screen to the front
    app.processEvents()
    main_window = MainWindow(app=app)

    main_window.setWindowTitle("DE Spy")  # Set the window title

    if sys.platform == "darwin":
        logo_path = "Spyde.icns"
    else:
        logo_path = "SpydeDark.png"  # Replace with the actual path to your logo
    main_window.setWindowIcon(QIcon(logo_path))
    main_window.show()
    splash.finish(main_window)  # Close the splash screen when the main window is shown

    app.exec()
