"""
update_functions.py

Module containing functions to update a plot based on a selector.  These functions are
called on the move or change events of a selector.

"""

import numpy as np
from distributed import Future

from scipy import fft

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spyde.drawing.selector import BaseSelector
    from spyde.drawing.plots.plot import Plot


def update_from_navigation_selection(
    selector: "BaseSelector", child: "Plot", indices, get_result: bool = False
):
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

    print("Updating child plot based on navigation selection with indices:", indices)
    print("Current signal shape", current_signal.data.shape)

    if current_signal._lazy:
        if isinstance(current_signal.data[0], Future):
            current_img = np.ones(current_signal.axes_manager.signal_shape, dtype=np.int8)
            if current_img.ndim == 2:
                #make checkerboard pattern to indicate loading
                current_img[::2, ::2] = 0
        else:
            # Always return the future...
            current_img = current_signal._get_cache_dask_chunk(
                indices, get_result=get_result, return_future=True,
            )
    else:

        tuple_inds = tuple([indices[ind] for ind in np.arange(len(indices))])
        if len(tuple_inds) == 1:
            current_img = current_signal.data[tuple_inds]
        else:
            current_img = np.mean(current_signal.data[tuple_inds], axis=0)
    return current_img


def get_fft(selector: "BaseSelector", child: "Plot", indices, get_result: bool = False):
    """
    Get the FFT of the image.

    Parameters
    ----------
    img : array-like
        The input image.

    Returns
    -------
    array-like
        The FFT of the input image.
    """
    # convert indices to image slice:
    max_x, max_y = np.max(indices, axis=0)
    min_x, min_y = np.min(indices, axis=0)

    img_max_x = selector.parent.current_data.shape[0] - 1
    img_max_y = selector.parent.current_data.shape[1] - 1
    if max_x > img_max_x:
        max_x = img_max_x
    if max_y > img_max_y:
        max_y = img_max_y
    if min_x < 0:
        min_x = 0
    if min_y < 0:
        min_y = 0

    slice_x, slice_y = slice(min_x, max_x + 1), slice(min_y, max_y + 1)
    sliced_img = selector.parent.current_data[slice_x, slice_y]
    fft_img = fft.fftshift(fft.fft2(sliced_img))
    return fft_img.real
