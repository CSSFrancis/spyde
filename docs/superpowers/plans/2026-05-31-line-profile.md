# Line Profile + Title-Bar Commit Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a title-bar Commit button to all live PlotWindows and a Line Profile tool that extracts 1D profiles from any 2D plot and virtual line scans from 4D STEM navigator images.

**Architecture:** Title-bar commit wires a caller-supplied function to a hidden button in `FramelessSubWindow`; `PlotWindow.set_commit_fn` shows it. Virtual imaging is migrated to use this infrastructure (caret-box Commit removed). Line profile uses `LineROI.getArrayRegion` for the signal-plot case and dask-indexed stacks for the nav-plot case; both flow through the existing `PlotUpdateWorker` path.

**Tech Stack:** PySide6, pyqtgraph `LineROI`, dask.distributed, numpy, hyperspy `Signal1D`/`Signal2D`, existing `PlotUpdateWorker`, `_pending_signal_queue`/`_flush_pending_signals` pattern.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `spyde/qt/subwindow.py` | Modify | Add hidden `commit_button` to title bar |
| `spyde/drawing/plots/plot_window.py` | Modify | Add `set_commit_fn`, `set_commit_enabled` |
| `spyde/drawing/plots/plot.py` | Modify | Extend `plot_state is None` branch for 1D data |
| `spyde/actions/pyxem.py` | Modify | Remove caret-box Commit button; call `set_commit_fn` |
| `spyde/drawing/update_functions.py` | Modify | Add `compute_line_profile_kernel`, `compute_nav_line_sum_kernel` |
| `spyde/actions/line_profile.py` | Create | `line_profile_action`, `add_line_profile`, commit functions |
| `spyde/toolbars.yaml` | Modify | Add `Line Profile` entry |
| `spyde/tests/test_commit_infrastructure.py` | Create | `TestCommitInfrastructure` |
| `spyde/tests/test_line_profile.py` | Create | All line profile tests |
| `spyde/tests/test_virtual_image.py` | Modify | Regression: virtual image commit via title bar |

---

## Task 1: Title-bar Commit button in `FramelessSubWindow`

**Files:**
- Modify: `spyde/qt/subwindow.py`
- Create: `spyde/tests/test_commit_infrastructure.py`

- [ ] **Step 1: Write failing tests**

Create `spyde/tests/test_commit_infrastructure.py`:

```python
"""Tests for the title-bar Commit button infrastructure."""
from PySide6 import QtWidgets
from spyde.qt.shared import open_window


class TestCommitInfrastructure:
    def test_commit_button_hidden_by_default(self, qtbot):
        from spyde.drawing.plots.plot_window import PlotWindow
        win = open_window()
        qtbot.addWidget(win)
        pw = win.add_plot_window(is_navigator=False, signal_tree=None)
        assert hasattr(pw.title_bar, "commit_button"), "commit_button not on title_bar"
        assert not pw.title_bar.commit_button.isVisible(), (
            "Commit button should be hidden by default"
        )
        win.close()

    def test_set_commit_fn_shows_button(self, qtbot):
        win = open_window()
        qtbot.addWidget(win)
        pw = win.add_plot_window(is_navigator=False, signal_tree=None)
        called = []
        pw.set_commit_fn(lambda: called.append(1))
        assert pw.title_bar.commit_button.isVisible(), (
            "set_commit_fn should make Commit button visible"
        )
        win.close()

    def test_commit_button_calls_function(self, qtbot):
        win = open_window()
        qtbot.addWidget(win)
        pw = win.add_plot_window(is_navigator=False, signal_tree=None)
        called = []
        pw.set_commit_fn(lambda: called.append(1))
        pw.title_bar.commit_button.click()
        assert called == [1], "Commit button did not call the provided function"
        win.close()

    def test_set_commit_enabled_controls_button(self, qtbot):
        win = open_window()
        qtbot.addWidget(win)
        pw = win.add_plot_window(is_navigator=False, signal_tree=None)
        pw.set_commit_fn(lambda: None)
        assert not pw.title_bar.commit_button.isEnabled(), (
            "Button should start disabled after set_commit_fn"
        )
        pw.set_commit_enabled(True)
        assert pw.title_bar.commit_button.isEnabled()
        pw.set_commit_enabled(False)
        assert not pw.title_bar.commit_button.isEnabled()
        win.close()
```

- [ ] **Step 2: Run to confirm failure**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_commit_infrastructure.py -v
```

Expected: `AttributeError` — `title_bar` has no `commit_button`.

- [ ] **Step 3: Add `commit_button` to `FramelessSubWindow`**

In `spyde/qt/subwindow.py`, find the block that adds `minimize_button`, `maximize_button`, `close_button` and the `title_bar_layout.addWidget` calls. Insert the commit button between the `title_label` and `minimize_button`:

```python
        # After self.title_bar_layout.addWidget(self.title_label):
        self.commit_button = QtWidgets.QPushButton("Commit", self.title_bar)
        self.commit_button.setFixedHeight(20)
        self.commit_button.setStyleSheet(
            "QPushButton { color: white; background-color: rgba(80,160,80,180); "
            "border: 1px solid rgba(255,255,255,60); border-radius: 3px; padding: 0 6px; }"
            "QPushButton:disabled { background-color: rgba(80,80,80,120); color: rgba(255,255,255,80); }"
            "QPushButton:hover { background-color: rgba(100,200,100,200); }"
        )
        self.commit_button.hide()
        # Insert before minimize_button (index 1, after title_label at index 0)
        self.title_bar_layout.insertWidget(1, self.commit_button)
```

The full `title_bar_layout.addWidget` sequence after this change:
```
addWidget(title_label)    # index 0
insertWidget(1, commit_button)  # index 1 — hidden by default
addWidget(minimize_button)
addWidget(maximize_button)
addWidget(close_button)
```

- [ ] **Step 4: Run tests to confirm they pass**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_commit_infrastructure.py::TestCommitInfrastructure::test_commit_button_hidden_by_default -v
```

Expected: PASS (the `commit_button` attribute now exists and is hidden).

The other tests still fail because `set_commit_fn` doesn't exist yet — that's Task 2.

- [ ] **Step 5: Commit**

```bash
git add spyde/qt/subwindow.py spyde/tests/test_commit_infrastructure.py
git commit -m "feat: add hidden Commit button to FramelessSubWindow title bar"
```

---

## Task 2: `set_commit_fn` and `set_commit_enabled` on `PlotWindow`

**Files:**
- Modify: `spyde/drawing/plots/plot_window.py`

- [ ] **Step 1: Add methods to `PlotWindow`**

