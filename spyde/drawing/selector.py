from pyqtgraph import LinearRegionItem, RectROI, LineROI

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
        chosen_rows = m[g.ravel()]          # shape: (n_comb, Ci)
        parts.append(chosen_rows)

    # Concatenate columns from all arrays
    combined = np.concatenate(parts, axis=1)
    return combined

def no_return_update_function(selector: "BaseSelector", child_plot: "Plot", indices: np.ndarray):
    """
    An update function that does nothing and returns None.
    Useful as a placeholder when no update is needed.
    """
    return None

def create_linked_selectors(
    selector_cls: Type["BaseSelector"],
    initial_selector: "BaseSelector",
    parent_plots: Iterable["Plot"],
) -> List["BaseSelector"]:
    """
    Create new selectors on `parent_plots` that stay linked with `initial_selector`.

    * Each plot gets its own selector instance.
    * Any change to one selector's ROI is propagated to all others.
    """
    parent_plots = list(parent_plots)
    if not parent_plots:
        return []

    # Collect all selectors that will participate in the linkage
    selectors: List["BaseSelector"] = [initial_selector]

    # Build a selector on each plot except the one that already has initial_selector
    for plot in parent_plots:
        if plot is initial_selector.parent:
            continue

        sel = selector_cls(
            parent=initial_selector.parent,
            children=[],
            update_function=[no_return_update_function,],
            multi_selector=initial_selector.multi_selector,
        )
        # Force an initial geometry sync from the master
        _copy_selector_geometry(src=initial_selector, dst=sel)
        selectors.append(sel)

    # Link all selectors together
    _wire_selector_group(selectors)
    return selectors


def _copy_selector_geometry(src: "BaseSelector", dst: "BaseSelector") -> None:
    """
    Copy ROI/region geometry from `src` to `dst`.

    This assumes your `BaseSelector` exposes a uniform API, e.g.
    * `get_geometry()` / `set_geometry()`
    or at least `getRegion()` / `setRegion()` for linear/rectangular ROIs.
    Adjust this function to match your actual selector API.
    """
    selector_src = src.selector
    selector_dst = dst.selector

    # LinearRegionItem / similar
    if hasattr(selector_src, "getRegion") and hasattr(selector_dst, "setRegion"):
        region = selector_src.getRegion()
        selector_dst.setRegion(region)
        return

    # Rectangular ROI / general ROI
    if hasattr(selector_src, "pos") and hasattr(selector_src, "size"):
        selector_dst.setPos(selector_src.pos())
        if hasattr(selector_dst, "setSize"):
            selector_dst.setSize(selector_src.size())
        return

    # Fallback: extend as needed (elliptical, annular, etc.)
    # raise NotImplementedError or just ignore


