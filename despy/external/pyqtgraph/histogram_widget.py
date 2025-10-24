"""
GraphicsWidget displaying an image histogram along with gradient editor. Can be used to
adjust the appearance of images.
"""


import weakref
from functools import partial

import numpy as np

from pyqtgraph import debug as debug
from pyqtgraph import functions as fn
from pyqtgraph.Point import Point
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets
from pyqtgraph import AxisItem
from pyqtgraph import GradientEditorItem
from pyqtgraph import GraphicsWidget
from pyqtgraph import LinearRegionItem
from pyqtgraph import PlotCurveItem
from pyqtgraph import ViewBox
from pyqtgraph import GraphicsView
__all__ = ['HistogramLUTItem','HistogramLUTWidget']


class HistogramLUTItem(GraphicsWidget):
    """
    :class:`~pyqtgraph.GraphicsWidget` with controls for adjusting the display of an
    :class:`~pyqtgraph.ImageItem`.

    Includes:

      - Image histogram
      - Movable region over the histogram to select black/white levels
      - Gradient editor to define color lookup table for single-channel images

    Parameters
    ----------
    image : pyqtgraph.ImageItem, optional
        If provided, control will be automatically linked to the image and changes to
        the control will be reflected in the image's appearance. This may also be set
        via :meth:`setImageItem`.
    fillHistogram : bool, optional
        By default, the histogram is rendered with a fill. Performance may be improved
        by disabling the fill. Additional control over the fill is provided by
        :meth:`fillHistogram`.
    levelMode : str, optional
        'mono' (default)
            One histogram with a :class:`~pyqtgraph.LinearRegionItem` is displayed to
            control the black/white levels of the image. This option may be used for
            color images, in which case the histogram and levels correspond to all
            channels of the image.
        'rgba'
            A histogram and level control pair is provided for each image channel. The
            alpha channel histogram and level control are only shown if the image
            contains an alpha channel.
    gradientPosition : str, optional
        Position of the gradient editor relative to the histogram. Must be one of
        {'right', 'left', 'top', 'bottom'}. 'right' and 'left' options should be used
        with a 'vertical' orientation; 'top' and 'bottom' options are for 'horizontal'
        orientation.
    orientation : str, optional
        The orientation of the axis along which the histogram is displayed. Either
        'vertical' (default) or 'horizontal'.
    autoLevel : bool, optional
        If True, the levels will be set automatically based on the image histogram
        whenever the image data changes. Default is True.
    constantLevel: bool, optional
        If True, the relative levels will be maintained when the image data changes.

    Attributes
    ----------
    sigLookupTableChanged : QtCore.Signal
        Emits the HistogramLUTItem itself when the gradient changes
    sigLevelsChanged : QtCore.Signal
        Emits the HistogramLUTItem itself while the movable region is changing
    sigLevelChangeFinished : QtCore.Signal
        Emits the HistogramLUTItem itself when the movable region is finished changing

    See Also
    --------
    :class:`~pyqtgraph.ImageItem`
        HistogramLUTItem is most useful when paired with an ImageItem.
    :class:`~pyqtgraph.ImageView`
        Widget containing a paired ImageItem and HistogramLUTItem.
    :class:`~pyqtgraph.HistogramLUTWidget`
        QWidget containing a HistogramLUTItem for widget-based layouts.
    """

    sigLookupTableChanged = QtCore.Signal(object)
    sigLevelsChanged = QtCore.Signal(object)
    sigLevelChangeFinished = QtCore.Signal(object)

    def __init__(self, image=None, fillHistogram=True, levelMode='mono',
                 gradientPosition='right', orientation='vertical',
                 autoLevel=True, constantLevel=False):
        GraphicsWidget.__init__(self)
        self.bins = None
        self.counts = None
        self.lut = None
        self.imageItem = lambda: None  # fake a dead weakref
        self.levelMode = levelMode
        self.orientation = orientation
        self.gradientPosition = gradientPosition


        if orientation == 'vertical' and gradientPosition not in {'right', 'left'}:
            self.gradientPosition = 'right'
        elif orientation == 'horizontal' and gradientPosition not in {'top', 'bottom'}:
            self.gradientPosition = 'bottom'

        self.layout = QtWidgets.QGraphicsGridLayout()
        self.setLayout(self.layout)
        self.layout.setContentsMargins(1, 1, 1, 1)
        self.layout.setSpacing(0)

        self.vb = ViewBox(parent=self)
        if self.orientation == 'vertical':
            self.vb.setMaximumWidth(152)
            self.vb.setMinimumWidth(45)
            self.vb.setMouseEnabled(x=False, y=True)
        else:
            self.vb.setMaximumHeight(152)
            self.vb.setMinimumHeight(45)
            self.vb.setMouseEnabled(x=True, y=False)

        self.gradient = GradientEditorItem(orientation=self.gradientPosition)
        self.gradient.loadPreset('grey')

        # LinearRegionItem orientation refers to the bounding lines
        regionOrientation = 'horizontal' if self.orientation == 'vertical' else 'vertical'
        self.regions = [
            # single region for mono levelMode
            LinearRegionItem([0, 1], regionOrientation, swapMode='block'),
            # r/g/b/a regions for rgba levelMode
            LinearRegionItem([0, 1], regionOrientation, swapMode='block', pen='r',
                             brush=fn.mkBrush((255, 50, 50, 50)), span=(0., 1/3.)),
            LinearRegionItem([0, 1], regionOrientation, swapMode='block', pen='g',
                             brush=fn.mkBrush((50, 255, 50, 50)), span=(1/3., 2/3.)),
            LinearRegionItem([0, 1], regionOrientation, swapMode='block', pen='b',
                             brush=fn.mkBrush((50, 50, 255, 80)), span=(2/3., 1.)),
            LinearRegionItem([0, 1], regionOrientation, swapMode='block', pen='w',
                             brush=fn.mkBrush((255, 255, 255, 50)), span=(2/3., 1.))
        ]
        self.region = self.regions[0]  # for backward compatibility.
        for region in self.regions:
            region.setZValue(1000)
            self.vb.addItem(region)
            region.lines[0].addMarker('<|', 0.5)
            region.lines[1].addMarker('|>', 0.5)
            region.sigRegionChanged.connect(self.regionChanging)
            region.sigRegionChangeFinished.connect(self.regionChanged)

        # gradient position to axis orientation
        ax = {'left': 'right', 'right': 'left',
              'top': 'bottom', 'bottom': 'top'}[self.gradientPosition]
        self.axis = AxisItem(ax, linkView=self.vb, maxTickLength=-10, parent=self)

        # axis / viewbox / gradient order in the grid
        avg = (0, 1, 2) if self.gradientPosition in {'right', 'bottom'} else (2, 1, 0)
        if self.orientation == 'vertical':
            self.layout.addItem(self.axis, 0, avg[0])
            self.layout.addItem(self.vb, 0, avg[1])
            self.layout.addItem(self.gradient, 0, avg[2])
        else:
            self.layout.addItem(self.axis, avg[0], 0)
            self.layout.addItem(self.vb, avg[1], 0)
            self.layout.addItem(self.gradient, avg[2], 0)

        self.gradient.setFlag(self.gradient.GraphicsItemFlag.ItemStacksBehindParent)
        self.vb.setFlag(self.gradient.GraphicsItemFlag.ItemStacksBehindParent)

        self.gradient.sigGradientChanged.connect(self.gradientChanged)
        self.vb.sigRangeChanged.connect(self.viewRangeChanged)

        comp = QtGui.QPainter.CompositionMode.CompositionMode_Plus
        self.plots = [
            PlotCurveItem(pen=(200, 200, 200, 100)),  # mono
            PlotCurveItem(pen=(255, 0, 0, 100), compositionMode=comp),  # r
            PlotCurveItem(pen=(0, 255, 0, 100), compositionMode=comp),  # g
            PlotCurveItem(pen=(0, 0, 255, 100), compositionMode=comp),  # b
            PlotCurveItem(pen=(200, 200, 200, 100), compositionMode=comp),  # a
        ]
        self.plot = self.plots[0]  # for backward compatibility.
        for plot in self.plots:
            if self.orientation == 'vertical':
                plot.setRotation(90)
            self.vb.addItem(plot)

        self.fillHistogram(fillHistogram)
        self._showRegions()
        self.autoLevel = autoLevel
        self.constantLevel = constantLevel
        self.autoHistogramRange()

        self._imageChangedDebounceMs = 35
        self._imageChangedTimer = QtCore.QTimer(self)
        self._imageChangedTimer.setSingleShot(True)
        self._imageChangedTimer.setInterval(self._imageChangedDebounceMs)
        self._pendingImageChange = {
            'autoLevel': False,
            'autoRange': False,
            'min_percentile': None,
            'max_percentile': None,
        }
        self._imageChangedTimer.timeout.connect(self._processImageChanged)

        if image is not None:
            self.setImageItem(image)

    def fillHistogram(self, fill=True, level=0.0, color=(100, 100, 200)):
        """Control fill of the histogram curve(s).

        Parameters
        ----------
        fill : bool, optional
            Set whether or not the histogram should be filled.
        level : float, optional
            Set the fill level. See :meth:`PlotCurveItem.setFillLevel
            <pyqtgraph.PlotCurveItem.setFillLevel>`. Only used if ``fill`` is True.
        color : color_like, optional
            Color to use for the fill when the histogram ``levelMode == "mono"``. See
            :meth:`PlotCurveItem.setBrush <pyqtgraph.PlotCurveItem.setBrush>`.
        """
        colors = [color, (255, 0, 0, 50), (0, 255, 0, 50), (0, 0, 255, 50), (255, 255, 255, 50)]
        for color, plot in zip(colors, self.plots):
            if fill:
                plot.setFillLevel(level)
                plot.setBrush(color)
            else:
                plot.setFillLevel(None)

    def paint(self, p, *args):
        # paint the bounding edges of the region item and gradient item with lines
        # connecting them
        if self.levelMode != 'mono' or not self.region.isVisible():
            return

        pen = self.region.lines[0].pen

        mn, mx = self.getLevels()
        vbc = self.vb.viewRect().center()
        gradRect = self.gradient.mapRectToParent(self.gradient.gradRect.rect())
        if self.orientation == 'vertical':
            p1mn = self.vb.mapFromViewToItem(self, Point(vbc.x(), mn)) + Point(0, 5)
            p1mx = self.vb.mapFromViewToItem(self, Point(vbc.x(), mx)) - Point(0, 5)
            if self.gradientPosition == 'right':
                p2mn = gradRect.bottomLeft()
                p2mx = gradRect.topLeft()
            else:
                p2mn = gradRect.bottomRight()
                p2mx = gradRect.topRight()
        else:
            p1mn = self.vb.mapFromViewToItem(self, Point(mn, vbc.y())) - Point(5, 0)
            p1mx = self.vb.mapFromViewToItem(self, Point(mx, vbc.y())) + Point(5, 0)
            if self.gradientPosition == 'bottom':
                p2mn = gradRect.topLeft()
                p2mx = gradRect.topRight()
            else:
                p2mn = gradRect.bottomLeft()
                p2mx = gradRect.bottomRight()

        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        for pen in [fn.mkPen((0, 0, 0, 100), width=3), pen]:
            p.setPen(pen)

            # lines from the linear region item bounds to the gradient item bounds
            p.drawLine(p1mn, p2mn)
            p.drawLine(p1mx, p2mx)

            # lines bounding the edges of the gradient item
            if self.orientation == 'vertical':
                p.drawLine(gradRect.topLeft(), gradRect.topRight())
                p.drawLine(gradRect.bottomLeft(), gradRect.bottomRight())
            else:
                p.drawLine(gradRect.topLeft(), gradRect.bottomLeft())
                p.drawLine(gradRect.topRight(), gradRect.bottomRight())

    def setHistogramRange(self, mn, mx, padding=0.1):
        """Set the X/Y range on the histogram plot, depending on the orientation. This disables auto-scaling."""
        if self.orientation == 'vertical':
            self.vb.enableAutoRange(self.vb.YAxis, False)
            self.vb.setYRange(mn, mx, padding)
        else:
            self.vb.enableAutoRange(self.vb.XAxis, False)
            self.vb.setXRange(mn, mx, padding)

    def getHistogramRange(self):
        """Returns range on the histogram plot."""
        if self.orientation == 'vertical':
            return self.vb.viewRange()[1]
        else:
            return self.vb.viewRange()[0]

    def autoHistogramRange(self):
        """Enable auto-scaling on the histogram plot."""
        self.vb.enableAutoRange(self.vb.XYAxes)

    def disableAutoHistogramRange(self):
        """Disable auto-scaling on the histogram plot."""
        self.vb.disableAutoRange(self.vb.XYAxes)

    def setImageItem(self, img, min_percentile=None, max_percentile=None):
        """Set an ImageItem to have its levels and LUT automatically controlled by this
        HistogramLUTItem.
        """
        self.imageItem = weakref.ref(img)
        if hasattr(img, 'sigImageChanged'):
            image_changed_funct = partial(self.imageChanged, autoLevel=self.autoLevel)
            img.sigImageChanged.connect(image_changed_funct)
        self._setImageLookupTable()
        self.imageChanged(autoLevel=False,
                          min_percentile=min_percentile,
                          max_percentile=max_percentile)

    @QtCore.Slot()
    def viewRangeChanged(self):
        self.update()

    @QtCore.Slot()
    def gradientChanged(self):
        if self.imageItem() is not None:
            self._setImageLookupTable()

        self.lut = None
        self.sigLookupTableChanged.emit(self)

    def _setImageLookupTable(self):
        if self.gradient.isLookupTrivial():
            self.imageItem().setLookupTable(None)
        else:
            self.imageItem().setLookupTable(self.getLookupTable)

    def getLookupTable(self, img=None, n=None, alpha=None):
        """Return a lookup table from the color gradient defined by this
        HistogramLUTItem.
        """
        if self.levelMode != 'mono':
            return None
        if n is None:
            if img.dtype == np.uint8:
                n = 256
            else:
                n = 512
        if self.lut is None:
            self.lut = self.gradient.getLookupTable(n, alpha=alpha)
        return self.lut

    @QtCore.Slot()
    def regionChanged(self):
        if self.imageItem() is not None:
            self.imageItem().setLevels(self.getLevels())
        self.sigLevelChangeFinished.emit(self)

    @QtCore.Slot()
    def regionChanging(self):
        if self.imageItem() is not None:
            self.imageItem().setLevels(self.getLevels())
        self.update()
        self.sigLevelsChanged.emit(self)

    @QtCore.Slot()
    def imageChanged(self,
                     autoLevel=False,
                     autoRange=False,
                     min_percentile=None,
                     max_percentile=None,):
        if self.imageItem() is None:
            return

        # Store latest args and restart debounce timer
        self._pendingImageChange.update({
            'autoLevel': autoLevel,
            'autoRange': autoRange,
            'min_percentile': min_percentile,
            'max_percentile': max_percentile,
        })
        self._imageChangedTimer.start()

    def _processImageChanged(self):

        if self.imageItem() is None:
            return

        autoLevel = self._pendingImageChange.get('autoLevel', False)
        autoRange = self._pendingImageChange.get('autoRange', False)
        min_percentile = self._pendingImageChange.get('min_percentile', None)
        max_percentile = self._pendingImageChange.get('max_percentile', None)

        if self.levelMode == 'mono':
            for plt in self.plots[1:]:
                plt.setVisible(False)
            self.plots[0].setVisible(True)
            # plot one histogram for all image data
            profiler = debug.Profiler()
            h = self.imageItem().getHistogram()
            self.bins = h[0]
            self.counts = h[1]
            profiler('get histogram')
            if h[0] is None:
                return
            self.plot.setData(*h)
            profiler('set plot')
            if autoLevel:
                mn = h[0][0]
                mx = h[0][-1]
                self.region.setRegion([mn, mx])
                profiler('set region')
            elif min_percentile is not None and max_percentile is not None:
                mn, mx = self.get_percentile_levels(min_percentile, max_percentile)
                self.region.setRegion([mn, mx])
                profiler('set region by percentile')
            else:
                mn, mx = self.imageItem().getLevels()
                self.region.setRegion([mn, mx])
        else:
            # plot one histogram for each channel
            self.plots[0].setVisible(False)
            ch = self.imageItem().getHistogram(perChannel=True)
            if ch[0] is None:
                return
            for i in range(1, 5):
                if len(ch) >= i:
                    h = ch[i-1]
                    self.plots[i].setVisible(True)
                    self.plots[i].setData(*h)
                    if autoLevel:
                        mn = h[0][0]
                        mx = h[0][-1]
                        self.regions[i].setRegion([mn, mx])
                else:
                    # hide channels not present in image data
                    self.plots[i].setVisible(False)
            # make sure we are displaying the correct number of channels
            self._showRegions()

    def levels2percentile(self, min_percentile, max_percentile):
        """Get levels based on percentiles of the image histogram.

        Parameters
        ----------
        min_percentile : float
            Minimum percentile (0-100).
        max_percentile : float
            Maximum percentile (0-100).

        Returns
        -------
        levels : tuple
            (min, max) levels corresponding to the requested percentiles.
        """
        if self.bins is None or self.counts is None:
            return None

        cumsum = np.cumsum(self.counts)
        total = cumsum[-1]
        low_idx = np.searchsorted(cumsum, (min_percentile / 100.0) * total)
        high_idx = np.searchsorted(cumsum, (max_percentile / 100.0) * total)

        min_level = self.bins[low_idx] if low_idx < len(self.bins) else self.bins[-1]
        max_level = self.bins[high_idx] if high_idx < len(self.bins) else self.bins[-1]

        return (min_level, max_level)

    def get_percentile_levels(self):
        """From the current levels, get the corresponding percentiles."""
        if self.bins is None or self.counts is None:
            return None

        mn, mx = self.getLevels()
        cumsum = np.cumsum(self.counts)
        total = cumsum[-1]

        low_idx = np.searchsorted(self.bins, mn)
        high_idx = np.searchsorted(self.bins, mx)

        min_percentile = (cumsum[low_idx] / total) * 100.0 if low_idx < len(cumsum) else 100.0
        max_percentile = (cumsum[high_idx] / total) * 100.0 if high_idx < len(cumsum) else 100.0

        return (min_percentile, max_percentile)

    def getLevels(self):
        """Return the min and max levels.

        For rgba mode, this returns a list of the levels for each channel.
        """
        if self.levelMode == 'mono':
            return self.region.getRegion()
        else:
            nch = self.imageItem().channels()
            if nch is None:
                nch = 3
            return [r.getRegion() for r in self.regions[1:nch+1]]

    def setLevels(self, min=None, max=None, rgba=None):
        """Set the min/max (bright and dark) levels.

        Parameters
        ----------
        min : float, optional
            Minimum level.
        max : float, optional
            Maximum level.
        rgba : list, optional
            Sequence of (min, max) pairs for each channel for 'rgba' mode.
        """
        if None in {min, max} and (rgba is None or None in rgba[0]):
            raise ValueError("Must specify min and max levels")

        if self.levelMode == 'mono':
            if min is None:
                min, max = rgba[0]
            self.region.setRegion((min, max))
        else:
            if rgba is None:
                rgba = 4*[(min, max)]
            for levels, region in zip(rgba, self.regions[1:]):
                region.setRegion(levels)

    def setLevelMode(self, mode):
        """Set the method of controlling the image levels offered to the user.

        Options are 'mono' or 'rgba'.
        """
        if mode not in {'mono', 'rgba'}:
            raise ValueError(f"Level mode must be one of {{'mono', 'rgba'}}, got {mode}")

        if mode == self.levelMode:
            return

        oldLevels = self.getLevels()
        self.levelMode = mode
        self._showRegions()

        # do our best to preserve old levels
        if mode == 'mono':
            levels = np.array(oldLevels).mean(axis=0)
            self.setLevels(*levels)
        else:
            levels = [oldLevels] * 4
            self.setLevels(rgba=levels)

        # force this because calling self.setLevels might not set the imageItem
        # levels if there was no change to the region item
        if self.imageItem() is not None:
            self.imageItem().setLevels(self.getLevels())

        self.imageChanged(autoLevel=self.autoLevel)
        self.update()

    def _showRegions(self):
        for i in range(len(self.regions)):
            self.regions[i].setVisible(False)

        if self.levelMode == 'rgba':
            nch = 4
            if self.imageItem() is not None:
                # Only show rgb channels if connected image lacks alpha.
                nch = self.imageItem().channels()
                if nch is None:
                    nch = 3
            xdif = 1.0 / nch
            for i in range(1, nch+1):
                self.regions[i].setVisible(True)
                self.regions[i].setSpan((i-1) * xdif, i * xdif)
            self.gradient.hide()
        elif self.levelMode == 'mono':
            self.regions[0].setVisible(True)
            self.gradient.show()
        else:
            raise ValueError(f"Unknown level mode {self.levelMode}")

    def saveState(self):
        return {
            'gradient': self.gradient.saveState(),
            'levels': self.getLevels(),
            'mode': self.levelMode,
        }

    def restoreState(self, state):
        if 'mode' in state:
            self.setLevelMode(state['mode'])
        self.gradient.restoreState(state['gradient'])
        self.setLevels(*state['levels'])


"""
Widget displaying an image histogram along with gradient editor. Can be used to adjust
the appearance of images. This is a wrapper around HistogramLUTItem
"""


class HistogramLUTWidget(GraphicsView):
    """QWidget wrapper for :class:`~pyqtgraph.HistogramLUTItem`.

    All parameters are passed along in creating the HistogramLUTItem.
    """

    def __init__(self, parent=None, *args, **kargs):
        background = kargs.pop('background', 'default')
        GraphicsView.__init__(self, parent, useOpenGL=False, background=background)
        self.item = HistogramLUTItem(*args, **kargs)
        self.setCentralItem(self.item)

        self.orientation = kargs.get('orientation', 'vertical')
        if self.orientation == 'vertical':
            self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Expanding)
            self.setMinimumWidth(95)
        else:
            self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
            self.setMinimumHeight(95)

    def sizeHint(self):
        if self.orientation == 'vertical':
            return QtCore.QSize(115, 200)
        else:
            return QtCore.QSize(200, 115)

    def __getattr__(self, attr):
        return getattr(self.item, attr)