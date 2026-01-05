from __future__ import annotations
from typing import Optional, Union

from PySide6 import QtCore, QtGui, QtWidgets


def _opposite_side(side: str) -> str:
    """Return the opposite side for caret positioning."""
    return {"top": "bottom", "bottom": "top", "left": "right", "right": "left"}.get(
        side, "top"
    )


def _bind_action_to_plot_item(
        action: Optional[QtGui.QAction], item: Union[QtWidgets.QGraphicsItem, QtWidgets.QWidget]
) -> None:
    """Bind action toggle/trigger to plot item visibility."""
    if action is None:
        return

    if action.isCheckable():
        action.toggled.connect(lambda checked, it=item: it.setVisible(checked))
    else:
        action.triggered.connect(lambda _, it=item: it.setVisible(not it.isVisible()))


def _set_initial_item_visibility(
        item: Union[QtWidgets.QGraphicsItem, QtWidgets.QWidget], action: Optional[QtGui.QAction]
) -> None:
    """Set initial visibility for plot item based on action state."""
    try:
        visible = bool(action.isChecked()) if (action and action.isCheckable()) else False
        item.setVisible(visible)
    except Exception:
        pass


def _sync_plot_items_visibility(
        action: Optional[QtGui.QAction], data: dict
) -> None:
    """Sync plot items visibility with action state."""
    for item in data.get("plot_items", {}).values():
        try:
            if action and action.isCheckable():
                item.setVisible(action.isChecked())
        except Exception:
            pass


def _center_vertically(
        btn: Optional[QtWidgets.QToolButton], fallback_y: int, widget_height: int
) -> int:
    """Center widget vertically relative to button."""
    if btn:
        return btn.mapToGlobal(QtCore.QPoint(0, 0)).y() + (btn.height() - widget_height) // 2
    return fallback_y


def _center_horizontally(
        btn: Optional[QtWidgets.QToolButton], fallback_x: int, widget_width: int
) -> int:
    """Center widget horizontally relative to button."""
    if btn:
        return btn.mapToGlobal(QtCore.QPoint(0, 0)).x() + (btn.width() - widget_width) // 2
    return fallback_x


def _configure_widget_layout(
        widget: QtWidgets.QWidget, layout: Optional[QtWidgets.QLayout]
) -> None:
    """Configure widget layout if provided."""
    if layout is not None:
        if layout.parent() is not None and layout.parent() is not widget:
            layout.setParent(None)
        if widget.layout() is None:
            widget.setLayout(layout)


def _finalize_popout_layout(popout: QtWidgets.QWidget) -> None:
    """Ensure popout layout is finalized before positioning."""
    try:
        if hasattr(popout, "finalize_layout"):
            popout.finalize_layout()
    except Exception:
        pass