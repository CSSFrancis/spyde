import time
from multiprocessing.shared_memory import SharedMemory

from PySide6 import QtCore, QtGui

import pyqtgraph as pg
from distributed.client import FutureCancelledError
from pyqtgraph import PlotItem

from spyde.external.pyqtgraph.scale_bar import OutlinedScaleBar as ScaleBar
from math import floor, log10

import numpy as np
import dask.array as da
from dask.distributed import Future

from typing import TYPE_CHECKING, Union, List, Dict, Tuple, Optional

if TYPE_CHECKING:
    from spyde.signal_tree import BaseSignalTree
    from spyde.__main__ import MainWindow
    from spyde.drawing.selectors import BaseSelector
from hyperspy.signal import BaseSignal
from spyde.drawing.plots.plot_states import PlotState

import logging

logger = logging.getLogger(__name__)

COLORMAPS = {
    "gray": pg.colormap.get("CET-L1"),
    "viridis": pg.colormap.get("viridis"),
    "plasma": pg.colormap.get("plasma"),
    "cividis": pg.colormap.get("cividis"),
    "fire": pg.colormap.get("CET-L3"),
}


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
        is_navigator: bool = False,
        multiplot_manager: Union["MultiplotManager", None] = None,
        plot_window: Union["PlotWindow", None] = None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.is_navigator = is_navigator
        # update flags
        self.needs_update_range = (
            None
        )  # type: bool | None # whether the range needs to be updated
        self.needs_auto_level = (
            True
        )  # type: bool # whether the plot needs to be auto-leveled

        # Scale bar for image plots
        self._scale_bar = None  # type: ScaleBar | None # the scale bar item
        self._scale_bar_vb = (
            None
        )  # type: pg.ViewBox | None # the viewbox the scale bar is attached to

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

        self.multiplot_manager = multiplot_manager  # type: MultiplotManager | None

        # Either an image item (2D) or line item (1D)
        self.image_item = pg.ImageItem()  # type: pg.ImageItem
        self.line_item = pg.PlotDataItem()  # type: pg.PlotDataItem

        self.getViewBox().setAspectLocked(True, ratio=1)  # locked aspect ratio

        self._move_sync = True

        self.plot_window = plot_window  # type: PlotWindow | None
        # Register with the main window for needs update

        self._updating_text = None  # type: pg.TextItem | None
        self._needs_hide_updating_text = False

        # shared memory
        BUFFER_SIZE = (8192 * 8192 * 4) + 128  # Example size, adjust as needed
        self.shared_memory = SharedMemory(name=f"plot_buffer{id(self)}",
                                          create=True,
                                          size=BUFFER_SIZE)

        self.data_max_y = 1  # type: float
        self.data_min_y = 0  # type: float

    @property
    def toolbars(self):
        return [
            self.plot_state.toolbar_top,
            self.plot_state.toolbar_bottom,
            self.plot_state.toolbar_left,
            self.plot_state.toolbar_right,
        ]

    def set_colormap(self, colormap: str):
        """Set the colormap for the image item."""
        cmap = COLORMAPS.get(colormap, COLORMAPS["gray"])
        self.image_item.setColorMap(cmap)
        self.plot_state.colormap = colormap

    def enable_scale_bar(self, enabled: bool = True):
        """Enable or disable an auto-updating horizontal scale bar."""
        vb = (
            getattr(self, "vb", None) or getattr(self, "getViewBox", lambda: None)()
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

    @property
    def parent_selector(self):
        """Get the parent selector for this plot."""
        return self.plot_window.parent_selector

    def normalize_axes(self):
        """ Normalize the axes widths for 1D plots in the plot window."""
        for plot in self.plot_window.plots:
            plot.getAxis('left').setWidth(75)

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

        print("setting Plot states: ", self.plot_states, " to signal:", signal)
        self.plot_state = self.plot_states.get(signal)

        # switch plot items if needed for dimensionality change
        old_dim = 0 if old_plot_state is None else old_plot_state.dimensions
        vb = self.getViewBox()

        if self.plot_state.dimensions == 2 and old_dim != 2:
            #self.clear()
            if self.line_item is None:
                self.removeItem(self.line_item)
            self.addItem(self.image_item)
            print("All Items:", self.items)
            vb.setAspectLocked(True, ratio=1)
            vb.enableAutoRange(x=True, y=True)
            vb.autoRange()

        elif self.plot_state.dimensions == 1 and old_dim != 1:
            # self.clear()
            self.addItem(self.line_item)
            vb.setAspectLocked(False)
            vb.enableAutoRange(x=False, y=True)
            vb.setMouseEnabled(x=True, y=False)
            self.normalize_axes()

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
            if self.current_data is None:
                self.parent_selector.delayed_update_data(force=False)
            print("updating data for dynamic plot state...", self.current_data)
            self.update_data(self.current_data, force=False)
        else:
            print(
                "updating data for static plot state...",
                self.plot_state.current_signal.data,
            )
            self.update_data(self.plot_state.current_signal.data)
        self.getViewBox().autoRange()

        # update the toolbars
        self.update_image_rectangle()

        if self.plot_state.dimensions == 2:
            self.enable_scale_bar(True)
        else:
            self.enable_scale_bar(False)
        self.main_window.on_subwindow_activated(self.plot_window)
        # update the plot
        if self.parent_selector is not None:
            self.parent_selector.delayed_update_data(force=False)
            self.needs_update_range = True
            # update the plot range
            self.update_range()

        # show the toolbars should be last so that the widgets can be initialized properly
        print(self.image_item)
        print("Showing toolbars for plot state:", self.plot_state)
        self.plot_state.show_toolbars()
        self.axes["left"]["item"].setLabel(signal.metadata.General.title)

    def add_plot_state(
        self,
        signal: BaseSignal,
        dimensions: int = None,
        dynamic: bool = False,
        overwrite: bool = False,
    ) -> Optional[PlotState]:
        """Create and add a new PlotState for some signal."""
        print("Plot states", self.plot_states)
        if signal not in self.plot_states or overwrite:
            ps = PlotState(
                signal=signal,
                dimensions=dimensions,
                dynamic=dynamic,
                plot=self,
            )
            self.plot_states[signal] = ps
            if self.plot_state is None:
                self.set_plot_state(signal)
            return ps
        else:
            return None

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
                    getattr(self.multiplot_manager, "navigation_selectors", [])
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
        return self.plot_window.main_window

    def update_range(self):
        """Update the view range to fit the current data."""
        self.getViewBox().autoRange()
        #self.normalize_axes()

    def mousePressEvent(self, ev):
        """Ensure clicking a plot marks it as the active plot."""
        super().mousePressEvent(ev)
        if (
            ev.button() == QtCore.Qt.MouseButton.LeftButton
            and self.plot_window is not None
        ):
            self.plot_window.current_plot_item = self

    def add_updating_plot_text(self):
        """Add a text item to the plot that indicates when the plot is updating.

        This should always be in the center of the plot
        """
        self._updating_text = pg.TextItem(
            text=f"Updating Plot...\nVisit {self.main_window.client.dashboard_link} for progress",
            color=(255, 0, 0), anchor=(-.1, -0.5)
        )
        self._updating_text.setZValue(1000)
        self.addItem(self._updating_text)
        self._updating_text.setParentItem(self.getViewBox())

        # Center the text in the current view
        vb = self.getViewBox()
        view_range = vb.viewRange()

        print("The view range:", view_range)
        center_x = (view_range[0][0] + view_range[0][1]) / 2
        center_y = (view_range[1][0] + view_range[1][1]) / 2
        self._updating_text.setPos(center_x, center_y)



    def update_data(
        self, new_data: Union[np.ndarray, da.Array, Future, List[Future]], force: bool = False
    ):
        """Update the current data being displayed in the plot.

        If the new_data is a Future, the update will be deferred until the Future is complete, the update
        will be handled by the event loop instead.
        """
        print("Updating plot data", new_data, " force=", force)


        #  This is just a workaround as hyperspy doesn't currently handle Future arrays.
        # TODO: Remove this when hyperspy supports Future arrays.
        if isinstance(new_data, np.ndarray) and isinstance(new_data[0], Future):
            new_data =  new_data[0]

        # When first initialized we can set up the data as np.ones...
        if self.current_data is None and isinstance(new_data, Future):
            place_holder = np.ones(self.plot_state.current_signal.axes_manager.signal_shape)
            if place_holder.ndim == 2:
                #make checkerboard pattern to indicate loading
                place_holder[::2, ::2] = 0
            self.current_data = place_holder
            self.update()

            self.add_updating_plot_text()
            # This will then get overwritten below when the Future completes.
            self.needs_update_range = True
            self.needs_auto_level = True
            self._needs_hide_updating_text = True
        print("Setting current data to:", new_data)
        self.current_data = new_data
        if isinstance(new_data, Future) and not force:
            pass
        elif isinstance(new_data, Future) and force:
            try:
                self.current_data = new_data.result()
                self.update()
            except FutureCancelledError:
                print("Future was cancelled, cannot update plot data.")
                pass
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
            dynamic=True,
        )
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
        print("Showing selectors for plot_window:", self.plot_window)
        print("Current visible selectors:", visible_selectors)
        if self.multiplot_manager is not None:
            if self.plot_window not in self.multiplot_manager.navigation_selectors:
                print("No navigation selectors for this plot window.")
            else:
                visible_selectors += self.multiplot_manager.navigation_selectors[
                    self.plot_window
                ]
            print("visible selectors:", visible_selectors)
        # Hide selectors from other plots. Faster than deleting and recreating them (also renders nicer).
        for selector in self.main_window.navigation_selectors:
            if selector not in visible_selectors:
                selector.widget.hide()
            else:
                if selector.widget.parent() is None:
                    self.main_window.selectors_layout.addWidget(selector.widget)
                selector.widget.show()

    def remove_selector_control_widgets(self):
        print("Removing selector control widgets for plot_window:", self.plot_window)
        visible_selectors = (
            self.plot_state.plot_selectors + self.plot_state.signal_tree_selectors
        )
        if self.multiplot_manager is not None:
            print("Nav sel", self.multiplot_manager.navigation_selectors)
            print("Plot win", self.plot_window)
            if self.plot_window not in self.multiplot_manager.navigation_selectors:
                print("No navigation selectors for this plot window.")
            else:
                visible_selectors += self.multiplot_manager.navigation_selectors[
                    self.plot_window
                ]
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
            print("Updating 1D plot with axis:", axis)
            print("Data shape:", current_data)
            self.line_item.setData(axis, current_data)

            if self._needs_hide_updating_text and self._updating_text is not None:
                self.removeItem(self._updating_text)
                self._updating_text.hide()
                self._updating_text = None
                self._needs_hide_updating_text = False

            if self.needs_update_range:
                self.data_max_y = np.nanmax(current_data)
                self.data_min_y = np.nanmin(current_data)
                self.update_range()
                self.needs_update_range = False

        elif self.plot_state.dimensions == 2:
            img = (
                np.asarray(self.current_data)
                if isinstance(self.current_data, da.Array)
                else self.current_data
            )

            print("Setting image data with img", img)

            start_time = time.perf_counter()
            if img.dtype == np.int16:
                img = img.astype(np.uint16)
            self.image_item.setImage(
                img, levels=(self.plot_state.min_level, self.plot_state.max_level),autoDownsample=True
            )
            elapsed = time.perf_counter() - start_time
            print(f"setImage took {elapsed * 1000:.2f}ms")
            if self.needs_auto_level and img is not None:
                mn, mx = self.image_item.quickMinMax()
                self.image_item.setLevels((mn, mx))
                self.plot_state.max_level = mx
                self.plot_state.min_level = mn
                self.plot_state.max_percentile = 100.0
                self.plot_state.min_percentile = 0.0
                self.needs_auto_level = False
            if self._needs_hide_updating_text and self._updating_text is not None:
                self.removeItem(self._updating_text)
                self._updating_text.hide()
                self._updating_text = None
                self._needs_hide_updating_text = False
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

        logger.info("Plot: Removing selector control widgets for this plot")
        # Remove the selectors for this plot
        self.remove_selector_control_widgets()

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
