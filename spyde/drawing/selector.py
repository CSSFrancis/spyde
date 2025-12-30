import time

from pyqtgraph import LinearRegionItem, RectROI, LineROI, ROI

from PySide6 import QtCore, QtWidgets, QtGui
import numpy as np

import pyqtgraph as pg
import logging

from typing import TYPE_CHECKING, Union, List, Type, Iterable

if TYPE_CHECKING:
    from spyde.drawing.plots.plot import Plot, PlotWindow

Logger = logging.getLogger(__name__)


def broadcast_rows_cartesian(*arrays: np.ndarray) -> np.ndarray:
    """
    Cartesian product over *rows* of multiple index arrays, keeping
    the columns of each array together.

    Each input is treated as shape (Ni, Ci): Ni rows, Ci columns.
    The output has shape (N_total, sum(Ci)), where N_total is the
    product of all Ni.

    Example:
    time_axs    : (3, 1) -> [[0],[1],[2]]
    spatial_axs : (3, 2) -> [[3,4],[4,5],[5,6]]

    broadcast_rows_cartesian(time_axs, spatial_axs) ->
        shape (9, 3), rows like [t, x, y].
    """
    if len(arrays) == 0:
        return np.empty((0, 0), dtype=int)

    # Normalize to 2D: (N_rows, N_cols)
    mats = [np.atleast_2d(a) for a in arrays]
    n_rows = [m.shape[0] for m in mats]

    # Meshgrid over row indices only
    grids = np.meshgrid(*[np.arange(n) for n in n_rows], indexing="ij")

    # For each array, select rows according to its index grid and reshape
    parts = []
    for m, g in zip(mats, grids):
        # g.ravel() gives the chosen row index per combination
        chosen_rows = m[g.ravel()]  # shape: (n_comb, Ci)
        parts.append(chosen_rows)

    # Concatenate columns from all arrays
    combined = np.concatenate(parts, axis=1)
    return combined


def no_return_update_function(
    selector: "BaseSelector", child_plot: "Plot", indices: np.ndarray
):
    """
    An update function that does nothing and returns None.
    Useful as a placeholder when no update is needed.
    """
    return None


def create_linked_rect_roi(core_roi: ROI) -> ROI:
    """Create a new ROI of the same type as `core_roi`, linked to `core_roi` so that it always matches its geometry/
    position.
    """

    roi_type = type(core_roi)

    new_roi = roi_type(
        pos=core_roi.pos(),
        size=core_roi.size(),
        pen=core_roi.pen,
        handlePen=core_roi.handlePen,
        hoverPen=core_roi.hoverPen,
        handleHoverPen=core_roi.handleHoverPen,
    )

    def sync_roi(source_roi, target_roi):
        """Synchronize target_roi to match source_roi's state."""
        target_roi.blockSignals(True)  # Prevent infinite recursion
        target_roi.setPos(source_roi.pos(), finish=False)
        target_roi.setSize(source_roi.size(), finish=False)
        target_roi.setAngle(source_roi.angle(), finish=False)
        target_roi.blockSignals(False)
        print("Syncing ROIs:", source_roi, target_roi)
        #target_roi.sigRegionChanged.emit()

    core_roi.sigRegionChanged.connect(lambda: sync_roi(core_roi, new_roi))
    new_roi.sigRegionChanged.connect(lambda: sync_roi(new_roi, core_roi))

    new_roi.sigRegionChanged.connect(core_roi.sigRegionChanged.emit)

    return new_roi

def create_linked_linear_region(core_roi: LinearRegionItem,
                                pen,
                                hover_pen) -> LinearRegionItem:
    """Create a new LinearRegionItem linked to `core_roi` so that it always matches its geometry/position.
    """

    new_roi = LinearRegionItem(
        values=core_roi.getRegion(),
        pen = pen,
        hoverPen = hover_pen,
    )

    def sync_roi(source_roi, target_roi):
        """Synchronize target_roi to match source_roi's state."""
        target_roi.blockSignals(True)  # Prevent infinite recursion
        target_roi.setRegion(source_roi.getRegion())
        target_roi.blockSignals(False)
        print("Syncing Linear ROIs:", source_roi, target_roi)

    core_roi.sigRegionChanged.connect(lambda: sync_roi(core_roi, new_roi))
    new_roi.sigRegionChanged.connect(lambda: sync_roi(new_roi, core_roi))

    new_roi.sigRegionChanged.connect(core_roi.sigRegionChanged.emit)

    return new_roi



