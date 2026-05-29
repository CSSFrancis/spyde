# Virtual Image Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the full virtual detector → live GPU-accelerated preview → commit-as-signal-tree workflow for 3D/4D/5D/6D STEM datasets.

**Architecture:** ROI placed on the diffraction plot triggers `roi_to_mask()` + `compute_virtual_image_kernel()` on `sigRegionChangeFinished`; the result Future is polled by the existing `PlotUpdateWorker`; a `ComputeStatusIndicator` widget shows per-chunk progress. GPU support is via a dedicated dask worker with `resources={"GPU": 1}`, probed at startup via `nvidia-smi`. Committing runs the same kernel and calls `MainWindow.add_signal()` from the dask callback thread via `QMetaObject.invokeMethod`.

**Tech Stack:** PySide6, pyqtgraph, dask.distributed, numpy, hyperspy/pyxem (`VirtualDarkFieldImage`), dask.array (tensordot)

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `spyde/drawing/update_functions.py` | Modify | Add `compute_virtual_image_kernel()` |
| `spyde/actions/pyxem.py` | Modify | Add `roi_to_mask()`, `_roi_metadata()`, wire `add_virtual_image()` with live/commit logic |
| `spyde/qt/compute_status_indicator.py` | Create | `ComputeStatusIndicator` widget (QPainter arc) |
| `spyde/drawing/plots/plot_window.py` | Modify | Anchor `ComputeStatusIndicator` in `resizeEvent` |
| `spyde/__main__.py` | Modify | `_probe_gpus()`, GPU worker in `DaskClusterWorker`, `self._gpu_worker_address`, `_add_signal_from_thread` slot |
| `spyde/conftest.py` | Modify | Add `gpu_available` session fixture |
| `spyde/tests/test_actions.py` | Modify | Extend `TestActions` with `TestVirtualImageROI` class |
| `spyde/tests/test_virtual_image.py` | Create | `TestVirtualImageKernel`, `TestVirtualImageLivePreview`, `TestVirtualImageCommit`, `TestGPUWorkerSetup`, `TestVirtualImageKernelGPU` |

---

## Task 1: `compute_virtual_image_kernel` in `update_functions.py`

**Files:**
- Modify: `spyde/drawing/update_functions.py`
- Test: `spyde/tests/test_virtual_image.py` (create)

- [ ] **Step 1: Write failing tests**

Create `spyde/tests/test_virtual_image.py`:

```python
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

    def test_returns_future(self):
        from spyde.drawing.update_functions import compute_virtual_image_kernel
        data = da.ones((4, 4, 8, 8), dtype=np.float32, chunks=(2, 2, 8, 8))
        mask = self._mask()
        future = compute_virtual_image_kernel(data, mask, self.client, None)
        assert isinstance(future, Future)
```

- [ ] **Step 2: Run tests to confirm they fail**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_virtual_image.py::TestVirtualImageKernel -v
```

Expected: `ImportError` or `AttributeError` — `compute_virtual_image_kernel` does not exist yet.

- [ ] **Step 3: Implement `compute_virtual_image_kernel`**

Add to `spyde/drawing/update_functions.py` (after the existing imports, before `write_shared_array`):

```python
import dask
import dask.array as da
import distributed
```

Then add this function at the bottom of `spyde/drawing/update_functions.py`:

```python
def compute_virtual_image_kernel(
    data: da.Array,
    mask: np.ndarray,
    client: distributed.Client,
    gpu_worker_address: str | None,
) -> distributed.Future:
    """
    Compute a virtual image by contracting the last two axes of data with mask.

    Works for any number of navigation axes (3D, 4D, 5D, 6D datasets).
    Signal axes must be the last two (HyperSpy convention).

    Parameters
    ----------
    data : dask array, shape (...nav..., nkx, nky)
    mask : float32 numpy array, shape (nkx, nky)
    client : dask distributed Client
    gpu_worker_address : str or None
        GPU worker address; None means CPU-only fallback.

    Returns
    -------
    distributed.Future resolving to np.ndarray of shape (...nav...)
    """
    ndim = data.ndim
    sig_axes = [ndim - 2, ndim - 1]
    da_mask = da.from_array(mask, chunks=mask.shape)
    resources = {"GPU": 1} if gpu_worker_address else {}
    with dask.annotate(resources=resources):
        result = da.tensordot(data, da_mask, axes=(sig_axes, [0, 1]))
    return client.compute(result)
```

- [ ] **Step 4: Run tests to confirm they pass**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_virtual_image.py::TestVirtualImageKernel -v
```

Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add spyde/drawing/update_functions.py spyde/tests/test_virtual_image.py
git commit -m "feat: add compute_virtual_image_kernel for N-D STEM datasets"
```

---

## Task 2: `ComputeStatusIndicator` widget

**Files:**
- Create: `spyde/qt/compute_status_indicator.py`

The widget is a 24×24 px transparent overlay drawn entirely in `paintEvent`. It has four states: idle (small green filled circle), computing (grey ring with clockwise arc), done (full green circle, auto-transitions to idle after 500 ms).

- [ ] **Step 1: Write failing import test**

Add to `spyde/tests/test_virtual_image.py`:

```python
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
```

- [ ] **Step 2: Run to confirm failure**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_virtual_image.py::TestComputeStatusIndicator -v
```

Expected: `ModuleNotFoundError` for `compute_status_indicator`.

- [ ] **Step 3: Implement `ComputeStatusIndicator`**

Create `spyde/qt/compute_status_indicator.py`:

