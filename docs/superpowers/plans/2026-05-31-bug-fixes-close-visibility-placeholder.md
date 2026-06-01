# Bug Fixes: close crash, visibility conflict, white placeholder

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three bugs: `close_plot` NoneType crash, toolbar-toggle/3-state visibility conflict, and white placeholder box in title bar.

**Architecture:** Bug 1 is a one-line guard in `plot.py`. Bug 2 adds `controlling_action` to `PlotWindow`, set in `register_action_plot_window`, and consulted in the 3-state visibility block. Bug 3 is a two-line style fix in `subwindow.py`. All three are independent and committed separately.

**Tech Stack:** PySide6, pyqtgraph, pytest-qt

---

## File Map

| File | Change |
|---|---|
| `spyde/drawing/plots/plot.py` | Guard `close_plot` with `if self.plot_state is not None` |
| `spyde/drawing/plots/plot_window.py` | Add `self.controlling_action = None` to `__init__` |
| `spyde/drawing/toolbars/toolbar.py` | Set `plot_window.controlling_action = act` in `register_action_plot_window` |
| `spyde/__main__.py` | Update 3-state block to respect `controlling_action.isChecked()` |
| `spyde/qt/subwindow.py` | Make `_status_placeholder` transparent |

---

## Task 1: Fix `close_plot` NoneType crash

**Files:**
- Modify: `spyde/drawing/plots/plot.py:735-742`
- Test: `spyde/tests/test_close_windows.py`

### Context

`close_plot` is called when a `PlotWindow` closes. It iterates `self.plot_states` and calls `.close()` on each. After that loop, `self.plot_state` (a property) returns `None` because there are no more active states. The next line accesses `self.plot_state.plot_selectors_children` — crash.

The current code at `spyde/drawing/plots/plot.py:720-742`:
```python
def close_plot(self):
    logger.info("Plot: Closing plot:", self)
    self._update_main_cursor(None, None, None, None, None)
    self._mouse_proxy = None

    # delete all the plot states associated with the plot
    for plot_state in self.plot_states:
        self.plot_states[plot_state].close()

    logger.info("Plot: Removing selector control widgets for this plot")
    # Remove the selectors for this plot
    self.remove_selector_control_widgets()

    logger.info("Deleting current plot selectors and child plots")
    # need to delete the current selectors and child plots
    for child_plot in (
        self.plot_state.plot_selectors_children
        + self.plot_state.signal_tree_selectors_children
    ):
        try:
            child_plot.close()
        except Exception:
            pass
```

- [ ] **Step 1: Write a failing test**

Add to `spyde/tests/test_close_windows.py`:

```python
def test_close_preview_window_no_crash(qtbot, stem_4d_dataset):
    """Closing a line-profile preview window must not raise AttributeError."""
    from spyde.tests.test_line_profile import _add_line_profile_on_signal
    win = stem_4d_dataset["window"]
    n_before = len(win.plot_subwindows)
    _add_line_profile_on_signal(qtbot, win)
    preview_windows = win.plot_subwindows[n_before:]
    assert len(preview_windows) == 1
    preview = preview_windows[0]
    # This must not raise AttributeError: 'NoneType' object has no attribute 'plot_selectors_children'
    try:
        preview.close()
    except AttributeError as e:
        raise AssertionError(f"close() raised AttributeError: {e}") from e
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest spyde/tests/test_close_windows.py::test_close_preview_window_no_crash -v
```

Expected: FAIL with `AssertionError: close() raised AttributeError: 'NoneType' object has no attribute 'plot_selectors_children'`

- [ ] **Step 3: Guard the children block in `close_plot`**

In `spyde/drawing/plots/plot.py`, replace the children cleanup block:

```python
    logger.info("Deleting current plot selectors and child plots")
    # need to delete the current selectors and child plots
    for child_plot in (
        self.plot_state.plot_selectors_children
        + self.plot_state.signal_tree_selectors_children
    ):
        try:
            child_plot.close()
        except Exception:
            pass
```

With:

```python
    logger.info("Deleting current plot selectors and child plots")
    if self.plot_state is not None:
        for child_plot in (
            self.plot_state.plot_selectors_children
            + self.plot_state.signal_tree_selectors_children
        ):
            try:
                child_plot.close()
            except Exception:
                pass
```

- [ ] **Step 4: Run test to verify it passes**

```
uv run pytest spyde/tests/test_close_windows.py::test_close_preview_window_no_crash -v
```

Expected: PASS

- [ ] **Step 5: Run existing close tests to check for regressions**

```
uv run pytest spyde/tests/test_close_windows.py -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add spyde/drawing/plots/plot.py spyde/tests/test_close_windows.py
git commit -m "fix: guard close_plot against None plot_state after all states closed"
```

