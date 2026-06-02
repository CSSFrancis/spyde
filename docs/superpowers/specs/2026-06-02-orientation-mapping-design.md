# Orientation Mapping Action — Design Spec

**Date:** 2026-06-02
**Status:** Approved

## Overview

Add a template-matching orientation mapping action to SpyDE for 4D-STEM datasets. The action is a single toolbar button that opens a caret panel wizard with 5 sequentially gated steps. It uses diffsims to generate a simulated diffraction library and pyxem's `get_orientation` to match each diffraction pattern against the library.

Scope: template matching only (not vector matching or ML/SPED).

---

## Toolbar Entry Point

New entry in `spyde/toolbars.yaml`:

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

A new SVG icon is needed at `spyde/drawing/toolbars/icons/orientation_mapping.svg`.

Implementation lives in `spyde/actions/pyxem.py` as a single `orientation_mapping(toolbar, ...)` closure function, following the same pattern as `add_virtual_image`.

---

## Wizard Steps

Each step has a status indicator and its controls are disabled until the previous step completes. Step 2 is the exception — it is never blocking.

### Step 1 — Load CIF / Define Crystal

**UI:**
- Drop zone + file browser button accepting one or more `.cif` files
- Once loaded, each phase is listed with its parsed name and space group
- Single shared numeric input: accelerating voltage (kV)

**On "Load":**
- Parse each CIF using `orix` / `diffpy.structure` into a `Phase` object
- Store phase list in closure
- Unlock Step 3

**Notes:**
- Multi-phase is supported — pass a list of phases and a list of rotation sets to `calculate_diffraction2d`
- No calibration input — RLVs are in real (Å⁻¹) units

---

### Step 2 — (Optional) Center DP

**UI:** Checkbox "Signal already centered" (default checked if signal went through Center Zero Beam upstream). If unchecked, a "Center Now" button calls the existing `center_zero_beam` logic.

**Gating:** Never blocks Step 3. Advisory only.

---

### Step 3 — Generate Library

**UI:**
- `resolution` — angle density in degrees (float, default 1.0)
- `minimum_intensity` — intensity threshold (float, default 0.05)
- "Generate" button

**On "Generate":**
```python
from diffsims.generators.simulation_generator import SimulationGenerator
from orix.sampling import get_sample_reduced_fundamental

generator = SimulationGenerator(accelerating_voltage, minimum_intensity=minimum_intensity)

# For each phase:
rotations = get_sample_reduced_fundamental(
    resolution=resolution,
    point_group=phase.point_group,
)

# reciprocal_radius derived from signal calibration axes (max physically reasonable extent)
sim = generator.calculate_diffraction2d(
    phases,                   # single Phase or list of Phases
    rotation=rotations,       # single or list of rotations
    max_excitation_error=0.1,
    reciprocal_radius=reciprocal_radius,  # auto-derived from signal, not user-facing
    with_direct_beam=False,
)
```

Runs on the main thread (fast, no Dask). Stores `sim` in closure. Unlocks Step 4.

**`reciprocal_radius` derivation:** computed from `signal.axes_manager.signal_axes` calibration at startup — set to the maximum reasonable extent of the diffraction pattern. Not exposed to the user.

---

### Step 4 — Refine Parameters

**UI:**
- `scale` slider — Å⁻¹/px (float)
- `gamma` slider — exponent for gamma correction applied as `polar ** gamma` before matching (float, default 0.5)
- `min_intensity` slider — minimum spot intensity to display in overlay (float)
- Circle ROI on the diffraction pattern plot — radius sets the max reciprocal radius used in matching (spots beyond this radius are filtered from the library at match time)

**Secondary PlotWindow:**
- Opens a new `PlotWindow` showing the diffraction pattern at the current navigator position
- A `ScatterPlotItem` overlays the best-fit simulation spots (position scaled to pixel coords, size/alpha weighted by intensity, filtered by circle ROI radius)
- The circle ROI is a `CircleROI` added to this plot

**Live refit triggers (all feed into a single `_schedule_refit()` with 150 ms debounce):**
1. Any slider value changes
2. Circle ROI resized
3. Navigator position changes (connected to the plot's existing nav update signal)

**Refit loop (per trigger):**
1. Extract single diffraction pattern at current nav position
2. Compute azimuthal integral: `pattern.get_azimuthal_integral2d(npt=100, npt_azim=360, mean=True)`
3. Apply gamma: `polar ** gamma`
4. Filter library spots beyond circle ROI radius
5. Call `polar.get_orientation(sim_filtered)`
6. Update `ScatterPlotItem` with best-match spot positions

Step 5 unlocks immediately after Step 4 opens (user runs fit whenever satisfied).

---

### Step 5 — Run Fit

**UI:** "Run Fit" button with a `ComputeStatusIndicator`.

**On "Run Fit":**
```python
# Compute azimuthal integral of full dataset
polar = signal.get_azimuthal_integral2d(npt=100, npt_azim=360, inplace=False, mean=True)
polar = polar ** gamma

# Run orientation mapping (via Dask)
orientation_map = polar.get_orientation(sim, n_best=-1, frac_keep=1)
```

**Output signals** — each pushed to `main_window._pending_signal_queue`:
1. `OrientationMap` — raw orientation map (IPF RGB)
2. Correlation score map — 2D image of best-match correlation scores
3. Mirror symmetry map — 2D image of mirror symmetry scores
4. Phase map — 2D image of best-match phase index (multi-phase only)

Navigation axes (scale, offset, units, name) copied from parent signal to each output.

---

## Code Structure

| File | Change |
|---|---|
| `spyde/toolbars.yaml` | Add `Orientation Mapping` entry |
| `spyde/actions/pyxem.py` | Add `orientation_mapping(toolbar, ...)` function |
| `spyde/drawing/toolbars/icons/orientation_mapping.svg` | New icon |

No new files beyond the icon. All wizard state lives in the `orientation_mapping` closure.

The caret panel parameter dict uses existing parameter types where possible. A new `file_drop` parameter type may need to be added to the caret system to support the drop zone + multi-file picker in Step 1.

---

## Dependencies

- `diffsims` — `SimulationGenerator`, `calculate_diffraction2d`
- `orix` — `get_sample_reduced_fundamental`, `Phase`
- `diffpy.structure` or `orix` — CIF parsing
- All already available in the pyxem dependency tree

---

## Future Work

See `docs/future_tasks.md` — "Action workspace management: too many overlapping PlotWindows as actions multiply."