class BaseSelector:
    """
    Base class for selectors.

    Parameters
    ----------
    parent : Plot
        The parent plot item to which the selector will be added.
    child : Plot | None
        An optional child plot item to which the selector will send updates when the selection
        moves.
    update_function : callable | None
        An optional function to call when the selection. This is a function that takes a BaseSelector instance
        (self) and the selected indices as arguments and then performs the update on the child plot.
        If the function returns a da.Future, the update timer will start and wait for the future to complete
        before updating the child plot.
    width : int
        The width of the selector lines.
    color : str
        The color of the selector lines.
    hover_color : str
        The color of the selector lines when hovered.
    """

    def __init__(
        self,
        parent: "PlotWindow",
        children: Union["Plot", List["Plot"]],
        update_function: Union[callable, List[callable]],
        width: int = 3,
        color: str = "green",
        hover_color: str = "red",
        live_delay: int = 2,
        resize_on_move: bool = False,
        multi_selector: bool = False,
    ):

        # the parent plot (data source) and the child plot (where the data is plotted)
        # a selector can have multiple children.
        self.parent = parent  # type: PlotWindow
        if not isinstance(children, list):
            self.children = {children: update_function}  # type: dict[Plot, callable]
            self.active_children = [
                children,
            ]  # type: list[Plot]
            children.plot_window.parent_selector = self
            # children.parent_selector = self

        else:
            self.children = {}  # type: dict[Plot, callable]
            for child, function in zip(children, update_function):
                self.children[child] = function
                child.parent_selector = self

        # Create a pen for the selector
        self.roi_pen = pg.mkPen(color=color, width=width)  # type: pg.mkPen
        self.handlePen = pg.mkPen(color=color, width=width)  # type: pg.mkPen
        self.hoverPen = pg.mkPen(color=hover_color, width=width)  # type: pg.mkPen
        self.handleHoverPen = pg.mkPen(color=hover_color, width=width)  # type: pg.mkPen

        # The widget which is added to the sidebar to control things like updating, if the selector is
        # live or if the selector should integrate.
        self.widget = QtWidgets.QWidget()  # type: QtWidgets.QWidget
        self.layout = QtWidgets.QHBoxLayout(self.widget)  # type: QtWidgets.QHBoxLayout
        self.is_integrating = False

        # The current selection
        self.current_indices = None

        self.update_timer = QtCore.QTimer()  # type: QtCore.QTimer
        self.update_timer.setInterval(
            live_delay
        )  # To make things smoother we delay how fast we update the plots
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self.delayed_update_data)
        self.update_function = update_function
        self._last_size_sig = None
        self.selector = None  # to be defined in subclasses # type: pg.ROI | None
        self.linked_selectors = []  # type: List[ROI]
        self.multi_selector = multi_selector
        self.timer = None

    def apply_transform_to_selector(self, transform: QtGui.QTransform):
        """
        Apply a transformation to the selector.
        """
        if self.selector is not None:
            self.selector.resetTransform()
            self.selector.setTransform(transform)

    def _get_selected_indices_from_upstream(self):
        """
        Get the selected indices from upstream selectors.
        """
        indices_list = []
        for parent_selector in self.upstream_selectors():
            indices = parent_selector._get_selected_indices()
            indices_list.append(indices)
        return indices_list

    def get_selected_indices(self):
        """
        Get the currently selected indices from the selector.
        """
        if self.multi_selector:
            upstream_indices = self._get_selected_indices_from_upstream()
            current_indices = self._get_selected_indices()
            combo = upstream_indices + [
                current_indices,
            ]
            combined_indices = broadcast_rows_cartesian(*combo)
            return combined_indices
        else:
            print("single selector", self._get_selected_indices())
            return self._get_selected_indices()

    def _get_selected_indices(self):
        """
        Placeholder method to be implemented in subclasses.
        """
        raise NotImplementedError(
            "Subclasses must implement _get_selected_indices method."
        )

    def upstream_selectors(self):
        """
        Get a list of upstream selectors.
        """
        selectors = []
        current = self.parent
        while (
            hasattr(current, "parent_selector") and current.parent_selector is not None
        ):
            selectors.append(current.parent_selector)
            current = current.parent_selector.parent
        return selectors

    def update_data(self, ev=None):
        """
        Start the timer to delay the update.
        """
        print("Updating Data...", )
        if ev is None:
            self.delayed_update_data()
        else:
            print("Restarting Timer")
            self.update_timer.start()

    def delayed_update_data(self, force: bool = False, update_contrast: bool = False):
        """
        Perform the actual update if the indices have not changed.
        """
        if self.timer is not None:
            print(f"Starting Updating Data, timer took {(time.time() - self.timer)*1000:.2f} ms")

        indices = self.get_selected_indices()
        if not np.array_equal(indices, self.current_indices) or force:
            for child in self.children:
                new_data = self.children[child](self, child, indices, cache_in_shared_memory=True)
                child.update_data(
                    new_data
                )  # update the child plot data. If this is a future, then
                if update_contrast:
                    child.needs_auto_level = True
                # update all plots downstream of the child
                if (
                    child.multiplot_manager is not None
                    and child.plot_window
                    in child.multiplot_manager.navigation_selectors
                ):
                    print("Updating Downstream Plots...")
                    for child_selector in child.multiplot_manager.navigation_selectors[
                        child.plot_window
                    ]:
                        child_selector.delayed_update_data()
            # the plot will update when the future completes
            self.current_indices = indices
        if self.timer is not None:
            print(f"Finished Updating Data, took {(time.time() - self.timer)*1000:.2f} ms")

    # Helper: compute a compact signature of the current selector size
    def _size_signature(self):
        sel = getattr(self, "selector", None)
        if isinstance(sel, LinearRegionItem):
            region = sel.getRegion()
            width = float(abs(region[1] - region[0]))
            return (round(width, 6),)
        if isinstance(sel, RectROI):
            s = sel.size()
            return (int(round(s.x())), int(round(s.y())))
        if isinstance(sel, LineROI):
            # approximate by length of the line
            p1, p2 = sel.pos(), sel.pos() + sel.size()
            dx, dy = float(p2.x() - p1.x()), float(p2.y() - p1.y())
            length = (dx * dx + dy * dy) ** 0.5
            return (round(length, 6),)
        return None

    # Helper: autorange a child plot based on its dimension
    def _autorange_child_plot(self, child_plot):
        try:
            vb = child_plot.getViewBox()
        except Exception:
            return
        dim = getattr(getattr(child_plot, "plot_state", None), "dimensions", None)
        if dim == 1:
            vb.setAspectLocked(False)
        vb.enableAutoRange(x=True, y=True)
        vb.autoRange()

    # Called when the user finishes a region change; only auto-range on size changes
    def _on_region_change_finished(self):
        new_sig = self._size_signature()
        size_changed = new_sig != self._last_size_sig
        if size_changed or self._last_size_sig is None:
            for child in self.children.keys():
                self._autorange_child_plot(child)
            self._last_size_sig = new_sig

    def add_linked_selector(self, plot: "Plot"):
        """
        Add the selector to a new plot.
        """
        pass

    def move_selector(self, key: QtCore.Qt.Key):
        """
        Move the selector based on the key pressed.
        """
        pass

    def close(self):
        """
        Clean up the selector.
        """
        if self.selector is not None:
            for plot in self.parent.plots:
                if self.selector in plot.items:
                    plot.removeItem(self.selector)
                    plot.update()
        self.selector = None