In `spyde/drawing/plots/plot_window.py`, add after `set_compute_indicator`:

```python
def set_commit_fn(self, fn: callable, label: str = "Commit") -> None:
    """Wire a commit function and show the title-bar Commit button.

    The button starts disabled — call set_commit_enabled(True) once
    the first data is ready.
    """
    from PySide6 import QtCore
    self._commit_fn = fn
    btn = self.title_bar.commit_button
    btn.setText(label)
    # Disconnect any previously connected function to avoid double-firing
    try:
        btn.clicked.disconnect()
    except RuntimeError:
        pass
    btn.clicked.connect(fn)
    btn.setEnabled(False)
    btn.show()

@QtCore.Slot(bool)
def set_commit_enabled(self, enabled: bool) -> None:
    """Enable or disable the title-bar Commit button.

    Decorated as a Slot(bool) so it can be called safely from dask
    callback threads via QMetaObject.invokeMethod(..., QueuedConnection).
    """
    btn = self.title_bar.commit_button
    btn.setEnabled(enabled)
```

- [ ] **Step 2: Run all commit infrastructure tests**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_commit_infrastructure.py -v
```

Expected: all 4 tests pass.

- [ ] **Step 3: Commit**

```bash
git add spyde/drawing/plots/plot_window.py
git commit -m "feat: add set_commit_fn and set_commit_enabled to PlotWindow"
```

---

## Task 3: Migrate virtual imaging to title-bar commit

**Files:**
- Modify: `spyde/actions/pyxem.py`
- Modify: `spyde/tests/test_virtual_image.py`

Remove the caret-box `commit_button` from `add_virtual_image` and replace with `virtual_plot_window.set_commit_fn(_do_commit)`.

- [ ] **Step 1: Update `add_virtual_image` in `spyde/actions/pyxem.py`**

**Remove** the `"commit_button"` entry from the `params` dict:

```python
    params = {
        "type": {
            "name": "Detector Type",
            "type": "enum",
            "default": "disk",
            "options": ["annular", "disk", "rectangle", "multiple_disks"],
        },
        "calculation": {
            "name": "Calculation",
            "type": "enum",
            "default": "mean",
            "options": ["mean", "FEM Omega", "COM"],
        },
        "live_compute_row": {
            "name": "",
            "type": "button_row",
            "buttons": [
                {"key": "live_button", "label": "Live (ON)", "callback": lambda: _toggle_live()},
                {"key": "compute_button", "label": "Compute", "callback": _on_compute_clicked},
            ],
        },
        # commit_button REMOVED — now lives in the PlotWindow title bar
    }
```

**Remove** these lines (no longer needed):

```python
    commit_btn = params_caret_box.get_parameter_widget("commit_button")
    if commit_btn is not None:
        commit_btn.setEnabled(False)
```

**After creating `virtual_plot_window`** (after `virtual_plot_window.set_compute_indicator(indicator)`), add:

```python
    virtual_plot_window.set_commit_fn(_do_commit)
```

**In `_trigger_computation`**, replace the caret-box enable/disable logic:

```python
    def _trigger_computation(_roi=None):
        if _roi is None:
            _roi = roi
        from spyde.drawing.update_functions import compute_virtual_image_kernel
        _timer_holder.clear()
        mask = roi_to_mask(_roi, signal)
        _cached_mask[0] = mask
        _cached_roi[0] = _roi
        future = compute_virtual_image_kernel(signal.data, mask, client, gpu_worker)
        virtual_plot.current_data = future
        _start_progress_poll(future, indicator, client, _timer_holder)
        virtual_plot_window.set_commit_enabled(False)

        def _on_preview_done(fut):
            from PySide6 import QtCore as _QtCore
            _QtCore.QMetaObject.invokeMethod(
                virtual_plot_window, "set_commit_enabled",
                _QtCore.Qt.ConnectionType.QueuedConnection,
                _QtCore.Q_ARG(bool, True),
            )

        future.add_done_callback(_on_preview_done)
```

**In `_do_commit`**, replace `commit_btn.setEnabled(False/True)` with `virtual_plot_window.set_commit_enabled(False/True)`:

```python
    def _do_commit():
        if _cached_mask[0] is None:
            return
        from spyde.drawing.update_functions import compute_virtual_image_kernel
        from pyxem.signals import VirtualDarkFieldImage
        from PySide6 import QtCore as _QtCore

        virtual_plot_window.set_commit_enabled(False)
        indicator.set_computing()
        future = compute_virtual_image_kernel(signal.data, _cached_mask[0], client, gpu_worker)

        def _on_done(fut):
            try:
                result = fut.result()
            except Exception as e:
                print(f"Commit failed: {e}")
                _QtCore.QMetaObject.invokeMethod(
                    virtual_plot_window, "set_commit_enabled",
                    _QtCore.Qt.ConnectionType.QueuedConnection,
                    _QtCore.Q_ARG(bool, True),
                )
                return
            vdf = VirtualDarkFieldImage(result)
            nav_axes = list(signal.axes_manager.navigation_axes)
            sig_axes = list(vdf.axes_manager.signal_axes)
            for i, ax in enumerate(nav_axes):
                if i < len(sig_axes):
                    sig_axes[i].scale = ax.scale
                    sig_axes[i].offset = ax.offset
                    sig_axes[i].units = ax.units
                    sig_axes[i].name = ax.name
            vdf.metadata.Signal.virtual_detector = _roi_metadata(_cached_roi[0] or roi)
            main_window._pending_signal_queue.append(vdf)
            _QtCore.QMetaObject.invokeMethod(
                main_window, "_flush_pending_signals",
                _QtCore.Qt.ConnectionType.QueuedConnection,
            )
            _QtCore.QMetaObject.invokeMethod(
                virtual_plot_window, "set_commit_enabled",
                _QtCore.Qt.ConnectionType.QueuedConnection,
                _QtCore.Q_ARG(bool, True),
            )

        future.add_done_callback(_on_done)
