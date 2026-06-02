# Orientation Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 5-step wizard toolbar action to SpyDE that runs template-matching orientation mapping on 4D-STEM datasets using diffsims and pyxem.

**Architecture:** A single `orientation_mapping(toolbar, ...)` closure function in `spyde/actions/pyxem.py`, following the same pattern as `add_virtual_image`. The wizard state is entirely closure-local. Step gating is done by calling `widget.setEnabled(False/True)`. The live refine preview opens a secondary `PlotWindow` and overlays a `ScatterPlotItem` of simulated spots, debounced at 150ms.

**Tech Stack:** PySide6, pyqtgraph, diffsims (`SimulationGenerator`), orix (`get_sample_reduced_fundamental`, `Phase`), pyxem (`get_orientation`, `OrientationMap`), Dask (Step 5 only).

---

## File Map

| File | Action |
|---|---|
| `spyde/actions/pyxem.py` | Add `orientation_mapping()` and helpers |
| `spyde/drawing/toolbars/caret_group.py` | Add `file_drop` parameter type to `CaretParams` |
| `spyde/toolbars.yaml` | Add `Orientation Mapping` toolbar entry |
| `spyde/drawing/toolbars/icons/orientation_mapping.svg` | New icon |
| `spyde/tests/test_orientation_mapping.py` | New test file |

---

## Task 1: Add `file_drop` parameter type to CaretParams

The CIF picker needs a widget that supports both drag-and-drop and a file browser button, accepting multiple files. `CaretParams` does not have this type yet.

**Files:**
- Modify: `spyde/drawing/toolbars/caret_group.py` (around line 349 in the `dtype` branch)
- Test: `spyde/tests/test_orientation_mapping.py`

- [ ] **Step 1: Write failing test**

```python
# spyde/tests/test_orientation_mapping.py
import pytest
from pytestqt.qtbot import QtBot
from spyde.drawing.toolbars.caret_group import CaretParams
from PySide6 import QtWidgets


def test_file_drop_widget_created(qtbot):
    params = {
        "cif_files": {
            "name": "CIF Files",
            "type": "file_drop",
            "extensions": [".cif"],
        }
    }
    widget = CaretParams(parameters=params)
    qtbot.addWidget(widget)
    # The kwargs entry should be a QWidget (the file drop widget)
    assert "cif_files" in widget.kwargs
    drop_widget = widget.kwargs["cif_files"]
    assert hasattr(drop_widget, "get_files")
    assert drop_widget.get_files() == []
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest spyde/tests/test_orientation_mapping.py::test_file_drop_widget_created -v
```
Expected: FAIL — `AttributeError` or `KeyError` since `file_drop` type is not handled.

- [ ] **Step 3: Add `FileDropWidget` class above `CaretGroup` in `caret_group.py`**

Add this class after the imports, before `CaretGroup`:

```python
class FileDropWidget(QtWidgets.QWidget):
    """A widget that accepts drag-and-drop or browse-selected files."""

    filesChanged = QtCore.Signal(list)  # emits list of file paths

    def __init__(self, extensions=None, parent=None):
        super().__init__(parent)
        self._extensions = [e.lower() for e in (extensions or [])]
        self._files = []

        self.setAcceptDrops(True)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        self._label = QtWidgets.QLabel("Drop .cif file(s) here", self)
        self._label.setWordWrap(True)
        self._label.setStyleSheet("color: rgba(255,255,255,150); font-size: 10px;")
        layout.addWidget(self._label)

        self._browse_btn = QtWidgets.QPushButton("Browse...", self)
        self._browse_btn.setStyleSheet(
            "QPushButton { color: white; background-color: rgba(255,255,255,30); "
            "border: 1px solid black; }"
        )
        self._browse_btn.clicked.connect(self._on_browse)
        layout.addWidget(self._browse_btn)

    def get_files(self):
        return list(self._files)

    def _on_browse(self):
        ext_filter = " ".join(f"*{e}" for e in self._extensions) if self._extensions else "*"
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Select CIF file(s)", "", f"CIF files ({ext_filter})"
        )
        if paths:
            self._set_files(paths)

    def _set_files(self, paths):
        self._files = list(paths)
        names = [p.split("/")[-1].split("\\")[-1] for p in paths]
        self._label.setText(", ".join(names))
        self.filesChanged.emit(self._files)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if not self._extensions or any(
                url.toLocalFile().lower().endswith(tuple(self._extensions))
                for url in urls
            ):
                event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if not self._extensions
            or url.toLocalFile().lower().endswith(tuple(self._extensions))
        ]
        if paths:
            self._set_files(paths)
```

- [ ] **Step 4: Add `file_drop` branch to `CaretParams.__init__` in `caret_group.py`**

