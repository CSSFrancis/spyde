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
