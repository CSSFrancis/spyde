from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton, QGroupBox,
)
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPainter, QPainterPath, QRegion
import pyqtgraph as pg
import numpy as np


class CircularBorderOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.border_width = 2
        self.border_color = Qt.GlobalColor.white

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        size = min(self.width(), self.height())
        center_x = self.width() / 2
        center_y = self.height() / 2
        radius = size / 2

        pen = painter.pen()
        pen.setColor(self.border_color)
        pen.setWidth(self.border_width)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        border_offset = self.border_width / 2
        painter.drawEllipse(
            int(center_x - radius + border_offset),
            int(center_y - radius + border_offset),
            int(size - 2 * border_offset),
            int(size - 2 * border_offset)
        )


class CircularPlotWidget(QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        layout = QVBoxLayout(self)

        self.plot = pg.PlotWidget()
        self.plot.setAspectLocked(True)
        layout.addWidget(self.plot)

        self.overlay = CircularBorderOverlay(self)
        self._update_mask()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_mask()
        self.overlay.setGeometry(self.plot.geometry())

    def _update_mask(self):
        size = min(self.plot.width(), self.plot.height())
        center_x = self.plot.width() / 2
        center_y = self.plot.height() / 2
        radius = size / 2

        path = QPainterPath()
        path.addEllipse(center_x - radius, center_y - radius, size, size)

        region = QRegion(path.toFillPolygon().toPolygon())
        self.plot.setMask(region)

    def showEvent(self, event):
        super().showEvent(event)
        self._update_mask()
        self.overlay.setGeometry(self.plot.geometry())

class StageControlWidget(QGroupBox):
    def __init__(self,   parent=None):
        super().__init__(parent)

        self.setWindowTitle("Stage Control")

        self._stage_info = {
            "label": "Default",
            "notes": "",
            "user": "",
        }
        self.setTitle("Stage Control")

        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.plot_widget = CircularPlotWidget()
        self.plot_widget.setMinimumSize(75, 75)
        self.setMaximumWidth(300)
        self.setMaximumHeight(400)

        # create a circular image and display it inside the circular plot area
        size = 400
        xs = np.linspace(-1, 1, size)
        ys = np.linspace(-1, 1, size)
        xx, yy = np.meshgrid(xs, ys)
        rr = np.sqrt(xx ** 2 + yy ** 2)
        mask = rr <= 1.0

        img = np.zeros((size, size, 4), dtype=np.uint8)
        img[..., 0] = (255 * (1 - rr)).clip(0, 255)  # R
        img[..., 1] = (255 * rr).clip(0, 255)  # G
        img[..., 2] = 128  # B
        img[..., 3] = (255 * mask).astype(np.uint8)  # A: transparent outside circle

        self.image_item = pg.ImageItem(img)
        self.image_item.setRect(-1, -1, 2, 2)  # align image to radius=1 circle coordinates
        self.plot_widget.plot.addItem(self.image_item)
        self.plot_widget.plot.hideAxis('left')
        self.plot_widget.plot.hideAxis('bottom')


        main_layout.addWidget(self.plot_widget)

        # --- Stage position display (x, y, z, alpha, beta) ---
        position_layout = QHBoxLayout()
        self.x_label = QLabel("x: 0.000")
        self.y_label = QLabel("y: 0.000")
        self.z_label = QLabel("z: 0.000")
        self.alpha_label = QLabel("alpha: 0.000")
        self.beta_label = QLabel("beta: 0.000")

        for lbl in [
            self.x_label,
            self.y_label,
            self.z_label,
            self.alpha_label,
            self.beta_label,
        ]:
            lbl.setMinimumWidth(50)
            position_layout.addWidget(lbl)

        main_layout.addLayout(position_layout)

        # Buttons for collecting a montage and eucentric focus
        button_layout = QHBoxLayout()
        self.montage_button = QPushButton("Collect Montage")
        self.eucentric_button = QPushButton("Eucentric Focus")
        button_layout.addWidget(self.montage_button)
        button_layout.addWidget(self.eucentric_button)
        main_layout.addLayout(button_layout)
        self.setLayout(main_layout)
        # Connect buttons to dummy functions
        self.montage_button.clicked.connect(self.collect_montage)
        self.eucentric_button.clicked.connect(self.eucentric_focus)

    def collect_montage(self):
        """
        Montage collection routine.

        Returns
        -------

        """
        # wait 15 seconds to simulate montage collection
        # change button text to "Cancel Montage" during this time
        if self.montage_button.text() == "Cancel Montage":
            print("Montage collection cancelled.")
            self._cancel_montage()
            return
        else:
            print("Collecting montage... (dummy function)")
            self.montage_button.setText("Cancel Montage")
            QTimer.singleShot(15000, self._montage_complete)

    def _montage_complete(self):
        print("Montage collection complete.")
        self.montage_button.setText("Collect Montage")

    def _cancel_montage(self):
        print("Cancelling montage... (dummy function)")
        # Here you would add logic to actually cancel the montage process.
        self.montage_button.setText("Collect Montage")
        return

    def eucentric_focus(self):
        print("Performing eucentric focus... (dummy function)")
        # Here you would add logic to perform eucentric focusing.
        return




