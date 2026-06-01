# Session-Scoped Test Fixture Design

**Date:** 2026-05-31
**Status:** Approved

## Overview

Every test fixture currently spins up its own `MainWindow` + Dask `LocalCluster` + `Client`. Dask startup takes ~3s per fixture instantiation. With dozens of tests this dominates total run time. The fix: create one `MainWindow` + Dask cluster per test session, and auto-reset the MDI area between tests.

---

## Architecture

### Two-layer fixture design

**Layer 1 — `_session_window` (session-scoped, private)**
- Creates a single `QApplication` (if not already running) and one `MainWindow`
- Waits for the Dask client to be ready
- Lives for the entire pytest session — never closed between tests
- Not used directly by tests

**Layer 2 — `reset_window` (function-scoped, internal helper)**
- Called by every dataset fixture before setup
- Closes all subwindows in `mdi_area.subWindowList()` (triggers `closeEvent` on each)
- Resets `win.plot_subwindows = []` and `win.signal_trees = []`
- Calls `QApplication.processEvents()` to drain the Qt event queue
- Returns the cleaned-up `MainWindow`

**Dataset fixtures** (`stem_4d_dataset`, `tem_2d_dataset`, `insitu_tem_2d_dataset`, `stem_5d_dataset`, `window`)
- Function-scoped (unchanged)
- Call `reset_window` internally to get a clean `MainWindow`
- Call `create_data(win, ...)` and wait for the expected subwindow count
- Return the same `{"window": win, "mdi_area": ..., "subwindows": ..., "signal_trees": ...}` dict
- **Remove** the `finally: _close_window(qtbot, win)` teardown block — session manages lifetime

---

## Reset Procedure

```python
def _reset_window(win):
    """Close all subwindows and clear signal/plot tracking lists."""
    for sw in list(win.mdi_area.subWindowList()):
        sw.close()
    win.plot_subwindows.clear()
    win.signal_trees.clear()
    QApplication.processEvents()
```

This runs synchronously before each dataset fixture sets up its data.

---

## What Changes

| Before | After |
|---|---|
| Each fixture: `win = open_window()` (new MainWindow + Dask) | Each fixture: `win = _reset_window(session_win)` |
| `finally: _close_window(qtbot, win)` in every fixture | No teardown in dataset fixtures |
| Dask starts N times (once per fixture invocation) | Dask starts once per session |
| `open_window()` called per test | `open_window()` called once at session start |

---

## What Stays the Same

- All test signatures: `(qtbot, stem_4d_dataset)` — unchanged
- Return dict shape: `{"window", "mdi_area", "subwindows", "signal_trees"}` — unchanged
- `window` fixture (empty window) — same shape, also resets before yielding
- The `gpu_available` session fixture — untouched

---

## File Affected

- `spyde/conftest.py` — only file changed

---

## Edge Cases

- **`qtbot` still needed**: `qtbot.waitUntil(...)` is still used in dataset fixtures to wait for subwindows to appear after `create_data`. The `qtbot` fixture remains function-scoped.
- **Dask client reuse**: The session window's Dask client is reused across tests. Tests that submit futures will share the same cluster — this is already the case within a single test class today.
- **Signal tree teardown**: `win.signal_trees.clear()` removes references. Signal tree objects may still have Qt widgets in memory until GC; `sw.close()` handles the widget side.
- **Test ordering**: Tests remain independent — each gets a freshly reset window. Order within a module doesn't matter.
