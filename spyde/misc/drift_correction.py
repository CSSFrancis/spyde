"""
Functions to perform a lazy drift correction on a dataset.  This isn't entirely lazy, but it's written using
dask to allow for using multiple cores. It might be more efficient to implement this using the GPU at some point.
"""

import dask.array as da
import numpy as np
from typing import Tuple

def get_shifts(reference: np.ndarray,
               current_data: np.ndarray,
               sobel:bool = True,
               phase_correlation: bool = True,
               hanning: bool = True,
               roi : Tuple[int, int, int, int] = None,
               ) -> Tuple[float, float]:
    """
    Calculate the shifts between the reference and current data using some form of correlation.

    Parameters
    ----------
    reference : np.ndarray
        The reference image to compare against.
    current_data : np.ndarray
        The current image to calculate the shift for.
    sobel : bool, optional
        Whether to apply a Sobel filter to enhance edges. Default is True.
    phase_correlation : bool, optional
        Whether to use phase correlation for shift calculation. Default is True.
    hanning : bool, optional
        Whether to apply a Hanning window to reduce edge effects. Default is True.
    roi : Tuple[int, int, int, int], optional
        A region of interest (x_start, x_end, y_start, y_end) to limit the area of interest. Default is None.
    """
    pass


def drift_correction():
    """
    So there are a couple of different cases:

    1. We align to the 1st frame always.  This is a simple embarrassingly parallel problem.
    2. We align to the previous frame.  This is a serial problem, but we can do some overlapping
       computations to speed things up. Unfortunately we need to know all the shifts to determine
       how to align each frame.  But the alignments can be saved?
    3. A Statistical approach where each frame is aligned to the n frames before and n frames after.
       The 3 best "references" are determined by the highest average cross-correlation and the
       shifts for those frames are averaged to determine the final shift for the current frame.
    """


def map_overlap_drift_correction(data):
    if data.ndim != 3:
        raise ValueError(f"Data must be 3D for drift correction not: {data.ndim}.")

    if not isinstance(data, da.Array):
        data = da.asarray(data, chunks= ("auto", -1, -1))

    da.map_overlap(drift_correction,
                  data,
                  depth= {0:1, 1:0, 2:0},
                  dtype=data.dtype,
                  drop_axis=0,
                  new_axis=0)


