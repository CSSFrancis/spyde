# Sub-project 1: MainWindow Decomposition + Typed Signal Tree

**Date:** 2026-06-01  
**Status:** Approved  
**Stepping stone toward:** Sub-project 2 (Action protocol + ActionRegistry), Sub-project 3 (Reactive signal tree)

---

## Overview

SpyDE's `MainWindow` (~1500 lines) currently owns too many independent concerns: Dask lifecycle, MDI window management, dock construction, drag-and-drop, histogram binding, colormap selection, recent files, and subwindow visibility. `BaseSignalTree` builds Qt widgets directly (`build_axes_groups`, `get_metadata_widget`), coupling signal logic to Qt and making it untestable without a running app. The signal tree's internal `_tree` dict has no typed API, making traversal fragile.

This sub-project extracts three collaborator classes from `MainWindow`, moves Qt construction out of `BaseSignalTree`, introduces a typed `SignalNode` dataclass, bundles five concrete bug fixes, and fills the critical test gaps exposed by those clean seams.

---

## Section 1: MainWindow Decomposition

### Goal

Reduce `MainWindow` to a thin coordinator (~300–400 lines) that wires three focused collaborators together and handles app-level concerns: menu bar, recent files, file open/export, status bar cursor readout, and close event.

### Collaborators

#### `DaskManager` (`spyde/dask_manager.py`)

Owns everything Dask-related. `MainWindow` holds one instance.

**Responsibilities:**
- `DaskClusterWorker` QThread and startup
- `LocalCluster` and `Client` references
- `_gpu_worker_address`, `_heavy_compute_workers`
- `_on_dask_ready`, `_on_dask_error` slots
- `shutdown()` — the full `_shutdown_dask` logic

**Public interface:**
```python
class DaskManager(QObject):
    ready = Signal()           # emitted when client is available

    @property
    def client(self) -> Client | None: ...
    @property
    def heavy_workers(self) -> list[str] | None: ...
    @property
    def gpu_worker_address(self) -> str | None: ...

    def start(self) -> None: ...
    def shutdown(self) -> None: ...
```

`MainWindow` connects `DaskManager.ready` to unblock any pending `add_signal` calls, replacing the current `while self.client is None: processEvents()` busy-wait.

---

#### `MDIManager` (`spyde/mdi_manager.py`)

Owns all MDI subwindow lifecycle and coordination. `MainWindow` holds one instance and installs it as the event filter on `mdi_area`.

**Responsibilities:**
- `plot_subwindows: list[PlotWindow]`
- `signal_trees: list[BaseSignalTree]`
- `add_plot_window(...)` → `PlotWindow`
- `tile_active_windows()`
- `on_subwindow_activated(window)` — broken into focused private methods:
  - `_update_toolbar_visibility(active_plots, all_plots)`
  - `_update_3state_visibility(active_tree, all_windows)`
  - `_update_histogram_binding(plot, plot_state)`
  - `_update_dock_panels(window, plot)`
- Drag-and-drop event filter logic (`navigator_enter`, `navigator_move`, `navigator_leave`, `navigator_drop`)
- `register_navigator_drag_payload`, `_navigator_drag_payloads`
- `_auto_position_near_owner`

**Public interface (subset):**
```python
class MDIManager(QObject):
    subwindow_activated = Signal(object)   # PlotWindow

    def add_plot_window(self, *, is_navigator, plot_manager, signal_tree) -> PlotWindow: ...
    def tile_active_windows(self) -> None: ...
    def active_plot(self) -> Plot | None: ...
    def active_plot_window(self) -> PlotWindow | None: ...
```

`MainWindow` connects `MDIManager.subwindow_activated` to `DockManager.on_active_plot_changed`.

---

#### `DockManager` (`spyde/dock_manager.py`)

Owns all dock widget construction and updates. `MainWindow` holds one instance.

