import logging

from pyqtgraph import LinearRegionItem, RectROI, CircleROI, LineROI

from PySide6 import QtCore, QtWidgets, QtGui
import numpy as np

import pyqtgraph as pg
import logging

from typing import TYPE_CHECKING, Union, List

if TYPE_CHECKING:
    from spyde.drawing.multiplot import Plot, NavigationPlotManager

Logger = logging.getLogger(__name__)


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
        parent: Union["Plot", "NavigationPlotManager"],
        children: Union["Plot", List["Plot"]],
        update_function: Union[callable, List[callable]],
        width: int = 3,
        color: str = "green",
        hover_color: str = "red",
        live_delay: int = 20,
        resize_on_move: bool = False,
    ):

        # the parent plot (data source) and the child plot (where the data is plotted)
        # a selector can have multiple children.
        self.parent = parent  # type: Plot | NavigationPlotManager
        if not isinstance(children, list):
            self.children = {children: update_function}  # type: dict[Plot, callable]
            self.active_children = [
                children,
            ]  # type: list[Plot]
            children.parent_selector = self

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

    def apply_transform_to_selector(self, transform: QtGui.QTransform):
        """
        Apply a transformation to the selector.
        """
        if self.selector is not None:
            self.selector.resetTransform()
            self.selector.setTransform(transform)

    def get_selected_indices(self):
        """
        Get the currently selected indices from the selector.
        """
        raise NotImplementedError(
            "get_selected_indices must be implemented in subclasses"
        )

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
        print("updating the data:", self.children)
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
            vb = child_plot.plot_item.getViewBox()
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
            self.parent.plot_item.removeItem(self.selector)
            self.parent.plot_item.update()
        self.selector = None


class RectangleSelector(BaseSelector):
    def __init__(
        self,
        parent: Union["Plot", "NavigationPlotManager"],
        children: Union["Plot", List["Plot"]],
        update_function: Union[callable, List[callable]],
        live_delay: int = 20,
        *args,
        **kwargs,
    ):
        super().__init__(
            parent, children, update_function, live_delay=live_delay, *args, **kwargs
        )
        print("Creating Rectangle Selector")
        print(args, kwargs)
        self.selector = RectROI(
            pos=(0, 0),
            size=(10, 10),
            pen=self.roi_pen,
            handlePen=self.handlePen,
            hoverPen=self.hoverPen,
            handleHoverPen=self.handleHoverPen,
            *args,
            **kwargs,
        )
        self._last_size_sig = (0, 0)
        self.selector.sigRegionChangeFinished.connect(self._on_region_change_finished)

        parent.plot_item.addItem(self.selector)
        self.selector.sigRegionChanged.connect(self.update_data)

    def get_selected_indices(self):
        """
        Get the currently selected indices from the selector.
        """
        lower_left = self.selector.pos()
        size = self.selector.size()

        # pyqtgraph only knows one coordinate system.  We need to map to scene
        # to pixels.

        inverted_transform, is_inversion = self.parent.image_item.transform().inverted()

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
        parent: Union["Plot", "NavigationPlotManager"],
        children: Union["Plot", List["Plot"]],
        update_function: Union[callable, List[callable]],
        live_delay: int = 20,
        *args,
        **kwargs,
    ):
        super().__init__(
            parent, children, update_function, live_delay=live_delay, *args, **kwargs
        )


class LinearRegionSelector(BaseSelector):
    """
    A selector which uses a LinearRegionItem to select a region along one axis.

    """

    def __init__(
        self,
        parent: Union["Plot", "NavigationPlotManager"],
        children: Union["Plot", List["Plot"]],
        update_function: Union[callable, List[callable]],
        *args,
        **kwargs,
    ):
        super().__init__(parent, children, update_function, *args, **kwargs)
        self.selector = LinearRegionItem(
            pen=self.roi_pen, hoverPen=self.hoverPen, *args, **kwargs
        )
        self._last_size_sig = self._size_signature()
        self.selector.sigRegionChangeFinished.connect(self._on_region_change_finished)
        parent.plot_item.addItem(self.selector)
        self.selector.sigRegionChanged.connect(self.update_data)

    def get_selected_indices(self):
        """
        Get the currently selected indices from the selector.
        """
        region = self.selector.getRegion()
        if region[0] > region[1]:
            region = (region[1], region[0])
        indices = np.array(
            [
                np.arange(
                    np.floor(region[0]).astype(int), np.ceil(region[1]).astype(int)
                ),
            ]
        ).T
        return indices


class IntegratingLinearRegionSelector(IntegratingSelectorMixin, LinearRegionSelector):
    def __init__(
        self,
        parent: Union["Plot", "NavigationPlotManager"],
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
        parent: Union["Plot", "NavigationPlotManager"],
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
        parent.plot_item.addItem(self.selector)
        self.selector.sigRegionChanged.connect(self.update_data)

    def get_selected_indices(self):
        """
        Get the currently selected indices from the selector.
        """
        pos = self.selector.getArraySlice(
            np.arange(self.parent.data.shape[0]), self.parent.data.shape
        )[0]
        indices = np.array(
            [[np.round(pos[0][i]).astype(int)] for i in range(len(pos[0]))]
        )
        return indices
