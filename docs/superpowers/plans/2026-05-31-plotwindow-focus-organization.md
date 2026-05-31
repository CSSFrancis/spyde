# PlotWindow Focus & Organization Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a 3-state visibility model for PlotWindows (Shown/Background/Hidden), move the commit button and status indicator into the title bar left zone, auto-position preview windows near their owner, and add a tile button.

**Architecture:** Every `PlotWindow` gets an `owner_plot_window` attribute and always has a `signal_tree`. `MainWindow.on_subwindow_activated` drives visibility state changes centrally. Title bar layout is restructured in `FramelessSubWindow`. Preview placement and tiling are utility methods on `MainWindow`.

**Tech Stack:** PySide6, pyqtgraph, pytest-qt

---

## File Map

| File | Change |
|---|---|
| `spyde/drawing/plots/plot_window.py` | Add `owner_plot_window` attribute; update `set_compute_indicator` to insert into title bar |
| `spyde/qt/subwindow.py` | Restructure title bar layout: `[status_placeholder][commit][title][min][max][close]`; restyle commit button |
| `spyde/__main__.py` | Update `on_subwindow_activated` for 3-state visibility; update `add_plot_window` for auto-placement; add `tile_active_windows` slot + View menu entry |
| `spyde/actions/line_profile.py` | Pass `signal_tree` and set `owner_plot_window` on all preview windows |
| `spyde/actions/pyxem.py` | Pass `signal_tree` and set `owner_plot_window` on preview window |
| `spyde/actions/base.py` | Pass `signal_tree` and set `owner_plot_window` on preview window |
| `spyde/tests/test_line_profile.py` | Add tests for visibility state after activation |
| `spyde/tests/test_virtual_image.py` | Add test for owner_plot_window tagging |

---

## Task 1: Add `owner_plot_window` attribute to `PlotWindow`

**Files:**
- Modify: `spyde/drawing/plots/plot_window.py:52-107`
- Test: `spyde/tests/test_line_profile.py`

- [ ] **Step 1: Write the failing test**

Add to `spyde/tests/test_line_profile.py`:

```python
def test_preview_window_has_owner_plot_window(qtbot, stem_4d_dataset):
    """Preview windows created by line profile must have owner_plot_window set."""
    win = stem_4d_dataset["window"]
    nav_window = stem_4d_dataset["subwindows"][0]
    # activate the nav window so toolbar is available
    win.mdi_area.setActiveSubWindow(nav_window)
    qtbot.wait(100)
    plot = nav_window.current_plot_item
    toolbar = plot.plot_state.toolbar_top
    n_before = len(win.plot_subwindows)
    toolbar.add_line_profile_action()
    qtbot.wait(100)
    new_windows = [pw for pw in win.plot_subwindows[n_before:]]
    for pw in new_windows:
        assert pw.owner_plot_window is not None, (
            f"Preview window {pw} missing owner_plot_window"
        )
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest spyde/tests/test_line_profile.py::test_preview_window_has_owner_plot_window -v
```

Expected: `AttributeError: 'PlotWindow' object has no attribute 'owner_plot_window'`

- [ ] **Step 3: Add `owner_plot_window` to `PlotWindow.__init__`**

In `spyde/drawing/plots/plot_window.py`, inside `__init__` after `self._commit_connection = None`:

```python
self.owner_plot_window = None  # type: "PlotWindow | None"
```

- [ ] **Step 4: Run test to verify it still fails (now for the right reason)**

```
pytest spyde/tests/test_line_profile.py::test_preview_window_has_owner_plot_window -v
```

Expected: `AssertionError` — attribute exists but is still `None` (will be fixed in Task 2).

- [ ] **Step 5: Commit**

```bash
git add spyde/drawing/plots/plot_window.py spyde/tests/test_line_profile.py
git commit -m "feat: add owner_plot_window attribute to PlotWindow"
```

---

## Task 2: Tag preview windows in `line_profile.py`, `pyxem.py`, `base.py`

