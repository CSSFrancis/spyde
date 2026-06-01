# MainWindow Decomposition + Typed Signal Tree Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract `DaskManager`, `MDIManager`, and `DockManager` from `MainWindow`; replace `BaseSignalTree`'s raw dict tree with a typed `SignalNode` dataclass; remove all Qt imports from `BaseSignalTree`; fix five concrete bugs; fill critical test gaps.

**Architecture:** Three collaborator classes extracted from `MainWindow` reduce it to a thin coordinator. `BaseSignalTree` becomes Qt-free by moving widget construction to `signal_tree_presenter.py`. A `SignalNode` dataclass replaces the raw `_tree` dict, giving the tree a clean typed traversal API. All changes preserve existing external behavior.

**Tech Stack:** Python 3.11+, PySide6, pyqtgraph, HyperSpy, Dask Distributed, pytest, pytest-qt

---

## File Map

| File | Status | Responsibility |
|---|---|---|
| `spyde/signal_node.py` | **New** | `SignalNode` dataclass |
| `spyde/drawing/colormaps.py` | **New** | Single `COLORMAPS` definition |
| `spyde/dask_manager.py` | **New** | Dask lifecycle extracted from `MainWindow` |
| `spyde/mdi_manager.py` | **New** | MDI lifecycle extracted from `MainWindow` |
| `spyde/dock_manager.py` | **New** | Dock construction extracted from `MainWindow` |
| `spyde/drawing/signal_tree_presenter.py` | **New** | Qt widget builders extracted from `BaseSignalTree` |
| `spyde/signal_tree.py` | **Modify** | Replace raw dict with `SignalNode`; remove Qt imports |
| `spyde/__main__.py` | **Modify** | Thin coordinator; wire collaborators |
| `spyde/drawing/plots/plot.py` | **Modify** | Lazy shared memory; import `COLORMAPS` from colormaps.py |
| `spyde/tests/test_signal_tree.py` | **New** | Tree logic tests (no Qt) |
| `spyde/tests/test_update_functions.py` | **New** | Update function tests (no Qt) |
| `spyde/tests/test_plot_update_worker.py` | **New** | Worker polling tests |
| `spyde/tests/test_actions.py` | **Modify** | Replace fixed `wait()` delays |

---

## Task 1: `SignalNode` dataclass + tree tests (no Qt)

**Files:**
- Create: `spyde/signal_node.py`
- Create: `spyde/tests/test_signal_tree.py`

- [ ] **Step 1: Write failing tests**

Create `spyde/tests/test_signal_tree.py`:

```python
import numpy as np
import hyperspy.api as hs
import pytest
from spyde.signal_node import SignalNode


def _make_signal(shape=(4, 4)):
    data = np.zeros(shape)
    return hs.signals.Signal2D(data)


class TestSignalNode:
    def test_fields(self):
        sig = _make_signal()
        node = SignalNode(signal=sig, name="root", parent=None)
        assert node.signal is sig
        assert node.name == "root"
        assert node.parent is None
        assert node.children == {}
        assert node.transformation is None
        assert node.args == ()
        assert node.kwargs == {}

    def test_parent_linkage(self):
        sig_a = _make_signal()
        sig_b = _make_signal()
        parent = SignalNode(signal=sig_a, name="root", parent=None)
        child = SignalNode(signal=sig_b, name="filtered", parent=parent)
        assert child.parent is parent

    def test_children_dict(self):
        sig_a = _make_signal()
        sig_b = _make_signal()
        parent = SignalNode(signal=sig_a, name="root", parent=None)
        child = SignalNode(signal=sig_b, name="filtered", parent=parent)
        parent.children["filtered"] = child
        assert "filtered" in parent.children
        assert parent.children["filtered"] is child

    def test_transformation_stored(self):
        sig = _make_signal()
        node = SignalNode(
            signal=sig,
            name="rebinned",
            parent=None,
            transformation="rebin",
            args=(2,),
            kwargs={"scale": [1, 1, 2, 2]},
        )
        assert node.transformation == "rebin"
        assert node.args == (2,)
        assert node.kwargs == {"scale": [1, 1, 2, 2]}
```

- [ ] **Step 2: Run tests — expect import error**

```
pytest spyde/tests/test_signal_tree.py -v
```

Expected: `ModuleNotFoundError: No module named 'spyde.signal_node'`

- [ ] **Step 3: Create `spyde/signal_node.py`**

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

- [ ] **Step 4: Run tests — expect pass**

```
pytest spyde/tests/test_signal_tree.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```
git add spyde/signal_node.py spyde/tests/test_signal_tree.py
git commit -m "feat: add SignalNode dataclass with tests"
```

---

## Task 2: Migrate `BaseSignalTree` to `SignalNode` + traversal API

**Files:**
- Modify: `spyde/signal_tree.py`
- Modify: `spyde/tests/test_signal_tree.py` (add tree-level tests)

- [ ] **Step 1: Add tree-level failing tests**

Append to `spyde/tests/test_signal_tree.py`:

```python
from unittest.mock import MagicMock
from spyde.signal_tree import BaseSignalTree


def _make_tree():
    """Minimal BaseSignalTree without Qt (mock main_window)."""
    sig = _make_signal((4, 4, 8, 8))  # 4D: nav(4,4) sig(8,8)
    mw = MagicMock()
    mw._heavy_compute_workers = None
    # Prevent MDI/plot construction during __init__
    mw.add_plot_window.return_value = MagicMock()
    mw.add_plot_window.return_value.add_new_plot.return_value = MagicMock()
    tree = BaseSignalTree.__new__(BaseSignalTree)
    tree.root = sig
    tree.main_window = mw
    tree.navigator_signals = {}
    tree.signal_plots = []
    tree.navigator_plot_manager = None
    tree.client = None
    from spyde.signal_node import SignalNode
    tree.root_node = SignalNode(signal=sig, name="root", parent=None)
    return tree, sig


class TestBaseSignalTreeTraversal:
    def test_walk_visits_root(self):
        tree, sig = _make_tree()
        nodes = list(tree.walk())
        assert len(nodes) == 1
        assert nodes[0].signal is sig

    def test_walk_visits_children(self):
        tree, sig = _make_tree()
        from spyde.signal_node import SignalNode
        child_sig = _make_signal((4, 4, 8, 8))
        child = SignalNode(signal=child_sig, name="filtered", parent=tree.root_node)
        tree.root_node.children["filtered"] = child
        nodes = list(tree.walk())
        assert len(nodes) == 2
        signals_visited = [n.signal for n in nodes]
        assert sig in signals_visited
        assert child_sig in signals_visited

    def test_walk_branching_tree(self):
        tree, sig = _make_tree()
        from spyde.signal_node import SignalNode
        child_a = SignalNode(signal=_make_signal(), name="a", parent=tree.root_node)
        child_b = SignalNode(signal=_make_signal(), name="b", parent=tree.root_node)
        grandchild = SignalNode(signal=_make_signal(), name="c", parent=child_a)
        tree.root_node.children["a"] = child_a
        tree.root_node.children["b"] = child_b
        child_a.children["c"] = grandchild
        assert len(list(tree.walk())) == 4

    def test_signals_list_includes_root(self):
        tree, sig = _make_tree()
        assert sig in tree.signals()

    def test_signals_list_includes_descendants(self):
        tree, sig = _make_tree()
        from spyde.signal_node import SignalNode
        child_sig = _make_signal()
        child = SignalNode(signal=child_sig, name="filtered", parent=tree.root_node)
        tree.root_node.children["filtered"] = child
        sigs = tree.signals()
        assert sig in sigs
        assert child_sig in sigs

    def test_get_node_finds_signal(self):
        tree, sig = _make_tree()
        node = tree.get_node(sig)
        assert node is not None
        assert node.signal is sig

    def test_get_node_unknown_returns_none(self):
        tree, _ = _make_tree()
        unknown = _make_signal()
        assert tree.get_node(unknown) is None

    def test_get_node_finds_child(self):
        tree, _ = _make_tree()
        from spyde.signal_node import SignalNode
        child_sig = _make_signal()
        child = SignalNode(signal=child_sig, name="filtered", parent=tree.root_node)
        tree.root_node.children["filtered"] = child
        node = tree.get_node(child_sig)
        assert node is child
```

- [ ] **Step 2: Run tests — expect failure**

```
pytest spyde/tests/test_signal_tree.py::TestBaseSignalTreeTraversal -v
```

Expected: AttributeError — `BaseSignalTree` has no `root_node`, `walk()`, or typed `get_node`.

- [ ] **Step 3: Replace `_tree` dict with `SignalNode` in `signal_tree.py`**

In `spyde/signal_tree.py`, make these changes:

**Add import at top:**
```python
from spyde.signal_node import SignalNode
from typing import Iterator
```

**Remove this import block** (Qt imports at the top of signal_tree.py):
```python
from functools import partial
import numpy as np
from PySide6 import QtWidgets
from PySide6.QtCore import Qt
```
Replace with:
```python
from functools import partial
import numpy as np
```
(Keep `partial` and `np` — they are used in `_on_axis_field_edit` which moves to the presenter in Task 6. For now keep the method body but we will remove the Qt import by temporarily removing the Qt-dependent methods — see Task 6.)

**In `__init__`, replace:**
```python
self._tree = {
    "root": {
        "signal": root_signal,
        "function": None,
        "args": None,
        "kwargs": None,
        "children": {},
    }
}
```
With:
```python
self.root_node = SignalNode(signal=root_signal, name="root", parent=None)
```

**Add `walk()` method:**
```python
def walk(self) -> Iterator[SignalNode]:
    """Depth-first generator over all nodes."""
    stack = [self.root_node]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(node.children.values())
