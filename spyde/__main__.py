from __future__ import annotations
import sys
import os
from collections import deque
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

from dask.distributed import Future
import pyqtgraph as pg
import hyperspy.api as hs
import pyxem.data
from hyperspy.signal import BaseSignal

from spyde.live.camera_control_widget import CameraControlWidget
from spyde.live.control_dock_widget import ControlDockWidget
from spyde.live.particle_scanning import ParticleScanControlWidget
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
from spyde.drawing.colormaps import COLORMAPS
from spyde.dask_manager import DaskManager
from spyde.dock_manager import DockManager
from spyde.drawing.signal_tree_presenter import build_axes_groups, build_metadata_dict

SUPPORTED_EXTS = (".hspy", ".mrc", ".tif", ".tiff", ".de5")  # extend as needed


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
        self._pending_signal_queue: deque = deque()  # thread-safe deque for cross-thread signal delivery

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
            self.dock_manager = DockManager(main_window=self, parent=self)
            # expose selectors_layout for Plot.show_selector_control_widget compatibility
            self.selectors_layout = self.dock_manager.selectors_layout
            self.histogram = self.dock_manager.histogram
            self.cmap_selector = self.dock_manager.cmap_selector
            self.metadata_layout = self.dock_manager.metadata_layout
            self.axes_layout = self.dock_manager.axes_layout
            self.btn_auto = self.dock_manager.btn_auto
            self.btn_reset = self.dock_manager.btn_reset
            # expose dock/control widgets for backward compat
            self.dock_widget = self.dock_manager.dock_widget
            self.control_widget = self.dock_manager.control_widget


        self.cursor_readout = QtWidgets.QLabel("x: -, y: -, value: -")
        self.statusBar().addPermanentWidget(self.cursor_readout)

        # For accepting dropped files into the mdi area
        self.mdi_area.setAcceptDrops(True)
        self.mdi_area.installEventFilter(self)
        print(f"Starting Dask LocalCluster with {workers} workers, {threads_per_worker} threads per worker")
        self.dask_manager = DaskManager(
            n_workers=workers,
            threads_per_worker=threads_per_worker,
            parent=self,
        )
        self.dask_manager.ready.connect(self._on_dask_ready)
        self.dask_manager.start()
        if self.app is not None:
            self.app.aboutToQuit.connect(self.dask_manager.shutdown)
            self.app.aboutToQuit.connect(self._shutdown_update_thread)

    @QtCore.Slot()
    def _on_dask_ready(self):
        print("MainWindow: Dask ready.")

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
        view_plot_control_action.triggered.connect(lambda: self.dock_manager.toggle_plot_control())
        view_menu.addAction(view_plot_control_action)

        view_camera_control_action = QAction("Toggle Instrument Control Dock", self)
        view_camera_control_action.triggered.connect(lambda: self.dock_manager.toggle_instrument_control())
        view_menu.addAction(view_camera_control_action)

        tile_action = QAction("Tile Active Windows", self)
        tile_action.triggered.connect(self.tile_active_windows)
        tile_action.setShortcut("Ctrl+T")
        view_menu.addAction(tile_action)

    def export_current_signal(self):
        plot = self._active_plot()
        if not isinstance(plot, Plot):
            QMessageBox.warning(self, "Error", "No active plot window to export from.")
            return
        MovieExportDialog(plot=plot, parent=self).exec()

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
        if self.dask_manager.client:
            dashboard_url = self.dask_manager.client.dashboard_link
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
            if "navigation_shape" in kwargs and kwargs["navigation_shape"] == ():
                kwargs.pop("navigation_shape")
                kwargs.pop("chunks")
            print("Loading signal from file:", file_path, "with kwargs:", kwargs)
            # tifffile-backed lazy arrays embed an open BufferedReader that
            # cannot be pickled by Dask's distributed scheduler.  Load the
            # TIFF eagerly and then convert to a serializable dask array via
            # as_lazy(), which calls da.from_array on the in-memory numpy data.
            is_tiff = file_path.lower().endswith((".tif", ".tiff"))
            if is_tiff:
                tiff_kwargs = {k: v for k, v in kwargs.items() if k != "lazy"}
                signal = hs.load(file_path, lazy=False, **tiff_kwargs)
                signal = signal.as_lazy()
            else:
                signal = hs.load(file_path, **kwargs)
            # fix MRC loading in rsciio.
            if (signal.axes_manager.signal_dimension + signal.axes_manager.navigation_dimension) == 2:
                signal = signal.transpose(2)
            if kwargs.get("lazy", False) or is_tiff:
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
        self.file_dialog.setNameFilter("Supported Files (*.hspy *.mrc *.tif *.tiff);;"
                                       "Hyperspy Files (*.hspy);;"
                                       "mrc Files (*.mrc);;"
                                       "TIFF Files (*.tif *.tiff)")

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
        if self.dask_manager.client is None:
            message_box = QtWidgets.QMessageBox(self)
            message_box.setWindowTitle("Please wait")
            message_box.setText("Dask client is still initializing. Please wait...")
            message_box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.NoButton)
            message_box.setModal(False)
            message_box.show()

            while self.dask_manager.client is None:
                QApplication.processEvents()
            message_box.hide()
            message_box.close()


        signal_tree = BaseSignalTree(
            root_signal=signal, main_window=self, distributed_client=self.dask_manager.client
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

    @QtCore.Slot(object)
    def _add_signal_from_thread(self, signal):
        """Thread-safe slot to add a committed virtual image signal."""
        self.add_signal(signal)

    @QtCore.Slot()
    def _flush_pending_signals(self):
        """Drain the thread-safe pending-signal queue on the GUI thread."""
        while self._pending_signal_queue:
            sig = self._pending_signal_queue.popleft()
            self.add_signal(sig)

    def load_example_data(self, name):
        """
        Load example data for testing purposes.
        """
        signal = getattr(pyxem.data, name)(allow_download=True, lazy=True)
        self.add_signal(signal)
        print("Example data loaded:", name)

    def _auto_position_near_owner(self, pw: "PlotWindow") -> None:
        """Position pw to the right of its owner, or below if no room."""
        owner = pw.owner_plot_window
        if owner is None:
            return
        mdi_rect = self.mdi_area.rect()
        gap = 8
        # Try right of owner
        x = owner.x() + owner.width() + gap
        y = owner.y()
        if x + pw.width() <= mdi_rect.width():
            pw.move(x, y)
            return
        # Try below owner
        x = owner.x()
        y = owner.y() + owner.height() + gap
        if y + pw.height() <= mdi_rect.height():
            pw.move(x, y)
            return
        # Clamp to MDI bounds as fallback
        x = min(x, max(0, mdi_rect.width() - pw.width()))
        y = min(y, max(0, mdi_rect.height() - pw.height()))
        pw.move(x, y)

    def tile_active_windows(self) -> None:
        """Tile all Shown PlotWindows (active SignalTree) in an even grid."""
        import math
        active = self.mdi_area.activeSubWindow()
        if not isinstance(active, PlotWindow):
            return
        active_tree = active.signal_tree
        shown = [
            pw for pw in self.plot_subwindows
            if pw.signal_tree is active_tree and pw.isVisible()
        ]
        n = len(shown)
        if n == 0:
            return
        cols = math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)
        mdi_rect = self.mdi_area.rect()
        margin = 6
        cell_w = (mdi_rect.width() - margin * (cols + 1)) // cols
        cell_h = (mdi_rect.height() - margin * (rows + 1)) // rows
        for i, pw in enumerate(shown):
            row = i // cols
            col = i % cols
            x = margin + col * (cell_w + margin)
            y = margin + row * (cell_h + margin)
            pw.setGeometry(x, y, cell_w, cell_h)

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
        if self.metadata_layout is None:
            return
        while self.metadata_layout.count():
            item = self.metadata_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            else:
                del item

        if hasattr(plot, "signal_tree"):
            metadata_dict = build_metadata_dict(plot.signal_tree)
            for subsection, items in metadata_dict.items():
                group = QtWidgets.QGroupBox(str(subsection))
                group.setSizePolicy(
                    QtWidgets.QSizePolicy.Policy.Expanding,
                    QtWidgets.QSizePolicy.Policy.Fixed,
                )
                group.setFixedHeight(120)
                group_layout = QtWidgets.QVBoxLayout(group)
                group_layout.setContentsMargins(6, 6, 6, 6)
                group_layout.setSpacing(0)
                scroll = QtWidgets.QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
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
        if self.axes_layout is None:
            return
        while self.axes_layout.count():
            item = self.axes_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            else:
                del item

        if hasattr(window, "signal_tree") and window.signal_tree is not None:
            plot_state = window.plot_state
            current_signal = plot_state.current_signal if plot_state else None
            groups = build_axes_groups(window.signal_tree, current_signal, window)
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
        if getattr(self, '_in_subwindow_activated', False):
            return
        self._in_subwindow_activated = True
        try:
            self._on_subwindow_activated_impl(window)
        finally:
            self._in_subwindow_activated = False

    def _on_subwindow_activated_impl(self, window: "PlotWindow") -> None:
        """Implementation of on_subwindow_activated — never call directly."""
        print("Subwindow activated:", window)
        if window is None or not isinstance(window, PlotWindow):
            return

        plot = window.current_plot_item
        plot_state = getattr(plot, "plot_state", None)
        if plot is None:
            return

        # hide all toolbar from other plots in the same window except toolbars from
        # the active signal tree
        if window.signal_tree is not None and window.signal_tree.navigator_plot_manager is not None:
            active_plots = [w.current_plot_item for
                            w in window.signal_tree.navigator_plot_manager.all_plot_windows
                            if w.isVisible()]
        else:
            active_plots = [plot]

        for plt in active_plots:
            if getattr(plt, "plot_state", None) is not None:
                plt.plot_state.show_toolbars()
            if hasattr(plt, "show_selector_control_widget"):
                plt.show_selector_control_widget()

        for pw in self.plot_subwindows:
            for plt in pw.plots:
                if plt in active_plots:
                    continue
                if getattr(plt, "plot_state", None) is not None:
                    plt.plot_state.hide_toolbars()

        # ── 3-state visibility ───────────────────────────────────────────────────
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        active_tree = window.signal_tree
        for pw in self.plot_subwindows:
            same_tree = (pw.signal_tree is active_tree)
            is_action_preview = (pw.owner_plot_window is not None)
            action = getattr(pw, 'controlling_action', None)
            # Non-checkable actions don't track toggle state — always show their windows
            action_wants_visible = (action is None or not action.isCheckable() or action.isChecked())

            if same_tree and action_wants_visible:
                if not pw.isVisible():
                    pw.show()
                pw.setGraphicsEffect(None)
            elif same_tree and not action_wants_visible:
                pw.hide()
            elif is_action_preview:
                pw.hide()
            else:
                if not pw.isVisible():
                    pw.show()
                effect = QGraphicsOpacityEffect(pw)
                effect.setOpacity(0.65)
                pw.setGraphicsEffect(effect)
        # ── end 3-state visibility ───────────────────────────────────────────────

        st = getattr(window, "signal_tree", None)
        if st is not None and st is not self.current_selected_signal_tree:
            self.current_selected_signal_tree = st

        self.dock_manager.on_active_plot_changed(window)



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
                    # Fallback: existing file-drop handling
                    paths = self._extract_file_paths(mime)
                    if any(self._is_supported_file(p) for p in paths):
                        self._create_signals(paths)
                        event.acceptProposedAction()
                        return True

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
        self.dask_manager.shutdown()
        self._shutdown_update_thread()
        super().closeEvent(event)

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

    def close(self) -> None:
        self._shutdown_update_thread()
        try:
            self.dask_manager.shutdown()
        except Exception:
            pass
        super().close()


