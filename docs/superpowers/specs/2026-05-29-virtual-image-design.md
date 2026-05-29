# Virtual Image Workflow Design

**Date:** 2026-05-29  
**Status:** Approved  
**Scope:** Full virtual detector → live preview → GPU-accelerated computation → commit as signal tree

---

## 1. Overview

A 4D STEM dataset has shape `(nx, ny, nkx, nky)`. A virtual image integrates the diffraction-space intensity inside a detector ROI (disk, annular, rectangle) across every navigation position, producing a `(nx, ny)` image. This design adds the complete workflow:

1. User places one or more colored ROIs on the diffraction pattern
2. Each ROI immediately spawns a paired plot window showing the live virtual image
3. When the ROI stops moving, the kernel recomputes the virtual image asynchronously
4. A circular progress arc in the plot window shows real computation progress
5. The user can commit any virtual image as an independent `VirtualDarkFieldImage` signal tree root

GPU acceleration (NVIDIA, via dask worker resources) is built-in from the start and degrades gracefully to CPU when no GPU is present.

---

## 2. Architecture Overview

```
add_virtual_image()
    │
    ├── roi_to_mask(roi, signal) → float32 (nkx, nky) mask
    │
    ├── spawns PlotWindow + Plot (dynamic=True, placeholder data)
    │
    └── sigRegionChangeFinished →
            compute_virtual_image_kernel(data, mask, client, gpu_worker)
                │
                ├── da.tensordot(data, da_mask, axes=([2,3],[0,1]))  → (nx,ny)
                ├── dask.annotate(resources={"GPU": 1})  if gpu available
                ├── client.compute(result) → Future
                │
                └── Future → PlotUpdateWorker poll → plot.update_data()
                                                   → ComputeStatusIndicator
```

Commit path:
```
Commit button →
    compute_virtual_image_kernel() → Future
    future.add_done_callback(on_commit_done)
        → VirtualDarkFieldImage(result)
        → main_window.add_signal()  [new signal tree root]
```

---

## 3. GPU Worker Setup

### 3.1 GPU Probe at Startup

A new function `_probe_gpus() -> int` in `spyde/__main__.py` runs at `LocalCluster` init time (already in a background thread — no GUI latency). It calls:

```python
subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
               capture_output=True, timeout=3)
```

No cupy import is required — avoids a hard dependency. Returns the number of GPUs found; returns 0 if `nvidia-smi` is absent or fails.

### 3.2 Cluster Configuration

If `_probe_gpus() > 0`, one additional worker is added to the `LocalCluster` with:
```python
resources={"GPU": 1}
CUDA_VISIBLE_DEVICES="0"
```

`MainWindow` stores `self._gpu_worker_address: str | None`. `None` means CPU-only fallback.

### 3.3 CPU Fallback

When `_gpu_worker_address is None`, `dask.annotate(resources={"GPU": 1})` is a no-op — dask ignores resource constraints when no worker satisfies them, so the same graph runs on CPU workers with numpy. No conditional code paths in the kernel.

### 3.4 Future: Multi-GPU and MPS

The `_probe_gpus()` function returns the full GPU count. The cluster setup is written to accept `n_gpus` and add one worker per device. MPS (Apple Silicon) support is added later by detecting `torch.backends.mps.is_available()` and routing through a MPS-pinned worker with the same `resources={"GPU": 1}` tag.

---

## 4. ROI → Mask Conversion

### 4.1 Function Signature

```python
# spyde/actions/pyxem.py
def roi_to_mask(roi, signal) -> np.ndarray:
    """
    Convert a PyQtGraph ROI to a float32 boolean mask over the signal axes.

    Parameters
    ----------
    roi : CircleROI | RingROI | RectROI
        PyQtGraph ROI placed on the diffraction pattern plot.
    signal : BaseSignal
        The 4D STEM signal. Signal axes are used for coordinate grid.

    Returns
    -------
    np.ndarray, shape (nkx, nky), dtype float32
        1.0 inside the detector region, 0.0 outside.
    """
```

### 4.2 Coordinate Conversion

