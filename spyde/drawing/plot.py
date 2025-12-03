from PySide6 import QtCore, QtWidgets, QtGui

import pyqtgraph as pg
from pyqtgraph import GraphicsItem, PlotItem

from spyde.external.pyqtgraph.scale_bar import OutlinedScaleBar as ScaleBar
from math import floor, log10

import numpy as np
import dask.array as da
from dask.distributed import Future

from typing import TYPE_CHECKING, Union, List, Dict, Tuple

if TYPE_CHECKING:
    from spyde.signal_tree import BaseSignalTree
    from spyde.__main__ import MainWindow
    from spyde.drawing.selector import BaseSelector
    from spyde.drawing.plot_managers import MultiplotManager
from hyperspy.signal import BaseSignal

from spyde.drawing.plot_states import PlotState, NavigationManagerState
from spyde.drawing.update_functions import update_from_navigation_selection
from spyde.qt.subwindow import FramelessSubWindow

import logging

logger = logging.getLogger(__name__)

COLORMAPS = {
    "gray": pg.colormap.get("CET-L1"),
    "viridis": pg.colormap.get("viridis"),
    "plasma": pg.colormap.get("plasma"),
    "cividis": pg.colormap.get("cividis"),
    "fire": pg.colormap.get("CET-L3"),
}