class RectangleSelector(BaseSelector):
    def __init__(
        self,
        parent: "PlotWindow",
        children: Union["Plot", List["Plot"]],
        update_function: Union[callable, List[callable]],
        live_delay: int = 2,
        multi_selector: bool = False,
        *args,
        **kwargs,
    ):
        super().__init__(
            parent,
            children,
            update_function,
            live_delay=live_delay,
            multi_selector=multi_selector,
            *args,
            **kwargs,
        )
        print("Creating Rectangle Selector")
        print(args, kwargs)

        # auto position and size
        # 10 % of the image size and bottom left corner
        transform = parent.current_plot_item.image_item.transform()
        pos = transform.map(QtCore.QPointF(0, 0))
        width = parent.current_plot_item.image_item.width() // 10

        self.selector = RectROI(
            pos=pos,
            size=(width, width),
            pen=self.roi_pen,
            handlePen=self.handlePen,
            hoverPen=self.hoverPen,
            handleHoverPen=self.handleHoverPen,
            *args,
            **kwargs,
        )
        self._last_size_sig = (0, 0)
        self.selector.sigRegionChangeFinished.connect(self._on_region_change_finished)

        for plot in parent.plots:
            # The selector isn't actually added to any plot??
            self.add_linked_selector(plot)
        self.selector.sigRegionChanged.connect(self.update_data)

    def _get_selected_indices(self):
        """
        Get the currently selected indices from the selector.
        """
        if self.multi_selector:
            [
                parent_selector.get_selected_indices()
                for parent_selector in self.upstream_selectors()
            ]

        lower_left = self.selector.pos()
        size = self.selector.size()

        # pyqtgraph only knows one coordinate system.  We need to map the scene
        # to pixels.

        inverted_transform, is_inversion = (
            self.parent.current_plot_item.image_item.transform().inverted()
        )

        lower_left_pixel = inverted_transform.map(lower_left)

        size_pixels = inverted_transform.map(size) - inverted_transform.map(
            QtCore.QPointF(0, 0)
        )

        # ignore rotation for now...
        rotation = self.selector.angle()

        y_indices = np.arange(0, np.round(size_pixels.y()), dtype=int)
        x_indices = np.arange(0, np.round(size_pixels.x()), dtype=int)

        indices = np.reshape(np.array(np.meshgrid(x_indices, y_indices)).T, (-1, 2))
        indices[:, 0] += np.round(lower_left_pixel.x()).astype(int)
        indices[:, 1] += np.round(lower_left_pixel.y()).astype(int)
        indices = indices.astype(int)
        return indices

    def add_linked_selector(self, plot: "Plot"):

        if self.selector is not None:
            new_selector = create_linked_rect_roi(self.selector)
            plot.addItem(new_selector)
            self.linked_selectors.append(new_selector)

    def translate_pixels(self, shift_x: int, shift_y: int):
        """
        Translate the selector by the given amount in pixels.
        """
        if self.selector is not None:
            shift = QtCore.QPointF(shift_x, shift_y)
            transform = self.parent.current_plot_item.image_item.transform()
            shift = transform.map(shift)
            self.selector.translate(shift.x(), shift.y())


    def move_selector(self, key: QtCore.Qt.Key):
        """
        Move the selector based on the key pressed.
        """
        self.timer = time.time()
        if key == QtCore.Qt.Key.Key_Left:
            self.translate_pixels(-1, 0)
        elif key == QtCore.Qt.Key.Key_Right:
            self.translate_pixels(1, 0)
        elif key == QtCore.Qt.Key.Key_Up:
            self.translate_pixels(0, 1)
        elif key == QtCore.Qt.Key.Key_Down:
            self.translate_pixels(0, -1)


class IntegratingSelectorMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_live = True

        self.integrate_button = QtWidgets.QPushButton("Integrate")
        self.integrate_button.setCheckable(True)
        self.live_button = QtWidgets.QPushButton("Live")
        self.live_button.setCheckable(True)
        self.live_button.setChecked(True)
        self.live_button.toggled.connect(self.on_live_toggled)
        self.layout.addWidget(self.live_button)
        # Turn buttons red while pressed
        _red_btn_style = "QPushButton:checked { background-color: red; }"
        self.live_button.setStyleSheet(_red_btn_style)
        self.integrate_button.setStyleSheet(_red_btn_style)

        self.integrate_button.setChecked(False)
        self.integrate_button.update()
        self.integrate_button.toggled.connect(self.on_integrate_toggled)
        self.integrate_button.pressed.connect(self.on_integrate_pressed)
        self.layout.addWidget(self.integrate_button)
        self.widget.setLayout(self.layout)
        self.size_limits = (1, 15, 1, 15)

    def on_integrate_toggled(self, checked):
        print("Integrate Toggled")
        print(self.is_live)
        if self.is_live:
            self.is_integrating = checked
            self.delayed_update_data(force=True, update_contrast=True)

    def on_integrate_pressed(self):
        if not self.is_live:
            # fire off the integration
            print("Computing!")
            self.delayed_update_data(force=True, update_contrast=True)

    def on_live_toggled(self, checked):
        self.is_live = checked
        if checked:
            self.integrate_button.setText("Integrate")
            self.integrate_button.setCheckable(True)
            self.integrate_button.setChecked(self.is_integrating)
            # TODO: Need to set selection to some default small region for live mode
            self.size_limits = (1, 15, 1, 15)
            # update the plot
            self.delayed_update_data(force=True, update_contrast=True)

        else:
            self.integrate_button.setText("Compute")
            self.is_integrating = True
            self.integrate_button.setCheckable(False)
            # self.size_limits = (1, self.limits[1], 1, self.limits[3])
            # don't need to update the plot here.

    def update_data(self, ev=None):
        """
        Start the timer to delay the update.
        """
        print("Updating Data")
        if self.is_live:
            if ev is None:
                self.delayed_update_data()
            else:
                Logger.log(level=logging.INFO, msg="Restarting Timer")
                self.update_timer.start()


