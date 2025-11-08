# python
from typing import TYPE_CHECKING, Callable, Optional, Union

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

if TYPE_CHECKING:
    from spyde.drawing.multiplot import Plot


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
        self.layout_padding = (0, 0, 0, 0)  # left, top, right, bottom
        # Normalize position like "top-left" -> primary side
        def _normalize_position(pos: str) -> str:
            if not isinstance(pos, str):
                return "top"
            p = pos.lower()
            if "left" in p:
                return "left"
            if "right" in p:
                return "right"
            if "bottom" in p:
                return "bottom"
            return "top"

        norm_pos = _normalize_position(position)
        vertical = norm_pos not in ["top", "bottom"]
        self.position = norm_pos
        super().__init__(title, parent)

        self._radius = float(radius)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self.setContentsMargins(0, 0, 0, 0)
        self.plot = plot

        self.action_widgets: dict[str, dict] = {}

        # set up fixed style
        self.setOrientation(
            QtCore.Qt.Orientation.Vertical
            if vertical
            else QtCore.Qt.Orientation.Horizontal
        )

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
        if (
            container := self._resolve_container_parent(self.parentWidget())
        ) is not None:
            container.installEventFilter(self._position_tracker)
        if self.plot is not None:
            self.plot.installEventFilter(self._position_tracker)

    def add_action(
        self,
        name: str,
        icon_path: Union[str, QIcon],
        function: Callable,
        toggle: bool = False,
        parameters: dict = None,
        sub_functions: list = None,
    ) -> QtGui.QAction:
        """
        Add an action to the toolbar.
        """
        if parameters is None:
            parameters = dict()
        if sub_functions is None:
            sub_functions = []

        if isinstance(icon_path, str):
            icon_path = QIcon(icon_path)
        else:
            icon_path = icon_path
        action = self.addAction(icon_path, name)

        if (lay := self.layout()) is not None:
            lay.setContentsMargins(*self.layout_padding) # left, top, right, bottom
            lay.setSpacing(0)

        if parameters != {}:
            #  create a popout menu for the action with a submit button
            from spyde.drawing.toolbars.caret_group import CaretParams

            popout = CaretParams(
                title=name,
                parameters=parameters,
                function=function,
                toolbar=self,
                action_name=name,
                auto_attach=True,
            )
            # bind action to show the popout
            popout.hide()
            action.setCheckable(True)
            self.add_action_widget(name, popout, None)
            action.toggled.connect(
                lambda checked, w=popout: (w.show() if checked else w.hide())
            )
        elif sub_functions != []:
            popout_menu = PopoutToolBar(
                title=name,
                plot=None,
                parent=self._resolve_container_parent(self.parentWidget()),
                radius=int(self._radius),
                moveable=False,
                position=self.position,
            )
            popout_menu.setOrientation(
                QtCore.Qt.Orientation.Vertical
                if self.position in ("left", "right")
                else QtCore.Qt.Orientation.Horizontal
            )
            print(sub_functions)
            for sub in sub_functions:
                sub_function, sub_icon, sub_name, sub_toggle, sub_parameters = sub
                popout_menu.add_action(
                    sub_name,
                    sub_icon,
                    sub_function,
                    toggle=sub_toggle,
                    parameters=sub_parameters,
                )
            # Ensure the popout grows to fit its content (it starts empty)
            popout_menu.hide()
            self.add_action_widget(name, popout_menu, None)
            popout_menu.adjustSize()
            action.setCheckable(True)
            action.toggled.connect(
                lambda checked, w=popout_menu: (w.show() if checked else w.hide())
            )
        else:
            action.triggered.connect(
            lambda _, f=function, n=name: f(self, action_name=n)
        )
        if isinstance(self, PopoutToolBar):
            self.adjustSize()
        else:
            self.setFixedSize(self.sizeHint())
        if hasattr(self, "_reposition_function") and callable(self._reposition_function):
            self._reposition_function()
        return action

    def num_actions(self) -> int:
        return len(self.actions())

    def remove_action(self, name: str):
        for action in self.actions():
            if action.text() == name:
                self.removeAction(action)
                break
        # After removing, refresh size so content stays centered and inside edges
        if isinstance(self, PopoutToolBar):
            self.adjustSize()
        else:
            self.setFixedSize(self.sizeHint())

    def set_size(self):
        # Lock size so it doesn't change when moved
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed
        )
        size = self.sizeHint()
        self.setFixedSize(size)

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
    def _resolve_container_parent(
        parent: Optional[QtWidgets.QWidget],
    ) -> Optional[QtWidgets.QWidget]:
        # Prefer a content container instead of QMainWindow for overlays
        if isinstance(parent, QtWidgets.QMainWindow):
            cw = parent.centralWidget()
            if isinstance(cw, QtWidgets.QMdiArea):
                return cw.viewport()
            return cw or parent
        return parent

    def add_action_widget(
        self,
        action_name: str,
        widget: QtWidgets.QWidget,
        layout: Optional[QtWidgets.QLayout],
    ) -> None:
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
        def _find_toolbutton_for_action(
            act: Optional[QtGui.QAction],
        ) -> Optional[QtWidgets.QToolButton]:
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
            # caret must point toward the toolbar (opposite of anchor)
            def _opposite(side: str) -> str:
                return {"top": "bottom", "bottom": "top", "left": "right", "right": "left"}.get(side, "top")

            tb_global_tl = self.mapToGlobal(QtCore.QPoint(0, 0))
            act = self._find_action(action_name)
            btn = _find_toolbutton_for_action(act)

            hint = widget.sizeHint()
            w_w, w_h = hint.width(), hint.height()

            # Compute default anchor side from toolbar position (fallback => bottom)
            if self.position == "left":
                anchor = "left"
                x = tb_global_tl.x() - w_w - self._margin
                y = (btn.mapToGlobal(QtCore.QPoint(0, 0)).y() + (btn.height() - w_h) // 2) if btn else tb_global_tl.y()
            elif self.position == "right":
                anchor = "right"
                x = tb_global_tl.x() + self.width() + self._margin
                y = (btn.mapToGlobal(QtCore.QPoint(0, 0)).y() + (btn.height() - w_h) // 2) if btn else tb_global_tl.y()
            elif self.position == "top":
                anchor = "top"
                y = tb_global_tl.y() - w_h - self._margin
                x = (btn.mapToGlobal(QtCore.QPoint(0, 0)).x() + (btn.width() - w_w) // 2) if btn else tb_global_tl.x()
            else:
                anchor = "bottom"
                y = tb_global_tl.y() + self.height() + self._margin
                x = (btn.mapToGlobal(QtCore.QPoint(0, 0)).x() + (btn.width() - w_w) // 2) if btn else tb_global_tl.x()

            desired_global = QtCore.QPoint(x, y)
            desired_in_parent = parent.mapFromGlobal(desired_global)

            final_anchor = anchor  # track flips

            # Boundary-aware flip inside the MDI viewport
            pr = parent.rect()
            if anchor == "bottom" and (desired_in_parent.y() + w_h > pr.height()):
                # Flip to above toolbar
                y = tb_global_tl.y() - w_h - self._margin
                desired_in_parent.setY(parent.mapFromGlobal(QtCore.QPoint(0, y)).y())
                final_anchor = "top"
            elif anchor == "top" and desired_in_parent.y() < 0:
                # Flip to below toolbar
                y = tb_global_tl.y() + self.height() + self._margin
                desired_in_parent.setY(parent.mapFromGlobal(QtCore.QPoint(0, y)).y())
                final_anchor = "bottom"
            elif anchor == "left" and desired_in_parent.x() < 0:
                # Flip to right of toolbar
                x = tb_global_tl.x() + self.width() + self._margin
                desired_in_parent.setX(parent.mapFromGlobal(QtCore.QPoint(x, 0)).x())
                final_anchor = "right"
            elif anchor == "right" and (desired_in_parent.x() + w_w > pr.width()):
                # Flip to left of toolbar
                x = tb_global_tl.x() - w_w - self._margin
                desired_in_parent.setX(parent.mapFromGlobal(QtCore.QPoint(x, 0)).x())
                final_anchor = "left"

            # Clamp inside viewport to avoid drifting to sides
            clamped_x = max(0, min(desired_in_parent.x(), pr.width() - w_w))
            clamped_y = max(0, min(desired_in_parent.y(), pr.height() - w_h))
            desired_in_parent = QtCore.QPoint(clamped_x, clamped_y)

            # Caret should point toward the toolbar (opposite of where the widget is placed)
            if hasattr(widget, "set_side"):
                widget.set_side(_opposite(final_anchor))

            widget.move(desired_in_parent)
            widget.raise_()

        # Create and install position tracker
        widget._reposition_function = position_widget
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
        if action is not None:
            if action.isCheckable():
                action.toggled.connect(
                    lambda checked: (widget.setVisible(checked), position_widget())
                )
                action.setChecked(False)  # Start hidden
            else:
                action.triggered.connect(
                    lambda: (
                        widget.setVisible(not widget.isVisible()),
                        position_widget(),
                    )
                )

        # Initial placement (single, clean)
        QtCore.QTimer.singleShot(0, position_widget)

    def register_action_plot_item(self, action_name: str, item: QtWidgets.QGraphicsItem) -> None:
        """
        Register a plot graphics item (e.g., pyqtgraph ROI) with an action so that:
        - It is shown only when the action is toggled on.
        - It is cleaned up when the toolbar is cleared/closed.
        """
        if action_name not in self.action_widgets:
            self.action_widgets[action_name] = {}

        items = self.action_widgets[action_name].setdefault("plot_items", [])
        if item not in items:
            items.append(item)

        act = self._find_action(action_name)
        # Default to hidden unless the action is already checked.
        try:
            item.setVisible(bool(act.isChecked()) if (act and act.isCheckable()) else False)
        except Exception:
            pass

        if act is not None:
            if act.isCheckable():
                # Keep ROI visibility in sync with toggle state.
                act.toggled.connect(lambda checked, it=item: it.setVisible(checked))
            else:
                # For non-checkable, toggle visibility on click.
                act.triggered.connect(
                    lambda _, it=item: it.setVisible(not it.isVisible())
                )

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
                plot_global_tl.y() + self._margin,
            )
        elif self.position == "right":
            desired_global = QtCore.QPoint(
                plot_global_tl.x() + self.plot.width() + self._margin,
                plot_global_tl.y() + self._margin,
            )
        elif self.position == "top":
            desired_global = QtCore.QPoint(
                plot_global_tl.x() + self._margin,
                plot_global_tl.y() - self.height() - self._margin,
            )
        else:  # "bottom"
            desired_global = QtCore.QPoint(
                plot_global_tl.x() + self._margin,
                plot_global_tl.y() + self.plot.height() + self._margin,
            )

        desired_in_parent = parent.mapFromGlobal(desired_global)

        self._move_sync = True
        try:
            self.move(desired_in_parent)
            self.raise_()
        finally:
            self._move_sync = False

        # Reposition any open widgets
        for data in self.action_widgets.values():
            fn = data.get("position_fn")
            w = data.get("widget")
            if callable(fn) and w is not None and w.isVisible():
                QtCore.QTimer.singleShot(0, fn)

    @staticmethod
    def _make_position_tracker(callback: Callable[[], None]) -> QtCore.QObject:
        class _Tracker(QtCore.QObject):
            def eventFilter(self, obj, event):
                if event.type() in (
                    QtCore.QEvent.Type.Move,
                    QtCore.QEvent.Type.Resize,
                    QtCore.QEvent.Type.Show,
                ):
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

    def showEvent(self, ev: QtGui.QShowEvent) -> None:
        super().showEvent(ev)
        # Resync popouts and plot items when toolbar reappears
        for name, data in self.action_widgets.items():
            act = self._find_action(name)
            widget = data.get("widget")
            fn = data.get("position_fn")
            if widget is not None and act is not None and act.isCheckable():
                widget.setVisible(act.isChecked())
                if callable(fn) and widget.isVisible():
                    QtCore.QTimer.singleShot(0, fn)
            for item in data.get("plot_items", []) or []:
                try:
                    if act is not None and act.isCheckable():
                        item.setVisible(act.isChecked())
                except Exception:
                    pass

    def hideEvent(self, ev: QtGui.QHideEvent) -> None:
        # Hide popouts and plot items with the toolbar
        for data in self.action_widgets.values():
            widget = data.get("widget")
            if widget is not None:
                widget.hide()
            for item in data.get("plot_items", []) or []:
                try:
                    item.setVisible(False)
                except Exception:
                    pass
        super().hideEvent(ev)

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

            # Remove any registered plot items (e.g., ROIs) from the plot
            for item in list(data.get("plot_items", []) or []):
                try:
                    if self.plot is not None and hasattr(self.plot, "plot_item"):
                        self.plot.plot_item.removeItem(item)
                except Exception:
                    pass
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

            # Remove any registered plot items (e.g., ROIs) from the plot
            for item in list(data.get("plot_items", []) or []):
                try:
                    if self.plot is not None and hasattr(self.plot, "plot_item"):
                        self.plot.plot_item.removeItem(item)
                except Exception:
                    pass

        self.action_widgets.clear()

        # Remove main position tracker
        tracker = getattr(self, "_position_tracker", None)
        if tracker is not None:
            self._remove_event_filter_safe(tracker)

        super().closeEvent(ev)

    # New: convenience to create a caret-style subtoolbar as a popout for an action
    def create_subtoolbar(
        self,
        action_name: str,
        title: str = "",
        *,
        side: str = "auto",
        orientation: Optional[Qt.Orientation] = None,
        caret_base: int = 14,
        caret_depth: int = 8,
        padding: int = 8,
    ) -> "PopoutToolBar":
        """
        Create a caret-style subtoolbar shown as a popout for the given action.

        Returns the PopoutToolBar so callers can add actions to it.
        """
        parent = self._resolve_container_parent(self.parentWidget())
        # Orientation defaults to horizontal for top/bottom, vertical for left/right
        if orientation is None:
            orientation = (
                Qt.Orientation.Vertical
                if self.position in ("left", "right")
                else Qt.Orientation.Horizontal
            )
        sub = PopoutToolBar(
            title=title or action_name,
            plot=None,              # free-floating; add_action_widget handles positioning
            parent=parent,
            radius=int(self._radius),
            moveable=False,
            position=self.position,  # used for default orientation only; not auto-positioned
            side=side,
            caret_base=caret_base,
            caret_depth=caret_depth,
            padding=padding,
        )
        sub.setOrientation(orientation)
        sub.hide()
        # Register with the same mechanism as any widget
        self.add_action_widget(action_name, sub, None)
        return sub


class PopoutToolBar(RoundedToolBar):
    """
    A floating RoundedToolBar with a caret tip, intended to be used as a popout anchored to a parent toolbar action.
    It shares the same style as RoundedToolBar but draws a caret and reserves space for it, like CaretGroup.
    """

    def __init__(
        self,
        title: str,
        plot: "Plot" = None,
        parent: Optional[QtWidgets.QWidget] = None,
        radius: int = 8,
        moveable: bool = False,
        position: str = "bottom",
        reposition_function: Optional[Callable[[], None]] = None,
        *,
        side: str = "auto",
        caret_base: int = 14,
        caret_depth: int = 8,
        padding: int = 8,
    ):



        # Popout does not need plot tracking; pass plot=None to avoid auto-placement
        self._side = side if side in ("top", "bottom", "left", "right", "auto") else "auto"
        self._caret_base = int(caret_base)
        self._caret_depth = int(caret_depth)
        self._padding = int(0)
        self._reposition_function = reposition_function


        super().__init__(title, plot=None, parent=parent, radius=radius, moveable=moveable, position=position)
        # Visual params for caret bubble
        self._pen_color = QtGui.QColor(255, 255, 255, 120)
        self._bg_color = QtGui.QColor(30, 30, 30, 240)
        # Transparent background; we fully paint our bubble

        top_margin = 2 + self._caret_depth
        self.setStyleSheet(
            f"QToolBar {{"
            "  background: transparent;"
            "  border: none;"
            "  padding: 4px;"
            "  margin: 0px;"
            "}"
            f"QToolButton {{"
            "  border: none;"
            f"  margin: {top_margin}px 2px 2px 2px;"
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

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # Allow dynamic growth; RoundedToolBar.__init__ fixed the size – undo that here.
        self._unlock_fixed_size()
        self._margin = 1
        self.layout_padding = (self._padding, self._padding, self._padding, self._padding)  # left, top, right, bottom

    def _unlock_fixed_size(self):
        # Remove fixed-size constraints introduced by RoundedToolBar.set_size()
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Preferred)
        self.setMinimumSize(0, 18)  # minimum height to fit buttons
        self.setMaximumSize(16777215, 16777215)

    # Ensure subtoolbars grow to fit their actions (don't lock to fixed size)
    def _refresh_fixed_size(self):
        self.adjustSize()

    # Optional helper if caller updates content later
    def content_updated(self):
        self.adjustSize()
        self.update()

    def set_side(self, side: str):
        if side not in ("top", "bottom", "left", "right"):
            return
        if self._side != side:
            self._side = side
            #self._update_margins()
            self.update()

    def sizeHint(self) -> QtCore.QSize:
        """
        Size hint shouldn't account for caret space.
        """
        s = super().sizeHint()
        if self._side in ("top", "bottom"):
            return QtCore.QSize(s.width(), s.height())
        return QtCore.QSize(s.width(), s.height())

    def _update_margins(self):
        l = r = t = b = self._padding
        if self._side == "top":
            t += self._caret_depth
        elif self._side == "bottom":
            b += self._caret_depth
        elif self._side == "left":
            l += self._caret_depth
        elif self._side == "right":
            r += self._caret_depth
        self.setContentsMargins(l, t, r, b)

    def _bubble_rect(self) -> QtCore.QRectF:
        rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self._side == "top":
            rect.adjust(0, self._caret_depth, 0, 0)
        elif self._side == "bottom":
            rect.adjust(0, 0, 0, -self._caret_depth)
        elif self._side == "left":
            rect.adjust(self._caret_depth, 0, 0, 0)
        elif self._side == "right":
            rect.adjust(0, 0, -self._caret_depth, 0)
        return rect

    def _caret_polygon(self, bubble: QtCore.QRectF) -> QtGui.QPolygonF:
        base = float(self._caret_base)
        depth = float(self._caret_depth)
        if self._side in ("top", "bottom"):
            cx = bubble.center().x()
            x1 = cx - base / 2.0
            x2 = cx + base / 2.0
            if self._side == "top":
                y = bubble.top()
                return QtGui.QPolygonF([QtCore.QPointF(x1, y), QtCore.QPointF(x2, y), QtCore.QPointF(cx, y - depth)])
            else:
                y = bubble.bottom()
                return QtGui.QPolygonF([QtCore.QPointF(x1, y), QtCore.QPointF(x2, y), QtCore.QPointF(cx, y + depth)])
        else:
            cy = bubble.center().y()
            y1 = cy - base / 2.0
            y2 = cy + base / 2.0
            if self._side == "left":
                x = bubble.left()
                return QtGui.QPolygonF([QtCore.QPointF(x, y1), QtCore.QPointF(x, y2), QtCore.QPointF(x - depth, cy)])
            else:
                x = bubble.right()
                return QtGui.QPolygonF([QtCore.QPointF(x, y1), QtCore.QPointF(x, y2), QtCore.QPointF(x + depth, cy)])

    def paintEvent(self, ev: QtGui.QPaintEvent) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        bubble = self._bubble_rect()

        bubble_path = QtGui.QPainterPath()
        bubble_path.addRoundedRect(bubble, self._radius, self._radius)

        caret_poly = self._caret_polygon(bubble)
        caret_path = QtGui.QPainterPath()
        caret_path.addPolygon(caret_poly)

        # simplify paths to eliminate seam between bubble and caret
        bubble_path.addPath(caret_path)
        path = bubble_path.simplified()

        p.setBrush(self._bg_color)
        pen = QtGui.QPen(self._pen_color)
        pen.setWidthF(1.0)
        pen.setCosmetic(True)
        pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPath(path)
        # Paint actions/toolbuttons
        QtWidgets.QToolBar.paintEvent(self, ev)