```

- [ ] **Step 2: Update virtual image tests for title-bar commit**

In `spyde/tests/test_virtual_image.py`, find `TestVirtualImageCommit` and update the helper and tests to use the title-bar button instead of the caret box:

Replace the `_setup_with_preview` method and commit button references:

```python
class TestVirtualImageCommit:
    """End-to-end commit tests using the title-bar Commit button."""

    def _setup_with_preview(self, qtbot, win):
        """Add detector, trigger first computation, wait for preview image."""
        tb, vi_widget, action_name, caret_box, roi, preview_window = _add_virtual_detector(qtbot, win)
        preview_plot = preview_window.plots[0]

        roi.sigRegionChangeFinished.emit(roi)
        qtbot.waitUntil(
            lambda: (
                preview_plot.current_data is not None
                and not isinstance(preview_plot.current_data, Future)
            ),
            timeout=10000,
        )
        return caret_box, roi, preview_plot, preview_window

    def test_commit_button_disabled_before_first_computation(self, qtbot, stem_4d_dataset):
        """Commit button in title bar must be disabled immediately after adding a detector."""
        win = stem_4d_dataset["window"]
        tb, vi_widget, action_name, caret_box, roi, preview_window = _add_virtual_detector(qtbot, win)
        assert not preview_window.title_bar.commit_button.isEnabled(), (
            "Commit button should be disabled before any computation"
        )

    def test_commit_button_enabled_after_preview_completes(self, qtbot, stem_4d_dataset):
        """Commit button must become enabled once the first preview computation finishes."""
        win = stem_4d_dataset["window"]
        caret_box, roi, preview_plot, preview_window = self._setup_with_preview(qtbot, win)
        assert preview_window.title_bar.commit_button.isEnabled(), (
            "Commit button should be enabled after preview computation"
        )

    def test_commit_adds_new_signal_tree(self, qtbot, stem_4d_dataset):
        """Clicking title-bar Commit must add exactly one new root to main_window.signal_trees."""
        win = stem_4d_dataset["window"]
        n_before = len(win.signal_trees)
        caret_box, roi, preview_plot, preview_window = self._setup_with_preview(qtbot, win)

        preview_window.title_bar.commit_button.click()

        qtbot.waitUntil(lambda: len(win.signal_trees) == n_before + 1, timeout=10000)
        assert len(win.signal_trees) == n_before + 1

    def test_committed_signal_is_virtual_dark_field(self, qtbot, stem_4d_dataset):
        """The committed signal tree root must be a VirtualDarkFieldImage."""
        from pyxem.signals import VirtualDarkFieldImage
        win = stem_4d_dataset["window"]
        n_before = len(win.signal_trees)
        caret_box, roi, preview_plot, preview_window = self._setup_with_preview(qtbot, win)

        preview_window.title_bar.commit_button.click()

        qtbot.waitUntil(lambda: len(win.signal_trees) == n_before + 1, timeout=10000)
        new_signal = win.signal_trees[n_before].root
        assert isinstance(new_signal, VirtualDarkFieldImage), (
            f"Expected VirtualDarkFieldImage, got {type(new_signal)}"
        )

    def test_committed_signal_axes_match_parent_nav(self, qtbot, stem_4d_dataset):
        """The VDF signal axes must carry the scale/offset of the source navigation axes."""
        win = stem_4d_dataset["window"]
        nav, sig = win.plots
        source_signal = sig.plot_state.current_signal

        n_before = len(win.signal_trees)
        caret_box, roi, preview_plot, preview_window = self._setup_with_preview(qtbot, win)

        preview_window.title_bar.commit_button.click()

        qtbot.waitUntil(lambda: len(win.signal_trees) == n_before + 1, timeout=10000)
        vdf = win.signal_trees[n_before].root

        src_nav = list(source_signal.axes_manager.navigation_axes)
        vdf_sig = list(vdf.axes_manager.signal_axes)
        assert len(vdf_sig) == len(src_nav)
        for i, src_ax in enumerate(src_nav):
            vdf_ax = vdf_sig[i]
            assert abs(vdf_ax.scale - src_ax.scale) < 1e-9
            assert abs(vdf_ax.offset - src_ax.offset) < 1e-9

    def test_committed_signal_has_roi_metadata(self, qtbot, stem_4d_dataset):
        """The committed VDF must carry ROI geometry in metadata.Signal.virtual_detector."""
        win = stem_4d_dataset["window"]
        n_before = len(win.signal_trees)
        caret_box, roi, preview_plot, preview_window = self._setup_with_preview(qtbot, win)

        preview_window.title_bar.commit_button.click()

        qtbot.waitUntil(lambda: len(win.signal_trees) == n_before + 1, timeout=10000)
        vdf = win.signal_trees[n_before].root

        assert vdf.metadata.Signal.virtual_detector is not None
        assert "type" in vdf.metadata.Signal.virtual_detector

    def test_preview_window_remains_open_after_commit(self, qtbot, stem_4d_dataset):
        """The live preview PlotWindow must stay open after committing."""
        win = stem_4d_dataset["window"]
        caret_box, roi, preview_plot, preview_window = self._setup_with_preview(qtbot, win)

        n_trees = len(win.signal_trees)
        preview_window.title_bar.commit_button.click()
        qtbot.waitUntil(lambda: len(win.signal_trees) > n_trees - 1, timeout=10000)
        qtbot.wait(500)

        assert preview_window.isVisible()

    def test_two_commits_produce_two_independent_trees(self, qtbot, stem_4d_dataset):
        """Committing twice must produce two independent signal trees."""
        win = stem_4d_dataset["window"]
        n_before = len(win.signal_trees)
        caret_box, roi, preview_plot, preview_window = self._setup_with_preview(qtbot, win)

        preview_window.title_bar.commit_button.click()
        qtbot.waitUntil(lambda: len(win.signal_trees) == n_before + 1, timeout=10000)
        qtbot.waitUntil(lambda: preview_window.title_bar.commit_button.isEnabled(), timeout=5000)

        preview_window.title_bar.commit_button.click()
        qtbot.waitUntil(lambda: len(win.signal_trees) == n_before + 2, timeout=10000)

        tree1 = win.signal_trees[n_before]
        tree2 = win.signal_trees[n_before + 1]
        assert tree1 is not tree2
        assert tree1.root is not tree2.root
```

- [ ] **Step 3: Run tests**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_commit_infrastructure.py spyde/tests/test_virtual_image.py::TestVirtualImageCommit spyde/tests/test_actions.py::TestActions::test_virtual_imaging -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add spyde/actions/pyxem.py spyde/tests/test_virtual_image.py
git commit -m "refactor: migrate virtual imaging to title-bar commit button"
```

---

## Task 4: Extend `Plot.update()` for 1D no-PlotState data

**Files:**
- Modify: `spyde/drawing/plots/plot.py`

The virtual preview `Plot` has `plot_state = None`. Currently `update()` only handles 2D data in this branch. Line profile previews are 1D.

- [ ] **Step 1: Write failing test**

Add to `spyde/tests/test_commit_infrastructure.py`:

```python
    def test_plot_update_1d_no_plotstate(self, qtbot):
        """Plot.update() with plot_state=None and 1D current_data must call line_item.setData."""
        import numpy as np
        from spyde.qt.shared import open_window
        win = open_window()
        qtbot.addWidget(win)
        pw = win.add_plot_window(is_navigator=False, signal_tree=None)
        plot = pw.add_new_plot()

        # Add line_item to scene (same as the virtual preview fix)
        if plot.line_item not in plot.items:
            plot.addItem(plot.line_item)

        assert plot.plot_state is None

        data_1d = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        plot.current_data = data_1d
        plot.update()

        assert plot.line_item.yData is not None, "1D data not rendered: line_item.yData is None"
        np.testing.assert_array_equal(plot.line_item.yData, data_1d)
        win.close()
```

- [ ] **Step 2: Run to confirm failure**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_commit_infrastructure.py::TestCommitInfrastructure::test_plot_update_1d_no_plotstate -v
```

Expected: FAIL — `line_item.yData is None` because the 2D branch doesn't handle 1D data.

- [ ] **Step 3: Extend the `plot_state is None` branch**

In `spyde/drawing/plots/plot.py`, find the `update()` method and replace the `if self.plot_state is None:` block:

```python
        if self.plot_state is None:
            if self.current_data is not None:
                data = (
                    np.asarray(self.current_data)
                    if isinstance(self.current_data, da.Array)
                    else self.current_data
                )
                if data.ndim == 2:
                    if data.dtype == np.int16:
                        data = data.astype(np.uint16)
                    self.image_item.setImage(data, autoLevels=True, autoDownsample=True)
                elif data.ndim == 1:
                    self.line_item.setData(data)
                self.update_range()
            return
```

- [ ] **Step 4: Run tests**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_commit_infrastructure.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add spyde/drawing/plots/plot.py spyde/tests/test_commit_infrastructure.py
git commit -m "feat: extend Plot.update() to handle 1D data when plot_state is None"
```

---

## Task 5: Line profile kernels in `update_functions.py`

**Files:**
- Modify: `spyde/drawing/update_functions.py`
- Create: `spyde/tests/test_line_profile.py`

**Key facts about `LineROI.getArrayRegion`:**
- Returns shape `(length_px, width_px)` — axis 0 is along the line, axis 1 is perpendicular
- `nanmean(axis=1)` produces the 1D profile of shape `(length_px,)`
- `returnMappedCoords=True` returns `coords` of shape `(2, length_px, width_px)` where `coords[0]` = x (column) indices, `coords[1]` = y (row) indices in the image

- [ ] **Step 1: Write failing tests**

Create `spyde/tests/test_line_profile.py`:

```python
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
```

- [ ] **Step 2: Run to confirm failure**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_line_profile.py::TestLineProfileKernel -v
```

Expected: `ImportError` — kernels do not exist yet.

- [ ] **Step 3: Implement the kernels**

Add to the bottom of `spyde/drawing/update_functions.py`:

```python
def compute_line_profile_kernel(
    image: np.ndarray,
    roi,
    image_item,
    client: distributed.Client,
) -> distributed.Future:
    """Extract a 1D line profile from a 2D image via LineROI.getArrayRegion.

    Parameters
    ----------
    image : np.ndarray, shape (ny, nx)
        The currently displayed image (plot.image_item.image).
    roi : pyqtgraph.LineROI
    image_item : pyqtgraph.ImageItem
    client : dask distributed Client

    Returns
    -------
    distributed.Future resolving to np.ndarray shape (length_px,)

    Notes
    -----
    LineROI.getArrayRegion returns shape (length_px, width_px).
    nanmean over axis=1 collapses the perpendicular width to give the profile.
    """
    region = roi.getArrayRegion(image, image_item)   # (length_px, width_px)
    profile = np.nanmean(region, axis=1)             # (length_px,)
    return client.submit(lambda p=profile: p)


def compute_nav_line_sum_kernel(
    data: da.Array,
    ys: np.ndarray,
    xs: np.ndarray,
    client: distributed.Client,
    gpu_worker_address: "str | None",
) -> distributed.Future:
    """Compute the mean diffraction pattern over all nav pixels in a line strip.

    Parameters
    ----------
    data : dask array, shape (...nav..., nkx, nky)
        HyperSpy convention: last two axes are signal.
    ys : np.ndarray, shape (N,)
        Row (y) pixel indices of all nav pixels inside the strip.
    xs : np.ndarray, shape (N,)
        Column (x) pixel indices of all nav pixels inside the strip.
    client : dask distributed Client
    gpu_worker_address : str or None

    Returns
    -------
    distributed.Future resolving to np.ndarray shape (nkx, nky)
    """
    nav_slices = data[ys, xs]          # (N, nkx, nky)
    resources = {"GPU": 1} if gpu_worker_address else {}
    with dask.annotate(resources=resources):
        result = da.mean(nav_slices, axis=0)
    return client.compute(result)
```

- [ ] **Step 4: Run tests**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_line_profile.py::TestLineProfileKernel -v
```

Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add spyde/drawing/update_functions.py spyde/tests/test_line_profile.py
git commit -m "feat: add compute_line_profile_kernel and compute_nav_line_sum_kernel"
```

---

## Task 6: `add_line_profile` — signal-plot case

**Files:**
- Create: `spyde/actions/line_profile.py`
- Modify: `spyde/toolbars.yaml`
- Modify: `spyde/tests/test_line_profile.py`

- [ ] **Step 1: Write failing integration tests**

Add to `spyde/tests/test_line_profile.py`:

```python
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
        tb, lp_widget, action_name, caret_box, roi, preview_window = _add_line_profile_on_signal(qtbot, win)
        preview_plot = preview_window.plots[0]
        nav, sig = win.plots

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
```

- [ ] **Step 2: Run to confirm failure**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_line_profile.py::TestLineProfileSignalPlot::test_spawns_one_preview_window -v
```

Expected: `AssertionError` — "Line Profile action not found in signal toolbar".

- [ ] **Step 3: Add YAML entry**

In `spyde/toolbars.yaml`, add after the `Virtual Imaging` block:

```yaml
  Line Profile:
    description: Extract a 1D line profile from the current 2D plot.
    icon: drawing/toolbars/icons/virtual_imaging.svg
    function: spyde.actions.line_profile.line_profile_action
    plot_dim: [2]
    toolbar_side: bottom
    toggle: True
    submenu: True
    subfunctions:
      add_line_profile:
        name: Add Line Profile
        description: Add a line profile ROI to the plot.
        icon: drawing/toolbars/icons/zoom.svg
        function: spyde.actions.line_profile.add_line_profile
```

