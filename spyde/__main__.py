from __future__ import annotations
import sys
import os
from typing import Union
from functools import partial
import webbrowser
from time import perf_counter
from uuid import uuid4

from PySide6.QtGui import QAction, QIcon, QBrush
from PySide6.QtCore import Qt, QEvent
from PySide6.QtWidgets import (
    QSplashScreen,
    QMainWindow,
    QApplication,
    QMessageBox,
    QDialog,
    QFileDialog,
)
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtGui import QPixmap, QColor

from dask.distributed import Client, Future, LocalCluster
import pyqtgraph as pg
import hyperspy.api as hs
import pyxem.data
from hyperspy.signal import BaseSignal

from spyde.live.camera_control_widget import CameraControlWidget
from spyde.live.control_dock_widget import ControlDockWidget
from spyde.live.stage_control_widget import StageControlWidget
from spyde.live.stem_control_widget import StemControlWidget
from spyde.live.reference_control_widget import ReferenceControlWidget
from spyde.misc.dialogs import DatasetSizeDialog, CreateDataDialog, MovieExportDialog
from spyde.drawing.plots.plot import Plot
from spyde.drawing.plots.plot_window import PlotWindow
from spyde.signal_tree import BaseSignalTree
from spyde.external.pyqtgraph.histogram_widget import (
    HistogramLUTWidget,
    HistogramLUTItem,
)
from spyde.workers.plot_update_worker import PlotUpdateWorker
from spyde.actions.base import NAVIGATOR_DRAG_MIME

COLORMAPS = {
    "gray": pg.colormap.get("CET-L1"),
    "viridis": pg.colormap.get("viridis"),
    "plasma": pg.colormap.get("plasma"),
    "cividis": pg.colormap.get("cividis"),
    "fire": pg.colormap.get("CET-L3"),
}

SUPPORTED_EXTS = (".hspy", ".mrc")  # extend as needed


class DaskClusterWorker(QtCore.QObject):
    finished = QtCore.Signal(object, object)  # cluster_or_none, client_or_none
    error = QtCore.Signal(Exception)

    def __init__(self, n_workers: int, threads_per_worker: int, parent=None):
        super().__init__(parent)
        self.n_workers = n_workers
        self.threads_per_worker = threads_per_worker
        self._stopped = False

    @QtCore.Slot()
    def start(self):
        if self._stopped:
            return
        try:
            cluster = LocalCluster(
                n_workers=self.n_workers,
                threads_per_worker=self.threads_per_worker,

            )
            client = Client(cluster)

            self.finished.emit(cluster, client)
        except Exception as e:
            self.error.emit(e)

    @QtCore.Slot()
    def stop(self):
        self._stopped = True


class StartupTimer:
    """Context manager that prints how long a startup step took."""

    def __init__(self, label: str) -> None:
        self.label = label
        self._start = 0.0

    def __enter__(self) -> "StartupTimer":
        self._start = perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        elapsed_ms = (perf_counter() - self._start) * 1000.0
        status = "failed" if exc_type else "completed"
        print(f"[startup] {self.label} {status} in {elapsed_ms:.1f} ms")
        return False


def log_startup_time(label: str) -> StartupTimer:
    """Convenience factory for StartupTimer instances."""
    return StartupTimer(label)


