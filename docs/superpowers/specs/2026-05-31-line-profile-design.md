# Line Profile Workflow Design

**Date:** 2026-05-31
**Status:** Approved
**Scope:** Title-bar commit infrastructure + line profile tool for any 2D plot

---

## 1. Overview

This design adds two things:

1. **Title-bar commit infrastructure** — every live `PlotWindow` (virtual image, line profile, future tools) gets a "Commit" button in its `FramelessSubWindow` title bar that spawns a new `SignalTree`. The caret-box Commit button is removed from virtual imaging.

2. **Line profile tool** — a `LineROI` placed on any 2D plot that extracts a 1D intensity profile with adjustable perpendicular integration width. Behaviour differs by plot type:

   | Plot type | Result | Preview windows |
   |-----------|--------|-----------------|
   | Signal plot (2D image) | `Signal1D` — profile at current nav position | 1 (1D line plot) |
   | Navigator plot (4D STEM etc.) | `Signal2D` with shape `(N, nkx, nky)` — virtual line scan | 2 (1D profile + summed diffraction) |

Both cases are live (update on ROI move) and committed via the title-bar button.

---

## 2. Architecture Overview

```
add_line_profile(toolbar)
    │
    ├── LineROI placed on plot
    │
    ├── if signal plot:
    │     └── 1 preview PlotWindow (1D)
    │           set_commit_fn(_do_commit_signal)
    │
    └── if navigator plot:
          ├── preview PlotWindow 1 (1D profile, instant from image_item.image)
          └── preview PlotWindow 2 (2D summed diffraction, lazy dask future)
                set_commit_fn(_do_commit_nav)

sigRegionChangeFinished →
    _on_line_roi_finished (if live)
        ├── signal plot:  compute_line_profile_kernel → Future → PlotUpdateWorker → line_item.setData
        └── nav plot:
              ├── instant: getArrayRegion(image_item.image) → nanmean → line_item.setData
              └── lazy:    compute_nav_line_sum_kernel → Future → PlotUpdateWorker → image_item.setImage

Commit (title bar button) →
    _do_commit_signal:  Signal1D(profile) → _add_signal_from_thread
    _do_commit_nav:     da.stack([data[y_i, x_i] ...]) → Signal2D → _add_signal_from_thread
```

---

## 3. Title-Bar Commit Infrastructure

### 3.1 `FramelessSubWindow` changes

Add a "Commit" `QPushButton` to the right of the title label in the existing title bar, between the label and the minimize button. Hidden by default.

```python
self.commit_button = QtWidgets.QPushButton("Commit", self.title_bar)
self.commit_button.setFixedHeight(20)
self.commit_button.hide()
self.title_bar_layout.insertWidget(1, self.commit_button)  # after label, before controls
```

### 3.2 `PlotWindow` methods

```python
def set_commit_fn(self, fn: callable, label: str = "Commit") -> None:
    """Wire a commit function and show the title-bar Commit button."""
    self._commit_fn = fn
    self.title_bar.commit_button.setText(label)
    self.title_bar.commit_button.show()
    self.title_bar.commit_button.setEnabled(False)  # disabled until first data
    self.title_bar.commit_button.clicked.connect(fn)

@QtCore.Slot(bool)
def set_commit_enabled(self, enabled: bool) -> None:
    """Enable or disable the title-bar Commit button.
    Decorated as a Slot so it can be called safely from dask callback threads
    via QMetaObject.invokeMethod(..., QueuedConnection).
    """
    if hasattr(self.title_bar, "commit_button"):
        self.title_bar.commit_button.setEnabled(enabled)
```

### 3.3 Migration of virtual imaging

In `add_virtual_image` (`spyde/actions/pyxem.py`):
- Remove `"commit_button"` from the `params` dict
- Remove `_on_commit_clicked` trampoline and `_do_commit` wiring to caret box
- After creating `virtual_plot_window`, call:
  ```python
  virtual_plot_window.set_commit_fn(_do_commit)
  ```
- `_on_preview_done` callback calls `virtual_plot_window.set_commit_enabled(True)` instead of `QMetaObject.invokeMethod` on a caret box button
- `_do_commit` calls `virtual_plot_window.set_commit_enabled(False)` at start and `virtual_plot_window.set_commit_enabled(True)` on completion/error via `QMetaObject.invokeMethod`

---

## 4. Line Profile Kernel

### 4.1 Signal-plot kernel

