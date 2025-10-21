from despy.drawing.toolbars.rounded_toolbar import RoundedToolBar
from PySide6.QtGui import QIcon
from PySide6 import QtCore, QtWidgets
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from despy.drawing.multiplot import Plot


class Plot2DControlToolbar(RoundedToolBar):
    def __init__(self,
                 parent:None,
                 vertical: bool = True,
                 plot: "Plot" = None):
        super().__init__(title="Plot Controls", parent=parent, plot=plot, vertical=vertical)

        # Actions

        add_selector_action = self.addAction(QIcon('drawing/toolbars/icons/add_selector.svg'), "Add Selector")
        add_selector_action.triggered.connect(self.plot.add_selector_and_new_plot)

        # need to set all the action icons size at the end
        self.set_size()


class Plot1DControlToolbar(RoundedToolBar):
    """
    A toolbar to manage plot controls.
    """

    def __init__(self,
                 parent=None,
                 vertical=True,
                 plot: "Plot" = None):
        super().__init__(parent,
                         plot=plot,
                         vertical=vertical)

        # need to set all the action icons size at the end
        self.set_size()