Signal axes provide `scale` and `offset` for `kx` and `ky`. The ROI position is in PyQtGraph scene/data coordinates (after the image transform). The same `inverted_transform` technique used in `RectangleSelector._get_selected_indices` converts ROI geometry to pixel index space. `roi_to_mask` owns this conversion internally — the caller passes the raw PyQtGraph ROI and the signal.

### 4.3 Per-ROI-Type Logic

| ROI type | Mask condition (pixel coords) |
|----------|-------------------------------|
| `CircleROI` | `(x - cx)² + (y - cy)² <= r²` |
| `RingROI` | `inner_r² <= (x-cx)² + (y-cy)² <= outer_r²` |
| `RectROI` | bounding box test |

Output is `np.bool_` array cast to `float32` before return. `da.tensordot` requires numeric dtype.

### 4.4 Mask Caching

The mask is cached on the action widget after each `sigRegionChangeFinished`. The commit path reuses this cached mask — no recomputation unless the ROI moved since last compute.

---

## 5. Virtual Image Kernel

### 5.1 Function Signature

```python
# spyde/drawing/update_functions.py
def compute_virtual_image_kernel(
    data: da.Array,
    mask: np.ndarray,
    client: distributed.Client,
    gpu_worker_address: str | None,
) -> distributed.Future:
    """
    Compute a virtual image by contracting data over diffraction axes with mask.

    Uses da.tensordot for memory-efficient contraction — no intermediate
    (nx, ny, nkx, nky) array is materialised.

    Parameters
    ----------
    data : dask array, shape (nx, ny, nkx, nky)
    mask : float32 numpy array, shape (nkx, nky)
    client : dask distributed Client
    gpu_worker_address : str or None
        Address of the GPU worker. None → CPU fallback.

    Returns
    -------
    distributed.Future resolving to np.ndarray shape (nx, ny)
    """
```

### 5.2 Computation

```python
da_mask = da.from_array(mask, chunks=mask.shape)  # never split
with dask.annotate(resources={"GPU": 1} if gpu_worker_address else {}):
    result = da.tensordot(data, da_mask, axes=([2, 3], [0, 1]))  # → (nx, ny)
future = client.compute(result)
return future
```

`da.tensordot` with a single-chunk mask fuses multiply and sum into one kernel call per navigation chunk. Peak memory per worker = one navigation chunk + mask. The mask is broadcast, not replicated per chunk.

### 5.3 Data must be `(nx, ny, nkx, nky)`

If the signal has a different axis order, the kernel caller is responsible for transposing `signal.data` before passing it in. `signal.axes_manager` gives the canonical axis order.

### 5.4 GPU Execution

When `gpu_worker_address` is set, the dask annotation routes tasks to the GPU worker. The GPU worker has cupy available; dask's array operations dispatch to cupy automatically when the array is on-device (same as pyxem's existing `to_device()`/`to_host()` pattern). The result is transferred back to CPU numpy before the future resolves.

---

## 6. Live Preview Wiring

### 6.1 Plot Window Spawn

`add_virtual_image()` immediately calls `main_window.add_plot_window()` and creates a `Plot` with `dynamic=True`, `dimensions=2`. The plot is initialised with a checkerboard placeholder (same pattern as the existing future-pending path in `plot.py`). The `PlotWindow` is stored in the action widget's metadata keyed by `action_name`.

### 6.2 ROI → Computation Connection

```python
roi.sigRegionChangeFinished.connect(
    lambda: _on_virtual_roi_finished(roi, plot, signal, indicator)
)
```

`_on_virtual_roi_finished`:
1. `mask = roi_to_mask(roi, signal)` — cache on widget
2. `indicator.set_computing()`
3. `future = compute_virtual_image_kernel(data, mask, client, gpu_worker)`
4. `plot.update_data(future)` — hooks into `PlotUpdateWorker` poll loop
5. Attach progress polling (Section 8)

### 6.3 Multiple Detectors

Each `add_virtual_image` call is fully independent: its own ROI, its own `PlotWindow`, its own future. Moving one ROI recomputes only that detector's plot. There is no shared state between detectors.

### 6.4 Visibility Toggle

The "Virtual Imaging" toolbar toggle shows/hides all ROIs AND all paired plot windows together. The existing `register_action_plot_item` / `unregister_action_plot_item` mechanism handles ROI visibility. Plot window show/hide is wired to the same toggle signal, iterating over all stored `action_name → PlotWindow` entries.

