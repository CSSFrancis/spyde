from spyde.drawing.selectors.base_selector import BaseSelector, IntegratingSelectorMixin


import time

from pyqtgraph import LinearRegionItem, RectROI, LineROI, ROI

from PySide6 import QtCore, QtWidgets, QtGui
import numpy as np

import pyqtgraph as pg
import logging

from typing import TYPE_CHECKING, Union, List, Type, Iterable

from spyde.drawing.selectors.utils import create_linked_linear_region, create_linked_infinite_line

if TYPE_CHECKING:
    from spyde.drawing.plots.plot import Plot
    from spyde.drawing.plots.plot_window import PlotWindow

Logger = logging.getLogger(__name__)


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
        self.roi = LinearRegionItem(
            pen=self.roi_pen, hoverPen=self.hoverPen, *args, **kwargs
        )
        self._last_size_sig = self._size_signature()
        self.roi.sigRegionChangeFinished.connect(self._on_region_change_finished)

        for plot in parent.plots:
            # The selector isn't actually added to any plot??
            self.add_linked_roi(plot)
        self.roi.sigRegionChanged.connect(self.update_data)


    def _get_selected_indices(self):
        """
        Get the currently selected indices from the selector.
        """

        axs = self.parent.current_plot_state.current_signal.axes_manager.signal_axes[0]

        scale = axs.scale
        offset = axs.offset

        region = self.roi.getRegion()
        start, end = region
        if start > end:
            start, end = end, start

        start = (start - offset) / scale
        end = (end - offset) / scale

        indices = np.arange(
            np.floor(start).astype(int), np.ceil(end).astype(int)
        ).reshape(-1, 1)

        return indices

    def add_linked_roi(self, plot: "Plot"):

        if self.roi is not None:
            new_selector = create_linked_linear_region(self.roi,
                                                       pen=self.roi_pen,
                                                       hover_pen=self.hoverPen)
            plot.addItem(new_selector)
            self.linked_selectors.append(new_selector)

    def translate_pixels(self, shift_x: int):
        """
        Translate the selector by the given amount in pixels.
        """
        if self.roi is not None:
            axs = self.parent.current_plot_state.current_signal.axes_manager.signal_axes[0]
            scale = axs.scale
            offset = axs.offset
            region = self.roi.getRegion()
            start, end = region

            self.roi.setRegion([start + shift_x*scale, end + shift_x*scale])

    def move_roi(self, key: QtCore.Qt.Key):
        """
        Move the selector based on the key pressed.
        """
        self.timer = time.time()
        if key == QtCore.Qt.Key.Key_Left:
            self.translate_pixels(-1)
        elif key == QtCore.Qt.Key.Key_Right:
            self.translate_pixels(1)

