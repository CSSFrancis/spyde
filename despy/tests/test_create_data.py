import pytest
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
        if action_name.lower() in action.text().lower():
            return action
    return None


class TestOpenExampleData:

    def test_open_example_data(self, qtbot):
        app = QtWidgets.QApplication.instance()
        win = MainWindow(app=app)
        qtbot.addWidget(win)
        win.show()
        QTest.qWaitForWindowExposed(win)

        menubar = win.menuBar()
        assert menubar is not None
        file_menu_action = _find_menu_action(menubar, "File")
        assert file_menu_action is not None
        load_examples = _find_menu_action(file_menu_action, "Load Example Data...")

        # only load the smallest example to keep test fast
        small_ptyco = _find_menu_action(load_examples.menu(), "small_ptychography")
        assert small_ptyco is not None
        small_ptyco.trigger()

        # this should load the example data and create a new MDI subwindow
        qtbot.waitUntil(lambda: len(getattr(win, "mdi_area").subWindowList()) > 0, timeout=5000)

        # assert that there are two subwindows: one for the plot and one for the navigation
        subwindows = win.mdi_area.subWindowList()
        assert len(subwindows) == 2

        # check that there is a single selector on the navigation plot

        assert len(win.signal_trees) == 1
        assert len(win.signal_trees[0].signal_plots) == 1
        assert len(win.signal_trees[0].navigator_plot_manager.plots) == 1
        assert len(win.signal_trees[0].navigator_plot_manager.navigation_selectors) == 1

        win.signal_trees[0].navigator_plot_manager.add_navigation_selector_and_signal_plot()
        assert len(win.signal_trees[0].navigator_plot_manager.navigation_selectors) == 2
        assert len(win.signal_trees[0].signal_plots) == 2

        # resize all  the subwindows to not overlap. Make 2 columns
        subwindows = win.mdi_area.subWindowList()[::-1]  # reverse to have nav on left
        win.mdi_area.tileSubWindows()

        qtbot.wait(500)
        # take a screenshot and save as a png
        pixmap = win.grab()
        pixmap.save("test_open_example_data.png", "PNG")

        # close the window
        win.close()

    # Add 5D STEM once supported
    @pytest.mark.parametrize("signal_type", ("Image",
                                         "Insitu TEM",
                                         "4D STEM"))
    def test_create_test_data(self, qtbot, signal_type):
        app = QtWidgets.QApplication.instance()
        win = MainWindow(app=app)
        qtbot.addWidget(win)
        win.show()
        QTest.qWaitForWindowExposed(win)

        menubar = win.menuBar()
        assert menubar is not None
        file_menu_action = _find_menu_action(menubar, "File")
        assert file_menu_action is not None
        create_data_action = _find_menu_action(file_menu_action, "Create Data")

        # Create some test data
        def _accept_dialog(signal_type=signal_type):
            # Find the dialog, switch to the requested tab, then click OK (fallback to accept)
            app = QtWidgets.QApplication.instance()
            for w in app.topLevelWidgets():
                if isinstance(w, QtWidgets.QDialog) and w.isVisible():
                    # Try to switch the QTabWidget to the provided signal_type
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

        # assert that there is a single subwindow with the created data
        qtbot.waitUntil(lambda: len(getattr(win, "mdi_area").subWindowList()) > 0, timeout=5000)
        subwindows = win.mdi_area.subWindowList()

        if signal_type == "5D STEM":
            expected_plots = 3
        elif signal_type == "4D STEM" or signal_type == "Insitu TEM":
            expected_plots = 2
        else:
            expected_plots = 1
        assert len(subwindows) == expected_plots






