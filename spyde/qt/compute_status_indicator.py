from PySide6 import QtWidgets, QtCore, QtGui


class ComputeStatusIndicator(QtWidgets.QWidget):
    """24×24 px transparent overlay showing computation progress.

    States:
      idle      — small filled green circle
      computing — grey ring; clockwise arc fills proportional to completed/total tasks
      done      — fully filled green circle; auto-transitions to idle after 500 ms
    """

    SIZE = 24

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self._state = "idle"
        self._total_tasks = 1
        self._completed_tasks = 0
        self._done_timer = QtCore.QTimer(self)
        self._done_timer.setSingleShot(True)
        self._done_timer.timeout.connect(self.set_idle)

    def set_idle(self):
        self._state = "idle"
        self._done_timer.stop()
        self.update()

    def set_computing(self, total_tasks: int = 1):
        self._state = "computing"
        self._total_tasks = max(1, total_tasks)
        self._completed_tasks = 0
        self._done_timer.stop()
        self.update()

    def set_done(self):
        self._state = "done"
        self.update()
        self._done_timer.start(500)

    def update_progress(self, completed: int):
        if self._state != "computing":
            return
        self._completed_tasks = completed
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        cx, cy, r = self.SIZE / 2, self.SIZE / 2, self.SIZE / 2 - 3

        if self._state == "idle":
            small_r = r * 0.4
            painter.setBrush(QtGui.QColor(0, 200, 0))
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.drawEllipse(
                QtCore.QRectF(cx - small_r, cy - small_r, small_r * 2, small_r * 2)
            )

        elif self._state == "computing":
            pen = QtGui.QPen(QtGui.QColor(120, 120, 120), 3)
            painter.setPen(pen)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            rect = QtCore.QRectF(cx - r, cy - r, r * 2, r * 2)
            painter.drawEllipse(rect)
            frac = self._completed_tasks / self._total_tasks
            span = int(frac * 360 * 16)
            if span > 0:
                arc_pen = QtGui.QPen(QtGui.QColor(0, 200, 0), 3)
                painter.setPen(arc_pen)
                painter.drawArc(rect, 90 * 16, -span)  # negative = clockwise

        elif self._state == "done":
            painter.setBrush(QtGui.QColor(0, 200, 0))
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.drawEllipse(QtCore.QRectF(cx - r, cy - r, r * 2, r * 2))

        painter.end()