class IntegratingRectangleSelector(IntegratingSelectorMixin, RectangleSelector):
    def __init__(
            self,
            parent: "PlotWindow",
            children: Union["Plot", List["Plot"]],
            update_function: Union[callable, List[callable]],
            live_delay: int = 3,
            multi_selector: bool = False,
            *args,
            **kwargs,
    ):
        # Store initial crosshair size options
        self._crosshair_selector = None
        self._rect_selector = None

        super().__init__(
            parent,
            children,
            update_function,
            live_delay=live_delay,
            multi_selector=multi_selector,
            *args,
            **kwargs,
        )

        # Store the rectangle selector created by parent
        self._rect_selector = self.selector

        # Start with crosshair mode
        self._switch_to_crosshair_mode()


    def on_integrate_toggled(self, checked):
        """Switch between crosshair and rectangle."""
        if not checked:
            self._switch_to_crosshair_mode()
        else:
            self._switch_to_rectangle_mode()
        super().on_integrate_toggled(checked)

    def _switch_to_crosshair_mode(self):
        """Replace rectangle with crosshair."""
        if self._crosshair_selector is None:
            # Get center of current rectangle
            pos = self._rect_selector.pos()
            size = self._rect_selector.size()
            center_pos = pos + QtCore.QPointF(size.x() / 2, size.y() / 2)

            # Create crosshair at center with pixel size
            pixel_size = 3 * 10
            view = self.parent.current_plot_item.getViewBox()

            self._crosshair_selector = CrosshairROI(
                center_pos,
                pixel_size=pixel_size,
                view=view,
                pen=self.roi_pen,
                hoverPen=self.hoverPen
            )
            self._crosshair_selector.sigRegionChanged.connect(self.update_data)

        # Remove rectangle from plots
        for plot in self.parent.plots:
            if self._rect_selector in plot.items:
                plot.removeItem(self._rect_selector)

        # Remove linked rectangles
        for linked in self.linked_selectors:
            for plot in self.parent.plots:
                if linked in plot.items:
                    plot.removeItem(linked)

        # Add crosshair
        for plot in self.parent.plots:
            plot.addItem(self._crosshair_selector)

        self.selector = self._crosshair_selector
        # maybe both should be connected?
        self.selector.sigRegionChanged.connect(self.update_data)

    def _switch_to_rectangle_mode(self):
        """Replace crosshair with rectangle."""
        if self._crosshair_selector is not None:
            # Get crosshair center position
            pos = self._crosshair_selector.pos()
            size = self._crosshair_selector.size()
            center_pos = pos + QtCore.QPointF(size[0] / 2, size[1] / 2)

            # Disconnect zoom updates
            view = self.parent.current_plot_item.getViewBox()
            if view is not None:
                self._crosshair_selector.view.sigRangeChanged.disconnect(
                    self._crosshair_selector._update_for_zoom
                )

            # Remove crosshair
            for plot in self.parent.plots:
                if self._crosshair_selector in plot.items:
                    plot.removeItem(self._crosshair_selector)

            self._crosshair_selector.sigRegionChanged.disconnect(self.update_data)

            # Position rectangle at crosshair center
            rect_size = self._rect_selector.size()
            new_pos = center_pos - QtCore.QPointF(rect_size.x() / 2, rect_size.y() / 2)
            self._rect_selector.setPos(new_pos)

        # Re-add rectangle and linked selectors
        for i, plot in enumerate(self.parent.plots):
            if i == 0:
                plot.addItem(self._rect_selector)
            elif i - 1 < len(self.linked_selectors):
                plot.addItem(self.linked_selectors[i - 1])

        self.selector = self._rect_selector
        self.selector.sigRegionChanged.connect(self.update_data)


    def _get_selected_indices(self):
        """Handle both crosshair and rectangle selection."""
        if not self.is_integrating:
            # Get crosshair center pixel
            inverted_transform, _ = self.parent.current_plot_item.image_item.transform().inverted()
            pos = self._crosshair_selector.pos()
            size = self._crosshair_selector.size()
            center = pos + QtCore.QPointF(size[0] / 2, size[1] / 2)
            center_pixel = inverted_transform.map(center)

            x = int(np.round(center_pixel.x()))
            y = int(np.round(center_pixel.y()))
            indices = np.array([[x, y]])
            print("Selected Indices (Crosshair):", indices)
            return indices
        else:
            # Use parent implementation for rectangle
            return super()._get_selected_indices()

