from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor, QIcon
from pathlib import Path
from spyde.drawing.toolbars.plot_control_toolbar import resolve_icon_path


class FramelessSubWindow(QtWidgets.QMdiSubWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._moving = False
        self._move_start = None
        self._resize_start = None

        self.title_bar = QtWidgets.QWidget(self)
        self.title_bar.setFixedHeight(30)
        self.title_bar.setMinimumHeight(30)
        self.title_bar.setMinimumWidth(200)
        self.title_bar.setStyleSheet(
            "background-color: #2b2b2b; "
            "border-top-left-radius: 6px; "
            "border-top-right-radius: 6px; "
            "QPushButton { background: transparent; border: none; border-radius: 4px; } "
            "QPushButton:hover { background-color: #3a3a3a; } "
            "QPushButton:pressed { background-color: #454545; }"
        )
        self.title_bar_layout = QtWidgets.QHBoxLayout(self.title_bar)
        self.title_bar_layout.setContentsMargins(0, 0, 0, 0)
        self.layout().setContentsMargins(0, 0, 0, 0)

        self.title_label = QtWidgets.QLabel("Custom Window", self.title_bar)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet("color: #ffffff;")
        self.title_bar_layout.addWidget(self.title_label)


        self.minimize_button = QtWidgets.QPushButton(self.title_bar)
        self._icon_minimize = QIcon(resolve_icon_path("qt/assets/icons/minimize.svg"))
        self._icon_maximize = QIcon(resolve_icon_path("qt/assets/icons/maximize.svg"))
        self._icon_close = QIcon(resolve_icon_path("qt/assets/icons/close.svg"))

        print("resolved icons", resolve_icon_path("qt/assets/icons/minimize.svg"))
        print(self._icon_minimize.isNull())

        self.minimize_button.setFixedSize(25, 25)
        self.minimize_button.clicked.connect(self.toggle_minimize)
        self.minimize_button.setIcon(self._icon_minimize)
        self.minimize_button.setIconSize(QtCore.QSize(16, 16))

        self.maximize_button = QtWidgets.QPushButton(self.title_bar)
        self.maximize_button.setIcon(self._icon_maximize)
        self.maximize_button.setCheckable(True)
        self.maximize_button.setChecked(False)
        self.maximize_button.setFixedSize(25, 25)
        self.maximize_button.clicked.connect(self.toggle_maximize)
        self.maximize_button.setIconSize(QtCore.QSize(16, 16))

        self.close_button = QtWidgets.QPushButton(self.title_bar)
        self.close_button.setIcon(self._icon_close)
        self.close_button.setFixedSize(25, 25)
        self.close_button.clicked.connect(self.close)
        self.close_button.setIconSize(QtCore.QSize(16, 16))

        self.title_bar.mousePressEvent = self.start_move
        self.title_bar.mouseMoveEvent = self.move_window
        self.title_bar.mouseReleaseEvent = self.end_move

        self.title_bar_layout.addWidget(self.minimize_button)
        self.title_bar_layout.addWidget(self.maximize_button)
        self.title_bar_layout.addWidget(self.close_button)
        self.title_bar_layout.setContentsMargins(0, 0, 5, 0)

        self.setLayout(QtWidgets.QVBoxLayout())
        self.layout().setContentsMargins(0, 0, 0, 0)
        self.layout().addWidget(self.title_bar)
        self.layout().setSpacing(0)
        self.old_size = self.size()
        self.is_minimized = False
        self.setMouseTracking(True)
        self.title_bar.setMouseTracking(True)
        self.title_label.setMouseTracking(True)
        self.setMouseTracking(True)
        self.plot_widget = None
        self.installEventFilter(self)
        for w in self.findChildren(QtWidgets.QWidget):
            w.installEventFilter(self)


        self._resizing_top = False
        self._resizing_bottom = False
        self._resizing_left = False
        self._resizing_right = False

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Type.MouseMove:
            self.mouseMoveEvent(event)
        elif event.type() == QtCore.QEvent.Type.MouseButtonPress:
            self.mousePressEvent(event)
        elif event.type() == QtCore.QEvent.Type.MouseButtonRelease:
            self.mouseReleaseEvent(event)
        return super().eventFilter(obj, event)

    def toggle_minimize(self):
        # Minimize the window
        if self.is_minimized:
            self.resize(self.old_size)
            self.is_minimized = False
        else:
            self.is_minimized = True
            self.old_size = self.size()
            self.resize(QtCore.QSize(300, 30))

    def toggle_maximize(self):
        # Toggle between maximized and normal window states
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    @property
    def resizing(self):
        return self._resizing_top or self._resizing_bottom or self._resizing_left or self._resizing_right

    def start_move(self, event):
        # Start dragging the window
        if event.button() == Qt.MouseButton.LeftButton and not self.resizing:
            self._moving = True
            self._move_start = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def move_window(self, event):
        # Move the window while dragging
        if self._moving:
            self.move(event.globalPosition().toPoint() - self._move_start)

    def end_move(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._moving = False
            # Snap back inside the MDI area if out of bounds
            container = None
            try:
                mdi = self.mdiArea()
                if mdi is not None:
                    container = mdi.viewport()
            except Exception:
                pass
            if container is None:
                container = self.parentWidget()
            if container is not None:
                pw, ph = container.width(), container.height()
                w, h = self.width(), self.height()
                max_x = max(0, pw - w)
                max_y = max(0, ph - h)
                new_x = min(max(self.x(), 0), max_x)
                new_y = min(max(self.y(), 0), max_y)
                if new_x != self.x() or new_y != self.y():
                    self.move(new_x, new_y)

    def mouseMoveEvent(self, event):
        margins = 7  # Resize margin
        rect = self.rect()

        # Map to local coords regardless of source widget
        gp = event.globalPosition().toPoint()
        pos = self.mapFromGlobal(gp)

        x, y = pos.x(), pos.y()
        w, h = rect.width(), rect.height()

        # Update cursor shape only when not resizing and only on change
        if not self.resizing:
            desired = Qt.CursorShape.ArrowCursor
            if x < margins and y < margins:
                desired = Qt.CursorShape.SizeFDiagCursor  # Top-left corner
            elif x > w - margins and y < margins:
                desired = Qt.CursorShape.SizeBDiagCursor  # Top-right corner
            elif x < margins and y > h - margins:
                desired = Qt.CursorShape.SizeBDiagCursor  # Bottom-left corner
            elif x > w - margins and y > h - margins:
                desired = Qt.CursorShape.SizeFDiagCursor  # Bottom-right corner
            elif x < margins:
                desired = Qt.CursorShape.SizeHorCursor  # Left edge
            elif x > w - margins:
                desired = Qt.CursorShape.SizeHorCursor  # Right edge
            elif y < margins:
                desired = Qt.CursorShape.SizeVerCursor  # Top edge
            elif y > h - margins:
                desired = Qt.CursorShape.SizeVerCursor  # Bottom edge

            if self.cursor().shape() != desired:
                self.setCursor(QCursor(desired))

        if self.resizing:
            # Non-incremental deltas from the press position
            gp = event.globalPosition().toPoint()
            dx = gp.x() - self._press_global_pos.x()
            dy = gp.y() - self._press_global_pos.y()

            # Skip if no delta to avoid redundant work
            if dx == 0 and dy == 0:
                return

            init_geo = self._initial_geo
            new_x, new_y = init_geo.x(), init_geo.y()
            new_width, new_height = init_geo.width(), init_geo.height()

            if self._resizing_top:
                new_y = init_geo.y() + dy
                new_height = init_geo.height() - dy
            if self._resizing_bottom:
                new_height = init_geo.height() + dy
            if self._resizing_left:
                new_x = init_geo.x() + dx
                new_width = init_geo.width() - dx
            if self._resizing_right:
                new_width = init_geo.width() + dx

            # Enforce minimum size with proper anchoring
            min_w, min_h = 50, 30
            if new_width < min_w:
                if self._resizing_left:
                    new_x = init_geo.x() + (init_geo.width() - min_w)
                new_width = min_w
            if new_height < min_h:
                if self._resizing_top:
                    new_y = init_geo.y() + (init_geo.height() - min_h)
                new_height = min_h

            # Avoid redundant geometry updates
            geo = self.geometry()
            if (new_x, new_y, new_width, new_height) == (geo.x(), geo.y(), geo.width(), geo.height()):
                return

            self.setUpdatesEnabled(False)
            try:
                self.setGeometry(new_x, new_y, new_width, new_height)
            finally:
                self.setUpdatesEnabled(True)

    def mousePressEvent(self, event):
        margins = 10  # Resize margin
        rect = self.rect()

        if event.button() == Qt.MouseButton.LeftButton:
            p = self.mapFromGlobal(event.globalPosition().toPoint())
            x, y = p.x(), p.y()
            w, h = rect.width(), rect.height()

            self._resizing_top = self._resizing_bottom = False
            self._resizing_left = self._resizing_right = False

            if x < margins and y < margins:
                self._resizing_top = True
                self._resizing_left = True  # Top-left corner
            elif x > w - margins and y < margins:
                self._resizing_top = True
                self._resizing_right = True  # Top-right corner
            elif x < margins and y > h - margins:
                self._resizing_bottom = True
                self._resizing_left = True  # Bottom-left corner
            elif x > w - margins and y > h - margins:
                self._resizing_bottom = True
                self._resizing_right = True  # Bottom-right corner
            elif x < margins:
                self._resizing_left = True
            elif x > w - margins:
                self._resizing_right = True
            elif y < margins:
                self._resizing_top = True
            elif y > h - margins:
                self._resizing_bottom = True

            if self.resizing:
                # Store starting global pos and geometry for non-incremental resizing
                self._press_global_pos = event.globalPosition().toPoint()
                self._initial_geo = self.geometry()

    def mouseReleaseEvent(self, event):
        # Stop resizing the window
        if event.button() == Qt.MouseButton.LeftButton:
            self._resizing_top = False
            self._resizing_bottom = False
            self._resizing_left = False
            self._resizing_right = False