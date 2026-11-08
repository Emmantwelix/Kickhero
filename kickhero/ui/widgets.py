"""Small reusable widgets in the app's style: segmented control, icon buttons and toggles, accuracy ring,
popover panel, card grid, sparkline, filter chips."""

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QFont, QGuiApplication, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from . import theme
from .drawing import icon, qc

SEGMENT_CSS = f"""
QFrame#segment {{ background: {theme.PANEL_2}; border: 1px solid {theme.BORDER}; border-radius: 10px; }}
QFrame#segment QPushButton {{
    background: transparent; border: 1px solid transparent; border-radius: 7px; padding: 5px 12px;
    color: {theme.MUTED}; font-weight: 600;
}}
QFrame#segment QPushButton:hover {{ color: {theme.TEXT}; background: {theme.SURFACE_3}; }}
QFrame#segment QPushButton:checked {{ background: {theme.ACCENT_SOFT}; border-color: {theme.ACCENT}; color: #ffffff; }}
QFrame#segment QPushButton:disabled {{ color: {theme.FAINT}; background: transparent; border-color: transparent; }}
QFrame#segment QPushButton:checked:disabled {{ background: {theme.SURFACE_3}; border-color: {theme.SURFACE_3}; }}
"""


class HoverFade(QObject):
    """A widget's hover as a value that eases between 0 and 1 (`t`), so painted cards fade their hover look in
    and out instead of snapping. The widget repaints as it changes."""

    MS = 160

    def __init__(self, widget):
        super().__init__(widget)
        self.widget, self.t = widget, 0.0
        self.anim = QVariantAnimation(self, duration=self.MS, easingCurve=QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(self._set)
        widget.installEventFilter(self)

    def _set(self, v):
        self.t = float(v)
        self.widget.update()

    def eventFilter(self, obj, e):
        if e.type() in (QEvent.Enter, QEvent.Leave):
            self.anim.stop()
            self.anim.setStartValue(self.t)
            self.anim.setEndValue(1.0 if e.type() == QEvent.Enter else 0.0)
            self.anim.setDuration(round(self.MS * abs((1.0 if e.type() == QEvent.Enter else 0.0) - self.t)) or 1)
            self.anim.start()
        return False


def state_icon(name, size=16, off=theme.MUTED, on=theme.TEXT):
    """An icon that is muted when off and bright when checked or hovered."""
    ic = QIcon()
    ic.addPixmap(icon(name, off, size), QIcon.Normal, QIcon.Off)
    ic.addPixmap(icon(name, on, size), QIcon.Normal, QIcon.On)
    ic.addPixmap(icon(name, on, size), QIcon.Active, QIcon.Off)
    ic.addPixmap(icon(name, theme.FAINT, size), QIcon.Disabled, QIcon.Off)
    return ic


def icon_button(name, text="", tip="", checkable=False, checked=False, flat=False, size=16):
    """A button with a line icon (and optional label); checkable ones work as toggles."""
    b = QPushButton(text)
    b.setIcon(state_icon(name, size))
    b.setIconSize(QSize(size, size))
    b.setToolTip(tip)
    b.setCheckable(checkable)
    b.setChecked(checked)
    b.setFocusPolicy(Qt.NoFocus)
    b.setCursor(Qt.PointingHandCursor)
    if flat:
        b.setObjectName("flat")
    return b


class Segmented(QFrame):
    """A row of mutually exclusive options in one rounded track (e.g. Slow | Medium | Normal | Max)."""

    selected = Signal(int)

    def __init__(self, labels, tips=(), parent=None):
        super().__init__(parent)
        self.setObjectName("segment")
        self.setStyleSheet(SEGMENT_CSS)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for i, text in enumerate(labels):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            if i < len(tips):
                b.setToolTip(tips[i])
            self.group.addButton(b, i)
            lay.addWidget(b)
        self.group.idClicked.connect(self.selected.emit)

    def add_widget(self, w):
        """An extra control at the end of the track (e.g. a custom-value button)."""
        self.layout().addWidget(w)

    def button(self, i):
        return self.group.button(i)

    def set_index(self, i):
        """Check option i (or none, with i = -1) without emitting selected."""
        self.group.setExclusive(i >= 0)
        for k, b in enumerate(self.group.buttons()):
            b.setChecked(k == i)
        self.group.setExclusive(True)

    def index(self):
        return self.group.checkedId()


class StatRing(QWidget):
    """A ring that fills to a fraction (accuracy), with the percentage in the middle."""

    def __init__(self, size=132, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.value = 0.0
        self.color = theme.ACCENT
        self.caption = ""
        self.text = None

    def set_value(self, value, color=None, caption="", text=None):
        """text: what to show in the middle instead of the percentage."""
        self.value = max(0.0, min(1.0, value))
        self.color = color or theme.ACCENT
        self.caption = caption
        self.text = text
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        thick = w * 0.075
        r = QRectF(thick / 2 + 1, thick / 2 + 1, w - thick - 2, w - thick - 2)
        p.setPen(QPen(qc(theme.PANEL_2), thick, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(r, 0, 360 * 16)
        if self.value > 0:
            p.setPen(QPen(qc(self.color), thick, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(r, 90 * 16, -round(self.value * 360 * 16))
        p.setPen(qc(theme.TEXT))
        f = QFont(self.font())
        f.setPointSizeF(w * 0.17)
        f.setBold(True)
        p.setFont(f)
        text_r = QRectF(0, 0, w, w * (0.9 if self.caption else 1.0))
        p.drawText(text_r, Qt.AlignCenter, self.text if self.text is not None else f"{self.value * 100:.0f}%")
        if self.caption:
            f.setPointSizeF(max(7.5, w * 0.065))
            f.setBold(False)
            p.setFont(f)
            p.setPen(qc(theme.MUTED))
            p.drawText(QRectF(0, w * 0.58, w, w * 0.15), Qt.AlignCenter, self.caption)
        p.end()


class Popover(QFrame):
    """A floating card under a button (closes when you click elsewhere)."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("card")
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)

    def show_under(self, anchor, above=False):
        self.adjustSize()
        pos = anchor.mapToGlobal(anchor.rect().bottomLeft())
        if above:
            pos = anchor.mapToGlobal(anchor.rect().topLeft())
            pos.setY(pos.y() - self.height() - 8)
        else:
            pos.setY(pos.y() + 8)
        self.move(pos)
        self.show()



class KeysPopover(Popover):
    """Keys and mouse tips under a "?" button (instead of a line of small print on the page)."""

    def __init__(self, keys, mouse=(), note="", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(8)
        lay.addWidget(QLabel("KEYS", objectName="group"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(5)
        for i, (key, what) in enumerate(keys):
            k = QLabel(key)
            k.setStyleSheet(f"background: {theme.PANEL_2}; border: 1px solid {theme.BORDER}; border-radius: 5px; "
                            "padding: 2px 8px; font-weight: 600;")
            grid.addWidget(k, i, 0, Qt.AlignLeft)
            grid.addWidget(QLabel(what, objectName="muted"), i, 1)
        lay.addLayout(grid)
        if note:
            lay.addWidget(QLabel(note, objectName="caption"))
        if mouse:
            lay.addSpacing(4)
            lay.addWidget(QLabel("MOUSE", objectName="group"))
            for tip in mouse:
                t = QLabel(tip, objectName="muted", wordWrap=True)
                t.setFixedWidth(330)
                lay.addWidget(t)


class CardGrid(QWidget):
    """Cards in as many equal columns as fit (at least min_width each), re-flowed when resized.
    The cards size themselves from their width: card.height_for(width). With max_rows, cards that don't fit
    in that many rows are hidden (e.g. one row on the home page). With fill, a short row of cards stretches
    across the whole width instead of leaving empty columns."""

    def __init__(self, min_width=180, gap=16, max_rows=None, fill=False, parent=None):
        super().__init__(parent)
        self.min_width, self.gap, self.max_rows, self.fill = min_width, gap, max_rows, fill
        self.cards = []
        self.columns = 1

    def set_cards(self, cards):
        for c in self.cards:
            if c not in cards:
                c.setParent(None)
                c.deleteLater()
        self.cards = list(cards)
        for c in self.cards:
            c.setParent(self)
            c.show()
        self.relayout()

    def relayout(self):
        w = max(self.width(), self.min_width)
        cols = max(1, (w + self.gap) // (self.min_width + self.gap))
        if self.fill and self.cards:
            cols = min(cols, len(self.cards))
        cw = (w - self.gap * (cols - 1)) / cols
        self.columns = cols
        shown = self.cards[:cols * self.max_rows] if self.max_rows else self.cards
        for c in self.cards:
            c.setVisible(c in shown)
        y = 0
        for row in range(0, len(shown), cols):
            line = shown[row:row + cols]
            h = max(c.height_for(int(cw)) for c in line)
            for i, c in enumerate(line):
                c.setGeometry(round(i * (cw + self.gap)), y, int(cw), h)
            y += h + self.gap
        self.setMinimumHeight(max(0, y - self.gap))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.relayout()


class Sparkline(QWidget):
    """A small line chart of recent values in 0-1 (e.g. accuracy per run), the last one marked."""

    def __init__(self, height=48, parent=None):
        super().__init__(parent)
        self.setFixedHeight(height)
        self.values = []

    def set_values(self, values):
        self.values = list(values)
        self.update()

    def paintEvent(self, _):
        if not self.values:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h, pad = self.width(), self.height(), 5
        p.setPen(QPen(qc(theme.BORDER), 1, Qt.DashLine))
        p.drawLine(QPointF(0, pad), QPointF(w, pad))  # 100%
        n = len(self.values)
        pts = [QPointF(pad + (w - 2 * pad) * (i / (n - 1) if n > 1 else 0.5), pad + (h - 2 * pad) * (1 - v))
               for i, v in enumerate(self.values)]
        if n > 1:
            path = QPainterPath(pts[0])
            for q in pts[1:]:
                path.lineTo(q)
            p.setPen(QPen(qc(theme.ACCENT), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.setBrush(qc(theme.ACCENT))
        p.drawEllipse(pts[-1], 3.5, 3.5)
        p.end()


def chip(text, tip=""):
    """A small pill-shaped toggle (a filter)."""
    b = QPushButton(text)
    b.setObjectName("chip")
    b.setCheckable(True)
    b.setToolTip(tip)
    b.setFocusPolicy(Qt.NoFocus)
    b.setCursor(Qt.PointingHandCursor)
    return b


def rounded_pixmap(img, w, h, radius, top_only=False):
    """A QImage scaled to fill w x h (cropped to the centre) with rounded corners, as a QPixmap."""
    dpr = QGuiApplication.primaryScreen().devicePixelRatio() if QGuiApplication.primaryScreen() else 1.0
    pw, ph = round(w * dpr), round(h * dpr)
    scaled = img.scaled(pw, ph, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    pm = QPixmap(pw, ph)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    r = radius * dpr
    path.addRoundedRect(QRectF(0, 0, pw, ph + (r if top_only else 0)), r, r)
    p.setClipPath(path)
    p.drawImage(QPointF((pw - scaled.width()) / 2, (ph - scaled.height()) / 2), scaled)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm
