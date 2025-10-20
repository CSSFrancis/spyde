import distributed
import pyxem.data
import webbrowser

from PySide6.QtGui import QAction, QIcon, QPixmap, QColor
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QSplashScreen, QMainWindow, QApplication, QMessageBox, QDialog, QFileDialog
from PySide6 import QtWidgets, QtCore
from PySide6.QtGui import QPixmap, QColor


import sys
import os
from functools import partial
import hyperspy.api as hs
from dask.distributed import Client, Future, LocalCluster

from despy.misc.dialogs import DatasetSizeDialog, CreateDataDialog
from despy.drawing.plot import Plot

import pyqtgraph as pg

color_maps = ["viridis", "plasma", "magma", "cividis", "grays"]


class MainWindow(QMainWindow):
    """
    A class to manage the main window of the application.
    """

    def __init__(self, app=None):
        super().__init__()
        self.app = app
        # Test if the theme is set correctly
        cpu_count = os.cpu_count()
        threads = (cpu_count//4) - 1
        cluster = LocalCluster(n_workers=threads, threads_per_worker=4)
        self.client = Client(cluster)  # Start a local Dask client (this should be settable eventually)
        print(self.client.dashboard_link)
        self.setWindowTitle("DE-Spy")
        # get screen size and set window size to 3/4 of the screen size
        # get screen size and set subwindow size to 1/4 of the screen size

        screen = QApplication.primaryScreen()
        self.screen_size = screen.size()
        self.resize(self.screen_size.width() * 3 // 4, self.screen_size.height() * 3 // 4)
        self.histogram = None

        # center the main window on the screen
        self.move(
            (self.screen_size.width() - self.width()) // 2,
            (self.screen_size.height() - self.height()) // 2
        )
        # create an MDI area
        self.mdi_area = QtWidgets.QMdiArea()
        self.setCentralWidget(self.mdi_area)

        self.plot_subwindows = []

        self.mdi_area.subWindowActivated.connect(self.on_subwindow_activated)
        self.create_menu()
        self.setMouseTracking(True)


        self.selectors_layout = None
        self.s_list_widget = None
        self.add_plot_control_widget()
        self.file_dialog = None

        self.timer = QTimer()
        self.timer.setInterval(10)  # Every 10ms we will check to update the plots??
        self.timer.timeout.connect(self.update_plots_loop)
        self.timer.start()

        self.mdi_area.setStyleSheet("background-color: #2b2b2b;")  # Dark gray background
    def update_plots_loop(self):
        """This is a simple loop to check if the plots need to be updated. Currently, this
        is running on the main event loop, but it could be moved to a separate thread if it
        starts to slow down the GUI.
        """
        for p in self.plot_subwindows:
            if isinstance(p.data, Future) and p.data.done():
                print("Updating Plot")
                p.data = p.data.result()
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
            hyper_signal = HyperSignal(signal, main_window=self, client=self.client)
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

    def add_signal(self, s):
        """
        Add a signal to the main window.
        """
        hyper_signal = HyperSignal(s, main_window=self, client=self.client)
        plot = Plot(hyper_signal, is_signal=False, key_navigator=True, main_window=self)
        plot.main_window = self

        self.add_plot(plot)
        plot.add_selector_and_new_plot()

    def load_example_data(self, name):
        """
        Load example data for testing purposes.
        """
        signal = getattr(pyxem.data, name)(allow_download=True, lazy=True)
        self.add_signal(signal)

    def add_plot(self, plot):
        plot.resize(self.screen_size.height() // 2, self.screen_size.height() // 2)

        plot.setWindowTitle("Test")
        plot.titleColor = QColor("green")
        self.mdi_area.addSubWindow(plot)
        plot.show()
        self.plot_subwindows.append(plot)
        plot.mdi_area = self.mdi_area
        return

    def on_subwindow_activated(self, window):
        print("Activated Subwindow", window)
        print("hasattr show_selector_control_widget:", hasattr(window, "show_selector_control_widget"))

        if hasattr(window, "show_selector_control_widget"):
            window.show_selector_control_widget()
            print("Making toolbar visible for", window)
        if hasattr(window, "toolbar"):
            window.toolbar.setVisible(True)
        for plot in self.plot_subwindows:
            if window != plot:
                plot.toolbar.setVisible(False)
                if hasattr(plot, "hide_selector_control_widget"):
                    plot.hide_selector_control_widget()
        # if an image then set the histogram to the image
        if window is not None and getattr(window, "image_item", None) is not None:
            print("Setting histogram to image", window.image_item)
            self.histogram.setImageItem(window.image_item)

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
        display_group = QtWidgets.QGroupBox("Plot Display Controls" )
        display_group.setMaximumHeight(250)
        display_layout = QtWidgets.QVBoxLayout(display_group)

        # Create a Histogram plot LUT widget
        self.histogram = pg.HistogramLUTWidget(orientation="horizontal",)
        self.histogram.setMinimumWidth(200)
        self.histogram.setMinimumHeight(100)
        self.histogram.setMaximumHeight(150)
        display_layout.addWidget(self.histogram)

        # Add a color map selector inside a group box
        self.cmap_selector = QtWidgets.QComboBox()
        self.cmap_selector.addItems(color_maps)
        self.cmap_selector.setCurrentText("grays")
        self.cmap_selector.currentTextChanged.connect(self.on_cmap_changed)
        cmap_layout = QtWidgets.QHBoxLayout()
        cmap_layout.addWidget(QtWidgets.QLabel("Colormap"))
        cmap_layout.addWidget(self.cmap_selector, 1)
        display_layout.addLayout(cmap_layout)
        layout.addWidget(display_group)

        # Create a Group for the metadata
        # ----------------------------------------
        metadata_group = QtWidgets.QGroupBox("Experimental Metadata")
        metadata_layout = QtWidgets.QVBoxLayout(metadata_group)
        layout.addWidget(metadata_group)

        # Create a Group for the axes
        # ----------------------------------------
        axes_group = QtWidgets.QGroupBox("Plot Axes")
        axes_layout = QtWidgets.QVBoxLayout(axes_group)
        layout.addWidget(axes_group)

        # Create a Group for the Selector Controls
        # ----------------------------------------
        # The when a plot is selected we will populate self.selectors_layout with a
        # selector control layout...
        selectors_group = QtWidgets.QGroupBox("Selectors Controls")
        self.selectors_layout = QtWidgets.QVBoxLayout(selectors_group)

        layout.addWidget(selectors_group)
        dock_widget.setWidget(main_widget)

        self.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, dock_widget)

    def on_cmap_changed(self, cmap_name: str):
        # Apply colormap to the active plot and sync the histogram widget
        sub = self.mdi_area.activeSubWindow()
        if sub is None:
            return
        w = sub.widget()
        if hasattr(w, "set_colormap"):
            w.set_colormap(cmap_name)

        try:
            cm = pg.colormap.get(cmap_name)
            if hasattr(self.histogram, "setColorMap"):
                self.histogram.setColorMap(cm)
            elif hasattr(self.histogram, "gradient"):
                self.histogram.gradient.setColorMap(cm)
        except Exception:
            pass

    def close(self):
        self.client.close()
        super().close()





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