class LinearRegionSelector(BaseSelector):
    """
    A selector which uses a LinearRegionItem to select a region along one axis.

    """

    def __init__(
        self,
        parent: "PlotWindow",
        children: Union["Plot", List["Plot"]],
        update_function: Union[callable, List[callable]],
        multi_selector: bool = False,
        *args,
        **kwargs,
    ):
        super().__init__(
            parent,
            children,
            update_function,
            multi_selector=multi_selector,
            *args,
            **kwargs,
        )
        self.selector = LinearRegionItem(
            pen=self.roi_pen, hoverPen=self.hoverPen, *args, **kwargs
        )
        self._last_size_sig = self._size_signature()
        self.selector.sigRegionChangeFinished.connect(self._on_region_change_finished)

        for plot in parent.plots:
            # The selector isn't actually added to any plot??
            self.add_linked_selector(plot)
        self.selector.sigRegionChanged.connect(self.update_data)


    def _get_selected_indices(self):
        """
        Get the currently selected indices from the selector.
        """

        axs = self.parent.current_plot_state.current_signal.axes_manager.signal_axes[0]

        scale = axs.scale
        offset = axs.offset

        region = self.selector.getRegion()
        start, end = region
        if start > end:
            start, end = end, start

        start = (start - offset) / scale
        end = (end - offset) / scale

        indices = np.arange(
            np.floor(start).astype(int), np.ceil(end).astype(int)
        ).reshape(-1, 1)

        return indices

    def add_linked_selector(self, plot: "Plot"):

        if self.selector is not None:
            new_selector = create_linked_linear_region(self.selector,
                                                       pen=self.roi_pen,
                                                       hover_pen=self.hoverPen)
            plot.addItem(new_selector)
            self.linked_selectors.append(new_selector)

    def translate_pixels(self, shift_x: int):
        """
        Translate the selector by the given amount in pixels.
        """
        if self.selector is not None:
            axs = self.parent.current_plot_state.current_signal.axes_manager.signal_axes[0]
            scale = axs.scale
            offset = axs.offset
            region = self.selector.getRegion()
            start, end = region

            self.selector.setRegion([start + shift_x*scale, end + shift_x*scale])

    def move_selector(self, key: QtCore.Qt.Key):
        """
        Move the selector based on the key pressed.
        """
        self.timer = time.time()
        if key == QtCore.Qt.Key.Key_Left:
            self.translate_pixels(-1)
        elif key == QtCore.Qt.Key.Key_Right:
            self.translate_pixels(1)


