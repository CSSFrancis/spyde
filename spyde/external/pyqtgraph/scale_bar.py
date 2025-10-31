from pyqtgraph import functions as fn  # to avoid linting error
from pyqtgraph import getConfigOption  # to avoid linting error
from pyqtgraph.Point import Point  # to avoid linting error
from pyqtgraph.Qt import QtCore, QtWidgets  # to avoid linting error
from pyqtgraph.graphicsItems.GraphicsObject import (
    GraphicsObject,
)  # to avoid linting error
from pyqtgraph.graphicsItems.GraphicsWidgetAnchor import (
    GraphicsWidgetAnchor,
)  # to avoid linting error
from pyqtgraph.graphicsItems.TextItem import TextItem  # to avoid linting error
import re


import html


def tex_to_html(s: str) -> str:
    """
    Render a tiny TeX subset to Qt rich text (HTML) that QTextDocument can display.
    - Converts ^ and _ into <sup>/<sub>.
    - Preserves plain text and escaped.
    Note: Qt does not support MathML; do not emit MathML here.
    """
    # match unescaped $...$ or $$...$$, non-greedy, across lines
    pattern = re.compile(r"(?<!\\)(\${1,2})(.+?)(?<!\\)\1", re.DOTALL)

    def simple_tex_to_html(tex: str) -> str:
        # escape HTML first, then inject sup/sub
        t = html.escape(tex)

        # superscripts with braces: x^{...}
        t = re.sub(r"([A-Za-z0-9\)\]\}])\^\{([^}]*)\}", r"\1<sup>\2</sup>", t)
        # superscripts single char: x^y or x^-
        t = re.sub(r"([A-Za-z0-9\)\]\}])\^([A-Za-z0-9\+\-\=])", r"\1<sup>\2</sup>", t)

        # subscripts with braces: x_{...}
        t = re.sub(r"([A-Za-z0-9\)\]\}])_\{([^}]*)\}", r"\1<sub>\2</sub>", t)
        # subscripts single char: x_y
        t = re.sub(r"([A-Za-z0-9\)\]\}])_([A-Za-z0-9])", r"\1<sub>\2</sub>", t)

        return t.replace("\n", "<br/>")

    parts: list[str] = []
    pos = 0

    for m in pattern.finditer(s):
        # plain text before the match
        plain = s[pos : m.start()].replace(r"\$", "$")
        parts.append(html.escape(plain).replace("\n", "<br/>"))

        # convert inline/block TeX to simple HTML
        tex = m.group(2)
        is_block = len(m.group(1)) == 2
        rendered = simple_tex_to_html(tex)
        if is_block:
            parts.append(
                f'<div style="display:block;text-align:center">{rendered}</div>'
            )
        else:
            parts.append(f'<span class="math">{rendered}</span>')

        pos = m.end()

    # trailing plain text
    tail = s[pos:].replace(r"\$", "$")
    parts.append(html.escape(tail).replace("\n", "<br/>"))

    return "".join(parts)


class OutlinedScaleBar(GraphicsWidgetAnchor, GraphicsObject):
    """
    Displays a rectangular bar to indicate the relative scale of objects on the view.


    """

    def __init__(
        self,
        size,
        width=5,
        brush=None,
        pen=None,
        border_pen=None,
        fill_brush=None,
        suffix="m",
        offset=None,
    ):
        GraphicsObject.__init__(self)
        GraphicsWidgetAnchor.__init__(self)
        self.setFlag(self.GraphicsItemFlag.ItemHasNoContents)
        self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)

        if brush is None:
            brush = getConfigOption("foreground")
        self.brush = fn.mkBrush(brush)
        self.pen = fn.mkPen(pen)

        self.text = TextItem(text="", anchor=(0.5, 1))

        new_text = f"{size} {suffix}"

        print(new_text)
        print(tex_to_html(new_text))

        self.text.setHtml(tex_to_html(new_text))
        self.text.setParentItem(self)
        self.text.setZValue(1)

        # Background styles for the bounding box (defaults are semi-transparent)
        if border_pen is None:
            border_pen = (0, 0, 0, 200)
        if fill_brush is None:
            fill_brush = (0, 0, 0, 100)
        self.bg_pen = fn.mkPen(border_pen)
        self.bg_brush = fn.mkBrush(fill_brush)

        self._width = width
        self.size = size
        if offset is None:
            offset = (0, 0)
        self.offset = offset

        self.background = QtWidgets.QGraphicsRectItem()
        self.background.setPen(self.bg_pen)
        self.background.setBrush(self.bg_brush)
        self.background.setParentItem(self)
        self.background.setZValue(-1)

        self.bar = QtWidgets.QGraphicsRectItem()
        self.bar.setPen(self.pen)
        self.bar.setBrush(self.brush)
        self.bar.setParentItem(self)
        self.bar.setZValue(0)
        # padding around the bounding box
        self._pad = 4

    def changeParent(self):
        view = self.parentItem()
        if view is None:
            return
        view.sigRangeChanged.connect(self.updateBar)
        self.updateBar()

    def updateBar(self):
        view = self.parentItem()
        if view is None:
            return
        p1 = view.mapFromViewToItem(self, QtCore.QPointF(0, 0))
        p2 = view.mapFromViewToItem(self, QtCore.QPointF(self.size, 0))
        w = (p2 - p1).x()
        self.bar.setRect(QtCore.QRectF(-w, 0, w, self._width))
        self.text.setPos(-w / 2.0, 0)

        # Update background to enclose both bar and text
        try:
            bar_rect = self.bar.mapRectToParent(self.bar.rect())
            text_rect = self.text.mapRectToParent(self.text.boundingRect())
            rect = bar_rect.united(text_rect).adjusted(
                -self._pad, -self._pad, self._pad, self._pad
            )
            self.background.setRect(rect)
        except Exception:
            pass

    def boundingRect(self):
        return QtCore.QRectF()

    def setParentItem(self, p):
        ret = GraphicsObject.setParentItem(self, p)
        if self.offset is not None:
            offset = Point(self.offset)
            anchorx = 1 if offset[0] <= 0 else 0
            anchory = 1 if offset[1] <= 0 else 0
            anchor = (anchorx, anchory)
            self.anchor(itemPos=anchor, parentPos=anchor, offset=offset)
        return ret
