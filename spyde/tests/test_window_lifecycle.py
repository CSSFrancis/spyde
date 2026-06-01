import pytest
from spyde.drawing.plots.plot_window import PlotWindow


class TestCloseWindowLifecycle:
    def test_close_window_removes_from_tracking(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        initial_count = len(win.plot_subwindows)
        assert initial_count >= 2

        # Close the first subwindow
        pw = win.plot_subwindows[0]
        pw.close()
        qtbot.waitUntil(
            lambda: len(win.plot_subwindows) < initial_count,
            timeout=3000,
        )
        assert pw not in win.plot_subwindows

    def test_close_nav_window_removes_signal_tree(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        initial_tree_count = len(win.signal_trees)
        assert initial_tree_count >= 1

        # The nav window is the first subwindow (level-1)
        nav_pw = win.plot_subwindows[0]
        nav_pw.close()
        qtbot.waitUntil(
            lambda: len(win.signal_trees) < initial_tree_count,
            timeout=3000,
        )
        assert len(win.signal_trees) == initial_tree_count - 1
