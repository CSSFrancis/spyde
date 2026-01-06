# Test creating and closing FFT windows.
import pytest


class TestFFT:

    def test_fft_change_on_navigator_moving(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        subwindows = win.plots
        assert len(subwindows) == 2

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
        fft_button.trigger() # Close FFT the fft will be hidden

        num_visible = 0
        for window in win.plot_subwindows:
            if window.isVisible():
                num_visible += 1
        assert num_visible == 2

        qtbot.wait(500)
        fft_button.trigger() # Open FFT again
        qtbot.wait(500)
