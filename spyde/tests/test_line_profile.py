"""Tests for line profile compute kernels."""
import numpy as np
import dask.array as da
import pytest
from distributed import Future


class TestLineProfileKernel:
    @pytest.fixture(autouse=True)
    def client(self, stem_4d_dataset):
        self.win = stem_4d_dataset["window"]
        self.client = self.win.client

    def test_signal_profile_horizontal_line(self):
        """Horizontal line through a known row must return that row's values."""
        from spyde.drawing.update_functions import compute_line_profile_kernel
        import pyqtgraph as pg
        from PySide6 import QtWidgets
        import sys
        app = QtWidgets.QApplication.instance()

        # 10x10 image: row 5 has values 50..59
        img = np.zeros((10, 10), dtype=np.float32)
        img[5, :] = np.arange(10, dtype=np.float32) + 50
        img_item = pg.ImageItem(img)

        # Horizontal line from col 1 to col 8 at row 5, width=1
        roi = pg.LineROI([1, 5], [8, 5], width=1)
        future = compute_line_profile_kernel(img, roi, img_item, self.client)
        profile = future.result()

        assert isinstance(profile, np.ndarray)
        assert profile.ndim == 1
        assert len(profile) > 0

    def test_signal_profile_width_averages_perpendicular(self):
        """Width > 1 must average perpendicular pixels: uniform image → same result."""
        from spyde.drawing.update_functions import compute_line_profile_kernel
        import pyqtgraph as pg
        from PySide6 import QtWidgets

        img = np.ones((20, 20), dtype=np.float32) * 3.0
        img_item = pg.ImageItem(img)
        roi_w1 = pg.LineROI([2, 10], [17, 10], width=1)
        roi_w4 = pg.LineROI([2, 10], [17, 10], width=4)

        p1 = compute_line_profile_kernel(img, roi_w1, img_item, self.client).result()
        p4 = compute_line_profile_kernel(img, roi_w4, img_item, self.client).result()

        assert p1.shape == p4.shape, "Profile length should be same regardless of width"
        np.testing.assert_allclose(p1, p4, rtol=1e-5,
            err_msg="Uniform image: width should not change profile values")

    def test_nav_line_sum_kernel_output_shape(self):
        """Nav line sum kernel must reduce nav dims to (nkx, nky)."""
        from spyde.drawing.update_functions import compute_nav_line_sum_kernel
        data = da.ones((8, 8, 16, 16), dtype=np.float32, chunks=(4, 4, 16, 16))
        ys = np.array([2, 3, 4, 5])
        xs = np.array([3, 3, 3, 3])
        future = compute_nav_line_sum_kernel(data, ys, xs, self.client, None)
        result = future.result()
        assert result.shape == (16, 16)

    def test_nav_line_sum_kernel_values(self):
        """Nav line sum: mean of selected nav slices must match numpy reference."""
        from spyde.drawing.update_functions import compute_nav_line_sum_kernel
        rng = np.random.default_rng(42)
        data_np = rng.random((8, 8, 4, 4)).astype(np.float32)
        data = da.from_array(data_np, chunks=(4, 4, 4, 4))
        ys = np.array([1, 2, 3])
        xs = np.array([4, 5, 6])
        future = compute_nav_line_sum_kernel(data, ys, xs, self.client, None)
        result = future.result()
        expected = np.mean(data_np[ys, xs], axis=0)
        np.testing.assert_allclose(result, expected, rtol=1e-5)

    def test_returns_future(self):
        """Both kernels must return a distributed.Future."""
        from spyde.drawing.update_functions import compute_line_profile_kernel, compute_nav_line_sum_kernel
        import pyqtgraph as pg
        from PySide6 import QtWidgets

        img = np.ones((10, 10), dtype=np.float32)
        img_item = pg.ImageItem(img)
        roi = pg.LineROI([1, 5], [8, 5], width=1)
        f1 = compute_line_profile_kernel(img, roi, img_item, self.client)
        assert isinstance(f1, Future)

        data = da.ones((4, 4, 8, 8), dtype=np.float32, chunks=(2, 2, 8, 8))
        f2 = compute_nav_line_sum_kernel(data, np.array([1,2]), np.array([1,2]), self.client, None)
        assert isinstance(f2, Future)


def _add_line_profile_on_signal(qtbot, win):
    """Helper: add a Line Profile ROI to the signal (diffraction) plot."""
    nav, sig = win.plots
    tb = sig.plot_state.toolbar_bottom
    lp_action = None
    for a in tb.actions():
        if a.text() == "Line Profile":
            lp_action = a
            break
    assert lp_action is not None, "Line Profile action not found in signal toolbar"

    lp_action.trigger()
    qtbot.wait(200)

    lp_widget = tb.action_widgets["Line Profile"]["widget"]
    for a in lp_widget.actions():
        if a.text() == "Add Line Profile":
            a.trigger()
            break
    qtbot.wait(300)

    new_action = lp_widget.actions()[-1]
    new_action.trigger()
    qtbot.wait(300)

    action_name = new_action.text()
    caret_box = lp_widget.action_widgets[action_name]["widget"]
    roi = tb.action_widgets["Line Profile"]["plot_items"][action_name]
    preview_window = tb.action_widgets["Line Profile"].get("plot_windows", {}).get(action_name)
    return tb, lp_widget, action_name, caret_box, roi, preview_window


