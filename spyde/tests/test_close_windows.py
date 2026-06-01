# Test Closing the windows and making sure that the
# appropriate resources are released.
from pyqtgraph import RectROI

from spyde.drawing.plots.plot_window import PlotWindow
from spyde.external.pyqtgraph.crosshair_roi import CrosshairROI


class TestCloseWindows:
    def test_close_signal_window(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        subplots = win.plots
        subwindows = win.plot_subwindows
        assert len(subwindows) == 2
        assert len(subplots) == 2

        nav, sig = subwindows  # type: PlotWindow
        nav_plot, sig_plot = nav.current_plot_item, sig.current_plot_item
        nav_manager = nav.multiplot_manager
        assert len(nav_manager.navigation_selectors) == 1
        selector = nav_manager.navigation_selectors[nav][0]

        # make sure that the selector is in the navigation plot (not true as the selector is just a "copy")
        # assert selector.roi in nav_plot.items
        sig.close()

        assert len(win.plot_subwindows) == 1
        assert nav in win.plot_subwindows

        # assert that the selector was removed from the navigation plot
        print(nav_manager.navigation_selectors)
        assert len(nav_manager.navigation_selectors[nav]) == 0

        # make sure that the selector is removed from the navigation plot
        for item in nav_plot.items:
            assert not isinstance(item, CrosshairROI)
            assert not isinstance(item, RectROI)
        qtbot.wait(500)

    def test_close_navigation_window(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        subplots = win.plots
        subwindows = win.plot_subwindows
        assert len(subwindows) == 2
        assert len(subplots) == 2

        nav, sig = subwindows  # type: PlotWindow
        nav_plot, sig_plot = nav.current_plot_item, sig.current_plot_item

        nav_manager = nav.multiplot_manager
        assert len(nav_manager.navigation_selectors) == 1
        selector = nav_manager.navigation_selectors[nav][0]

        # make sure that the selector is in the navigation plot
        nav.close()

        # Both windows should be closed now
        assert len(win.plot_subwindows) == 0
        assert len(nav_manager.navigation_selectors[nav]) == 0

        # assert the signalTree is removed from the main window
        assert len(win.signal_trees) == 0


def test_close_preview_window_no_crash(qtbot, stem_4d_dataset):
    """Closing a line-profile preview window must not raise AttributeError."""
    from spyde.tests.test_line_profile import _add_line_profile_on_signal
    win = stem_4d_dataset["window"]
    n_before = len(win.plot_subwindows)
    _add_line_profile_on_signal(qtbot, win)
    preview_windows = win.plot_subwindows[n_before:]
    assert len(preview_windows) == 1
    preview = preview_windows[0]
    try:
        preview.close()
    except AttributeError as e:
        raise AssertionError(f"close() raised AttributeError: {e}") from e
