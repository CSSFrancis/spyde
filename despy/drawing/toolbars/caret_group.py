from PySide6 import QtCore, QtGui, QtWidgets


class CaretGroup(QtWidgets.QGroupBox):
    """
    A polygonal QGroupBox with a centered triangular caret on one side,
    styled to match RoundedToolBar:
    - Smooth rounded corners
    - Translucent dark fill
    - Thin cosmetic light outline
    side: one of "top", "bottom", "left", "right"
    """
    def __init__(
        self,
        title: str = "",
        parent=None,
        side: str = "right",
        radius: int = 8,
        caret_base: int = 14,
        caret_depth: int = 8,
        border_width: int = 1,
        padding: int = 8,
        use_mask: bool = False,  # keep False for smooth edges
    ):
        super().__init__(title, parent)
        self._side = side
        self._radius = float(radius)
        self._carrot_base = int(caret_base)
        self._carrot_depth = int(caret_depth)
        self._border_width = float(border_width)
        self._padding = int(padding)
        self._use_mask = bool(use_mask)

        # Visuals to match RoundedToolBar
        self._bg_color = QtGui.QColor(50, 50, 50,
                                      200)  # 200 ≈ less transparent; use 255 for fully opaque
        self._pen_color = QtGui.QColor(255, 255, 255, 60)

        # Transparent background, no default frame
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFlat(True)
        self.setStyleSheet("QGroupBox { border: none; }")

        self._update_margins()
        self._update_mask()

    def set_side(self, side: str):
        if side not in ("top", "bottom", "left", "right"):
            return
        if self._side != side:
            self._side = side
            self._update_margins()
            self._update_mask()
            self.update()

    def set_use_mask(self, enabled: bool):
        """Enable only if you need precise hit‑testing; it will look more aliased."""
        self._use_mask = bool(enabled)
        self._update_mask()
        self.update()

    def sizeHint(self):
        base = super().sizeHint()
        if self._side in ("top", "bottom"):
            return QtCore.QSize(base.width(), base.height() + self._carrot_depth)
        else:
            return QtCore.QSize(base.width() + self._carrot_depth, base.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_mask()

    def _update_margins(self):
        l = r = t = b = self._padding
        if self._side == "top":
            t += self._carrot_depth
        elif self._side == "bottom":
            b += self._carrot_depth
        elif self._side == "left":
            l += self._carrot_depth
        else:  # right
            r += self._carrot_depth
        self.setContentsMargins(l, t, r, b)

    def _bubble_rect(self) -> QtCore.QRectF:
        # Sub‑pixel align for crisp 1px pen
        bw = self._border_width
        rect = QtCore.QRectF(self.rect()).adjusted(bw / 2.0, bw / 2.0, -bw / 2.0, -bw / 2.0)
        if self._side == "top":
            rect.adjust(0, self._carrot_depth, 0, 0)
        elif self._side == "bottom":
            rect.adjust(0, 0, 0, -self._carrot_depth)
        elif self._side == "left":
            rect.adjust(self._carrot_depth, 0, 0, 0)
        else:  # right
            rect.adjust(0, 0, -self._carrot_depth, 0)
        return rect

    def _caret_polygon(self, bubble: QtCore.QRectF) -> QtGui.QPolygonF:
        base = float(self._carrot_base)
        depth = float(self._carrot_depth)
        if self._side in ("top", "bottom"):
            cx = bubble.center().x()
            x1 = cx - base / 2.0
            x2 = cx + base / 2.0
            if self._side == "top":
                y = bubble.top()
                return QtGui.QPolygonF(
                    [QtCore.QPointF(x1, y), QtCore.QPointF(x2, y), QtCore.QPointF(cx, y - depth)]
                )
            else:
                y = bubble.bottom()
                return QtGui.QPolygonF(
                    [QtCore.QPointF(x1, y), QtCore.QPointF(x2, y), QtCore.QPointF(cx, y + depth)]
                )
        else:
            cy = bubble.center().y()
            y1 = cy - base / 2.0
            y2 = cy + base / 2.0
            if self._side == "left":
                x = bubble.left()
                return QtGui.QPolygonF(
                    [QtCore.QPointF(x, y1), QtCore.QPointF(x, y2), QtCore.QPointF(x - depth, cy)]
                )
            else:
                x = bubble.right()
                return QtGui.QPolygonF(
                    [QtCore.QPointF(x, y1), QtCore.QPointF(x, y2), QtCore.QPointF(x + depth, cy)]
                )

    def _path(self) -> QtGui.QPainterPath:
        bubble = self._bubble_rect()
        path = QtGui.QPainterPath()
        path.addRoundedRect(bubble, self._radius, self._radius)
        path.addPolygon(self._caret_polygon(bubble))
        return path.simplified()

    def _update_mask(self):
        # Mask is binary and causes aliasing; keep it off for smooth visuals.
        if self._use_mask:
            path = self._path()
            region = QtGui.QRegion(path.toFillPolygon().toPolygon())
            self.setMask(region)
        else:
            self.clearMask()

    def paintEvent(self, event: QtGui.QPaintEvent):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, True)

        path = self._path()

        # Fill to match RoundedToolBar
        p.setBrush(QtGui.QBrush(self._bg_color))

        # 1px cosmetic pen with round joins/caps for smoother edges
        pen = QtGui.QPen(self._pen_color)
        pen.setWidthF(self._border_width)
        pen.setCosmetic(True)
        pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        p.setPen(pen)

        p.drawPath(path)