**Files:**
- Modify: `spyde/actions/line_profile.py:161-170`, `spyde/actions/line_profile.py:243-262`
- Modify: `spyde/actions/pyxem.py` (virtual image preview window creation)
- Modify: `spyde/actions/base.py` (generic action preview window creation)
- Test: `spyde/tests/test_line_profile.py`, `spyde/tests/test_virtual_image.py`

- [ ] **Step 1: Update `line_profile.py` signal-plot branch**

In `spyde/actions/line_profile.py`, in the `if not plot.is_navigator:` branch, change:

```python
preview_window = main_window.add_plot_window(is_navigator=False, signal_tree=None)
```

to:

```python
preview_window = main_window.add_plot_window(
    is_navigator=False, signal_tree=plot.plot_state.current_signal and plot.signal_tree or None
)
preview_window.owner_plot_window = plot.plot_window
```

Wait — `plot.signal_tree` is the cleanest path. Use:

```python
preview_window = main_window.add_plot_window(
    is_navigator=False, signal_tree=plot.signal_tree
)
preview_window.owner_plot_window = plot.plot_window
```

- [ ] **Step 2: Update `line_profile.py` navigator branch**

In `spyde/actions/line_profile.py`, in the `else:` (navigator) branch, change both `add_plot_window` calls:

```python
profile_window = main_window.add_plot_window(
    is_navigator=False, signal_tree=plot.signal_tree
)
profile_window.owner_plot_window = plot.plot_window
```

```python
sum_window = main_window.add_plot_window(
    is_navigator=False, signal_tree=plot.signal_tree
)
sum_window.owner_plot_window = plot.plot_window
```

- [ ] **Step 3: Update `pyxem.py`**

Find the `add_plot_window` call that creates the virtual image preview window in `spyde/actions/pyxem.py`. Change `signal_tree=None` to `signal_tree=plot.signal_tree` and add `owner_plot_window`:

```python
virtual_plot_window = main_window.add_plot_window(
    is_navigator=False, signal_tree=plot.signal_tree
)
virtual_plot_window.owner_plot_window = plot.plot_window
```

- [ ] **Step 4: Update `base.py`**

Find the `add_plot_window` call in `spyde/actions/base.py` (around line 111). Change to:

```python
plot_window = m_window.add_plot_window(
    is_navigator=False,
    signal_tree=getattr(plot, 'signal_tree', None),
)
plot_window.owner_plot_window = plot.plot_window
```

- [ ] **Step 5: Verify `plot.signal_tree` exists on `Plot`**

```
grep -n "signal_tree" spyde/drawing/plots/plot.py | head -20
```

Confirm `Plot` has a `signal_tree` attribute (set at construction). If not, access it via `plot.plot_window.signal_tree`.

- [ ] **Step 6: Run tests**

```
pytest spyde/tests/test_line_profile.py::test_preview_window_has_owner_plot_window -v
pytest spyde/tests/test_virtual_image.py -v
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add spyde/actions/line_profile.py spyde/actions/pyxem.py spyde/actions/base.py
git commit -m "feat: tag preview windows with owner_plot_window and signal_tree"
```

---

## Task 3: Implement 3-state visibility in `on_subwindow_activated`

**Files:**
- Modify: `spyde/__main__.py:899-961`
- Test: `spyde/tests/test_line_profile.py`

- [ ] **Step 1: Write failing tests**

Add to `spyde/tests/test_line_profile.py`:

