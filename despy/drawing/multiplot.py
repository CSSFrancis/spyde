from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtCore import Qt
from functools import partial

import pyqtgraph as pg
import numpy as np
import dask.array as da
from dask.distributed import Future

from despy.drawing.selector import Selector
from despy.drawing.toolbars.plot_control_toolbar import (
    Plot1DControlToolbar,
    Plot2DControlToolbar,
)
from despy.misc.utils import fast_index_virtual

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from despy.signal_tree import BaseSignalTree
    from despy.main_window import MainWindow


class Plot(QtWidgets.QMdiSubWindow):
    """
    A QMdi sub-window that displays either a 2D image or a 1D line plot from a BaseSignalTree.
    It can host interactive selectors. These selectors are split into three categories:

    1) NavigationSelector: This is the selector from the parent navigation plot.  This selector
         defines the slice of data being viewed in this plot. These selectors are managed
         by the NavigationPlotManager.
    2) PlotSelectors: These are selectors that are attached to this plot.  These selectors define
         regions of interest within the data being displayed.  For example, in a 2D image plot,
         a rectangle selector might define a region to compute a live FFT or a linear selector
         might define a line profile.
    3) SignalTreeSelectors: These selectors spawn a new SignalTree and are mostly used for
        virtual imaging. The SignalTree can be loosely linked to a `Plot`.  It will update when the
        `compute_data` method for the SignalTreeSelector is called.



    Parameters
    ----------
    signal_tree : BaseSignalTree
        The BaseSignalTree to visualize. This is either a signal plot or a navigation plot.
    is_navigator : bool
        True if this plot is for navigation (virtual image), False if for signal
    parent_selector: Selector | None
        The parent `Selector`. The parent_selector is on a navigation plot then it will be used to
        slice the signal_tree to update a signal_plot If selector is None, then no parent selector
        is attached to the plot (i.e. for a navigator plot which won't have any parent selector).
    multi_plot : MultiPlot | None
        The MultiPlot manager if this plot is part of a MultiPlot.
    """

    def __init__(
            self,
            signal_tree: BaseSignalTree,
            is_navigator=False,  # True if this plot is for navigation (virtual image), False if for signal
            parent_selector: Selector = None,
            nav_plot_manager: "NavigationPlotManager" = None,
            *args,
            **kwargs,
    ):
        super().__init__(*args, **kwargs)

        # State
        # the list of selectors attached to this plot/data.  These selectors can be for:
        # - line profiles: Choosing regions along which to extract a line profile
        # - live fft: Choosing regions to compute live FFTs
        self.self_selectors = []

        # Child plots are dependent plots like live FFT plots, line profile plots, etc.
        # on the close event of this plot, these child plots should also be closed.
        # The histogram plot is "Special" and is not included here.
        self.child_plots = []
        self.signal_tree = signal_tree
        self.is_navigator = is_navigator
        self.parent_selector = parent_selector
        self.nav_plot_manager = nav_plot_manager

        # the current data being displayed in the plot
        self.current_data = None

        # Container and plot widget
        self.container = QtWidgets.QWidget()
        container_layout = QtWidgets.QVBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        # set up the plot widget with pyqtgraph
        self.plot_widget = pg.PlotWidget()
        container_layout.addWidget(self.plot_widget)
        self.plot_item = self.plot_widget.getPlotItem()
        self.plot_item.getViewBox().setAspectLocked(True, ratio=1)  # locked aspect ratio

        # Floating toolbar (position synchronized in moveEvent)
        self.toolbar = None  # toolbar will be set in the derived classes Plot1D and Plot2D
        self._move_sync = True

    @property
    def main_window(self) -> "MainWindow":
        """Get the main window containing this sub-window."""
        return self.signal_tree.main_window

    def moveEvent(self, ev: QtGui.QMoveEvent) -> None:
        """Keep the floating toolbar positioned to the right of the subwindow."""
        super().moveEvent(ev)
        tb = getattr(self, "toolbar", None)
        if tb is None or tb.parentWidget() is None or getattr(self, "_move_sync", False):
            return
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


class Plot2D(Plot):
    """
    A QMdi sub-window that displays a 2D image from a BaseSignalTree.
    It can have interactive selectors.

    Parameters
    ----------
    signal_tree : BaseSignalTree
        The BaseSignalTree to visualize. This is either a signal plot or a navigation plot.

    """

    def __init__(
            self,
            signal_tree: BaseSignalTree,
            is_navigator=False,  # True if this plot is for navigation (virtual image), False if for signal
            *args,
            **kwargs,
    ):
        super().__init__(
            signal_tree,
            is_navigator=is_navigator,
            *args,
            **kwargs,
        )

        self.toolbar = Plot2DControlToolbar(self,
                                            vertical=True,
                                            plot=self)


class Plot1D(Plot):
    """
    A QMdi sub-window that displays a 1D line plot from a BaseSignalTree.
    It can have interactive selectors.

    Parameters
    ----------
    signal_tree : BaseSignalTree
        The BaseSignalTree to visualize. This is either a signal plot or a navigation plot.

    """

    def __init__(
            self,
            signal_tree: BaseSignalTree,
            is_navigator=False,  # True if this plot is for navigation (virtual image), False if for signal
            *args,
            **kwargs,
    ):
        super().__init__(
            signal_tree,
            is_navigator=is_navigator,
            *args,
            **kwargs,
        )

        self.toolbar = Plot1DControlToolbar(self,
                                            vertical=True,
                                            plot=self)


class NavigationPlotManager:
    """
    A class to manage multiple `Plot` instances for navigation plots.


    Parameters
    ----------
    main_window : MainWindow
        The main window of the application.
    """

    def __init__(self,
                 main_window: "MainWindow",
                 signal_tree: "BaseSignalTree"
                 ):
        self.main_window = main_window
        self.plots = []  # type: list[Plot]
        self.navigation_selectors = []  # type: list[Selector]
        self.signal_tree = signal_tree

    def nav_dim(self) -> int:
        """
        Get the number of navigation dimensions in the signal tree.
        """
        return self.signal_tree.nav_dim

    def add_navigation_selector_and_signal_plot(self, type=None):
        """
        Add a Selector (or Multi-selector) to the navigation plots. For 2+ dimensional
        navigation signals, multiple-linked selectors will be created.
        """
        if self.nav_dim() == 1:
            self.plots.append(Plot1D(signal_tree=self.signal_tree,
                                     is_navigator=True,
                                     ))