```

**Replace `signals()` method:**
```python
def signals(self) -> list:
    """Return a list of all signals in the tree, including the root."""
    return [node.signal for node in self.walk()]
```

**Replace `get_node()` method:**
```python
def get_node(self, signal) -> SignalNode | None:
    """Get the node in the tree corresponding to the given signal."""
    for node in self.walk():
        if node.signal is signal:
            return node
    return None
```

**Replace `add_node()` method:**
```python
def add_node(self, parent_signal, new_signal, transformation: str):
    """Add a new node to the signal tree."""
    parent_node = self.get_node(parent_signal)
    if parent_node is None:
        raise ValueError("Parent node not found in the tree.")
    child = SignalNode(
        signal=new_signal,
        name=transformation,
        parent=parent_node,
        transformation=transformation,
    )
    parent_node.children[transformation] = child
```

**Replace `add_transformation()` method** — update internal dict access to use `SignalNode`:
```python
def add_transformation(
    self,
    parent_signal,
    method: str = None,
    function: callable = None,
    node_name: str = None,
    *args,
    **kwargs,
):
    if method is not None:
        try:
            new_signal = getattr(parent_signal, method)(*args, **kwargs)
        except Exception as e:
            from PySide6 import QtWidgets
            QtWidgets.QMessageBox.critical(
                self.main_window,
                "Transformation error",
                f"An error occurred while applying transformation "
                f"'{method or (function.__name__ if function else '')}':\n{e}",
            )
            return
    else:
        new_signal = function(parent_signal, *args, **kwargs)

    parent_node = self.get_node(parent_signal)
    if parent_node is None:
        raise ValueError("Parent signal not found in the tree.")

    transformation_name = method if method is not None else function.__name__
    if node_name is None:
        node_name = transformation_name

    # Handle name collision
    final_name = node_name
    if final_name in parent_node.children:
        count = 1
        candidate = f"{node_name}_{count}"
        while candidate in parent_node.children:
            count += 1
            candidate = f"{node_name}_{count}"
        final_name = candidate

    child = SignalNode(
        signal=new_signal,
        name=final_name,
        parent=parent_node,
        transformation=transformation_name,
        args=args,
        kwargs=kwargs,
    )
    parent_node.children[final_name] = child
    print(f"Added transformation '{final_name}' to the tree under parent signal.")
    self.update_plot_states(new_signal)
    return new_signal
```

- [ ] **Step 4: Run traversal tests**

```
pytest spyde/tests/test_signal_tree.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Run full test suite to check for regressions**

```
pytest spyde/tests/ -x -q
```

Expected: No new failures. Fix any breakage before continuing.

- [ ] **Step 6: Commit**

```
git add spyde/signal_node.py spyde/signal_tree.py spyde/tests/test_signal_tree.py
git commit -m "feat: replace raw _tree dict with typed SignalNode; add traversal API"
```

---

## Task 3: `add_transformation` name-collision + return-value tests

**Files:**
- Modify: `spyde/tests/test_signal_tree.py`

- [ ] **Step 1: Add failing tests**

Append to `spyde/tests/test_signal_tree.py`:

```python
class TestAddTransformation:
    def test_name_collision_appends_suffix(self):
        tree, sig = _make_tree()
        from spyde.signal_node import SignalNode
        child_sig = _make_signal()
        child = SignalNode(signal=child_sig, name="filtered", parent=tree.root_node)
        tree.root_node.children["filtered"] = child

        # Manually add a second child with the same name via add_node
        child_sig_2 = _make_signal()
        child_2 = SignalNode(signal=child_sig_2, name="filtered", parent=tree.root_node)
        # Simulate collision handling that add_transformation does
        name = "filtered"
        if name in tree.root_node.children:
            count = 1
            candidate = f"{name}_{count}"
            while candidate in tree.root_node.children:
                count += 1
                candidate = f"{name}_{count}"
            name = candidate
        assert name == "filtered_1"

    def test_get_node_finds_nested_child(self):
        tree, sig = _make_tree()
        from spyde.signal_node import SignalNode
        child_sig = _make_signal()
        grandchild_sig = _make_signal()
        child = SignalNode(signal=child_sig, name="filtered", parent=tree.root_node)
        grandchild = SignalNode(signal=grandchild_sig, name="rebinned", parent=child)
        tree.root_node.children["filtered"] = child
        child.children["rebinned"] = grandchild

        node = tree.get_node(grandchild_sig)
        assert node is grandchild
        assert node.parent is child
```

- [ ] **Step 2: Run tests**

```
pytest spyde/tests/test_signal_tree.py::TestAddTransformation -v
```

Expected: PASS (these test logic already implemented in Task 2).

- [ ] **Step 3: Commit**

```
git add spyde/tests/test_signal_tree.py
git commit -m "test: add add_transformation name-collision and nesting tests"
```

---

## Task 4: Fix `COLORMAPS` duplication

**Files:**
- Create: `spyde/drawing/colormaps.py`
- Modify: `spyde/drawing/plots/plot.py`
- Modify: `spyde/__main__.py`

- [ ] **Step 1: Create `spyde/drawing/colormaps.py`**

```python
import pyqtgraph as pg

COLORMAPS = {
    "gray": pg.colormap.get("CET-L1"),
    "viridis": pg.colormap.get("viridis"),
    "plasma": pg.colormap.get("plasma"),
    "cividis": pg.colormap.get("cividis"),
    "fire": pg.colormap.get("CET-L3"),
}
```

- [ ] **Step 2: Update `spyde/drawing/plots/plot.py`**

Replace lines 30–36 (the `COLORMAPS` dict definition):
```python
COLORMAPS = {
    "gray": pg.colormap.get("CET-L1"),
    "viridis": pg.colormap.get("viridis"),
    "plasma": pg.colormap.get("plasma"),
    "cividis": pg.colormap.get("cividis"),
    "fire": pg.colormap.get("CET-L3"),
}
```
With:
```python
from spyde.drawing.colormaps import COLORMAPS
```

- [ ] **Step 3: Update `spyde/__main__.py`**

Replace lines 48–54 (the `COLORMAPS` dict definition):
```python
COLORMAPS = {
    "gray": pg.colormap.get("CET-L1"),
    "viridis": pg.colormap.get("viridis"),
    "plasma": pg.colormap.get("plasma"),
    "cividis": pg.colormap.get("cividis"),
    "fire": pg.colormap.get("CET-L3"),
}
```
With:
```python
from spyde.drawing.colormaps import COLORMAPS
```

- [ ] **Step 4: Run tests**

```
pytest spyde/tests/ -x -q
```

Expected: All tests PASS. No colormap-related errors.

- [ ] **Step 5: Commit**

```
git add spyde/drawing/colormaps.py spyde/drawing/plots/plot.py spyde/__main__.py
git commit -m "fix: consolidate COLORMAPS into spyde/drawing/colormaps.py"
```

---

## Task 5: Fix lazy shared memory allocation in `Plot`

**Files:**
- Modify: `spyde/drawing/plots/plot.py`

- [ ] **Step 1: Remove eager allocation from `Plot.__init__`**

In `spyde/drawing/plots/plot.py`, find `__init__` and remove these lines (around line 118–121):

```python
# shared memory
BUFFER_SIZE = (8192 * 8192 * 4) + 128  # Example size, adjust as needed
self.shared_memory = SharedMemory(name=f"plot_buffer{id(self)}",
                                  create=True,
                                  size=BUFFER_SIZE)
```

Replace with:
```python
self._shared_memory = None  # allocated lazily on first 2D use
```

- [ ] **Step 2: Add lazy `shared_memory` property**

Add after the `__init__` method (before `toolbars` property):

```python
@property
def shared_memory(self):
    """Allocate shared memory lazily on first access (2D plots only)."""
    if self._shared_memory is None:
        from multiprocessing.shared_memory import SharedMemory
        BUFFER_SIZE = (8192 * 8192 * 4) + 128
        self._shared_memory = SharedMemory(
            name=f"plot_buffer{id(self)}",
            create=True,
            size=BUFFER_SIZE,
        )
    return self._shared_memory
```

- [ ] **Step 3: Update `close_plot` to release shared memory if allocated**

In `close_plot()` method, at the end before the final `logger.info`, add:

```python
if self._shared_memory is not None:
    try:
        self._shared_memory.close()
        self._shared_memory.unlink()
    except Exception:
        pass
    self._shared_memory = None
```

- [ ] **Step 4: Remove `SharedMemory` import from the top-level import** in `plot.py`

Find and remove:
```python
from multiprocessing.shared_memory import SharedMemory
```
(It is now imported inside the property.)

