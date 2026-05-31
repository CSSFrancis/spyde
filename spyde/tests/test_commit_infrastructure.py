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

    def test_plot_update_1d_no_plotstate(self, qtbot):
        """Plot.update() with plot_state=None and 1D current_data must call line_item.setData."""
        import numpy as np
        from spyde.qt.shared import open_window
        win = open_window()
        qtbot.addWidget(win)
        pw = win.add_plot_window(is_navigator=False, signal_tree=None)
        plot = pw.add_new_plot()

        # Add line_item to scene (same as the virtual preview fix)
        if plot.line_item not in plot.items:
            plot.addItem(plot.line_item)

        assert plot.plot_state is None

        data_1d = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        plot.current_data = data_1d
        plot.update()

        assert plot.line_item.yData is not None, "1D data not rendered: line_item.yData is None"
        np.testing.assert_array_equal(plot.line_item.yData, data_1d)
        win.close()