In the `dtype` if/elif chain (around line 349), add before the `else` clause:

```python
elif dtype == "file_drop":
    extensions = item.get("extensions", [])
    editor = FileDropWidget(extensions=extensions, parent=row_widget)
```

- [ ] **Step 5: Run test to verify it passes**

```
pytest spyde/tests/test_orientation_mapping.py::test_file_drop_widget_created -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add spyde/drawing/toolbars/caret_group.py spyde/tests/test_orientation_mapping.py
git commit -m "feat: add file_drop parameter type to CaretParams"
```

---

## Task 2: Add orientation mapping SVG icon

**Files:**
- Create: `spyde/drawing/toolbars/icons/orientation_mapping.svg`

- [ ] **Step 1: Create the SVG icon**

Create `spyde/drawing/toolbars/icons/orientation_mapping.svg` with this content (a simple compass/crystal icon):

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <polygon points="12,2 22,20 2,20" />
  <line x1="12" y1="2" x2="12" y2="20" />
  <line x1="2" y1="20" x2="22" y2="20" />
  <line x1="7" y1="11" x2="17" y2="11" />
</svg>
```

- [ ] **Step 2: Add toolbar YAML entry**

In `spyde/toolbars.yaml`, after the `Line Profile` entry, add:

```yaml
  Orientation Mapping:
    description: Run template matching orientation mapping on a 4D-STEM dataset.
    icon: drawing/toolbars/icons/orientation_mapping.svg
    function: spyde.actions.pyxem.orientation_mapping
    plot_dim: [2]
    toolbar_side: bottom
    navigation: False
    toggle: True
```

- [ ] **Step 3: Commit**

```bash
git add spyde/drawing/toolbars/icons/orientation_mapping.svg spyde/toolbars.yaml
git commit -m "feat: add orientation mapping icon and toolbar entry"
```

---

## Task 3: Implement Step 1 — Load CIF / Define Crystal

Add the `orientation_mapping` function stub to `spyde/actions/pyxem.py` with Step 1 working: CIF file drop, accelerating voltage input, phase parsing and display, Step 3 unlock.

**Files:**
- Modify: `spyde/actions/pyxem.py` (append after `compute_virtual_image`)
- Modify: `spyde/tests/test_orientation_mapping.py`

- [ ] **Step 1: Write failing test**

Append to `spyde/tests/test_orientation_mapping.py`:

```python
from unittest.mock import MagicMock, patch
import numpy as np


def _make_mock_toolbar():
    """Build a minimal mock toolbar that orientation_mapping expects."""
    toolbar = MagicMock()
    # parent_toolbar.plot chain
    plot = MagicMock()
    signal = MagicMock()
    # signal axes: two signal axes each with scale=0.01, size=128
    ax0 = MagicMock(); ax0.scale = 0.01; ax0.size = 128
    ax1 = MagicMock(); ax1.scale = 0.01; ax1.size = 128
    signal.axes_manager.signal_axes = [ax0, ax1]
    signal.axes_manager.navigation_axes = []
    plot.plot_state.current_signal = signal
    plot.main_window = MagicMock()
    plot.main_window.dask_manager.client = MagicMock()
    plot.main_window.dask_manager.gpu_worker_address = None
    toolbar.parent_toolbar.plot = plot
    toolbar.plot = plot
    toolbar.num_actions.return_value = 0
    toolbar.add_action.return_value = (MagicMock(), MagicMock())
    return toolbar


def test_orientation_mapping_creates_action(qtbot):
    from spyde.actions.pyxem import orientation_mapping
    toolbar = _make_mock_toolbar()
    # Should not raise
    orientation_mapping(toolbar, action_name="Orientation Mapping")
    toolbar.add_action.assert_called_once()
    call_kwargs = toolbar.add_action.call_args
    assert call_kwargs[1]["name"] == "Orientation Mapping" or call_kwargs[0][0] == "Orientation Mapping"
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest spyde/tests/test_orientation_mapping.py::test_orientation_mapping_creates_action -v
```
Expected: FAIL — `ImportError` or `AttributeError` since `orientation_mapping` doesn't exist yet.

- [ ] **Step 3: Add `orientation_mapping` stub to `spyde/actions/pyxem.py`**

Append to the bottom of `spyde/actions/pyxem.py`:

```python
def _compute_reciprocal_radius(signal) -> float:
    """Derive max reciprocal radius from signal axes calibration."""
    sig_axes = signal.axes_manager.signal_axes
    # Use the smaller of the two half-extents so the circle fits within the pattern
    half_extents = [ax.scale * ax.size / 2.0 for ax in sig_axes]
    return min(half_extents)