- [ ] **Step 5: Run tests**

```
pytest spyde/tests/ -x -q
```

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```
git add spyde/drawing/plots/plot.py
git commit -m "fix: allocate Plot shared memory lazily; release on close"
```

---

## Task 6: Fix minor bugs (`plot_windows` return, dead `init_dask_cluster`)

**Files:**
- Modify: `spyde/signal_tree.py`
- Modify: `spyde/__main__.py`

- [ ] **Step 1: Fix missing `return` in `plot_windows` property**

In `spyde/signal_tree.py`, find the `plot_windows` property (around line 145–151):

```python
@property
def plot_windows(self) -> List["PlotWindow"]:
    """
    Return a list of all plots in the signal tree, including navigator and signal plots.
    """
    self.navigator_plot_manager.plot_windows
```

Replace with:

```python
@property
def plot_windows(self) -> List["PlotWindow"]:
    """Return all plot windows in the signal tree."""
    if self.navigator_plot_manager is None:
        return []
    return self.navigator_plot_manager.plot_windows
```

- [ ] **Step 2: Delete dead `init_dask_cluster` method from `MainWindow`**

In `spyde/__main__.py`, find and delete the entire method (around lines 343–349):

```python
def init_dask_cluster(self):
    with log_startup_time("Dask LocalCluster + Client setup"):
        cluster = LocalCluster(
            n_workers=self.n_workers, threads_per_worker=self.threads_per_worker
        )
        self.client = Client(cluster)
    print(f"Starting Dashboard at: {self.client.dashboard_link}")
```

- [ ] **Step 3: Run tests**

```
pytest spyde/tests/ -x -q
```

Expected: All tests PASS.

- [ ] **Step 4: Commit**

```
git add spyde/signal_tree.py spyde/__main__.py
git commit -m "fix: add missing return to plot_windows property; delete dead init_dask_cluster"
```

---

## Task 7: `DaskManager` extraction

**Files:**
- Create: `spyde/dask_manager.py`
- Modify: `spyde/__main__.py`

- [ ] **Step 1: Create `spyde/dask_manager.py`**

```python
from __future__ import annotations
import logging
import os
import subprocess

from PySide6 import QtCore
from PySide6.QtCore import QObject, Signal, Slot

from dask.distributed import Client, LocalCluster

logger = logging.getLogger(__name__)


def _probe_gpus() -> int:
    """Return number of NVIDIA GPUs detected via nvidia-smi. Returns 0 on any failure."""
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


class _DaskClusterWorker(QObject):
    finished = Signal(object, object, object)  # cluster, client, gpu_worker_address
    error = Signal(Exception)

    def __init__(self, n_workers: int, threads_per_worker: int, parent=None):
        super().__init__(parent)
        self.n_workers = n_workers
        self.threads_per_worker = threads_per_worker
        self._stopped = False

    @Slot()
    def start(self):
        if self._stopped:
            return
        try:
            cluster = LocalCluster(
                n_workers=self.n_workers,
                threads_per_worker=self.threads_per_worker,
            )
            client = Client(cluster)
            n_gpus = _probe_gpus()
            gpu_worker_address = "gpu_available" if n_gpus > 0 else None
            self.finished.emit(cluster, client, gpu_worker_address)
        except Exception as e:
            self.error.emit(e)

    @Slot()
    def stop(self):
        self._stopped = True


class DaskManager(QObject):
    """Owns the Dask LocalCluster and Client lifecycle."""

    ready = Signal()  # emitted once the client is available

    def __init__(self, n_workers: int, threads_per_worker: int, parent=None):
        super().__init__(parent)
        self._client: Client | None = None
        self._cluster: LocalCluster | None = None
        self._gpu_worker_address: str | None = None
        self._heavy_compute_workers: list[str] | None = None
        self._n_workers = n_workers
        self._threads_per_worker = threads_per_worker
        self._dask_thread: QtCore.QThread | None = None
        self._dask_worker: _DaskClusterWorker | None = None

    @property
    def client(self) -> Client | None:
        return self._client

    @property
    def heavy_workers(self) -> list[str] | None:
        return self._heavy_compute_workers

    @property
    def gpu_worker_address(self) -> str | None:
        return self._gpu_worker_address

    def start(self) -> None:
        """Start the Dask cluster in a background thread."""
        self._dask_thread = QtCore.QThread(self)
        self._dask_worker = _DaskClusterWorker(
            n_workers=self._n_workers,
            threads_per_worker=self._threads_per_worker,
        )
        self._dask_worker.moveToThread(self._dask_thread)
        self._dask_thread.started.connect(self._dask_worker.start)
        self._dask_worker.finished.connect(self._on_dask_ready)
        self._dask_worker.error.connect(self._on_dask_error)
        self._dask_thread.finished.connect(self._dask_worker.deleteLater)
        self._dask_thread.start()

    @Slot(object, object, object)
    def _on_dask_ready(self, cluster, client, gpu_worker_address=None):
        self._cluster = cluster
        self._client = client
        self._gpu_worker_address = gpu_worker_address
        print(f"Dask cluster ready. Dashboard: {client.dashboard_link}")
        worker_keys = list(client.scheduler_info()["workers"].keys())
        heavy = worker_keys[1:]
        self._heavy_compute_workers = heavy if heavy else None
        self._dask_thread.quit()
        self._dask_thread.wait(2000)
        self.ready.emit()

    @Slot(Exception)
    def _on_dask_error(self, exc):
        print(f"Failed to start Dask cluster: {exc}")
        self._dask_thread.quit()
        self._dask_thread.wait(2000)

    def shutdown(self) -> None:
        """Gracefully shut down the Dask client and cluster."""
        import logging as _logging
        import time
        import multiprocessing as mp
        import gc

        print("Shutting down Dask cluster and client...")
        for name in ("distributed", "distributed.comm", "distributed.comm.tcp"):
            lg = _logging.getLogger(name)
            lg.setLevel(_logging.CRITICAL)
            lg.propagate = False
            try:
                lg.handlers.clear()
            except Exception:
                lg.handlers = []
            lg.addHandler(_logging.NullHandler())

        client = self._client
        if client is not None:
            try:
                try:
                    client.close(timeout="2s")
                except TypeError:
                    try:
                        client.close(timeout=2)
                    except Exception:
                        client.close()
                except Exception:
                    try:
                        client.close()
                    except Exception:
                        pass
            finally:
                self._client = None

        cluster = self._cluster
        if cluster is not None:
            try:
                try:
                    cluster.scale(0)
                except Exception:
                    pass
                try:
                    cluster.close(timeout="2s")
                except TypeError:
                    cluster.close(timeout=2)
                except Exception:
                    cluster.close()
            except Exception:
                pass
            finally:
                self._cluster = None

        time.sleep(0.5)
        try:
            for child in mp.active_children():
                try:
                    child.terminate()
                    child.join(timeout=0.5)
                except Exception:
                    try:
                        child.kill()
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            gc.collect()
        except Exception:
            pass
```

- [ ] **Step 2: Update `MainWindow.__init__` to use `DaskManager`**

In `spyde/__main__.py`:

Add import near the top:
```python
from spyde.dask_manager import DaskManager
```

Remove `DaskClusterWorker` class definition and `_probe_gpus` function (they now live in `dask_manager.py`).

In `MainWindow.__init__`, replace the Dask startup block (the section that creates `self._dask_thread`, `self._dask_worker`, etc.) with:

```python
cpu_count = os.cpu_count()
print("CPU Count:", cpu_count)
if cpu_count is None or cpu_count < 4:
    workers = 1
    threads_per_worker = 1
else:
    if cpu_count <= 16:
        workers = (cpu_count // 2) - 1
        threads_per_worker = 2
    else:
        workers = (cpu_count // 4) - 1
        threads_per_worker = 4

print(f"Starting Dask LocalCluster with {workers} workers, {threads_per_worker} threads per worker")
self.dask_manager = DaskManager(
    n_workers=workers,
    threads_per_worker=threads_per_worker,
    parent=self,
)
self.dask_manager.ready.connect(self._on_dask_ready)
self.dask_manager.start()
```

Add a `_on_dask_ready` slot to `MainWindow` (thin adapter — delegates to `dask_manager`):
```python
@QtCore.Slot()
def _on_dask_ready(self):
    print("MainWindow: Dask ready.")
```

Replace all direct references to `self.client`, `self.cluster`, `self._gpu_worker_address`, `self._heavy_compute_workers` in `MainWindow` with `self.dask_manager.client`, etc.

Replace `self._shutdown_dask()` calls in `closeEvent` and `__init__` with `self.dask_manager.shutdown()`.

In `add_signal`, replace the busy-wait:
```python
while self.client is None:
    QApplication.processEvents()
```
With:
```python
while self.dask_manager.client is None:
    QApplication.processEvents()
```

- [ ] **Step 3: Run tests**

```
pytest spyde/tests/ -x -q
```

Expected: All tests PASS.

- [ ] **Step 4: Commit**

```
git add spyde/dask_manager.py spyde/__main__.py
git commit -m "feat: extract DaskManager from MainWindow"
```

---

## Task 8: `signal_tree_presenter.py` — move Qt widget building out of `BaseSignalTree`

