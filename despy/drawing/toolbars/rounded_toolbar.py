# python
from typing import TYPE_CHECKING, Callable, Optional

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

if TYPE_CHECKING:
    from despy.drawing.multiplot import Plot


class RoundedToolBar(QtWidgets.QToolBar):
    """
    A QToolBar with rounded corners and a semi-transparent background.

    This toolbar is designed to be used alongside a Plot widget, allowing for floating
    tools around some plot area. ("top", "bottom", "left", "right")
    """
    def __init__(
        self,
        title: str,
        plot: "Plot" = None,
        parent: Optional[QtWidgets.QWidget] = None,
        radius: int = 8,
        moveable: bool = False,
        position: str = "top-left",
    ):
        # Ensure we never parent directly to QMainWindow; prefer content area
        parent = self._resolve_container_parent(parent)

        vertical = position not in ["top", "bottom"]
        self.position = position
        super().__init__(title, parent)

        self._radius = float(radius)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self.setContentsMargins(0, 0, 0, 0)
        self.plot = plot

        self.action_widgets: dict[str, dict] = {}

        # set up fixed style
        self.setOrientation(QtCore.Qt.Orientation.Vertical if vertical
                            else QtCore.Qt.Orientation.Horizontal)

        # Compact buttons
        self.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.setIconSize(QtCore.QSize(18, 18))

        # Hover/pressed background for tool buttons
        #
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
            "QToolButton:checked {"
            "  background-color: rgba(255, 255, 255, 40);"
            "}"
            "QAction:checked {"
            "  background-color: rgba(255, 255, 255, 40);"
            "}"
        )
        self.setMovable(moveable)

        # Move/link guards and margin
        self._move_sync = False
        self._margin = 8
        self.set_size()

        # Track geometry to keep the toolbar and spawned widgets positioned
        self._position_tracker = self._make_position_tracker(self.move_next_to_plot)
        self.installEventFilter(self._position_tracker)
        if (container := self._resolve_container_parent(self.parentWidget())) is not None:
            container.installEventFilter(self._position_tracker)
        if self.plot is not None:
            self.plot.installEventFilter(self._position_tracker)

    def add_action(self,
                   name: str,
                   icon_path: str,
                   function: Callable,
                   toggle: bool = False) -> QtGui.QAction:
        """
        Add an action to the toolbar.
        """
        action = self.addAction(QIcon(icon_path), name)
        print(f"Adding action '{name}' to toolbar.")
        print("  Toggle:", toggle)
        if toggle:
            action.setCheckable(True)
            action.toggled.connect(lambda checked, f=function: f(self, toggle=checked))
        else:
            action.triggered.connect(lambda _, f=function: f(self))
        return action

    def num_actions(self) -> int:
        return len(self.actions())

    def remove_action(self, name: str):
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
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        # Sub-pixel align for crisp 1px stroke at any DPR
        rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        path = QtGui.QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)

        # Fill
        p.setBrush(QtGui.QColor(30, 30, 30, 240))
        # 1px cosmetic pen to keep edge sharp on HiDPI
        pen = QtGui.QPen(QtGui.QColor(255, 255, 255, 120))
        pen.setWidthF(1.0)
        pen.setCosmetic(True)
        pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)

        p.drawPath(path)
        super().paintEvent(ev)

    @staticmethod
    def _resolve_container_parent(parent: Optional[QtWidgets.QWidget]) -> Optional[QtWidgets.QWidget]:
        # Prefer a content container instead of QMainWindow for overlays
        if isinstance(parent, QtWidgets.QMainWindow):
            cw = parent.centralWidget()
            if isinstance(cw, QtWidgets.QMdiArea):
                return cw.viewport()
            return cw or parent
        return parent

    def add_action_widget(self,
                          action_name: str,
                          widget: QtWidgets.QWidget,
                          layout: Optional[QtWidgets.QLayout]) -> None:
        """Add a custom widget which spawns from clicking some action in the toolbar."""
        if action_name not in self.action_widgets:
            self.action_widgets[action_name] = {}

        # Re-parent to a safe content container (not QMainWindow)
        parent = self._resolve_container_parent(self.parentWidget())
        if parent is None:
            return

        widget.setParent(parent)

        # If a layout is provided, ensure it is owned by the widget (not QMainWindow)
        if layout is not None:
            if layout.parent() is not None and layout.parent() is not widget:
                layout.setParent(None)
            if widget.layout() is None:
                widget.setLayout(layout)

        # Find the tool button for the action
        def _find_toolbutton_for_action(act: Optional[QtGui.QAction]) -> Optional[QtWidgets.QToolButton]:
            if act is None:
                return None
            for btn in self.findChildren(QtWidgets.QToolButton):
                try:
                    if btn.defaultAction() is act:
                        return btn
                except Exception:
                    pass
            return None

        def position_widget():
            tb_global_tl = self.mapToGlobal(QtCore.QPoint(0, 0))
            act = self._find_action(action_name)
            btn = _find_toolbutton_for_action(act)

            # Use sizeHint to position even while hidden
            hint = widget.sizeHint()
            w_w, w_h = hint.width(), hint.height()

            if btn is None:
                print("Warning: Could not find tool button for action", action_name)

            if self.position == "left":
                x = tb_global_tl.x() - w_w - self._margin
                if btn is not None:
                    btn_tl = btn.mapToGlobal(QtCore.QPoint(0, 0))
                    y = btn_tl.y() + (btn.height() - w_h) // 2
                else:
                    y = tb_global_tl.y()
            elif self.position == "right":
                x = tb_global_tl.x() + self.width() + self._margin
                if btn is not None:
                    btn_tl = btn.mapToGlobal(QtCore.QPoint(0, 0))
                    y = btn_tl.y() + (btn.height() - w_h) // 2
                else:
                    y = tb_global_tl.y()
            elif self.position == "top":
                y = tb_global_tl.y() - w_h - self._margin
                if btn is not None:
                    btn_tl = btn.mapToGlobal(QtCore.QPoint(0, 0))
                    x = btn_tl.x() + (btn.width() - w_w) // 2
                else:
                    x = tb_global_tl.x()
            else:  # "bottom"
                y = tb_global_tl.y() + self.height() + self._margin
                if btn is not None:
                    btn_tl = btn.mapToGlobal(QtCore.QPoint(0, 0))
                    x = btn_tl.x() + (btn.width() - w_w) // 2
                else:
                    x = tb_global_tl.x()

            desired_global = QtCore.QPoint(x, y)
            desired_in_parent = parent.mapFromGlobal(desired_global)
            widget.move(desired_in_parent)
            widget.raise_()

        # Create and install position tracker
        tracker = self._make_position_tracker(position_widget)
        self.installEventFilter(tracker)
        parent.installEventFilter(tracker)
        if self.plot is not None:
            self.plot.installEventFilter(tracker)

        self.action_widgets[action_name]["widget"] = widget
        self.action_widgets[action_name]["layout"] = layout
        self.action_widgets[action_name]["tracker"] = tracker
        self.action_widgets[action_name]["position_fn"] = position_widget

        # Auto-bind to an action with the same name
        action = self._find_action(action_name)
        print(f"Auto-binding action widget '{action_name}' to toolbar action.")
        print(f"  Found action: {action}, isCheckable={action.isCheckable() if action else 'N/A'}")
        if action is not None:
            if action.isCheckable():
                print(f"Binding action widget '{action_name}' to toggle action.")
                print("Positioning widget on toggle.")
                action.toggled.connect(lambda checked: (widget.setVisible(checked), position_widget()))
                action.setChecked(False)  # Start hidden
            else:
                action.triggered.connect(lambda: (widget.setVisible(not widget.isVisible()), position_widget()))
                
        # this is a little buggy. This should cleaner but likely requires more robust Toolbar creating logic
        QtCore.QTimer.singleShot(1, position_widget)  # Initial placement delay to ensure correct position
        QtCore.QTimer.singleShot(3, position_widget)  # Initial placement delay to ensure correct position
        QtCore.QTimer.singleShot(5, position_widget)  # Initial placement delay to ensure correct position
        QtCore.QTimer.singleShot(10, position_widget)  # Initial placement delay to ensure correct position
        QtCore.QTimer.singleShot(20, position_widget)  # Initial placement delay to ensure correct position

    def _find_action(self, name: str) -> Optional[QtGui.QAction]:
        for a in self.actions():
            if a.text() == name:
                return a
        return None

    def moveEvent(self, event) -> None:
        super().moveEvent(event)

    def move_next_to_plot(self):
        """Place the toolbar next to the plot using global mapping."""
        if self.plot is None:
            return

        parent = self._resolve_container_parent(self.parentWidget())
        if parent is None:
            return

        plot_global_tl = self.plot.mapToGlobal(QtCore.QPoint(0, 0))

        if self.position == "left":
            desired_global = QtCore.QPoint(
                plot_global_tl.x() - self.width() - self._margin,
                plot_global_tl.y() + self._margin
            )
        elif self.position == "right":
            desired_global = QtCore.QPoint(
                plot_global_tl.x() + self.plot.width() + self._margin,
                plot_global_tl.y() + self._margin
            )
        elif self.position == "top":
            desired_global = QtCore.QPoint(
                plot_global_tl.x() + self._margin,
                plot_global_tl.y() - self.height() - self._margin
            )
        else:  # "bottom"
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

    @staticmethod
    def _make_position_tracker(callback: Callable[[], None]) -> QtCore.QObject:
        class _Tracker(QtCore.QObject):
            def eventFilter(self, obj, event):
                if event.type() in (QtCore.QEvent.Type.Move,
                                    QtCore.QEvent.Type.Resize,
                                    QtCore.QEvent.Type.Show):
                    QtCore.QTimer.singleShot(0, callback)
                return False
        return _Tracker()

    def _remove_event_filter_safe(self, tracker: QtCore.QObject) -> None:
        parent = self._resolve_container_parent(self.parentWidget())

        try:
            self.removeEventFilter(tracker)
        except Exception:
            pass
        if parent is not None:
            try:
                parent.removeEventFilter(tracker)
            except Exception:
                pass
        if self.plot is not None:
            try:
                self.plot.removeEventFilter(tracker)
            except Exception:
                pass

    def clear(self, /):
        """Clear all actions and associated widgets from the toolbar."""
        # Close action widgets and remove their event filters
        for data in list(self.action_widgets.values()):
            widget = data.get("widget")
            tracker = data.get("tracker")
            if tracker is not None:
                self._remove_event_filter_safe(tracker)

            if widget is not None:
                try:
                    widget.close()
                except Exception:
                    pass
                widget.deleteLater()

        self.action_widgets.clear()

        # Remove all actions
        for action in self.actions():
            self.removeAction(action)
        super().clear()

    def closeEvent(self, ev: QtGui.QCloseEvent) -> None:

        # Close action widgets and remove their event filters
        for data in list(self.action_widgets.values()):
            widget = data.get("widget")
            tracker = data.get("tracker")
            if tracker is not None:
                self._remove_event_filter_safe(tracker)

            if widget is not None:
                try:
                    widget.close()
                except Exception:
                    pass
                widget.deleteLater()

        self.action_widgets.clear()

        # Remove main position tracker
        tracker = getattr(self, "_position_tracker", None)
        if tracker is not None:
            self._remove_event_filter_safe(tracker)

        super().closeEvent(ev)


