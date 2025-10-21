from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from despy.drawing.plot import Plot


class RoundedToolBar(QtWidgets.QToolBar):
    """
    A QToolBar with rounded corners and a semi-transparent background.
    """
    def __init__(self,
                 title: str,
                 plot: "Plot" = None,
                 parent: QtWidgets.QWidget = None,
                 radius: int = 8,
                 moveable: bool=False,
                 vertical: bool=False):
        super().__init__(title, parent)
        self._radius = float(radius)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self.setContentsMargins(0, 0, 0, 0)
        self.plot = plot

        # set up fixed style
        self.setOrientation(QtCore.Qt.Orientation.Vertical if vertical
                            else QtCore.Qt.Orientation.Horizontal)

        # Compact buttons
        self.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.setIconSize(QtCore.QSize(18, 18))

        # Hover/pressed background for tool buttons
        self.setStyleSheet(
            "QToolBar {"
            "  background: transparent;"
            "  border: none;"
            "  padding: 4px;"
            "  margin: 0px;"
            "}"
            "QToolButton {"
            "  border: none;"
            "  margin: 2px;"
            "  background: transparent;"
            "  padding: 4px;"
            "  border-radius: 6px;"
            "}"
            "QToolButton:hover {"
            "  background-color: rgba(255, 255, 255, 40);"
            "}"
            "QToolButton:pressed {"
            "  background-color: rgba(255, 255, 255, 64);"
            "}"
        )
        self.setMovable(moveable)

        # Move/link guards and margin
        self._move_sync = False
        self._margin = 8

    def set_plot(self, plot: "Plot"):
        self.plot = plot
        # Actions
        reset_act = self.addAction(QIcon('drawing/toolbars/icons/fullsize.svg'), "Reset")
        reset_act.triggered.connect(lambda: self.plot.plot_item.getViewBox().autoRange())

        zoom_in = self.addAction(QIcon('drawing/toolbars/icons/zoom.svg'), "Zoom In")
        zoom_in.triggered.connect(lambda: self._zoom(0.8))

        zoom_out = self.addAction(QIcon('drawing/toolbars/icons/zoomout.svg'), "Zoom Out")
        zoom_out.triggered.connect(lambda: self._zoom(1.25))
        self.set_size()

    def set_size(self):
        # Lock size so it doesn't change when moved
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed,
                           QtWidgets.QSizePolicy.Policy.Fixed)
        self.setFixedSize(self.sizeHint())

        # Initial placement
        QtCore.QTimer.singleShot(0, self.move_next_to_plot)

    def paintEvent(self, ev: QtGui.QPaintEvent) -> None:
        """
        """
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        # Sub-pixel align for crisp 1px stroke at any DPR
        rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        path = QtGui.QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)

        # Fill
        p.setBrush(QtGui.QColor(30, 30, 30, 180))
        # 1px cosmetic pen to keep edge sharp on HiDPI
        pen = QtGui.QPen(QtGui.QColor(255, 255, 255, 60))
        pen.setWidthF(1.0)
        pen.setCosmetic(True)
        pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)

        p.drawPath(path)
        # Children (tool buttons) paint themselves
        super().paintEvent(ev)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if self.plot is None or self._move_sync:
            return

        # Move the plot to stay at a fixed offset to the left of this toolbar
        parent_viewport = self.plot.parentWidget()  # QMdiArea viewport
        if parent_viewport is None:
            return

        self._move_sync = True
        try:
            # Toolbar TL in global coords -> MDI viewport coords
            tb_global = self.mapToGlobal(QtCore.QPoint(0, 0))
            tb_in_mdi = parent_viewport.mapFromGlobal(tb_global)

            # Desired plot TL: to the left of the toolbar by margin
            new_plot_pos = tb_in_mdi - QtCore.QPoint(self.plot.width() + self._margin, self._margin)
            self.plot.move(new_plot_pos)
            self.plot.raise_()
        finally:
            self._move_sync = False

    def move_next_to_plot(self):
        """Place the toolbar to the right of the plot using global mapping."""
        if self.plot is None or self.parentWidget() is None:
            return

        parent = self.parentWidget()
        plot_global_tl = self.plot.mapToGlobal(QtCore.QPoint(0, 0))
        desired_global = QtCore.QPoint(plot_global_tl.x() + self.plot.width() + self._margin,
                                       plot_global_tl.y() + self._margin)
        desired_in_parent = parent.mapFromGlobal(desired_global)

        self._move_sync = True
        try:
            self.move(desired_in_parent)
            self.raise_()
        finally:
            self._move_sync = False

    def _zoom(self, factor: float):
        vb = self.plot.plot_item.getViewBox()
        vb.scaleBy((factor, factor))