```python
def test_preview_window_hidden_when_other_signal_tree_active(qtbot, stem_4d_dataset):
    """Preview windows are hidden when a different SignalTree's window is active."""
    win = stem_4d_dataset["window"]
    nav_window = stem_4d_dataset["subwindows"][0]
    win.mdi_area.setActiveSubWindow(nav_window)
    qtbot.wait(100)
    plot = nav_window.current_plot_item
    toolbar = plot.plot_state.toolbar_top
    n_before = len(win.plot_subwindows)
    toolbar.add_line_profile_action()
    qtbot.wait(100)
    preview_windows = [pw for pw in win.plot_subwindows[n_before:]]

    # Create a second signal tree so there's an "other" active window
    from spyde.qt.shared import create_data
    import hyperspy.api as hs
    sig2 = hs.signals.Signal2D(create_data((64, 64)))
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
    plot = nav_window.current_plot_item
    toolbar = plot.plot_state.toolbar_top
    n_before = len(win.plot_subwindows)
    toolbar.add_line_profile_action()
    qtbot.wait(100)
    preview_windows = [pw for pw in win.plot_subwindows[n_before:]]

    # Switch away
    from spyde.qt.shared import create_data
    import hyperspy.api as hs
    sig2 = hs.signals.Signal2D(create_data((64, 64)))
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

    from spyde.qt.shared import create_data
    import hyperspy.api as hs
    sig2 = hs.signals.Signal2D(create_data((64, 64)))
    win.add_signal(sig2)
    qtbot.wait(200)
    other_window = win.plot_subwindows[-1]
    win.mdi_area.setActiveSubWindow(other_window)
    qtbot.wait(100)

    # nav_window belongs to first signal tree — should be dimmed, not hidden
    assert nav_window.isVisible(), "Core window must remain visible (just dimmed)"
    assert abs(nav_window.windowOpacity() - 0.65) < 0.01, (
        f"Expected 65% opacity, got {nav_window.windowOpacity()}"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest spyde/tests/test_line_profile.py::test_preview_window_hidden_when_other_signal_tree_active spyde/tests/test_line_profile.py::test_preview_window_shown_when_owner_signal_tree_active spyde/tests/test_line_profile.py::test_core_windows_background_opacity_when_other_tree_active -v
```

Expected: all FAIL (no visibility changes happen yet).

- [ ] **Step 3: Implement 3-state visibility logic**

Replace the body of `on_subwindow_activated` in `spyde/__main__.py` from line 899. The new implementation adds the visibility update after the existing toolbar show/hide logic:

```python
def on_subwindow_activated(self, window: "PlotWindow") -> None:
    """MDI activation handler: update toolbars, metadata, histogram binding, and colormap selector."""
    print("Subwindow activated:", window)
    if window is None or not isinstance(window, PlotWindow):
        return

    plot = window.current_plot_item
    plot_state = getattr(plot, "plot_state", None)
    if plot is None:
        return

    # hide all toolbar from other plots in the same window except toolbars from
    # the active signal tree
    if window.signal_tree is not None and window.signal_tree.navigator_plot_manager is not None:
        active_plots = [win.current_plot_item for
                        win in window.signal_tree.navigator_plot_manager.all_plot_windows
                        if win.isVisible()]
    else:
        active_plots = [plot]

    for plt in active_plots:
        if getattr(plt, "plot_state", None) is not None:
            plt.plot_state.show_toolbars()
        if hasattr(plt, "show_selector_control_widget"):
            plt.show_selector_control_widget()

    for win in self.plot_subwindows:
        for plt in win.plots:
            if plt in active_plots:
                continue
            else:
                if getattr(plt, "plot_state", None) is not None:
                    plt.plot_state.hide_toolbars()

    # ── 3-state visibility ───────────────────────────────────────────────────
    active_tree = window.signal_tree
    for pw in self.plot_subwindows:
        same_tree = (pw.signal_tree is active_tree)
        is_action_preview = (pw.owner_plot_window is not None)

        if same_tree:
            # Shown: 100% opacity, always visible
            if not pw.isVisible():
                pw.show()
            pw.setWindowOpacity(1.0)
        elif is_action_preview:
            # Hidden: action preview belonging to a different tree
            pw.hide()
        else:
            # Background: core/nav window of an inactive tree
            if not pw.isVisible():
                pw.show()
            pw.setWindowOpacity(0.65)
    # ── end 3-state visibility ───────────────────────────────────────────────

    # Histogram binding: use the image_item on the inner widget / plot
    img_item = plot.image_item
    if (
        self.histogram is not None
        and img_item is not None
        and img_item is not self._histogram_image_item
    ):
        try:
            self.histogram.setImageItem(img_item)
            self._histogram_image_item = img_item
            if plot_state is not None:
                self.histogram.setLevels(plot_state.min_level, plot_state.max_level)
            self.histogram.item.autoHistogramRange()
        except Exception:
            pass

    st = getattr(window, "signal_tree", None)
    if st is not None and st is not self.current_selected_signal_tree:
        self.current_selected_signal_tree = st
        self.update_metadata_widget(plot)

    self.update_axes_widget(plot)

    if plot_state is not None and hasattr(self, "cmap_selector"):
        self.cmap_selector.setCurrentText(plot_state.colormap)
```