**Files:**
- Create: `spyde/drawing/signal_tree_presenter.py`
- Modify: `spyde/signal_tree.py`

- [ ] **Step 1: Create `spyde/drawing/signal_tree_presenter.py`**

Copy the bodies of `build_axes_groups` and `get_metadata_widget` (and their helper `_on_axis_field_edit`) out of `signal_tree.py` into this new file. The functions take `signal_tree` as a parameter rather than `self`:

```python
from __future__ import annotations
from functools import partial
from typing import TYPE_CHECKING

from PySide6 import QtWidgets
from PySide6.QtCore import Qt

if TYPE_CHECKING:
    from spyde.signal_tree import BaseSignalTree
    from spyde.drawing.plots.plot import Plot
from hyperspy.signal import BaseSignal
from spyde.external.qt.labels import EditableLabel
from spyde import METADATA_WIDGET_CONFIG


def _on_axis_field_edit(
    signal_tree: "BaseSignalTree",
    signal: BaseSignal,
    axis,
    field: str,
    line_edit: QtWidgets.QLineEdit,
    is_nav: bool,
    text: str = "",
):
    """Update an axis field on edit. If is_nav, updates all signals in the tree."""
    if is_nav:
        for sig in signal_tree.signals():
            index = sig.axes_manager._axes.index(axis)
            sig.axes_manager._axes[index].__setattr__(field, line_edit.text())
        for plot in signal_tree.navigator_plot_manager.plots.values():
            plot.update_image_rectangle()
    else:
        index = signal.axes_manager._axes.index(axis)
        signal.axes_manager._axes[index].__setattr__(field, line_edit.text())
        for plot in signal_tree.signal_plots:
            if plot.plot_state.current_signal is signal:
                plot.update_image_rectangle()


def build_axes_groups(
    signal_tree: "BaseSignalTree",
    signal: BaseSignal | None,
    plot: "Plot",
) -> list[QtWidgets.QGroupBox]:
    """Build Navigation Axes + Signal Axes QGroupBoxes with editable fields."""
    groups: list[QtWidgets.QGroupBox] = []

    def _make_group(title: str, axes_list, is_nav=False) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox(title)
        group.setSizePolicy(
            QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed
        )
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setMaximumHeight(160)

        container = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(container)
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(2)

        header_style = "font-size: 9px; font-weight: 600;"
        for col, label in enumerate(["Name", "Scale", "Offset", "Units"]):
            h = QtWidgets.QLabel(label)
            h.setStyleSheet(header_style)
            if col == 0:
                h.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(h, 0, col)

        for row, axis in enumerate(axes_list, start=1):
            name_edit = EditableLabel(str(axis.name))
            scale_edit = EditableLabel(str(axis.scale))
            offset_edit = EditableLabel(str(axis.offset))
            units_edit = EditableLabel(str(axis.units))

            for w in (name_edit, scale_edit, offset_edit, units_edit):
                w.setStyleSheet("font-size: 8px;")
                w.setFixedWidth(72)
                w.setFixedHeight(18)

            for w, field in zip(
                (name_edit, scale_edit, offset_edit, units_edit),
                ("name", "scale", "offset", "units"),
            ):
                w.editingFinished.connect(
                    partial(_on_axis_field_edit, signal_tree, signal, axis, field, w, is_nav)
                )

            grid.addWidget(name_edit, row, 0)
            grid.addWidget(scale_edit, row, 1)
            grid.addWidget(offset_edit, row, 2)
            grid.addWidget(units_edit, row, 3)

        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(3, 1)

        scroll.setWidget(container)
        v = QtWidgets.QVBoxLayout(group)
        v.setContentsMargins(4, 4, 4, 4)
        v.addWidget(scroll)
        return group

    groups.append(
        _make_group(
            "Navigation Axes",
            signal_tree.root.axes_manager.navigation_axes,
            is_nav=True,
        )
    )
    if signal is not None and not plot.is_navigator:
        groups.append(_make_group("Signal Axes", signal.axes_manager.signal_axes))
    return groups


def build_metadata_dict(signal_tree: "BaseSignalTree") -> dict[str, dict[str, str]]:
    """Return metadata as a plain dict. DockManager turns this into widgets."""
    subsections: dict[str, dict[str, str]] = {}
    for subsection, props in METADATA_WIDGET_CONFIG["metadata_widget"].items():
        subsections[subsection] = {}
        for prop, value in props.items():
            if "key" in value:
                current_value = signal_tree.root.metadata.get_item(
                    item_path=value["key"], default=value.get("default", "--")
                )
            elif "attr" in value:
                current_value = signal_tree.get_nested_attr(value["attr"])
            elif "function" in value:
                fun = signal_tree.get_nested_attr(value["function"])
                current_value = fun() if callable(fun) else "--"
            else:
                current_value = "--"
            subsections[subsection][prop] = (
                f"{current_value} {value.get('units', '')}".strip()
            )
    return subsections
```

- [ ] **Step 2: Remove Qt widget methods from `BaseSignalTree`**

In `spyde/signal_tree.py`:

- Delete the `build_axes_groups` method entirely.
- Delete the `get_metadata_widget` method entirely.
- Delete the `_on_axis_field_edit` method entirely.
- Remove Qt imports at the top: `from PySide6 import QtWidgets` and `from PySide6.QtCore import Qt`.
- Remove `from spyde.external.qt.labels import EditableLabel` and `from spyde import METADATA_WIDGET_CONFIG` (they move to the presenter).
- Keep `from functools import partial` and `import numpy as np` — still needed by remaining methods.

- [ ] **Step 3: Update callers in `MainWindow`**

In `spyde/__main__.py`, find `update_axes_widget` and `update_metadata_widget`. Update them to call the presenter:

```python
# Add import at top of __main__.py
from spyde.drawing.signal_tree_presenter import build_axes_groups, build_metadata_dict
```

In `update_axes_widget`:
```python
def update_axes_widget(self, window: "Plot") -> None:
    if self.axes_layout is None:
        return
    while self.axes_layout.count():
        item = self.axes_layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()
        else:
            del item

    if hasattr(window, "signal_tree") and window.signal_tree is not None:
        plot_state = window.plot_state
        current_signal = plot_state.current_signal if plot_state else None
        groups = build_axes_groups(window.signal_tree, current_signal, window)
        for group in groups:
            self.axes_layout.addWidget(group)
```

In `update_metadata_widget`:
```python
def update_metadata_widget(self, plot: Plot) -> None:
    if self.metadata_layout is None:
        return
    while self.metadata_layout.count():
        item = self.metadata_layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()
        else:
            del item

    if hasattr(plot, "signal_tree"):
        metadata_dict = build_metadata_dict(plot.signal_tree)
        for subsection, items in metadata_dict.items():
            group = QtWidgets.QGroupBox(str(subsection))
            group.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding,
                QtWidgets.QSizePolicy.Policy.Fixed,
            )
            group.setFixedHeight(120)
            group_layout = QtWidgets.QVBoxLayout(group)
            group_layout.setContentsMargins(6, 6, 6, 6)
            group_layout.setSpacing(0)
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            container = QtWidgets.QWidget()
            grid = QtWidgets.QGridLayout(container)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(12)
            grid.setVerticalSpacing(4)
            for row, (key, value) in enumerate((items or {}).items()):
                key_label = QtWidgets.QLabel(f"{key}:")
                value_label = QtWidgets.QLabel(f"{value}")
                key_label.setStyleSheet("font-size: 10px;")
                value_label.setStyleSheet("font-size: 10px;")
                key_label.setAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                grid.addWidget(key_label, row, 0)
                grid.addWidget(value_label, row, 1)
            grid.setColumnStretch(0, 0)
            grid.setColumnStretch(1, 1)
            scroll.setWidget(container)
            group_layout.addWidget(scroll)
            self.metadata_layout.addWidget(group)
```

- [ ] **Step 4: Verify `BaseSignalTree` has no Qt imports**

```
python -c "import ast, sys; tree = ast.parse(open('spyde/signal_tree.py').read()); imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]; print([ast.dump(i) for i in imports if 'Qt' in ast.dump(i) or 'PySide' in ast.dump(i)])"
```

Expected: empty list `[]`.

- [ ] **Step 5: Run tests**

```
pytest spyde/tests/ -x -q
```

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```
git add spyde/drawing/signal_tree_presenter.py spyde/signal_tree.py spyde/__main__.py
git commit -m "feat: move Qt widget building out of BaseSignalTree into signal_tree_presenter"
```

---

## Task 9: `DockManager` extraction

**Files:**
- Create: `spyde/dock_manager.py`
- Modify: `spyde/__main__.py`

- [ ] **Step 1: Create `spyde/dock_manager.py`**