---

## Task 2: Add `controlling_action` to `PlotWindow`

**Files:**
- Modify: `spyde/drawing/plots/plot_window.py:107`
- Modify: `spyde/drawing/toolbars/toolbar.py:421-423`

### Context

`PlotWindow` needs to know which toolbar action controls its visibility (if any), so the 3-state block can ask "is the user's toggle currently on?" The action is available in `register_action_plot_window` via `_find_action(action_name)`.

- [ ] **Step 1: Add `controlling_action` to `PlotWindow.__init__`**

In `spyde/drawing/plots/plot_window.py`, after `self.owner_plot_window = None` (line 107), add:

```python
self.controlling_action = None  # type: "QtGui.QAction | None"
```

- [ ] **Step 2: Set `controlling_action` in `register_action_plot_window`**

In `spyde/drawing/toolbars/toolbar.py`, replace the `register_action_plot_window` method body:

```python
    def register_action_plot_window(self, action_name: str,
                                    plot_window: QtWidgets.QWidget,
                                    key: Optional[str] = None) -> None:
        """Associate a plot window with an action; auto-hide/show based on toggle state."""
        if action_name not in self.action_widgets:
            self.action_widgets[action_name] = {}
        if "plot_windows" not in self.action_widgets[action_name]:
            self.action_widgets[action_name]["plot_windows"] = {}
        key = key or f"plot_{len(self.action_widgets[action_name]['plot_windows'])}"
        self.action_widgets[action_name]["plot_windows"][key] = plot_window

        act = self._find_action(action_name)
        _set_initial_item_visibility(plot_window, act)
        _bind_action_to_plot_item(act, plot_window)
        if act is not None and hasattr(plot_window, 'controlling_action'):
            plot_window.controlling_action = act
```

- [ ] **Step 3: Verify no test regressions**

```
uv run pytest spyde/tests/test_virtual_image.py spyde/tests/test_fft.py -v --tb=short
```

Expected: all PASS (or same as baseline)

- [ ] **Step 4: Commit**

```bash
git add spyde/drawing/plots/plot_window.py spyde/drawing/toolbars/toolbar.py
git commit -m "feat: add controlling_action to PlotWindow; set from register_action_plot_window"
```

---

## Task 3: Update 3-state visibility to respect `controlling_action`

**Files:**
- Modify: `spyde/__main__.py` (the `# ── 3-state visibility ──` block, around line 998-1016)
- Test: `spyde/tests/test_virtual_image.py`

### Context

The current 3-state block unconditionally shows all same-tree windows. It needs to check `pw.controlling_action.isChecked()` for action-preview windows.

Current block (in `_on_subwindow_activated_impl`):
```python
        # ── 3-state visibility ───────────────────────────────────────────────────
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        active_tree = window.signal_tree
        for pw in self.plot_subwindows:
            same_tree = (pw.signal_tree is active_tree)
            is_action_preview = (pw.owner_plot_window is not None)

            if same_tree:
                if not pw.isVisible():
                    pw.show()
                pw.setGraphicsEffect(None)
            elif is_action_preview:
                pw.hide()
            else:
                if not pw.isVisible():
                    pw.show()
                effect = QGraphicsOpacityEffect(pw)
                effect.setOpacity(0.65)
                pw.setGraphicsEffect(effect)
        # ── end 3-state visibility ───────────────────────────────────────────────
```

- [ ] **Step 1: Write a failing test**

Add to `spyde/tests/test_virtual_image.py`:

```python
def test_fft_window_stays_hidden_after_toggle_off(qtbot, stem_4d_dataset):
    """Toggling the FFT action off then triggering activation must keep FFT window hidden."""
    from PySide6.QtWidgets import QApplication
    win = stem_4d_dataset["window"]
    nav_window = stem_4d_dataset["subwindows"][0]
    win.mdi_area.setActiveSubWindow(nav_window)
    qtbot.wait(100)

    nav, sig = win.plots
    tb = nav.plot_state.toolbar_top
    # Find and trigger the FFT action to open the FFT window
    fft_action = None
    for a in tb.actions():
        if "fft" in a.text().lower() or "FFT" in a.text():
            fft_action = a
            break
    if fft_action is None:
        pytest.skip("No FFT action found on this toolbar")

    fft_action.setChecked(True)
    qtbot.wait(100)
    QApplication.processEvents()

    # Find the FFT plot window
    fft_windows = [pw for pw in win.plot_subwindows if pw.controlling_action is fft_action]
    if not fft_windows:
        pytest.skip("No FFT window registered with controlling_action")
    fft_window = fft_windows[0]
    assert fft_window.isVisible(), "FFT window should be visible when action is checked"

    # Toggle FFT off
    fft_action.setChecked(False)
    qtbot.wait(100)
    QApplication.processEvents()
    assert not fft_window.isVisible(), "FFT window should be hidden after toggle off"

    # Trigger on_subwindow_activated — must NOT re-show the FFT window
    win.on_subwindow_activated(nav_window)
    assert not fft_window.isVisible(), (
        "FFT window must stay hidden after on_subwindow_activated when action is unchecked"
    )
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest spyde/tests/test_virtual_image.py::test_fft_window_stays_hidden_after_toggle_off -v
```