```python
# spyde/drawing/update_functions.py
def compute_line_profile_kernel(
    image: np.ndarray,
    roi,                        # pyqtgraph LineROI
    image_item,                 # pg.ImageItem
    client: distributed.Client,
) -> distributed.Future:
    """Extract a 1D line profile from a 2D image using LineROI.getArrayRegion.

    Parameters
    ----------
    image : np.ndarray, shape (ny, nx)
        The currently displayed image (from plot.image_item.image).
    roi : LineROI
        The placed line ROI.
    image_item : pg.ImageItem
        The image item the ROI is mapped against.
    client : distributed.Client

    Returns
    -------
    distributed.Future resolving to np.ndarray shape (length_px,)
    """
    region = roi.getArrayRegion(image, image_item)   # (width_px, length_px)
    profile = np.nanmean(region, axis=0)             # (length_px,)
    return client.submit(lambda p=profile: p)
```

### 4.2 Navigator-plot sum kernel

```python
def compute_nav_line_sum_kernel(
    data: da.Array,             # (...nav..., nkx, nky)
    ys: np.ndarray,             # 1D array of nav-y pixel indices in the strip
    xs: np.ndarray,             # 1D array of nav-x pixel indices in the strip
    client: distributed.Client,
    gpu_worker_address: str | None,
) -> distributed.Future:
    """Compute the mean diffraction pattern over all nav pixels in the line strip.

    Parameters
    ----------
    data : dask array, shape (...nav..., nkx, nky)
    ys, xs : pixel index arrays — all nav pixels within the LineROI strip
    client : distributed.Client
    gpu_worker_address : str or None

    Returns
    -------
    distributed.Future resolving to np.ndarray shape (nkx, nky)
    """
    # Index the nav dimensions (last two axes are always signal)
    nav_slices = data[ys, xs]           # (n_strip_pixels, nkx, nky)
    resources = {"GPU": 1} if gpu_worker_address else {}
    with dask.annotate(resources=resources):
        result = da.mean(nav_slices, axis=0)
    return client.compute(result)
```

### 4.3 Coordinate extraction

```python
def _get_line_nav_coords(roi, image_item, nav_shape):
    """
    Extract pixel coordinates along a LineROI and within its perpendicular strip.

    Returns
    -------
    line_points : np.ndarray, shape (N, 2)
        (y, x) pixel coords of the N points along the line centre.
    strip_ys, strip_xs : np.ndarray
        All nav-pixel indices inside the full strip (for the sum kernel).
    N : int
        Number of points along the line (1 per pixel).
    """
    # Use getArrayRegion with returnMappedCoords to get pixel coordinates
    dummy = np.zeros(nav_shape, dtype=np.float32)
    region, coords = roi.getArrayRegion(
        dummy, image_item, returnMappedCoords=True
    )
    # coords shape: (2, width_px, length_px) — (row/col, width, length)
    # Centre line: take the middle row of the width dimension
    mid = coords.shape[1] // 2
    line_ys = np.round(coords[0, mid, :]).astype(int)
    line_xs = np.round(coords[1, mid, :]).astype(int)

    # Clip to nav shape bounds
    line_ys = np.clip(line_ys, 0, nav_shape[0] - 1)
    line_xs = np.clip(line_xs, 0, nav_shape[1] - 1)

    # All strip pixels (for sum kernel)
    strip_ys = np.clip(np.round(coords[0]).astype(int).ravel(), 0, nav_shape[0] - 1)
    strip_xs = np.clip(np.round(coords[1]).astype(int).ravel(), 0, nav_shape[1] - 1)

    N = line_ys.shape[0]
    return line_ys, line_xs, strip_ys, strip_xs, N
```

---

## 5. `add_line_profile` Implementation

**File:** `spyde/actions/line_profile.py` (new file)

### 5.1 Entry point

```python
def line_profile_action(*args, **kwargs):
    """Placeholder for the Line Profile toolbar toggle."""
    pass

def add_line_profile(toolbar, action_name="Add Line Profile", *args, **kwargs):
    """Add a LineROI to the current 2D plot and wire live preview + commit."""
```

### 5.2 ROI placement

The `LineROI` is centred horizontally on the plot at 1/3 and 2/3 of the image width, at the vertical midpoint. Width starts at 1 pixel in data units. Color cycles the same way as virtual imaging (red, green, blue…).