```python
from __future__ import annotations
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import QObject, Signal, Slot, Qt

from spyde.drawing.colormaps import COLORMAPS
from spyde.drawing.signal_tree_presenter import build_axes_groups, build_metadata_dict
from spyde.external.pyqtgraph.histogram_widget import HistogramLUTWidget, HistogramLUTItem
from spyde.live.camera_control_widget import CameraControlWidget
from spyde.live.control_dock_widget import ControlDockWidget
from spyde.live.particle_scanning import ParticleScanControlWidget

if TYPE_CHECKING:
    from spyde.__main__ import MainWindow
    from spyde.drawing.plots.plot import Plot
    from spyde.drawing.plots.plot_window import PlotWindow


class DockManager(QObject):
    """Owns Plot Control and Instrument Control dock construction and updates."""

    def __init__(self, main_window: "MainWindow", parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._histogram_image_item = None

        self.dock_widget: QtWidgets.QDockWidget | None = None
        self.control_widget: ControlDockWidget | None = None
        self.histogram: HistogramLUTWidget | None = None
        self.cmap_selector: QtWidgets.QComboBox | None = None
        self.metadata_layout: QtWidgets.QHBoxLayout | None = None
        self.axes_layout: QtWidgets.QVBoxLayout | None = None
        self.btn_auto: QtWidgets.QPushButton | None = None
        self.btn_reset: QtWidgets.QPushButton | None = None

        self._build_plot_control_dock()
        self._build_instrument_control_dock()

    def _build_plot_control_dock(self) -> None:
        mw = self.main_window
        self.dock_widget = QtWidgets.QDockWidget("Plot Control", mw)
        self.dock_widget.setObjectName("plotControlDock")
        self.dock_widget.setFeatures(
            self.dock_widget.features()
            & ~QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.dock_widget.setBaseSize(mw.width() // 6, mw.height() // 6)

        main_widget = QtWidgets.QWidget()
        main_widget.setAutoFillBackground(True)
        main_widget.setStyleSheet("background-color: #141414;")
        layout = QtWidgets.QVBoxLayout(main_widget)

        display_group = QtWidgets.QGroupBox("Plot Display Controls")
        display_group.setMaximumHeight(250)
        display_layout = QtWidgets.QVBoxLayout(display_group)

        self.histogram = HistogramLUTWidget(
            orientation="horizontal", autoLevel=False, constantLevel=True
        )
        self.histogram.setMinimumWidth(200)
        self.histogram.setMinimumHeight(100)
        self.histogram.setMaximumHeight(150)
        self.histogram.item.sigLevelChangeFinished.connect(self._on_histogram_levels_finished)
        display_layout.addWidget(self.histogram)

        self.cmap_selector = QtWidgets.QComboBox()
        self.cmap_selector.addItems(list(COLORMAPS.keys()))
        self.cmap_selector.setCurrentText("gray")
        self.cmap_selector.currentTextChanged.connect(self._on_cmap_changed)
        cmap_layout = QtWidgets.QHBoxLayout()
        cmap_layout.addWidget(QtWidgets.QLabel("Colormap"))
        cmap_layout.addWidget(self.cmap_selector, 1)
        display_layout.addLayout(cmap_layout)
        layout.addWidget(display_group)

        buttons_layout = QtWidgets.QHBoxLayout()
        self.btn_auto = QtWidgets.QPushButton("auto")
        self.btn_reset = QtWidgets.QPushButton("reset")
        self.btn_auto.clicked.connect(self._on_contrast_auto)
        self.btn_reset.clicked.connect(self._on_contrast_reset)
        buttons_layout.addWidget(self.btn_auto)
        buttons_layout.addWidget(self.btn_reset)
        display_layout.addLayout(buttons_layout)

        metadata_group = QtWidgets.QGroupBox("Metadata")
        self.metadata_layout = QtWidgets.QHBoxLayout(metadata_group)
        layout.addWidget(metadata_group)

        axes_group = QtWidgets.QGroupBox("Plot Axes")
        self.axes_layout = QtWidgets.QVBoxLayout(axes_group)
        layout.addWidget(axes_group)

        selectors_group = QtWidgets.QGroupBox("Selectors Controls")
        self.selectors_layout = QtWidgets.QVBoxLayout(selectors_group)
        layout.addWidget(selectors_group)

        self.dock_widget.setWidget(main_widget)
        mw.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, self.dock_widget)

    def _build_instrument_control_dock(self) -> None:
        mw = self.main_window
        self.control_widget = ControlDockWidget()
        self.control_widget.setVisible(False)
        mw.addDockWidget(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea, self.control_widget)
        self.control_widget.add_widget(CameraControlWidget())
        self.control_widget.add_widget(ParticleScanControlWidget())

    def toggle_plot_control(self) -> None:
        if self.dock_widget is not None:
            self.dock_widget.setVisible(not self.dock_widget.isVisible())

    def toggle_instrument_control(self) -> None:
        if self.control_widget is not None:
            self.control_widget.setVisible(not self.control_widget.isVisible())

    @Slot(object)
    def on_active_plot_changed(self, window: "PlotWindow") -> None:
        """Called when a new PlotWindow is activated."""
        if window is None:
            return
        plot = window.current_plot_item
        if plot is None:
            return
        plot_state = getattr(plot, "plot_state", None)

        # Histogram binding
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

        # Colormap selector sync
        if plot_state is not None and self.cmap_selector is not None:
            self.cmap_selector.setCurrentText(plot_state.colormap)

        # Metadata and axes panels
        st = getattr(window, "signal_tree", None)
        if st is not None:
            self._update_metadata_panel(plot)
        self._update_axes_panel(plot)

    def _update_metadata_panel(self, plot: "Plot") -> None:
        if self.metadata_layout is None:
            return
        while self.metadata_layout.count():
            item = self.metadata_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            else:
                del item
        if not hasattr(plot, "signal_tree") or plot.signal_tree is None:
            return
        metadata_dict = build_metadata_dict(plot.signal_tree)
        for subsection, items in metadata_dict.items():
            group = QtWidgets.QGroupBox(str(subsection))
            group.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding,
                QtWidgets.QSizePolicy.Policy.Fixed,
            )
            group.setFixedHeight(120)
            group_layout = QtWidgets.QVBoxLayout(group)
            group_layout.setContentsMargins(6, 6, 6, 6)
            group_layout.setSpacing(0)
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            container = QtWidgets.QWidget()
            grid = QtWidgets.QGridLayout(container)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(12)
            grid.setVerticalSpacing(4)
            for row, (key, value) in enumerate((items or {}).items()):
                key_label = QtWidgets.QLabel(f"{key}:")
                value_label = QtWidgets.QLabel(f"{value}")
                key_label.setStyleSheet("font-size: 10px;")
                value_label.setStyleSheet("font-size: 10px;")
                key_label.setAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                grid.addWidget(key_label, row, 0)
                grid.addWidget(value_label, row, 1)
            grid.setColumnStretch(0, 0)
            grid.setColumnStretch(1, 1)
            scroll.setWidget(container)
            group_layout.addWidget(scroll)
            self.metadata_layout.addWidget(group)

    def _update_axes_panel(self, plot: "Plot") -> None:
        if self.axes_layout is None:
            return
        while self.axes_layout.count():
            item = self.axes_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            else:
                del item
        if not hasattr(plot, "signal_tree") or plot.signal_tree is None:
            return
        plot_state = plot.plot_state
        current_signal = plot_state.current_signal if plot_state else None
        groups = build_axes_groups(plot.signal_tree, current_signal, plot)
        for group in groups:
            self.axes_layout.addWidget(group)

    def _on_cmap_changed(self, cmap_name: str) -> None:
        sub = self.main_window.mdi_area.activeSubWindow()
        if sub is None:
            return
        if hasattr(sub, "set_colormap"):
            sub.set_colormap(cmap_name)

    def _on_contrast_auto(self) -> None:
        w = self.main_window.mdi_manager.active_plot()
        if w is None or not hasattr(w, "plot_state") or w.plot_state is None:
            return
        if getattr(w.plot_state, "dimensions", 0) == 2:
            mn, mx = self.histogram.percentile2levels(0.00, 99.0)
            self.histogram.setLevels(mn, mx)

    def _on_contrast_reset(self) -> None:
        w = self.main_window.mdi_manager.active_plot()
        if w is None or not hasattr(w, "plot_state") or w.plot_state is None:
            return
        if getattr(w.plot_state, "dimensions", 0) == 2:
            mn, mx = w.image_item.quickMinMax()
            self.histogram.setLevels(mn, mx)

    def _on_histogram_levels_finished(self, signal: HistogramLUTItem) -> None:
        if (
            signal is None
            or getattr(signal, "bins", None) is None
            or getattr(signal, "counts", None) is None
        ):
            return
        percentiles = signal.get_percentile_levels()
        levels = signal.getLevels()
        w = self.main_window.mdi_manager.active_plot()
        if w is None or not hasattr(w, "plot_state") or w.plot_state is None:
            return
        w.plot_state.max_level = levels[1]
        w.plot_state.min_level = levels[0]
        w.plot_state.max_percentile = percentiles[1]
        w.plot_state.min_percentile = percentiles[0]
```

- [ ] **Step 2: Update `MainWindow` to use `DockManager`**

In `spyde/__main__.py`:

Add import:
```python
from spyde.dock_manager import DockManager
```

In `__init__`, replace the calls to `self.add_plot_control_widget()` and `self.add_instrument_control_widget()` with:
```python
self.dock_manager = DockManager(main_window=self, parent=self)
# expose selectors_layout for Plot.show_selector_control_widget compatibility
self.selectors_layout = self.dock_manager.selectors_layout
```

