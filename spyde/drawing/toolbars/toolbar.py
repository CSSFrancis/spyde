from __future__ import annotations
from typing import TYPE_CHECKING, Callable, Optional, Union, Tuple

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon


if TYPE_CHECKING:
    from spyde.drawing.toolbars.caret_group import CaretParams
    from spyde.drawing.toolbars.popout_toolbar import PopoutToolBar
from spyde.drawing.toolbars.stylized_toolbar import StylizedToolBar

from spyde.drawing.toolbars.utils import (_finalize_popout_layout,
                                          _center_vertically,
                                          _center_horizontally,
                                          _configure_widget_layout,
                                          _sync_plot_items_visibility,
                                          _opposite_side,_bind_action_to_plot_item,
                                          _set_initial_item_visibility,
                                          )

class RoundedToolBar(StylizedToolBar):
    """
    A QToolBar with rounded corners and a semi-transparent background.

    This toolbar is designed to be used alongside a Plot widget, allowing for floating
    tools around some plot area. ("top", "bottom", "left", "right")

    Parameters
    ----------
    title : str
        The title of the toolbar.
    plot : Plot, optional
        The associated Plot widget to position the toolbar next to.
    parent : QWidget, optional
        The parent widget.
    radius : int, optional
        The corner radius for the rounded corners. Default is 8.
    moveable : bool, optional
        Whether the toolbar is moveable by the user. Default is False.
    position : str, optional
        The position of the toolbar relative to the plot ("top", "bottom", "left", "right").
        Default is "top".
    """

    # ========== Action Management ==========

    def add_action(
            self,
            name: str,
            icon_path: Union[str, QIcon],
            function: Callable,
            toggle: bool = False,
            parameters: Optional[dict] = None,
            sub_functions: Optional[list] = None,
    ) -> Tuple[QtGui.QAction, Optional[Union["CaretParams", "PopoutToolBar"]]]:
        """Create a QAction, attach optional popout (CaretParams or PopoutToolBar), wire visibility, and size-adjust."""
        parameters = parameters or {}
        sub_functions = sub_functions or []

        icon = QIcon(icon_path) if isinstance(icon_path, str) else icon_path
        action = self.addAction(icon, name)
        self._configure_layout()

        action_widget = None
        if parameters:
            action_widget = self._create_parameter_popout(name, parameters, function, action)
        elif sub_functions:
            action_widget = self._create_submenu_popout(name, sub_functions, action)
        else:
            self._configure_plain_action(action, function, name, toggle)

        self._finalize_action_creation()
        return action, action_widget

    def _configure_layout(self) -> None:
        """Configure toolbar layout margins and spacing."""
        if (lay := self.layout()) is not None:
            lay.setContentsMargins(*self.layout_padding)
            lay.setSpacing(0)

    def _create_parameter_popout(
            self, name: str, parameters: dict, function: Callable, action: QtGui.QAction
    ) -> "CaretParams":
        """Create a CaretParams popout widget for an action with parameters."""
        from spyde.drawing.toolbars.caret_group import CaretParams

        popout = CaretParams(
            title=name,
            parameters=parameters,
            function=function,
            toolbar=self,
            action_name=name,
            auto_attach=True,
        )
        _finalize_popout_layout(popout)
        popout.hide()

        action.setCheckable(True)
        self._connect_exclusive_action(action)
        self.add_action_widget(name, popout, None)
        action.toggled.connect(lambda checked, w=popout: w.setVisible(checked))

        return popout

    def _create_submenu_popout(
            self, name: str, sub_functions: list, action: QtGui.QAction
    ) -> "PopoutToolBar":
        """Create a PopoutToolBar submenu for an action with sub-functions."""
        from spyde.drawing.toolbars.popout_toolbar import PopoutToolBar

        popout_menu = PopoutToolBar(
            title=name,
            plot=None,
            parent=self._resolve_container_parent(self.parentWidget()),
            radius=int(self._radius),
            moveable=False,
            position=self.position,
            parent_toolbar=self,
        )
        popout_menu.setOrientation(
            QtCore.Qt.Orientation.Vertical
            if self.position in ("left", "right")
            else QtCore.Qt.Orientation.Horizontal
        )

        for sub in sub_functions:
            sub_function, sub_icon, sub_name, sub_toggle, sub_parameters = sub
            popout_menu.add_action(
                sub_name, sub_icon, sub_function, toggle=sub_toggle, parameters=sub_parameters
            )

        popout_menu.hide()
        self.add_action_widget(name, popout_menu, None)
        popout_menu.adjustSize()

        action.setCheckable(True)
        self._connect_exclusive_action(action)

        return popout_menu

    def _configure_plain_action(
            self, action: QtGui.QAction, function: Callable, name: str, toggle: bool
    ) -> None:
        """Configure a plain action without popouts."""
        if toggle:
            action.setCheckable(True)
            self._connect_exclusive_action(action)
        action.triggered.connect(lambda _, f=function, n=name: f(self, action_name=n))

    def _connect_exclusive_action(self, action: QtGui.QAction) -> None:
        """Connect exclusive action handler if enabled."""
        if self.exclusive_checkable_actions:
            action.toggled.connect(
                lambda checked, a=action: self._enforce_exclusive_checked(a, checked)
            )

    def _finalize_action_creation(self) -> None:
        """Adjust toolbar size and reposition after adding an action."""
        from spyde.drawing.toolbars.popout_toolbar import PopoutToolBar

        if isinstance(self, PopoutToolBar):
            self.adjustSize()
        else:
            self.setFixedSize(self.sizeHint())

        if hasattr(self, "_reposition_function") and callable(self._reposition_function):
            self._reposition_function()

    def _enforce_exclusive_checked(self, action: QtGui.QAction, checked: bool) -> None:
        """Ensure only one checkable action on this toolbar is checked at a time."""
        if not checked:
            return

        for other in self.actions():
            if other is action:
                continue
            if other.isCheckable() and other.isChecked():
                other.trigger()

    def num_actions(self) -> int:
        """Return the number of actions currently in the toolbar."""
        return len(self.actions())

    def remove_action(self, name: str) -> None:
        """Remove a QAction by its text label and refresh toolbar size."""
        for action in self.actions():
            if action.text() == name:
                self.removeAction(action)
                break

        self._finalize_action_creation()

    def _find_action(self, name: str) -> Optional[QtGui.QAction]:
        """Locate an existing QAction by its text label."""
        for action in self.actions():
            if action.text() == name:
                return action
        return None

    # ========== Widget Positioning ==========

    def add_action_widget(
            self,
            action_name: str,
            widget: QtWidgets.QWidget,
            layout: Optional[QtWidgets.QLayout],
    ) -> None:
        """Register a floating widget (callout) for an action and install dynamic edge-aware positioning."""
        if action_name not in self.action_widgets:
            self.action_widgets[action_name] = {}

        parent = self._resolve_container_parent(self.parentWidget())
        if parent is None:
            return

        widget.setParent(parent)
        _configure_widget_layout(widget, layout)

        position_fn = self._create_position_function(widget, action_name, parent)
        tracker = self._make_position_tracker(position_fn)

        self._install_position_tracker(tracker, parent)
        self._store_action_widget_data(action_name, widget, layout, tracker, position_fn)
        self._bind_action_to_widget(action_name, widget, position_fn)

        QtCore.QTimer.singleShot(0, position_fn)

    def _create_position_function(
            self, widget: QtWidgets.QWidget, action_name: str, parent: QtWidgets.QWidget
    ) -> Callable:
        """Create a position function for the widget."""

        def position_widget():
            _finalize_popout_layout(widget)

            act = self._find_action(action_name)
            btn = self._find_toolbutton_for_action(act)

            anchor, pos = self._compute_widget_position(widget, btn)
            final_anchor, final_pos = self._adjust_for_boundaries(widget, pos, anchor, parent)

            if hasattr(widget, "set_side"):
                widget.set_side(_opposite_side(final_anchor))

            widget.move(final_pos)
            widget.raise_()

        return position_widget

    def _find_toolbutton_for_action(
            self, action: Optional[QtGui.QAction]
    ) -> Optional[QtWidgets.QToolButton]:
        """Find the QToolButton associated with an action."""
        if action is None:
            return None

        for btn in self.findChildren(QtWidgets.QToolButton):
            try:
                if btn.defaultAction() is action:
                    return btn
            except Exception:
                pass
        return None

    def _compute_widget_position(
            self, widget: QtWidgets.QWidget, btn: Optional[QtWidgets.QToolButton]
    ) -> Tuple[str, QtCore.QPoint]:
        """Compute the initial position and anchor side for a widget."""
        tb_global_tl = self.mapToGlobal(QtCore.QPoint(0, 0))
        hint = widget.sizeHint()
        w_w, w_h = hint.width(), hint.height()

        if self.position == "left":
            anchor = "left"
            x = tb_global_tl.x() - w_w - self._margin
            y = _center_vertically(btn, tb_global_tl.y(), w_h)
        elif self.position == "right":
            anchor = "right"
            x = tb_global_tl.x() + self.width() + self._margin
            y = _center_vertically(btn, tb_global_tl.y(), w_h)
        elif self.position == "top":
            anchor = "top"
            y = tb_global_tl.y() - w_h - self._margin
            x = _center_horizontally(btn, tb_global_tl.x(), w_w)
        else:  # bottom
            anchor = "bottom"
            y = tb_global_tl.y() + self.height() + self._margin
            x = _center_horizontally(btn, tb_global_tl.x(), w_w)

        return anchor, QtCore.QPoint(x, y)

    def _adjust_for_boundaries(
            self,
            widget: QtWidgets.QWidget,
            pos: QtCore.QPoint,
            anchor: str,
            parent: QtWidgets.QWidget,
    ) -> Tuple[str, QtCore.QPoint]:
        """Adjust widget position to stay within parent boundaries."""
        tb_global_tl = self.mapToGlobal(QtCore.QPoint(0, 0))
        hint = widget.sizeHint()
        w_w, w_h = hint.width(), hint.height()

        pos_in_parent = parent.mapFromGlobal(pos)
        final_anchor = anchor
        pr = parent.rect()

        # Flip if out of bounds
        if anchor == "bottom" and (pos_in_parent.y() + w_h > pr.height()):
            pos.setY(tb_global_tl.y() - w_h - self._margin)
            final_anchor = "top"
        elif anchor == "top" and pos_in_parent.y() < 0:
            pos.setY(tb_global_tl.y() + self.height() + self._margin)
            final_anchor = "bottom"
        elif anchor == "left" and pos_in_parent.x() < 0:
            pos.setX(tb_global_tl.x() + self.width() + self._margin)
            final_anchor = "right"
        elif anchor == "right" and (pos_in_parent.x() + w_w > pr.width()):
            pos.setX(tb_global_tl.x() - w_w - self._margin)
            final_anchor = "left"

        # Clamp to viewport
        pos_in_parent = parent.mapFromGlobal(pos)
        clamped_x = max(0, min(pos_in_parent.x(), pr.width() - w_w))
        clamped_y = max(0, min(pos_in_parent.y(), pr.height() - w_h))

        return final_anchor, QtCore.QPoint(clamped_x, clamped_y)

    def _install_position_tracker(
            self, tracker: QtCore.QObject, parent: QtWidgets.QWidget
    ) -> None:
        """Install position tracker event filter."""
        self.installEventFilter(tracker)
        parent.installEventFilter(tracker)
        if self.plot_window is not None:
            self.plot_window.installEventFilter(tracker)

    def _store_action_widget_data(
            self,
            action_name: str,
            widget: QtWidgets.QWidget,
            layout: Optional[QtWidgets.QLayout],
            tracker: QtCore.QObject,
            position_fn: Callable,
    ) -> None:
        """Store widget data in action_widgets dictionary."""
        widget._reposition_function = position_fn
        self.action_widgets[action_name]["widget"] = widget
        self.action_widgets[action_name]["layout"] = layout
        self.action_widgets[action_name]["tracker"] = tracker
        self.action_widgets[action_name]["position_fn"] = position_fn

    def _bind_action_to_widget(
            self, action_name: str, widget: QtWidgets.QWidget, position_fn: Callable
    ) -> None:
        """Bind action toggle/trigger to widget visibility."""
        action = self._find_action(action_name)
        if action is None:
            return

        if action.isCheckable():
            action.toggled.connect(
                lambda checked: (widget.setVisible(checked), position_fn())
            )
            action.setChecked(False)
        else:
            action.triggered.connect(
                lambda: (widget.setVisible(not widget.isVisible()), position_fn())
            )

    # ========== Plot Item Management ==========

    def register_action_plot_item(
            self, action_name: str, item: QtWidgets.QGraphicsItem, key: Optional[str] = None
    ) -> None:
        """Associate a QGraphicsItem with an action; auto-hide/show based on toggle state."""
        self.plot.addItem(item)

        if action_name not in self.action_widgets:
            self.action_widgets[action_name] = {}
        if "plot_items" not in self.action_widgets[action_name]:
            self.action_widgets[action_name]["plot_items"] = {}

        key = key or f"item_{len(self.action_widgets[action_name]['plot_items'])}"
        self.action_widgets[action_name]["plot_items"][key] = item

        act = self._find_action(action_name)
        _set_initial_item_visibility(item, act)
        _bind_action_to_plot_item(act, item)

    def unregister_action_plot_item(self, action_name: str, key: str) -> None:
        """Deregister all QGraphicsItems associated with an action."""
        if (
                action_name in self.action_widgets
                and "plot_items" in self.action_widgets[action_name]
                and key in self.action_widgets[action_name]["plot_items"]
        ):
            item = self.action_widgets[action_name]["plot_items"].pop(key)
            try:
                if self.plot_window is not None and hasattr(self.plot_state, "plot_item"):
                    self.plot.removeItem(item)
            except Exception:
                pass
            return item

    # ========== Plot Window Management ==========
    def register_action_plot_window(self, action_name: str,
                                    plot_window: QtWidgets.QWidget,
                                    key: Optional[str] = None) -> None:
        """Associate a plot window with an action; auto-hide/show based on toggle state."""
        if action_name not in self.action_widgets:
            self.action_widgets[action_name] = {}
        if "plot_windows" not in self.action_widgets[action_name]:
            self.action_widgets[action_name]["plot_windows"] = {}
        key = key or f"plot_{len(self.action_widgets[action_name]['plot_windows'])}"
        self.action_widgets[action_name]["plot_windows"][key] = plot_window

        act = self._find_action(action_name)
        _set_initial_item_visibility(plot_window, act)
        _bind_action_to_plot_item(act, plot_window)

    def unregister_action_plot_window(self, action_name: str) -> None:
        """Deregister the plot window associated with an action."""
        if (
                action_name in self.action_widgets
                and "plot_window" in self.action_widgets[action_name]
        ):
            window = self.action_widgets[action_name].pop("plot_window")
            try:
                window.close()
            except Exception:
                pass
            return window
    # ========== Event Handling ==========

    def showEvent(self, ev: QtGui.QShowEvent) -> None:
        super().showEvent(ev)
        self._sync_widget_visibility()

    def _sync_widget_visibility(self) -> None:
        """Sync popout and plot item visibility when toolbar is shown."""
        for name, data in self.action_widgets.items():
            act = self._find_action(name)
            widget = data.get("widget")
            position_fn = data.get("position_fn")

            if widget and act and act.isCheckable():
                widget.setVisible(act.isChecked())
                if callable(position_fn) and widget.isVisible():
                    QtCore.QTimer.singleShot(0, position_fn)

            _sync_plot_items_visibility(act, data)

    def hideEvent(self, ev: QtGui.QHideEvent) -> None:
        """Hide all associated popouts and plot items when the toolbar is hidden."""
        self._hide_all_widgets()
        super().hideEvent(ev)

    def _hide_all_widgets(self) -> None:
        """Hide all action widgets and plot items."""
        for data in self.action_widgets.values():
            widget = data.get("widget")
            if widget:
                widget.hide()

            for item in data.get("plot_items", {}).values():
                try:
                    item.setVisible(False)
                except Exception:
                    pass

    # ========== Cleanup ==========

    def clear(self) -> None:
        """Remove all actions, popouts, and associated plot items; detach event filters safely."""
        self._cleanup_action_widgets()
        self.action_widgets.clear()

        for action in self.actions():
            self.removeAction(action)

        super().clear()

    def closeEvent(self, ev: QtGui.QCloseEvent) -> None:
        """Clean up all associated widgets and event filters when the toolbar is closed."""
        self._cleanup_action_widgets()
        self.action_widgets.clear()

        tracker = getattr(self, "_position_tracker", None)
        if tracker:
            self._remove_event_filter_safe(tracker)

        super().closeEvent(ev)

    def _cleanup_action_widgets(self) -> None:
        """Clean up all action widgets, trackers, and plot items."""
        for data in list(self.action_widgets.values()):
            self._cleanup_widget(data.get("widget"), data.get("tracker"))
            self._cleanup_plot_items(data.get("plot_items", {}))

    def _cleanup_widget(
            self, widget: Optional[QtWidgets.QWidget], tracker: Optional[QtCore.QObject]
    ) -> None:
        """Clean up a single widget and its tracker."""
        if tracker:
            self._remove_event_filter_safe(tracker)

        if widget:
            try:
                widget.close()
            except Exception:
                pass
            widget.deleteLater()

    def _cleanup_plot_items(self, plot_items: dict) -> None:
        """Remove all plot items from the plot."""
        for item in plot_items.values():
            try:
                if self.plot and hasattr(self.plot, "plot_item"):
                    self.plot.plot_item.removeItem(item)
            except Exception:
                pass

    # ========== Utility Methods ==========

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
        """Instantiate and register a caret-style PopoutToolBar as the popout for the given action."""
        from spyde.drawing.toolbars.popout_toolbar import PopoutToolBar

        parent = self._resolve_container_parent(self.parentWidget())

        if orientation is None:
            orientation = (
                Qt.Orientation.Vertical
                if self.position in ("left", "right")
                else Qt.Orientation.Horizontal
            )

        sub = PopoutToolBar(
            title=title or action_name,
            plot=None,
            parent=parent,
            radius=int(self._radius),
            moveable=False,
            position=self.position,
            side=side,
            caret_base=caret_base,
            caret_depth=caret_depth,
            padding=padding,
            parent_toolbar=self,
        )
        sub.setOrientation(orientation)
        sub.hide()

        self.add_action_widget(action_name, sub, None)
        return sub