### 6.5 Live / Manual Toggle

Each virtual detector caret box has a **"Live" toggle button** (same pattern as `IntegratingSelectorMixin.live_button`):

- **Live ON (default):** `sigRegionChangeFinished` triggers computation automatically
- **Live OFF:** `sigRegionChangeFinished` does nothing. A **"Compute" button** in the caret box triggers one computation on demand.

The Live button is red when active (matching existing selector UI convention).

---

## 7. Commit Path

### 7.1 Commit Button

A "Commit" button is added to each virtual detector's caret box, below the type/calculation dropdowns. It is **disabled** until the first computation completes (i.e. the plot has non-placeholder data). It is **disabled while a computation future is pending** and re-enabled on completion or error.

### 7.2 Non-Blocking Commit

```python
def on_commit_clicked():
    commit_button.setEnabled(False)
    indicator.set_computing()
    future = compute_virtual_image_kernel(data, cached_mask, client, gpu_worker)

    def on_done(fut):
        try:
            result = fut.result()
        except Exception as e:
            QtCore.QMetaObject.invokeMethod(
                main_window, "show_error", Qt.QueuedConnection,
                QtCore.Q_ARG(str, str(e))
            )
            return
        vdf = VirtualDarkFieldImage(result)
        # copy navigation axes
        for i, ax in enumerate(signal.axes_manager.navigation_axes):
            vdf.axes_manager.navigation_axes[i].scale = ax.scale
            vdf.axes_manager.navigation_axes[i].offset = ax.offset
            vdf.axes_manager.navigation_axes[i].units = ax.units
            vdf.axes_manager.navigation_axes[i].name = ax.name
        # store ROI geometry in metadata
        vdf.metadata.Signal.virtual_detector = _roi_metadata(roi)
        QtCore.QMetaObject.invokeMethod(
            main_window, "_add_signal_from_thread", Qt.QueuedConnection,
            QtCore.Q_ARG(object, vdf)
        )

    future.add_done_callback(on_done)
```

`_add_signal_from_thread` is a new `@Slot` on `MainWindow` that calls `self.add_signal(signal)` — the same path as loading a file.

### 7.3 Result

- A new `BaseSignalTree` rooted at `VirtualDarkFieldImage` is added to `main_window.signal_trees`
- The live preview plot window remains open and independent
- Committing again creates a second independent signal tree
- The commit future shares the same `ComputeStatusIndicator` as the live preview

---

## 8. Computation Progress Indicator

### 8.1 `ComputeStatusIndicator` Widget

New file: `spyde/qt/compute_status_indicator.py`

```python
class ComputeStatusIndicator(QWidget):
    def set_idle(self): ...
    def set_computing(self, total_tasks: int): ...
    def set_done(self): ...   # auto-transitions to idle after 500ms
    def update_progress(self, completed: int): ...
```

A 24×24px transparent `QWidget` anchored to the top-left corner of the `PlotWindow`. Drawn entirely in `paintEvent` with `QPainter`.

| State | Visual |
|-------|--------|
| Idle | Small filled green circle |
| Computing | Grey ring; clockwise arc fills from 0° proportional to `completed/total` tasks |
| Done | Fully filled green circle, fades to idle after 500ms |

### 8.2 Progress Polling

After submitting a future, a `QTimer` polls every 200ms:

```python
def _poll_progress(future, indicator, client, task_keys):
    info = client.scheduler_info()
    all_tasks = info.get("tasks", {})
    completed = sum(
        1 for k in task_keys
        if all_tasks.get(k, {}).get("state") in ("memory", "released", "forgotten")
    )
    indicator.update_progress(completed)
    if completed >= len(task_keys):
        timer.stop()
```

`task_keys` is captured from `result.__dask_graph__()` (the output layer keys only — one per navigation chunk) before `client.compute()` is called. This gives genuine per-chunk progress without any pyxem changes.

**Known risk:** The dask graph key API is internal and may change between distributed versions. If key inspection is fragile in practice, fall back to a fixed-rate spinner (one full rotation per 2s) as a safe degradation. This is flagged for investigation during implementation.

### 8.3 Placement

