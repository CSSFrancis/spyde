# Test creating and closing FFT windows.
import pytest


class TestFFT:

    def test_fft_change_on_navigator_moving(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        subwindows = win.mdi_area.subWindowList()
        assert len(subwindows) == 2

        nav, sig = stem_4d_dataset["subwindows"]  # type: Plot
        nav_manager = nav.nav_plot_manager
        assert len(nav_manager.navigation_selectors) == 1
        selector = nav_manager.navigation_selectors[0]

        # make sure that the selector is in the navigation plot
        assert selector.selector in nav.plot_item.items

        # Simulate moving the selector in the navigation plot

        original_pos = selector.selector.pos()  # Original position

        target_pos = (original_pos[0] + 10, original_pos[1] + 10)
        selector.selector.setPos(target_pos[0], target_pos[1])

        # Verify that the position has been updated
        new_pos = selector.selector.pos()
        assert new_pos.x() == original_pos[0] + 10
        assert new_pos.y() == original_pos[1] + 10