def orientation_mapping(
    toolbar: RoundedToolBar,
    action_name: str = "Orientation Mapping",
    *args,
    **kwargs,
):
    """5-step wizard for template-matching orientation mapping of 4D-STEM data."""

    plot = toolbar.parent_toolbar.plot
    signal = plot.plot_state.current_signal
    main_window = plot.main_window
    client = main_window.dask_manager.client

    # ── Closure state ──────────────────────────────────────────────────────────
    _phases = []          # list of orix Phase objects (populated in Step 1)
    _sim = [None]         # diffsims Simulation2D (populated in Step 3)
    _gamma = [0.5]        # gamma exponent (updated by Step 4 slider)
    _min_intensity = [0.1]
    _scale = [None]       # Å⁻¹/px; None = use signal calibration
    _max_radius = [_compute_reciprocal_radius(signal)]
    _refit_timer = []     # holds the 150ms debounce QTimer
    _scatter_item = [None]   # pyqtgraph ScatterPlotItem on refine PlotWindow
    _refine_plot_window = [None]

    # ── Step-gating widget handles (populated after add_action) ────────────────
    _step3_widgets = []   # widgets to enable when Step 1 completes
    _step4_widgets = []   # widgets to enable when Step 3 completes
    _step5_widgets = []   # widgets to enable when Step 4 opens

    def _on_cif_loaded(files):
        """Parse CIF files into orix Phase objects and unlock Step 3."""
        from orix.crystal_map import Phase
        _phases.clear()
        for path in files:
            try:
                phase = Phase.from_cif(path)
                _phases.append(phase)
            except Exception as e:
                print(f"Failed to load CIF {path}: {e}")
        if _phases:
            for w in _step3_widgets:
                w.setEnabled(True)

    params = {
        "cif_files": {
            "name": "CIF Files",
            "type": "file_drop",
            "extensions": [".cif"],
        },
        "accelerating_voltage": {
            "name": "Voltage (kV)",
            "type": "float",
            "default": 200.0,
        },
        "_phase_list_label": {
            "name": "Phases",
            "type": "str",
            "default": "(none loaded)",
        },
        "_step2_header": {
            "name": "── Step 2 (optional): Center DP ──",
            "type": "str",
            "default": "",
        },
        "already_centered": {
            "name": "Already Centered",
            "type": "button",
            "label": "✓ Already centered",
            "callback": lambda: None,
        },
        "_step3_header": {
            "name": "── Step 3: Generate Library ──",
            "type": "str",
            "default": "",
        },
        "resolution": {
            "name": "Angle Density (°)",
            "type": "float",
            "default": 1.0,
        },
        "minimum_intensity": {
            "name": "Min Intensity",
            "type": "float",
            "default": 0.05,
        },
        "generate_library_row": {
            "name": "",
            "type": "button_row",
            "buttons": [
                {"key": "generate_btn", "label": "Generate Library",
                 "callback": lambda: _on_generate_clicked()},
            ],
        },
        "_step4_header": {
            "name": "── Step 4: Refine Parameters ──",
            "type": "str",
            "default": "",
        },
        "open_refine_row": {
            "name": "",
            "type": "button_row",
            "buttons": [
                {"key": "open_refine_btn", "label": "Open Refine Preview",
                 "callback": lambda: _on_open_refine_clicked()},
            ],
        },
        "_step5_header": {
            "name": "── Step 5: Run Fit ──",
            "type": "str",
            "default": "",
        },
        "run_fit_row": {
            "name": "",
            "type": "button_row",
            "buttons": [
                {"key": "run_fit_btn", "label": "Run Fit",
                 "callback": lambda: _on_run_fit_clicked()},
            ],
        },
    }

    action, params_caret_box = toolbar.add_action(
        name=action_name,
        icon_path=resolve_icon_path("drawing/toolbars/icons/orientation_mapping.svg"),
        function=lambda *a, **kw: None,
        toggle=True,
        parameters=params,
    )

    # Collect step-gated widgets
    for key in ["resolution", "minimum_intensity", "generate_btn"]:
        w = params_caret_box.get_parameter_widget(key)
        if w is not None:
            w.setEnabled(False)
            _step3_widgets.append(w)

    for key in ["open_refine_btn"]:
        w = params_caret_box.get_parameter_widget(key)
        if w is not None:
            w.setEnabled(False)
            _step4_widgets.append(w)

    for key in ["run_fit_btn"]:
        w = params_caret_box.get_parameter_widget(key)
        if w is not None:
            w.setEnabled(False)
            _step5_widgets.append(w)

    # Wire CIF drop widget
    cif_widget = params_caret_box.get_parameter_widget("cif_files")
    if cif_widget is not None and hasattr(cif_widget, "filesChanged"):
        cif_widget.filesChanged.connect(_on_cif_loaded)

    # Placeholder callbacks — implemented in later tasks
    def _on_generate_clicked():
        pass

    def _on_open_refine_clicked():
        pass

    def _on_run_fit_clicked():
        pass
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest spyde/tests/test_orientation_mapping.py::test_orientation_mapping_creates_action -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add spyde/actions/pyxem.py spyde/tests/test_orientation_mapping.py
git commit -m "feat: add orientation_mapping stub with Step 1 CIF loading"
```

---

## Task 4: Implement Step 3 — Generate Library

Fill in `_on_generate_clicked` inside the `orientation_mapping` closure.

**Files:**
- Modify: `spyde/actions/pyxem.py`
- Modify: `spyde/tests/test_orientation_mapping.py`

- [ ] **Step 1: Write failing test**

Append to `spyde/tests/test_orientation_mapping.py`:

```python
def test_generate_library(qtbot):
    """_generate_library_from_phases returns a Simulation2D given valid phases."""
    from spyde.actions.pyxem import _generate_library_from_phases
    from unittest.mock import patch, MagicMock

    mock_sim = MagicMock()
    mock_generator_cls = MagicMock()
    mock_generator_cls.return_value.calculate_diffraction2d.return_value = mock_sim

    mock_rotations = MagicMock()
    mock_phase = MagicMock()
    mock_phase.point_group = MagicMock()

    with patch("spyde.actions.pyxem.SimulationGenerator", mock_generator_cls), \
         patch("spyde.actions.pyxem.get_sample_reduced_fundamental",
               return_value=mock_rotations):
        result = _generate_library_from_phases(
            phases=[mock_phase],
            accelerating_voltage=200.0,
            resolution=1.0,
            minimum_intensity=0.05,
            reciprocal_radius=0.64,
        )

    assert result is mock_sim
    mock_generator_cls.assert_called_once_with(200.0, minimum_intensity=0.05)
    mock_generator_cls.return_value.calculate_diffraction2d.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest spyde/tests/test_orientation_mapping.py::test_generate_library -v