class IntegratingLinearRegionSelector(IntegratingSelectorMixin, LinearRegionSelector):
    def __init__(
            self,
            parent: "PlotWindow",
            children: Union["Plot", List["Plot"]],
            update_function: Union[callable, List[callable]],
            *args,
            **kwargs,
    ):
        super().__init__(parent, children, update_function, *args, **kwargs)
        self._line_mode_selector = None
        self._region_selector = self.selector

        # Initialize in line mode since is_integrating starts as False (Probably should
        self._switch_to_line_mode()

    def on_integrate_toggled(self, checked):
        """Override to switch between LinearRegionItem and InfiniteLine."""
        if not checked:
            # Switch to InfiniteLine mode when NOT integrating
            self._switch_to_line_mode()
        else:
            # Switch back to LinearRegionItem mode when integrating
            self._switch_to_region_mode()
        super().on_integrate_toggled(checked)

    def _switch_to_line_mode(self):
        """Replace LinearRegionItem with InfiniteLine."""
        if self._line_mode_selector is None:
            region = self.selector.getRegion()
            center = (region[0] + region[1]) / 2

            self._line_mode_selector = pg.InfiniteLine(
                pos=center,
                angle=90,
                pen=self.roi_pen,
                hoverPen=self.hoverPen,
                movable=True
            )

        # Remove LinearRegionItem from all plots
        for plot in self.parent.plots:
            if self.selector in plot.items:
                plot.removeItem(self.selector)

        # Remove linked selectors
        for linked in self.linked_selectors:
            for plot in self.parent.plots:
                if linked in plot.items:
                    plot.removeItem(linked)

        # Add InfiniteLine to all plots
        for plot in self.parent.plots:
            plot.addItem(self._line_mode_selector)

        self._line_mode_selector.sigPositionChanged.connect(self.update_data)

    def _switch_to_region_mode(self):
        """Replace InfiniteLine with LinearRegionItem."""
        if self._line_mode_selector is not None:
            # Get position from InfiniteLine
            pos = self._line_mode_selector.value()

            # Remove InfiniteLine from all plots
            for plot in self.parent.plots:
                if self._line_mode_selector in plot.items:
                    plot.removeItem(self._line_mode_selector)

            self._line_mode_selector.sigPositionChanged.disconnect(self.update_data)

            # Restore LinearRegionItem centered at the line position
            width = 10  # Default width, adjust as needed
            self.selector.setRegion([pos - width / 2, pos + width / 2])

            # Re-add LinearRegionItem and linked selectors
            for i, plot in enumerate(self.parent.plots):
                if i == 0:
                    plot.addItem(self.selector)
                else:
                    plot.addItem(self.linked_selectors[i - 1])

    def _get_selected_indices(self):
        """Override to handle both LinearRegionItem and InfiniteLine."""
        if not self.is_integrating and self._line_mode_selector is not None:
            # Get single index from InfiniteLine
            axs = self.parent.current_plot_state.current_signal.axes_manager.signal_axes[0]
            scale = axs.scale
            offset = axs.offset

            pos = self._line_mode_selector.value()
            index = int(np.round((pos - offset) / scale))

            print("Selected index from line:", index)
            return np.array([[index]])
        else:
            # Use parent implementation for LinearRegionItem
            return super()._get_selected_indices()

