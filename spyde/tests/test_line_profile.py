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


def _add_line_profile_on_nav(qtbot, win):
    """Helper: add a Line Profile ROI to the navigator plot."""
    nav, sig = win.plots
    tb = nav.plot_state.toolbar_bottom
    lp_action = None
    for a in tb.actions():
        if a.text() == "Line Profile":
            lp_action = a
            break
    assert lp_action is not None, "Line Profile action not found in navigator toolbar"

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
    plot_windows = tb.action_widgets["Line Profile"].get("plot_windows", {})
    profile_window = plot_windows.get(action_name + "_profile")
    sum_window = plot_windows.get(action_name + "_sum")
    return tb, lp_widget, action_name, caret_box, roi, profile_window, sum_window


class TestLineProfileNavPlot:
    """End-to-end tests: line profile on navigator (real-space) plot."""

    def test_spawns_two_preview_windows(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        n_before = len(win.plot_subwindows)
        _add_line_profile_on_nav(qtbot, win)
        assert len(win.plot_subwindows) == n_before + 2, (
            "Line profile on navigator should spawn exactly 2 preview windows"
        )

    def test_both_windows_are_frameless(self, qtbot, stem_4d_dataset):
        from PySide6.QtCore import Qt
        win = stem_4d_dataset["window"]
        tb, lp_widget, action_name, caret_box, roi, profile_window, sum_window = _add_line_profile_on_nav(qtbot, win)
        assert profile_window is not None, "Profile window (1D) not registered"
        assert sum_window is not None, "Sum window (2D) not registered"
        assert profile_window.windowFlags() & Qt.WindowType.FramelessWindowHint
        assert sum_window.windowFlags() & Qt.WindowType.FramelessWindowHint

    def test_roi_is_on_navigator_plot(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        nav, sig = win.plots
        tb, lp_widget, action_name, caret_box, roi, profile_window, sum_window = _add_line_profile_on_nav(qtbot, win)
        assert roi in nav.items, "LineROI should be on the navigator plot"
        assert roi not in sig.items

    def test_profile_window_updates_instantly(self, qtbot, stem_4d_dataset):
        """Window 1 (1D profile) must update without waiting for dask."""
        win = stem_4d_dataset["window"]
        tb, lp_widget, action_name, caret_box, roi, profile_window, sum_window = _add_line_profile_on_nav(qtbot, win)
        profile_plot = profile_window.plots[0]

        roi.sigRegionChangeFinished.emit(roi)
        # Give one Qt event loop cycle — no dask wait needed
        qtbot.wait(300)

        assert profile_plot.line_item.yData is not None, (
            "1D profile window must update instantly from the rendered nav image"
        )

    def test_sum_window_updates_via_dask(self, qtbot, stem_4d_dataset):
        """Window 2 (summed diffraction) must update via dask within timeout."""
        win = stem_4d_dataset["window"]
        tb, lp_widget, action_name, caret_box, roi, profile_window, sum_window = _add_line_profile_on_nav(qtbot, win)
        sum_plot = sum_window.plots[0]

        roi.sigRegionChangeFinished.emit(roi)
        qtbot.waitUntil(
            lambda: (
                sum_plot.current_data is not None
                and not isinstance(sum_plot.current_data, __import__('distributed').Future)
            ),
            timeout=10000,
        )
        assert sum_plot.image_item.image is not None
        assert sum_plot.image_item.image.ndim == 2

    def test_commit_button_only_on_sum_window(self, qtbot, stem_4d_dataset):
        """Commit button must appear on window 2 (sum), not window 1 (profile)."""
        win = stem_4d_dataset["window"]
        tb, lp_widget, action_name, caret_box, roi, profile_window, sum_window = _add_line_profile_on_nav(qtbot, win)
        assert not profile_window.title_bar.commit_button.isVisible(), (
            "Commit button should NOT be visible on the 1D profile window"
        )
        assert sum_window.title_bar.commit_button.isVisible(), (
            "Commit button should be visible on the sum (2D) window"
        )

    def test_end_to_end_commit_signal2d(self, qtbot, stem_4d_dataset):
        """Full flow: add nav ROI → wait → click Commit → Signal2D with shape (N, nkx, nky)."""
        import hyperspy.api as hs
        win = stem_4d_dataset["window"]
        nav, sig = win.plots
        source_signal = sig.plot_state.current_signal
        nkx, nky = source_signal.axes_manager.signal_shape

        n_before = len(win.signal_trees)
        tb, lp_widget, action_name, caret_box, roi, profile_window, sum_window = _add_line_profile_on_nav(qtbot, win)
        sum_plot = sum_window.plots[0]

        roi.sigRegionChangeFinished.emit(roi)
        qtbot.waitUntil(
            lambda: (
                sum_plot.current_data is not None
                and not isinstance(sum_plot.current_data, __import__('distributed').Future)
            ),
            timeout=10000,
        )
        qtbot.waitUntil(lambda: sum_window.title_bar.commit_button.isEnabled(), timeout=3000)

        sum_window.title_bar.commit_button.click()
        qtbot.waitUntil(lambda: len(win.signal_trees) == n_before + 1, timeout=15000)

        new_signal = win.signal_trees[n_before].root
        assert isinstance(new_signal, hs.signals.Signal2D), (
            f"Expected Signal2D, got {type(new_signal)}"
        )
        assert new_signal.data.ndim == 3
        assert new_signal.data.shape[1] == nky
        assert new_signal.data.shape[2] == nkx

    def test_committed_signal_nav_axis_scale(self, qtbot, stem_4d_dataset):
        """Nav axis scale of committed signal must match source nav pixel scale."""
        win = stem_4d_dataset["window"]
        nav, sig = win.plots
        source_signal = sig.plot_state.current_signal

        n_before = len(win.signal_trees)
        tb, lp_widget, action_name, caret_box, roi, profile_window, sum_window = _add_line_profile_on_nav(qtbot, win)
        sum_plot = sum_window.plots[0]

        roi.sigRegionChangeFinished.emit(roi)
        qtbot.waitUntil(
            lambda: sum_plot.current_data is not None
            and not isinstance(sum_plot.current_data, __import__('distributed').Future),
            timeout=10000,
        )
        qtbot.waitUntil(lambda: sum_window.title_bar.commit_button.isEnabled(), timeout=3000)
        sum_window.title_bar.commit_button.click()
        qtbot.waitUntil(lambda: len(win.signal_trees) == n_before + 1, timeout=15000)

        new_signal = win.signal_trees[n_before].root
        src_scale = abs(source_signal.axes_manager.navigation_axes[0].scale)
        committed_scale = abs(new_signal.axes_manager.navigation_axes[0].scale)
        assert abs(committed_scale - src_scale) / max(src_scale, 1e-10) < 0.01, (
            f"Nav axis scale mismatch: committed={committed_scale}, source={src_scale}"
        )

    def test_committed_signal_has_correct_nav_units(self, qtbot, stem_4d_dataset):
        """Nav axis units of committed signal must match source nav axis units."""
        win = stem_4d_dataset["window"]
        nav, sig = win.plots
        source_signal = sig.plot_state.current_signal
        src_units = source_signal.axes_manager.navigation_axes[0].units

        n_before = len(win.signal_trees)
        tb, lp_widget, action_name, caret_box, roi, profile_window, sum_window = _add_line_profile_on_nav(qtbot, win)
        sum_plot = sum_window.plots[0]

        roi.sigRegionChangeFinished.emit(roi)
        qtbot.waitUntil(
            lambda: sum_plot.current_data is not None
            and not isinstance(sum_plot.current_data, __import__('distributed').Future),
            timeout=10000,
        )
        qtbot.waitUntil(lambda: sum_window.title_bar.commit_button.isEnabled(), timeout=3000)
        sum_window.title_bar.commit_button.click()
        qtbot.waitUntil(lambda: len(win.signal_trees) == n_before + 1, timeout=15000)

        new_signal = win.signal_trees[n_before].root
        committed_units = new_signal.axes_manager.navigation_axes[0].units
        assert committed_units == src_units, (
            f"Units mismatch: committed='{committed_units}', source='{src_units}'"
        )

    def test_width_gt_1_committed_signal_shape_unchanged(self, qtbot, stem_4d_dataset):
        """Width > 1 changes the strip averaged but not the output shape (N, nkx, nky)."""
        win = stem_4d_dataset["window"]
        n_before = len(win.plot_subwindows)
        tb, lp_widget, action_name, caret_box, roi, profile_window, sum_window = _add_line_profile_on_nav(qtbot, win)
        sum_plot = sum_window.plots[0]

        # Set width > 1
        width_widget = caret_box.get_parameter_widget("width")
        width_widget.setText("3")

        n_trees_before = len(win.signal_trees[0:1])
        n_signal_trees = len(win.signal_trees)
        roi.sigRegionChangeFinished.emit(roi)
        qtbot.waitUntil(
            lambda: sum_plot.current_data is not None
            and not isinstance(sum_plot.current_data, __import__('distributed').Future),
            timeout=10000,
        )
        qtbot.waitUntil(lambda: sum_window.title_bar.commit_button.isEnabled(), timeout=3000)
        sum_window.title_bar.commit_button.click()
        qtbot.waitUntil(lambda: len(win.signal_trees) == n_signal_trees + 1, timeout=15000)

        new_signal = win.signal_trees[n_signal_trees].root
        assert new_signal.data.ndim == 3, "Width > 1 must still produce 3D signal"


def test_preview_window_hidden_when_other_signal_tree_active(qtbot, stem_4d_dataset):
    """Preview windows are hidden when a different SignalTree's window is active."""
    win = stem_4d_dataset["window"]
    nav_window = stem_4d_dataset["subwindows"][0]
    win.mdi_area.setActiveSubWindow(nav_window)
    qtbot.wait(100)
    n_before = len(win.plot_subwindows)
    _add_line_profile_on_signal(qtbot, win)
    qtbot.wait(100)
    preview_windows = [pw for pw in win.plot_subwindows[n_before:]]

    # Create a second signal tree so there's an "other" active window
    import hyperspy.api as hs
    import numpy as np
    sig2 = hs.signals.Signal2D(np.zeros((64, 64)))
    win.add_signal(sig2)
    qtbot.wait(200)
    # activate the new signal's window
    other_window = win.plot_subwindows[-1]
    win.mdi_area.setActiveSubWindow(other_window)
    qtbot.wait(100)

    for pw in preview_windows:
        assert not pw.isVisible(), f"Preview window {pw} should be hidden"


def test_preview_window_shown_when_owner_signal_tree_active(qtbot, stem_4d_dataset):
    """Preview windows reappear when their SignalTree becomes active again."""
    win = stem_4d_dataset["window"]
    nav_window = stem_4d_dataset["subwindows"][0]
    win.mdi_area.setActiveSubWindow(nav_window)
    qtbot.wait(100)
    n_before = len(win.plot_subwindows)
    _add_line_profile_on_signal(qtbot, win)
    qtbot.wait(100)
    preview_windows = [pw for pw in win.plot_subwindows[n_before:]]

    # Switch away
    import hyperspy.api as hs
    import numpy as np
    sig2 = hs.signals.Signal2D(np.zeros((64, 64)))
    win.add_signal(sig2)
    qtbot.wait(200)
    other_window = win.plot_subwindows[-1]
    win.mdi_area.setActiveSubWindow(other_window)
    qtbot.wait(100)

    # Switch back
    win.mdi_area.setActiveSubWindow(nav_window)
    qtbot.wait(100)

    for pw in preview_windows:
        assert pw.isVisible(), f"Preview window {pw} should be visible"


def test_core_windows_background_opacity_when_other_tree_active(qtbot, stem_4d_dataset):
    """Core/nav windows of inactive SignalTree get 65% opacity, not hidden."""
    win = stem_4d_dataset["window"]
    nav_window = stem_4d_dataset["subwindows"][0]

    import hyperspy.api as hs
    import numpy as np
    sig2 = hs.signals.Signal2D(np.zeros((64, 64)))
    win.add_signal(sig2)
    qtbot.wait(200)
    other_window = win.plot_subwindows[-1]
    # Explicitly trigger 3-state visibility with the other window's tree as active
    win.on_subwindow_activated(other_window)

    # nav_window belongs to first signal tree — should be dimmed, not hidden
    from PySide6.QtWidgets import QGraphicsOpacityEffect
    assert nav_window.isVisible(), "Core window must remain visible (just dimmed)"
    effect = nav_window.graphicsEffect()
    assert isinstance(effect, QGraphicsOpacityEffect), (
        f"Expected QGraphicsOpacityEffect on nav_window, got {effect}"
    )
    assert abs(effect.opacity() - 0.65) < 0.01, (
        f"Expected 65% opacity effect, got {effect.opacity()}"
    )


def test_preview_window_has_owner_plot_window(qtbot, stem_4d_dataset):
    """Preview windows created by line profile must have owner_plot_window set."""
    win = stem_4d_dataset["window"]
    n_before = len(win.plot_subwindows)
    _add_line_profile_on_signal(qtbot, win)
    new_windows = win.plot_subwindows[n_before:]
    assert len(new_windows) > 0, "Expected at least one new preview window"
    for pw in new_windows:
        assert pw.owner_plot_window is not None, (
            f"Preview window {pw} missing owner_plot_window"
        )


class TestLineProfileAxisScale:
    """Dedicated axis scale/units correctness with synthetic data having known axes."""

    def _make_4d_signal_with_known_axes(self):
        """4D STEM signal with explicitly set nav and signal axes."""
        import hyperspy.api as hs
        data = np.ones((6, 6, 8, 8), dtype=np.float32)
        sig = hs.signals.Signal2D(data)
        sig.axes_manager.navigation_axes[0].scale = 0.5
        sig.axes_manager.navigation_axes[0].units = "nm"
        sig.axes_manager.navigation_axes[0].name = "x"
        sig.axes_manager.navigation_axes[1].scale = 0.5
        sig.axes_manager.navigation_axes[1].units = "nm"
        sig.axes_manager.navigation_axes[1].name = "y"
        sig.axes_manager.signal_axes[0].scale = 0.1
        sig.axes_manager.signal_axes[0].units = "1/nm"
        sig.axes_manager.signal_axes[1].scale = 0.1
        sig.axes_manager.signal_axes[1].units = "1/nm"
        return sig

    def test_nav_line_committed_signal_axes_scale_and_units(self, qtbot):
        """Committed nav-line signal: nav axis scale and units match source nav axes."""
        import hyperspy.api as hs
        from spyde.qt.shared import open_window
        win = open_window()
        qtbot.addWidget(win)

        sig = self._make_4d_signal_with_known_axes()
        win.add_signal(sig)
        qtbot.waitUntil(lambda: len(win.mdi_area.subWindowList()) == 2, timeout=5000)

        nav, _ = win.plots
        tb = nav.plot_state.toolbar_bottom
        lp_action = None
        for a in tb.actions():
            if a.text() == "Line Profile":
                lp_action = a
                break
        assert lp_action is not None, "Line Profile not in nav toolbar"
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
        roi = tb.action_widgets["Line Profile"]["plot_items"][action_name]
        sum_window = tb.action_widgets["Line Profile"].get("plot_windows", {}).get(action_name + "_sum")
        assert sum_window is not None
        sum_plot = sum_window.plots[0]

        roi.sigRegionChangeFinished.emit(roi)
        qtbot.waitUntil(
            lambda: sum_plot.current_data is not None
            and not isinstance(sum_plot.current_data, __import__('distributed').Future),
            timeout=10000,
        )
        qtbot.waitUntil(lambda: sum_window.title_bar.commit_button.isEnabled(), timeout=3000)

        n_before = len(win.signal_trees)
        sum_window.title_bar.commit_button.click()
        qtbot.waitUntil(lambda: len(win.signal_trees) == n_before + 1, timeout=15000)

        committed = win.signal_trees[n_before].root
        nav_ax = committed.axes_manager.navigation_axes[0]
        assert abs(nav_ax.scale - 0.5) < 1e-6, (
            f"Expected nav scale 0.5 nm/px, got {nav_ax.scale}"
        )
        assert nav_ax.units == "nm", f"Expected units 'nm', got '{nav_ax.units}'"

        sig_axes = committed.axes_manager.signal_axes
        assert abs(sig_axes[0].scale - 0.1) < 1e-6, (
            f"Expected signal scale 0.1 1/nm, got {sig_axes[0].scale}"
        )
        assert sig_axes[0].units == "1/nm"

        win.close()
