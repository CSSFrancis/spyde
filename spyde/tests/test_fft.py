# Test creating and closing FFT windows.
import pytest


class TestFFT:

    def test_fft_change_on_navigator_moving(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        subwindows = win.plots
        assert len(subwindows) == 2
        nav_window, sig_window = win.plot_subwindows

        nav, sig = subwindows

        toolbar_bottom = sig.plot_state.toolbar_right  # type: RoundedToolBar

        actions = toolbar_bottom.actions()
        print("Actions:", actions)

        for action in actions:
            print(action.text())
            if action.text() == "FFT":
                fft_button = action
        fft_button.trigger()
        qtbot.wait(500)
        for window in win.plot_subwindows:
            assert window.isVisible()
        assert len(win.plot_subwindows) == 3
        fft_button.trigger()

        qtbot.wait(500)
        assert len(win.plot_subwindows) == 3
        num_visible = 0
        for window in win.plot_subwindows:
            if window.isVisible():
                num_visible += 1
        assert num_visible == 2

        fft_button.trigger()
        qtbot.wait(500)
        fft_win = win.plot_subwindows[2]  # type: PlotWindow
        current_img = fft_win.current_plot_item.image_item.image
        # Move the navigator ROI
        nav_manager = nav.multiplot_manager
        selector = nav_manager.navigation_selectors[nav_window][0]
        selector.roi.setPos((5, 5))
        qtbot.wait(500)
        # Check that the FFT image has changed
        new_img = fft_win.current_plot_item.image_item.image
        assert not (current_img == new_img).all()