- [ ] **Step 4: Run tests**

```
pytest spyde/tests/test_line_profile.py::test_preview_window_hidden_when_other_signal_tree_active spyde/tests/test_line_profile.py::test_preview_window_shown_when_owner_signal_tree_active spyde/tests/test_line_profile.py::test_core_windows_background_opacity_when_other_tree_active -v
```

Expected: all PASS.

- [ ] **Step 5: Run full test suite to check for regressions**

```
pytest spyde/tests/ -v --tb=short 2>&1 | tail -40
```

Expected: no new failures.

- [ ] **Step 6: Commit**

```bash
git add spyde/__main__.py spyde/tests/test_line_profile.py
git commit -m "feat: implement 3-state PlotWindow visibility (shown/background/hidden)"
```

---

## Task 4: Restructure title bar — move status indicator inline, restyle commit button

**Files:**
- Modify: `spyde/qt/subwindow.py:21-115`
- Modify: `spyde/drawing/plots/plot_window.py:108-113`
- Test: `spyde/tests/test_commit_infrastructure.py`

- [ ] **Step 1: Write failing test**

Add to `spyde/tests/test_commit_infrastructure.py`:

```python
def test_commit_button_is_left_of_title(qtbot, window):
    """Commit button must appear before the title label in the title bar layout."""
    pw = window["window"].add_plot_window(is_navigator=False, signal_tree=None)
    layout = pw.title_bar.layout()
    commit_idx = None
    title_idx = None
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item and item.widget():
            w = item.widget()
            if w is pw.title_bar.commit_button:
                commit_idx = i
            elif hasattr(pw, 'title_label') and w is pw.title_label:
                title_idx = i
    assert commit_idx is not None, "Commit button not found in title bar layout"
    assert title_idx is not None, "Title label not found in title bar layout"
    assert commit_idx < title_idx, (
        f"Commit button (idx {commit_idx}) should come before title (idx {title_idx})"
    )
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest spyde/tests/test_commit_infrastructure.py::test_commit_button_is_left_of_title -v
```

Expected: FAIL — commit button is currently inserted at index 1 (after the title label).

- [ ] **Step 3: Restructure title bar layout in `subwindow.py`**

In `spyde/qt/subwindow.py`, replace the title bar construction block (lines ~50–103) with:

```python
self.title_bar_layout = QtWidgets.QHBoxLayout(self.title_bar)
self.title_bar_layout.setContentsMargins(5, 5, 5, 5)
self.title_bar_layout.setSpacing(4)

# Left zone: [status_placeholder] [commit]
self._status_placeholder = QtWidgets.QWidget(self.title_bar)
self._status_placeholder.setFixedSize(24, 24)
self.title_bar_layout.addWidget(self._status_placeholder)

self.title_bar.commit_button = QtWidgets.QPushButton("Commit", self.title_bar)
self.title_bar.commit_button.setFixedHeight(18)
self.title_bar.commit_button.setStyleSheet(
    "QPushButton { color: white; background-color: rgba(80,160,80,180); "
    "border: 1px solid rgba(255,255,255,60); border-radius: 8px; padding: 0 4px; "
    "font-size: 11px; }"
    "QPushButton:disabled { background-color: rgba(80,80,80,120); color: rgba(255,255,255,80); }"
    "QPushButton:hover { background-color: rgba(100,200,100,200); }"
)
self.title_bar.commit_button.hide()
self.title_bar_layout.addWidget(self.title_bar.commit_button)

# Centre: title label (stretches to fill)
self.title_label = QtWidgets.QLabel("", self.title_bar)
self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
self.title_label.setStyleSheet("color: #ffffff;")
self.title_bar_layout.addWidget(self.title_label, stretch=1)

# Right zone: window controls
self.minimize_button = QtWidgets.QPushButton(self.title_bar)
self._icon_minimize = QIcon(resolve_icon_path("qt/assets/icons/minimize.svg"))
self._icon_maximize = QIcon(resolve_icon_path("qt/assets/icons/maximize.svg"))
self._icon_close = QIcon(resolve_icon_path("qt/assets/icons/close.svg"))

self.minimize_button.setFixedSize(20, 20)
self.minimize_button.clicked.connect(self.toggle_minimize)
self.minimize_button.setIcon(self._icon_minimize)
self.minimize_button.setIconSize(QtCore.QSize(12, 12))

self.maximize_button = QtWidgets.QPushButton(self.title_bar)
self.maximize_button.setIcon(self._icon_maximize)
self.maximize_button.setCheckable(True)
self.maximize_button.setChecked(False)
self.maximize_button.setFixedSize(20, 20)
self.maximize_button.clicked.connect(self.toggle_maximize)
self.maximize_button.setIconSize(QtCore.QSize(12, 12))

self.close_button = QtWidgets.QPushButton(self.title_bar)
self.close_button.setIcon(self._icon_close)
self.close_button.setFixedSize(20, 20)
self.close_button.clicked.connect(self.close)
self.close_button.setIconSize(QtCore.QSize(12, 12))

self.title_bar_layout.addWidget(self.minimize_button)
self.title_bar_layout.addWidget(self.maximize_button)
self.title_bar_layout.addWidget(self.close_button)
```

Also remove the old `self.title_bar_layout.insertWidget(1, self.title_bar.commit_button)` line that used to insert the commit button after construction (it no longer exists separately).

- [ ] **Step 4: Update `set_compute_indicator` in `plot_window.py`**

Replace the current `set_compute_indicator` method (lines 108–113):

```python
def set_compute_indicator(self, indicator) -> None:
    """Insert the ComputeStatusIndicator into the title bar left zone."""
    self._compute_indicator = indicator
    # Replace the status placeholder with the real indicator
    layout = self.title_bar_layout
    old = self._status_placeholder
    idx = layout.indexOf(old)
    layout.removeWidget(old)
    old.deleteLater()
    self._status_placeholder = indicator
    indicator.setParent(self.title_bar)
    layout.insertWidget(idx, indicator)
    indicator.show()
```

Also remove the `resizeEvent` lines that repositioned the indicator at `(8, 8)`:

In `resizeEvent` in `plot_window.py`, remove:
```python
if self._compute_indicator is not None:
    self._compute_indicator.move(8, 8)
    self._compute_indicator.raise_()
```

- [ ] **Step 5: Run tests**

```
pytest spyde/tests/test_commit_infrastructure.py -v
```

Expected: all PASS including the new test.

- [ ] **Step 6: Run full suite**

```
pytest spyde/tests/ -v --tb=short 2>&1 | tail -40
```

Expected: no new failures.

- [ ] **Step 7: Commit**

```bash
git add spyde/qt/subwindow.py spyde/drawing/plots/plot_window.py spyde/tests/test_commit_infrastructure.py
git commit -m "feat: restructure title bar layout — status+commit left, pill-style commit button"
```

---

## Task 5: Auto-position preview windows near their owner

**Files:**
- Modify: `spyde/__main__.py:734-783`
- Test: `spyde/tests/test_line_profile.py`

- [ ] **Step 1: Write failing test**