class MainWindow(QMainWindow):
    """
    A class to manage the main window of the application.
    """

    def __init__(self, app=None):
        super().__init__()
        self._in_subwindow_activation = False
        self._original_layout = None
        self.btn_reset = None
        self.btn_auto = None
        self.app = app
        self.metadata_group = None  # type: Union[QtWidgets.QGroupBox, None]
        self.metadata_layout = None  # type: Union[QtWidgets.QVBoxLayout, None]

        self.axes_group = None  # type: Union[QtWidgets.QGroupBox, None]
        self.axes_layout = None  # type: Union[QtWidgets.QVBoxLayout, None]
        cpu_count = os.cpu_count()
        print("CPU Count:", cpu_count)
        if cpu_count is None or cpu_count < 4:
            workers = 1  # Don't overdo it on small systems
            threads_per_worker = 1
        else:
            # take roughly 3/4s of the available cores
            if cpu_count <= 16:
                workers = (cpu_count // 2) - 1
                threads_per_worker = 2
            else:
                workers = (cpu_count // 4) - 1  # For very large systems, limit workers
                threads_per_worker = 4
        # get screen size and set window size to 3/4 of the screen size
        self.dock_widget = None
        self.control_widget = None

        screen = QApplication.primaryScreen()
        self.screen_size = screen.size()
        self.resize(
            self.screen_size.width() * 3 // 4, self.screen_size.height() * 3 // 4
        )
        self.histogram = None
        self._histogram_image_item = None  # track bound ImageItem to avoid LUT resets

        # center the main window on the screen
        self.move(
            (self.screen_size.width() - self.width()) // 2,
            (self.screen_size.height() - self.height()) // 2,
        )
        # create an MDI area
        self.mdi_area = QtWidgets.QMdiArea()
        self.mdi_area.setBackground(QBrush(QColor("#0d0d0d")))
        self.setCentralWidget(self.mdi_area)

        # settings and recent menu
        self.settings = QtCore.QSettings("spyde", "SpyDE")
        self.recent_menu = None

        self.plot_subwindows = []  # type: list[PlotWindow]

        self.mdi_area.subWindowActivated.connect(self.on_subwindow_activated)
        self.create_menu()
        self.setMouseTracking(True)

        self.selectors_layout = None
        self.s_list_widget = None
        self.file_dialog = None

        # Start a background worker thread to poll plot Futures
        self._update_thread = QtCore.QThread(self)
        self._plot_update_worker = PlotUpdateWorker(
            lambda: [p for plots in self.plot_subwindows for p in plots.plots],
            interval_ms=5,
        )
        self._plot_update_worker.moveToThread(self._update_thread)
        self._update_thread.started.connect(self._plot_update_worker.start)
        self._plot_update_worker.plot_ready.connect(self.on_plot_future_ready)
        self._plot_update_worker.signal_ready.connect(self.on_signal_future_ready)
        self._plot_update_worker.debug_print.connect(lambda msg: print(msg))

        with log_startup_time("Plot update worker thread start"):
            self._update_thread.start()

        if self.app is not None:
            # Use Fusion style on non-macOS
            if sys.platform != "darwin":
                QtWidgets.QApplication.setStyle("Fusion")
                with log_startup_time("Apply application stylesheet"):
                    self.app.setStyleSheet(
                        """
                        QMdiArea { background: #0d0d0d; }             /* background: very dark */
                        QMainWindow { background-color: #0d0d0d; }
                        QDockWidget, QDockWidget > QWidget { background-color: #141414; color: #ffffff; } /* dock: slightly lighter */
                        QDockWidget#plotControlDock > QWidget { background-color: #141414; }
                        QDockWidget::title { background-color: #141414; color: #ffffff; padding: 2px; }
                        QMenuBar { background-color: #1d1d1d; color: #ffffff; } /* header: lighter than dock */
                        QMenuBar::item { background-color: transparent; color: #ffffff; }
                        QStatusBar { background-color: #1d1d1d; color: #ffffff; } /* footer: same as header */

                        /* Dialogs */
                        QDialog, QMessageBox, QFileDialog { background-color: #141414; color: #ffffff; }
                        QDialog > QWidget, QMessageBox > QWidget, QFileDialog QWidget { background-color: #141414; color: #ffffff; }

                        /* Dialog buttons */
                        QDialog QPushButton, QMessageBox QPushButton, QFileDialog QPushButton {
                            background-color: #1e1e1e;
                            color: #ffffff;
                            border: 1px solid #2a2a2a;
                            padding: 4px 8px;
                        }
                        QDialog QPushButton:hover, QMessageBox QPushButton:hover, QFileDialog QPushButton:hover {
                            background-color: #2a2a2a;
                        }

                        /* Inputs */
                        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit,
                        QDateEdit, QTimeEdit, QDateTimeEdit {
                            color: #ffffff;
                            background-color: #1a1a1a;
                            border: 1px solid #2a2a2a;
                        }

                        /* Views inside dialogs (file lists, trees, tables) */
                        QListView, QTreeView, QTableView {
                            background-color: #1a1a1a;
                            color: #ffffff;
                            alternate-background-color: #151515;
                            selection-background-color: #2a2a2a;
                            selection-color: #ffffff;
                        }
                        QHeaderView::section {
                            background-color: #1d1d1d;
                            color: #ffffff;
                            border: 0px;
                            padding: 4px;
                        }

                        QLabel, QGroupBox, QPushButton, QComboBox, QLineEdit, QSpinBox, QCheckBox {
                            color: #ffffff;
                            background-color: transparent;
                        }
                        """
                    )
        else:
            self.mdi_area.setStyleSheet("background-color: #0d0d0d;")

        self.signal_trees = []  # type: list[BaseSignalTree]
        self.current_selected_signal_tree = None  # type: Union[BaseSignalTree, None]
        self._pending_navigator_assignment = None
        self._navigator_drag_payloads: dict[str, dict[str, object]] = {}
        self._navigator_drag_over_active = False
        with log_startup_time("Plot control dock creation"):
            self.add_plot_control_widget()

        with log_startup_time("Inst. control dock creation"):
            self.add_instrument_control_widget()


        self.cursor_readout = QtWidgets.QLabel("x: -, y: -, value: -")
        self.statusBar().addPermanentWidget(self.cursor_readout)

        # For accepting dropped files into the mdi area
        self.mdi_area.setAcceptDrops(True)
        self.mdi_area.installEventFilter(self)
        if app is not None:
            app.aboutToQuit.connect(self._shutdown_update_thread)

        print(
            f"Starting Dask LocalCluster with {workers} workers, and {threads_per_worker} threads per worker"
        )

        # Dask background startup
        self.client = None
        self.cluster = None  # add: keep cluster reference for clean shutdown
        self._dask_thread = QtCore.QThread(self)
        self._dask_worker = DaskClusterWorker(
            n_workers=workers,
            threads_per_worker=threads_per_worker,
        )
        self._dask_worker.moveToThread(self._dask_thread)
        self._dask_thread.started.connect(self._dask_worker.start)
        self._dask_worker.finished.connect(self._on_dask_ready)
        self._dask_worker.error.connect(self._on_dask_error)
        # ensure proper cleanup of worker object
        self._dask_thread.finished.connect(self._dask_worker.deleteLater)
        self._dask_thread.start()

        self.app.aboutToQuit.connect(self._shutdown_dask)
        self.app.aboutToQuit.connect(self._shutdown_update_thread)

    @QtCore.Slot(object, object)
    def _on_dask_ready(self, cluster, client):
        # store both client and cluster so we can close cleanly
        self.cluster = cluster
        self.client = client
        print(f"Dask cluster ready. Dashboard: {client.dashboard_link}")

        self._worker_keys = list(self.client.scheduler_info()['workers'].keys())
        self._heavy_compute_workers = self._worker_keys[1:]  # leave one worker free for GUI tasks
        # stop the bootstrap thread
        self._dask_thread.quit()
        self._dask_thread.wait(2000)

    @QtCore.Slot(Exception)
    def _on_dask_error(self, exc):
        print(f"Failed to start Dask cluster: {exc}")
        self._dask_thread.quit()
        self._dask_thread.wait(2000)

    def init_dask_cluster(self):
        with log_startup_time("Dask LocalCluster + Client setup"):
            cluster = LocalCluster(
                n_workers=self.n_workers, threads_per_worker=self.threads_per_worker
            )
            self.client = Client(cluster)
        print(f"Starting Dashboard at: {self.client.dashboard_link}")

    @property
    def plots(self) -> list[Plot]:
        """Get a flat list of all Plot instances in all plot windows."""
        all_plots = []
        for pw in self.plot_subwindows:
            all_plots.extend(pw.plots)
        return all_plots

    @property
    def navigation_selectors(self):
        selectors = []
        for s in self.signal_trees:
            if s.navigator_plot_manager is not None:
                selectors.extend(s.navigator_plot_manager.all_navigation_selectors)
        return selectors

    @QtCore.Slot(object, object, object)
    def on_plot_future_ready(self, plot: Plot, result: object, fid:int) -> None:
        """
        Receive finished compute results from the worker and apply them on the GUI thread.

        Parameters:
            plot: Plot to update.
            result: Either the computed data or an Exception.
            fid: The id of the Future that was completed.
        """
        if isinstance(result, Exception):
            print(f"Plot update failed: {result}")
            return
        try:
            print("Updating Plot from worker signal...")
            # make sure that the future is still the current data. It may have changed meanwhile.
            if id(plot.current_data) != fid:
                print("Plot data has changed since the Future was issued; skipping update.")
                return
            else:
                plot.current_data = result
                plot.update()
        except Exception as e:
            print(f"Failed to update plot: {e}")

    @QtCore.Slot(object, object, object)
    def on_signal_future_ready(self,
                               signal: BaseSignal,
                               result: object,
                               plot: Plot) -> None:
        """
        Receive finished compute results from the worker and apply them on the GUI thread.

        Parameters:


        Parameters
        ----------
        signal: Signal to update.
        result: Either the computed data or an Exception.
        plot:
            The targeted plot to update
        """
        if isinstance(result, Exception):
            print(f"signal update failed: {result}")
            return
        try:
            signal.data = result
            signal._lazy = False
            signal._assign_subclass()
            plot.parent_selector.delayed_update_data(update_contrast=True, force=True)
        except Exception as e:
            print(f"Failed to update signal: {e}")


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

        self.recent_menu = file_menu.addMenu("Open Recent")
        self._update_recent_menu()

        example_data = file_menu.addMenu("Load Example Data...")

        names = [
            "mgo_nanocrystals",
            "small_ptychography",
            "zrnb_precipitate",
            "pdcusi_insitu",
        ]
        for n in names:
            action = example_data.addAction(n)
            action.triggered.connect(partial(self.load_example_data, n))

        export_file = QAction("Export Current Signal...", self)
        export_file.triggered.connect(self.export_current_signal)
        file_menu.addAction(export_file)

        # Add View Menu
        view_menu = menubar.addMenu("View")

        # Add a view to open the dask dashboard
        view_dashboard_action = QAction("Open Dask Dashboard", self)
        view_dashboard_action.triggered.connect(self.open_dask_dashboard)
        view_menu.addAction(view_dashboard_action)

        view_plot_control_action = QAction("Toggle Plot Control Dock", self)
        view_plot_control_action.triggered.connect(self.toggle_plot_control_dock)
        view_menu.addAction(view_plot_control_action)

        view_camera_control_action = QAction("Toggle Instrument Control Dock", self)
        view_camera_control_action.triggered.connect(self.toggle_camera_control_dock)
        view_menu.addAction(view_camera_control_action)

    def toggle_plot_control_dock(self) -> None:
        """
        Toggle the visibility of the plot control dock widget.
        """
        if self.dock_widget is not None:
            is_visible = self.dock_widget.isVisible()
            self.dock_widget.setVisible(not is_visible)

    def toggle_camera_control_dock(self) -> None:
        """
        Toggle the visibility of the camera control dock widget.
        """
        if self.control_widget is not None:
            is_visible = self.control_widget.isVisible()
            self.control_widget.setVisible(not is_visible)

    def export_current_signal(self):
        if not isinstance(self._active_plot(), Plot):
            QMessageBox.warning(self, "Error", "No active plot window to export from.")
            return
        export_dialog = MovieExportDialog(plot=self._active_plot(), parent=self).exec()

    ### Handling Recent File opens ###

    def _add_to_recent(self, path: str) -> None:
        """Add a path to the recent-files list (persisted via QSettings)."""
        try:
            recent = self.settings.value("recentFiles", [])
            # QSettings may return a single string if only one item stored
            if isinstance(recent, str):
                recent = [recent]
            recent = list(recent or [])
            if path in recent:
                recent.remove(path)
            recent.insert(0, path)
            # cap recent list
            recent = recent[:10]
            self.settings.setValue("recentFiles", recent)
            self._update_recent_menu()
        except Exception:
            pass

    def _update_recent_menu(self) -> None:
        """Rebuild the Open Recent submenu from QSettings."""
        if self.recent_menu is None:
            return
        self.recent_menu.clear()
        recent = self.settings.value("recentFiles", [])
        if isinstance(recent, str):
            recent = [recent]
        recent = list(recent or [])
        if not recent:
            act = QAction("No recent files", self)
            act.setEnabled(False)
            self.recent_menu.addAction(act)
            return
        for path in recent:
            # show only the filename in the menu but keep full path in the triggered slot
            display = os.path.basename(path) if os.path.basename(path) else path
            act = QAction(display, self)
            act.setToolTip(path)
            act.triggered.connect(partial(self.open_recent, path))
            self.recent_menu.addAction(act)
        self.recent_menu.addSeparator()
        clear_act = QAction("Clear Recent", self)
        clear_act.triggered.connect(self._clear_recent)
        self.recent_menu.addAction(clear_act)

    def open_recent(self, path: str) -> None:
        """Open a recent file (called by the recent menu actions)."""
        if not os.path.isfile(path):
            QMessageBox.warning(self, "Open Recent", f"File not found: {path}")
            # remove missing entry
            try:
                recent = self.settings.value("recentFiles", [])
                if isinstance(recent, str):
                    recent = [recent]
                recent = list(recent or [])
                if path in recent:
                    recent.remove(path)
                    self.settings.setValue("recentFiles", recent)
                    self._update_recent_menu()
            except Exception:
                pass
            return
        # reuse existing loading path
        self._create_signals([path])
        # ensure the opened file is moved to the top of recent
        self._add_to_recent(path)

    def _clear_recent(self) -> None:
        """Clear the recent-files list."""
        try:
            self.settings.remove("recentFiles")
            self._update_recent_menu()
        except Exception:
            pass

    def open_dask_dashboard(self) -> None:
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
            data, navigators = dialog.get_data()
            print("Data created")
            if data is not None:
                self.add_signal(data, navigators=navigators)

    def _create_signals(self, file_paths: list[str]) -> None:
        """Internal helper to load multiple file paths into signals and add them."""
        for file_path in file_paths:
            kwargs = {"lazy": True}
            if file_path.endswith(".mrc"):
                dialog = DatasetSizeDialog(self, filename=file_path)
                print("Opening Dataset Size Dialog for .mrc file")
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    x_size = dialog.x_input.value()
                    y_size = dialog.y_input.value()
                    time_size = dialog.time_input.value()
                    kwargs["navigation_shape"] = tuple(
                        [val for val in (x_size, y_size, time_size) if val > 1]
                    )
                    print(f"{kwargs['navigation_shape']}")
                else:
                    print("Dialog cancelled")
                    return
                # .mrc always have 2 signal axes.  Maybe needs changed for eels.
                if len(kwargs["navigation_shape"]) == 3:
                    kwargs["chunks"] = (
                        (1,) + ("auto",) * (len(kwargs["navigation_shape"]) - 1)
                    ) + (-1, -1)
                else:
                    kwargs["chunks"] = (("auto",) * len(kwargs["navigation_shape"])) + (
                        -1,
                        -1,
                    )

                print(f"chunks: {kwargs['chunks']}")
            if hasattr(kwargs, "navigation_shape") and kwargs["navigation_shape"] == ():
                kwargs.pop("navigation_shape")
                kwargs.pop("chunks")
            print("Loading signal from file:", file_path, "with kwargs:", kwargs)
            signal = hs.load(file_path, **kwargs)
            if kwargs.get("lazy", False):
                if signal.axes_manager.navigation_dimension == 1:
                    signal.cache_pad = 3
                elif signal.axes_manager.navigation_dimension == 2:
                    signal.cache_pad = 2
            print("Signal loaded:", signal)
            print("Signal shape:", signal.data.shape)
            print("Signal Chunks:", signal.data.chunks)
            self.add_signal(signal)
            try:
                self._add_to_recent(file_path)
            except Exception:
                print("Failed to add to recent files list")

    def open_file(self):
        self.file_dialog = QFileDialog()
        self.file_dialog.setFileMode(QtWidgets.QFileDialog.FileMode.ExistingFiles)
        self.file_dialog.setNameFilter("Supported Files (*.hspy *.mrc);;"
                                       "Hyperspy Files (*.hspy);;"
                                       "mrc Files (*.mrc)")

        if self.file_dialog.exec():
            file_paths = self.file_dialog.selectedFiles()
            if file_paths:
                self._create_signals(file_paths)

    def add_signal(self, signal, navigators=None) -> None:
        """Add a signal to the main window.

        This will "plant" a new seed for a signal tree and set up the associated plots.

        Parameters
        ----------
        signal : hs.signals.BaseSignal
            The hyperspy signal to add.

        """
        print("Creating Signal Tree for signal")

        # If Dask client is not ready, show a waiting message and check until it is
        if self.client is None:
            message_box = QtWidgets.QMessageBox(self)
            message_box.setWindowTitle("Please wait")
            message_box.setText("Dask client is still initializing. Please wait...")
            message_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.NoButton)
            message_box.setModal(False)
            message_box.show()

            while self.client is None:
                QApplication.processEvents()
            message_box.hide()
            message_box.close()


        signal_tree = BaseSignalTree(
            root_signal=signal, main_window=self, distributed_client=self.client
        )
        self.signal_trees.append(signal_tree)
        print("Signal Tree Created")
        if navigators is not None:
            for i, nav in enumerate(navigators):
                title = nav.metadata.get_item(
                    "General.title", default="navigation_" + str(i)
                )
                if title == "":
                    title = "navigation_" + str(i)
                print("Adding navigator signal:", title)
                signal_tree.add_navigator_signal(title, nav)

        if signal.metadata.get_item("General.virtual_images", False):
            for key, item in signal.metadata.General.virtual_images:
                print("Adding virtual image navigator signal:", key)
                signal_tree.add_navigator_signal(key, item)

    def load_example_data(self, name):
        """
        Load example data for testing purposes.
        """
        signal = getattr(pyxem.data, name)(allow_download=True, lazy=True)
        self.add_signal(signal)
        print("Example data loaded:", name)

    def add_plot_window(
        self,
        is_navigator: bool = False,  # if navigator then it will share the navigation selectors
        plot_manager: Union["MultiplotManager", None] = None,
        signal_tree: Union["BaseSignalTree", None] = None,
        *args,
        **kwargs,
    ) -> PlotWindow:
        """
        Plot window construction:
        Create a new PlotWindow instance, add it to the MDI area, and set it up.

        Parameters
        ----------
        is_navigator : bool
            Whether this plot window is for a navigator signal.
        plot_manager : MultiplotManager or None
            The plot manager to associate with this plot window.
        signal_tree : BaseSignalTree or None
            The signal tree to associate with this plot window.
        Returns
        -------
        PlotWindow
            The created PlotWindow instance.
        """
        pw = PlotWindow(
            is_navigator=is_navigator,
            main_window=self,
            signal_tree=signal_tree,
            plot_manager=plot_manager,
            *args,
            **kwargs,
        )
        # pw.setWidget(pw.container)

        pw.resize(self.screen_size.height() // 3, self.screen_size.height() // 3)

        # Add to MDI and make the subwindow frameless
        self.mdi_area.addSubWindow(pw)
        try:
            # Remove title bar and frame
            pw.setWindowFlags(pw.windowFlags() | Qt.WindowType.FramelessWindowHint)
            pw.setStyleSheet("QMdiSubWindow { border: none; }")
        except Exception:
            pass

        pw.show()
        self.plot_subwindows.append(pw)
        # set the main window reference in the plot
        return pw

    def update_metadata_widget(self, plot: Plot) -> None:
        """Rebuild metadata panel for the active Plot's signal tree."""
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
        if hasattr(plot, "signal_tree"):
            signal_tree = plot.signal_tree
            metadata_dict = signal_tree.get_metadata_widget()
            for subsection, items in metadata_dict.items():
                group = QtWidgets.QGroupBox(str(subsection))

                # Keep each group a constant height and allow scrolling inside
                group.setSizePolicy(
                    QtWidgets.QSizePolicy.Policy.Expanding,
                    QtWidgets.QSizePolicy.Policy.Fixed,
                )
                group.setFixedHeight(120)

                # Group layout that holds the scroll area
                group_layout = QtWidgets.QVBoxLayout(group)
                group_layout.setContentsMargins(6, 6, 6, 6)
                group_layout.setSpacing(0)

                # Scroll area inside the group
                scroll = QtWidgets.QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setHorizontalScrollBarPolicy(
                    Qt.ScrollBarPolicy.ScrollBarAsNeeded
                )
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
                    key_label.setAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                    grid.addWidget(key_label, row, 0)
                    grid.addWidget(value_label, row, 1)

                grid.setColumnStretch(0, 0)
                grid.setColumnStretch(1, 1)

                scroll.setWidget(container)
                group_layout.addWidget(scroll)

                self.metadata_layout.addWidget(group)

    def update_axes_widget(self, window: "Plot") -> None:
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

    def set_cursor_readout(
        self, x=None, y=None, xpix=None, ypix=None, value=None
    ) -> None:
        """Update status bar readout with cursor coordinates and data value."""

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

    def on_subwindow_activated(self, window: "PlotWindow") -> None:
        """MDI activation handler: update toolbars, metadata, histogram binding, and colormap selector."""
        # Guard against re-entry


        print("Subwindow activated:", window)
        if window is None or not isinstance(window, PlotWindow):
            return

        plot = window.current_plot_item
        plot_state = getattr(plot, "plot_state", None)
        if plot is None:
            return

        # hide all toolbar from other plots in the same window except toolbars from
        # the active signal tree
        if window.signal_tree.navigator_plot_manager is not None:
            active_plots = [win.current_plot_item for
                            win in window.signal_tree.navigator_plot_manager.all_plot_windows
                            if win.isVisible()]
        else:
            active_plots = [plot]

        for plt in active_plots:
            plt.plot_state.show_toolbars()
            plt.show_selector_control_widget()

        for win in self.plot_subwindows:
            for plt in win.plots:
                if plt in active_plots:
                    continue
                else:
                    plt.plot_state.hide_toolbars()
                    plt.remove_selector_control_widgets()

        # Histogram binding: use the image_item on the inner widget / plot
        img_item = plot.image_item
        if (
            self.histogram is not None
            and img_item is not None
            and img_item is not self._histogram_image_item
        ):
            try:
                self.histogram.setImageItem(img_item)
                self._histogram_image_item = img_item
                if plot_state is not None:
                    self.histogram.setLevels(plot_state.min_level, plot_state.max_level)
            except Exception:
                pass

        st = getattr(window, "signal_tree", None)
        if st is not None and st is not self.current_selected_signal_tree:
            self.current_selected_signal_tree = st
            self.update_metadata_widget(plot)

        if plot_state is not None and hasattr(self, "cmap_selector"):
            self.cmap_selector.setCurrentText(plot_state.colormap)


    def add_instrument_control_widget(self):
        """
        This is the left-hand side docked widget that contains the instrument controls.
        """
        self.control_widget = ControlDockWidget()
        self.control_widget.setVisible(False)  # Add this line

        self.addDockWidget(
            QtCore.Qt.DockWidgetArea.LeftDockWidgetArea, self.control_widget
        )
        self.control_widget.add_widget(StageControlWidget())
        self.control_widget.add_widget(CameraControlWidget())
        self.control_widget.add_widget(StemControlWidget())
        self.control_widget.add_widget(ReferenceControlWidget())


    def add_plot_control_widget(self):
        """
        This is the right-hand side docked widget the contains the plot controls, image metadata
        and the selector controls.

        It updates with the current active plot in the MDI area.

        """
        self.dock_widget = QtWidgets.QDockWidget("Plot Control", self)
        self.dock_widget.setObjectName("plotControlDock")
        self.dock_widget.setFeatures(
            self.dock_widget.features()
            & ~QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.dock_widget.setBaseSize(self.width() // 6, self.height() // 6)

        # Create a main widget and layout

        main_widget = QtWidgets.QWidget()
        main_widget.setAutoFillBackground(True)
        main_widget.setStyleSheet("background-color: #141414;")
        layout = QtWidgets.QVBoxLayout(main_widget)

        # Creating the display group box
        # ------------------------------
        display_group = QtWidgets.QGroupBox("Plot Display Controls")
        display_group.setMaximumHeight(250)
        display_layout = QtWidgets.QVBoxLayout(display_group)

        # Create a Histogram plot LUT widget
        self.histogram = HistogramLUTWidget(
            orientation="horizontal", autoLevel=False, constantLevel=True
        )  # type: HistogramLUTWidget
        self.histogram.setMinimumWidth(200)
        self.histogram.setMinimumHeight(100)
        self.histogram.setMaximumHeight(150)
        self.histogram.item.sigLevelChangeFinished.connect(
            self.on_histogram_levels_finished
        )
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
        self.dock_widget.setWidget(main_widget)

        self.addDockWidget(
            QtCore.Qt.DockWidgetArea.RightDockWidgetArea, self.dock_widget
        )

    def _active_plot(self) -> Union[Plot, None]:
        """Return the currently active QMdiSubWindow (Plot) or None."""
        sub = self.mdi_area.activeSubWindow()
        if not isinstance(sub, PlotWindow):
            return None
        else:
            return sub.current_plot_item

    def _active_plot_window(self) -> Union[PlotWindow, None]:
        """Return the currently active QMdiSubWindow (PlotWindow) or None."""
        sub = self.mdi_area.activeSubWindow()
        if not isinstance(sub, PlotWindow):
            return None
        else:
            return sub

    def on_contrast_auto_click(self) -> None:
        """
        Set image contrast to [1st, 99th] percentile for 2D; y-range percentiles for 1D.
        Persist on PlotState, so it remains constant when data changes.
        """
        w = self._active_plot()
        if w is None or not hasattr(w, "plot_state") or w.plot_state is None:
            return

        if getattr(w.plot_state, "dimensions", 0) == 2:
            mn, mx = self.histogram.percentile2levels(0.00, 99.0)
            self.histogram.setLevels(mn, mx)

    def on_contrast_reset_click(self) -> None:
        """
        Reset contrast to full range for 2D; re-enable y auto-range for 1D.
        Persist on PlotState.
        """
        w = self._active_plot()
        if w is None or not hasattr(w, "plot_state") or w.plot_state is None:
            return
        if getattr(w.plot_state, "dimensions", 0) == 2:
            mn, mx = w.image_item.quickMinMax()
            self.histogram.setLevels(mn, mx)

    def on_cmap_changed(self, cmap_name: str) -> None:
        # Apply colormap to the active plot and sync the histogram widget
        sub = self.mdi_area.activeSubWindow()
        if sub is None:
            return
        if hasattr(sub, "set_colormap"):
            print("Setting colormap on plot:", cmap_name)
            sub.set_colormap(cmap_name)

    def on_histogram_levels_finished(self, signal: HistogramLUTItem) -> None:
        """
        On histogram level change, update the active plot's contrast via PlotState
        and apply immediately. Guard against missing histogram data.
        """
        # Guard: histogram not ready yet
        if (
            signal is None
            or getattr(signal, "bins", None) is None
            or getattr(signal, "counts", None) is None
        ):
            return
        percentiles = signal.get_percentile_levels()
        levels = signal.getLevels()
        w = self._active_plot()
        if w is None or not hasattr(w, "plot_state") or w.plot_state is None:
            return
        else:
            w.plot_state.max_level = levels[1]
            w.plot_state.min_level = levels[0]
            w.plot_state.max_percentile = percentiles[1]
            w.plot_state.min_percentile = percentiles[0]
        print("Setting levels:", levels, "percentiles:", percentiles, "on plot:", w)

    def _is_supported_file(self, path: str) -> bool:
        try:
            return os.path.isfile(path) and path.lower().endswith(SUPPORTED_EXTS)
        except Exception:
            return False

    def _extract_file_paths(self, mime) -> list[str]:
        paths = []
        if mime is None:
            return paths
        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile():
                    p = url.toLocalFile()
                    if p:
                        paths.append(p)
        elif mime.hasText():
            for chunk in mime.text().split():
                if os.path.isfile(chunk):
                    paths.append(chunk)
        return paths

    def _handle_drop_files(self, paths: list[str]) -> None:
        files = [p for p in paths if self._is_supported_file(p)]
        if files:
            self._create_signals(files)

    # Only handle drag/drop on the MDI area
    def eventFilter(
        self,
        obj,
        event: QEvent,
    ) -> bool:
        """Handle clicks, drags and drops into the main window."""

        if event is not None:
            et = event.type()
            if obj is self._active_plot_window() and et == QEvent.Type.MouseButtonPress:
                try:
                    pos = event.position().toPoint()
                except Exception:
                    pos = event.pos()
                print("click pos:", pos)
                for plot in self.plots:
                    contains = plot.geometry().contains(pos)
                    if contains:
                        print("Clicked on plot:", plot)
                        self.current_plot_item = plot

            if obj is self.mdi_area:
                et = event.type()

                # Handle navigator drag events only when entering/moving over the active subwindow
                # on drag start then save the layout

                if et in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
                    mime = event.mimeData()
                    if mime is not None and mime.hasFormat(NAVIGATOR_DRAG_MIME):
                        active_sub = self.mdi_area.activeSubWindow()
                        if active_sub is not None:
                            try:
                                pos = event.position().toPoint()
                            except Exception:
                                pos = event.pos()
                            contains = active_sub.geometry().contains(pos)
                            if contains:
                                local_x = pos.x() - active_sub.geometry().x()
                                local_y = pos.y() - active_sub.geometry().y()
                                if not self._navigator_drag_over_active:
                                    self.navigator_enter()
                                    print(
                                        f"Navigator drag entered active subwindow at local position: ({local_x}, {local_y})"
                                    )
                                else:
                                    self.navigator_move(pos=pos)
                                    print(
                                        f"Navigator drag moving inside active subwindow at local position: ({local_x}, {local_y})"
                                    )
                                self._navigator_drag_over_active = True
                                event.acceptProposedAction()
                                return True
                            if self._navigator_drag_over_active:
                                print("Navigator drag over")
                                self.navigator_leave()
                                print("Navigator drag left active subwindow")
                                self._navigator_drag_over_active = False
                            return False
                    # Fallback: existing file-drag handling (unchanged)
                    paths = self._extract_file_paths(mime)
                    if any(self._is_supported_file(p) for p in paths):
                        event.acceptProposedAction()
                        return True

                elif et == QEvent.Type.Drop:
                    mime = event.mimeData()
                    # Handle navigator drop only if over active subwindow
                    if mime is not None and mime.hasFormat(NAVIGATOR_DRAG_MIME):
                        active_sub = self.mdi_area.activeSubWindow()
                        try:
                            pos = event.position().toPoint()
                        except Exception:
                            pos = event.pos()
                        contains = (
                            active_sub is not None
                            and active_sub.geometry().contains(pos)
                        )
                        if contains:
                            local_x = pos.x() - active_sub.geometry().x()
                            local_y = pos.y() - active_sub.geometry().y()
                            print(
                                f"Navigator dropped into active subwindow at local position: ({local_x}, {local_y})"
                            )
                            self._navigator_drag_over_active = False
                            self.navigator_drop(pos=pos, mime_data=mime)
                            event.acceptProposedAction()
                            return True
                        if self._navigator_drag_over_active:
                            print("Navigator drag left active subwindow before drop")
                            self._navigator_drag_over_active = False
                        return False

                elif et == QEvent.Type.DragLeave:
                    if self._navigator_drag_over_active:
                        print("Navigator drag left active subwindow")
                        self.navigator_leave()
                        self._navigator_drag_over_active = False
            return super().eventFilter(obj, event)
        return None

    def register_navigator_drag_payload(self, signal, nav_manager) -> str:
        token = uuid4().hex
        self._navigator_drag_payloads[token] = {
            "signal": signal,
            "nav_manager": nav_manager,
        }
        return token

    def navigator_enter(self):
        """
        Handle navigator drag enter event. Creates a visual placeholder. This is used to show where the
        navigator plot will be placed.
        """
        # Create placeholder
        placeholder = pg.PlotItem()
        placeholder.setTitle("Drop Navigator Here", color="#888888")
        placeholder.hideAxis("left")
        placeholder.hideAxis("bottom")

        rect = pg.QtWidgets.QGraphicsRectItem()
        rect.setBrush(pg.mkBrush((100, 100, 255, 100)))
        rect.setPen(pg.mkPen((100, 100, 255), width=2))
        placeholder.addItem(rect)

        self._navigator_placeholder = placeholder
        self._navigator_placeholder_rect = rect

    def navigator_move(self, pos: QtCore.QPointF):
        """
        Handle navigator drag move event. Just repositions the placeholder without clearing/redrawing
        the entire layout.

        This is more efficient than recreating the layout each time but more complicated...
        """
        active_plot_window = self._active_plot_window()
        if active_plot_window is None or not hasattr(self, "_navigator_placeholder"):
            return
        # Calculate new position
        active_plot_window._build_new_layout(
            drop_pos=pos, plot_to_add=self._navigator_placeholder
        )
        # self.build_new_layout(active_plot_window, drop_pos=pos, plot_to_add=self._navigator_placeholder)

        if hasattr(self, "_navigator_placeholder_rect"):
            vb = self._navigator_placeholder.getViewBox()
            self._navigator_placeholder_rect.setRect(vb.rect())

    def navigator_leave(self):
        """
        Handle navigator drag leave event. Removes the placeholder and
        restores the original layout.
        """
        active_plot_window = self._active_plot_window()
        print("Setting back original layout:", active_plot_window.previous_subplots_pos)
        active_plot_window.set_graphics_layout_widget(
            active_plot_window.previous_subplots_pos
        )

    def navigator_drop(self, pos: QtCore.QPointF, mime_data):
        """
        Handle navigator drop event. Creates the actual navigator plot
        at the drop position.
        """
        active_plot_window = self._active_plot_window()
        if active_plot_window is None:
            return
        nav_plot = active_plot_window.insert_new_plot(
            drop_pos=pos,
        )

        # Extract navigator data from mime
        token = mime_data.data(NAVIGATOR_DRAG_MIME).data().decode("utf-8")
        payload = self._navigator_drag_payloads.pop(token, None)
        if payload is None:
            return

        signal = payload["signal"]  # type: hs.signals.BaseSignal
        print("Adding navigator signal to plot:", signal)
        for navigation_signal in nav_plot.signal_tree.navigator_signals.values():
            nav_plot.multiplot_manager.add_plot_states_for_navigation_signals(
                navigation_signal
            )
        print("setting plot state to:", signal[0])
        print(signal[0].data)
        nav_plot.set_plot_state(signal=signal[0])
        # Clean up
        self._original_layout_state = {}
        active_plot_window.previous_subplots_pos = {}
        active_plot_window.previous_subplot_added = None
        self._original_layout = None
        # TODO: reset view to fit data

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        # 1) shutdown Dask to stop its background threads and logging
        self._shutdown_dask()
        # 2) stop any QThreads we own
        self._shutdown_update_thread()
        super().closeEvent(event)

    def _shutdown_dask(self) -> None:
        """Robust shutdown for Dask used during application quit.

        - Silence distributed logging.
        - Scale cluster to 0, close cluster, then close client.
        - Wait briefly to let processes exit, then attempt to terminate
          any multiprocessing children started from this process.
        - Must be called on the main thread before QApplication teardown.
        """
        import logging
        import time
        import multiprocessing as mp
        import gc

        print("Shutting down Dask cluster and client...")

        # Silence distributed logs to avoid I/O errors during teardown
        try:
            for name in ("distributed", "distributed.comm", "distributed.comm.tcp"):
                lg = logging.getLogger(name)
                lg.setLevel(logging.CRITICAL)
                lg.propagate = False
                try:
                    lg.handlers.clear()
                except Exception:
                    lg.handlers = []
                lg.addHandler(logging.NullHandler())
        except Exception:
            pass

        # Close client first if present (client talks to cluster)
        try:
            client = getattr(self, "client", None)
            if client is not None:
                try:
                    client.close(timeout="2s")
                except TypeError:
                    # older/newer API may expect numeric timeout
                    try:
                        client.close(timeout=2)
                    except Exception:
                        client.close()
                except Exception:
                    # fallback to best-effort close
                    try:
                        client.close()
                    except Exception:
                        pass
                finally:
                    self.client = None
        except Exception:
            self.client = None

        # Then scale down and close the cluster
        try:
            cluster = getattr(self, "cluster", None)
            if cluster is not None:
                try:
                    # try a graceful scale-down first
                    try:
                        cluster.scale(0)
                    except Exception:
                        pass
                    # close the cluster (synchronous)
                    try:
                        cluster.close(timeout="2s")
                    except TypeError:
                        cluster.close(timeout=2)
                    except Exception:
                        cluster.close()
                except Exception:
                    pass
                finally:
                    self.cluster = None
        except Exception:
            self.cluster = None

        # Give OS a moment to reap processes and release semaphores
        time.sleep(0.5)

        # Attempt to clean up multiprocessing children started by this process
        try:
            for child in mp.active_children():
                print("Terminating leftover child process:", child.pid)
                try:
                    child.terminate()
                    child.join(timeout=0.5)
                except Exception:
                    try:
                        child.kill()
                    except Exception:
                        pass
        except Exception:
            pass

        # Force garbage collection (helps resource_tracker cleanup)
        try:
            gc.collect()
        except Exception:
            pass

    def _shutdown_update_thread(self) -> None:
        worker = getattr(self, "_plot_update_worker", None)
        thread = getattr(self, "_update_thread", None)

        if worker is not None:
            QtCore.QMetaObject.invokeMethod(
                worker, "stop", QtCore.Qt.ConnectionType.QueuedConnection
            )
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(2000)

        # also ensure the dask bootstrap thread is stopped if still running
        dthread = getattr(self, "_dask_thread", None)
        if dthread is not None and dthread.isRunning():
            dthread.quit()
            dthread.wait(2000)

    def close(self) -> None:
        self._shutdown_update_thread()
        try:
            self.client.shutdown()
        except Exception:
            pass
        super().close()


def main() -> MainWindow:
    with log_startup_time("QApplication startup"):
        app = QtWidgets.QApplication(sys.argv)
        app.setApplicationName("SpyDe")  # Set the application name
    # Create and show the splash screen
    logo_path = "SpydeDark.png"
    pixmap = QPixmap(logo_path).scaled(
        300,
        300,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )

    splash = QSplashScreen(pixmap, Qt.WindowType.FramelessWindowHint)
    splash.show()
    splash.raise_()  # Bring the splash screen to the front
    app.processEvents()
    with log_startup_time("MainWindow construction"):
        main_window = MainWindow(app=app)

    main_window.setWindowTitle("SpyDE")  # Set the window title

    if sys.platform == "darwin":
        base_dir = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.join(base_dir, "icon.icns")
        print("Using macOS icon:", logo_path)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.join(base_dir, "SpydeDark.png")

    main_window.setWindowIcon(QIcon(str(logo_path)))
    main_window.show()
    splash.finish(main_window)  # Close the splash screen when the main window is shown

    app.exec()
    return main_window


if __name__ == "__main__":
    # multiprocessing.freeze_support()
    sys.exit(main())
