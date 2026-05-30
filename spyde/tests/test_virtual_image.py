"""Tests for the virtual image compute kernel."""
import numpy as np
import dask.array as da
import pytest

from distributed import Future


class TestVirtualImageKernel:
    @pytest.fixture(autouse=True)
    def client(self, stem_4d_dataset):
        self.win = stem_4d_dataset["window"]
        self.client = self.win.client

    def _mask(self, nkx=8, nky=8):
        mask = np.zeros((nkx, nky), dtype=np.float32)
        mask[2:6, 2:6] = 1.0
        return mask

    def test_4d_output_shape(self):
        from spyde.drawing.update_functions import compute_virtual_image_kernel
        data = da.ones((4, 4, 8, 8), dtype=np.float32, chunks=(2, 2, 8, 8))
        mask = self._mask()
        future = compute_virtual_image_kernel(data, mask, self.client, None)
        assert isinstance(future, Future)
        result = future.result()
        assert result.shape == (4, 4)

    def test_4d_values_match_tensordot_reference(self):
        from spyde.drawing.update_functions import compute_virtual_image_kernel
        rng = np.random.default_rng(0)
        data_np = rng.random((4, 4, 8, 8)).astype(np.float32)
        mask = self._mask()
        data = da.from_array(data_np, chunks=(2, 2, 8, 8))
        future = compute_virtual_image_kernel(data, mask, self.client, None)
        result = future.result()
        expected = np.tensordot(data_np, mask, axes=([2, 3], [0, 1]))
        np.testing.assert_allclose(result, expected, rtol=1e-5)

    def test_3d_input(self):
        from spyde.drawing.update_functions import compute_virtual_image_kernel
        data = da.ones((4, 8, 8), dtype=np.float32, chunks=(2, 8, 8))
        mask = self._mask()
        future = compute_virtual_image_kernel(data, mask, self.client, None)
        result = future.result()
        assert result.shape == (4,)

    def test_5d_input(self):
        from spyde.drawing.update_functions import compute_virtual_image_kernel
        data = da.ones((2, 4, 4, 8, 8), dtype=np.float32, chunks=(1, 2, 2, 8, 8))
        mask = self._mask()
        future = compute_virtual_image_kernel(data, mask, self.client, None)
        result = future.result()
        assert result.shape == (2, 4, 4)

    def test_6d_input(self):
        from spyde.drawing.update_functions import compute_virtual_image_kernel
        data = da.ones((2, 3, 4, 4, 8, 8), dtype=np.float32, chunks=(1, 1, 2, 2, 8, 8))
        mask = self._mask()
        future = compute_virtual_image_kernel(data, mask, self.client, None)
        result = future.result()
        assert result.shape == (2, 3, 4, 4)

    def test_numpy_input_works(self):
        from spyde.drawing.update_functions import compute_virtual_image_kernel
        data_np = np.ones((4, 4, 8, 8), dtype=np.float32)
        mask = self._mask()
        data = da.from_array(data_np)
        future = compute_virtual_image_kernel(data, mask, self.client, None)
        result = future.result()
        assert result.shape == (4, 4)

    def test_gpu_annotation_branch_returns_future(self):
        from spyde.drawing.update_functions import compute_virtual_image_kernel
        data = da.ones((4, 4, 8, 8), dtype=np.float32, chunks=(2, 2, 8, 8))
        mask = self._mask()
        # Pass a fake address — annotation is set on the graph but scheduling
        # falls through to CPU workers when no GPU worker matches.
        future = compute_virtual_image_kernel(data, mask, self.client, "tcp://fake:8786")
        assert isinstance(future, Future)
        result = future.result()
        assert result.shape == (4, 4)


class TestGPUWorkerSetup:
    def test_probe_gpus_returns_zero_when_absent(self):
        """_probe_gpus returns 0 when nvidia-smi is not found."""
        import unittest.mock as mock
        from spyde.__main__ import _probe_gpus
        with mock.patch("spyde.__main__.subprocess.run", side_effect=FileNotFoundError):
            assert _probe_gpus() == 0

    def test_probe_gpus_returns_zero_on_timeout(self):
        import unittest.mock as mock
        import subprocess
        from spyde.__main__ import _probe_gpus
        with mock.patch("spyde.__main__.subprocess.run", side_effect=subprocess.TimeoutExpired("nvidia-smi", 3)):
            assert _probe_gpus() == 0

    def test_probe_gpus_returns_count_from_mocked_output(self):
        import unittest.mock as mock
        from spyde.__main__ import _probe_gpus
        fake_result = mock.Mock()
        fake_result.returncode = 0
        fake_result.stdout = b"NVIDIA GeForce RTX 3080\nNVIDIA GeForce RTX 3080\n"
        with mock.patch("spyde.__main__.subprocess.run", return_value=fake_result):
            assert _probe_gpus() == 2

    def test_gpu_worker_address_is_none_when_no_gpu(self, stem_4d_dataset):
        """_gpu_worker_address is None when no GPU is present (default on CI)."""
        win = stem_4d_dataset["window"]
        assert hasattr(win, "_gpu_worker_address")
        import subprocess
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, timeout=3,
            )
            has_gpu = r.returncode == 0 and r.stdout.strip()
        except Exception:
            has_gpu = False
        if not has_gpu:
            assert win._gpu_worker_address is None