Add to `spyde/tests/test_line_profile.py`:

```python
def test_preview_window_positioned_near_owner(qtbot, stem_4d_dataset):
    """Preview windows should be placed to the right of or below their owner."""
    win = stem_4d_dataset["window"]
    nav_window = stem_4d_dataset["subwindows"][0]
    win.mdi_area.setActiveSubWindow(nav_window)
    qtbot.wait(100)
    plot = nav_window.current_plot_item
    toolbar = plot.plot_state.toolbar_top
    n_before = len(win.plot_subwindows)
    toolbar.add_line_profile_action()
    qtbot.wait(100)
    preview_windows = win.plot_subwindows[n_before:]
    owner = nav_window

    mdi_rect = win.mdi_area.rect()
    for pw in preview_windows:
        # Must be within MDI bounds
        assert pw.x() >= 0, f"Preview x={pw.x()} is out of bounds"
        assert pw.y() >= 0, f"Preview y={pw.y()} is out of bounds"
        assert pw.x() + pw.width() <= mdi_rect.width() + 1, "Preview overflows MDI right"
        assert pw.y() + pw.height() <= mdi_rect.height() + 1, "Preview overflows MDI bottom"
        # Must not overlap owner exactly (i.e. it was repositioned)
        overlap = (
            pw.x() == owner.x() and pw.y() == owner.y()
        )
        assert not overlap, "Preview window was not repositioned from owner position"
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest spyde/tests/test_line_profile.py::test_preview_window_positioned_near_owner -v
```

Expected: FAIL — preview windows default to same or overlapping position as owner.

- [ ] **Step 3: Add `_auto_position_near_owner` to `MainWindow`**

Add this method to `MainWindow` in `spyde/__main__.py` just before `add_plot_window`:

```python
def _auto_position_near_owner(self, pw: "PlotWindow") -> None:
    """Position pw to the right of its owner, or below if no room."""
    owner = pw.owner_plot_window
    if owner is None:
        return
    mdi_rect = self.mdi_area.rect()
    gap = 8
    # Try right of owner
    x = owner.x() + owner.width() + gap
    y = owner.y()
    if x + pw.width() <= mdi_rect.width():
        pw.move(x, y)
        return
    # Try below owner
    x = owner.x()
    y = owner.y() + owner.height() + gap
    if y + pw.height() <= mdi_rect.height():
        pw.move(x, y)
        return
    # Clamp to MDI bounds as fallback
    x = min(x, max(0, mdi_rect.width() - pw.width()))
    y = min(y, max(0, mdi_rect.height() - pw.height()))
    pw.move(x, y)
```

- [ ] **Step 4: Call `_auto_position_near_owner` in `add_plot_window`**

At the end of `add_plot_window` in `spyde/__main__.py`, just before `return pw`:

```python
if pw.owner_plot_window is not None:
    self._auto_position_near_owner(pw)
```

Note: `owner_plot_window` is set by the caller **after** `add_plot_window` returns in Tasks 2. So auto-positioning must be called by the action code instead. Update `line_profile.py` to call `main_window._auto_position_near_owner(preview_window)` after setting `owner_plot_window`:

In `spyde/actions/line_profile.py`, after `preview_window.owner_plot_window = plot.plot_window`:
```python
main_window._auto_position_near_owner(preview_window)
```

Do the same for `profile_window` and `sum_window` in the navigator branch, and for the preview windows in `pyxem.py` and `base.py`.

- [ ] **Step 5: Remove the line from `add_plot_window`**

Since positioning happens in the action code (after `owner_plot_window` is set), remove the early call added in Step 4 from `add_plot_window`.

- [ ] **Step 6: Run tests**

```
pytest spyde/tests/test_line_profile.py::test_preview_window_positioned_near_owner -v
```

Expected: PASS.

- [ ] **Step 7: Run full suite**

```
pytest spyde/tests/ -v --tb=short 2>&1 | tail -40
```

Expected: no new failures.

- [ ] **Step 8: Commit**