**Responsibilities:**
- Plot Control dock construction (histogram, colormap selector, auto/reset buttons)
- Instrument Control dock construction
- `update_metadata_widget(plot)` — calls `signal_tree_presenter.build_metadata_widget(signal_tree)`
- `update_axes_widget(plot)` — calls `signal_tree_presenter.build_axes_groups(signal_tree, signal, plot)`
- Histogram level change handler
- Colormap change handler
- `on_active_plot_changed(plot)` slot — called whenever the active plot changes

**Public interface (subset):**
```python
class DockManager(QObject):
    @Slot(object)
    def on_active_plot_changed(self, window: PlotWindow) -> None:
        """Receives a PlotWindow; extracts current_plot_item internally."""
        ...
    def toggle_plot_control(self) -> None: ...
    def toggle_instrument_control(self) -> None: ...
```

---

### MainWindow after decomposition

```python
class MainWindow(QMainWindow):
    def __init__(self, app=None):
        self.dask_manager = DaskManager(self)
        self.mdi_manager = MDIManager(mdi_area=self.mdi_area, main_window=self)
        self.dock_manager = DockManager(main_window=self)
        self._wire()

    def _wire(self):
        self.dask_manager.ready.connect(self._on_dask_ready)
        self.mdi_manager.subwindow_activated.connect(
            self.dock_manager.on_active_plot_changed
        )
        self.dask_manager.start()

    # Remaining responsibilities: menu, recent files, file open/export,
    # status bar cursor readout, closeEvent
```

`MainWindow` no longer imports from `spyde.drawing.*` directly for dock construction — that lives in `DockManager`.

---

## Section 2: Typed Signal Tree

### Goal

`BaseSignalTree._tree` replaced by a typed `SignalNode` dataclass. Qt construction removed from `BaseSignalTree`. A standalone presenter module handles widget building.

### `SignalNode` dataclass (`spyde/signal_node.py`)

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from hyperspy.signal import BaseSignal

@dataclass
class SignalNode:
    signal: BaseSignal
    name: str
    parent: Optional["SignalNode"]
    children: dict[str, "SignalNode"] = field(default_factory=dict)
    transformation: Optional[str] = None
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
```

### `BaseSignalTree` API changes

The external behavior of all public methods is preserved. Internal implementation changes:

| Before | After |
|---|---|
| `self._tree = {"root": {"signal": ..., "children": {}}}` | `self.root_node = SignalNode(signal=root_signal, name="root", parent=None)` |
| `self.get_node(signal)` — walks raw dict | `self.get_node(signal)` — walks `SignalNode` tree |
| `self.signals()` — recursive dict traversal | `self.walk()` generator + `self.signals()` list |
| `self.add_node(...)` | `self.add_transformation(...)` — same signature, typed internals |
| `build_axes_groups(...)` — builds Qt widgets | **Removed** — moved to presenter |
| `get_metadata_widget()` — builds Qt widgets | **Removed** — moved to presenter |

New traversal API:
```python
def walk(self) -> Iterator[SignalNode]:
    """Depth-first generator over all nodes."""

def signals(self) -> list[BaseSignal]:
    """All signals in the tree including root."""

def get_node(self, signal: BaseSignal) -> SignalNode | None:
    """Find node by signal identity."""
```

`BaseSignalTree` will have **zero Qt imports** after this change.

### `signal_tree_presenter.py` (`spyde/drawing/signal_tree_presenter.py`)

Standalone module of pure functions. Takes tree/signal data, returns Qt widgets. Called by `DockManager`.

```python
def build_axes_groups(
    signal_tree: BaseSignalTree,
    signal: BaseSignal | None,
    plot: Plot,
) -> list[QGroupBox]:
    """Build Navigation Axes + Signal Axes group boxes."""

def build_metadata_widget(
    signal_tree: BaseSignalTree,
) -> dict[str, dict[str, str]]:
    """Return metadata dict for dock display (no Qt construction here — DockManager builds widgets)."""