class TestComputeStatusIndicator:
    def test_import(self):
        from spyde.qt.compute_status_indicator import ComputeStatusIndicator
        assert ComputeStatusIndicator is not None

    def test_states(self, qtbot):
        from spyde.qt.compute_status_indicator import ComputeStatusIndicator
        w = ComputeStatusIndicator()
        qtbot.addWidget(w)
        w.show()

        w.set_idle()
        assert w._state == "idle"

        w.set_computing(total_tasks=10)
        assert w._state == "computing"
        assert w._total_tasks == 10

        w.update_progress(5)
        assert w._completed_tasks == 5

        w.set_done()
        assert w._state == "done"


class TestVirtualImageLivePreview:

    def _get_vi_action(self, sig_plot):
        tb = sig_plot.plot_state.toolbar_bottom
        for a in tb.actions():
            if a.text() == "Virtual Imaging":
                return a, tb
        raise AssertionError("Virtual Imaging action not found")

    def _add_detector(self, qtbot, win):
        nav, sig = win.plots
        vi_action, tb = self._get_vi_action(sig)
        vi_action.trigger()
        qtbot.wait(200)
        vi_widget = tb.action_widgets["Virtual Imaging"]["widget"]
        for a in vi_widget.actions():
            if a.text() == "Add Virtual Image":
                a.trigger()
                break
        qtbot.wait(300)
        new_action = vi_widget.actions()[-1]
        new_action.trigger()
        qtbot.wait(300)
        return tb, vi_widget

    def test_add_virtual_image_spawns_plot_window(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        n_before = len(win.plot_subwindows)
        self._add_detector(qtbot, win)
        assert len(win.plot_subwindows) == n_before + 1

    def test_roi_move_triggers_computation(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        tb, vi_widget = self._add_detector(qtbot, win)
        roi = list(tb.action_widgets["Virtual Imaging"]["plot_items"].values())[0]
        roi.sigRegionChangeFinished.emit(roi)
        qtbot.wait(5000)
        child_plot = win.plot_subwindows[-1].plots[0]
        assert child_plot.current_data is not None
        assert not isinstance(child_plot.current_data, __import__('distributed').Future)

    def test_virtual_imaging_toggle_hides_plot_window(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        nav, sig = win.plots[:2]
        tb, vi_widget = self._add_detector(qtbot, win)
        vi_action, _ = self._get_vi_action(sig)
        child_window = win.plot_subwindows[-1]
        roi = list(tb.action_widgets["Virtual Imaging"]["plot_items"].values())[0]

        assert roi.isVisible()
        assert child_window.isVisible()

        vi_action.trigger()
        qtbot.wait(200)
        assert not roi.isVisible()
        assert not child_window.isVisible()

        vi_action.trigger()
        qtbot.wait(200)
        assert roi.isVisible()
        assert child_window.isVisible()


class TestVirtualImageCommit:

    def _setup(self, qtbot, win):
        nav, sig = win.plots
        tb = sig.plot_state.toolbar_bottom
        for a in tb.actions():
            if a.text() == "Virtual Imaging":
                vi_action = a
                break
        vi_action.trigger()
        qtbot.wait(200)
        vi_widget = tb.action_widgets["Virtual Imaging"]["widget"]
        for a in vi_widget.actions():
            if a.text() == "Add Virtual Image":
                a.trigger()
                break
        qtbot.wait(300)
        new_action = vi_widget.actions()[-1]
        new_action.trigger()
        qtbot.wait(300)
        action_name = new_action.text()
        caret_box = vi_widget.action_widgets[action_name]["widget"]

        roi = list(tb.action_widgets["Virtual Imaging"]["plot_items"].values())[0]
        roi.sigRegionChangeFinished.emit(roi)
        qtbot.wait(5000)
        return caret_box

    def test_commit_button_disabled_before_computation(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        nav, sig = win.plots
        tb = sig.plot_state.toolbar_bottom
        for a in tb.actions():
            if a.text() == "Virtual Imaging":
                vi_action = a
                break
        vi_action.trigger()
        qtbot.wait(200)
        vi_widget = tb.action_widgets["Virtual Imaging"]["widget"]
        for a in vi_widget.actions():
            if a.text() == "Add Virtual Image":
                a.trigger()
                break
        qtbot.wait(300)
        new_action = vi_widget.actions()[-1]
        new_action.trigger()
        qtbot.wait(300)
        action_name = new_action.text()
        caret_box = vi_widget.action_widgets[action_name]["widget"]
        commit_btn = caret_box.get_parameter_widget("commit_button")
        assert not commit_btn.isEnabled()

    def test_commit_adds_signal_tree(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        n_before = len(win.signal_trees)
        caret_box = self._setup(qtbot, win)
        commit_btn = caret_box.get_parameter_widget("commit_button")
        assert commit_btn.isEnabled(), "Commit button should be enabled after first computation"
        commit_btn.click()
        qtbot.wait(8000)
        assert len(win.signal_trees) == n_before + 1

    def test_committed_signal_is_virtual_dark_field(self, qtbot, stem_4d_dataset):
        from pyxem.signals import VirtualDarkFieldImage
        win = stem_4d_dataset["window"]
        n_before = len(win.signal_trees)
        caret_box = self._setup(qtbot, win)
        commit_btn = caret_box.get_parameter_widget("commit_button")
        commit_btn.click()
        qtbot.wait(8000)
        new_tree = win.signal_trees[n_before]
        assert isinstance(new_tree.root, VirtualDarkFieldImage)