**Note on icon:** Use `virtual_imaging.svg` as a placeholder — replace with a dedicated line-profile icon when one is available. The `zoom.svg` icon is used for the subfunction.

- [ ] **Step 4: Create `spyde/actions/line_profile.py`** with the signal-plot case only first:

```python
"""Line profile action for any 2D plot.

Two cases:
- Signal plot (is_navigator=False): LineROI on the image → 1D profile → Signal1D commit
- Navigator plot (is_navigator=True): LineROI on nav image → two previews:
    1. Instant 1D profile from the rendered nav image
    2. Lazy dask sum of diffraction patterns in the strip → Signal2D commit
"""
import numpy as np
import dask.array as da
from collections import deque

import pyqtgraph as pg
from pyqtgraph import mkPen
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtCore import Qt

from spyde.drawing.toolbars.toolbar import RoundedToolBar
from spyde.drawing.toolbars.plot_control_toolbar import resolve_icon_path
from spyde.actions.pyxem import _start_progress_poll


COLORS = ["red", "green", "blue", "yellow", "cyan", "magenta"]


def line_profile_action(*args, **kwargs):
    """Placeholder for the Line Profile toolbar toggle."""
    pass


def _make_pen_and_icon(toolbar):
    """Return (color_str, pen, QIcon) cycling through COLORS based on action count."""
    num = toolbar.num_actions()
    color = COLORS[num % len(COLORS)]
    pen = mkPen(color=color, width=3)
    icon_path = resolve_icon_path("drawing/toolbars/icons/virtual_imaging.svg")
    base_icon = QIcon(icon_path)
    icon_size = toolbar.iconSize()
    dpr = getattr(toolbar, "devicePixelRatioF", lambda: 1.0)()
    req_w = max(1, int(icon_size.width() * dpr))
    req_h = max(1, int(icon_size.height() * dpr))
    base_pixmap = base_icon.pixmap(req_w, req_h)
    colored = QPixmap(base_pixmap.size())
    colored.setDevicePixelRatio(dpr)
    colored.fill(Qt.GlobalColor.transparent)
    p = QPainter(colored)
    p.drawPixmap(0, 0, base_pixmap)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(colored.rect(), QColor(color))
    p.end()
    icon = QIcon()
    icon.addPixmap(colored)
    return color, pen, icon


def _get_line_nav_coords(roi, image_item, nav_shape):
    """Extract pixel coords along the line centre and all strip pixels.

    Returns
    -------
    line_ys : np.ndarray shape (N,)  — row indices of the N line-centre points
    line_xs : np.ndarray shape (N,)  — col indices of the N line-centre points
    strip_ys : np.ndarray shape (M,) — all row indices inside the full strip
    strip_xs : np.ndarray shape (M,) — all col indices inside the full strip
    N : int                          — number of points along the line
    coords : np.ndarray shape (2, N, W) — raw coords for per-column slicing
    """
    dummy = np.zeros(nav_shape, dtype=np.float32)
    _, coords = roi.getArrayRegion(dummy, image_item, returnMappedCoords=True)
    # coords shape: (2, length_px, width_px)
    # coords[0] = x (column) indices, coords[1] = y (row) indices
    mid_w = coords.shape[2] // 2
    line_xs = np.clip(np.round(coords[0, :, mid_w]).astype(int), 0, nav_shape[1] - 1)
    line_ys = np.clip(np.round(coords[1, :, mid_w]).astype(int), 0, nav_shape[0] - 1)
    strip_xs = np.clip(np.round(coords[0]).astype(int).ravel(), 0, nav_shape[1] - 1)
    strip_ys = np.clip(np.round(coords[1]).astype(int).ravel(), 0, nav_shape[0] - 1)
    N = line_ys.shape[0]
    return line_ys, line_xs, strip_ys, strip_xs, N, coords


def add_line_profile(
    toolbar: RoundedToolBar,
    action_name: str = "Add Line Profile",
    *args,
    **kwargs,
):
    """Add a LineROI to the current 2D plot and wire live preview + title-bar commit."""
    from spyde.qt.compute_status_indicator import ComputeStatusIndicator
    from spyde.drawing.plots.plot_window import PlotWindow as _PlotWindow

    color, pen, icon = _make_pen_and_icon(toolbar)
    action_name = f"Line Profile ({color})"

    plot = toolbar.parent_toolbar.plot
    signal = plot.plot_state.current_signal
    main_window = plot.main_window
    client = main_window.client
    gpu_worker = getattr(main_window, "_gpu_worker_address", None)

    _live_enabled = [True]
    _timer_holder = []
    _cached_profile = [None]  # last computed 1D profile (numpy array)

    def _on_compute_clicked():
        _trigger_computation()

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
                {"key": "live_button", "label": "Live (ON)", "callback": lambda: _toggle_live()},
                {"key": "compute_button", "label": "Compute", "callback": _on_compute_clicked},
            ],
        },
    }

    action, params_caret_box = toolbar.add_action(
        name=action_name,
        icon_path=icon,
        function=line_profile_action,
        toggle=True,
        parameters=params,
    )
    try:
        if hasattr(params_caret_box, "finalize_layout"):
            params_caret_box.finalize_layout()
    except Exception:
        pass

    # ── Place LineROI ────────────────────────────────────────────────────────
    # Centre the line horizontally across the middle 60% of the image
    img_item = plot.image_item
    transform = img_item.transform()
    img_w = img_item.width()
    img_h = img_item.height()
    from PySide6 import QtCore
    center = transform.map(QtCore.QPointF(img_w / 2, img_h / 2))
    cx, cy = center.x(), center.y()
    # get data-unit width from signal axes
    if signal is not None and signal.axes_manager.signal_axes:
        ax0 = signal.axes_manager.signal_axes[1]  # x-axis (columns)
        data_width = ax0.size * abs(ax0.scale)
    else:
        data_width = img_w
    half_len = data_width * 0.3
    pos1 = [cx - half_len, cy]
    pos2 = [cx + half_len, cy]
    roi = pg.LineROI(pos1, pos2, width=1, pen=pen)
    toolbar.parent_toolbar.register_action_plot_item(
        action_name="Line Profile", item=roi, key=action_name
    )

    # ── Spawn preview PlotWindow ────────────────────────────────────────────
    preview_window = main_window.add_plot_window(is_navigator=False, signal_tree=None)
    preview_plot = preview_window.add_new_plot()
    if preview_plot.line_item not in preview_plot.items:
        preview_plot.addItem(preview_plot.line_item)
    indicator = ComputeStatusIndicator(color=color)
    preview_window.set_compute_indicator(indicator)
    toolbar.parent_toolbar.register_action_plot_window(
        action_name="Line Profile", plot_window=preview_window, key=action_name
    )

    # ── Computation ─────────────────────────────────────────────────────────
    def _trigger_computation():
        from spyde.drawing.update_functions import compute_line_profile_kernel
        image = plot.image_item.image
        if image is None:
            return
        _timer_holder.clear()
        future = compute_line_profile_kernel(image, roi, plot.image_item, client)
        preview_plot.current_data = future
        _start_progress_poll(future, indicator, client, _timer_holder)
        preview_window.set_commit_enabled(False)

        def _on_done(fut):
            from PySide6 import QtCore as _QtCore
            try:
                result = fut.result()
                _cached_profile[0] = result
            except Exception:
                pass
            _QtCore.QMetaObject.invokeMethod(
                preview_window, "set_commit_enabled",
                _QtCore.Qt.ConnectionType.QueuedConnection,
                _QtCore.Q_ARG(bool, True),
            )

        future.add_done_callback(_on_done)

    def _on_roi_finished(_roi=None):
        if not _live_enabled[0]:
            return
        _trigger_computation()

    roi.sigRegionChangeFinished.connect(_on_roi_finished)

    def _toggle_live():
        live_btn = params_caret_box.get_parameter_widget("live_button")
        _live_enabled[0] = not _live_enabled[0]
        if live_btn is not None:
            live_btn.setText("Live (ON)" if _live_enabled[0] else "Live (OFF)")

    # ── Commit ──────────────────────────────────────────────────────────────
    def _do_commit_signal():
        import hyperspy.api as hs
        from PySide6 import QtCore as _QtCore
        profile = _cached_profile[0]
        if profile is None:
            return
        preview_window.set_commit_enabled(False)
        sig = hs.signals.Signal1D(profile.copy())
        # Axis scale: Euclidean line length in data coords / n_points
        handles = roi.getHandles()
        p1 = roi.mapToParent(handles[0].pos())
        p2 = roi.mapToParent(handles[1].pos())
        import math
        line_len = math.sqrt((p2.x() - p1.x())**2 + (p2.y() - p1.y())**2)
        n_points = len(profile)
        sig.axes_manager.signal_axes[0].scale = line_len / n_points if n_points > 0 else 1.0
        if signal is not None and signal.axes_manager.signal_axes:
            sig.axes_manager.signal_axes[0].units = signal.axes_manager.signal_axes[0].units
        main_window._pending_signal_queue.append(sig)
        _QtCore.QMetaObject.invokeMethod(
            main_window, "_flush_pending_signals",
            _QtCore.Qt.ConnectionType.QueuedConnection,
        )
        _QtCore.QMetaObject.invokeMethod(
            preview_window, "set_commit_enabled",
            _QtCore.Qt.ConnectionType.QueuedConnection,
            _QtCore.Q_ARG(bool, True),
        )

    preview_window.set_commit_fn(_do_commit_signal)
```

