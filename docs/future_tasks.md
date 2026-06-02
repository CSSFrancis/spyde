# Future Tasks

Items flagged during design/implementation sessions for later consideration. Not prioritized.

---

## Action Workspace Management

**Problem:** As more actions are added (Virtual Imaging, Orientation Mapping, Line Profile, etc.), each spawning its own `PlotWindow` and overlay items, the MDI area becomes cluttered with overlapping windows that are hard to manage together.

**Context:** Flagged during orientation mapping design session (2026-06-02). The `add_virtual_image` closure pattern works well for individual actions but doesn't coordinate across multiple active actions.

**Possible directions:**
- A workspace/layout manager that groups action-owned windows near their parent
- A way to minimize/collapse action windows together when the action is toggled off
- Docking or tiling strategies for action preview windows
