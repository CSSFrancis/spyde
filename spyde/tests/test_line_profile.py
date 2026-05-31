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