- [ ] **Step 5: Run signal-plot tests**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_line_profile.py::TestLineProfileSignalPlot -v
```

Expected: all 8 tests pass.

- [ ] **Step 6: Run existing virtual image and action tests as regression check**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_actions.py::TestActions::test_virtual_imaging -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add spyde/actions/line_profile.py spyde/toolbars.yaml spyde/tests/test_line_profile.py
git commit -m "feat: add line profile action (signal-plot case) with title-bar commit"
```

---

## Task 7: Navigator-plot case in `add_line_profile`

**Files:**
- Modify: `spyde/actions/line_profile.py`
- Modify: `spyde/tests/test_line_profile.py`

- [ ] **Step 1: Write failing integration tests**

Add to `spyde/tests/test_line_profile.py`:

```python
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
        # Shape: (N, nkx, nky) — N depends on line length
        assert new_signal.data.ndim == 3
        assert new_signal.data.shape[1] == nky  # HyperSpy stores signal as (ny, nx) = (nky, nkx)
        assert new_signal.data.shape[2] == nkx

    def test_committed_signal_nav_axis_scale(self, qtbot, stem_4d_dataset):
        """Nav axis scale of committed signal must match source nav pixel scale."""
        import hyperspy.api as hs
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
        # Nav axis scale must equal source signal nav pixel scale
        src_scale = abs(source_signal.axes_manager.navigation_axes[0].scale)
        committed_scale = abs(new_signal.axes_manager.navigation_axes[0].scale)
        assert abs(committed_scale - src_scale) / max(src_scale, 1e-10) < 0.01, (
            f"Nav axis scale mismatch: committed={committed_scale}, source={src_scale}"
        )

    def test_committed_signal_has_correct_nav_units(self, qtbot, stem_4d_dataset):
        """Nav axis units of committed signal must match source nav axis units."""
        import hyperspy.api as hs
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
        import hyperspy.api as hs
        win = stem_4d_dataset["window"]
        n_before = len(win.signal_trees)
        tb, lp_widget, action_name, caret_box, roi, profile_window, sum_window = _add_line_profile_on_nav(qtbot, win)
        sum_plot = sum_window.plots[0]

        # Set width > 1
        width_widget = params_caret_box = caret_box.get_parameter_widget("width")
        width_widget.setText("3")

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
        assert new_signal.data.ndim == 3, "Width > 1 must still produce 3D signal"
```