Expected: FAIL — the FFT window reappears after `on_subwindow_activated`.

- [ ] **Step 3: Update the 3-state visibility block**

In `spyde/__main__.py`, replace the 3-state block with:

```python
        # ── 3-state visibility ───────────────────────────────────────────────────
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        active_tree = window.signal_tree
        for pw in self.plot_subwindows:
            same_tree = (pw.signal_tree is active_tree)
            is_action_preview = (pw.owner_plot_window is not None)
            action = getattr(pw, 'controlling_action', None)
            action_wants_visible = (action is None or action.isChecked())

            if same_tree and action_wants_visible:
                if not pw.isVisible():
                    pw.show()
                pw.setGraphicsEffect(None)
            elif same_tree and not action_wants_visible:
                pw.hide()
            elif is_action_preview:
                pw.hide()
            else:
                if not pw.isVisible():
                    pw.show()
                effect = QGraphicsOpacityEffect(pw)
                effect.setOpacity(0.65)
                pw.setGraphicsEffect(effect)
        # ── end 3-state visibility ───────────────────────────────────────────────
```

- [ ] **Step 4: Run test to verify it passes**

```
uv run pytest spyde/tests/test_virtual_image.py::test_fft_window_stays_hidden_after_toggle_off -v
```

Expected: PASS

- [ ] **Step 5: Run broader regression check**

```
uv run pytest spyde/tests/test_virtual_image.py spyde/tests/test_line_profile.py::test_preview_window_hidden_when_other_signal_tree_active spyde/tests/test_line_profile.py::test_preview_window_shown_when_owner_signal_tree_active spyde/tests/test_line_profile.py::test_core_windows_background_opacity_when_other_tree_active -v --tb=short
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add spyde/__main__.py spyde/tests/test_virtual_image.py
git commit -m "fix: 3-state visibility respects controlling_action.isChecked() for same-tree previews"
```

---

## Task 4: Fix white status placeholder

**Files:**
- Modify: `spyde/qt/subwindow.py:54-56`

### Context

`_status_placeholder` is a 24×24 `QWidget` with no background styling. It appears as a white box in the title bar on any `PlotWindow` that never calls `set_compute_indicator`. The fix is two lines of styling.

- [ ] **Step 1: Write a failing test**

Add to `spyde/tests/test_commit_infrastructure.py`:

```python
def test_status_placeholder_is_transparent(qtbot, window):
    """The status placeholder must not have a white/opaque background."""
    pw = window["window"].add_plot_window(is_navigator=False, signal_tree=None)
    placeholder = pw._status_placeholder
    # Stylesheet must contain 'transparent' — opaque white is the bug
    style = placeholder.styleSheet()
    assert "transparent" in style, (
        f"_status_placeholder stylesheet should contain 'transparent', got: {style!r}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest spyde/tests/test_commit_infrastructure.py::test_status_placeholder_is_transparent -v
```

Expected: FAIL — stylesheet is empty.

- [ ] **Step 3: Add transparent styling to `_status_placeholder`**

In `spyde/qt/subwindow.py`, after the line `self._status_placeholder.setFixedSize(24, 24)` (currently line 55), add:

```python
        self._status_placeholder.setStyleSheet("background: transparent;")
        self._status_placeholder.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
```

- [ ] **Step 4: Run test to verify it passes**

```
uv run pytest spyde/tests/test_commit_infrastructure.py::test_status_placeholder_is_transparent -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add spyde/qt/subwindow.py spyde/tests/test_commit_infrastructure.py
git commit -m "fix: make _status_placeholder transparent so it doesn't show as white box"
```

---

## Final Verification

- [ ] Run all affected test files once:

```
uv run pytest spyde/tests/test_close_windows.py spyde/tests/test_virtual_image.py spyde/tests/test_commit_infrastructure.py spyde/tests/test_line_profile.py::test_preview_window_hidden_when_other_signal_tree_active spyde/tests/test_line_profile.py::test_preview_window_shown_when_owner_signal_tree_active -v --tb=short 2>&1 | tail -20
```

Expected: all PASS (or same as pre-existing baseline failures)
