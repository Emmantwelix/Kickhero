"""Widgets that keep pages fitting on small screens: a page stack sized by the page on show,
labels that shorten long text with "...", and a row of buttons that wraps onto more lines."""

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLabel, QLayout, QSizePolicy, QStackedWidget, QWidget, QWidgetItem


class PageStack(QStackedWidget):
    """A QStackedWidget that only needs room for the page on show (a plain one needs room for
    its widest page, so one long song title on a hidden page could push the window off screen)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.currentChanged.connect(lambda _: self.updateGeometry())

    def sizeHint(self):
        page = self.currentWidget()
        return page.sizeHint() if page else super().sizeHint()

    def minimumSizeHint(self):
        page = self.currentWidget()
        return page.minimumSizeHint() if page else super().minimumSizeHint()


class ElidedLabel(QLabel):
    """One line of text that shortens to "..." instead of making the window wider."""

    def __init__(self, text="", **kwargs):
        super().__init__(**kwargs)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setText(text)

    def setText(self, text):
        self._full = text or ""
        self.setToolTip(self._full if self.fontMetrics().horizontalAdvance(self._full) > self.width() else "")
        self._elide()
        self.updateGeometry()

    def text(self):
        return self._full

    def sizeHint(self):
        m = self.contentsMargins()
        return QSize(self.fontMetrics().horizontalAdvance(self._full) + m.left() + m.right() + 4,
                     super().sizeHint().height())

    def minimumSizeHint(self):
        return QSize(min(60, self.sizeHint().width()), super().minimumSizeHint().height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide()

    def _elide(self):
        m = self.contentsMargins()
        width = self.width() - m.left() - m.right()
        shown = self.fontMetrics().elidedText(self._full, Qt.ElideRight, max(0, width))
        self.setToolTip(self._full if shown != self._full else "")
        QLabel.setText(self, shown)


class FlowRow(QWidget):
    """A row of widgets that wraps onto further lines when the page is too narrow for it."""

    def __init__(self, spacing=8, parent=None):
        super().__init__(parent)
        self.flow = _FlowLayout(self, spacing)

    def addWidget(self, w):
        self.flow.addWidget(w)

    def addSpacing(self, px):
        spacer = QWidget(self)
        spacer.setFixedSize(px, 1)
        self.flow.addWidget(spacer)


class _FlowLayout(QLayout):
    def __init__(self, parent, spacing):
        super().__init__(parent)
        self.setContentsMargins(0, 0, 0, 0)
        self._items = []
        self._gap = spacing

    def addItem(self, item):
        self._items.append(item)

    def addWidget(self, w):
        self.addChildWidget(w)
        self.addItem(QWidgetItem(w))

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._place(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, move=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            if not item.isEmpty():
                size = size.expandedTo(item.minimumSize())
        return size

    def _place(self, rect, move):
        """Lay the items out in lines (each item centred on its line); returns the height used."""
        lines, line, x = [], [], rect.x()
        for item in self._items:
            if item.isEmpty():
                continue
            w = item.sizeHint().width()
            if line and x + w > rect.right() + 1:
                lines.append(line)
                line, x = [], rect.x()
            line.append(item)
            x += w + self._gap
        if line:
            lines.append(line)
        y = rect.y()
        for line in lines:
            line_h = max(item.sizeHint().height() for item in line)
            x = rect.x()
            for item in line:
                hint = item.sizeHint()
                if move:
                    item.setGeometry(QRect(QPoint(x, y + (line_h - hint.height()) // 2), hint))
                x += hint.width() + self._gap
            y += line_h + self._gap
        return max(0, y - self._gap - rect.y())
