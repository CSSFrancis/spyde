from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

from functools import partial
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from despy.drawing.plot import Plot


class RoundedToolBar(QtWidgets.QToolBar):
    """
    A QToolBar with rounded corners and a semi-transparent background.

    This toolbar is designed to be used alongside a Plot widget, allowing for floating
    tools around some plot area. ("top", "bottom", "left", "right")
    """
    def __init__(self,
                 title: str,
                 plot: "Plot" = None,
                 parent: QtWidgets.QWidget = None,
                 radius: int = 8,
                 moveable: bool=False,
                 position: "str" = "top-left",
                 ):

        if position in ["top", "bottom"]:
            vertical = False
        elif position in ["right", "left"]:
            vertical = True
        self.position = position
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
        self.set_size()

    def add_action(self,
                   name: str,
                   icon_path: str,
                   function: callable):
        """
        Add an action to the toolbar.

        Parameters
        ----------
        name : str
            The name of the action.
        icon_path : str
            The path to the icon for the action.
        function : callable
            The function to be called when the action is triggered.
        """
        icon = QIcon(icon_path)

        new_action = self.addAction(icon, name)
        partial_function = partial(function, self.plot)
        new_action.triggered.connect(partial_function)

    def num_actions(self) -> int:
        """
        Get the number of actions in the toolbar.

        Returns
        -------
        int
            The number of actions in the toolbar.
        """
        return len(self.actions())

    def remove_action(self, name: str):
        """
        Remove an action from the toolbar by name.

        Parameters
        ----------
        name : str
            The name of the action to be removed.
        """
        for action in self.actions():
            if action.text() == name:
                self.removeAction(action)
                break

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
        # Intentionally do not move the plot here. The plot will reposition us.

    def move_next_to_plot(self):
        """Place the toolbar next to the plot using global mapping."""
        if self.plot is None or self.parentWidget() is None:
            return

        parent = self.parentWidget()
        plot_global_tl = self.plot.mapToGlobal(QtCore.QPoint(0, 0))

        if self.position == "left":
            # to the left of the plot
            desired_global = QtCore.QPoint(
                plot_global_tl.x() - self.width() - self._margin,
                plot_global_tl.y() + self._margin
            )
        elif self.position == "right":
            # to the right of the plot
            desired_global = QtCore.QPoint(
                plot_global_tl.x() + self.plot.width() + self._margin,
                plot_global_tl.y() + self._margin
            )
        elif self.position == "top":
            # above the plot
            desired_global = QtCore.QPoint(
                plot_global_tl.x() + self._margin,
                plot_global_tl.y() - self.height() - self._margin
            )
        else:  # "bottom"
            # below the plot
            desired_global = QtCore.QPoint(
                plot_global_tl.x() + self._margin,
                plot_global_tl.y() + self.plot.height() + self._margin
            )

        desired_in_parent = parent.mapFromGlobal(desired_global)

        self._move_sync = True
        try:
            self.move(desired_in_parent)
            self.raise_()
        finally:
            self._move_sync = False


