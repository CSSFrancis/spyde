# Test UI elements and make sure that they are rendering as intended to reduce clipping etc.


import pytest
class TestDrawing:
    def test_toolbar_drawing(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        subwindows = win.mdi_area.subWindowList()
        assert len(subwindows) == 2

        # Click on the navigation plot and make sure that the toolbar is fully visible

        nav, sig = stem_4d_dataset["subwindows"]

        win.mdi_area.setActiveSubWindow(nav)
        qtbot.wait(500)

        toolbar_top = nav.plot_state.toolbar_top  # type: RoundedToolBar
        toolbar_bottom = nav.plot_state.toolbar_bottom  # type: RoundedToolBar
        toolbar_right = nav.plot_state.toolbar_right  # type: RoundedToolBar
        toolbar_left = nav.plot_state.toolbar_left  # type: RoundedToolBar

        assert toolbar_right.isVisible()

