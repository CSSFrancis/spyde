# PlotWindow Focus & Organization Polish

**Date:** 2026-05-31  
**Status:** Approved

## Overview

When a line profile (or other toolbar action) is added, the MDI area becomes cluttered: preview windows float freely, all windows are always fully visible regardless of which SignalTree is active, and the commit button is oversized and oddly placed. This design introduces a 3-state visibility model, ownership tagging for preview windows, a repositioned/restyled commit button, smarter preview placement, and a tile shortcut.

---

## 1. Three-State Visibility Model

Every `PlotWindow` is in exactly one of three states at any time, recomputed in `MainWindow.on_subwindow_activated` whenever the active window changes.

| State | Condition | Visual Effect |
|---|---|---|
| **Shown** | `signal_tree` == active signal tree | 100% opacity, visible |
| **Background** | `signal_tree` != active, no `owner_plot_window` | 65% opacity, still visible |
| **Hidden** | has `owner_plot_window` AND `signal_tree` != active | `hide()` — fully removed from view |

**Rules:**
- Core/nav windows (no `owner_plot_window`) are never fully hidden — they go Background at worst.
- Action-preview windows (have `owner_plot_window`) are Hidden whenever their SignalTree is not active, and Shown when it is.
- `setWindowOpacity(0.65)` implements Background; `hide()`/`show()` implements Hidden.
- When a hidden window's SignalTree becomes active again it is `show()`n and restored to 100% opacity.

---

## 2. Ownership Tagging

**Problem:** Preview windows created by toolbar actions (`line_profile.py`, `pyxem.py`, `base.py`) currently pass `signal_tree=None` to `add_plot_window`, so they have no tree membership and no owner.

**Change:** Add an `owner_plot_window: PlotWindow | None = None` attribute to `PlotWindow`. At preview-window creation time:

1. Pass the owner plot's `signal_tree` (not `None`) to `add_plot_window`.
2. Set `preview_window.owner_plot_window = plot` (the Plot's parent PlotWindow).

This ensures every `PlotWindow` always has a `signal_tree`, and the 3-state logic is purely data-driven.

**Files to update:** `spyde/actions/line_profile.py`, `spyde/actions/pyxem.py`, `spyde/actions/base.py`

---

## 3. Title Bar Layout & Commit Button Restyle

**New left-to-right order:**

```
[status circle] [commit]          [title]          [min] [max] [close]
```

The status circle (`ComputeStatusIndicator`) moves from a floating overlay on the plot widget into the title bar's left zone, sitting at the same visual level as the commit button. This cleans up the plot area and groups action feedback together.

**Commit button changes:**
- Fixed height: 18px (down from 20px)
- Border-radius: 8px (pill shape)
- Horizontal padding: 4px each side (tighter)
- Position: inserted at index 1 in the title bar layout (after status placeholder at index 0)

**Status circle in title bar:**
- `set_compute_indicator` in `PlotWindow` currently calls `indicator.setParent(self)` and positions it at `(8, 8)` as a floating overlay. Change it to insert the indicator widget into the title bar layout at index 0 instead.
- When no indicator is set, index 0 is an empty `QWidget` spacer of fixed size so the commit button doesn't jump.

**Files to update:** `spyde/qt/subwindow.py`, `spyde/drawing/plots/plot_window.py`

---

## 4. Preview Window Placement

**Problem:** New preview windows appear at a default position (usually center or top-left), piling on top of existing windows.

**Change:** In `add_plot_window` (or immediately after in the action code), if the window has an `owner_plot_window`, auto-position it:

1. Try placing it to the **right** of the owner: `x = owner.x() + owner.width() + 8`, `y = owner.y()`.
2. If that would overflow the MDI area width, try placing it **below** the owner instead.
3. Clamp final position to MDI bounds.

This is a best-effort placement — the user can move windows freely afterwards.

**Files to update:** `spyde/drawing/plots/plot_window.py` (add a `_auto_position_near_owner` helper called from `add_plot_window` in `__main__.py`)

---

## 5. Tile Button

Add a small tile/grid icon button to the `MainWindow`'s MDI toolbar area (top-right of the MDI area, or in the main toolbar). On click:

1. Collect all **Shown** `PlotWindow`s (those belonging to the active SignalTree).
2. Compute an even grid layout: `ceil(sqrt(n))` columns, enough rows to fit all windows.
3. Divide the MDI viewport into equal cells and `setGeometry` each window to its cell (with a small margin).
4. Background windows are excluded — they remain wherever they are.

**Files to update:** `spyde/__main__.py` (add `tile_active_windows` slot + button wiring)

---

## Implementation Order

1. Ownership tagging (`owner_plot_window` attribute + pass signal_tree in action files)
2. Three-state visibility in `on_subwindow_activated`
3. Title bar layout & commit button restyle
4. Preview window auto-placement
5. Tile button
