"""
update_functions.py

Module containing functions to update a plot based on a selector.  These functions are
called on the move or change events of a selector.

"""
import numpy as np

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from despy.drawing.selector import BaseSelector
    from despy.drawing.multiplot import Plot


def update_from_navigation_selection(selector: "BaseSelector",
                                     child: "Plot",
                                     indices,
                                     get_result: bool = False):
    """
    Update the plot based on the navigation selection. This is the most common update function for using some
    navigation selector (on a parent) and updating a child plot.

    Parameters
    ----------
    selector : BaseSelector
        The selector that triggered the update.
    child : Plot
        The child plot to update.
    indices : array-like
        The indices selected by the selector.
    get_result : bool
        Whether to compute the result immediately (for Dask arrays). Always False for using
        dask distributed futures.
    """
    # get the data from the signal tree based on the current indices

    current_signal = child.plot_state.current_signal

    if not selector.is_integrating:
        indices = np.mean(indices, axis=0).astype(int)

    if current_signal._lazy:
        current_img = current_signal._get_cache_dask_chunk(indices,
                                                           get_result=get_result)
    else:
        tuple_inds = tuple([indices[ind]
                            for ind in np.arange(len(indices))])
        current_img = np.sum(current_signal.data[tuple_inds], axis=0)
    return current_img