```bash
git add spyde/__main__.py spyde/actions/line_profile.py spyde/actions/pyxem.py spyde/actions/base.py spyde/tests/test_line_profile.py
git commit -m "feat: auto-position preview windows to the right of their owner"
```

---

## Task 6: Add tile button to View menu

**Files:**
- Modify: `spyde/__main__.py:422-471` (create_menu), `spyde/__main__.py` (new method)
- Test: `spyde/tests/test_line_profile.py`

- [ ] **Step 1: Write failing test**

Add to `spyde/tests/test_line_profile.py`:

```python
def test_tile_active_windows_fills_mdi(qtbot, stem_4d_dataset):
    """tile_active_windows lays out Shown windows in a grid within MDI bounds."""
    win = stem_4d_dataset["window"]
    subwindows = stem_4d_dataset["subwindows"]
    # ensure first window is active
    win.mdi_area.setActiveSubWindow(subwindows[0])
    qtbot.wait(100)
    active_tree = subwindows[0].signal_tree
    shown = [pw for pw in win.plot_subwindows if pw.signal_tree is active_tree]
    assert len(shown) >= 1

    win.tile_active_windows()
    qtbot.wait(50)

    mdi_rect = win.mdi_area.rect()
    for pw in shown:
        assert pw.x() >= 0
        assert pw.y() >= 0
        assert pw.x() + pw.width() <= mdi_rect.width() + 1
        assert pw.y() + pw.height() <= mdi_rect.height() + 1
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest spyde/tests/test_line_profile.py::test_tile_active_windows_fills_mdi -v
```

Expected: `AttributeError: 'MainWindow' object has no attribute 'tile_active_windows'`

- [ ] **Step 3: Implement `tile_active_windows`**

Add to `MainWindow` in `spyde/__main__.py`:

```python
def tile_active_windows(self) -> None:
    """Tile all Shown PlotWindows (active SignalTree) in an even grid."""
    import math
    active = self.mdi_area.activeSubWindow()
    if not isinstance(active, PlotWindow):
        return
    active_tree = active.signal_tree
    shown = [
        pw for pw in self.plot_subwindows
        if pw.signal_tree is active_tree and pw.isVisible()
    ]
    n = len(shown)
    if n == 0:
        return
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    mdi_rect = self.mdi_area.rect()
    margin = 6
    cell_w = (mdi_rect.width() - margin * (cols + 1)) // cols
    cell_h = (mdi_rect.height() - margin * (rows + 1)) // rows
    for i, pw in enumerate(shown):
        row = i // cols
        col = i % cols
        x = margin + col * (cell_w + margin)
        y = margin + row * (cell_h + margin)
        pw.setGeometry(x, y, cell_w, cell_h)
```

- [ ] **Step 4: Add tile action to View menu in `create_menu`**

In `spyde/__main__.py` inside `create_menu`, after the `view_camera_control_action` block:

```python
tile_action = QAction("Tile Active Windows", self)
tile_action.triggered.connect(self.tile_active_windows)
tile_action.setShortcut("Ctrl+T")
view_menu.addAction(tile_action)
```

- [ ] **Step 5: Run tests**

```
pytest spyde/tests/test_line_profile.py::test_tile_active_windows_fills_mdi -v
```

Expected: PASS.

- [ ] **Step 6: Run full suite**

```
pytest spyde/tests/ -v --tb=short 2>&1 | tail -40
```

Expected: no new failures.

- [ ] **Step 7: Commit**

```bash
git add spyde/__main__.py spyde/tests/test_line_profile.py
git commit -m "feat: add tile_active_windows (Ctrl+T) to View menu"
```

---

## Final Verification

- [ ] Run full test suite one more time:

```
pytest spyde/tests/ -v 2>&1 | tail -50
```

- [ ] Manual smoke check: open a 4D STEM dataset, add a line profile, switch to a second dataset, confirm preview windows disappear; switch back, confirm they reappear; press Ctrl+T, confirm windows tile.
