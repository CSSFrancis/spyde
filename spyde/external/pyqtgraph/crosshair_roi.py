from pyqtgraph import ROI
from PySide6 import QtCore

class CrosshairROI(ROI):
    """A crosshair (+) shaped ROI with adjustable arm lengths that stays constant size when zooming."""

    def __init__(self, pos, pixel_size=10, view=None, **kwargs):
        if 'size' in kwargs:
            kwargs.pop('size')
        super().__init__(pos, [pixel_size, pixel_size], **kwargs)
        self.pixel_size = pixel_size  # Size in pixels
        self.view = view  # ViewBox reference

        # Remove default handle
        for h in self.getHandles():
            self.removeHandle(h)

        # Add handle at center to move the crosshair
        #self.addTranslateHandle([0.5, 0.5])
        self.scene_size = pixel_size*20  # Initial size in data units
        # Connect to view range changes to maintain constant pixel size
        if self.view is not None:
            self.view.sigRangeChanged.connect(self._update_for_zoom)
            self._update_for_zoom()

        self.size_value = pixel_size  # Store current size in data units

    def _update_for_zoom(self):
        """Update size based on current zoom level to maintain constant pixel size."""
        if self.view is None:
            return

        # Get the current view range
        view_rect = self.view.viewRect()
        view_width = view_rect.width()
        view_height = view_rect.height()

        # Get widget size in pixels
        widget_width = self.view.width()
        widget_height = self.view.height()

        if widget_width == 0 or widget_height == 0:
            return

        # Calculate data units per pixel
        units_per_pixel_x = view_width / widget_width
        units_per_pixel_y = view_height / widget_height

        # Set size to maintain constant pixel size
        scene_size = max(units_per_pixel_x, units_per_pixel_y) * self.pixel_size
        self.scene_size = scene_size
        self.setSize([scene_size, scene_size], finish=False)
        self.size_value = scene_size

    def paint(self, p, *args):
        """Draw a + shape with a small square in the center."""
        pen = self.currentPen
        p.setPen(pen)

        size = self.size_value
        center = size / 2

        # Draw vertical line
        p.drawLine(QtCore.QPointF(center, 0), QtCore.QPointF(center, size))
        # Draw horizontal line
        p.drawLine(QtCore.QPointF(0, center), QtCore.QPointF(size, center))

        # Draw small square in center (10% of total size)
        square_size = size * 0.1
        half_square = square_size / 2
        p.drawRect(QtCore.QRectF(
            center - half_square,
            center - half_square,
            square_size,
            square_size
        ))

    def set_pixel_size(self, pixel_size):
        """Adjust the crosshair pixel size."""
        self.pixel_size = pixel_size
        self._update_for_zoom()
        self.update()

    def boundingRect(self):
        """Return the bounding rectangle for the crosshair, accounting for pen width."""
        # Use size_value which is always initialized, fallback to pixel_size
        size = getattr(self, 'size_value', self.pixel_size * 20)

        # Add padding for pen width to avoid clipping
        pen_width = self.pen.width() if hasattr(self, 'pen') else 1
        padding = pen_width / 2

        return QtCore.QRectF(-padding, -padding, size + 2 * padding, size + 2 * padding)