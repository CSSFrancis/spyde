
from typing import Optional, Callable

from PySide6 import QtWidgets, QtGui, QtCore


class RoundedButton(QtWidgets.QPushButton):
    """
    Minimal styled push button with optional icon and text.
    """

    def __init__(
        self,
        icon_path: Optional[str] = None,
        text: Optional[str] = None,
        tooltip: Optional[str] = None,
        parent: Optional[QtWidgets.QWidget] = None,
    ):
        super().__init__(parent)

        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setIconSize(QtCore.QSize(18, 18))
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

        if text:
            self.setText(text)
        if icon_path:
            self.setIcon(QtGui.QIcon(icon_path))
        if tooltip:
            self.setToolTip(tooltip)

        # Consistent hover/pressed background for push buttons
        self.setStyleSheet(
            "QPushButton {"
            "  border: none;"
            "  background-color: rgba(30, 30, 30, 230);"
            "  margin: 2px;"
            "  padding: 4px 8px;"
            "  border-radius: 6px;"
            "}"
            "QPushButton:hover {"
            "  background-color: rgba(40, 40, 40, 230);"
            "}"
            "QPushButton:pressed {"
            "  background-color: rgba(50, 50, 50, 230);"
            "}"
        )