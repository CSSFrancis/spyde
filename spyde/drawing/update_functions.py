"""
update_functions.py

Module containing functions to update a plot based on a selector.  These functions are
called on the move or change events of a selector.

"""

import sys
import numpy as np
import dask
import dask.array as da
import distributed
from distributed import Future

from scipy import fft

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spyde.drawing.selectors import BaseSelector
    from spyde.drawing.plots.plot import Plot
from multiprocessing import shared_memory

# Shared memory IPC only works on non-Windows: on Windows, Dask workers are
# separate processes and cannot open shared memory segments created by the GUI
# process (OpenFileMapping fails with FileNotFoundError).
_SHARED_MEMORY_SUPPORTED = sys.platform != "win32"

def write_shared_array(data, shared_arr_name):
    dtype_bytes = data.dtype.str.encode('utf-8')
    dtype_length = len(dtype_bytes)
    # Calculate header size: 4 bytes for dtype length + dtype bytes + shape info
    ndim = data.ndim
    # Create shared memory
    shm = shared_memory.SharedMemory(name=shared_arr_name)
    # Write header
    buffer = shm.buf
    offset = 0
    # Write dtype length (4 bytes)
    buffer[offset:offset+4] = dtype_length.to_bytes(4, byteorder='little')
    offset += 4
    # Write dtype string
    buffer[offset:offset+dtype_length] = dtype_bytes
    offset += dtype_length
    # Write number of dimensions (4 bytes)
    buffer[offset:offset+4] = ndim.to_bytes(4, byteorder='little')
    offset += 4
    # Write shape (8 bytes per dimension)
    for dim in data.shape:
        buffer[offset:offset+8] = dim.to_bytes(8, byteorder='little')
        offset += 8
    # Write array data
    target_arr = np.ndarray(data.shape, dtype=data.dtype, buffer=shm.buf[offset:])
    target_arr[:] = data
    return


def read_shared_array(shm):
    buffer = shm.buf
    offset = 0
    # Read dtype length
    dtype_length = int.from_bytes(buffer[offset:offset+4], byteorder='little')
    offset += 4
    # Read dtype
    dtype_str = bytes(buffer[offset:offset+dtype_length]).decode('utf-8')
    dtype = np.dtype(dtype_str)
    offset += dtype_length
    # Read ndim
    ndim = int.from_bytes(buffer[offset:offset+4], byteorder='little')
    offset += 4
    # Read shape
    shape = tuple(int.from_bytes(buffer[offset+i*8:offset+(i+1)*8], byteorder='little')
                  for i in range(ndim))
    offset += ndim * 8
    # Create array from buffer
    arr = np.ndarray(shape, dtype=dtype, buffer=buffer[offset:])
    return arr