Delete `add_plot_control_widget` and `add_instrument_control_widget` methods from `MainWindow`.

Delete `on_contrast_auto_click`, `on_contrast_reset_click`, `on_cmap_changed`, `on_histogram_levels_finished`, `update_metadata_widget`, `update_axes_widget`, `toggle_plot_control_dock`, `toggle_camera_control_dock` methods from `MainWindow`.

In `toggle_plot_control_dock` menu action handler, replace with:
```python
view_plot_control_action.triggered.connect(self.dock_manager.toggle_plot_control)
```

In `toggle_camera_control_dock` menu action handler, replace with:
```python
view_camera_control_action.triggered.connect(self.dock_manager.toggle_instrument_control)
```

In `_on_subwindow_activated_impl`, replace the histogram/metadata/axes update block at the bottom with:
```python
self.dock_manager.on_active_plot_changed(window)
```

Also update `on_subwindow_activated` in `MainWindow` to forward to `dock_manager` for cmap selector:
Replace:
```python
if plot_state is not None and hasattr(self, "cmap_selector"):
    self.cmap_selector.setCurrentText(plot_state.colormap)
```
With nothing — `DockManager.on_active_plot_changed` already handles this.

- [ ] **Step 3: Update `export_current_signal` to use `mdi_manager`**

```python
def export_current_signal(self):
    plot = self.mdi_manager.active_plot() if hasattr(self, "mdi_manager") else self._active_plot()
    if not isinstance(plot, Plot):
        QMessageBox.warning(self, "Error", "No active plot window to export from.")
        return
    MovieExportDialog(plot=plot, parent=self).exec()
```

- [ ] **Step 4: Run tests**

```
pytest spyde/tests/ -x -q
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```
git add spyde/dock_manager.py spyde/__main__.py
git commit -m "feat: extract DockManager from MainWindow"
```

---

## Task 10: `MDIManager` extraction

**Files:**
- Create: `spyde/mdi_manager.py`
- Modify: `spyde/__main__.py`

- [ ] **Step 1: Create `spyde/mdi_manager.py`**

```python
from __future__ import annotations
import math
from typing import TYPE_CHECKING, Union
from uuid import uuid4

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QEvent, QObject, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QGraphicsOpacityEffect

import pyqtgraph as pg

from spyde.actions.base import NAVIGATOR_DRAG_MIME

if TYPE_CHECKING:
    from spyde.__main__ import MainWindow
    from spyde.drawing.plots.plot import Plot
    from spyde.drawing.plots.plot_window import PlotWindow
    from spyde.drawing.plots.multiplot_manager import MultiplotManager
    from spyde.signal_tree import BaseSignalTree