```
Expected: FAIL — `ImportError` since `_generate_library_from_phases` doesn't exist.

- [ ] **Step 3: Add `_generate_library_from_phases` to `spyde/actions/pyxem.py`**

Add these imports near the top of `pyxem.py` (after existing imports):

```python
from diffsims.generators.simulation_generator import SimulationGenerator
from orix.sampling import get_sample_reduced_fundamental
```

Add the helper function before `orientation_mapping`:

```python
def _generate_library_from_phases(phases, accelerating_voltage, resolution,
                                   minimum_intensity, reciprocal_radius):
    """Generate a diffsims Simulation2D library from a list of orix Phase objects."""
    generator = SimulationGenerator(
        accelerating_voltage, minimum_intensity=minimum_intensity
    )
    rotations = [
        get_sample_reduced_fundamental(
            resolution=resolution, point_group=phase.point_group
        )
        for phase in phases
    ]
    sim = generator.calculate_diffraction2d(
        phases if len(phases) > 1 else phases[0],
        rotation=rotations if len(rotations) > 1 else rotations[0],
        max_excitation_error=0.1,
        reciprocal_radius=reciprocal_radius,
        with_direct_beam=False,
    )
    return sim
```

- [ ] **Step 4: Wire `_on_generate_clicked` inside `orientation_mapping`**

Replace the placeholder `_on_generate_clicked` function in the `orientation_mapping` closure:

```python
def _on_generate_clicked():
    voltage = float(params_caret_box.get_parameter_widget("accelerating_voltage").text() or 200.0)
    resolution = float(params_caret_box.get_parameter_widget("resolution").text() or 1.0)
    min_intensity = float(params_caret_box.get_parameter_widget("minimum_intensity").text() or 0.05)
    reciprocal_radius = _compute_reciprocal_radius(signal)
    try:
        _sim[0] = _generate_library_from_phases(
            phases=_phases,
            accelerating_voltage=voltage,
            resolution=resolution,
            minimum_intensity=min_intensity,
            reciprocal_radius=reciprocal_radius,
        )
        for w in _step4_widgets:
            w.setEnabled(True)
    except Exception as e:
        print(f"Library generation failed: {e}")
