import dask.array as da
import numpy as np
from math import log10, floor

def fast_index_virtual(arr, indexes, method="sum", reverse=True):
    """
    Fast gather-and-reduce over a set of N-D integer index coordinates.

    Parameters
    ----------
    arr : numpy.ndarray | dask.array.Array
        Source array. The indexed dimensions are assumed to be the trailing ones
        when reverse is True.
    indexes : array-like, shape (K, D)
        Integer index coordinates. K points across D indexed dims.
    method : str
        Reduction method across the indexed dimensions: "sum" or "mean".
    reverse : bool
        If True, treat the D indexed dims as the last D dims of `arr`.
        reverse=False is not implemented.

    Returns
    -------
    numpy.ndarray | dask.array.Array
        Reduced array with the indexed dims removed.
    """
    if indexes is None:
        return arr

    idx = np.asarray(indexes)
    if idx.size == 0:
        return arr
    if idx.ndim == 1:
        idx = idx[:, None]

    # Compute bounding box and mask within that box to avoid fancy indexing
    mins = idx.min(axis=0)
    maxs = idx.max(axis=0)
    slice_ranges = tuple(slice(int(lo), int(hi) + 1) for lo, hi in zip(mins, maxs))
    shape = (maxs - mins + 1).astype(int)
    mask = np.zeros(shape, dtype=bool)
    shifted = (idx - mins).astype(int)
    mask[tuple(shifted.T)] = True

    if not reverse:
        raise NotImplementedError("reverse=False is not implemented.")

    # Extract only the bounding box from the end of arr's dims
    sub = arr[(...,) + slice_ranges]

    # Broadcast mask to the trailing dims of `sub`
    extend = (sub.ndim - mask.ndim) * (None,)
    bmask = mask[extend]

    is_dask = isinstance(sub, da.Array)

    if method == "sum":
        prod = sub * bmask
        axes = tuple(range(-mask.ndim, 0))
        return da.sum(prod, axis=axes) if is_dask else np.sum(prod, axis=axes)

    if method == "mean":
        # Replace non-selected values by NaN, then nanmean across indexed dims
        subf = sub.astype(float)
        masked = da.where(bmask, subf, np.nan) if is_dask else np.where(bmask, subf, np.nan)
        axes = tuple(range(-mask.ndim, 0))
        return da.nanmean(masked, axis=axes) if is_dask else np.nanmean(masked, axis=axes)

    raise ValueError(f"Unsupported reduction method: {method}")


def get_nice_length(signal, is_navigator=False):
    """
    Get a nice length for plotting axes.

    Returns
    -------
    int
        A nice length value.
    """
    if is_navigator:
        axes = signal.axes_manager.navigation_axes
    else:
        axes = signal.axes_manager.signal_axes

    x_range = axes[0].scale * axes[0].size

    target = x_range / 5
    if not np.isfinite(target) or target <= 0:
        target = 1.0

    exp = floor(log10(target))
    base = 10 ** exp
    norm = target / base

    if norm < 1.5:
        nice = 1.0
    elif norm < 2.5:
        nice = 2.0
    elif norm < 3.5:
        nice = 2.5
    elif norm < 7.5:
        nice = 5.0
    else:
        nice = 10.0

    nice_length = nice * base
    units = signal.axes_manager.signal_axes[0].units
    return nice_length, units
