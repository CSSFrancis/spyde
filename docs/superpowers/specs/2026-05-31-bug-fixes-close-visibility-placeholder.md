# Bug Fixes: close crash, visibility conflict, white placeholder

**Date:** 2026-05-31
**Status:** Approved

## Overview

Three bugs introduced or exposed during the PlotWindow focus & organization work:

1. `close_plot` crashes with `AttributeError: 'NoneType' object has no attribute 'plot_selectors_children'`
2. Toggling an FFT window off then triggering `on_subwindow_activated` (e.g. adding a line profile) incorrectly shows the FFT window again
3. Windows without a compute indicator show a white 24×24 box in the title bar left zone

---

## Bug 1 — `close_plot` NoneType crash

**Root cause:** In `spyde/drawing/plots/plot.py:close_plot`, the loop `for plot_state in self.plot_states: close()` closes all plot states. After this loop, `self.plot_state` (the property that returns the current active state) returns `None`. The next block immediately accesses `self.plot_state.plot_selectors_children`, which crashes.

**Fix:** Guard the children-cleanup block with `if self.plot_state is not None:`.

---

## Bug 2 — Toolbar toggle vs 3-state visibility conflict

**Root cause:** `_bind_action_to_plot_item` connects `action.toggled → pw.setVisible(checked)`. The 3-state block in `_on_subwindow_activated_impl` unconditionally calls `pw.show()` for all same-tree windows, overriding the user's toggle.

**Fix:** Add `controlling_action: QAction | None = None` to `PlotWindow`. Set it in `toolbar.register_action_plot_window` when a preview window is registered. The 3-state block uses the action's checked state to decide visibility:

| `same_tree` | `owner_plot_window` | `controlling_action.isChecked()` | Result |
|---|---|---|---|
| True | None | — | Shown (remove opacity effect) |
| True | set | True or None | Shown (remove opacity effect) |
| True | set | False | Hidden |
| False | None | — | Background (65% opacity effect) |
| False | set | — | Hidden |

---

## Bug 3 — White status placeholder

**Root cause:** `_status_placeholder` is a plain `QWidget` with no background styling. It inherits the system default (white/grey) and appears as a white box in the title bar left zone on windows that never receive a compute indicator.

**Fix:** In `FramelessSubWindow.__init__`, add transparent styling to `_status_placeholder`:
```python
self._status_placeholder.setStyleSheet("background: transparent;")
self._status_placeholder.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
```

---

## Files Affected

| File | Change |
|---|---|
| `spyde/drawing/plots/plot.py` | Guard `close_plot` children block with `if self.plot_state is not None` |
| `spyde/drawing/plots/plot_window.py` | Add `self.controlling_action = None` to `__init__` |
| `spyde/drawing/toolbars/toolbar.py` | Set `plot_window.controlling_action = act` in `register_action_plot_window` |
| `spyde/__main__.py` | Update 3-state block to respect `controlling_action.isChecked()` |
| `spyde/qt/subwindow.py` | Add transparent styling to `_status_placeholder` |
