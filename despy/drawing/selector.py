from pyqtgraph import LinearRegionItem, RectROI, CircleROI

from PySide6 import QtCore, QtWidgets
import numpy as np

import pyqtgraph as pg


class Selector:
    def __init__(self,
                 parent=None,
                 on_nav=True,
                 integration_order=None,
                 type="RectangleSelector",
                 *args,
                 **kwargs):

        # Create a pen with a width of 3 pixels and a red color
        roi_pen = pg.mkPen(color='green', width=5)
        handlePen = pg.mkPen(color='green', width=5)
        hoverPen = pg.mkPen(color='r', width=5)
        handleHoverPen = pg.mkPen(color='r', width=5)

        if type == "RectangleSelector":
            print("Creating Rectangle Selector")
            print(args, kwargs)
            self.selector = RectROI(pen=roi_pen,
                                    handlePen=handlePen,
                                    hoverPen=hoverPen,
                                    handleHoverPen=handleHoverPen,
                                    *args,
                                    **kwargs,
                                    )
        elif type == "CircleSelector" or type == "RingSelector":
            self.selector = CircleROI(*args, **kwargs, edge_thickness=4)
        elif type == "LineSelector":
            self.selector = LinearRegionItem(pen=roi_pen,
                                             hoverPen=hoverPen,
                                             *args,
                                             **kwargs)
        else:
            raise ValueError("Invalid Selector Type")
        parent.addItem(self.selector)

        self.is_live = not on_nav  # if on signal is_live is always False
        self.widget = QtWidgets.QWidget()
        self.layout = QtWidgets.QHBoxLayout(self.widget)
        self.plots = []
        self.is_integrating = False

        self.update_timer = QtCore.QTimer()
        self.update_timer.setInterval(20)  # Every 20ms we will check to update the plots??
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self.delayed_update_data)

        if on_nav:
            self.integrate_button = QtWidgets.QPushButton("Integrate")
            self.integrate_button.setCheckable(True)
            self.live_button = QtWidgets.QPushButton("Live")
            self.live_button.setCheckable(True)
            self.live_button.setChecked(True)
            self.live_button.toggled.connect(self.on_live_toggled)
            self.layout.addWidget(self.live_button)
        else:
            self.integrate_button = QtWidgets.QPushButton("Compute")
            self.integrate_button.setCheckable(False)

        self.integrate_button.setChecked(False)
        self.integrate_button.update()
        self.integrate_button.toggled.connect(self.on_integrate_toggled)
        self.integrate_button.pressed.connect(self.on_integrate_pressed)
        self.layout.addWidget(self.integrate_button)
        self.widget.setLayout(self.layout)
        self.integration_order = integration_order
        self.last_indices = [[0, 0],]

    def __getattr__(self, item):
        try:
            return getattr(self.selector, item)
        except AttributeError:
            raise AttributeError(f"'Selector' object has no attribute '{item}'")

    def on_integrate_toggled(self, checked):
        print("Integrate Toggled")
        print(self.is_live)
        if self.is_live:
            self.is_integrating = checked
            self.update_data()
            for p in self.plots:
                p.update_plot(get_result=True)

    def on_integrate_pressed(self):
        if not self.is_live:
            # fire off the integration
            print("Computing!")
            for p in self.plots:
                p.compute_data()

    def on_live_toggled(self, checked):
        self.is_live = checked
        if checked:
            self.integrate_button.setText("Integrate")
            self.integrate_button.setCheckable(True)
            self.integrate_button.setChecked(self.is_integrating)
            self.selection = (self.selection[0], self.selection[0] + 15, self.selection[2], self.selection[2] + 15)
            self.size_limits = (1, 15, 1, 15)
            # update the plot
            for p in self.plots:
                p.update_data()
        else:
            self.integrate_button.setText("Compute")
            self.is_integrating = True
            self.integrate_button.setCheckable(False)
            self.size_limits = (1, self.limits[1], 1, self.limits[3])

    def get_selected_indices(self):
        """
        Get the currently selected indices from the selector.

        This just gets the list of x, y indices  to handel arbitrary ROIs,
        shapes etc.
        """
        if isinstance(self.selector, RectROI):
            lower_left = self.selector.pos()
            size = self.selector.size()
            
            # ignore rotation for now...
            rotation = self.selector.angle()

            y_indices = np.arange(0, np.round(size.y()), dtype=int)
            x_indices = np.arange(0, np.round(size.x()), dtype=int)

            indices = np.reshape(np.array(np.meshgrid(x_indices,
                                                      y_indices)).T,
                                 (-1, 2))
            indices[:, 0] += np.round(lower_left.x()).astype(int)
            indices[:, 1] += np.round(lower_left.y()).astype(int)
            indices = indices.astype(int)

        elif isinstance(self.selector, LinearRegionItem):
            region = self.selector.getRegion()
            if region[0] > region[1]:
                region = (region[1], region[0])
            indices = np.array([np.arange(np.floor(region[0]).astype(int),
                                          np.ceil(region[1]).astype(int)),]).T
        else:
            raise NotImplementedError("Selector type not supported yet")

        if not self.is_integrating:
            # just take the mean index
            indices = np.array([[np.round(np.mean(indices[:, i])).astype(int)
                                for i in range(indices.shape[1])],])


        return indices

    def update_data(self, ev=None):
        """
        Start the timer to delay the update.
        """
        if ev is None:
            self.delayed_update_data()
        elif self.is_live:
            print("Restarting Timer")
            self.update_timer.start()

    def delayed_update_data(self):
        """
        Perform the actual update if the indices have not changed.
        """
        print("Time out")
        indices = self.get_selected_indices()
        print("Indices", indices)
        print("Last Indices", self.last_indices)
        if not np.array_equal(indices, self.last_indices):
            print("Updating Data")
            self.last_indices = indices
            for p in self.plots:
                p.current_indexes[self.integration_order] = indices
                print("Updating Plot")
                p.update_plot()