class PlotWindow(FramelessSubWindow):
    """
     A QMdi sub-window that contains either a single Plot or potentially multiple plots in some layout.

     The ``PlotWindow`` has a graphics layout widget which has an ``items`` dictionary which maps a GraphicsItem
     to a (row, col) position in the layout.  In the instance of a single Plot, the items dictionary will
     have a single entry mapping the Plot's plot_item to (0, 0).

     In addition to the items dictionary, the ``PlotWindow`` also has a plot_state dictionary which maps
     each GraphicsItem to its corresponding ``PlotState``.

    When multiple plots are present, the items dictionary will have multiple entries mapping each Plot's
    plot_item to its (row, col) position in the layout.

    In the case that the PlotWindow is a member of a NavigationPlotManager,  a navigation selector will be
    added to each plot in the window.  Each `Plot` (or GraphicsItem) can be updated independently based on an
    associated update function. This allows for more complex plots (real/img FFT side-by-side,  update all
    virtual images at once)

    Each PlotWindow will also have toolbars, but these are all associated with individual Plots within the window
    (more specifically, with the PlotStates of each Plot).  Clicking on some plot will activate its toolbars and hide
    the toolbars of other plots within the same window. This can be slightly confusing, but it allows for the
    flexibility of multiple plots within the same window without needing to manage multiple sets of toolbars. The active
    `Plot` within the `PlotWindow` is shown by a small highlight around the plot area.
    """
    def __init__(self,
        is_navigator: bool = False, # if navigator then it will share the navigation selectors
        plot_manager: Union["MultiplotManager", None] = None,
        signal_tree: Union["BaseSignalTree", None] = None,
        main_window: Union["MainWindow", None] = None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.signal_tree = signal_tree
        self.is_navigator = is_navigator  # type: bool
        # the plot manager for managing multiple plot windows.  Different from Multiplexed Plots as
        # this is for managing multiple Plot windows.
        self.plot_manager = plot_manager # type: MultiplotManager | None

        self.current_plot_item = None # type: Plot | None

        # Always use a graphics layout for handling multiple plots
        self.container = QtWidgets.QWidget()  # type: QtWidgets.QWidget
        container_layout = QtWidgets.QVBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        self.plot_widget = pg.GraphicsLayoutWidget(self.container)

        # Previous layout state
        self.previous_subplots_pos = dict()  # type: Dict[pg.PlotItem:tuple[int, int]] | Dict
        self.previous_graphics_layout_widget = None  # type: pg.GraphicsLayoutWidget | None

        # explicitly set the main window on construction
        self.main_window = main_window # type: "MainWindow"

    @property
    def plots(self) -> List["Plot"]:
        """Get the list of Plot objects in this PlotWindow."""
        plots = []
        for item in self.plot_widget.ci.items.keys():
            if isinstance(item, Plot):
                plots.append(item)
        return plots

    def add_new_plot(self, row: int=0, col: int=0) -> "Plot":
        """ Creates and returns a new (empty) Plot."""
        plot =  Plot(signal_tree=self.signal_tree,
                     is_navigator=self.is_navigator,
                     plot_window=self,
        )
        self.add_item(plot, row, col)
        return plot

    def add_item(self, item: GraphicsItem, row: int=0, col: int=0):
        """Add a GraphicsItem to the graphics layout at the specified row and column."""
        self.plot_widget.addItem(item, row, col)

        print(self.plot_widget.ci.items, " after adding item at (", row, ",", col, ")")

        if isinstance(item, Plot):
            item.plot_window = self
            self.current_plot_item = item

    def set_graphics_layout_widget(self,
                                   layout_dictionary:Dict[GraphicsItem, List[Tuple[int, int]]],
                                   ):
        """
        Set the graphics layout widget based on a layout dictionary. This will compare the current
        layout with the layout dictionary and rearrange the subplots accordingly.

        This is mostly used for restoring saved layouts when multiplexing `Plot` objects. This could also
        be extended to support any GraphicsItem, but currently it is only tested against `Plot` objects.

        Parameters
        ----------
        layout_dictionary : Dict[GraphicsItem, List[Tuple[int, int]]]
            A dictionary mapping plot items to their (row, col) positions in the layout.
        """
        # first remove any subplots that are not in the layout dictionary or are in the wrong position

        print("The items", self.plot_widget.ci.items, " layout dict:", layout_dictionary)

        # only clear if there are changes
        needs_update = False
        for plot_item, pos in self.plot_widget.ci.items.items():
            if isinstance(pos, list):
                pos = pos[0]
            if plot_item not in layout_dictionary or layout_dictionary[plot_item] != pos:
                needs_update = True

        for plot_item in layout_dictionary:
            if plot_item not in self.plot_widget.ci.items:
                needs_update = True

        if needs_update:
            print("Old layout:", self.plot_widget.ci.items, "New layout:", layout_dictionary)
            try:
                self.plot_widget.clear() # clear all items first
            except ValueError as e:
                print("Error clearing plot widget:", e)
                print("Continuing...")
            for plot_item, pos in layout_dictionary.items():
                if isinstance(pos, list):
                    pos = pos[0]
                self.add_item(plot_item, pos[0], pos[1])



class Plot(PlotItem):
    """
    A Plot within a QMdi sub-window. This can be either a 2D image or a 1D line plot.

    Each plot has a PlotState which manages the current signal, selectors, and child plots. Each plot also has
    a list of PlotStates for each signal that can be displayed in the plot.

    Parameters
    ----------
    signal_tree : BaseSignalTree
        The BaseSignalTree to visualize. This is either a signal plot or a navigation plot.
    is_navigator : bool
        True if this plot is for navigation (virtual image), False if for signal
    multi_plot : MultiPlot | None
        The MultiPlot manager if this plot is part of a MultiPlot.
    """

    def __init__(
        self,
        signal_tree: "BaseSignalTree",
        is_navigator : bool = False,
        nav_plot_manager: Union["NavigationPlotManager", None] = None,
        plot_window: Union["PlotWindow", None] = None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.is_navigator = is_navigator
        # update flags
        self.needs_update_range = None  # type: bool | None # whether the range needs to be updated
        self.needs_auto_level = True # type: bool # whether the plot needs to be auto-leveled

        # Scale bar for image plots
        self._scale_bar = None # type: ScaleBar | None # the scale bar item
        self._scale_bar_vb = None # type: pg.ViewBox | None # the viewbox the scale bar is attached to

        # For mouse move events and cursor readout
        self._mouse_proxy = None
        QtCore.QTimer.singleShot(0, self._attach_mouse_move)

        # State
        # -----
        # managing the current state of the plot. Including child plots and (non-navigation) selectors
        # navigation selectors are managed by the NavigationPlotManager. This starts uninitialized.
        # if the plot is multiplexed, this will be a list of PlotStates where each PlotState corresponds
        # to the same index in the pyqtgraph GraphicsLayoutWidget.items dict.

        self.plot_state = None  # type: PlotState | None | List[PlotState]
        self.plot_states = dict()  # type: Dict[BaseSignal:PlotState]

        self.signal_tree = signal_tree  # type: BaseSignalTree

        # the current data being displayed in the plot
        self.current_data = None  # type: Union[np.ndarray, da.Array, Future, None]

        self.nav_plot_manager = nav_plot_manager  # type: NavigationPlotManager | None


        # Either an image item (2D) or line item (1D)
        self.image_item = pg.ImageItem()  # type: pg.ImageItem
        self.line_item = pg.PlotDataItem()  # type: pg.PlotDataItem

        self.getViewBox().setAspectLocked(
            True, ratio=1
        )  # locked aspect ratio

        self._move_sync = True

        # Parent selector if this plot is a child plot
        self.parent_selector = None  # type: BaseSelector | None

        self.plot_window = plot_window  # type: PlotWindow | None
        # Register with the main window for needs update

    def set_colormap(self, colormap: str):
        """Set the colormap for the image item."""
        cmap = COLORMAPS.get(colormap, COLORMAPS["gray"])
        self.image_item.setColorMap(cmap)
        self.plot_state.colormap = colormap

    def enable_scale_bar(self, enabled: bool = True):
        """Enable or disable an auto-updating horizontal scale bar."""
        vb = (
            getattr(self, "vb", None)
            or getattr(self, "getViewBox", lambda: None)()
        )  # type: pg.ViewBox | None
        if self.plot_state.dimensions != 2:
            self._scale_bar = None
        if enabled:
            # axes are stored in the plot state.

            # length in data units
            if self.is_navigator:


                axes = self.signal_tree.root.axes_manager.navigation_axes
            else:
                axes = self.plot_state.current_signal.axes_manager.signal_axes

            x_range = axes[0].scale * axes[0].size

            target = x_range / 5
            if not np.isfinite(target) or target <= 0:
                target = 1.0

            exp = floor(log10(target))
            base = 10**exp
            norm = target / base

            if norm < 1.5:
                nice = 1.0
            elif norm < 2.5:
                nice = 2.0
            elif norm < 3.5:
                nice = 2.5
            elif norm < 7.5:
                nice = 5.0
            else:
                nice = 10.0

            nice_length = nice * base
            units = self.plot_state.current_signal.axes_manager.signal_axes[0].units

            if self._scale_bar is None:
                self._scale_bar = ScaleBar(
                    nice_length,
                    suffix=units,
                    pen=pg.mkPen(0, 0, 0, 200),
                    brush=pg.mkBrush(255, 255, 255, 180),
                )
                self._scale_bar.setZValue(1000)
                self._scale_bar.setParentItem(vb)
                self._scale_bar.anchor((1, 1), (1, 1), offset=(-12, -12))
            else:
                self._scale_bar.size = nice_length
                new_text = f"{nice_length} {units}"
                self._scale_bar.text.setHtml(new_text)
                self._scale_bar.update()

    def set_plot_state(self, signal: BaseSignal):
        """Set the plot state to the state for some signal."""
        # first save the current plot state selectors and child plots
        old_plot_state = self.plot_state
        self.needs_auto_level = True
        if old_plot_state is not None:
            # save the old plot state
            self.plot_states[self.plot_state.current_signal] = old_plot_state
            # hide old toolbars
            old_plot_state.hide_toolbars()

            if old_plot_state is not None:
                # remove all the current selectors and hide child plots
                for selector in (
                    old_plot_state.plot_selectors + old_plot_state.signal_tree_selectors
                ):
                    selector.widget.hide()
                for child_plot in (
                    old_plot_state.plot_selectors_children
                    + old_plot_state.signal_tree_selectors_children
                ):
                    child_plot.hide()

        # set the new plot state
        self.plot_state = self.plot_states.get(signal)

        # switch plot items if needed for dimensionality change
        old_dim = 0 if old_plot_state is None else old_plot_state.dimensions
        vb = self.getViewBox()

        if self.plot_state.dimensions == 2 and old_dim != 2:
            self.clear()
            self.addItem(self.image_item)
            vb.setAspectLocked(True, ratio=1)
            vb.enableAutoRange(x=True, y=True)
            vb.autoRange()

        elif self.plot_state.dimensions == 1 and old_dim != 1:
            self.clear()
            self.addItem(self.line_item)
            vb.setAspectLocked(False)
            vb.enableAutoRange(x=True, y=True)
            vb.autoRange()

        # show the new selectors and child plots
        for selector in (
            self.plot_state.plot_selectors + self.plot_state.signal_tree_selectors
        ):
            selector.widget.show()
        for child_plot in (
            self.plot_state.plot_selectors_children
            + self.plot_state.signal_tree_selectors_children
        ):
            child_plot.show()

        # fire the selector update to get the correct data displayed...
        if self.plot_state.dynamic:
            self.update_data(self.current_data, force=True)
        else:
            self.update_data(self.plot_state.current_signal.data)
        self.getViewBox().autoRange()

        # update the toolbars
        self.update_image_rectangle()

        if self.plot_state.dimensions == 2:
            self.enable_scale_bar(True)
        else:
            self.enable_scale_bar(False)
        self.main_window.on_subwindow_activated(self)
        # update the plot
        if self.parent_selector is not None:
            self.parent_selector.delayed_update_data(force=True)
            self.needs_update_range = True
            # update the plot range
            self.update_range()

        # show the toolbars should be last so that the widgets can be initialized properly
        print(self.image_item)
        print("Showing toolbars for plot state:", self.plot_state)
        self.plot_state.show_toolbars()

    def add_plot_state(self,
                           signal: BaseSignal,
                           dimensions: int= None,
                           dynamic: bool = False,
                           ) -> PlotState:
        """Create and add a new PlotState for some signal."""
        ps = PlotState(
            signal=signal,
            dimensions=dimensions,
            dynamic= dynamic,
            plot=self,
        )
        self.plot_states[signal] = ps
        return ps


    def update_image_rectangle(self):
        """Set the x and y range of the plot.

        #TODO: Have for other dimensions?
        """
        if self.is_navigator:
            axes = self.signal_tree.root.axes_manager.navigation_axes
        else:
            axes = self.plot_state.current_signal.axes_manager.signal_axes

        if self.plot_state.dimensions == 2:
            sx = axes[0].scale or 1.0
            sy = axes[1].scale or 1.0
            x = axes[0].offset
            y = axes[1].offset

            transform = QtGui.QTransform.fromTranslate(x, y).scale(sx, sy)
            self.image_item.resetTransform()
            self.image_item.setTransform(transform)

            # Update positions/sizes of any selectors to match the new transform.
            selectors = []  # type: List[BaseSelector]

            if self.plot_state is not None:
                selectors += getattr(self.plot_state, "plot_selectors", [])
                selectors += getattr(self.plot_state, "signal_tree_selectors", [])
            if getattr(self, "nav_plot_manager", None) is not None:
                selectors += list(
                    getattr(self.nav_plot_manager, "navigation_selectors", [])
                )

            print("Updating selectors for new image transform:", selectors)
            for sel in selectors:
                sel.apply_transform_to_selector(transform)
            self.enable_scale_bar(True)
            self.getViewBox().autoRange()
        else:
            self.enable_scale_bar(False)

    @property
    def main_window(self) -> "MainWindow":
        """Get the main window containing this sub-window."""
        return self.signal_tree.main_window

    def reposition_toolbars(self):
        """Reposition the floating toolbars around the subwindow."""
        for tb in (
            getattr(self.plot_state, "toolbar_right", None),
            getattr(self.plot_state, "toolbar_left", None),
            getattr(self.plot_state, "toolbar_top", None),
            getattr(self.plot_state, "toolbar_bottom", None),
        ):
            if tb is not None and tb.isVisible():
                tb.move_next_to_plot()

    def showEvent(self, ev: QtGui.QShowEvent) -> None:
        super().showEvent(ev)
        self.reposition_toolbars()

    def moveEvent(self, ev: QtGui.QMoveEvent) -> None:
        super().moveEvent(ev)
        self.reposition_toolbars()

    def resizeEvent(self, ev: QtGui.QResizeEvent) -> None:
        super().resizeEvent(ev)
        self.reposition_toolbars()

    def update_range(self):
        """Update the view range to fit the current data."""
        self.getViewBox().autoRange()

    def update_data(
        self, new_data: Union[np.ndarray, da.Array, Future], force: bool = False
    ):
        """Update the current data being displayed in the plot.

        If the new_data is a Future, the update will be deferred until the Future is complete, the update
        will be handled by the event loop instead.
        """
        print("Updating plot data", new_data)
        self.current_data = new_data
        if isinstance(new_data, Future) and not force:
            pass
        elif isinstance(new_data, Future) and force:
            self.current_data = new_data.result()
            self.update()
        else:
            self.update()
        print("Plot data updated.")

    def add_fft_selector(self):
        """Add an FFT selector to the plot."""
        from spyde.drawing.selector import RectangleSelector
        from spyde.drawing.update_functions import get_fft

        fft_plot = Plot(
            signal_tree=self.signal_tree,
            is_navigator=False,
        )

        fft_plot.add_plot_state(
            signal=self.plot_state.current_signal,
            dimensions=2,
            dynamic=True,)
        fft_plot.set_plot_state(self.plot_state.current_signal)
        fft_selector = RectangleSelector(
            parent=self,
            children=fft_plot,
            update_function=get_fft,
            live_delay=20,  # faster updates
        )
        fft_selector.delayed_update_data(force=True)
        fft_selector._on_region_change_finished()  # update the size
        self.plot_state.plot_selectors.append(fft_selector)

    def show_selector_control_widget(self):
        """
        Show selector control widgets for this plot and hide others.

        Rather than del
        """
        if self.plot_state is None:
            return
        visible_selectors = (
            self.plot_state.plot_selectors + self.plot_state.signal_tree_selectors
        )
        if self.nav_plot_manager is not None:
            visible_selectors += self.nav_plot_manager.navigation_selectors
        # Hide selectors from other plots. Faster than deleting and recreating them (also renders nicer).
        for selector in self.main_window.navigation_selectors:
            if selector not in visible_selectors:
                selector.widget.hide()
            else:
                if selector.widget.parent() is None:
                    self.main_window.selectors_layout.addWidget(selector.widget)
                selector.widget.show()

    def remove_selector_control_widgets(self):
        visible_selectors = (
            self.plot_state.plot_selectors + self.plot_state.signal_tree_selectors
        )
        if self.nav_plot_manager is not None:
            visible_selectors += self.nav_plot_manager.navigation_selectors
        for selector in visible_selectors:
            selector.widget.hide()
            self.main_window.selectors_layout.removeWidget(selector.widget)

    def _attach_mouse_move(self):
        """Attach a mouse-move proxy once plot_item exists."""
        try:
            pi = self
            if pi is None or not hasattr(pi, "scene"):
                return
            scene = pi.scene()
            if scene is None:
                return
            # Use pyqtgraph's SignalProxy to rate-limit updates
            self._mouse_proxy = pg.SignalProxy(
                scene.sigMouseMoved, rateLimit=60, slot=self._on_mouse_moved
            )
        except Exception:
            pass

    def _on_mouse_moved(self, evt):
        """Update main-window status with x, y, value under cursor for 1D/2D plots."""
        if not evt:
            self._update_main_cursor(None, None, None, None, None)
            return
        pos = evt[0]
        vb = self.getViewBox()
        if vb is None or not vb.sceneBoundingRect().contains(pos):
            self._update_main_cursor(None, None, None, None, None)
            return

        pt = vb.mapSceneToView(pos)
        x = float(pt.x())
        y = float(pt.y())

        if getattr(self.plot_state, "dimensions", 0) == 2:
            inverted_transform, is_inversion = self.image_item.transform().inverted()
        elif getattr(self.plot_state, "dimensions", 0) == 1:
            inverted_transform, is_inversion = self.line_item.transform().inverted()
        else:
            inverted_transform = None
            is_inversion = False
        pixel_x = None
        pixel_y = None
        if is_inversion:
            img_pt = inverted_transform.map(QtCore.QPointF(x, y))
            pixel_x = int(np.round(img_pt.x()))
            pixel_y = int(np.round(img_pt.y()))
        value = None

        if pixel_x is not None and pixel_y is not None:
            if getattr(self.plot_state, "dimensions", 0) == 2 and not isinstance(
                self.current_data, Future
            ):
                if (
                    0 <= floor(pixel_y) < self.current_data.shape[0]
                    and 0 <= floor(pixel_x) < self.current_data.shape[1]
                ):
                    value = self.current_data[floor(pixel_y), floor(pixel_x)]
            elif getattr(self.plot_state, "dimensions", 0) == 1 and not isinstance(
                self.current_data, Future
            ):
                if 0 <= floor(pixel_x) < self.current_data.shape[0]:
                    value = self.current_data[floor(pixel_x)]
        self._update_main_cursor(x, y, pixel_x, pixel_y, value)

    def _update_main_cursor(self, x, y, pixel_x, pixel_y, value):
        """Push the cursor readout to the main window status bar."""
        mw = getattr(self, "main_window", None)
        if mw is not None and hasattr(mw, "set_cursor_readout"):
            try:
                mw.set_cursor_readout(x, y, pixel_x, pixel_y, value)
            except Exception:
                pass

    def get_annular_roi_parameters(self):
        """
        Get the parameters for an annular ROI. This should be centered on the middle
        of the plot and have an inner radius of 25% of the width and an outer
        radius of 90% of the width.
        """
        # Create a modest default rectangle; users can reposition/resize.
        current_signal = self.plot_state.current_signal
        extent = current_signal.axes_manager.signal_extent
        center = (extent[1] + extent[0]) / 2, (extent[3] + extent[2]) / 2
        left, right, bottom, top = extent
        print("Computed signal center:", center)
        width = np.abs(extent[1] - extent[0])
        print("Computed signal width:", width)

        inner_rad = width * 0.125
        outer_rad = width * 0.45
        return center, inner_rad, outer_rad


    def update(self):
        """Push the current data to the plot items."""
        logger.info(
            "Plot update called with data:",
            self.current_data,
            " with type:",
            type(self.current_data),
        )
        if self.plot_state.dimensions == 1:
            current_data = (
                np.asarray(self.current_data)
                if isinstance(self.current_data, da.Array)
                else self.current_data
            )
            axis = self.plot_state.current_signal.axes_manager.signal_axes[0].axis
            logger.info("Updating 1D plot with axis:", axis)
            logger.info("Data shape:", current_data)
            self.line_item.setData(axis, current_data)
        elif self.plot_state.dimensions == 2:
            img = (
                np.asarray(self.current_data)
                if isinstance(self.current_data, da.Array)
                else self.current_data
            )

            self.image_item.setImage(
                img, levels=(self.plot_state.min_level, self.plot_state.max_level)
            )

            if self.needs_auto_level and img is not None:
                mn, mx = self.image_item.quickMinMax()
                self.image_item.setLevels((mn, mx))
                self.plot_state.max_level = mx
                self.plot_state.min_level = mn
                self.plot_state.max_percentile = 100.0
                self.plot_state.min_percentile = 0.0
                self.needs_auto_level = False
            if self.needs_update_range:
                self.update_range()
                self.needs_update_range = False

    def close_plot(self):
        logger.info("Plot: Closing plot:", self)
        self._update_main_cursor(None, None, None, None, None)
        self._mouse_proxy = None

        # delete all the plot states associated with the plot
        for plot_state in self.plot_states:
            self.plot_states[plot_state].close()


        logger.info("Deleting current plot selectors and child plots")
        # need to delete the current selectors and child plots
        for child_plot in (
                self.plot_state.plot_selectors_children
                + self.plot_state.signal_tree_selectors_children
        ):
            try:
                child_plot.close()
            except Exception:
                pass

    def closeEvent(self, event):
        """Cleanup toolbar, hide selector widgets, and close attached plots when needed."""
        self._update_main_cursor(None, None, None, None, None)
        self._mouse_proxy = None

        # delete all the plot states associated with the plot
        for plot_state in self.plot_states:
            self.plot_states[plot_state].close()



        logger.info("Closing parent selector if exists")
        if self.parent_selector is not None:
            logger.info("Closing parent selector")
            self.parent_selector.parent.nav_plot_manager.navigation_selectors.remove(
                self.parent_selector
            )
            self.parent_selector.widget.hide()
            self.parent_selector.close()

        # if part of a nav plot manager close everything and clean up the signal
        if self.nav_plot_manager is not None:
            logger.info("Closing nav plot manager plots")
            for plot in self.nav_plot_manager.plots:
                try:
                    plot.close()
                except Exception:
                    pass
            for plot in self.signal_tree.signal_plots:
                try:
                    plot.close()
                except Exception:
                    pass
            self.main_window.signal_trees.remove(self.signal_tree)
            self.signal_tree.close()
            logger.info("Removed signal tree from main window.")

        # Remove from main window tracking
        if hasattr(self.main_window, "plot_subwindows"):
            try:
                self.main_window.plot_subwindows.remove(self)
                logger.info("MultiPlot: Removed plot from main window tracking.")
                self.main_window.mdi_area
            except ValueError:
                pass
        logger.info("MultiPlot: Removing selector control widgets for this plot")

        # Remove the selectors for this plot
        self.remove_selector_control_widgets()
        logger.info("Plot: Calling CloseEvent of super class")
        super().closeEvent(event)
        logger.info("Plot: Plot closed.")

    def _apply_pending_navigator_assignment(self) -> bool:
        """Replace this plot with the queued navigator signal, if any."""
        mw = getattr(self, "main_window", None)
        payload = getattr(mw, "pending_navigator_assignment", None)
        if not payload or payload.get("target_plot") is not self:
            return False
        nav_manager = payload.get("nav_manager")
        signal = payload.get("signal")

        # clear any existing pending assignment
        mw.clear_pending_navigator_assignment()
        self.set_plot_state(signal)
        mw.statusBar().showMessage("Plot replaced", 2500)
        return True


class NavigationPlotManager:
    """
    A class to manage multiple `Plot` instances for navigation plots.

    There is only one `NavigationPlotManager` per `BaseSignalTree`. If we want to suplex
    multiple navigation plots. For example Time and Temperature in an in situ experiment,
    the selectors remain linked.

    Parameters
    ----------
    main_window : MainWindow
        The main window of the application.
    """

    def __init__(self, main_window: "MainWindow", signal_tree: "BaseSignalTree"):
        self.main_window = main_window  # type: MainWindow
        self.plots = []  # type: List[Plot]

        self.navigation_selectors = []  # type: List[BaseSelector]
        self.signal_tree = signal_tree  # type: BaseSignalTree
        self.navigation_manager_states = (
            dict()
        )  # type: dict[BaseSignal:NavigationManagerState]
        self.navigation_manager_state = None  # type: NavigationManagerState | None

        print(f"NavigationPlotManager: dim:{self.nav_dim}")
        if self.nav_dim < 1:
            raise ValueError(
                "NavigationPlotManager requires at least 1 navigation dimension."
            )
        elif self.nav_dim < 3:
            nav_plot_window = PlotWindow(
                is_navigator=True,
                plot_manager=self,
                signal_tree=self.signal_tree,
                main_window=main_window
            )
            nav_plot = nav_plot_window.add_new_plot()
            self.main_window.add_plot(nav_plot_window)

            self.plots.append(nav_plot)
            # create plot states for the nav plot
        for signal in self.signal_tree.navigator_signals.values():
            self.add_state(signal)

        print("Setting initial navigation manager state")
        print(list(self.signal_tree.navigator_signals.values())[0])
        self.set_navigation_manager_state(
            list(self.signal_tree.navigator_signals.values())[0]
        )

        # Add the navigation selector and signal plot
        self.add_navigation_selector_and_signal_plot()

    def add_state(self, signal: BaseSignal):
        """Add a navigation manager state for some signal.
        Parameters
        ----------
        signal : BaseSignal
            The signal for which to add the navigation state.
        """
        self.navigation_manager_states[BaseSignal] = NavigationManagerState(
            signal=signal, plot_manager=self
        )

        dim = self.navigation_manager_states[BaseSignal].dimensions
        print("Adding navigation state for signal:", signal, " with dimensions:", dim)
        dim = [d for d in dim if d > 0]
        for plot, d in zip(self.plots, dim):
            plot.add_plot_state(signal,
                                dimensions=d,
                                dynamic=False, # False for anything under 2?
                                )
    @property
    def navigation_signals(self) -> dict[str:BaseSignal]:
        """Return a list of navigation signals managed by this NavigationPlotManager."""
        return self.signal_tree.navigator_signals

    def set_navigation_manager_state(self, signal: Union[BaseSignal, str]):
        """Set the navigation state to the state for some signal.

        Parameters
        ----------
        signal : BaseSignal | str
            The signal for which to set the navigation state.
        """
        print(self.navigation_manager_states)
        print("Setting navigation manager state for signal:", signal)
        if isinstance(signal, str):
            signal = self.navigation_signals[signal]
        self.navigation_manager_state = self.navigation_manager_states.get(
            signal, NavigationManagerState(signal=signal, plot_manager=self)
        )
        for plot in self.plots:
            # create plot states for the child plot if it does not exist
            print("setting plot state for plot:", plot)
            plot.set_plot_state(signal)

    @property
    def nav_dim(self) -> int:
        """
        Get the number of navigation dimensions in the signal tree.
        """
        return self.signal_tree.nav_dim

    def add_navigation_selector_and_signal_plot(self, selector_type=None):
        """
        Add a Selector (or Multi-selector) to the navigation plots. For 2+ dimensional
        navigation signals, multiple-linked selectors will be created.
        """
        from spyde.drawing.selector import (
            IntegratingLinearRegionSelector,
            IntegratingRectangleSelector,
            BaseSelector,
        )

        if self.nav_dim == 1 and selector_type is None:
            selector_type = IntegratingLinearRegionSelector
        elif self.nav_dim == 2 and selector_type is None:
            selector_type = IntegratingRectangleSelector
        elif not isinstance(selector_type, BaseSelector):
            raise ValueError("Type must be a BaseSelector class.")
        # need to add an N-D Selector

        if self.nav_dim > 2:
            raise NotImplementedError(
                "Navigation selectors for >2D navigation not implemented yet."
            )
        else:
            logger.info("Adding navigation selector for 2+ dimensional navigation signals")
            window = PlotWindow(
                is_navigator=False,
                plot_manager=None,
                signal_tree=self.signal_tree,
                main_window=self.main_window,
                       )
            child = window.add_new_plot()
            # create plot states for the child plot
            self.signal_tree.create_plot_states(plot=child)


            logger.info("Added Child plot states: ", child.plot_states)
            selector = selector_type(
                parent=self.plots[0],
                children=child,
                update_function=update_from_navigation_selection,
            )
            child.set_plot_state(list(child.plot_states.keys())[0])
            self.navigation_selectors.append(selector)
            # Auto range...
            selector.update_data()
            child.update_data(child.current_data, force=True)
            logger.info("Auto-ranging child plot")
            child.getViewBox().autoRange()
            self.signal_tree.signal_plots.append(child)
            child.needs_auto_level = True
            logger.info("Added navigation selector and signal plot:", selector, child)
