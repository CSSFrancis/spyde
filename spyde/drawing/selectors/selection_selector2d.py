from typing import List

from pyqtgraph import ROI
from copy import deepcopy

def static_roi(roi:ROI) -> ROI:
    """
    Convert a dynamic ROI to a static one by copying its current state.
    """
    new_roi = deepcopy(roi)
    new_roi.translatable = False
    new_roi.rotatable = False
    new_roi.resizable = False
    return new_roi


class SelectionSelector2D:
    """
    Base class for 2D selection selectors.
    """

    def __init__(self,
                 rois:List[ROI|List[ROI]]):
        static_rois = []
        for roi in rois:
            if isinstance(roi, list):
                static_rois.append([static_roi(r) for r in roi])
            else:
                static_rois.append(static_roi(roi))

        self.rois = static_rois # type: List[ROI] or List[List[ROI]]

        for i, roi in enumerate(rois):
            if isinstance(roi, list):
                static_roi_list = [static_roi(r) for r in roi]
                for r in static_roi_list:
                    r.sigClicked.connect(lambda _, idx=i: self._on_roi_clicked(idx))
                static_rois.append(static_roi_list)
            else:
                static_r = static_roi(roi)
                static_r.sigClicked.connect(lambda _, idx=i: self._on_roi_clicked(idx))
                static_rois.append(static_r)

        self.rois = static_rois # type: List[ROI] or List[List[ROI]]
        self._last_clicked_index = None

    def _on_roi_clicked(self, index: int):
        """Handle ROI click events."""
        self._last_clicked_index = index

    def _get_selected_indices(self) -> int | None:
        """Return the index of the last clicked ROI."""
        return self._last_clicked_index