def _asset(filename: str) -> str:
    """Return the absolute path to a bundled asset regardless of how the app was launched."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)


def main() -> MainWindow:
    with log_startup_time("QApplication startup"):
        app = QtWidgets.QApplication(sys.argv)
        app.setApplicationName("SpyDE")

    # Splash screen — use package-relative path so it works when bundled
    splash_path = _asset("SpydeDark.png")
    pixmap = QPixmap(splash_path).scaled(
        300,
        300,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )

    splash = QSplashScreen(pixmap, Qt.WindowType.FramelessWindowHint)
    splash.show()
    splash.raise_()
    app.processEvents()

    with log_startup_time("MainWindow construction"):
        main_window = MainWindow(app=app)

    main_window.setWindowTitle("SpyDE")

    # Platform-appropriate window / taskbar icon
    if sys.platform == "darwin":
        icon_path = _asset("icon.icns")
    elif sys.platform == "win32":
        icon_path = _asset("Spyde.ico")
    else:  # Linux / other
        icon_path = _asset("Spyde.png")

    main_window.setWindowIcon(QIcon(icon_path))
    main_window.show()
    splash.finish(main_window)

    app.exec()
    return main_window


if __name__ == "__main__":
    # multiprocessing.freeze_support()
    sys.exit(main())
