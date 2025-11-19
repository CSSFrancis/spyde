from __future__ import annotations
from typing import Callable, Iterable, List, Optional
import os
from PySide6 import QtWidgets, QtCore
from PySide6.QtTest import QTest

from spyde.main_window import MainWindow

# Registry for windows the gallery scraper should capture
_SG_QT_WINDOWS: List[QtWidgets.QWidget] = []


def ensure_app() -> QtWidgets.QApplication:
    app = QtWidgets.QApplication.instance()
    return app or QtWidgets.QApplication([])


def wait_until(
    predicate: Callable[[], bool], timeout: int = 5000, interval: int = 50
) -> None:
    """Minimal waitUntil usable without pytest-qt."""
    deadline = QtCore.QDeadlineTimer(timeout)
    while not predicate():
        QtWidgets.QApplication.processEvents()
        QTest.qWait(interval)
        if deadline.hasExpired():
            raise TimeoutError("wait_until timed out")


def open_window() -> MainWindow:
    """Open the MainWindow, optionally registering it with pytest-qt."""
    app = ensure_app()
    win = MainWindow(app=app)
    win.show()
    QTest.qWaitForWindowExposed(win)
    return win


def _find_menu_action(menu_or_bar, action_name: str):
    if (
        hasattr(menu_or_bar, "menu")
        and callable(getattr(menu_or_bar, "menu"))
        and not hasattr(menu_or_bar, "actions")
    ):
        menu_or_bar = menu_or_bar.menu()
    if menu_or_bar is None or not hasattr(menu_or_bar, "actions"):
        return None
    for action in menu_or_bar.actions():
        text = (action.text() or "").lower()
        if action_name.lower() in text:
            return action
    return None


def create_data(win: MainWindow, signal_type: str) -> None:
    """Trigger File -> Create Data, select tab by name, accept dialog, and wait for subwindows."""
    menubar = win.menuBar()
    assert menubar is not None, "Menu bar not found"
    file_menu_action = _find_menu_action(menubar, "File")
    assert file_menu_action is not None, "File menu not found"
    create_data_action = _find_menu_action(file_menu_action, "Create Data")
    assert create_data_action is not None, "'Create Data' action not found"

    def _accept_dialog():
        app = QtWidgets.QApplication.instance()
        for w in app.topLevelWidgets():
            if isinstance(w, QtWidgets.QDialog) and w.isVisible():
                try:
                    tabs = w.findChild(QtWidgets.QTabWidget)
                    if tabs and signal_type:
                        target = (signal_type or "").strip().lower()
                        for i in range(tabs.count()):
                            label = (tabs.tabText(i) or "").strip().lower()
                            if label == target or label.startswith(target):
                                tabs.setCurrentIndex(i)
                                app.processEvents()
                                QTest.qWait(50)
                                break
                except Exception:
                    pass
                box = w.findChild(QtWidgets.QDialogButtonBox)
                if box:
                    ok_btn = box.button(QtWidgets.QDialogButtonBox.Ok)
                    if ok_btn and ok_btn.isEnabled():
                        ok_btn.click()
                        return
                w.accept()
                return

    QtCore.QTimer.singleShot(0, create_data_action.trigger)
    QtCore.QTimer.singleShot(100, _accept_dialog)

    # Wait until at least one subwindow appears
    wait_until(lambda: len(getattr(win, "mdi_area").subWindowList()) > 0, timeout=10000)


def register_window_for_gallery(widget: QtWidgets.QWidget) -> None:
    """Register a window for the Sphinx-Gallery scraper."""
    if widget not in _SG_QT_WINDOWS:
        _SG_QT_WINDOWS.append(widget)


def clear_registered_windows() -> None:
    _SG_QT_WINDOWS.clear()


def iter_registered_windows() -> Iterable[QtWidgets.QWidget]:
    """Windows explicitly registered for screenshots."""
    return list(_SG_QT_WINDOWS)


def grab_and_save(widget: QtWidgets.QWidget, path: str) -> str:
    """Grab a widget and save as PNG."""
    pixmap = widget.grab()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pixmap.save(path, "PNG")
    return path