def update_from_navigation_selection(
        selector: "BaseSelector",
        child: "Plot",
        indices,
        get_result: bool = False,
        cache_in_shared_memory: bool = True,
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
    cache_in_shared_memory : bool
        Whether to cache the result in shared memory. This bypasses TCP transfer
        with distributed futures but requires that the child process can access the
        shared memory (e.g., same machine). Default is False.
    """
    # get the data from the signal tree based on the current indices

    current_signal = child.plot_state.current_signal

    if not selector.is_integrating:
        indices = np.mean(indices, axis=0).astype(int)

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
            if cache_in_shared_memory and _SHARED_MEMORY_SUPPORTED:
                # Write to shared memory and return the name.
                # Only used on non-Windows: Dask workers on Windows are separate
                # processes and cannot open shared memory created by the GUI process.
                shared_arr_name = f"plot_buffer{id(child)}"
                current_img = child.main_window.dask_manager.client.submit(write_shared_array,
                                                current_img,
                                                shared_arr_name)
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

    img = selector.parent.image_item.image

    img_max_x = img.shape[0] - 1
    img_max_y = img.shape[1] - 1
    if max_x > img_max_x:
        max_x = img_max_x
    if max_y > img_max_y:
        max_y = img_max_y
    if min_x < 0:
        min_x = 0
    if min_y < 0:
        min_y = 0

    slice_x, slice_y = slice(min_x, max_x + 1), slice(min_y, max_y + 1)
    sliced_img = img[slice_x, slice_y]
    fft_img = fft.fftshift(fft.fft2(sliced_img))
    return fft_img.real


def compute_virtual_image_kernel(
    data: da.Array,
    mask: np.ndarray,
    client: distributed.Client,
    gpu_worker_address: "str | None",
) -> distributed.Future:
    """
    Compute a virtual image by masking and summing the last two (signal) axes.

    Equivalent to:
        np.sum(data * mask[np.newaxis, np.newaxis, ...], axis=(-1, -2))

    Works for any number of navigation axes (3D, 4D, 5D, 6D datasets).
    Signal axes must be the last two (HyperSpy convention).

    Broadcasting mask as a numpy array (not a dask array) means each worker
    multiplies its navigation chunk directly against the in-memory mask without
    any cross-chunk communication, then reduces over the last two axes within
    the chunk. This is O(n_nav_chunks) independent tasks with no shuffle.

    Parameters
    ----------
    data : dask array, shape (...nav..., ky, kx)
    mask : float32 numpy array, shape (ky, kx)
    client : dask distributed Client
    gpu_worker_address : str or None

    Returns
    -------
    distributed.Future resolving to np.ndarray of shape (...nav...)
    """
    mask = np.asarray(mask, dtype=np.float32)
    if gpu_worker_address:
        with dask.annotate(resources={"GPU": 1}):
            result = (data * mask).sum(axis=(-2, -1))
    else:
        result = (data * mask).sum(axis=(-2, -1))
    return client.compute(result)


def compute_line_profile_kernel(
    image: np.ndarray,
    roi,
    image_item,
    client: distributed.Client,
) -> distributed.Future:
    """Extract a 1D line profile from a 2D image via LineROI.getArrayRegion.

    Parameters
    ----------
    image : np.ndarray, shape (ny, nx)
        The currently displayed image (plot.image_item.image).
    roi : pyqtgraph.LineROI
    image_item : pyqtgraph.ImageItem
    client : dask distributed Client

    Returns
    -------
    distributed.Future resolving to np.ndarray shape (length_px,)

    Notes
    -----
    LineROI.getArrayRegion returns shape (length_px, width_px).
    nanmean over axis=1 collapses the perpendicular width to give the profile.
    """
    region = roi.getArrayRegion(image, image_item)   # (length_px, width_px)
    profile = np.nanmean(region, axis=1)             # (length_px,)
    return client.submit(lambda p=profile: p)


def compute_nav_line_sum_kernel(
    data: da.Array,
    ys: np.ndarray,
    xs: np.ndarray,
    client: distributed.Client,
    gpu_worker_address: "str | None",
) -> distributed.Future:
    """Compute the mean diffraction pattern over all nav pixels in a line strip.

    Parameters
    ----------
    data : dask array, shape (...nav..., nkx, nky)
        HyperSpy convention: last two axes are signal.
    ys : np.ndarray, shape (N,)
        Row (y) pixel indices of all nav pixels inside the strip.
    xs : np.ndarray, shape (N,)
        Column (x) pixel indices of all nav pixels inside the strip.
    client : dask distributed Client
    gpu_worker_address : str or None

    Returns
    -------
    distributed.Future resolving to np.ndarray shape (nkx, nky)
    """
    # Dask doesn't support multi-dimensional fancy indexing, so loop and vstack
    slices = [data[int(y), int(x)] for y, x in zip(ys, xs)]
    nav_slices = da.stack(slices, axis=0)  # (N, nkx, nky)
    resources = {"GPU": 1} if gpu_worker_address else {}
    with dask.annotate(resources=resources):
        result = da.mean(nav_slices, axis=0)
    return client.compute(result)