```python
center, _, _ = plot.get_annular_roi_parameters()  # reuse centre calculation
# pos1 at (cx - image_width/3, cy), pos2 at (cx + image_width/3, cy)
roi = LineROI(pos1, pos2, width=1_data_unit, pen=pen)
```

### 5.3 Caret box parameters

```python
params = {
    "width": {
        "name": "Width (px)",
        "type": "int",
        "default": 1,
    },
    "live_compute_row": {
        "name": "",
        "type": "button_row",
        "buttons": [
            {"key": "live_button", "label": "Live (ON)", "callback": _toggle_live},
            {"key": "compute_button", "label": "Compute", "callback": _trigger_computation},
        ],
    },
}
```

No Commit button in the caret box.

### 5.4 Branch: signal plot vs. navigator plot

```python
is_nav_plot = plot.is_navigator

if not is_nav_plot:
    _wire_signal_plot_preview(...)   # 1 window, Signal1D commit
else:
    _wire_nav_plot_preview(...)      # 2 windows, Signal2D commit
```

### 5.5 Signal-plot preview wiring

```python
preview_window = main_window.add_plot_window(is_navigator=False, signal_tree=None)
preview_plot = preview_window.add_new_plot()
preview_plot.addItem(preview_plot.line_item)   # line_item in scene (same fix as image_item)
indicator = ComputeStatusIndicator(color=color)
preview_window.set_compute_indicator(indicator)
preview_window.set_commit_fn(_do_commit_signal)
toolbar.parent_toolbar.register_action_plot_window(
    action_name="Line Profile", plot_window=preview_window, key=action_name
)

def _trigger_computation():
    image = plot.image_item.image
    if image is None:
        return
    future = compute_line_profile_kernel(image, roi, plot.image_item, client)
    preview_plot.current_data = future
    _start_progress_poll(future, indicator, client, _timer_holder)
    preview_window.set_commit_enabled(False)
    future.add_done_callback(
        lambda fut: QMetaObject.invokeMethod(
            preview_window, "set_commit_enabled",
            Qt.QueuedConnection, Q_ARG(bool, True)
        )
    )
```

`_do_commit_signal`:
```python
def _do_commit_signal():
    data = preview_plot.current_data
    if data is None or isinstance(data, Future):
        return
    sig = hs.signals.Signal1D(data)
    # Set axis scale from line length in data coords / n_points
    # Line length in data coordinates: Euclidean distance between the two endpoints
    h1, h2 = roi.getHandles()[0], roi.getHandles()[1]
    p1 = roi.mapToParent(h1.pos())
    p2 = roi.mapToParent(h2.pos())
    line_len = np.sqrt((p2.x() - p1.x())**2 + (p2.y() - p1.y())**2)
    sig.axes_manager.signal_axes[0].scale = line_len / len(data)
    # Units: take from the plot's signal axes if available, else empty string
    if signal is not None and signal.axes_manager.signal_axes:
        sig.axes_manager.signal_axes[0].units = signal.axes_manager.signal_axes[0].units
    else:
        sig.axes_manager.signal_axes[0].units = ""
    main_window._pending_signal_queue.append(sig)
    QMetaObject.invokeMethod(main_window, "_flush_pending_signals", ...)
```

### 5.6 Navigator-plot preview wiring

**Window 1 (1D profile — instant):**
```python
profile_window = main_window.add_plot_window(...)
profile_plot = profile_window.add_new_plot()
profile_plot.addItem(profile_plot.line_item)
# No commit on this window — it shows the nav image intensity only
toolbar.parent_toolbar.register_action_plot_window(
    action_name="Line Profile", plot_window=profile_window, key=action_name + "_profile"
)

def _update_profile_instant():
    image = plot.image_item.image   # already-rendered nav image
    if image is None:
        return
    region = roi.getArrayRegion(image, plot.image_item)
    profile = np.nanmean(region, axis=0)
    profile_plot.current_data = profile
    profile_plot.update()
```