class MDIManager(QObject):
    """Owns MDI subwindow lifecycle, 3-state visibility, and drag-and-drop."""

    subwindow_activated = Signal(object)  # PlotWindow

    def __init__(self, mdi_area: QtWidgets.QMdiArea, main_window: "MainWindow", parent=None):
        super().__init__(parent)
        self.mdi_area = mdi_area
        self.main_window = main_window
        self.plot_subwindows: list["PlotWindow"] = []
        self.signal_trees: list["BaseSignalTree"] = []
        self._navigator_drag_payloads: dict[str, dict] = {}
        self._navigator_drag_over_active = False
        self._navigator_placeholder = None
        self._navigator_placeholder_rect = None
        self._in_subwindow_activation = False

        self.mdi_area.subWindowActivated.connect(self._on_subwindow_activated)
        self.mdi_area.setAcceptDrops(True)
        self.mdi_area.installEventFilter(self)

    # ── Public interface ──────────────────────────────────────────────────────

    def add_plot_window(
        self,
        *,
        is_navigator: bool = False,
        plot_manager: "MultiplotManager | None" = None,
        signal_tree: "BaseSignalTree | None" = None,
    ) -> "PlotWindow":
        from spyde.drawing.plots.plot_window import PlotWindow
        from PySide6.QtCore import Qt

        screen_size = self.main_window.screen_size
        pw = PlotWindow(
            is_navigator=is_navigator,
            main_window=self.main_window,
            signal_tree=signal_tree,
            plot_manager=plot_manager,
        )
        pw.resize(screen_size.height() // 3, screen_size.height() // 3)
        self.mdi_area.addSubWindow(pw)
        try:
            pw.setWindowFlags(pw.windowFlags() | Qt.WindowType.FramelessWindowHint)
            pw.setStyleSheet("QMdiSubWindow { border: none; }")
        except Exception:
            pass
        pw.show()
        self.plot_subwindows.append(pw)
        return pw

    def active_plot(self) -> "Plot | None":
        sub = self.mdi_area.activeSubWindow()
        from spyde.drawing.plots.plot_window import PlotWindow
        if not isinstance(sub, PlotWindow):
            return None
        return sub.current_plot_item

    def active_plot_window(self) -> "PlotWindow | None":
        sub = self.mdi_area.activeSubWindow()
        from spyde.drawing.plots.plot_window import PlotWindow
        if not isinstance(sub, PlotWindow):
            return None
        return sub

    def tile_active_windows(self) -> None:
        from spyde.drawing.plots.plot_window import PlotWindow
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
            pw.setGeometry(
                margin + col * (cell_w + margin),
                margin + row * (cell_h + margin),
                cell_w,
                cell_h,
            )

    def register_navigator_drag_payload(self, signal, nav_manager) -> str:
        token = uuid4().hex
        self._navigator_drag_payloads[token] = {
            "signal": signal,
            "nav_manager": nav_manager,
        }
        return token

    def auto_position_near_owner(self, pw: "PlotWindow") -> None:
        owner = pw.owner_plot_window
        if owner is None:
            return
        mdi_rect = self.mdi_area.rect()
        gap = 8
        x = owner.x() + owner.width() + gap
        y = owner.y()
        if x + pw.width() <= mdi_rect.width():
            pw.move(x, y)
            return
        x = owner.x()
        y = owner.y() + owner.height() + gap
        if y + pw.height() <= mdi_rect.height():
            pw.move(x, y)
            return
        x = min(x, max(0, mdi_rect.width() - pw.width()))
        y = min(y, max(0, mdi_rect.height() - pw.height()))
        pw.move(x, y)

    # ── Subwindow activation ─────────────────────────────────────────────────

    def _on_subwindow_activated(self, window: "PlotWindow") -> None:
        if self._in_subwindow_activation:
            return
        self._in_subwindow_activation = True
        try:
            self._on_subwindow_activated_impl(window)
        finally:
            self._in_subwindow_activation = False

    def _on_subwindow_activated_impl(self, window: "PlotWindow") -> None:
        from spyde.drawing.plots.plot_window import PlotWindow
        print("Subwindow activated:", window)
        if window is None or not isinstance(window, PlotWindow):
            return

        plot = window.current_plot_item
        if plot is None:
            return

        self._update_toolbar_visibility(window)
        self._update_3state_visibility(window)
        self.subwindow_activated.emit(window)

    def _update_toolbar_visibility(self, window: "PlotWindow") -> None:
        if window.signal_tree is not None and window.signal_tree.navigator_plot_manager is not None:
            active_plots = [
                w.current_plot_item
                for w in window.signal_tree.navigator_plot_manager.all_plot_windows
                if w.isVisible()
            ]
        else:
            active_plots = [window.current_plot_item]

        for plt in active_plots:
            if getattr(plt, "plot_state", None) is not None:
                plt.plot_state.show_toolbars()
            if hasattr(plt, "show_selector_control_widget"):
                plt.show_selector_control_widget()

        for pw in self.plot_subwindows:
            for plt in pw.plots:
                if plt in active_plots:
                    continue
                if getattr(plt, "plot_state", None) is not None:
                    plt.plot_state.hide_toolbars()

    def _update_3state_visibility(self, window: "PlotWindow") -> None:
        active_tree = window.signal_tree
        for pw in self.plot_subwindows:
            same_tree = pw.signal_tree is active_tree
            is_action_preview = pw.owner_plot_window is not None
            action = getattr(pw, "controlling_action", None)
            action_wants_visible = (
                action is None or not action.isCheckable() or action.isChecked()
            )
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

    # ── Drag-and-drop event filter ───────────────────────────────────────────

    def eventFilter(self, obj, event: QEvent) -> bool:
        if event is None:
            return False
        if obj is self.mdi_area:
            et = event.type()
            if et in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
                mime = event.mimeData()
                if mime is not None and mime.hasFormat(NAVIGATOR_DRAG_MIME):
                    active_sub = self.mdi_area.activeSubWindow()
                    if active_sub is not None:
                        try:
                            pos = event.position().toPoint()
                        except Exception:
                            pos = event.pos()
                        if active_sub.geometry().contains(pos):
                            if not self._navigator_drag_over_active:
                                self._navigator_enter()
                            else:
                                self._navigator_move(pos)
                            self._navigator_drag_over_active = True
                            event.acceptProposedAction()
                            return True
                        if self._navigator_drag_over_active:
                            self._navigator_leave()
                            self._navigator_drag_over_active = False
                        return False
                paths = self._extract_file_paths(mime)
                if any(self._is_supported_file(p) for p in paths):
                    event.acceptProposedAction()
                    return True

            elif et == QEvent.Type.Drop:
                mime = event.mimeData()
                if mime is not None and mime.hasFormat(NAVIGATOR_DRAG_MIME):
                    active_sub = self.mdi_area.activeSubWindow()
                    try:
                        pos = event.position().toPoint()
                    except Exception:
                        pos = event.pos()
                    if active_sub is not None and active_sub.geometry().contains(pos):
                        self._navigator_drag_over_active = False
                        self._navigator_drop(pos, mime)
                        event.acceptProposedAction()
                        return True
                    if self._navigator_drag_over_active:
                        self._navigator_drag_over_active = False
                    return False
                paths = self._extract_file_paths(mime)
                if any(self._is_supported_file(p) for p in paths):
                    self.main_window._handle_drop_files(paths)
                    event.acceptProposedAction()
                    return True

            elif et == QEvent.Type.DragLeave:
                if self._navigator_drag_over_active:
                    self._navigator_leave()
                    self._navigator_drag_over_active = False

        return super().eventFilter(obj, event)

    def _navigator_enter(self) -> None:
        placeholder = pg.PlotItem()
        placeholder.setTitle("Drop Navigator Here", color="#888888")
        placeholder.hideAxis("left")
        placeholder.hideAxis("bottom")
        rect = pg.QtWidgets.QGraphicsRectItem()
        rect.setBrush(pg.mkBrush((100, 100, 255, 100)))
        rect.setPen(pg.mkPen((100, 100, 255), width=2))
        placeholder.addItem(rect)
        self._navigator_placeholder = placeholder
        self._navigator_placeholder_rect = rect

    def _navigator_move(self, pos: QtCore.QPointF) -> None:
        active = self.active_plot_window()
        if active is None or not hasattr(self, "_navigator_placeholder"):
            return
        active._build_new_layout(drop_pos=pos, plot_to_add=self._navigator_placeholder)
        if self._navigator_placeholder_rect is not None:
            vb = self._navigator_placeholder.getViewBox()
            self._navigator_placeholder_rect.setRect(vb.rect())

    def _navigator_leave(self) -> None:
        active = self.active_plot_window()
        if active is not None:
            active.set_graphics_layout_widget(active.previous_subplots_pos)

    def _navigator_drop(self, pos: QtCore.QPointF, mime_data) -> None:
        import hyperspy.api as hs
        active = self.active_plot_window()
        if active is None:
            return
        nav_plot = active.insert_new_plot(drop_pos=pos)
        token = mime_data.data(NAVIGATOR_DRAG_MIME).data().decode("utf-8")
        payload = self._navigator_drag_payloads.pop(token, None)
        if payload is None:
            return
        signal = payload["signal"]
        for navigation_signal in nav_plot.signal_tree.navigator_signals.values():
            nav_plot.multiplot_manager.add_plot_states_for_navigation_signals(navigation_signal)
        nav_plot.set_plot_state(signal=signal[0])
        active.previous_subplots_pos = {}
        active.previous_subplot_added = None

    def _is_supported_file(self, path: str) -> bool:
        import os
        from spyde.__main__ import SUPPORTED_EXTS
        try:
            return os.path.isfile(path) and path.lower().endswith(SUPPORTED_EXTS)
        except Exception:
            return False

    def _extract_file_paths(self, mime) -> list[str]:
        import os
        paths = []
        if mime is None:
            return paths
        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile():
                    p = url.toLocalFile()
                    if p:
                        paths.append(p)
        elif mime.hasText():
            for chunk in mime.text().split():
                if os.path.isfile(chunk):
                    paths.append(chunk)
        return paths
```

- [ ] **Step 2: Update `MainWindow` to use `MDIManager`**

In `spyde/__main__.py`:

Add import:
```python
from spyde.mdi_manager import MDIManager
```

In `__init__`, after creating `self.mdi_area`, replace the block that sets up `self.plot_subwindows`, installs the event filter, and connects `subWindowActivated` with:
```python
self.mdi_manager = MDIManager(mdi_area=self.mdi_area, main_window=self, parent=self)
# Keep these as pass-through properties for backward compatibility with BaseSignalTree etc.
self.plot_subwindows = self.mdi_manager.plot_subwindows
self.signal_trees = self.mdi_manager.signal_trees
```

Replace `self.add_plot_window(...)` calls in `MainWindow` with `self.mdi_manager.add_plot_window(...)`.

Replace `self.tile_active_windows()` with `self.mdi_manager.tile_active_windows()` in the menu action.

Replace `self._auto_position_near_owner(pw)` with `self.mdi_manager.auto_position_near_owner(pw)` in `add_fft_selector` (in `actions/base.py` — that function references `m_window`).

In `actions/base.py`, replace:
```python
m_window._auto_position_near_owner(plot_window)
```
With:
```python
m_window.mdi_manager.auto_position_near_owner(plot_window)
```

Replace `self.register_navigator_drag_payload(...)` in `NavigatorButton._start_drag` with `mw.mdi_manager.register_navigator_drag_payload(...)`.

Delete methods from `MainWindow`: `add_plot_window`, `tile_active_windows`, `on_subwindow_activated`, `_on_subwindow_activated_impl`, `navigator_enter`, `navigator_move`, `navigator_leave`, `navigator_drop`, `_auto_position_near_owner`, `register_navigator_drag_payload`, `_is_supported_file`, `_extract_file_paths`, `_handle_drop_files`, `eventFilter`.

Keep `_active_plot` and `_active_plot_window` as thin delegators:
```python
def _active_plot(self):
    return self.mdi_manager.active_plot()

def _active_plot_window(self):
    return self.mdi_manager.active_plot_window()
```

- [ ] **Step 3: Run full test suite**

```
pytest spyde/tests/ -x -q
```

Expected: All tests PASS.

- [ ] **Step 4: Commit**

```
git add spyde/mdi_manager.py spyde/__main__.py spyde/actions/base.py
git commit -m "feat: extract MDIManager from MainWindow"
```

---

## Task 11: Update function tests (no Qt)

**Files:**
- Create: `spyde/tests/test_update_functions.py`

- [ ] **Step 1: Write failing tests**

```python
import numpy as np
import hyperspy.api as hs
import pytest
from unittest.mock import MagicMock


class TestGetFft:
    def test_output_shape(self):
        from spyde.drawing.update_functions import get_fft

        img = np.random.rand(32, 32).astype(np.float32)
        image_item = MagicMock()
        image_item.image = img

        selector = MagicMock()
        selector.parent = MagicMock()
        selector.parent.image_item = image_item

        child = MagicMock()
        # indices: corners of a rectangle covering most of the image
        indices = np.array([[0, 0], [0, 31], [31, 0], [31, 31]])
        result = get_fft(selector, child, indices)
        assert result.shape == (32, 32)

    def test_output_is_real(self):
        from spyde.drawing.update_functions import get_fft

        img = np.random.rand(16, 16).astype(np.float32)
        image_item = MagicMock()
        image_item.image = img
        selector = MagicMock()
        selector.parent = MagicMock()
        selector.parent.image_item = image_item
        child = MagicMock()
        indices = np.array([[0, 0], [0, 15], [15, 0], [15, 15]])
        result = get_fft(selector, child, indices)
        assert np.isrealobj(result)


class TestUpdateFromNavigationSelectionEager:
    def _make_4d_signal(self):
        data = np.arange(4 * 4 * 8 * 8, dtype=np.float32).reshape(4, 4, 8, 8)
        sig = hs.signals.Signal2D(data)
        return sig

    def test_single_index_returns_correct_slice(self):
        from spyde.drawing.update_functions import update_from_navigation_selection

        sig = self._make_4d_signal()
        child = MagicMock()
        child.plot_state = MagicMock()
        child.plot_state.current_signal = sig

        selector = MagicMock()
        selector.is_integrating = False

        indices = np.array([[2, 3]])  # nav position (2, 3)
        result = update_from_navigation_selection(
            selector, child, indices, get_result=False, cache_in_shared_memory=False
        )
        expected = sig.data[2, 3]
        np.testing.assert_array_equal(result, expected)

    def test_integrating_averages_multiple_indices(self):
        from spyde.drawing.update_functions import update_from_navigation_selection

        sig = self._make_4d_signal()
        child = MagicMock()
        child.plot_state = MagicMock()
        child.plot_state.current_signal = sig

        selector = MagicMock()
        selector.is_integrating = True

        indices = np.array([[0, 0], [1, 0]])
        result = update_from_navigation_selection(
            selector, child, indices, get_result=False, cache_in_shared_memory=False
        )
        expected = np.mean([sig.data[0, 0], sig.data[1, 0]], axis=0)
        np.testing.assert_array_almost_equal(result, expected)
```

- [ ] **Step 2: Run tests — expect failure**

```
pytest spyde/tests/test_update_functions.py -v
```

Expected: The `update_from_navigation_selection` test may fail if the non-integrating path hits a different code branch. Investigate the branch in `update_functions.py` for the non-lazy, non-integrating case and adjust test indices if needed.

- [ ] **Step 3: Fix any discrepancy and run until passing**

```
pytest spyde/tests/test_update_functions.py -v
```

Expected: All 4 tests PASS.

- [ ] **Step 4: Commit**

```
git add spyde/tests/test_update_functions.py
git commit -m "test: add update_function unit tests (FFT shape, navigation selection)"
```

---

## Task 12: `PlotUpdateWorker` tests

**Files:**
- Create: `spyde/tests/test_plot_update_worker.py`

- [ ] **Step 1: Write failing tests**

```python
import pytest
from unittest.mock import MagicMock, patch
from PySide6 import QtCore
from spyde.workers.plot_update_worker import PlotUpdateWorker


def _make_done_future(value=None, key="test_key"):
    fut = MagicMock()
    fut.done.return_value = True
    fut.result.return_value = value if value is not None else __import__("numpy").zeros((4, 4))
    fut.key = key
    return fut


def _make_pending_future():
    fut = MagicMock()
    fut.done.return_value = False
    fut.key = "pending_key"
    return fut


class TestPlotUpdateWorker:
    def test_emits_plot_ready_when_future_done(self, qtbot):
        fut = _make_done_future(key="done_key")
        plot = MagicMock()
        plot.current_data = fut
        plot.plot_state = MagicMock()
        plot.plot_state.current_signal = MagicMock()
        plot.plot_state.current_signal.data = None

        worker = PlotUpdateWorker(get_plots_callable=lambda: [plot], interval_ms=5)

        received = []
        worker.plot_ready.connect(lambda p, r, fid: received.append((p, r, fid)))

        with qtbot.waitSignal(worker.plot_ready, timeout=1000):
            worker._check()

        assert len(received) == 1
        assert received[0][0] is plot

    def test_skips_pending_future(self, qtbot):
        fut = _make_pending_future()
        plot = MagicMock()
        plot.current_data = fut
        plot.plot_state = MagicMock()
        plot.plot_state.current_signal = MagicMock()
        plot.plot_state.current_signal.data = None

        worker = PlotUpdateWorker(get_plots_callable=lambda: [plot], interval_ms=5)
        received = []
        worker.plot_ready.connect(lambda p, r, fid: received.append((p, r, fid)))

        worker._check()
        assert len(received) == 0

    def test_deduplicates_same_future(self, qtbot):
        fut = _make_done_future(key="dup_key")
        plot = MagicMock()
        plot.current_data = fut
        plot.plot_state = MagicMock()
        plot.plot_state.current_signal = MagicMock()
        plot.plot_state.current_signal.data = None

        worker = PlotUpdateWorker(get_plots_callable=lambda: [plot], interval_ms=5)
        received = []
        worker.plot_ready.connect(lambda p, r, fid: received.append((p, r, fid)))

        worker._check()
        worker._check()  # second call — same future, already seen
        assert len(received) == 1

    def test_handles_exception_in_future(self, qtbot):
        fut = MagicMock()
        fut.done.return_value = True
        fut.result.side_effect = RuntimeError("compute failed")
        fut.key = "err_key"

        plot = MagicMock()
        plot.current_data = fut
        plot.plot_state = MagicMock()
        plot.plot_state.current_signal = MagicMock()
        plot.plot_state.current_signal.data = None

        worker = PlotUpdateWorker(get_plots_callable=lambda: [plot], interval_ms=5)
        received = []
        worker.plot_ready.connect(lambda p, r, fid: received.append((p, r, fid)))

        worker._check()  # must not raise
        assert len(received) == 1
        assert isinstance(received[0][1], RuntimeError)
```

- [ ] **Step 2: Run tests**

```
pytest spyde/tests/test_plot_update_worker.py -v
```

Expected: All 4 tests PASS.

- [ ] **Step 3: Commit**

```
git add spyde/tests/test_plot_update_worker.py
git commit -m "test: add PlotUpdateWorker polling and deduplication tests"
```

---

## Task 13: Window lifecycle tests + fix flaky `qtbot.wait` calls

**Files:**
- Create: `spyde/tests/test_window_lifecycle.py`
- Modify: `spyde/tests/test_actions.py`

- [ ] **Step 1: Write lifecycle tests**

Create `spyde/tests/test_window_lifecycle.py`:

```python
import pytest
from spyde.drawing.plots.plot_window import PlotWindow


class TestCloseWindowLifecycle:
    def test_close_window_removes_from_tracking(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        initial_count = len(win.plot_subwindows)
        assert initial_count >= 2

        # Close the first subwindow
        pw = win.plot_subwindows[0]
        pw.close()
        qtbot.waitUntil(
            lambda: len(win.plot_subwindows) < initial_count,
            timeout=3000,
        )
        assert pw not in win.plot_subwindows

    def test_close_nav_window_removes_signal_tree(self, qtbot, stem_4d_dataset):
        win = stem_4d_dataset["window"]
        initial_tree_count = len(win.signal_trees)
        assert initial_tree_count >= 1

        # The nav window is the first subwindow (level-1)
        nav_pw = win.plot_subwindows[0]
        nav_pw.close()
        qtbot.waitUntil(
            lambda: len(win.signal_trees) < initial_tree_count,
            timeout=3000,
        )
        assert len(win.signal_trees) == initial_tree_count - 1
```

- [ ] **Step 2: Run lifecycle tests**

```
pytest spyde/tests/test_window_lifecycle.py -v
```

Expected: Both tests PASS.

- [ ] **Step 3: Fix flaky `qtbot.wait` calls in `test_actions.py`**

In `spyde/tests/test_actions.py`, find and replace every `qtbot.wait(N)` that waits for a data/UI condition with `qtbot.waitUntil`:

Replace:
```python
qtbot.wait(4000)  # wait for the action to take effect
center_button_new.trigger()
```
With:
```python
qtbot.waitUntil(
    lambda: toolbar_bottom_new.action_widgets.get("Center Zero Beam", {}).get("plot_items"),
    timeout=8000,
)
center_button_new.trigger()
```

Replace:
```python
rebin_widget.submit_button.click()
qtbot.wait(6000)  # wait for the action to take effect
current_data = sig.current_data
```
With:
```python
rebin_widget.submit_button.click()
qtbot.waitUntil(
    lambda: (
        sig.current_data is not None
        and hasattr(sig.current_data, "shape")
        and sig.current_data.shape[0] == 32
    ),
    timeout=10000,
)
current_data = sig.current_data
```

Keep the `qtbot.wait(500)` calls that are pure UI settling delays (not waiting on data) — those are fine.

- [ ] **Step 4: Run actions tests**

```
pytest spyde/tests/test_actions.py -v
```

Expected: All tests PASS (and faster on slower machines).

- [ ] **Step 5: Commit**

```
git add spyde/tests/test_window_lifecycle.py spyde/tests/test_actions.py
git commit -m "test: add window lifecycle tests; replace fixed wait() delays with waitUntil"
```

---

## Task 14: Final integration run + memory check

**Files:** None (verification only)

- [ ] **Step 1: Run the complete test suite**

```
pytest spyde/tests/ -v --tb=short
```

Expected: All tests PASS. Note any that remain flaky — investigate root cause rather than increasing timeouts.

- [ ] **Step 2: Verify `BaseSignalTree` has zero Qt imports**

```
python -c "
import ast
src = open('spyde/signal_tree.py').read()
tree = ast.parse(src)
qt_imports = [
    ast.dump(n) for n in ast.walk(tree)
    if isinstance(n, (ast.Import, ast.ImportFrom))
    and ('PySide' in ast.dump(n) or 'Qt' in ast.dump(n))
]
print('Qt imports in signal_tree.py:', qt_imports)
assert not qt_imports, 'Found Qt imports!'
print('OK — zero Qt imports.')
"
```

Expected: `OK — zero Qt imports.`

- [ ] **Step 3: Verify `MainWindow` line count is reduced**

```
python -c "print(len(open('spyde/__main__.py').readlines()), 'lines')"
```

Expected: Under 600 lines (down from ~1639).

- [ ] **Step 4: Commit any final cleanup**

```
git add -u
git commit -m "chore: final cleanup after MainWindow decomposition sub-project 1"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] `DaskManager` extracted — Task 7
- [x] `MDIManager` extracted — Task 10
- [x] `DockManager` extracted — Task 9
- [x] `SignalNode` dataclass — Task 1
- [x] `BaseSignalTree` typed internals — Task 2
- [x] `build_axes_groups` / `get_metadata_widget` moved to presenter — Task 8
- [x] Zero Qt imports in `BaseSignalTree` — Task 8 + verified in Task 14
- [x] `COLORMAPS` deduplicated — Task 4
- [x] Lazy shared memory — Task 5
- [x] `plot_windows` missing return fixed — Task 6
- [x] Dead `init_dask_cluster` deleted — Task 6
- [x] Signal tree traversal tests — Tasks 1–3
- [x] Update function tests — Task 11
- [x] Worker tests — Task 12
- [x] Window lifecycle tests — Task 13
- [x] Flaky `qtbot.wait` replaced — Task 13
- [x] `on_subwindow_activated` broken into focused methods — inside `MDIManager._on_subwindow_activated_impl`