```

- [ ] **Step 5: Run test to verify it passes**

```
pytest spyde/tests/test_orientation_mapping.py::test_generate_library -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add spyde/actions/pyxem.py spyde/tests/test_orientation_mapping.py
git commit -m "feat: implement Step 3 library generation"
```

---

## Task 5: Implement Step 4 — Refine Parameters (preview window + overlay)

Fill in `_on_open_refine_clicked` and the live refit loop.

**Files:**
- Modify: `spyde/actions/pyxem.py`
- Modify: `spyde/tests/test_orientation_mapping.py`

- [ ] **Step 1: Write failing test**

Append to `spyde/tests/test_orientation_mapping.py`:

```python
def test_filter_sim_by_radius():
    """Spots beyond max_radius are excluded from the filtered simulation."""
    from spyde.actions.pyxem import _filter_sim_by_radius
    import numpy as np

    # Build a mock simulation with spot coords at various radii
    mock_sim = MagicMock()
    # Coords: (kx, ky) pairs — only first two within radius 0.5
    coords = np.array([[0.1, 0.2], [0.3, 0.3], [0.6, 0.0], [0.0, 0.8]])
    intensities = np.array([1.0, 0.8, 0.5, 0.3])

    filtered_coords, filtered_intensities = _filter_sim_by_radius(
        coords, intensities, max_radius=0.5
    )
    assert len(filtered_coords) == 2
    assert len(filtered_intensities) == 2
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest spyde/tests/test_orientation_mapping.py::test_filter_sim_by_radius -v
```
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Add `_filter_sim_by_radius` to `spyde/actions/pyxem.py`**

Add before `orientation_mapping`:

```python
def _filter_sim_by_radius(coords, intensities, max_radius):
    """Return coords and intensities for spots within max_radius."""
    r = np.sqrt(coords[:, 0] ** 2 + coords[:, 1] ** 2)
    mask = r <= max_radius
    return coords[mask], intensities[mask]
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest spyde/tests/test_orientation_mapping.py::test_filter_sim_by_radius -v
```
Expected: PASS

- [ ] **Step 5: Add `_get_best_fit_spots` helper to `spyde/actions/pyxem.py`**

This helper extracts best-match spot positions from the orientation map for a single pattern:

```python
def _get_best_fit_spots(signal, sim, nav_indices, gamma, max_radius):
    """
    Run get_orientation on a single diffraction pattern and return
    (coords_px, intensities) for the best-match simulation spots.

    coords_px : ndarray shape (N, 2) in pixel (row, col) coordinates
    intensities : ndarray shape (N,)
    """
    import hyperspy.api as hs

    # Extract single pattern — nav_indices is (row, col) or (i,) depending on signal nav dims
    nav_axes = signal.axes_manager.navigation_axes
    idx = tuple(int(i) for i in nav_indices)
    pattern_data = signal.data[idx]  # shape (ky, kx)
    pattern_signal = hs.signals.Signal2D(pattern_data)
    # Copy signal axes calibration
    for i, ax in enumerate(signal.axes_manager.signal_axes):
        pattern_signal.axes_manager.signal_axes[i].scale = ax.scale
        pattern_signal.axes_manager.signal_axes[i].offset = ax.offset
        pattern_signal.axes_manager.signal_axes[i].units = ax.units

    pattern_signal.set_signal_type("electron_diffraction")
    polar = pattern_signal.get_azimuthal_integral2d(
        npt=100, npt_azim=360, inplace=False, mean=True
    )
    polar = polar ** gamma

    orientation = polar.get_orientation(sim)

    # Get the best match simulation
    best_phase_idx = int(orientation.data["phase_index"].ravel()[0])
    best_rotation = orientation.data["orientation"].ravel()[0]

    # Re-simulate at the best rotation to get spot positions
    sig_ax = signal.axes_manager.signal_axes
    scale = sig_ax[0].scale  # Å⁻¹/px
    sim_at_best = sim.rotate_from_orientation(best_rotation)
    raw_coords = sim_at_best.coordinates  # shape (N, 2) in Å⁻¹
    intensities = sim_at_best.intensities   # shape (N,)

    # Filter by radius
    coords_filtered, intensities_filtered = _filter_sim_by_radius(
        raw_coords, intensities, max_radius
    )
    # Convert Å⁻¹ to pixel coords
    coords_px = coords_filtered / scale
    # Center on pattern
    cx = pattern_data.shape[1] / 2.0
    cy = pattern_data.shape[0] / 2.0
    coords_px[:, 0] += cx
    coords_px[:, 1] += cy
    return coords_px, intensities_filtered