- [ ] **Step 2: Run to confirm failure**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_line_profile.py::TestLineProfileNavPlot::test_spawns_two_preview_windows -v
```

Expected: `AssertionError` — only 1 window spawned (nav case not implemented yet).

- [ ] **Step 3: Add navigator-plot wiring to `add_line_profile`**

In `spyde/actions/line_profile.py`, replace the final section that currently only wires the signal-plot case. The `add_line_profile` function must branch on `plot.is_navigator`. The signal-plot code already works; now add the `else` branch for navigators and restructure the function:

```python
    # ── Branch: signal plot vs navigator plot ───────────────────────────────
    if not plot.is_navigator:
        # ── Signal plot: 1 preview window, Signal1D commit ──────────────────
        preview_window = main_window.add_plot_window(is_navigator=False, signal_tree=None)
        preview_plot = preview_window.add_new_plot()
        if preview_plot.line_item not in preview_plot.items:
            preview_plot.addItem(preview_plot.line_item)
        indicator = ComputeStatusIndicator(color=color)
        preview_window.set_compute_indicator(indicator)
        toolbar.parent_toolbar.register_action_plot_window(
            action_name="Line Profile", plot_window=preview_window, key=action_name
        )

        def _trigger_computation():
            from spyde.drawing.update_functions import compute_line_profile_kernel
            image = plot.image_item.image
            if image is None:
                return
            _timer_holder.clear()
            future = compute_line_profile_kernel(image, roi, plot.image_item, client)
            preview_plot.current_data = future
            _start_progress_poll(future, indicator, client, _timer_holder)
            preview_window.set_commit_enabled(False)

            def _on_done(fut):
                from PySide6 import QtCore as _QtCore
                try:
                    result = fut.result()
                    _cached_profile[0] = result
                except Exception:
                    pass
                _QtCore.QMetaObject.invokeMethod(
                    preview_window, "set_commit_enabled",
                    _QtCore.Qt.ConnectionType.QueuedConnection,
                    _QtCore.Q_ARG(bool, True),
                )

            future.add_done_callback(_on_done)

        def _on_roi_finished(_roi=None):
            if not _live_enabled[0]:
                return
            _trigger_computation()

        roi.sigRegionChangeFinished.connect(_on_roi_finished)

        def _do_commit_signal():
            import hyperspy.api as hs
            import math
            from PySide6 import QtCore as _QtCore
            profile = _cached_profile[0]
            if profile is None:
                return
            preview_window.set_commit_enabled(False)
            sig = hs.signals.Signal1D(profile.copy())
            handles = roi.getHandles()
            p1 = roi.mapToParent(handles[0].pos())
            p2 = roi.mapToParent(handles[1].pos())
            line_len = math.sqrt((p2.x() - p1.x())**2 + (p2.y() - p1.y())**2)
            n_points = len(profile)
            sig.axes_manager.signal_axes[0].scale = line_len / n_points if n_points > 0 else 1.0
            if signal is not None and signal.axes_manager.signal_axes:
                sig.axes_manager.signal_axes[0].units = signal.axes_manager.signal_axes[0].units
            main_window._pending_signal_queue.append(sig)
            _QtCore.QMetaObject.invokeMethod(
                main_window, "_flush_pending_signals",
                _QtCore.Qt.ConnectionType.QueuedConnection,
            )
            _QtCore.QMetaObject.invokeMethod(
                preview_window, "set_commit_enabled",
                _QtCore.Qt.ConnectionType.QueuedConnection,
                _QtCore.Q_ARG(bool, True),
            )

        preview_window.set_commit_fn(_do_commit_signal)

    else:
        # ── Navigator plot: 2 preview windows ───────────────────────────────
        _cached_line_info = [None]  # (line_ys, line_xs, N, coords)

        # Window 1: instant 1D profile
        profile_window = main_window.add_plot_window(is_navigator=False, signal_tree=None)
        profile_plot = profile_window.add_new_plot()
        if profile_plot.line_item not in profile_plot.items:
            profile_plot.addItem(profile_plot.line_item)
        toolbar.parent_toolbar.register_action_plot_window(
            action_name="Line Profile", plot_window=profile_window,
            key=action_name + "_profile"
        )

        # Window 2: lazy dask sum diffraction
        sum_indicator = ComputeStatusIndicator(color=color)
        sum_window = main_window.add_plot_window(is_navigator=False, signal_tree=None)
        sum_plot = sum_window.add_new_plot()
        if sum_plot.image_item not in sum_plot.items:
            sum_plot.addItem(sum_plot.image_item)
        sum_window.set_compute_indicator(sum_indicator)
        toolbar.parent_toolbar.register_action_plot_window(
            action_name="Line Profile", plot_window=sum_window,
            key=action_name + "_sum"
        )

        def _trigger_computation():
            from spyde.drawing.update_functions import compute_nav_line_sum_kernel
            # Instant profile from the rendered nav image
            image = plot.image_item.image
            if image is not None:
                region = roi.getArrayRegion(image, plot.image_item)
                instant_profile = np.nanmean(region, axis=1)
                profile_plot.current_data = instant_profile
                profile_plot.update()

            # Lazy dask sum
            _timer_holder.clear()
            nav_shape = (signal.axes_manager.navigation_shape[1],
                         signal.axes_manager.navigation_shape[0])  # (ny, nx)
            line_ys, line_xs, strip_ys, strip_xs, N, coords = _get_line_nav_coords(
                roi, plot.image_item, nav_shape
            )
            _cached_line_info[0] = (line_ys, line_xs, N, coords)
            future = compute_nav_line_sum_kernel(
                signal.data, strip_ys, strip_xs, client, gpu_worker
            )
            sum_plot.current_data = future
            _start_progress_poll(future, sum_indicator, client, _timer_holder)
            sum_window.set_commit_enabled(False)

            def _on_sum_done(fut):
                from PySide6 import QtCore as _QtCore
                try:
                    fut.result()
                except Exception:
                    pass
                _QtCore.QMetaObject.invokeMethod(
                    sum_window, "set_commit_enabled",
                    _QtCore.Qt.ConnectionType.QueuedConnection,
                    _QtCore.Q_ARG(bool, True),
                )

            future.add_done_callback(_on_sum_done)

        def _on_roi_finished(_roi=None):
            if not _live_enabled[0]:
                return
            _trigger_computation()

        roi.sigRegionChangeFinished.connect(_on_roi_finished)

        def _do_commit_nav():
            import hyperspy.api as hs
            from PySide6 import QtCore as _QtCore
            if _cached_line_info[0] is None:
                return
            line_ys, line_xs, N, coords = _cached_line_info[0]
            sum_window.set_commit_enabled(False)

            # Get current width from caret box
            width_widget = params_caret_box.get_parameter_widget("width")
            try:
                width_val = int(width_widget.text()) if width_widget else 1
            except (ValueError, TypeError):
                width_val = 1

            nav_shape = (signal.axes_manager.navigation_shape[1],
                         signal.axes_manager.navigation_shape[0])

            # Build lazy stack: one diffraction pattern per line point
            slices = []
            for i in range(N):
                if width_val <= 1:
                    yi = int(np.clip(line_ys[i], 0, nav_shape[0] - 1))
                    xi = int(np.clip(line_xs[i], 0, nav_shape[1] - 1))
                    slices.append(signal.data[yi, xi])
                else:
                    col_xs = np.clip(
                        np.round(coords[0, i, :]).astype(int), 0, nav_shape[1] - 1
                    )
                    col_ys = np.clip(
                        np.round(coords[1, i, :]).astype(int), 0, nav_shape[0] - 1
                    )
                    slices.append(da.mean(signal.data[col_ys, col_xs], axis=0))

            result_lazy = da.stack(slices, axis=0)  # (N, nkx, nky)
            future = client.compute(result_lazy)

            def _on_done(fut):
                from PySide6 import QtCore as _QtCore
                try:
                    arr = fut.result()
                except Exception as e:
                    print(f"Line profile commit failed: {e}")
                    _QtCore.QMetaObject.invokeMethod(
                        sum_window, "set_commit_enabled",
                        _QtCore.Qt.ConnectionType.QueuedConnection,
                        _QtCore.Q_ARG(bool, True),
                    )
                    return
                committed_sig = hs.signals.Signal2D(arr)
                # Nav axis: position along line, scale = source nav scale
                src_nav_ax = signal.axes_manager.navigation_axes[0]
                committed_sig.axes_manager.navigation_axes[0].scale = abs(src_nav_ax.scale)
                committed_sig.axes_manager.navigation_axes[0].units = src_nav_ax.units
                committed_sig.axes_manager.navigation_axes[0].name = "line position"
                # Signal axes: copy from source
                for i, ax in enumerate(signal.axes_manager.signal_axes):
                    committed_sig.axes_manager.signal_axes[i].scale = ax.scale
                    committed_sig.axes_manager.signal_axes[i].offset = ax.offset
                    committed_sig.axes_manager.signal_axes[i].units = ax.units
                    committed_sig.axes_manager.signal_axes[i].name = ax.name
                main_window._pending_signal_queue.append(committed_sig)
                _QtCore.QMetaObject.invokeMethod(
                    main_window, "_flush_pending_signals",
                    _QtCore.Qt.ConnectionType.QueuedConnection,
                )
                _QtCore.QMetaObject.invokeMethod(
                    sum_window, "set_commit_enabled",
                    _QtCore.Qt.ConnectionType.QueuedConnection,
                    _QtCore.Q_ARG(bool, True),
                )

            future.add_done_callback(_on_done)

        sum_window.set_commit_fn(_do_commit_nav)

    def _toggle_live():
        live_btn = params_caret_box.get_parameter_widget("live_button")
        _live_enabled[0] = not _live_enabled[0]
        if live_btn is not None:
            live_btn.setText("Live (ON)" if _live_enabled[0] else "Live (OFF)")