```python
from PySide6 import QtWidgets, QtCore, QtGui


class ComputeStatusIndicator(QtWidgets.QWidget):
    """24×24 px transparent overlay showing computation progress.

    States:
      idle      — small filled green circle
      computing — grey ring; clockwise arc fills proportional to completed/total tasks
      done      — fully filled green circle; auto-transitions to idle after 500 ms
    """

    SIZE = 24

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self._state = "idle"
        self._total_tasks = 1
        self._completed_tasks = 0
        self._done_timer = QtCore.QTimer(self)
        self._done_timer.setSingleShot(True)
        self._done_timer.timeout.connect(self.set_idle)

    def set_idle(self):
        self._state = "idle"
        self._done_timer.stop()
        self.update()

    def set_computing(self, total_tasks: int = 1):
        self._state = "computing"
        self._total_tasks = max(1, total_tasks)
        self._completed_tasks = 0
        self._done_timer.stop()
        self.update()

    def set_done(self):
        self._state = "done"
        self.update()
        self._done_timer.start(500)

    def update_progress(self, completed: int):
        self._completed_tasks = completed
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        cx, cy, r = self.SIZE / 2, self.SIZE / 2, self.SIZE / 2 - 3

        if self._state == "idle":
            small_r = r * 0.4
            painter.setBrush(QtGui.QColor(0, 200, 0))
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.drawEllipse(
                QtCore.QRectF(cx - small_r, cy - small_r, small_r * 2, small_r * 2)
            )

        elif self._state == "computing":
            # Grey background ring
            pen = QtGui.QPen(QtGui.QColor(120, 120, 120), 3)
            painter.setPen(pen)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            rect = QtCore.QRectF(cx - r, cy - r, r * 2, r * 2)
            painter.drawEllipse(rect)
            # Green arc: Qt uses 1/16th degrees, start at 90° (top), clockwise
            frac = self._completed_tasks / self._total_tasks
            span = int(frac * 360 * 16)
            if span > 0:
                arc_pen = QtGui.QPen(QtGui.QColor(0, 200, 0), 3)
                painter.setPen(arc_pen)
                painter.drawArc(rect, 90 * 16, -span)  # negative = clockwise

        elif self._state == "done":
            painter.setBrush(QtGui.QColor(0, 200, 0))
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.drawEllipse(QtCore.QRectF(cx - r, cy - r, r * 2, r * 2))

        painter.end()
```

- [ ] **Step 4: Run tests to confirm they pass**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_virtual_image.py::TestComputeStatusIndicator -v
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add spyde/qt/compute_status_indicator.py spyde/tests/test_virtual_image.py
git commit -m "feat: add ComputeStatusIndicator widget"
```

---

## Task 3: `roi_to_mask` in `spyde/actions/pyxem.py`

**Files:**
- Modify: `spyde/actions/pyxem.py`
- Modify: `spyde/tests/test_actions.py`

`roi_to_mask` converts a PyQtGraph ROI placed on the diffraction pattern to a `float32` boolean mask in pixel index space. It uses the same `inverted_transform` technique as `RectangleSelector._get_selected_indices` in `selector2d.py:177`.

- [ ] **Step 1: Write failing tests**

Add to `spyde/tests/test_actions.py`:

```python
import numpy as np
import hyperspy.api as hs
import dask.array as da
from pyqtgraph import CircleROI, RectROI
from spyde.external.pyqtgraph.ring_roi import RingROI


class TestVirtualImageROI:
    """Tests for roi_to_mask."""

    def _make_signal(self):
        """4D STEM signal with known signal axes."""
        data = da.zeros((4, 4, 8, 8), dtype=np.float32)
        sig = hs.signals.Signal2D(data)
        sig.axes_manager.signal_axes[0].scale = 1.0
        sig.axes_manager.signal_axes[0].offset = 0.0
        sig.axes_manager.signal_axes[1].scale = 1.0
        sig.axes_manager.signal_axes[1].offset = 0.0
        return sig

    def test_circle_roi_mask_shape(self):
        from spyde.actions.pyxem import roi_to_mask
        sig = self._make_signal()
        roi = CircleROI(pos=(2, 2), size=(4, 4))
        mask = roi_to_mask(roi, sig)
        assert mask.shape == (8, 8)

    def test_circle_roi_mask_dtype(self):
        from spyde.actions.pyxem import roi_to_mask
        sig = self._make_signal()
        roi = CircleROI(pos=(2, 2), size=(4, 4))
        mask = roi_to_mask(roi, sig)
        assert mask.dtype == np.float32

    def test_circle_roi_center_pixel_is_one(self):
        from spyde.actions.pyxem import roi_to_mask
        sig = self._make_signal()
        # Circle centered at pixel (4,4), radius 2 pixels
        roi = CircleROI(pos=(2, 2), size=(4, 4))
        mask = roi_to_mask(roi, sig)
        assert mask[4, 4] == 1.0, f"Center pixel should be 1.0, got {mask[4,4]}"

    def test_circle_roi_outside_is_zero(self):
        from spyde.actions.pyxem import roi_to_mask
        sig = self._make_signal()
        roi = CircleROI(pos=(2, 2), size=(4, 4))
        mask = roi_to_mask(roi, sig)
        assert mask[0, 0] == 0.0, f"Corner pixel should be 0.0, got {mask[0,0]}"

    def test_rect_roi_mask_shape(self):
        from spyde.actions.pyxem import roi_to_mask
        sig = self._make_signal()
        roi = RectROI(pos=(1, 1), size=(4, 4))
        mask = roi_to_mask(roi, sig)
        assert mask.shape == (8, 8)

    def test_rect_roi_dtype(self):
        from spyde.actions.pyxem import roi_to_mask
        sig = self._make_signal()
        roi = RectROI(pos=(1, 1), size=(4, 4))
        mask = roi_to_mask(roi, sig)
        assert mask.dtype == np.float32

    def test_ring_roi_mask_shape(self):
        from spyde.actions.pyxem import roi_to_mask
        sig = self._make_signal()
        roi = RingROI(center=(2, 2), inner_rad=1, outer_rad=3)
        mask = roi_to_mask(roi, sig)
        assert mask.shape == (8, 8)

    def test_ring_roi_center_excluded(self):
        from spyde.actions.pyxem import roi_to_mask
        sig = self._make_signal()
        # inner_rad=2, outer_rad=3 → center pixel (4,4) is inside inner radius
        roi = RingROI(center=(2, 2), inner_rad=2, outer_rad=3)
        mask = roi_to_mask(roi, sig)
        assert mask[4, 4] == 0.0, f"Center pixel should be 0.0 for ring ROI, got {mask[4,4]}"
```

- [ ] **Step 2: Run to confirm failure**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_actions.py::TestVirtualImageROI -v
```

Expected: `ImportError` — `roi_to_mask` does not exist yet.

- [ ] **Step 3: Implement `roi_to_mask` and `_roi_metadata`**

Add to `spyde/actions/pyxem.py`, after the existing imports:

```python
import numpy as np
from PySide6 import QtCore
```

Then add these two functions before `center_zero_beam`:

```python
def roi_to_mask(roi, signal) -> np.ndarray:
    """Convert a PyQtGraph ROI to a float32 mask over the signal axes.

    Uses the signal axes scale/offset to build a pixel coordinate grid.
    Returns shape (nkx, nky), dtype float32, values 0.0 or 1.0.
    """
    from pyqtgraph import CircleROI, RectROI
    from spyde.external.pyqtgraph.ring_roi import RingROI

    sig_axes = signal.axes_manager.signal_axes  # [kx_axis, ky_axis] — last two
    nkx = sig_axes[1].size
    nky = sig_axes[0].size
    scale_x = sig_axes[1].scale
    scale_y = sig_axes[0].scale
    offset_x = sig_axes[1].offset
    offset_y = sig_axes[0].offset

    # Build pixel-index arrays matching signal coordinate space
    # signal_axes[0] is the "row" axis (ky), signal_axes[1] is "col" (kx)
    rows = np.arange(nkx)  # kx pixel indices
    cols = np.arange(nky)  # ky pixel indices
    col_grid, row_grid = np.meshgrid(cols, rows)

    # Convert pixel indices to data coordinates
    x_data = col_grid * scale_x + offset_x
    y_data = row_grid * scale_y + offset_y

    if isinstance(roi, RingROI):
        # RingROI: inner circle = rois[0], outer circle = rois[1]
        inner_roi = roi.rois[0]
        outer_roi = roi.rois[1]
        inner_pos = inner_roi.pos()
        inner_size = inner_roi.size()
        outer_pos = outer_roi.pos()
        outer_size = outer_roi.size()
        # centers in data coords
        cx = outer_pos.x() + outer_size.x() / 2
        cy = outer_pos.y() + outer_size.y() / 2
        inner_r = inner_size.x() / 2
        outer_r = outer_size.x() / 2
        dist2 = (x_data - cx) ** 2 + (y_data - cy) ** 2
        mask_bool = (dist2 >= inner_r ** 2) & (dist2 <= outer_r ** 2)

    elif isinstance(roi, CircleROI):
        pos = roi.pos()
        size = roi.size()
        cx = pos.x() + size.x() / 2
        cy = pos.y() + size.y() / 2
        r = size.x() / 2
        dist2 = (x_data - cx) ** 2 + (y_data - cy) ** 2
        mask_bool = dist2 <= r ** 2

    elif isinstance(roi, RectROI):
        pos = roi.pos()
        size = roi.size()
        x0, x1 = pos.x(), pos.x() + size.x()
        y0, y1 = pos.y(), pos.y() + size.y()
        mask_bool = (x_data >= x0) & (x_data <= x1) & (y_data >= y0) & (y_data <= y1)

    else:
        raise TypeError(f"Unsupported ROI type: {type(roi)}")

    return mask_bool.astype(np.float32)


def _roi_metadata(roi) -> dict:
    """Extract ROI geometry as a plain dict for signal metadata storage."""
    from pyqtgraph import CircleROI, RectROI
    from spyde.external.pyqtgraph.ring_roi import RingROI

    if isinstance(roi, RingROI):
        return {
            "type": "ring",
            "center": (roi.rois[1].pos().x() + roi.rois[1].size().x() / 2,
                       roi.rois[1].pos().y() + roi.rois[1].size().y() / 2),
            "inner_radius": roi.rois[0].size().x() / 2,
            "outer_radius": roi.rois[1].size().x() / 2,
        }
    elif isinstance(roi, CircleROI):
        return {
            "type": "disk",
            "center": (roi.pos().x() + roi.size().x() / 2,
                       roi.pos().y() + roi.size().y() / 2),
            "radius": roi.size().x() / 2,
        }
    elif isinstance(roi, RectROI):
        return {
            "type": "rectangle",
            "pos": (roi.pos().x(), roi.pos().y()),
            "size": (roi.size().x(), roi.size().y()),
        }
    return {}
```

- [ ] **Step 4: Run tests to confirm they pass**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_actions.py::TestVirtualImageROI -v
```

Expected: all 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add spyde/actions/pyxem.py spyde/tests/test_actions.py
git commit -m "feat: add roi_to_mask and _roi_metadata for virtual detector workflow"
```

---

## Task 4: GPU worker probe and `_add_signal_from_thread` in `__main__.py`

**Files:**
- Modify: `spyde/__main__.py`
- Modify: `spyde/conftest.py`
- Modify: `spyde/tests/test_virtual_image.py`

- [ ] **Step 1: Write failing tests**

Add to `spyde/tests/test_virtual_image.py`:

```python
class TestGPUWorkerSetup:
    def test_probe_gpus_returns_zero_when_absent(self):
        """_probe_gpus returns 0 when nvidia-smi is not found."""
        import unittest.mock as mock
        from spyde.__main__ import _probe_gpus
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            assert _probe_gpus() == 0

    def test_probe_gpus_returns_zero_on_timeout(self):
        import unittest.mock as mock
        import subprocess
        from spyde.__main__ import _probe_gpus
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("nvidia-smi", 3)):
            assert _probe_gpus() == 0

    def test_probe_gpus_returns_count_from_mocked_output(self):
        import unittest.mock as mock
        from spyde.__main__ import _probe_gpus
        fake_result = mock.Mock()
        fake_result.returncode = 0
        fake_result.stdout = b"NVIDIA GeForce RTX 3080\nNVIDIA GeForce RTX 3080\n"
        with mock.patch("subprocess.run", return_value=fake_result):
            assert _probe_gpus() == 2

    def test_gpu_worker_address_is_none_when_no_gpu(self, stem_4d_dataset):
        """_gpu_worker_address is None when no GPU is present (default on CI)."""
        win = stem_4d_dataset["window"]
        assert hasattr(win, "_gpu_worker_address")
        # On a machine without a GPU the address must be None
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
```

- [ ] **Step 2: Run to confirm failure**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_virtual_image.py::TestGPUWorkerSetup -v
```

Expected: `ImportError` — `_probe_gpus` does not exist yet.

- [ ] **Step 3: Add `_probe_gpus` module-level function**

In `spyde/__main__.py`, add after the existing imports (near top, after `import os`):

```python
import subprocess
```

Then add this function before the `DaskClusterWorker` class:

```python
def _probe_gpus() -> int:
    """Return the number of NVIDIA GPUs detected via nvidia-smi. Returns 0 on any failure."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            timeout=3,
        )
        if result.returncode != 0:
            return 0
        lines = [l for l in result.stdout.decode().strip().splitlines() if l.strip()]
        return len(lines)
    except Exception:
        return 0
```

- [ ] **Step 4: Store `_gpu_worker_address` on `MainWindow`**

In `MainWindow.__init__`, after the line `self.histogram = None`, add:

```python
self._gpu_worker_address: str | None = None
```

- [ ] **Step 5: Probe GPU in `DaskClusterWorker.start` and report back**

Currently `DaskClusterWorker.finished` emits `(cluster, client)`. Change the signature to also carry the gpu worker address. Find `DaskClusterWorker` and update it:

```python
class DaskClusterWorker(QtCore.QObject):
    finished = QtCore.Signal(object, object, object)  # cluster, client, gpu_worker_address
    error = QtCore.Signal(Exception)

    def __init__(self, n_workers: int, threads_per_worker: int, parent=None):
        super().__init__(parent)
        self.n_workers = n_workers
        self.threads_per_worker = threads_per_worker
        self._stopped = False

    @QtCore.Slot()
    def start(self):
        if self._stopped:
            return
        try:
            n_gpus = _probe_gpus()
            cluster = LocalCluster(
                n_workers=self.n_workers,
                threads_per_worker=self.threads_per_worker,
            )
            client = Client(cluster)
            gpu_worker_address = None
            if n_gpus > 0:
                import os as _os
                env = dict(_os.environ, CUDA_VISIBLE_DEVICES="0")
                gpu_worker_address = cluster.scheduler_address  # placeholder; real impl below
                # Add a GPU worker to the existing cluster
                worker = cluster.start_worker(
                    resources={"GPU": 1},
                    env=env,
                )
                gpu_worker_address = str(worker)
            self.finished.emit(cluster, client, gpu_worker_address)
        except Exception as e:
            self.error.emit(e)

    @QtCore.Slot()
    def stop(self):
        self._stopped = True
```

**Note on GPU worker:** `LocalCluster.start_worker` is the dask API for adding extra workers at runtime. If `start_worker` is not available in the installed dask version, replace with:

```python
from distributed import Worker
import asyncio
worker = Worker(cluster.scheduler_address, resources={"GPU": 1}, env=env)
gpu_worker_address = worker.address
```

In practice you may need to test which API is available. The important contract is: `gpu_worker_address` is a string address of a worker that has `resources={"GPU": 1}`, or `None`.

- [ ] **Step 6: Wire `_gpu_worker_address` on the finished signal**

Find where `DaskClusterWorker.finished` is connected in `MainWindow.__init__`. It likely reads:

```python
self._dask_worker.finished.connect(self._on_dask_ready)
```

Update `_on_dask_ready` to accept the third argument:

```python
def _on_dask_ready(self, cluster, client, gpu_worker_address=None):
    self.cluster = cluster
    self.client = client
    self._gpu_worker_address = gpu_worker_address
    # ... rest of existing handler ...
```

- [ ] **Step 7: Add `_add_signal_from_thread` slot**

In `MainWindow`, add after `add_signal`:

```python
@QtCore.Slot(object)
def _add_signal_from_thread(self, signal):
    """Thread-safe slot to add a committed virtual image signal."""
    self.add_signal(signal)
```

- [ ] **Step 8: Add `gpu_available` session fixture to `conftest.py`**

```python
import subprocess

@pytest.fixture(scope="session")
def gpu_available() -> bool:
    """True if nvidia-smi detects at least one GPU."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, timeout=3,
        )
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception:
        return False
```

Also add the `gpu` pytest mark to `spyde/conftest.py` or `pytest.ini` / `pyproject.toml` so `pytest -m gpu` works without warnings. Check whether `pyproject.toml` has a `[tool.pytest.ini_options]` section:

```toml
[tool.pytest.ini_options]
markers = [
    "gpu: tests requiring a physical NVIDIA GPU",
]
```

- [ ] **Step 9: Run GPU setup tests**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_virtual_image.py::TestGPUWorkerSetup -v
```

Expected: all 4 tests pass.

- [ ] **Step 10: Commit**

```bash
git add spyde/__main__.py spyde/conftest.py spyde/tests/test_virtual_image.py
git commit -m "feat: add GPU worker probe and _add_signal_from_thread slot"
```

---

## Task 5: Anchor `ComputeStatusIndicator` in `PlotWindow`

**Files:**
- Modify: `spyde/drawing/plots/plot_window.py`

The indicator is a child widget of `PlotWindow`. It must stay at `(8, 8)` from the top-left and be transparent for mouse events. The virtual image live-preview path will create one indicator per virtual detector `PlotWindow`.

- [ ] **Step 1: Add `set_compute_indicator` and `resizeEvent` anchor**

In `PlotWindow`, add an instance attribute in `__init__` after `self.timer = None`:

```python
self._compute_indicator = None  # type: ComputeStatusIndicator | None
```

Add this method:

```python
def set_compute_indicator(self, indicator):
    """Attach a ComputeStatusIndicator and keep it at (8, 8)."""
    from spyde.qt.compute_status_indicator import ComputeStatusIndicator
    self._compute_indicator = indicator
    indicator.setParent(self)
    indicator.move(8, 8)
    indicator.raise_()
    indicator.show()
```

Update `resizeEvent` to reposition the indicator:

```python
def resizeEvent(self, ev: QtGui.QResizeEvent) -> None:
    super().resizeEvent(ev)
    self.reposition_toolbars()
    if self._compute_indicator is not None:
        self._compute_indicator.move(8, 8)
        self._compute_indicator.raise_()
```

- [ ] **Step 2: No separate test needed here** — the indicator will be exercised by the live preview integration tests in Task 6.

- [ ] **Step 3: Commit**

```bash
git add spyde/drawing/plots/plot_window.py
git commit -m "feat: anchor ComputeStatusIndicator to PlotWindow"
```

---

## Task 6: Wire `add_virtual_image` with live preview, progress, and commit

**Files:**
- Modify: `spyde/actions/pyxem.py`
- Modify: `spyde/tests/test_virtual_image.py`

This is the largest task. It replaces the empty `compute_virtual_image` stub and rewires `add_virtual_image` to:
1. Spawn a new `PlotWindow` with a `ComputeStatusIndicator`
2. Connect `sigRegionChangeFinished` → mask → kernel → `PlotUpdateWorker`
3. Poll task progress every 200 ms
4. Add Live toggle and Compute button to caret box
5. Add Commit button; non-blocking commit via `future.add_done_callback`

- [ ] **Step 1: Write failing integration tests**

Add to `spyde/tests/test_virtual_image.py`:

```python
class TestVirtualImageLivePreview:

    def _get_virtual_imaging_action(self, sig_plot):
        toolbar_bottom = sig_plot.plot_state.toolbar_bottom
        for action in toolbar_bottom.actions():
            if action.text() == "Virtual Imaging":
                return action, toolbar_bottom
        raise AssertionError("Virtual Imaging action not found")

    def _add_detector(self, qtbot, win):
        nav, sig = win.plots
        vi_action, toolbar_bottom = self._get_virtual_imaging_action(sig)
        vi_action.trigger()
        qtbot.wait(200)

        vi_widget = toolbar_bottom.action_widgets["Virtual Imaging"]["widget"]
        for action in vi_widget.actions():
            if action.text() == "Add Virtual Image":
                action.trigger()
                break
        qtbot.wait(200)

        # activate the new detector action (last in list)
        new_action = vi_widget.actions()[-1]
        new_action.trigger()
        qtbot.wait(200)
        return toolbar_bottom, vi_widget

    def test_add_virtual_image_spawns_plot_window(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        n_before = len(win.plot_subwindows)
        self._add_detector(qtbot, win)
        assert len(win.plot_subwindows) == n_before + 1

    def test_roi_move_triggers_computation(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        toolbar_bottom, vi_widget = self._add_detector(qtbot, win)

        roi = list(toolbar_bottom.action_widgets["Virtual Imaging"]["plot_items"].values())[0]
        roi.setPos(roi.pos() + roi.size() * 0.1)
        roi.sigRegionChangeFinished.emit(roi)

        qtbot.wait(3000)

        # The child plot (last added) should have non-placeholder data
        child_plot_window = win.plot_subwindows[-1]
        child_plot = child_plot_window.plots[0]
        assert child_plot.current_data is not None
        assert not (child_plot.current_data == 0).all() or not (child_plot.current_data == 1).all()

    def test_virtual_imaging_toggle_hides_roi_and_plot_window(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        toolbar_bottom, vi_widget = self._add_detector(qtbot, win)
        nav, sig = win.plots
        vi_action, _ = self._get_virtual_imaging_action(sig)

        child_window = win.plot_subwindows[-1]
        roi = list(toolbar_bottom.action_widgets["Virtual Imaging"]["plot_items"].values())[0]

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

    def _setup_with_computation(self, qtbot, win):
        """Add a detector, wait for first computation to complete."""
        nav, sig = win.plots
        toolbar_bottom = sig.plot_state.toolbar_bottom
        for action in toolbar_bottom.actions():
            if action.text() == "Virtual Imaging":
                vi_action = action
                break
        vi_action.trigger()
        qtbot.wait(200)

        vi_widget = toolbar_bottom.action_widgets["Virtual Imaging"]["widget"]
        for action in vi_widget.actions():
            if action.text() == "Add Virtual Image":
                action.trigger()
                break
        qtbot.wait(200)
        new_action = vi_widget.actions()[-1]
        new_action.trigger()
        qtbot.wait(200)

        # Fire the ROI to trigger computation
        roi = list(toolbar_bottom.action_widgets["Virtual Imaging"]["plot_items"].values())[0]
        roi.sigRegionChangeFinished.emit(roi)
        qtbot.wait(4000)  # allow computation to finish

        action_name = new_action.text()
        caret_box = vi_widget.action_widgets[action_name]["widget"]
        return caret_box, roi

    def test_commit_button_disabled_before_computation(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        nav, sig = win.plots
        toolbar_bottom = sig.plot_state.toolbar_bottom
        for action in toolbar_bottom.actions():
            if action.text() == "Virtual Imaging":
                vi_action = action
                break
        vi_action.trigger()
        qtbot.wait(200)

        vi_widget = toolbar_bottom.action_widgets["Virtual Imaging"]["widget"]
        for action in vi_widget.actions():
            if action.text() == "Add Virtual Image":
                action.trigger()
                break
        qtbot.wait(200)
        new_action = vi_widget.actions()[-1]
        new_action.trigger()
        qtbot.wait(200)

        action_name = new_action.text()
        caret_box = vi_widget.action_widgets[action_name]["widget"]
        commit_btn = caret_box.get_parameter_widget("commit_button")
        assert not commit_btn.isEnabled()

    def test_commit_adds_signal_tree(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        n_trees_before = len(win.signal_trees)
        caret_box, roi = self._setup_with_computation(qtbot, win)

        commit_btn = caret_box.get_parameter_widget("commit_button")
        assert commit_btn.isEnabled(), "Commit button should be enabled after first computation"
        commit_btn.click()
        qtbot.wait(5000)

        assert len(win.signal_trees) == n_trees_before + 1

    def test_committed_signal_is_virtual_dark_field(self, qtbot, stem_4d_dataset):
        from pyxem.signals import VirtualDarkFieldImage
        win = stem_4d_dataset["window"]
        n_trees_before = len(win.signal_trees)
        caret_box, roi = self._setup_with_computation(qtbot, win)

        commit_btn = caret_box.get_parameter_widget("commit_button")
        commit_btn.click()
        qtbot.wait(5000)

        new_tree = win.signal_trees[n_trees_before]
        assert isinstance(new_tree.root_signal, VirtualDarkFieldImage)
```

- [ ] **Step 2: Run to confirm failure**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_virtual_image.py::TestVirtualImageLivePreview::test_add_virtual_image_spawns_plot_window -v
```

Expected: `AssertionError` — no new `PlotWindow` is spawned (current `add_virtual_image` doesn't create one).

- [ ] **Step 3: Add `_on_virtual_roi_finished` helper and progress poller**

Add to `spyde/actions/pyxem.py` (after imports, before `center_zero_beam`):

```python
from PySide6 import QtCore
import dask


def _start_progress_poll(future, indicator, client, timer_holder: list):
    """Poll dask task progress every 200 ms and update the indicator.

    timer_holder is a single-element list so the timer reference stays alive.
    """
    try:
        graph = future.__dask_graph__() if hasattr(future, '__dask_graph__') else None
        task_keys = list(graph.keys()) if graph is not None else []
    except Exception:
        task_keys = []

    total = max(len(task_keys), 1)
    indicator.set_computing(total_tasks=total)

    timer = QtCore.QTimer()
    timer.setInterval(200)
    timer_holder.append(timer)

    def _poll():
        if future.done():
            timer.stop()
            indicator.set_done()
            return
        if not task_keys:
            return  # spinner only — no key introspection
        try:
            info = client.scheduler_info()
            all_tasks = info.get("tasks", {})
            completed = sum(
                1 for k in task_keys
                if all_tasks.get(str(k), {}).get("state") in ("memory", "released", "forgotten")
            )
            indicator.update_progress(completed)
        except Exception:
            pass

    timer.timeout.connect(_poll)
    timer.start()
```

- [ ] **Step 4: Rewrite `add_virtual_image` to wire live preview, indicator, live/commit toggle**

Replace the body of `add_virtual_image` in `spyde/actions/pyxem.py`. The existing code creates the ROI, icon, and caret box. Keep all of that, then add the new wiring immediately after the existing ROI setup (after `roi.sigRegionChangeFinished.connect(arrange_widgets_on_move)`):

```python
    # --- NEW: spawn paired PlotWindow for live preview ---
    from spyde.drawing.plots.plot_window import PlotWindow as _PlotWindow
    from spyde.qt.compute_status_indicator import ComputeStatusIndicator

    signal = toolbar.plot.plot_state.current_signal
    main_window = toolbar.plot.main_window
    client = main_window.client
    gpu_worker = getattr(main_window, "_gpu_worker_address", None)

    # Create plot window for the virtual image preview
    virtual_plot_window = _PlotWindow(
        is_navigator=False,
        main_window=main_window,
    )
    virtual_plot = virtual_plot_window.add_new_plot()
    main_window.mdi_area.addSubWindow(virtual_plot_window)
    virtual_plot_window.show()
    virtual_plot_window.resize(300, 300)
    main_window.plot_subwindows.append(virtual_plot_window)

    indicator = ComputeStatusIndicator()
    virtual_plot_window.set_compute_indicator(indicator)

    # --- Live/Manual state ---
    _live_enabled = [True]
    _cached_mask = [None]
    _timer_holder = []  # keeps QTimer refs alive

    def _on_virtual_roi_finished(_roi=roi):
        if not _live_enabled[0]:
            return
        from spyde.drawing.update_functions import compute_virtual_image_kernel
        mask = roi_to_mask(_roi, signal)
        _cached_mask[0] = mask
        future = compute_virtual_image_kernel(signal.data, mask, client, gpu_worker)
        virtual_plot.pending_future = future
        _start_progress_poll(future, indicator, client, _timer_holder)
        params_caret_box.get_parameter_widget("commit_button").setEnabled(False)

        def _on_preview_done(fut):
            QtCore.QMetaObject.invokeMethod(
                params_caret_box.get_parameter_widget("commit_button"),
                "setEnabled",
                QtCore.Qt.ConnectionType.QueuedConnection,
                QtCore.Q_ARG(bool, True),
            )

        future.add_done_callback(_on_preview_done)

    roi.sigRegionChangeFinished.connect(_on_virtual_roi_finished)

    # --- Add Live/Compute/Commit parameters to the caret box ---
    # These are added after the existing "type" and "calculation" params.
    # CaretParams supports QPushButton via type="button".
    params_caret_box.add_parameter(
        name="live_button",
        label="Live",
        type="toggle_button",
        default=True,
        callback=lambda enabled: _live_enabled.__setitem__(0, enabled),
    )

    def _on_compute_clicked():
        if _cached_mask[0] is None:
            _on_virtual_roi_finished()
        else:
            from spyde.drawing.update_functions import compute_virtual_image_kernel
            future = compute_virtual_image_kernel(signal.data, _cached_mask[0], client, gpu_worker)
            virtual_plot.pending_future = future
            _start_progress_poll(future, indicator, client, _timer_holder)

    params_caret_box.add_parameter(
        name="compute_button",
        label="Compute",
        type="button",
        callback=_on_compute_clicked,
    )

    commit_btn_params = params_caret_box.add_parameter(
        name="commit_button",
        label="Commit",
        type="button",
        callback=None,  # wired below
    )
    params_caret_box.get_parameter_widget("commit_button").setEnabled(False)

    def _on_commit_clicked():
        if _cached_mask[0] is None:
            return
        from spyde.drawing.update_functions import compute_virtual_image_kernel
        from pyxem.signals import VirtualDarkFieldImage
        params_caret_box.get_parameter_widget("commit_button").setEnabled(False)
        indicator.set_computing()
        future = compute_virtual_image_kernel(signal.data, _cached_mask[0], client, gpu_worker)

        def _on_done(fut):
            try:
                result = fut.result()
            except Exception as e:
                QtCore.QMetaObject.invokeMethod(
                    main_window, "show_error_message",
                    QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(str, str(e)),
                )
                QtCore.QMetaObject.invokeMethod(
                    params_caret_box.get_parameter_widget("commit_button"),
                    "setEnabled",
                    QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(bool, True),
                )
                return
            vdf = VirtualDarkFieldImage(result)
            for i, ax in enumerate(signal.axes_manager.navigation_axes):
                vdf.axes_manager.navigation_axes[i].scale = ax.scale
                vdf.axes_manager.navigation_axes[i].offset = ax.offset
                vdf.axes_manager.navigation_axes[i].units = ax.units
                vdf.axes_manager.navigation_axes[i].name = ax.name
            vdf.metadata.Signal.virtual_detector = _roi_metadata(roi)
            QtCore.QMetaObject.invokeMethod(
                main_window, "_add_signal_from_thread",
                QtCore.Qt.ConnectionType.QueuedConnection,
                QtCore.Q_ARG(object, vdf),
            )
            QtCore.QMetaObject.invokeMethod(
                params_caret_box.get_parameter_widget("commit_button"),
                "setEnabled",
                QtCore.Qt.ConnectionType.QueuedConnection,
                QtCore.Q_ARG(bool, True),
            )

        future.add_done_callback(_on_done)

    params_caret_box.get_parameter_widget("commit_button").clicked.connect(_on_commit_clicked)

    # --- Visibility toggle: hide/show virtual plot window with the ROI ---
    parent_toolbar = toolbar.parent_toolbar
    _original_toggle = getattr(parent_toolbar, "_virtual_image_toggle_handler", None)

    def _toggle_virtual_plot_window(visible: bool):
        if visible:
            virtual_plot_window.show()
        else:
            virtual_plot_window.hide()

    # Store in the action_widgets dict for the toggle to call
    if "Virtual Imaging" in toolbar.parent_toolbar.action_widgets:
        existing = toolbar.parent_toolbar.action_widgets["Virtual Imaging"]
        if "plot_windows" not in existing:
            existing["plot_windows"] = {}
        existing["plot_windows"][action_name] = virtual_plot_window
```

**Note on `CaretParams.add_parameter`:** Inspect `spyde/drawing/toolbars/caret_group.py` to confirm the API for adding parameters dynamically vs. declaratively. If `add_parameter` does not exist, use the `parameters` dict passed at creation time and include `live_button`, `compute_button`, `commit_button` in the initial `params` dict in `add_virtual_image` with `type="button"` or `type="toggle"`.

- [ ] **Step 5: Wire visibility toggle in the `Virtual Imaging` toolbar action handler**

Find the existing toggle handler for the "Virtual Imaging" toolbar action (in the toolbar machinery — `RoundedToolBar.register_action_plot_item` / the action's `triggered` signal). The toggle must iterate over `action_widgets["Virtual Imaging"]["plot_windows"]` and call `show()`/`hide()`. Grep for where the ROI visibility toggle is handled:

```
grep -n "plot_items" spyde/drawing/toolbars/toolbar.py
```

Add parallel handling for `"plot_windows"` alongside `"plot_items"`.

- [ ] **Step 6: Run live preview tests**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_virtual_image.py::TestVirtualImageLivePreview -v
```

Expected: all 3 tests pass.

- [ ] **Step 7: Run commit tests**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_virtual_image.py::TestVirtualImageCommit -v
```

Expected: all 3 tests pass (may take ~10–20 s due to computation waits).

- [ ] **Step 8: Run the existing `test_virtual_imaging` to confirm nothing regressed**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_actions.py::TestActions::test_virtual_imaging -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add spyde/actions/pyxem.py spyde/drawing/toolbars/toolbar.py spyde/tests/test_virtual_image.py
git commit -m "feat: wire add_virtual_image with live preview, progress indicator, and commit"
```

---

## Task 7: Wire `PlotUpdateWorker` to update the virtual preview `Plot`

**Files:**
- Modify: `spyde/workers/plot_update_worker.py` (inspect only — may already handle `pending_future` on any `Plot`)
- Modify: `spyde/drawing/plots/plot.py` (add `pending_future` attribute if not present)

The `PlotUpdateWorker` already polls `Plot.pending_future` across all plots in `plot_subwindows`. The virtual preview plot window is added to `main_window.plot_subwindows` in Task 6, so the worker should pick it up automatically. This task is a verification/fix step.

- [ ] **Step 1: Inspect `PlotUpdateWorker`**

Read `spyde/workers/plot_update_worker.py` and confirm that:
1. It iterates over all plots returned by the lambda (which returns all plots in `plot_subwindows`)
2. It reads `plot.pending_future` and, when resolved, calls something that sets the plot data

If `pending_future` is not the right attribute name, find what attribute the worker looks for on `Plot` objects and use that in Task 6 instead.

- [ ] **Step 2: Confirm `Plot` has `pending_future`**

Read `spyde/drawing/plots/plot.py` and look for `pending_future`. If it doesn't exist as an instance attribute, add it in `Plot.__init__`:

```python
self.pending_future = None  # type: Future | None
```

- [ ] **Step 3: Run full kernel + preview test suite**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_virtual_image.py -v -k "not gpu"
```

Expected: all non-GPU tests pass.

- [ ] **Step 4: Run existing tests to check for regressions**

```
.venv/Scripts/python.exe -m pytest spyde/tests/ -v -k "not gpu" --timeout=120
```

Expected: all previously passing tests still pass.

- [ ] **Step 5: Commit if any changes were made**

```bash
git add spyde/workers/plot_update_worker.py spyde/drawing/plots/plot.py
git commit -m "fix: ensure PlotUpdateWorker picks up virtual preview plot futures"
```

---

## Task 8: GPU integration test (optional, requires physical GPU)

**Files:**
- Modify: `spyde/tests/test_virtual_image.py`

- [ ] **Step 1: Add GPU tests**

Add to `spyde/tests/test_virtual_image.py`:

```python
@pytest.mark.gpu
class TestVirtualImageKernelGPU:

    @pytest.fixture(autouse=True)
    def skip_if_no_gpu(self, gpu_available):
        if not gpu_available:
            pytest.skip("No NVIDIA GPU detected")

    @pytest.fixture(autouse=True)
    def client(self, stem_4d_dataset):
        self.win = stem_4d_dataset["window"]
        self.client = self.win.client
        self.gpu_address = self.win._gpu_worker_address

    def _mask(self):
        mask = np.zeros((8, 8), dtype=np.float32)
        mask[2:6, 2:6] = 1.0
        return mask

    def test_4d_gpu_matches_cpu(self):
        from spyde.drawing.update_functions import compute_virtual_image_kernel
        rng = np.random.default_rng(1)
        data_np = rng.random((4, 4, 8, 8)).astype(np.float32)
        mask = self._mask()
        data = da.from_array(data_np, chunks=(2, 2, 8, 8))

        cpu_future = compute_virtual_image_kernel(data, mask, self.client, None)
        gpu_future = compute_virtual_image_kernel(data, mask, self.client, self.gpu_address)

        cpu_result = cpu_future.result()
        gpu_result = gpu_future.result()

        np.testing.assert_allclose(cpu_result, gpu_result, rtol=1e-4)

    def test_5d_gpu_matches_cpu(self):
        from spyde.drawing.update_functions import compute_virtual_image_kernel
        rng = np.random.default_rng(2)
        data_np = rng.random((2, 4, 4, 8, 8)).astype(np.float32)
        mask = self._mask()
        data = da.from_array(data_np, chunks=(1, 2, 2, 8, 8))

        cpu_future = compute_virtual_image_kernel(data, mask, self.client, None)
        gpu_future = compute_virtual_image_kernel(data, mask, self.client, self.gpu_address)

        np.testing.assert_allclose(cpu_future.result(), gpu_future.result(), rtol=1e-4)
        assert gpu_future.result().shape == (2, 4, 4)
```

- [ ] **Step 2: Confirm GPU tests are excluded from the default run**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_virtual_image.py -v -k "not gpu" --collect-only
```

Verify `TestVirtualImageKernelGPU` tests do not appear in the collection.

- [ ] **Step 3: Commit**

```bash
git add spyde/tests/test_virtual_image.py
git commit -m "test: add GPU kernel tests (skipped without NVIDIA GPU)"
```

---

## Self-Review Checklist

**Spec coverage:**

| Spec section | Covered by task |
|---|---|
| 3. GPU Worker Setup | Task 4 |
| 4. ROI → Mask | Task 3 |
| 5. Virtual Image Kernel | Task 1 |
| 6.1 Plot Window Spawn | Task 6 |
| 6.2 ROI → Computation Connection | Task 6 |
| 6.3 Multiple Detectors | Covered by multiple calls to `add_virtual_image` (each call is independent) |
| 6.4 Visibility Toggle | Task 6 step 5 |
| 6.5 Live/Manual Toggle | Task 6 step 4 |
| 7. Commit Path | Task 6 step 4 |
| 8.1 ComputeStatusIndicator | Task 2 |
| 8.2 Progress Polling | Task 6 step 3 (`_start_progress_poll`) |
| 8.3 Placement | Task 5 |
| 9.2 Kernel tests (3D/4D/5D/6D) | Task 1 |
| 9.3 Live preview tests | Task 6 |
| 9.4 Commit tests | Task 6 |
| 9.5 GPU worker setup tests | Task 4 |
| 9.6 GPU kernel tests | Task 8 |

**Known implementation detail to resolve during Task 6:**

- `CaretParams.add_parameter` — verify the API supports adding `button` and `toggle_button` types dynamically, or move all parameter declarations to the initial `params` dict. Read `spyde/drawing/toolbars/caret_group.py` at the start of Task 6 to confirm.
- `PlotUpdateWorker` poll attribute name — verify in Task 7 Step 1 before using `pending_future` in Task 6.
- `cluster.start_worker` API — verify availability at Task 4 Step 5; use the `distributed.Worker` fallback if absent.
- `MainWindow.show_error_message` — verify the method name exists, or replace with the correct error-display slot.