**Window 2 (summed diffraction — lazy):**
```python
sum_window = main_window.add_plot_window(...)
sum_plot = sum_window.add_new_plot()
sum_plot.addItem(sum_plot.image_item)
indicator = ComputeStatusIndicator(color=color)
sum_window.set_compute_indicator(indicator)
sum_window.set_commit_fn(_do_commit_nav)
toolbar.parent_toolbar.register_action_plot_window(
    action_name="Line Profile", plot_window=sum_window, key=action_name + "_sum"
)

def _trigger_computation():
    nav_shape = signal.axes_manager.navigation_shape[::-1]  # (ny, nx)
    line_ys, line_xs, strip_ys, strip_xs, N = _get_line_nav_coords(
        roi, plot.image_item, nav_shape
    )
    _cached_line_coords[0] = (line_ys, line_xs, N)
    future = compute_nav_line_sum_kernel(signal.data, strip_ys, strip_xs, client, gpu_worker)
    sum_plot.current_data = future
    _start_progress_poll(future, indicator, client, _timer_holder)
    sum_window.set_commit_enabled(False)
    future.add_done_callback(lambda fut: ...)
```

`_do_commit_nav`:
```python
def _do_commit_nav():
    line_ys, line_xs, N = _cached_line_coords[0]
    width_val = params_caret_box.get_parameter_widget("width").value()
    # Build lazy stack: (N, nkx, nky)
    # Use the full set of strip coords already captured at ROI-finish time.
    # For each column i along the line extract the strip pixels in that column
    # and average the diffraction patterns at those nav positions.
    _, _, all_strip_ys, all_strip_xs, _ = _get_line_nav_coords(
        roi, plot.image_item, nav_shape
    )
    # coords shape from getArrayRegion: (2, width_px, length_px)
    # Reconstruct per-column strip by re-calling with returnMappedCoords
    dummy = np.zeros(nav_shape, dtype=np.float32)
    _, coords = roi.getArrayRegion(dummy, plot.image_item, returnMappedCoords=True)
    slices = []
    for i in range(N):
        col_ys = np.clip(np.round(coords[0, :, i]).astype(int), 0, nav_shape[0] - 1)
        col_xs = np.clip(np.round(coords[1, :, i]).astype(int), 0, nav_shape[1] - 1)
        slices.append(da.mean(signal.data[col_ys, col_xs], axis=0))
    result = da.stack(slices, axis=0)
    future = client.compute(result)

    def _on_done(fut):
        arr = fut.result()
        sig = hs.signals.Signal2D(arr)
        # Navigation axis: position along line
        nav_ax = signal.axes_manager.navigation_axes[0]  # take x-axis scale
        sig.axes_manager.navigation_axes[0].scale = nav_ax.scale
        sig.axes_manager.navigation_axes[0].units = nav_ax.units
        sig.axes_manager.navigation_axes[0].name = "line position"
        # Signal axes: copy from source
        for i, ax in enumerate(signal.axes_manager.signal_axes):
            sig.axes_manager.signal_axes[i].scale = ax.scale
            sig.axes_manager.signal_axes[i].offset = ax.offset
            sig.axes_manager.signal_axes[i].units = ax.units
        main_window._pending_signal_queue.append(sig)
        QMetaObject.invokeMethod(main_window, "_flush_pending_signals", ...)

    future.add_done_callback(_on_done)
```

### 5.7 Width parameter wiring

The `width` int spinbox in the caret box controls the `LineROI` width in pixel units. On change, update `roi.setWidth(width_in_data_units)` and re-trigger computation if live.

---

## 6. `plot.update()` — 1D no-PlotState path

Currently `Plot.update()` when `plot_state is None` only handles 2D (`image_item.setImage`). Extend to handle 1D:

```python
if self.plot_state is None:
    if self.current_data is not None:
        data = np.asarray(self.current_data)
        if data.ndim == 2:
            self.image_item.setImage(data, autoLevels=True, autoDownsample=True)
        elif data.ndim == 1:
            self.line_item.setData(data)
        self.update_range()
    return
```

---

## 7. YAML and File Changes

```yaml
# spyde/toolbars.yaml — add after Virtual Imaging
Line Profile:
  description: Extract a 1D line profile from the current 2D plot.
  icon: drawing/toolbars/icons/line_profile.svg
  function: spyde.actions.line_profile.line_profile_action
  plot_dim: [2]
  toolbar_side: bottom
  navigation: null          # applies to both nav and signal 2D plots
  toggle: True
  submenu: True
  subfunctions:
    add_line_profile:
      name: Add Line Profile
      description: Add a line profile ROI to the plot.
      icon: drawing/toolbars/icons/zoom.svg
      function: spyde.actions.line_profile.add_line_profile
```

