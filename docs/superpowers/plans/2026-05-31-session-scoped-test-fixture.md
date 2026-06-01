# Session-Scoped Test Fixture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-test `MainWindow` + Dask cluster creation with a single session-scoped instance, auto-resetting the MDI area between tests to cut overall test run time dramatically.

**Architecture:** A private session-scoped fixture `_session_window` creates one `MainWindow` + Dask cluster for the whole pytest session. A `_reset_window` helper closes all subwindows and clears tracking lists. All dataset fixtures (`stem_4d_dataset`, etc.) call `_reset_window` instead of `open_window()` and drop their `finally` teardown blocks.

**Tech Stack:** pytest, pytest-qt, PySide6, `spyde.qt.shared.open_window`, `spyde.qt.shared.create_data`

---

## File Map

| File | Change |
|---|---|
| `spyde/conftest.py` | Full rewrite — session fixture + reset helper + updated dataset fixtures |

---

## Task 1: Add session-scoped fixture and reset helper

**Files:**
- Modify: `spyde/conftest.py`

- [ ] **Step 1: Write a test that verifies the session window is the same object across two fixture calls**

Add a new file `spyde/tests/test_fixture_session.py`:

```python
"""Verify the session-scoped window is reused across tests."""
import pytest


def test_session_window_identity_a(stem_4d_dataset):
    """Record the MainWindow id from first fixture call."""
    win = stem_4d_dataset["window"]
    # Store on the module for the next test to check
    import spyde.tests.test_fixture_session as _self
    _self._win_id = id(win)


def test_session_window_identity_b(stem_4d_dataset):
    """Verify second fixture call returns the same MainWindow instance."""
    import spyde.tests.test_fixture_session as _self
    win = stem_4d_dataset["window"]
    assert id(win) == _self._win_id, (
        "stem_4d_dataset must return the same MainWindow instance each time"
    )
```

- [ ] **Step 2: Run test to verify it fails (two different windows currently)**

```
uv run pytest spyde/tests/test_fixture_session.py -v
```

Expected: `test_session_window_identity_b` FAIL — `id(win)` differs because each fixture creates a new window.

- [ ] **Step 3: Rewrite `spyde/conftest.py`**

Replace the entire contents of `spyde/conftest.py` with:

```python
from __future__ import annotations

import pytest
from typing import Dict, Union, List, Iterator

from PySide6.QtWidgets import QApplication, QMdiArea

from spyde.qt.shared import open_window as _open_window
from spyde.qt.shared import create_data as _create_data
from spyde.__main__ import MainWindow
from spyde.drawing.plots.plot import Plot
from spyde.signal_tree import BaseSignalTree


# ---------------------------------------------------------------------------
# Session-scoped window: one MainWindow + Dask cluster per test session
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def _session_window():
    """Create a single MainWindow for the entire test session."""
    win = _open_window()
    # Wait for Dask client to be ready (open_window does not block on it)
    from PySide6.QtTest import QTest
    deadline = 30_000  # ms
    elapsed = 0
    while win.client is None and elapsed < deadline:
        QTest.qWait(100)
        elapsed += 100
    assert win.client is not None, "Dask client did not start within 30s"
    yield win
    # Session teardown: close the window once all tests are done
    win.close()


# ---------------------------------------------------------------------------
# Per-test reset: close all subwindows, clear tracking lists
# ---------------------------------------------------------------------------

def _reset_window(win: MainWindow) -> MainWindow:
    """Close all MDI subwindows and clear signal/plot tracking. Returns win."""
    # Close subwindows in reverse order to avoid cascading close errors
    for sw in list(win.mdi_area.subWindowList()):
        try:
            sw.close()
        except Exception:
            pass
    win.plot_subwindows.clear()
    win.signal_trees.clear()
    QApplication.processEvents()
    return win


# ---------------------------------------------------------------------------
# Dataset fixtures — reuse session window, reset before each test
# ---------------------------------------------------------------------------

@pytest.fixture()
def window(qtbot, _session_window) -> Iterator[Dict[str, Union[MainWindow, QMdiArea, List[Plot], List[BaseSignalTree]]]]:
    win = _reset_window(_session_window)
    qtbot.waitUntil(lambda: win.isVisible(), timeout=2000)
    yield {
        "window": win,
        "mdi_area": win.mdi_area,
        "subwindows": win.mdi_area.subWindowList(),
        "signal_trees": getattr(win, "signal_trees", []),
    }


@pytest.fixture()
def tem_2d_dataset(qtbot, _session_window) -> Iterator[Dict[str, Union[MainWindow, QMdiArea, List[Plot], List[BaseSignalTree]]]]:
    win = _reset_window(_session_window)
    _create_data(win, "Image")
    qtbot.waitUntil(lambda: len(win.mdi_area.subWindowList()) == 1, timeout=5000)
    yield {
        "window": win,
        "mdi_area": win.mdi_area,
        "subwindows": win.mdi_area.subWindowList(),
        "signal_trees": getattr(win, "signal_trees", []),
    }


@pytest.fixture()
def insitu_tem_2d_dataset(qtbot, _session_window) -> Iterator[Dict[str, Union[MainWindow, QMdiArea, List[Plot], List[BaseSignalTree]]]]:
    win = _reset_window(_session_window)
    _create_data(win, "Insitu TEM")
    qtbot.waitUntil(lambda: len(win.mdi_area.subWindowList()) == 2, timeout=5000)
    yield {
        "window": win,
        "mdi_area": win.mdi_area,
        "subwindows": win.mdi_area.subWindowList(),
        "signal_trees": getattr(win, "signal_trees", []),
    }


@pytest.fixture()
def stem_4d_dataset(qtbot, _session_window) -> Iterator[Dict[str, Union[MainWindow, QMdiArea, List[Plot], List[BaseSignalTree]]]]:
    win = _reset_window(_session_window)
    _create_data(win, "4D STEM")
    qtbot.waitUntil(lambda: len(win.mdi_area.subWindowList()) == 2, timeout=5000)
    yield {
        "window": win,
        "mdi_area": win.mdi_area,
        "subwindows": win.mdi_area.subWindowList(),
        "signal_trees": getattr(win, "signal_trees", []),
    }


@pytest.fixture()
def stem_5d_dataset(qtbot, _session_window) -> Iterator[Dict[str, Union[MainWindow, QMdiArea, List[Plot], List[BaseSignalTree]]]]:
    win = _reset_window(_session_window)
    _create_data(win, "5D STEM")
    qtbot.waitUntil(lambda: len(win.mdi_area.subWindowList()) == 3, timeout=10000)
    yield {
        "window": win,
        "mdi_area": win.mdi_area,
        "subwindows": win.mdi_area.subWindowList(),
        "signal_trees": getattr(win, "signal_trees", []),
    }


@pytest.fixture(scope="session")
def gpu_available() -> bool:
    """True if nvidia-smi detects at least one GPU."""
    import subprocess
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, timeout=3,
        )
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception:
        return False
```

