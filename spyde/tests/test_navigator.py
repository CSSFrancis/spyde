from functools import partial

from PySide6 import QtCore
from PySide6.QtCore import QRectF

from spyde.actions.base import NAVIGATOR_DRAG_MIME
from spyde.actions.base import NavigatorButton

class TestNavigatorMultiplex:

    def test_navigator_drop(self, qtbot, stem_4d_dataset, monkeypatch):
        win = stem_4d_dataset["window"]
        nav, sig = stem_4d_dataset["subwindows"]

        toolbar = nav.plot_state.toolbar_right
        win.mdi_area.activatePreviousSubWindow()
        qtbot.wait(200)

        navigator_action = next(
            action for action in toolbar.actions() if action.text() == "Select Navigator"
        )
        navigator_action.trigger()
        qtbot.wait(200)

        button_widget = toolbar.action_widgets["Select Navigator"]["widget"]
        first_button = next(
            child for child in button_widget.children() if isinstance(child, NavigatorButton)
        )

        drop_pos = nav.plot_item.mapToScene(nav.plot_item.boundingRect().center())
        initial_item_count = len(nav.plot_widget.ci.items)

        def fake_start_drag(btn: NavigatorButton):
            mw = btn.toolbar.plot.main_window
            token = mw.register_navigator_drag_payload(
                btn.signal, btn.toolbar.plot.nav_plot_manager
            )
            mime = QtCore.QMimeData()
            mime.setData(NAVIGATOR_DRAG_MIME, token.encode("utf-8"))
            mw.navigator_enter()
            mw._navigator_drag_over_active = True
            mw.navigator_drop(drop_pos, mime)
            mw._navigator_drag_over_active = False

        monkeypatch.setattr(NavigatorButton, "_start_drag", fake_start_drag)

        center = first_button.rect().center()
        qtbot.mousePress(first_button, QtCore.Qt.MouseButton.LeftButton, pos=center)
        qtbot.mouseMove(first_button, QtCore.QPoint(center.x() + 50, center.y()))
        qtbot.mouseRelease(first_button, QtCore.Qt.MouseButton.LeftButton, pos=center)
        # there should be two plots now stacked in one column

        assert len(nav.plot_widget.ci.items)  == 2

        qtbot.wait(2000)
        # Try adding another navigator
        initial_item_count = len(nav.plot_widget.ci.items)
        center = first_button.rect().center()
        qtbot.mousePress(first_button, QtCore.Qt.MouseButton.LeftButton, pos=center)

        # previous should now be two plots stored
        assert len(nav.previous_subplots_pos) == 2
        qtbot.mouseMove(first_button, QtCore.QPoint(center.x() + 50, center.y()))
        qtbot.wait(2000)

        qtbot.mouseRelease(first_button, QtCore.Qt.MouseButton.LeftButton, pos=center)
        qtbot.wait(2000)
        # there should be three plots now stacked in one column (the last one should be in the middle)
        #assert len(nav.plot_widget.ci.items)  == 3

    def test_navigator_preview(self, qtbot, stem_4d_dataset, monkeypatch):
        win = stem_4d_dataset["window"]
        nav, sig = stem_4d_dataset["subwindows"]

        win.mdi_area.setActiveSubWindow(nav)
        qtbot.wait(200)
        toolbar = nav.plot_state.toolbar_right
        qtbot.wait(200)

        navigator_action = next(
            action for action in toolbar.actions() if action.text() == "Select Navigator"
        )
        navigator_action.trigger()
        qtbot.wait(200)

        button_widget = toolbar.action_widgets["Select Navigator"]["widget"]
        first_button = next(
            child for child in button_widget.children() if isinstance(child, NavigatorButton)
        )

        drop_pos = nav.plot_item.mapToScene(nav.plot_item.boundingRect().center())
        initial_item_count = len(nav.plot_widget.ci.items)

        def fake_drag_move(self, pos=drop_pos):
            mw = self.toolbar.plot.main_window
            mime = QtCore.QMimeData()
            token = mw.register_navigator_drag_payload(
                self.signal, self.toolbar.plot.nav_plot_manager
            )
            mime.setData(NAVIGATOR_DRAG_MIME, token.encode("utf-8"))
            mw._navigator_drag_over_active = True
            mw.navigator_enter()
            mw.navigator_move(pos)

        def fake_leave(self):
            mw = self.toolbar.plot.main_window
            mw.navigator_leave()
            mw._navigator_drag_over_active = False


        monkeypatch.setattr(NavigatorButton, "_start_drag", fake_drag_move,raising=True)

        center = first_button.rect().center()
        qtbot.mousePress(first_button, QtCore.Qt.MouseButton.LeftButton, pos=center)
        qtbot.mouseMove(first_button, QtCore.QPoint(center.x() + 50, center.y()))
        qtbot.mouseRelease(first_button, QtCore.Qt.MouseButton.LeftButton, pos=center)
        # there should be two plots now stacked in one column

        assert len(nav.plot_widget.ci.items)  == 2

        qtbot.wait(2000)

        fake_leave(first_button)
        qtbot.wait(2000)
        # after leaving, the preview should be removed
        assert len(nav.plot_widget.ci.items)  == 1

        # re-enter

        monkeypatch.setattr(NavigatorButton, "_start_drag", fake_drag_move,raising=True)

        center = first_button.rect().center()
        qtbot.mousePress(first_button, QtCore.Qt.MouseButton.LeftButton, pos=center)
        qtbot.mouseMove(first_button, QtCore.QPoint(center.x() + 50, center.y()))
        qtbot.mouseRelease(first_button, QtCore.Qt.MouseButton.LeftButton, pos=center)
        # there should be two plots now stacked in one column

        assert len(nav.plot_widget.ci.items)  == 2


    def test_navigator_preview_left(self, qtbot, stem_4d_dataset, monkeypatch):
        win = stem_4d_dataset["window"]
        nav, sig = stem_4d_dataset["subwindows"]

        rows =nav.plot_widget.ci.layout.rowCount()
        cols = nav.plot_widget.ci.layout.columnCount()
        assert cols == 1
        assert rows == 1

        win.mdi_area.setActiveSubWindow(nav)
        qtbot.wait(200)
        toolbar = nav.plot_state.toolbar_right
        qtbot.wait(200)

        navigator_action = next(
            action for action in toolbar.actions() if action.text() == "Select Navigator"
        )
        navigator_action.trigger()
        qtbot.wait(200)

        button_widget = toolbar.action_widgets["Select Navigator"]["widget"]
        first_button = next(
            child for child in button_widget.children() if isinstance(child, NavigatorButton)
        )

        drop_pos = nav.plot_item.boundingRect().center()- QtCore.QPointF(200,0)
        initial_item_count = len(nav.plot_widget.ci.items)

        def fake_drag_move(self, pos=drop_pos):
            mw = self.toolbar.plot.main_window
            mime = QtCore.QMimeData()
            token = mw.register_navigator_drag_payload(
                self.signal, self.toolbar.plot.nav_plot_manager
            )
            mime.setData(NAVIGATOR_DRAG_MIME, token.encode("utf-8"))
            mw._navigator_drag_over_active = True
            mw.navigator_enter()
            mw.navigator_move(pos)

        def fake_leave(self):
            mw = self.toolbar.plot.main_window
            mw.navigator_leave()
            mw._navigator_drag_over_active = False


        monkeypatch.setattr(NavigatorButton, "_start_drag", fake_drag_move,raising=True)

        center = first_button.rect().center()
        qtbot.mousePress(first_button, QtCore.Qt.MouseButton.LeftButton, pos=center)
        qtbot.mouseMove(first_button, QtCore.QPoint(center.x() + 50, center.y()))
        qtbot.mouseRelease(first_button, QtCore.Qt.MouseButton.LeftButton, pos=center)
        # there should be two plots now stacked in one column

        assert len(nav.plot_widget.ci.items)  == 2

        qtbot.wait(2000)

        fake_leave(first_button)
        qtbot.wait(2000)
        # after leaving, the preview should be removed
        assert len(nav.plot_widget.ci.items)  == 1

        rows = nav.previous_graphics_layout_widget.ci.layout.rowCount()
        cols = nav.previous_graphics_layout_widget.ci.layout.columnCount()

        rows =nav.plot_widget.ci.layout.rowCount()
        cols = nav.plot_widget.ci.layout.columnCount()

        #assert cols == 1
        #assert rows == 1


        # re-enter on bottom
        drop_pos = nav.plot_item.boundingRect().center()
        def fake_drag_move(self, pos=drop_pos):
            mw = self.toolbar.plot.main_window
            mime = QtCore.QMimeData()
            token = mw.register_navigator_drag_payload(
                self.signal, self.toolbar.plot.nav_plot_manager
            )
            mime.setData(NAVIGATOR_DRAG_MIME, token.encode("utf-8"))
            mw._navigator_drag_over_active = True
            mw.navigator_enter()
            mw.navigator_move(pos)

        monkeypatch.setattr(NavigatorButton, "_start_drag", fake_drag_move,raising=True)

        center = first_button.rect().center()
        qtbot.mousePress(first_button, QtCore.Qt.MouseButton.LeftButton, pos=center)
        qtbot.mouseMove(first_button, QtCore.QPoint(center.x() + 50, center.y()))
        qtbot.mouseRelease(first_button, QtCore.Qt.MouseButton.LeftButton, pos=center)
        # there should be two plots now stacked in one column

        assert len(nav.plot_widget.ci.items)  == 2

        qtbot.wait(2000)
        fake_leave(first_button)
        qtbot.wait(2000)
        # after leaving, the preview should be removed
        assert len(nav.plot_widget.ci.items)  == 1

    def test_navigator_drop_3d(self, qtbot, insitu_tem_2d_dataset,monkeypatch):
        win = insitu_tem_2d_dataset["window"]
        nav, sig = insitu_tem_2d_dataset["subwindows"]

        toolbar = nav.plot_state.toolbar_right
        win.mdi_area.activatePreviousSubWindow()
        qtbot.wait(200)

        navigator_action = next(
            action for action in toolbar.actions() if action.text() == "Select Navigator"
        )
        navigator_action.trigger()
        qtbot.wait(200)

        button_widget = toolbar.action_widgets["Select Navigator"]["widget"]
        first_button = next(
            child for child in button_widget.children() if isinstance(child, NavigatorButton)
        )

        drop_pos = nav.plot_item.mapToScene(nav.plot_item.boundingRect().center())
        initial_item_count = len(nav.plot_widget.ci.items)

        def fake_start_drag(btn: NavigatorButton):
            mw = btn.toolbar.plot.main_window
            token = mw.register_navigator_drag_payload(
                btn.signal, btn.toolbar.plot.nav_plot_manager
            )
            mime = QtCore.QMimeData()
            mime.setData(NAVIGATOR_DRAG_MIME, token.encode("utf-8"))
            mw.navigator_enter()
            mw._navigator_drag_over_active = True
            mw.navigator_drop(drop_pos, mime)
            mw._navigator_drag_over_active = False

        monkeypatch.setattr(NavigatorButton, "_start_drag", fake_start_drag)

        center = first_button.rect().center()
        qtbot.mousePress(first_button, QtCore.Qt.MouseButton.LeftButton, pos=center)
        qtbot.mouseMove(first_button, QtCore.QPoint(center.x() + 50, center.y()))
        qtbot.mouseRelease(first_button, QtCore.Qt.MouseButton.LeftButton, pos=center)
        # there should be two plots now stacked in one column

        assert len(nav.plot_widget.ci.items)  == 2