```

- [ ] **Step 4: Run navigator-plot tests**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_line_profile.py::TestLineProfileNavPlot -v
```

Expected: all 10 tests pass.

- [ ] **Step 5: Run full test suite (non-GPU)**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_line_profile.py spyde/tests/test_commit_infrastructure.py spyde/tests/test_virtual_image.py -v -k "not gpu"
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add spyde/actions/line_profile.py spyde/tests/test_line_profile.py
git commit -m "feat: add line profile navigator-plot case (two preview windows, Signal2D commit)"
```

---

## Task 8: Axis scale correctness tests

**Files:**
- Modify: `spyde/tests/test_line_profile.py`

These tests use synthetic data with known axis scales to verify the committed signals carry the correct metadata.

- [ ] **Step 1: Write axis scale tests**

Add to `spyde/tests/test_line_profile.py`:

```python
class TestLineProfileAxisScale:
    """Dedicated axis scale/units correctness with synthetic data."""

    def _make_4d_signal_with_known_axes(self):
        """4D STEM signal with explicitly set nav and signal axes."""
        import hyperspy.api as hs
        data = np.ones((6, 6, 8, 8), dtype=np.float32)
        sig = hs.signals.Signal2D(data)
        # Nav axes: 0.5 nm/pixel
        sig.axes_manager.navigation_axes[0].scale = 0.5
        sig.axes_manager.navigation_axes[0].units = "nm"
        sig.axes_manager.navigation_axes[0].name = "x"
        sig.axes_manager.navigation_axes[1].scale = 0.5
        sig.axes_manager.navigation_axes[1].units = "nm"
        sig.axes_manager.navigation_axes[1].name = "y"
        # Signal axes: 0.1 1/nm per pixel
        sig.axes_manager.signal_axes[0].scale = 0.1
        sig.axes_manager.signal_axes[0].units = "1/nm"
        sig.axes_manager.signal_axes[1].scale = 0.1
        sig.axes_manager.signal_axes[1].units = "1/nm"
        return sig

    def test_nav_line_committed_signal_axes_scale_and_units(self, qtbot, stem_4d_dataset):
        """Committed nav-line signal: nav axis scale and units match source nav axes."""
        import hyperspy.api as hs
        from spyde.qt.shared import open_window, create_data
        win = open_window()
        qtbot.addWidget(win)

        # Load synthetic signal with known axes
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
        assert lp_action is not None
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
        plot_windows = tb.action_widgets["Line Profile"].get("plot_windows", {})
        sum_window = plot_windows.get(action_name + "_sum")
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

        # Signal axes must also be copied
        sig_axes = committed.axes_manager.signal_axes
        assert abs(sig_axes[0].scale - 0.1) < 1e-6
        assert sig_axes[0].units == "1/nm"

        win.close()
```

- [ ] **Step 2: Run axis scale tests**

```
.venv/Scripts/python.exe -m pytest spyde/tests/test_line_profile.py::TestLineProfileAxisScale -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add spyde/tests/test_line_profile.py
git commit -m "test: add axis scale correctness tests for nav-line profile commit"
```

---

## Self-Review

### Spec coverage

| Spec section | Covered by task |
|---|---|
| 3.1 `commit_button` in `FramelessSubWindow` | Task 1 |
| 3.2 `set_commit_fn`, `set_commit_enabled` on `PlotWindow` | Task 2 |
| 3.3 Virtual imaging migration to title-bar commit | Task 3 |
| 4.1 `compute_line_profile_kernel` | Task 5 |
| 4.2 `compute_nav_line_sum_kernel` | Task 5 |
| 4.3 `_get_line_nav_coords` | Task 6 (implemented inline in `line_profile.py`) |
| 5.3 Caret box: Width + Live/Compute button_row | Task 6 |
| 5.4 Signal-plot wiring | Task 6 |
| 5.5 Signal-plot preview + commit | Task 6 |
| 5.6 Nav-plot 2-window wiring + commit | Task 7 |
| 5.7 Width parameter wiring | Task 7 (`_do_commit_nav` uses width from caret box) |
| 6. `Plot.update()` 1D no-PlotState | Task 4 |
| 7. YAML entry | Task 6 |
| 8.1 `TestCommitInfrastructure` | Task 1 + 2 + 3 |
| 8.2 `TestLineProfileKernel` | Task 5 |
| 8.3 `TestLineProfileSignalPlot` end-to-end | Task 6 |
| 8.4 `TestLineProfileNavPlot` end-to-end | Task 7 |
| 8.5 `TestLineProfileAxisScale` | Task 8 |

All spec sections are covered. No placeholders.
