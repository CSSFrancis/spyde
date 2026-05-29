import numpy as np
import dask.array as da
import hyperspy.api as hs
from PySide6 import QtCore
from pytestqt.plugin import qtbot

from spyde.drawing.plots.multiplot_manager import MultiplotManager
from spyde.drawing.plots.plot import Plot
from spyde.external.pyqtgraph.crosshair_roi import CrosshairROI
from pyqtgraph import RectROI, InfiniteLine, LinearRegionItem

from spyde.qt.shared import open_window as _open_window


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


    def test_zoom_does_not_move_selector_or_recompute(self, qtbot, stem_4d_dataset):
        """Zooming the navigator should not shift the crosshair center or trigger signal recompute."""
        win = stem_4d_dataset["window"]
        subplots = win.plots
        subwindows = win.plot_subwindows
        nav, sig = subplots
        nav_window, sig_window = subwindows
        nav_manager = nav.multiplot_manager
        selector = nav_manager.navigation_selectors[nav_window][0]

        qtbot.wait(500)

        # Capture indices and data before zoom
        pre_zoom_indices = selector.selector._get_selected_indices().copy()
        pre_zoom_data = sig.current_data

        # Simulate zoom by changing the ViewBox range (triggers sigRangeChanged -> _update_for_zoom)
        vb = nav.getViewBox()
        current_range = vb.viewRange()
        cx = (current_range[0][0] + current_range[0][1]) / 2
        cy = (current_range[1][0] + current_range[1][1]) / 2
        half_w = (current_range[0][1] - current_range[0][0]) / 4
        half_h = (current_range[1][1] - current_range[1][0]) / 4
        # Zoom in 2x
        vb.setRange(xRange=(cx - half_w, cx + half_w), yRange=(cy - half_h, cy + half_h), padding=0)

        qtbot.wait(500)

        # Indices should be unchanged after zoom
        post_zoom_indices = selector.selector._get_selected_indices().copy()
        np.testing.assert_array_equal(
            pre_zoom_indices, post_zoom_indices,
            err_msg="Crosshair selector indices changed after zoom — center drifted"
        )

        # Signal data should not have changed (no recompute triggered)
        post_zoom_data = sig.current_data
        assert pre_zoom_data is post_zoom_data or np.array_equal(pre_zoom_data, post_zoom_data), \
            "Signal recomputed after zoom even though selector did not move"

    def test_chunk_recall_1d(self, qtbot):
        """
        Test that the moving selector accurately gets the right data from a chunked dataset"""

        data = np.repeat(
            np.arange(0, 10), repeats=1000).reshape(100, 10, 10)
        lazy_data = da.from_array(data, chunks=(10,10,10))
        new_sig = hs.signals.Signal2D(lazy_data)

        win = _open_window()

        win.add_signal(new_sig)
        qtbot.waitUntil(lambda: len(win.mdi_area.subWindowList()) == 2, timeout=5000)

        subplots = win.plots
        subwindows = win.plot_subwindows
        assert len(subwindows) == 2

        nav, sig = subplots  # type: Plot
        nav_window, sig_window = subwindows
        nav_manager = nav.multiplot_manager
        assert len(nav_manager.navigation_selectors) == 1
        selector = nav_manager.navigation_selectors[nav_window][0]
        current = sig.current_data

        nav, sig = subplots  # type: Plot

        np.testing.assert_array_equal(sig.image_item.image, 0)

        # move the selector to position 10
        for i in range(10):
            selector.roi.setPos(i*10)
            qtbot.wait(1000)
            np.testing.assert_array_equal(sig.image_item.image, i)


        # change the axes manager

        new_sig.axes_manager.navigation_axes[0].scale = 2
        new_sig.axes_manager.navigation_axes[0].offset = -10

        for i in range(10):
            selector.roi.setPos(i*10)
            qtbot.wait(1000)
            np.testing.assert_array_equal(sig.image_item.image, i)

        win.close()


