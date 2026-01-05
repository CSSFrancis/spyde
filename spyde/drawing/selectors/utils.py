import numpy as np
from spyde.external.pyqtgraph.crosshair_roi import CrosshairROI
from pyqtgraph import ROI, LinearRegionItem


def broadcast_rows_cartesian(*arrays: np.ndarray) -> np.ndarray:
    """
    Cartesian product over *rows* of multiple index arrays, keeping
    the columns of each array together.

    Each input is treated as shape (Ni, Ci): Ni rows, Ci columns.
    The output has shape (N_total, sum(Ci)), where N_total is the
    product of all Ni.

    Example:
    time_axs    : (3, 1) -> [[0],[1],[2]]
    spatial_axs : (3, 2) -> [[3,4],[4,5],[5,6]]

    broadcast_rows_cartesian(time_axs, spatial_axs) ->
        shape (9, 3), rows like [t, x, y].
    """
    if len(arrays) == 0:
        return np.empty((0, 0), dtype=int)

    # Normalize to 2D: (N_rows, N_cols)
    mats = [np.atleast_2d(a) for a in arrays]
    n_rows = [m.shape[0] for m in mats]

    # Meshgrid over row indices only
    grids = np.meshgrid(*[np.arange(n) for n in n_rows], indexing="ij")

    # For each array, select rows according to its index grid and reshape
    parts = []
    for m, g in zip(mats, grids):
        # g.ravel() gives the chosen row index per combination
        chosen_rows = m[g.ravel()]  # shape: (n_comb, Ci)
        parts.append(chosen_rows)

    # Concatenate columns from all arrays
    combined = np.concatenate(parts, axis=1)
    return combined


def no_return_update_function(
    selector: "BaseSelector", child_plot: "Plot", indices: np.ndarray
):
    """
    An update function that does nothing and returns None.
    Useful as a placeholder when no update is needed.
    """
    return None


def create_linked_rect_roi(core_roi: ROI) -> ROI:
    """Create a new ROI of the same type as `core_roi`, linked to `core_roi` so that it always matches its geometry/
    position.
    """

    roi_type = type(core_roi)

    # Handle CrosshairROI differently due to different constructor
    if isinstance(core_roi, CrosshairROI):
        # Get the view from the parent plot if available
        view = getattr(core_roi, 'view', None)
        new_roi = roi_type(
            pos=core_roi.pos(),
            pixel_size=core_roi.pixel_size,
            view=view,
            pen=core_roi.pen,
            hoverPen=core_roi.hoverPen,
        )
    else:
        new_roi = roi_type(
            pos=core_roi.pos(),
            size=core_roi.size(),
            pen=core_roi.pen,
            handlePen=core_roi.handlePen,
            hoverPen=core_roi.hoverPen,
            handleHoverPen=core_roi.handleHoverPen,
        )

    def sync_roi(source_roi, target_roi):
        """Synchronize target_roi to match source_roi's state."""
        target_roi.blockSignals(True)  # Prevent infinite recursion
        target_roi.setPos(source_roi.pos(), finish=False)
        target_roi.setSize(source_roi.size(), finish=False)
        target_roi.setAngle(source_roi.angle(), finish=False)
        target_roi.blockSignals(False)
        print("Syncing ROIs:", source_roi, target_roi)
        #target_roi.sigRegionChanged.emit()

    core_roi.sigRegionChanged.connect(lambda: sync_roi(core_roi, new_roi))
    new_roi.sigRegionChanged.connect(lambda: sync_roi(new_roi, core_roi))

    new_roi.sigRegionChanged.connect(core_roi.sigRegionChanged.emit)

    return new_roi

def create_linked_linear_region(core_roi: LinearRegionItem,
                                pen,
                                hover_pen) -> LinearRegionItem:
    """Create a new LinearRegionItem linked to `core_roi` so that it always matches its geometry/position.
    """

    new_roi = LinearRegionItem(
        values=core_roi.getRegion(),
        pen = pen,
        hoverPen = hover_pen,
    )

    def sync_roi(source_roi, target_roi):
        """Synchronize target_roi to match source_roi's state."""
        target_roi.blockSignals(True)  # Prevent infinite recursion
        target_roi.setRegion(source_roi.getRegion())
        target_roi.blockSignals(False)
        print("Syncing Linear ROIs:", source_roi, target_roi)

    core_roi.sigRegionChanged.connect(lambda: sync_roi(core_roi, new_roi))
    new_roi.sigRegionChanged.connect(lambda: sync_roi(new_roi, core_roi))

    new_roi.sigRegionChanged.connect(core_roi.sigRegionChanged.emit)

    return new_roi

def create_linked_infinite_line(core_roi: ROI,
                                pen,
                                hover_pen) -> ROI:
    """Create a new InfiniteLine linked to `core_roi` so that it always matches its geometry/position.
    """

    from pyqtgraph import InfiniteLine

    new_roi = InfiniteLine(
        pos=core_roi.value(),
        angle=core_roi.angle,
        pen=pen,
        hoverPen=hover_pen,
        movable=True,
        bounds=None,
    )

    def sync_roi(source_roi, target_roi):
        """Synchronize target_roi to match source_roi's state."""
        target_roi.blockSignals(True)  # Prevent infinite recursion
        target_roi.setValue(source_roi.value())
        target_roi.setAngle(source_roi.angle)
        target_roi.blockSignals(False)
        print("Syncing Infinite Lines:", source_roi, target_roi)

    core_roi.sigPositionChanged.connect(lambda: sync_roi(core_roi, new_roi))
    new_roi.sigPositionChanged.connect(lambda: sync_roi(new_roi, core_roi))

    new_roi.sigPositionChanged.connect(core_roi.sigPositionChanged.emit)

    return new_roi