class LineSelector(BaseSelector):
    """
    A selector which uses a LineROI to select a region along one axis.

    """

    def __init__(
        self,
        parent: "PlotWindow",
        children: Union["Plot", List["Plot"]],
        update_function: Union[callable, List[callable]],
        *args,
        **kwargs,
    ):
        super().__init__(parent, children, update_function, *args, **kwargs)
        self.selector = LineROI(
            pen=self.roi_pen,
            handlePen=self.handlePen,
            hoverPen=self.hoverPen,
            handleHoverPen=self.handleHoverPen,
            *args,
            **kwargs,
        )
        for plot in parent.plots:
            plot.addItem(self.selector)
        self.selector.sigRegionChanged.connect(self.update_data)

    def _get_selected_indices(self):
        """
        Get the currently selected indices from the selector.
        """
        pos = self.selector.getArraySlice(
            np.arange(self.parent.current_plot_item.data.shape[0]),
            self.parent.data.shape,
        )[0]
        indices = np.array(
            [[np.round(pos[0][i]).astype(int)] for i in range(len(pos[0]))]
        )
        return indices


class CrosshairROI(pg.ROI):
    """A crosshair (+) shaped ROI with adjustable arm lengths that stays constant size when zooming."""

    def __init__(self, pos, pixel_size=10, view=None, **kwargs):
        super().__init__(pos, [pixel_size, pixel_size], **kwargs)
        self.pixel_size = pixel_size  # Size in pixels
        self.view = view  # ViewBox reference

        # Remove default handle
        for h in self.getHandles():
            self.removeHandle(h)

        # Add handle at center to move the crosshair
        self.addTranslateHandle([0.5, 0.5])

        # Connect to view range changes to maintain constant pixel size
        if self.view is not None:
            self.view.sigRangeChanged.connect(self._update_for_zoom)
            self._update_for_zoom()

    def _update_for_zoom(self):
        """Update size based on current zoom level to maintain constant pixel size."""
        if self.view is None:
            return

        # Get the current view range
        view_rect = self.view.viewRect()
        view_width = view_rect.width()
        view_height = view_rect.height()

        # Get widget size in pixels
        widget_width = self.view.width()
        widget_height = self.view.height()

        if widget_width == 0 or widget_height == 0:
            return

        # Calculate data units per pixel
        units_per_pixel_x = view_width / widget_width
        units_per_pixel_y = view_height / widget_height

        # Set size to maintain constant pixel size
        scene_size = max(units_per_pixel_x, units_per_pixel_y) * self.pixel_size
        self.setSize([scene_size, scene_size], finish=False)
        self.size_value = scene_size

    def paint(self, p, *args):
        """Draw a + shape with a small square in the center."""
        pen = self.currentPen
        p.setPen(pen)

        size = self.size_value
        center = size / 2

        # Draw vertical line
        p.drawLine(QtCore.QPointF(center, 0), QtCore.QPointF(center, size))
        # Draw horizontal line
        p.drawLine(QtCore.QPointF(0, center), QtCore.QPointF(size, center))

        # Draw small square in center (10% of total size)
        square_size = size * 0.1
        half_square = square_size / 2
        p.drawRect(QtCore.QRectF(
            center - half_square,
            center - half_square,
            square_size,
            square_size
        ))

    def set_pixel_size(self, pixel_size):
        """Adjust the crosshair pixel size."""
        self.pixel_size = pixel_size
        self._update_for_zoom()
        self.update()

    def boundingRect(self):
        return QtCore.QRectF(0, 0, self.size_value, self.size_value)