class InfiniteLineSelector(BaseSelector):
    """
    A selector which uses an InfiniteLine to select a single position along one axis.

    """

    def __init__(
        self,
        parent: "PlotWindow",
        children: Union["Plot", List["Plot"]],
        update_function: Union[callable, List[callable]],
        *args,
        **kwargs,
    ):
        super().__init__(
            parent,
            children,
            update_function,
            *args,
            **kwargs,
        )
        self.roi = pg.InfiniteLine(
            angle=90,
            pen=self.roi_pen,
            hoverPen=self.hoverPen,
            movable=True
        )

        for plot in parent.plots:
            # The selector isn't actually added to any plot??
            self.add_linked_roi(plot)
        self.roi.sigPositionChanged.connect(self.update_data)

    def _get_selected_indices(self):
        """
        Get the currently selected index from the selector.
        """

        axs = self.parent.current_plot_state.current_signal.axes_manager.signal_axes[0]

        scale = axs.scale
        offset = axs.offset

        pos = self.roi.value()
        index = int(np.round((pos - offset) / scale))

        return np.array([[index]])

    def add_linked_roi(self, plot: "Plot"):

        if self.roi is not None:
            new_selector = create_linked_infinite_line(self.roi,
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
            pos = self.selector.value()

            self.selector.setValue(pos + shift_x*scale)

    def move_roi(self, key: QtCore.Qt.Key):
        """
        Move the selector based on the key pressed.
        """
        self.timer = time.time()
        if key == QtCore.Qt.Key.Key_Left:
            self.translate_pixels(-1)
        elif key == QtCore.Qt.Key.Key_Right:
            self.translate_pixels(1)



class IntegratingSelector1D(IntegratingSelectorMixin):
    def __init__(
            self,
            parent: "PlotWindow",
            children: Union["Plot", List["Plot"]],
            update_function: Union[callable, List[callable]],
            *args,
            **kwargs,
    ):
        super().__init__(parent, children, update_function, *args, **kwargs)
        self._inf_line_selector = InfiniteLineSelector(
            parent,
            children,
            update_function,
            *args,
            **kwargs,
        )
        self._linear_region_selector = LinearRegionSelector(
            parent,
            children,
            update_function,
            *args,
            **kwargs,
        )

        self._hide_linear_region_selector()
        self.selector = self._inf_line_selector
        # connect the is_integrating property to the selector
        self._inf_line_selector.is_integrating = False
        self._linear_region_selector.is_integrating = True

    def _hide_linear_region_selector(self):
        """Hide the linear region selector."""
        print(f"Hiding {self._linear_region_selector.linked_selectors}")
        for linked in self._linear_region_selector.linked_selectors:
                linked.hide()

    def _show_linear_region_selector(self):
        """Show the linear region selector."""
        for linked in self._linear_region_selector.linked_selectors:
                linked.show()
        self.selector = self._linear_region_selector

    def _hide_inf_line_selector(self):
        """Hide the inf. line selector."""
        for linked in self._inf_line_selector.linked_selectors:
                linked.hide()

    def _show_inf_line_selector(self):
        """Show the inf. line selector."""
        for linked in self._inf_line_selector.linked_selectors:
                linked.show()
        self.selector = self._inf_line_selector

    def add_linked_selector(self, plot: "Plot"):
        """Add both selectors to the new plot."""
        self._inf_line_selector.add_linked_roi(plot)
        self._linear_region_selector.add_linked_roi(plot)
        if not self.is_integrating:
            self._show_inf_line_selector()
            self._hide_linear_region_selector()
        else:
            self._show_linear_region_selector()
            self._hide_inf_line_selector()

    def on_integrate_toggled(self, checked):
        """Switch between inf line and region."""
        if not checked:
            self._hide_linear_region_selector()
            self._show_inf_line_selector()
        else:
            self._hide_inf_line_selector()
            self._show_linear_region_selector()
        super().on_integrate_toggled(checked)

    def _get_selected_indices(self):
        """Handle both inf line and region selectors."""
        if not self.is_integrating:
            # Use inf line implementation
            return self._inf_line_selector._get_selected_indices()
        else:
            # Use parent implementation for rectangle
            return self._linear_region_selector._get_selected_indices()

    def move_roi(self, key: QtCore.Qt.Key):
        """Move the active selector."""
        if not self.is_integrating:
            self._inf_line_selector.move_roi(key)
        else:
            self._linear_region_selector.move_roi(key)

    def hide(self):
        """Hide both selectors."""
        self._inf_line_selector.hide()
        self._linear_region_selector.hide()

    @property
    def roi(self):
        return self.selector.roi

    def show(self):
        """Show the active selector."""
        if not self.is_integrating:
            self._inf_line_selector.show()
        else:
            self._linear_region_selector.show()

    def close(self):
        """Close both selectors."""
        self._inf_line_selector.close()
        self._linear_region_selector.close()

    def add_linked_roi(self, plot: "Plot"):
        self._inf_line_selector.add_linked_roi(plot=plot)
        self._linear_region_selector.add_linked_roi(plot=plot)