| File | Change |
|------|--------|
| `spyde/qt/subwindow.py` | Add `commit_button` to title bar, hidden by default |
| `spyde/drawing/plots/plot_window.py` | Add `set_commit_fn`, `set_commit_enabled` |
| `spyde/drawing/plots/plot.py` | Extend `plot_state is None` branch for 1D data |
| `spyde/actions/pyxem.py` | Remove caret-box commit button; call `set_commit_fn` on preview window |
| `spyde/actions/line_profile.py` | New: `line_profile_action`, `add_line_profile`, `_do_commit_signal`, `_do_commit_nav`, `_get_line_nav_coords` |
| `spyde/drawing/update_functions.py` | Add `compute_line_profile_kernel`, `compute_nav_line_sum_kernel` |
| `spyde/toolbars.yaml` | Add `Line Profile` entry |
| `spyde/tests/test_line_profile.py` | New: all tests below |
| `spyde/tests/test_virtual_image.py` | Regression: virtual image commit still works via title bar |

---

## 8. Testing Plan

### 8.1 `TestCommitInfrastructure`

- `set_commit_fn` shows the Commit button in the title bar
- `set_commit_enabled(False)` disables it, `set_commit_enabled(True)` enables it
- Clicking the button calls the provided function exactly once
- Button is hidden by default on a plain `PlotWindow`
- **Regression:** virtual image preview Commit button (now title bar) still creates a new `SignalTree`

### 8.2 `TestLineProfileKernel`

Unit tests, no Qt:
- `compute_line_profile_kernel` with a known synthetic image and horizontal line → profile matches `image[row, :]`
- Width > 1 → result is mean over the strip (uniform image: same as width 1; gradient image: correct mean)
- Diagonal line → correct number of points `≈ √2 × pixel_length`
- `compute_nav_line_sum_kernel` with synthetic `(4, 4, 8, 8)` dask array → output shape `(8, 8)`

### 8.3 `TestLineProfileSignalPlot` — end-to-end integration

Using `stem_4d_dataset` fixture (signal plot = diffraction pattern):

- `add_line_profile` on signal plot spawns exactly 1 new `PlotWindow`
- Preview window has `FramelessWindowHint`
- ROI is on the signal plot, not the navigator
- `sigRegionChangeFinished` → `line_item.yData` is non-None within 5 s timeout
- Moving ROI to different position produces different profile (`yData` changes)
- Commit button in title bar disabled before first computation, enabled after
- **Full end-to-end:** add ROI → emit `sigRegionChangeFinished` → wait for `line_item.yData` → click title-bar Commit → `waitUntil(len(signal_trees) == n+1)` → assert `isinstance(new_tree.root, Signal1D)`
- Committed signal axis `scale` = line length in data coords / `len(profile)` (within 1%)

### 8.4 `TestLineProfileNavPlot` — end-to-end integration

Using `stem_4d_dataset` fixture (navigator = real-space STEM image):

- `add_line_profile` on navigator spawns exactly 2 new `PlotWindows`
- Window 1 (1D profile) updates **without** waiting for dask — `line_item.yData` non-None immediately after `sigRegionChangeFinished`
- Window 2 (summed diffraction) updates via dask future within 10 s timeout
- `ComputeStatusIndicator` on window 2 transitions idle → computing → done
- `FramelessWindowHint` on both windows
- Commit button appears on window 2 only
- **Full end-to-end:** add ROI → `sigRegionChangeFinished` → wait for both windows → click Commit on window 2 → `waitUntil(len(signal_trees) == n+1)` → assert `isinstance(new_tree.root, Signal2D)` and `root.data.shape == (N, nkx, nky)`
- Nav axis `scale` matches source nav axis scale (within 1%)
- Nav axis `units` matches source nav axis units
- Width > 1: committed signal shape still `(N, nkx, nky)` (width affects sum, not output shape)
- Two line profiles produce two independent signal trees

### 8.5 `TestLineProfileAxisScale`

Dedicated axis scale correctness tests using synthetic data with known `scale` and `offset`:
- Signal-plot case: axis scale = `line_length_data / n_points` matches expected value
- Nav-plot case: nav axis scale copied correctly from source signal
- Nav-plot case: signal axes (nkx, nky) scale/offset/units copied from source

---

## 9. Out of Scope

- Line profiles on 1D plots
- Angled/curved line profiles on 5D/6D datasets (nav-line only supported for 2D navigation space)
- Saving/loading line ROI geometry with project files
- Multiple simultaneous line profiles (can be added later using the same submenu pattern as virtual imaging)