- [ ] **Step 4: Run the identity tests to verify they pass**

```
uv run pytest spyde/tests/test_fixture_session.py -v
```

Expected: both PASS — same `MainWindow` instance returned each time.

- [ ] **Step 5: Run a broader smoke check**

```
uv run pytest spyde/tests/test_drawing.py spyde/tests/test_close_windows.py spyde/tests/test_navigator.py -v --tb=short
```

Expected: all tests pass (or same as baseline — no new failures).

- [ ] **Step 6: Commit**

```bash
git add spyde/conftest.py spyde/tests/test_fixture_session.py
git commit -m "feat: session-scoped MainWindow fixture — Dask starts once per test session"
```

---

## Task 2: Verify reset isolation between tests

**Files:**
- Modify: `spyde/tests/test_fixture_session.py`

- [ ] **Step 1: Add an isolation test**

Add to `spyde/tests/test_fixture_session.py`:

```python
def test_reset_clears_subwindows_a(tem_2d_dataset):
    """After loading a 2D dataset, there should be exactly 1 subwindow."""
    win = tem_2d_dataset["window"]
    assert len(win.mdi_area.subWindowList()) == 1, (
        f"Expected 1 subwindow after 2D dataset load, got {len(win.mdi_area.subWindowList())}"
    )


def test_reset_clears_subwindows_b(stem_4d_dataset):
    """After switching to 4D STEM dataset, old subwindows must be gone."""
    win = stem_4d_dataset["window"]
    assert len(win.mdi_area.subWindowList()) == 2, (
        f"Expected 2 subwindows after 4D STEM load, got {len(win.mdi_area.subWindowList())}"
    )
    assert len(win.signal_trees) == 1, (
        f"Expected 1 signal tree after reset, got {len(win.signal_trees)}"
    )
```

- [ ] **Step 2: Run isolation tests**

```
uv run pytest spyde/tests/test_fixture_session.py -v
```

Expected: all 4 tests PASS. If `test_reset_clears_subwindows_b` fails with more than 2 subwindows, the reset is not clearing state from `test_reset_clears_subwindows_a`.

- [ ] **Step 3: If reset fails — strengthen the reset**

If step 2 fails, update `_reset_window` in `spyde/conftest.py` to also wait for subwindows to actually close:

```python
def _reset_window(win: MainWindow) -> MainWindow:
    """Close all MDI subwindows and clear signal/plot tracking. Returns win."""
    for sw in list(win.mdi_area.subWindowList()):
        try:
            sw.close()
        except Exception:
            pass
    # Drain Qt events until all subwindows are gone (max 2s)
    from PySide6.QtTest import QTest
    deadline = 2000
    elapsed = 0
    while win.mdi_area.subWindowList() and elapsed < deadline:
        QApplication.processEvents()
        QTest.qWait(50)
        elapsed += 50
    win.plot_subwindows.clear()
    win.signal_trees.clear()
    QApplication.processEvents()
    return win
```

- [ ] **Step 4: Re-run isolation tests**

```
uv run pytest spyde/tests/test_fixture_session.py -v
```

Expected: all 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add spyde/conftest.py spyde/tests/test_fixture_session.py
git commit -m "test: add fixture isolation tests; strengthen reset if needed"
```

---

## Task 3: Run full test suite and verify no regressions

**Files:**
- None (verification only)

- [ ] **Step 1: Run full test suite**

```
uv run pytest spyde/tests/ -q --tb=short 2>&1 | tail -30
```

Note any new failures compared to baseline. Pre-existing failures (e.g. `test_add_plot_state` timing out) are expected.

- [ ] **Step 2: If any test fails due to fixture state leakage, fix the reset**

If a test fails because it sees subwindows/signal_trees from a previous test, the fix is always in `_reset_window` — add more aggressive cleanup. E.g., if `signal_trees` contains stale entries:

```python
# After clearing lists, also close any signal tree plots directly
for st in list(getattr(win, 'signal_trees', [])):
    try:
        st.close()
    except Exception:
        pass
win.signal_trees.clear()
```

- [ ] **Step 3: Commit any fixes**

```bash
git add spyde/conftest.py
git commit -m "fix: improve session window reset to handle residual signal tree state"
```

---

## Final Verification

- [ ] Time a before/after comparison:

```
# Time the targeted tests
uv run pytest spyde/tests/test_navigator.py spyde/tests/test_selectors.py -q 2>&1 | tail -5
```

Expected: total time significantly less than before (Dask starts once instead of once per test class).
