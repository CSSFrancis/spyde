from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtCore import Qt
from functools import partial

import pyqtgraph as pg
import numpy as np
import dask.array as da
from dask.distributed import Future

from despy.drawing.selector import BaseSelector
from despy.drawing.toolbars.plot_control_toolbar import (
    Plot1DControlToolbar,
    Plot2DControlToolbar,
)
from despy.misc.utils import fast_index_virtual


class Plot(QtWidgets.QMdiSubWindow):
    """
    A QMdi sub-window that displays either a 2D image or a 1D line plot from a HyperSignal.
    It can host interactive selectors and will coordinate dependent plots.
    """

    def __init__(
        self,
        signal,
        key_navigator=False,
        is_signal=False,
        selector_list=None,
        main_window=None,
        mdi_window=None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        # State
        self.selector_list = selector_list or []
        self.is_signal = is_signal
        self.qt_widget = None
        self.main_window = main_window
        self.mdi_area = mdi_window
        self.hyper_signal = signal
        self.selectors = []
        self.data = None
        self.current_indexes = []
        self.current_indexes_dense = []
        self.key_navigator = key_navigator

        # Container and plot widget
        self.container = QtWidgets.QWidget()
        container_layout = QtWidgets.QVBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        self.plot_widget = pg.PlotWidget()
        container_layout.addWidget(self.plot_widget)

        self.plot_item = self.plot_widget.getPlotItem()
        self.plot_item.getViewBox().setAspectLocked(True, ratio=1)
        self.setWidget(self.container)

        self.image_item = None
        self.line_item = None

        # Resolve what data to display
        if key_navigator:
            # Walk to the deepest navigation HyperSignal
            if self.hyper_signal.nav_sig is not None:
                key_hs = self.hyper_signal.nav_sig
                while key_hs.nav_sig is not None:
                    key_hs = key_hs.nav_sig
                self.hyper_signal = key_hs

            self.data = self.hyper_signal.signal.data
            name = "Key Navigator Plot"

        elif is_signal:
            # Display signal using current selectors
            self.setWindowTitle("Signal Plot")
            self.current_indexes = [s.get_selected_indices() for s in self.selector_list]
            self.current_indexes_dense = self.get_dense_indexes()

            if self.hyper_signal.signal._lazy:
                current_img = self.hyper_signal.signal._get_cache_dask_chunk(
                    self.current_indexes_dense, get_result=True
                )
            else:
                inds = tuple(self.current_indexes_dense[:, i] for i in range(self.current_indexes_dense.shape[1]))
                current_img = np.sum(self.hyper_signal.signal.data[inds], axis=0)

            self.data = current_img
            name = "Signal Plot"

        else:
            # Display navigation-derived "virtual image"
            key_hs = self.hyper_signal.nav_sig
            while key_hs and key_hs.nav_sig is not None:
                key_hs = key_hs.nav_sig

            self.current_indexes = [s.get_selected_indices() for s in self.selector_list]
            self.current_indexes_dense = self.get_dense_indexes()
            self.hyper_signal = key_hs or self.hyper_signal
            self.data = self.hyper_signal.signal.data
            self.setWindowTitle("Navigation Plot")
            name = "Virtual Image Plot"

        # Create items based on dimensionality
        if self.ndim == 2:
            # Ensure numpy data for image display (will compute if dask)
            img = np.asarray(self.data) if isinstance(self.data, da.Array) else self.data
            self.image_item = pg.ImageItem(img)
            self.plot_item.addItem(self.image_item)

        elif self.ndim == 1:
            # Normalize to fit in the visible area and show grid
            if key_navigator:
                axis = self.hyper_signal.signal.axes_manager.navigation_axes[0].axis
            else:
                axis = self.hyper_signal.signal.axes_manager.signal_axes[0].axis

            data = np.vstack(
                [
                    axis,
                    (self.data - np.min(self.data)) / (np.max(self.data) - np.min(self.data) + 1e-12) * np.max(axis),
                    np.zeros_like(self.data),
                ]
            ).T
            self.line_item = self.plot_item.plot(data[:, 0], data[:, 1], pen="y")
            self.plot_item.showGrid(x=True, y=True)
            self.plot_item.setTitle(name)

        else:
            raise ValueError("Invalid data shape for plotting. Must be 1D or 2D.")

        # Context-menu for selectors
        self.plot_widget.scene().sigMouseClicked.connect(self.get_context_menu)

        # Floating toolbar (position synchronized in moveEvent)
        self.toolbar = Plot2DControlToolbar(parent=self.main_window, vertical=True, plot=self) if self.ndim == 2 else \
                       Plot1DControlToolbar(parent=self.main_window, vertical=True, plot=self)

    def moveEvent(self, ev: QtGui.QMoveEvent) -> None:
        """Keep the floating toolbar positioned to the right of the subwindow."""
        super().moveEvent(ev)
        tb = getattr(self, "toolbar", None)
        if tb is None or tb.parentWidget() is None or getattr(self, "_move_sync", False):
            return

        self._move_sync = True
        try:
            parent = tb.parentWidget()
            plot_global_tl = self.mapToGlobal(QtCore.QPoint(0, 0))
            margin = getattr(tb, "_margin", 8)
            desired_global = QtCore.QPoint(
                plot_global_tl.x() + self.width() + margin,
                plot_global_tl.y() + margin,
            )
            desired_in_parent = parent.mapFromGlobal(desired_global)
            tb._move_sync = True
            try:
                tb.move(desired_in_parent)
                tb.raise_()
            finally:
                tb._move_sync = False
        finally:
            self._move_sync = False

    @property
    def ndim(self) -> int:
        """Dimensionality of the current data."""
        return int(self.data.ndim)

    @property
    def is_live(self) -> bool:
        """Selectors are 'live' only if all attached selectors are live."""
        if self.selector_list:
            return bool(np.all([s.is_live for s in self.selector_list]))
        return False

    @is_live.setter
    def is_live(self, value: bool):
        """Toggle 'live' mode across selectors when this is a signal plot."""
        if self.selector_list and self.is_signal:
            for s in self.selector_list:
                s.is_live = value
        else:
            print("Selector is not set or plot is not a signal plot.")

    @property
    def is_integrating(self) -> bool:
        """Selectors are 'integrating' only if all attached selectors are integrating."""
        if self.selector_list:
            return bool(np.all([s.is_integrating for s in self.selector_list]))
        return False

    def add_selector_and_new_plot(self, down_step=True, type="RectangleSelector", *args, **kwargs):
        """
        Add a selector to this plot and spawn the appropriate dependent plot.

        down_step=True:
            Create a downstream signal plot using the parent HyperSignal and the combined selectors.
        down_step=False:
            Create a new virtual image plot from this HyperSignal using the new selector.
        """
        # Only support RectangleSelector for 2D, LineSelector for 1D
        if self.ndim == 2:
            max_bounds = QtCore.QRectF(0, 0, self.image_item.width(), self.image_item.height())
            kwargs = {"resizable": True, "maxBounds": max_bounds}
            if type != "RectangleSelector":
                raise ValueError("Invalid selector type for 2D. Use 'RectangleSelector'.")
            kwargs["pos"] = (1, 1)
            kwargs["size"] = (3, 3)
        else:
            type = "LineSelector"

        selector = Selector(
            parent=self.plot_item,
            type=type,
            integration_order=len(self.selector_list),
            on_nav=not self.is_signal,
            **kwargs,
        )

        selector.is_live = True
        self.selectors.append(selector)

        if down_step:
            # Move down to the parent HyperSignal to compute a signal plot using all selectors
            hypersignal = self.hyper_signal.parent_signal
            sel_list = self.selector_list + [selector]
            new_plot = Plot(
                hypersignal,
                is_signal=True,
                selector_list=sel_list,
                main_window=self.main_window,
            )
            for s in new_plot.selector_list:
                s.plots.append(new_plot)
        else:
            # Create a virtual image plot on the current HyperSignal (for navigation)
            new_plot = Plot(
                self.hyper_signal,
                is_signal=False,
                selector_list=[selector],
                key_navigator=True,
                main_window=self.main_window,
            )
            selector.is_live = False
            selector.is_integrating = True

        selector.plots.append(new_plot)

        self.main_window.add_plot(new_plot)
        selector.selector.sigRegionChanged.connect(selector.update_data)
        return new_plot

    def get_context_menu(self, ev):
        """Right-click context menu for adding selectors."""
        if ev.button() != Qt.MouseButton.RightButton:
            return

        context_menu = QtWidgets.QMenu()
        selector_menu = context_menu.addMenu("Add Selector")
        down_step = self.hyper_signal.parent_signal is not None

        if self.ndim == 1:
            action = selector_menu.addAction("Add Line Selector")
            action.triggered.connect(
                partial(self.add_selector_and_new_plot, type="LineSelector", down_step=down_step)
            )
        else:
            action = selector_menu.addAction("Add Rectangle Selector and New Plot")
            action.triggered.connect(
                partial(self.add_selector_and_new_plot, type="RectangleSelector", down_step=down_step)
            )

        context_menu.exec_(QtGui.QCursor.pos())

    def show_selector_control_widget(self):
        """
        Show selector control widgets for this plot and hide others.
        Useful to avoid layout flicker when switching active plots.
        """
        # Hide selectors from other plots
        for plot in self.main_window.plot_subwindows:
            if plot is self:
                continue
            for selector in plot.selectors:
                selector.widget.hide()

        # Show selectors for this plot
        for selector in self.selectors:
            selector.widget.show()
            self.main_window.selectors_layout.addWidget(selector.widget)

    def compute_data(self, reverse=True):
        """
        Compute reduced data by gathering across selector-defined indices and
        applying a reduction.
        """
        self.current_indexes = [s.get_selected_indices() for s in self.selector_list]
        self.current_indexes_dense = self.get_dense_indexes()

        indexes = self.current_indexes_dense
        if indexes is None or indexes.size == 0:
            return

        # Start from the root HyperSignal
        parent_signal = self.hyper_signal
        while parent_signal.parent_signal is not None:
            parent_signal = parent_signal.parent_signal

        signal = parent_signal.signal
        result = fast_index_virtual(signal.data, indexes, reverse=reverse)

        if isinstance(result, da.Array):
            # Defer to Dask client; keep Future in self.data to avoid blocking UI
            self.data = self.hyper_signal.client.compute(result)
        else:
            self.data = result
            self.update()

    def get_dense_indexes(self):
        """
        Combine per-selector index arrays into a dense Cartesian product.
        Each selector may return a 1D array of indices; this stacks them.
        """
        indexes = None
        for item in self.current_indexes:
            arr = np.array(item)
            if arr.ndim == 1:
                arr = arr[:, None]

            if indexes is None:
                indexes = arr
            else:
                indexes = np.hstack(
                    [np.repeat(indexes, len(arr), axis=0), np.repeat(arr, len(indexes), axis=0)]
                )

        return indexes

    def update_plot(self, get_result=False):
        """
        Update the plot when selectors change. Uses a cache-aware path for lazy signals.
        """
        indexes = self.get_dense_indexes()
        if indexes is None:
            return

        if (
            self.current_indexes_dense is None
            or self.current_indexes_dense.shape != indexes.shape
            or not np.array_equal(self.current_indexes_dense, indexes)
        ):
            self.current_indexes_dense = indexes

            if self.hyper_signal.signal._lazy:
                current_img = self.hyper_signal.signal._get_cache_dask_chunk(indexes, get_result=get_result)
            else:
                inds = tuple(indexes[:, i] for i in range(indexes.shape[1]))
                current_img = np.sum(self.hyper_signal.signal.data[inds], axis=0)

            self.data = current_img
            if not isinstance(current_img, Future):
                self.update()

    def update(self):
        """Push the current data to the plot items."""
        if self.ndim == 1 and self.line_item is not None:
            axis = self.hyper_signal.signal.axes_manager.signal_axes[0].axis
            self.line_item.setData(axis, self.data)
        elif self.image_item is not None:
            img = np.asarray(self.data) if isinstance(self.data, da.Array) else self.data
            self.image_item.setImage(img, autoLevels=True)

    def closeEvent(self, event):
        """Cleanup toolbar, hide selector widgets, and close attached plots when needed."""
        # Close and delete the floating toolbar if present
        tb = getattr(self, "toolbar", None)
        if tb is not None:
            try:
                tb.plot = None  # break linkage to avoid moveEvent side-effects
            except Exception:
                pass
            tb.close()
            self.toolbar = None

        # Remove from main window tracking
        if hasattr(self.main_window, "plot_subwindows"):
            try:
                self.main_window.plot_subwindows.remove(self)
            except ValueError:
                pass

        # Hide the selectors for this plot
        for selector in self.selectors:
            selector.widget.hide()

        # If this is a key navigator, close associated plots
        if self.key_navigator:
            try:
                for signal_plot in getattr(self.hyper_signal, "signal_plots", []):
                    signal_plot.close()
                for nav_plot in getattr(self.hyper_signal, "navigation_plots", []):
                    nav_plot.close()
            except Exception:
                pass

        super().closeEvent(event)

