import time

from pyqtgraph import LinearRegionItem, RectROI, LineROI, ROI

from PySide6 import QtCore, QtWidgets, QtGui
import numpy as np

import pyqtgraph as pg
import logging

from typing import TYPE_CHECKING, Union, List

from spyde.drawing.selectors.utils import broadcast_rows_cartesian

if TYPE_CHECKING:
    from spyde.drawing.plots.plot import Plot
    from spyde.drawing.plots.plot_window import PlotWindow

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
        self.roi = None  # to be defined in subclasses # type: pg.ROI | None
        self.linked_selectors = []  # type: List[ROI]
        self.multi_selector = multi_selector
        self.timer = None

    def apply_transform_to_selector(self, transform: QtGui.QTransform):
        """
        Apply a transformation to the selector.
        """
        if self.roi is not None:
            self.roi.resetTransform()
            self.roi.setTransform(transform)

    def _get_selected_indices_from_upstream(self):
        """
        Get the selected indices from upstream selectors.
        """
        indices_list = []
        for parent_selector in self.upstream_selectors():
            indices = parent_selector._get_selected_indices_and_clip()
            indices_list.append(indices)
        return indices_list


    def get_selected_indices(self):
        """
        Get the currently selected indices from the selector.
        """
        if self.multi_selector:
            print("Multi Selector")
            upstream_indices = self._get_selected_indices_from_upstream()
            print("Upstream Indices: ", upstream_indices)
            current_indices = self._get_selected_indices_and_clip()
            combo = upstream_indices + [
                current_indices,
            ]
            combined_indices = broadcast_rows_cartesian(*combo)

            print("Combined Indices:", combined_indices)

            return combined_indices
        else:
            return self._get_selected_indices_and_clip()

    def _get_selected_indices_and_clip(self):
        """
        Get the selected indices and clip them to the data shape.
        """
        indices = self._get_selected_indices()
        signal_shape = self.parent.current_plot_state.current_signal.axes_manager.signal_shape
        clipped_indices = np.clip(indices, 0, np.array(signal_shape) - 1)
        return clipped_indices

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

    def add_linked_roi(self, plot: "Plot"):
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
        self.hide()
        for linked in self.linked_selectors:
            for plot in self.parent.plots:
                if linked in plot.items:
                    plot.removeItem(linked)

    def hide(self):
        """
        Hide the selector.
        """
        for linked in self.linked_selectors:
            linked.hide()

        if self.roi is not None:
            self.roi.hide()


class IntegratingSelectorMixin:
    def __init__(self, *args, **kwargs):
        self.layout = QtWidgets.QHBoxLayout()
        self.widget = QtWidgets.QWidget()

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
        self.selector = None # type: BaseSelector | None

    def on_integrate_toggled(self, checked):
        print("Integrate Toggled")
        print(self.is_live)
        if self.is_live:
            self.is_integrating = checked
            self.selector.delayed_update_data(force=True, update_contrast=True)

    def on_integrate_pressed(self):
        if not self.is_live:
            # fire off the integration
            print("Computing!")
            self.selector.delayed_update_data(force=True, update_contrast=True)

    @property
    def is_live(self):
        return self.live_button.isChecked()

    @property
    def is_integrating(self):
        return self.integrate_button.isChecked()

    @is_integrating.setter
    def is_integrating(self, value: bool):
        self.integrate_button.setChecked(value)


    def on_live_toggled(self, checked):
        if checked:
            self.integrate_button.setText("Integrate")
            self.integrate_button.setCheckable(True)
            self.integrate_button.setChecked(self.is_integrating)
            # TODO: Need to set selection to some default small region for live mode
            self.size_limits = (1, 15, 1, 15)
            # update the plot
            self.selector.delayed_update_data(force=True, update_contrast=True)

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
                self.selector.delayed_update_data()
            else:
                Logger.log(level=logging.INFO, msg="Restarting Timer")
                self.update_timer.start()