def _wire_selector_group(selectors: List["BaseSelector"]) -> None:
    """
    Wire a list of selectors so that any change to one updates all the others.
    """
    if not selectors:
        return

    updating = {"flag": False}  # simple reentrancy guard

    def make_handler(src_sel: BaseSelector):
        def _on_region_changed(*_args, **_kwargs):
            if updating["flag"]:
                return
            updating["flag"] = True
            try:
                for other in selectors:
                    if other is src_sel:
                        continue
                    _copy_selector_geometry(src_sel, other)
                    # Trigger their own update without refiring the change signal
                    other.delayed_update_data(force=True)
            finally:
                updating["flag"] = False

        return _on_region_changed

    # Connect both continuous and finished signals if present
    for sel in selectors:
        roi = sel.selector
        handler = make_handler(sel)

        if hasattr(roi, "sigRegionChanged"):
            roi.sigRegionChanged.connect(handler)
        if hasattr(roi, "sigRegionChangeFinished"):
            roi.sigRegionChangeFinished.connect(handler)
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
        live_delay: int = 20,
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
            #children.parent_selector = self

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
        self.multi_selector = multi_selector

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
            combo = upstream_indices + [current_indices,]
            combined_indices = broadcast_rows_cartesian(*combo)
            return combined_indices
        else:
            print("single selector", self._get_selected_indices())
            return self._get_selected_indices()

    def _get_selected_indices(self):
        """
        Placeholder method to be implemented in subclasses.
        """
        raise NotImplementedError("Subclasses must implement _get_selected_indices method.")

    def upstream_selectors(self):
        """
        Get a list of upstream selectors.
        """
        selectors = []
        current = self.parent
        while hasattr(current, "parent_selector") and current.parent_selector is not None:
            selectors.append(current.parent_selector)
            current = current.parent_selector.parent
        return selectors

    def update_data(self, ev=None):
        """
        Start the timer to delay the update.
        """
        if ev is None:
            self.delayed_update_data()
        else:
            print("Restarting Timer")
            self.update_timer.start()

    def delayed_update_data(self, force: bool = False, update_contrast: bool = False):
        """
        Perform the actual update if the indices have not changed.
        """
        indices = self.get_selected_indices()
        if not np.array_equal(indices, self.current_indices) or force:
            for child in self.children:
                print("Updating Child Plot:", child)
                new_data = self.children[child](self, child, indices)
                child.update_data(
                    new_data
                )  # update the child plot data. If this is a future then
                if update_contrast:
                    child.needs_auto_level = True
                # update all plots downstream of the child
                print("Child plot updated.", child)
                print("Child.multiplot_manager:", child.multiplot_manager)
                if child.multiplot_manager is not None and child.plot_window in child.multiplot_manager.navigation_selectors:
                    print("Updating Downstream Plots...")
                    for child_selector in child.multiplot_manager.navigation_selectors[child.plot_window]:
                        child_selector.delayed_update_data()
            # the plot will update when the future completes
            self.current_indices = indices

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
        live_delay: int = 20,
        multi_selector: bool = False,
        *args,
        **kwargs,
    ):
        super().__init__(
            parent, children, update_function, live_delay=live_delay, multi_selector=multi_selector, *args, **kwargs
        )
        print("Creating Rectangle Selector")
        print(args, kwargs)


        # auto position and size
        # 10 % of the image size and bottom left corner
        transform  = parent.current_plot_item.image_item.transform()
        pos  = transform.map(QtCore.QPointF(0, 0))
        width = parent.current_plot_item.image_item.width()//10

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
            print("Adding selector to plot:", plot)
            plot.addItem(self.selector)
        self.selector.sigRegionChanged.connect(self.update_data)

    def _get_selected_indices(self):
        """
        Get the currently selected indices from the selector.
        """
        if self.multi_selector:
            [parent_selector.get_selected_indices() for parent_selector in self.upstream_selectors()]

        lower_left = self.selector.pos()
        size = self.selector.size()

        # pyqtgraph only knows one coordinate system.  We need to map to scene
        # to pixels.

        inverted_transform, is_inversion = self.parent.current_plot_item.image_item.transform().inverted()

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
        live_delay: int = 20,
        multi_selector: bool = False,
        *args,
        **kwargs,
    ):
        super().__init__(
            parent, children, update_function, live_delay=live_delay, multi_selector=multi_selector, *args, **kwargs
        )


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
        super().__init__(parent, children, update_function, multi_selector=multi_selector, *args, **kwargs)
        self.selector = LinearRegionItem(
            pen=self.roi_pen, hoverPen=self.hoverPen, *args, **kwargs
        )
        self._last_size_sig = self._size_signature()
        self.selector.sigRegionChangeFinished.connect(self._on_region_change_finished)
        for plot in parent.plots:
            plot.addItem(self.selector)
        self.selector.sigRegionChanged.connect(self.update_data)

    def _get_selected_indices(self):
        """
        Get the currently selected indices from the selector.
        """

        axs = self.parent.current_plot_state.current_signal.axes_manager.signal_axes[0]

        scale  = axs.scale
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
            np.arange(self.parent.current_plot_item.data.shape[0]), self.parent.data.shape
        )[0]
        indices = np.array(
            [[np.round(pos[0][i]).astype(int)] for i in range(len(pos[0]))]
        )
        return indices
