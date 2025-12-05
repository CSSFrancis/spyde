# Test Closing the windows and making sure that the
# appropriate resources are released.
import pytest

from spyde.drawing.plot import Plot, PlotWindow
from typing import Tuple


class TestCloseWindows:
    def test_close_signal_window(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        subplots = win.plots
        subwindows =  win.plot_subwindows
        assert len(subwindows) == 2
        assert len(subplots) == 2

        nav, sig = subwindows  # type: PlotWindow
        nav_plot, sig_plot = nav.current_plot_item, sig.current_plot_item
        nav_manager = nav.multiplot_manager
        assert len(nav_manager.navigation_selectors) == 1
        selector = nav_manager.navigation_selectors[nav][0]

        # make sure that the selector is in the navigation plot
        assert selector.selector in nav_plot.items
        sig.close()

        assert len(win.plot_subwindows) == 1
        assert nav in win.plot_subwindows

        # assert that the selector was removed from the navigation plot
        print(nav_manager.navigation_selectors)
        assert len(nav_manager.navigation_selectors[nav]) == 0

        # make sure that the selector is removed from the navigation plot
        assert selector.selector not in nav_plot.items

    def test_close_navigation_window(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        subplots = win.plots
        subwindows =  win.plot_subwindows
        assert len(subwindows) == 2
        assert len(subplots) == 2

        nav, sig = subwindows  # type: PlotWindow
        nav_plot, sig_plot = nav.current_plot_item, sig.current_plot_item

        nav_manager = nav.multiplot_manager
        assert len(nav_manager.navigation_selectors) == 1
        selector = nav_manager.navigation_selectors[nav][0]

        # make sure that the selector is in the navigation plot
        assert selector.selector in nav_plot.items
        nav.close()

        # Both windows should be closed now
        assert len(win.plot_subwindows) == 0
        assert len(nav_manager.navigation_selectors[nav]) == 0

        # assert the signalTree is removed from the main window
        assert len(win.signal_trees) == 0
