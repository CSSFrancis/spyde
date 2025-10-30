# python
import pytest
from typing import Dict, Any
from PySide6 import QtWidgets, QtCore
from PySide6.QtTest import QTest

from despy.main_window import MainWindow


def _find_menu_action(menu_or_bar, action_name: str):
    # Normalize: if a QAction with a submenu, use its QMenu
    if hasattr(menu_or_bar, "menu") and callable(getattr(menu_or_bar, "menu")) and not hasattr(menu_or_bar, "actions"):
        menu_or_bar = menu_or_bar.menu()
    if menu_or_bar is None or not hasattr(menu_or_bar, "actions"):
        return None
    for action in menu_or_bar.actions():
        if action_name.lower() in (action.text() or "").lower():
            return action
    return None


def _create_data(win: MainWindow, qtbot, signal_type: str) -> None:
    menubar = win.menuBar()
    assert menubar is not None, "Menu bar not found"

    file_menu_action = _find_menu_action(menubar, "File")
    assert file_menu_action is not None, "File menu not found"

    create_data_action = _find_menu_action(file_menu_action, "Create Data")
    assert create_data_action is not None, "'Create Data' action not found"

    def _accept_dialog(signal_type=signal_type):
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

    # Trigger the action and accept the dialog
    QtCore.QTimer.singleShot(0, create_data_action.trigger)
    QtCore.QTimer.singleShot(100, _accept_dialog)

    # Wait for subwindows to appear
    qtbot.waitUntil(lambda: len(getattr(win, "mdi_area").subWindowList()) > 0, timeout=5000)


def _open_window(qtbot) -> MainWindow:
    app = QtWidgets.QApplication.instance()
    win = MainWindow(app=app)
    qtbot.addWidget(win)
    win.show()
    QTest.qWaitForWindowExposed(win)
    return win

@pytest.fixture()
def tem_2d_dataset(qtbot) -> Dict[str, Any]:
    win = _open_window(qtbot)
    try:
        _create_data(win, qtbot, "Image")
        # Expect two subwindows for Insitu TEM
        qtbot.waitUntil(lambda: len(win.mdi_area.subWindowList()) == 1, timeout=5000)
        return {
            "window": win,
            "mdi_area": win.mdi_area,
            "subwindows": win.mdi_area.subWindowList(),
            "signal_trees": getattr(win, "signal_trees", []),
        }
    finally:
        # Do not close here to allow the test to inspect; caller can close if needed
        pass

@pytest.fixture
def insitu_tem_2d_dataset(qtbot) -> Dict[str, Any]:
    win = _open_window(qtbot)
    try:
        _create_data(win, qtbot, "Insitu TEM")
        # Expect two subwindows for Insitu TEM
        qtbot.waitUntil(lambda: len(win.mdi_area.subWindowList()) == 2, timeout=5000)
        return {
            "window": win,
            "mdi_area": win.mdi_area,
            "subwindows": win.mdi_area.subWindowList(),
            "signal_trees": getattr(win, "signal_trees", []),
        }
    finally:
        # Do not close here to allow the test to inspect; caller can close if needed
        pass


@pytest.fixture
def stem_4d_dataset(qtbot) -> Dict[str, Any]:
    win = _open_window(qtbot)
    try:
        _create_data(win, qtbot, "4D STEM")
        # Expect two subwindows for 4D STEM
        qtbot.waitUntil(lambda: len(win.mdi_area.subWindowList()) == 2, timeout=5000)
        return {
            "window": win,
            "mdi_area": win.mdi_area,
            "subwindows": win.mdi_area.subWindowList(),
            "signal_trees": getattr(win, "signal_trees", []),
        }
    finally:
        # Do not close here to allow the test to inspect; caller can close if needed
        pass