from __future__ import annotations
from PySide6 import QtCore, QtWidgets
from pyqtgraph import  CircleROI
import numpy as np


class RingROI(QtWidgets.QGraphicsObject):
    r"""
    Chain of rectangular ROIs connected by handles.

    This is generally used to mark a curved path through
    an image similarly to PolyLineROI. It differs in that each segment
    of the chain is rectangular instead of linear and thus has width.

    ============== =============================================================
    **Arguments**
    points         (list of length-2 sequences) The list of points in the path.
    width          (float) The width of the ROIs orthogonal to the path.
    \**args        All extra keyword arguments are passed to ROI()
    ============== =============================================================
    """

    sigRegionChangeFinished = QtCore.Signal(object)
    sigRegionChangeStarted = QtCore.Signal(object)
    sigRegionChanged = QtCore.Signal(object)

    def __init__(self, center, inner_rad, outer_rad, pen=None, **args):
        QtWidgets.QGraphicsObject.__init__(self)
        self.pen = pen
        self.roiArgs = args
        self.rois = []

        ## create first segment
        self.addSegment(center, inner_rad)
        self.addSegment(center, outer_rad)

        # connect the move event of the first ROI to update the others
        first_roi = self.rois[0]
        first_roi.sigRegionChanged.connect(self.roiChangedEvent)
        first_roi.sigRegionChangeStarted.connect(self.roiChangeStartedEvent)
        first_roi.sigRegionChangeFinished.connect(self.roiChangeFinishedEvent)
        self.roiChangedEvent()

    def paint(self, *args):
        pass

    def boundingRect(self):
        return QtCore.QRectF()

    def roiChangedEvent(self):
        # make sure that the inner radius is always less than the outer radius
        inner_roi = self.rois[0]
        outer_roi = self.rois[1]
        inner_size = inner_roi.size()
        outer_size = outer_roi.size()

        if inner_size.x() > outer_size.x():
            inner_roi.setSize(QtCore.QSizeF(outer_size.x(), inner_size.y()))
            inner_roi.setPos(outer_roi.pos())
        if inner_size.y() > outer_size.y():
            inner_roi.setSize(QtCore.QSizeF(inner_size.x(), outer_size.y()))
            inner_roi.setPos(outer_roi.pos())

        # track position of the two rois
        inner_roi.blockSignals(True)
        outer_roi.blockSignals(True)
        inner_size = inner_roi.size()
        outer_size = outer_roi.size()
        # center the inner roi within the outer roi
        inner_roi.setPos(
            outer_roi.pos()
            + QtCore.QPointF(
                (outer_size.x() - inner_size.x()) / 2,
                (outer_size.y() - inner_size.y()) / 2,
            )
        )

        inner_roi.blockSignals(False)
        outer_roi.blockSignals(False)

        self.sigRegionChanged.emit(self)

    def roiChangeStartedEvent(self):
        self.sigRegionChangeStarted.emit(self)

    def roiChangeFinishedEvent(self):
        self.sigRegionChangeFinished.emit(self)

    def getHandlePositions(self):
        """Return the positions of all handles in local coordinates."""
        pos = [self.mapFromScene(self.lines[0].getHandles()[0].scenePos())]
        for l in self.rois:
            pos.append(self.mapFromScene(l.getHandles()[1].scenePos()))
        return pos

    def getArrayRegion(self, arr, img=None, axes=(0, 1), **kwds):
        """
        Return the result of :meth:`~pyqtgraph.ROI.getArrayRegion` for each rect
        in the chain concatenated into a single ndarray.

        See :meth:`~pyqtgraph.ROI.getArrayRegion` for a description of the
        arguments.

        Note: ``returnMappedCoords`` is not yet supported for this ROI type.
        """
        rgns = []
        for l in self.rois:
            rgn = l.getArrayRegion(arr, img, axes=axes, **kwds)
            if rgn is None:
                continue
            rgns.append(rgn)

        ## make sure orthogonal axis is the same size
        if img.axisOrder == "row-major":
            axes = axes[::-1]
        ms = min([r.shape[axes[1]] for r in rgns])
        sl = [slice(None)] * rgns[0].ndim
        sl[axes[1]] = slice(0, ms)
        rgns = [r[tuple(sl)] for r in rgns]

        return np.concatenate(rgns, axis=axes[0])

    def addSegment(self, pos=(0, 0), radius=10):
        """
        Add a new segment to the ROI connecting from the previous endpoint to *pos*.
        (pos is specified in the parent coordinate system of the MultiRectROI)
        """

        ## create new ROI
        newRoi = CircleROI(
            pos, [radius, radius], parent=self, pen=self.pen, **self.roiArgs
        )
        newRoi.sigRegionChanged.connect(self.roiChangedEvent)
        newRoi.sigRegionChangeStarted.connect(self.roiChangeStartedEvent)
        newRoi.sigRegionChangeFinished.connect(self.roiChangeFinishedEvent)
        self.sigRegionChanged.emit(self)
        self.rois.append(newRoi)

    def pos(self):
        """Return the position of the first ROI as the position of the RingROI."""
        if self.rois:
            return self.rois[1].pos()
        else:
            return QtCore.QPointF(0, 0)

    def size(self):
        """Return the size of the outermost ROI as the size of the RingROI."""
        if self.rois:
            return self.rois[-1].size()
        else:
            return QtCore.QSizeF(0, 0)