```

`_on_axis_field_edit` callback logic stays in the presenter; it only needs `BaseSignalTree` and axis references.

---

## Section 3: Bug Fixes

| Bug | File | Fix |
|---|---|---|
| 256 MB shared memory allocated per `Plot` at construction | `drawing/plots/plot.py:119` | Allocate lazily in a property; skip allocation for 1D plots |
| `COLORMAPS` defined in both `plot.py` and `__main__.py` | Both files | Single definition in `spyde/drawing/colormaps.py`, imported by both |
| `plot_windows` property missing `return` | `signal_tree.py:151` | Add `return self.navigator_plot_manager.plot_windows` |
| `on_subwindow_activated` 70-line monolith | `__main__.py:965` | Broken into 4 private methods during extraction to `MDIManager` |
| `init_dask_cluster` dead method (uses `self.n_workers` which doesn't exist) | `__main__.py:343` | Delete it |

---

## Section 4: Tests to Add

All new tests live in `spyde/tests/`. Signal tree tests require no Qt fixture.

### Signal tree tests (`test_signal_tree.py`)

```
test_signal_node_fields          — SignalNode has correct name, signal, parent, children
test_signal_node_parent_linkage  — child.parent is parent node
test_add_transformation_adds_child       — new node appears in parent.children
test_add_transformation_returns_signal   — returns the new BaseSignal
test_add_transformation_name_collision   — appends _1, _2 on duplicate names
test_get_node_finds_signal               — returns correct SignalNode
test_get_node_unknown_returns_none       — returns None for unknown signal
test_walk_visits_all_nodes               — generator yields root + all descendants
test_walk_branching_tree                 — handles multiple children per node
test_signals_list                        — includes root and all descendants
```

### Update function tests (`test_update_functions.py`)

```
test_get_fft_output_shape        — FFT of (32,32) input returns (32,32)
test_get_fft_real_only           — output is real-valued
test_update_navigation_eager     — non-lazy 4D signal, correct 2D slice returned for given indices
test_update_navigation_integrating — integrating=True averages multiple indices correctly
```

### Worker tests (`test_plot_update_worker.py`)

```
test_worker_emits_plot_ready_when_future_done   — Future.done() → plot_ready emitted
test_worker_skips_pending_future                — Future not done → no emission
test_worker_deduplicates_same_future            — same fid emitted only once
test_worker_handles_exception_in_future         — exception result passed through, no crash
```

### Cleanup / lifecycle tests

```
test_close_window_removes_from_tracking         — close_window() removes PlotWindow from plot_subwindows
test_close_window_cleans_signal_tree            — signal_tree removed from signal_trees on level-1 close
```

### Existing test improvements

- Replace `qtbot.wait(4000)` / `qtbot.wait(6000)` in `test_actions.py` with `qtbot.waitUntil(condition, timeout=8000)`

---

## Section 5: Out of Scope

The following are explicitly deferred to later sub-projects:

- **Action protocol / ActionRegistry** — Sub-project 2
- **Reactive Qt signals on `BaseSignalTree`** — Sub-project 3
- **Changes to `PlotState`, `MultiplotManager`, `PlotWindow`** — untouched
- **Changes to selectors, toolbar layout, pyxem actions** — untouched
- **Live instrument control widgets** — untouched

---

## File Map

| New / Changed File | Change |
|---|---|
| `spyde/dask_manager.py` | New — extracted from `MainWindow` |
| `spyde/mdi_manager.py` | New — extracted from `MainWindow` |
| `spyde/dock_manager.py` | New — extracted from `MainWindow` |
| `spyde/signal_node.py` | New — `SignalNode` dataclass |
| `spyde/drawing/colormaps.py` | New — single `COLORMAPS` definition |
| `spyde/drawing/signal_tree_presenter.py` | New — Qt-free tree → widget functions |
| `spyde/__main__.py` | Reduced to ~300–400 lines |
| `spyde/signal_tree.py` | No Qt imports; typed `SignalNode` internals |
| `spyde/drawing/plots/plot.py` | Lazy shared memory; import from `colormaps.py` |
| `spyde/tests/test_signal_tree.py` | New |
| `spyde/tests/test_update_functions.py` | New |
| `spyde/tests/test_plot_update_worker.py` | New |
| `spyde/tests/test_actions.py` | Replace fixed `wait()` delays |