The indicator is positioned by overriding `PlotWindow.resizeEvent` to keep it at `(8, 8)` from the top-left. It has `WA_TransparentForMouseEvents` set so it doesn't intercept clicks.

---

## 9. Testing Plan

### 9.1 `TestVirtualImageROI`

Extends `test_actions.py`:

- `roi_to_mask` returns shape `(nkx, nky)` for all three ROI types
- Mask is `0.0` outside the ROI and `1.0` inside (spot-check known pixel)
- `RingROI` mask has `False` at center (inner region excluded)
- Output dtype is `float32`
- Mask is cached on widget after `sigRegionChangeFinished`

### 9.2 `TestVirtualImageKernel`

- CPU path: `(4,4,8,8)` synthetic dask array, known mask → output matches `np.tensordot` reference
- Non-lazy (numpy) array input works
- `gpu_worker_address=None` → no error, CPU result correct
- Return type is `distributed.Future`
- Output shape is `(nx, ny)` regardless of chunking

### 9.3 `TestVirtualImageLivePreview`

Integration tests using `stem_4d_dataset` fixture:

- `add_virtual_image` spawns exactly one new `PlotWindow`
- `sigRegionChangeFinished` sets a future on the child plot
- After `qtbot.wait(3000)` child plot has non-checkerboard data
- Moving ROI and waiting produces different data
- `ComputeStatusIndicator` transitions: idle → computing → done → idle
- Live OFF: ROI move does NOT trigger computation
- Live OFF + Compute click: triggers exactly one computation

### 9.4 `TestVirtualImageCommit`

- Commit button disabled before first computation
- Commit button enabled after preview data arrives
- Commit adds a new entry to `main_window.signal_trees`
- New tree root is `VirtualDarkFieldImage`
- Navigation axes match parent signal axes
- `metadata.Signal.virtual_detector` is populated
- Live preview plot window remains open after commit
- Two commits produce two independent signal trees
- Commit button re-enabled after commit future resolves

### 9.5 `TestGPUWorkerSetup`

No real GPU required (mock `nvidia-smi`):

- `_probe_gpus()` returns 0 when `nvidia-smi` absent
- Returns correct count from mocked output
- `_gpu_worker_address` is `None` when no GPU found
- Cluster has `resources={"GPU": 1}` worker when GPU found (mock)

### 9.6 `TestVirtualImageKernelGPU` (`@pytest.mark.gpu`)

Runs only when `nvidia-smi` detects a GPU at collection time (session-scoped `gpu_available` fixture):

- Same `(4,4,8,8)` array routed through GPU worker
- Output matches CPU reference to `float32` precision
- GPU worker `processed` count increases after computation
- Progress arc angle advances during computation (200ms poll)

GPU tests excluded from standard `pytest spyde/tests/` run. Run with `pytest -m gpu`.

---

## 10. File Changes Summary

| File | Change |
|------|--------|
| `spyde/__main__.py` | `_probe_gpus()`, GPU worker in cluster init, `_gpu_worker_address`, `_add_signal_from_thread` slot |
| `spyde/actions/pyxem.py` | `roi_to_mask()`, `_roi_metadata()`, full `compute_virtual_image()`, live/commit wiring in `add_virtual_image()` |
| `spyde/drawing/update_functions.py` | `compute_virtual_image_kernel()` |
| `spyde/qt/compute_status_indicator.py` | New: `ComputeStatusIndicator` widget |
| `spyde/drawing/plots/plot_window.py` | Anchor `ComputeStatusIndicator`, wire to `PlotUpdateWorker` |
| `spyde/tests/test_actions.py` | Extend `TestVirtualImageROI` |
| `spyde/tests/test_virtual_image.py` | New: kernel, live preview, commit, GPU tests |
| `spyde/conftest.py` | `gpu_available` session fixture |

---

## 11. Out of Scope

- Multi-GPU scheduling (architecture supports it; not implemented in v1)
- MPS (Apple Silicon) backend — architecture is ready; add when `torch.backends.mps` path is tested
- pyxem upstream contribution of the kernel — done separately at maintainer's discretion
- FEM Omega and COM calculation modes — stub exists in caret box params; computed via separate functions in a future iteration
- Saving/loading virtual detector ROI geometry with the project file
