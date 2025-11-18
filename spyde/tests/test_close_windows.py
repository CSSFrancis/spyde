# Test Closing the windows and making sure that the
# appropriate resources are released.
import pytest

from spyde.drawing.multiplot import Plot
from typing import Tuple


class TestCloseWindows:
    def test_close_signal_window(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        subwindows = win.mdi_area.subWindowList()
        assert len(subwindows) == 2

        nav, sig = stem_4d_dataset["subwindows"] # type: Plot
        nav_manager = nav.nav_plot_manager
        assert len(nav_manager.navigation_selectors) == 1
        selector = nav_manager.navigation_selectors[0]

        # make sure that the selector is in the navigation plot
        assert selector.selector in nav.plot_item.items
        sig.close()

        assert len(win.plot_subwindows) ==1
        assert nav in win.plot_subwindows

        # assert that the selector was removed from the navigation plot
        assert len(nav_manager.navigation_selectors) == 0

        # make sure that the selector is removed from the navigation plot
        assert selector.selector not in nav.plot_item.items

    def test_close_navigation_window(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        subwindows = win.mdi_area.subWindowList()
        assert len(subwindows) == 2

        nav, sig = stem_4d_dataset["subwindows"]  # type: Plot
        nav_manager = nav.nav_plot_manager
        assert len(nav_manager.navigation_selectors) == 1
        selector = nav_manager.navigation_selectors[0]

        # make sure that the selector is in the navigation plot
        assert selector.selector in nav.plot_item.items
        nav.close()

        # Both windows should be closed now
        assert len(win.plot_subwindows) == 0
        assert len(nav_manager.navigation_selectors) == 0

        # assert the signalTree is removed from the main window
        assert len(win.signal_trees) == 0