```

- [ ] **Step 6: Fill in `_on_open_refine_clicked` inside `orientation_mapping`**

Replace the placeholder `_on_open_refine_clicked`:

```python
def _on_open_refine_clicked():
    from pyqtgraph import ScatterPlotItem, CircleROI as PgCircleROI
    from PySide6.QtCore import QTimer

    refine_pw = main_window.add_plot_window(
        is_navigator=False,
        signal_tree=plot.signal_tree,
    )
    refine_pw.owner_plot_window = plot.plot_window
    main_window._auto_position_near_owner(refine_pw)
    refine_plot = refine_pw.add_new_plot()
    if refine_plot.image_item not in refine_plot.items:
        refine_plot.addItem(refine_plot.image_item)
    _refine_plot_window[0] = refine_pw

    # Load current nav position pattern into refine plot
    nav_indices = _get_current_nav_indices(plot)
    _update_refine_pattern(refine_plot, signal, nav_indices)

    # Scatter overlay
    scatter = ScatterPlotItem(size=8, pen=mkPen("r", width=1), brush=None)
    refine_plot.addItem(scatter)
    _scatter_item[0] = scatter

    # Circle ROI for max radius
    sig_ax = signal.axes_manager.signal_axes
    cx_px = sig_ax[0].size / 2.0
    cy_px = sig_ax[1].size / 2.0
    r_px = _max_radius[0] / sig_ax[0].scale
    circle_roi = PgCircleROI(
        pos=(cx_px - r_px, cy_px - r_px),
        size=(2 * r_px, 2 * r_px),
        pen=mkPen("y", width=1),
    )
    refine_plot.addItem(circle_roi)

    # Debounce timer
    refit_timer = QTimer()
    refit_timer.setInterval(150)
    refit_timer.setSingleShot(True)
    _refit_timer.append(refit_timer)

    def _do_refit():
        if _sim[0] is None:
            return
        r_px_now = circle_roi.size().x() / 2.0
        _max_radius[0] = r_px_now * sig_ax[0].scale
        nav_idx = _get_current_nav_indices(plot)
        try:
            coords_px, intensities = _get_best_fit_spots(
                signal, _sim[0], nav_idx, _gamma[0], _max_radius[0]
            )
            spots = [{"pos": (c[0], c[1]), "size": max(3, intensities[i] * 12)}
                     for i, c in enumerate(coords_px)]
            _scatter_item[0].setData(spots)
        except Exception as e:
            print(f"Refit failed: {e}")

    def _schedule_refit():
        refit_timer.start()

    refit_timer.timeout.connect(_do_refit)
    circle_roi.sigRegionChangeFinished.connect(_schedule_refit)

    # Hook into navigator selector position changes
    nav_selector = getattr(plot, "parent_selector", None)
    if nav_selector is not None and hasattr(nav_selector, "roi"):
        nav_selector.roi.sigRegionChangeFinished.connect(_schedule_refit)

    # Sliders wired in Task 6; unlock Step 5 immediately
    for w in _step5_widgets:
        w.setEnabled(True)

    _schedule_refit()
