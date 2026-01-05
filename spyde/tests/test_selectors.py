import numpy as np

from spyde.drawing.plots.multiplot_manager import MultiplotManager
from spyde.drawing.plots.plot import Plot
from spyde.external.pyqtgraph.crosshair_roi import CrosshairROI
from pyqtgraph import RectROI, InfiniteLine, LinearRegionItem

class TestSelectors:
    def test_selector_moving(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        subplots = win.plots
        subwindows = win.plot_subwindows
        assert len(subwindows) == 2

        nav, sig = subplots  # type: Plot
        nav_window, sig_window = subwindows
        nav_manager = nav.multiplot_manager
        assert len(nav_manager.navigation_selectors) == 1
        selector = nav_manager.navigation_selectors[nav_window][0]
        current = sig.current_data

        print("Old data captured:", current)
        print("Selector", selector)
        print("Sector", selector.selector)
        print("Selector ROI type:", selector.selector.roi)
        print("Selector ROI:", selector.roi)

        assert sig in win.signal_trees[0].signal_plots
        # Simulate moving the selector in the navigation plot
        original_pos = selector.roi.pos()  # Mock original position
        new_pos = (original_pos[0] + 10, original_pos[1] + 10)
        selector.roi.setPos(new_pos[0], new_pos[1])

        # Verify that the position has been updated
        new_pos = selector.roi.pos()
        assert new_pos.x() == original_pos[0] + 10
        assert new_pos.y() == original_pos[1] + 10

        # wait and make sure that the signal plot updated accordingly
        qtbot.wait(500)

        # wait and make sure that the signal plot updated accordingly
        qtbot.wait(500)

        # capture new data from the signal plot and assert it changed
        new_data = sig.current_data
        assert current is not None and new_data is not None  # sanity check
        assert not np.array_equal(current, new_data)

    def test_toggle_integrating_2d(self, qtbot, stem_4d_dataset):
        """
        Test switching the selector between integrating and non-integrating modes.
        """
        win = stem_4d_dataset["window"]
        subplots = win.plots
        subwindows = win.plot_subwindows
        assert len(subwindows) == 2

        nav, sig = subplots  # type: Plot
        nav_window, sig_window = subwindows
        nav_manager = nav.multiplot_manager
        assert len(nav_manager.navigation_selectors) == 1
        selector = nav_manager.navigation_selectors[nav_window][0]
        current = sig.current_data

        # assert a CrossHairROI is part of nav items
        cross_hair = None
        rect_roi = None
        for item in nav.items:
            if isinstance(item, CrosshairROI):
                cross_hair = item
            elif isinstance(item, RectROI):
                rect_roi = item
        assert cross_hair is not None
        assert rect_roi is not None
        # wait and make sure that the signal plot updated accordingly
        qtbot.wait(500)
        assert not rect_roi.isVisible()
        assert cross_hair.isVisible()
        # press the integrating button
        selector.is_integrating = True
        # wait and make sure that the signal plot updated accordingly
        qtbot.wait(500)
        assert rect_roi.isVisible()
        assert not cross_hair.isVisible()
        # wait and make sure that the signal plot updated accordingly
        qtbot.wait(500)

    def test_toggle_integrating_1d(self, qtbot, insitu_tem_2d_dataset):
        """
        Test switching the selector between integrating and non-integrating modes.
        """
        win = insitu_tem_2d_dataset["window"]
        subplots = win.plots
        subwindows = win.plot_subwindows
        assert len(subwindows) == 2

        nav, sig = subplots  # type: Plot
        nav_window, sig_window = subwindows
        nav_manager = nav.multiplot_manager
        assert len(nav_manager.navigation_selectors) == 1
        selector = nav_manager.navigation_selectors[nav_window][0]
        current = sig.current_data

        # assert a CrossHairROI is part of nav items
        inf_line = None
        lin_region = None
        for item in nav.items:
            if isinstance(item, InfiniteLine):
                inf_line = item
            elif isinstance(item, LinearRegionItem):
                lin_region = item
        assert inf_line is not None
        assert lin_region is not None
        # wait and make sure that the signal plot updated accordingly
        qtbot.wait(500)
        assert not lin_region.isVisible()
        assert inf_line.isVisible()
        # press the integrating button
        selector.is_integrating = True
        # wait and make sure that the signal plot updated accordingly
        qtbot.wait(500)
        assert lin_region.isVisible()
        assert not inf_line.isVisible()
        # wait and make sure that the signal plot updated accordingly
        qtbot.wait(500)

    def test_add_selector(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        subplots = win.plots
        subwindows = win.plot_subwindows
        assert len(subwindows) == 2

        nav, sig = subplots  # type: Plot
        nav_window, sig_window = subwindows
        nav_manager = nav.multiplot_manager # type: MultiplotManager
        assert len(nav_manager.navigation_selectors) == 1

        # add another selector
        nav_manager.add_navigation_selector_and_signal_plot(nav_window)

        assert len(nav_manager.navigation_selectors[nav_window]) == 2
        assert len(nav_manager.signal_tree.signal_plots) == 2