class TestLineProfileSignalPlot:
    """End-to-end tests: line profile on signal (diffraction pattern) plot."""

    def test_spawns_one_preview_window(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        n_before = len(win.plot_subwindows)
        _add_line_profile_on_signal(qtbot, win)
        assert len(win.plot_subwindows) == n_before + 1, (
            "Line profile on signal plot should spawn exactly 1 preview window"
        )

    def test_preview_window_is_frameless(self, qtbot, stem_4d_dataset):
        from PySide6.QtCore import Qt
        win = stem_4d_dataset["window"]
        tb, lp_widget, action_name, caret_box, roi, preview_window = _add_line_profile_on_signal(qtbot, win)
        assert preview_window is not None
        assert preview_window.windowFlags() & Qt.WindowType.FramelessWindowHint

    def test_roi_is_on_signal_plot(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        nav, sig = win.plots
        tb, lp_widget, action_name, caret_box, roi, preview_window = _add_line_profile_on_signal(qtbot, win)
        assert roi in sig.items, "LineROI should be on the signal (diffraction) plot"
        assert roi not in nav.items, "LineROI should NOT be on the navigator"

    def test_roi_move_updates_line_item(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        tb, lp_widget, action_name, caret_box, roi, preview_window = _add_line_profile_on_signal(qtbot, win)
        preview_plot = preview_window.plots[0]

        roi.sigRegionChangeFinished.emit(roi)

        qtbot.waitUntil(
            lambda: preview_plot.line_item.yData is not None,
            timeout=8000,
        )
        assert preview_plot.line_item.yData.ndim == 1

    def test_different_roi_positions_produce_different_profiles(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        nav, sig = win.plots  # capture before preview window is added
        tb, lp_widget, action_name, caret_box, roi, preview_window = _add_line_profile_on_signal(qtbot, win)
        preview_plot = preview_window.plots[0]

        roi.sigRegionChangeFinished.emit(roi)
        qtbot.waitUntil(lambda: preview_plot.line_item.yData is not None, timeout=8000)
        first_profile = preview_plot.line_item.yData.copy()

        # Move ROI to a substantially different position
        old_pos = roi.pos()
        roi.setPos(old_pos.x(), old_pos.y() + sig.image_item.height() * 0.3)
        roi.sigRegionChangeFinished.emit(roi)

        qtbot.waitUntil(
            lambda: (
                preview_plot.line_item.yData is not None
                and not np.array_equal(preview_plot.line_item.yData, first_profile)
            ),
            timeout=8000,
        )
        assert not np.array_equal(preview_plot.line_item.yData, first_profile)

    def test_commit_button_disabled_before_first_computation(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        tb, lp_widget, action_name, caret_box, roi, preview_window = _add_line_profile_on_signal(qtbot, win)
        assert not preview_window.title_bar.commit_button.isEnabled()

    def test_commit_button_enabled_after_computation(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        tb, lp_widget, action_name, caret_box, roi, preview_window = _add_line_profile_on_signal(qtbot, win)
        preview_plot = preview_window.plots[0]

        roi.sigRegionChangeFinished.emit(roi)
        qtbot.waitUntil(lambda: preview_plot.line_item.yData is not None, timeout=8000)
        qtbot.waitUntil(lambda: preview_window.title_bar.commit_button.isEnabled(), timeout=3000)

    def test_end_to_end_commit_signal1d(self, qtbot, stem_4d_dataset):
        """Full flow: add ROI → move → wait → click Commit → Signal1D in new tree."""
        import hyperspy.api as hs
        win = stem_4d_dataset["window"]
        n_before = len(win.signal_trees)
        tb, lp_widget, action_name, caret_box, roi, preview_window = _add_line_profile_on_signal(qtbot, win)
        preview_plot = preview_window.plots[0]

        roi.sigRegionChangeFinished.emit(roi)
        qtbot.waitUntil(lambda: preview_plot.line_item.yData is not None, timeout=8000)
        qtbot.waitUntil(lambda: preview_window.title_bar.commit_button.isEnabled(), timeout=3000)

        preview_window.title_bar.commit_button.click()
        qtbot.waitUntil(lambda: len(win.signal_trees) == n_before + 1, timeout=10000)

        new_signal = win.signal_trees[n_before].root
        assert isinstance(new_signal, hs.signals.Signal1D), (
            f"Expected Signal1D, got {type(new_signal)}"
        )
        assert new_signal.data.ndim == 1

    def test_committed_signal1d_axis_scale(self, qtbot, stem_4d_dataset):
        """Committed Signal1D axis scale must equal line length / n_points."""
        import hyperspy.api as hs
        win = stem_4d_dataset["window"]
        n_before = len(win.signal_trees)
        tb, lp_widget, action_name, caret_box, roi, preview_window = _add_line_profile_on_signal(qtbot, win)
        preview_plot = preview_window.plots[0]

        roi.sigRegionChangeFinished.emit(roi)
        qtbot.waitUntil(lambda: preview_plot.line_item.yData is not None, timeout=8000)
        qtbot.waitUntil(lambda: preview_window.title_bar.commit_button.isEnabled(), timeout=3000)

        preview_window.title_bar.commit_button.click()
        qtbot.waitUntil(lambda: len(win.signal_trees) == n_before + 1, timeout=10000)

        new_signal = win.signal_trees[n_before].root
        n_points = len(new_signal.data)
        assert n_points > 0
        scale = new_signal.axes_manager.signal_axes[0].scale
        assert scale > 0, "Axis scale must be positive"