```

- [ ] **Step 7: Add `_get_current_nav_indices` and `_update_refine_pattern` helpers**

Add before `orientation_mapping`:

```python
def _get_current_nav_indices(plot):
    """Return current navigation indices as a tuple of ints."""
    selector = getattr(plot, "parent_selector", None)
    if selector is not None:
        try:
            indices = selector.get_selected_indices()
            return tuple(int(i) for i in np.atleast_1d(indices))
        except Exception:
            pass
    # Fallback: centre of navigation space
    nav_axes = plot.plot_state.current_signal.axes_manager.navigation_axes
    return tuple(ax.size // 2 for ax in nav_axes)


def _update_refine_pattern(refine_plot, signal, nav_indices):
    """Load the diffraction pattern at nav_indices into refine_plot."""
    idx = tuple(int(i) for i in nav_indices)
    pattern_data = np.array(signal.data[idx])
    refine_plot.update_data(pattern_data)
```

- [ ] **Step 8: Run all tests so far**

```
pytest spyde/tests/test_orientation_mapping.py -v
```
Expected: all PASS

- [ ] **Step 9: Commit**

```bash
git add spyde/actions/pyxem.py spyde/tests/test_orientation_mapping.py
git commit -m "feat: implement Step 4 refine preview with live overlay"
```

---

## Task 6: Add parameter sliders to Step 4 (scale, gamma, min intensity)

The refine caret panel needs float sliders for scale, gamma, and min intensity that trigger the refit loop.

**Files:**
- Modify: `spyde/actions/pyxem.py`

- [ ] **Step 1: Add slider parameters to the `params` dict in `orientation_mapping`**

In the `params` dict inside `orientation_mapping`, add these entries after `"open_refine_row"`:

```python
        "gamma": {
            "name": "Gamma",
            "type": "float",
            "default": 0.5,
        },
        "min_intensity_refine": {
            "name": "Min Spot Intensity",
            "type": "float",
            "default": 0.1,
        },
        "scale_override": {
            "name": "Scale (Å⁻¹/px, 0=auto)",
            "type": "float",
            "default": 0.0,
        },
```

Add these three keys to `_step4_widgets` collection (they start disabled, enabled when Step 4 opens):

In the section that populates `_step4_widgets`, add to the key list:

```python
for key in ["open_refine_btn", "gamma", "min_intensity_refine", "scale_override"]:
```

- [ ] **Step 2: Wire slider changes to `_schedule_refit` inside `_on_open_refine_clicked`**

In `_on_open_refine_clicked`, after the `refit_timer.timeout.connect(_do_refit)` line, add:

```python
    def _on_param_changed(*args):
        gamma_txt = params_caret_box.get_parameter_widget("gamma")
        min_i_txt = params_caret_box.get_parameter_widget("min_intensity_refine")
        scale_txt = params_caret_box.get_parameter_widget("scale_override")
        try:
            _gamma[0] = float(gamma_txt.text()) if gamma_txt else 0.5
        except ValueError:
            pass
        try:
            _min_intensity[0] = float(min_i_txt.text()) if min_i_txt else 0.1
        except ValueError:
            pass
        try:
            v = float(scale_txt.text()) if scale_txt else 0.0
            _scale[0] = v if v > 0 else None
        except ValueError:
            pass
        _schedule_refit()

    for param_key in ["gamma", "min_intensity_refine", "scale_override"]:
        w = params_caret_box.get_parameter_widget(param_key)
        if w is not None and hasattr(w, "textChanged"):
            w.textChanged.connect(_on_param_changed)
```

- [ ] **Step 3: Run all tests**

```
pytest spyde/tests/test_orientation_mapping.py -v
```
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add spyde/actions/pyxem.py
git commit -m "feat: wire gamma/scale/min-intensity sliders to live refit"
```

---

## Task 7: Implement Step 5 — Run Fit

Fill in `_on_run_fit_clicked` to run the full orientation map on the Dask cluster and open result signals.

**Files:**
- Modify: `spyde/actions/pyxem.py`
- Modify: `spyde/tests/test_orientation_mapping.py`

- [ ] **Step 1: Write failing test**

Append to `spyde/tests/test_orientation_mapping.py`:

```python
def test_extract_orientation_map_outputs():
    """_extract_orientation_outputs returns a list of (signal, title) tuples."""
    from spyde.actions.pyxem import _extract_orientation_outputs
    import numpy as np

    mock_om = MagicMock()
    # correlation and mirror_symmetry are 2D arrays
    mock_om.correlation = MagicMock()
    mock_om.correlation.data = np.zeros((4, 4))
    mock_om.mirror_symmetry = MagicMock()
    mock_om.mirror_symmetry.data = np.zeros((4, 4))
    mock_om.phase_index = MagicMock()
    mock_om.phase_index.data = np.zeros((4, 4), dtype=int)

    nav_axes = []  # no nav axes for simplicity

    results = _extract_orientation_outputs(mock_om, nav_axes, n_phases=2)
    titles = [r[1] for r in results]
    assert "Orientation Map" in titles
    assert "Correlation Score" in titles
    assert "Mirror Symmetry" in titles
    assert "Phase Map" in titles
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest spyde/tests/test_orientation_mapping.py::test_extract_orientation_map_outputs -v
```
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Add `_extract_orientation_outputs` helper**

Add before `orientation_mapping`:

```python
def _extract_orientation_outputs(orientation_map, nav_axes, n_phases=1):
    """
    Extract result signals from an OrientationMap.

    Returns list of (BaseSignal, title_str) tuples.
    """
    import hyperspy.api as hs

    def _copy_nav_axes(sig, nav_axes):
        for i, ax in enumerate(nav_axes):
            out_ax = sig.axes_manager.navigation_axes[i] if i < sig.axes_manager.navigation_dimension else None
            if out_ax is not None:
                out_ax.scale = ax.scale
                out_ax.offset = ax.offset
                out_ax.units = ax.units
                out_ax.name = ax.name
        return sig

    results = []

    # Orientation map (IPF color)
    results.append((orientation_map, "Orientation Map"))

    # Correlation score
    corr = hs.signals.Signal2D(orientation_map.correlation.data)
    _copy_nav_axes(corr, nav_axes)
    corr.metadata.General.title = "Correlation Score"
    results.append((corr, "Correlation Score"))

    # Mirror symmetry
    mirror = hs.signals.Signal2D(orientation_map.mirror_symmetry.data)
    _copy_nav_axes(mirror, nav_axes)
    mirror.metadata.General.title = "Mirror Symmetry"
    results.append((mirror, "Mirror Symmetry"))

    # Phase map (only meaningful for multi-phase)
    if n_phases > 1:
        phase_map = hs.signals.Signal2D(orientation_map.phase_index.data.astype(float))
        _copy_nav_axes(phase_map, nav_axes)
        phase_map.metadata.General.title = "Phase Map"
        results.append((phase_map, "Phase Map"))

    return results
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest spyde/tests/test_orientation_mapping.py::test_extract_orientation_map_outputs -v
```
Expected: PASS

- [ ] **Step 5: Fill in `_on_run_fit_clicked` inside `orientation_mapping`**

Replace the placeholder `_on_run_fit_clicked`:

```python
def _on_run_fit_clicked():
    from PySide6 import QtCore as _QtCore
    from spyde.qt.compute_status_indicator import ComputeStatusIndicator

    if _sim[0] is None:
        print("No library generated. Run Step 3 first.")
        return

    gamma_val = _gamma[0]
    sim_val = _sim[0]
    nav_axes = list(signal.axes_manager.navigation_axes)
    n_phases = len(_phases) if _phases else 1

    run_btn = params_caret_box.get_parameter_widget("run_fit_btn")
    if run_btn:
        run_btn.setEnabled(False)

    def _do_fit():
        try:
            polar = signal.get_azimuthal_integral2d(
                npt=100, npt_azim=360, inplace=False, mean=True
            )
            polar = polar ** gamma_val
            orientation_map = polar.get_orientation(sim_val, n_best=-1, frac_keep=1)
            results = _extract_orientation_outputs(orientation_map, nav_axes, n_phases)
            for result_signal, title in results:
                result_signal.metadata.General.title = title
                main_window._pending_signal_queue.append(result_signal)
            _QtCore.QMetaObject.invokeMethod(
                main_window, "_flush_pending_signals",
                _QtCore.Qt.ConnectionType.QueuedConnection,
            )
        except Exception as e:
            print(f"Orientation mapping failed: {e}")
        finally:
            if run_btn:
                _QtCore.QMetaObject.invokeMethod(
                    run_btn, "setEnabled",
                    _QtCore.Qt.ConnectionType.QueuedConnection,
                    _QtCore.Q_ARG(bool, True),
                )

    import threading
    fit_thread = threading.Thread(target=_do_fit, daemon=True)
    fit_thread.start()
```

- [ ] **Step 6: Run all tests**

```
pytest spyde/tests/test_orientation_mapping.py -v
```
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add spyde/actions/pyxem.py spyde/tests/test_orientation_mapping.py
git commit -m "feat: implement Step 5 run fit and output signal extraction"
```

---

## Task 8: Run full test suite and manual smoke test

- [ ] **Step 1: Run full test suite**

```
pytest spyde/tests/ -v
```
Expected: all existing tests PASS, new orientation mapping tests PASS.

- [ ] **Step 2: Manual smoke test**

Start the app:
```
python -m spyde
```

1. Open a 4D-STEM dataset (`.hspy` or `.mrc` with 4D data)
2. Confirm "Orientation Mapping" button appears in the bottom toolbar
3. Click it — confirm wizard caret panel opens with Steps 1–5 visible, Steps 3–5 disabled
4. Drag a `.cif` file onto the drop zone — confirm Step 3 unlocks
5. Click "Generate Library" — confirm Step 4 unlocks
6. Click "Open Refine Preview" — confirm secondary PlotWindow opens with diffraction pattern visible
7. Confirm yellow circle ROI is present on the refine plot
8. Drag the navigator — confirm the diffraction pattern in the refine window updates and scatter overlay refits
9. Adjust gamma slider — confirm overlay updates after 150ms
10. Click "Run Fit" — confirm the button disables during computation and result signals open when complete

- [ ] **Step 3: Commit any fixes found during smoke test**

```bash
git add -p
git commit -m "fix: orientation mapping smoke test corrections"
```

---

## Self-Review Notes

- **`_get_best_fit_spots`**: depends on pyxem's `Simulation2D` having `.rotate_from_orientation()`, `.coordinates`, and `.intensities` attributes. Verify against actual pyxem API during Task 5 implementation — adjust attribute names if needed.
- **`orientation_map.correlation` / `.mirror_symmetry` / `.phase_index`**: verify attribute names on the actual `OrientationMap` object from pyxem during Task 7.
- **`Phase.from_cif`**: verify this is the correct orix API for CIF loading. Alternative: `from orix.io import load` or `diffpy.structure.loadStructure` + manual `Phase` construction.
- **Step 5 threading**: uses `threading.Thread` rather than Dask because `get_orientation` on the full dataset already uses Dask internally. If this causes Qt thread-safety issues, wrap in a `QThread` instead.
- The `file_drop` widget added to `CaretParams` does not yet support the `_get_param_value` / `_on_submit_clicked` path — it is read directly via `cif_widget.filesChanged` signal, which is correct for this use case.