class TestPlotBehavior:

    def test_new_selector_centered_in_fov(self, qtbot, stem_4d_dataset):
        """A newly created crosshair selector should start at the center of the image FOV."""
        win = stem_4d_dataset["window"]
        nav, sig = win.plots
        nav_window = win.plot_subwindows[0]
        nav_manager = nav.multiplot_manager
        selector = nav_manager.navigation_selectors[nav_window][0]

        qtbot.wait(300)

        # Get image bounds in data coordinates
        image_item = nav.image_item
        transform = image_item.transform()
        img_w = image_item.width()
        img_h = image_item.height()
        center_data = transform.map(QtCore.QPointF(img_w / 2, img_h / 2))

        # Get the crosshair ROI center (pos is lower-left corner)
        roi = selector.selector.roi
        pos = roi.pos()
        size = roi.size()
        roi_center_x = pos.x() + size[0] / 2
        roi_center_y = pos.y() + size[1] / 2

        # The selector center should be within 5% of the image size from the FOV center
        tolerance_x = img_w * 0.05 * abs(transform.m11())
        tolerance_y = img_h * 0.05 * abs(transform.m22())
        assert abs(roi_center_x - center_data.x()) < tolerance_x, (
            f"Selector center x={roi_center_x:.3f} is not near image center x={center_data.x():.3f}"
        )
        assert abs(roi_center_y - center_data.y()) < tolerance_y, (
            f"Selector center y={roi_center_y:.3f} is not near image center y={center_data.y():.3f}"
        )

    def test_zoom_out_limit(self, qtbot, stem_4d_dataset):
        """Zooming out past 80% of image size should be prevented."""
        win = stem_4d_dataset["window"]
        nav, sig = win.plots
        qtbot.wait(300)

        vb = nav.getViewBox()
        # Get image extent
        image_item = nav.image_item
        transform = image_item.transform()
        img_w = image_item.width()
        img_h = image_item.height()
        x_min = transform.map(QtCore.QPointF(0, 0)).x()
        x_max = transform.map(QtCore.QPointF(img_w, 0)).x()
        img_data_width = abs(x_max - x_min)

        # Try to zoom out far beyond the image by setting a huge range
        vb.setRange(xRange=(x_min - img_data_width * 10, x_max + img_data_width * 10), padding=0)
        qtbot.wait(100)

        x_range = vb.viewRange()[0]
        actual_width = x_range[1] - x_range[0]
        # The actual view width must not exceed maxXRange (1.8 * img_data_width)
        assert actual_width <= img_data_width * 1.85, (
            f"View zoomed out too far: view width {actual_width:.3f} > limit {img_data_width * 1.85:.3f}"
        )

    def test_zoom_respects_mouse_position(self, qtbot, stem_4d_dataset):
        """Zooming should scale around the current view center (pyqtgraph native behavior preserved)."""
        win = stem_4d_dataset["window"]
        nav, sig = win.plots
        qtbot.wait(300)

        vb = nav.getViewBox()
        current_range = vb.viewRange()
        cx = (current_range[0][0] + current_range[0][1]) / 2
        cy = (current_range[1][0] + current_range[1][1]) / 2
        view_w = current_range[0][1] - current_range[0][0]
        view_h = current_range[1][1] - current_range[1][0]
        half_w = view_w / 4
        half_h = view_h / 4
        # Zoom in 2x symmetrically around the current center
        vb.setRange(xRange=(cx - half_w, cx + half_w), yRange=(cy - half_h, cy + half_h), padding=0)
        qtbot.wait(100)

        post_range = vb.viewRange()
        post_cx = (post_range[0][0] + post_range[0][1]) / 2
        post_cy = (post_range[1][0] + post_range[1][1]) / 2

        # Allow 1% of the original view width/height as tolerance
        tol_x = view_w * 0.01
        tol_y = view_h * 0.01
        assert abs(post_cx - cx) < tol_x, f"Center drifted in x: {post_cx:.4f} vs {cx:.4f}"
        assert abs(post_cy - cy) < tol_y, f"Center drifted in y: {post_cy:.4f} vs {cy:.4f}"

    def test_axes_visible_on_2d_plot(self, qtbot, stem_4d_dataset):
        """Both bottom and left axes must be visible on a freshly opened 2D signal plot."""
        win = stem_4d_dataset["window"]
        nav, sig = win.plots
        qtbot.wait(300)

        for plot in (nav, sig):
            if plot.plot_state.dimensions == 2:
                bottom = plot.getAxis('bottom')
                left = plot.getAxis('left')
                assert bottom.isVisible(), f"bottom axis not visible on {plot}"
                assert left.isVisible(), f"left axis not visible on {plot}"

    def test_axes_visible_on_1d_plot(self, qtbot, insitu_tem_2d_dataset):
        """Both bottom and left axes must be visible on a 1D signal plot."""
        win = insitu_tem_2d_dataset["window"]
        nav, sig = win.plots
        qtbot.wait(300)

        # sig is the 1D signal plot for insitu TEM
        bottom = sig.getAxis('bottom')
        left = sig.getAxis('left')
        assert bottom.isVisible(), "bottom axis not visible on 1D signal plot"
        assert left.isVisible(), "left axis not visible on 1D signal plot"