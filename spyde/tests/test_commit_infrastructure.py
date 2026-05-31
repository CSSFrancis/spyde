"""Tests for the title-bar Commit button infrastructure."""
from PySide6 import QtWidgets
from spyde.qt.shared import open_window


class TestCommitInfrastructure:
    def test_commit_button_hidden_by_default(self, qtbot):
        from spyde.drawing.plots.plot_window import PlotWindow
        win = open_window()
        qtbot.addWidget(win)
        pw = win.add_plot_window(is_navigator=False, signal_tree=None)
        assert hasattr(pw.title_bar, "commit_button"), "commit_button not on title_bar"
        assert not pw.title_bar.commit_button.isVisible(), (
            "Commit button should be hidden by default"
        )
        win.close()

    def test_set_commit_fn_shows_button(self, qtbot):
        win = open_window()
        qtbot.addWidget(win)
        pw = win.add_plot_window(is_navigator=False, signal_tree=None)
        called = []
        pw.set_commit_fn(lambda: called.append(1))
        assert pw.title_bar.commit_button.isVisible(), (
            "set_commit_fn should make Commit button visible"
        )
        win.close()

    def test_commit_button_calls_function(self, qtbot):
        win = open_window()
        qtbot.addWidget(win)
        pw = win.add_plot_window(is_navigator=False, signal_tree=None)
        called = []
        pw.set_commit_fn(lambda: called.append(1))
        # Enable before clicking — set_commit_fn starts disabled by design
        pw.set_commit_enabled(True)
        pw.title_bar.commit_button.click()
        assert called == [1], "Commit button did not call the provided function"
        win.close()

    def test_set_commit_enabled_controls_button(self, qtbot):
        win = open_window()
        qtbot.addWidget(win)
        pw = win.add_plot_window(is_navigator=False, signal_tree=None)
        pw.set_commit_fn(lambda: None)
        assert not pw.title_bar.commit_button.isEnabled(), (
            "Button should start disabled after set_commit_fn"
        )
        pw.set_commit_enabled(True)
        assert pw.title_bar.commit_button.isEnabled()
        pw.set_commit_enabled(False)
        assert not pw.title_bar.commit_button.isEnabled()
        win.close()
