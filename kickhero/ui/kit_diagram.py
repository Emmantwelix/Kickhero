"""A drum kit drawn from the front, for the pad setup: the drum to hit next glows, every hit flashes the
drum it was heard as, and drums already set up keep a soft tint. Click a drum to set up just that one.

Parts are the practice lanes plus OPEN_HAT (the hi-hat with its top cymbal lifted) and PEDAL (the hi-hat
pedal), so each pad setup step has something to light up."""

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import QWidget

from ..lanes import LANE_COLORS, LANE_NAMES, LANES, OPEN_HAT
from . import theme
from .drawing import qc

PEDAL = "hihat_pedal"
PART_NAMES = dict(LANE_NAMES, **{OPEN_HAT: "Open hi-hat", PEDAL: "Hi-hat pedal", "hihat": "Hi-hat"})
VIEW_W, VIEW_H = 420.0, 250.0   # the drawing's own coordinates, scaled to fit the widget
FLASH_S = 0.35                   # how long a hit's flash takes to fade


def color(part):
    return LANE_COLORS["hihat" if part in (OPEN_HAT, PEDAL) else part]


def ellipse(cx, cy, rx, ry, angle=0.0):
    path = QPainterPath()
    path.addEllipse(QPointF(0, 0), rx, ry)
    return QTransform().translate(cx, cy).rotate(angle).map(path)


def drum(cx, top, rx, ry, depth):
    """A drum seen from the front and a little above: the shell and its top head."""
    shell = QPainterPath()
    shell.addRect(QRectF(cx - rx, top, rx * 2, depth))
    shell.addEllipse(QPointF(cx, top + depth), rx, ry)
    shell = shell.united(ellipse(cx, top, rx, ry))
    return shell.simplified(), ellipse(cx, top, rx, ry)


def cymbal(cx, cy, rx, angle=0.0):
    return ellipse(cx, cy, rx, rx * 0.14, angle)


class KitDiagram(QWidget):
    part_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 220)
        self.setMouseTracking(True)
        self.target = None      # the part to hit now (glows)
        self.done = set()       # parts already set up (tinted)
        self.hover = None
        self._flash = {}        # part -> when it was hit
        self._timer = QTimer(self, interval=33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self.parts = self._build()

    # ---------- public ----------

    def set_target(self, part):
        self.target = part
        self.update()

    def set_done(self, parts):
        self.done = set(parts)
        self.update()

    def flash(self, part):
        self._flash[part] = time.perf_counter()
        self.update()

    # ---------- shapes ----------

    def _build(self):
        """part -> (filled shape, detail lines drawn on top) in drawing coordinates."""
        parts = {}
        kick = ellipse(210, 165, 60, 60)
        ring = QPainterPath()
        ring.addEllipse(QPointF(210, 165), 50, 50)
        parts["kick"] = (kick, [ring])
        for lane, cx in (("tom1", 172), ("tom2", 248)):
            body, head = drum(cx, 86, 27, 8, 30)
            parts[lane] = (body, [head])
        body, head = drum(338, 132, 32, 9, 70)
        parts["tom3"] = (body, [head])
        body, head = drum(110, 140, 32, 8, 22)
        parts["snare"] = (body, [head])
        seam = QPainterPath()
        seam.moveTo(11, 83)
        seam.lineTo(85, 83)
        parts["hihat"] = (ellipse(48, 83, 38, 7), [seam])  # closed: the two cymbals pressed together
        parts[OPEN_HAT] = (cymbal(48, 68, 38).united(cymbal(48, 87, 38)), [])
        pedal = QPainterPath()
        pedal.addRoundedRect(QRectF(34, 222, 30, 12), 3, 3)
        parts[PEDAL] = (pedal, [])
        parts["crash"] = (cymbal(112, 42, 50, -8), [])
        parts["ride"] = (cymbal(330, 58, 58, 6), [])
        return parts

    def _stands(self):
        path = QPainterPath()
        for a, b in (((48, 88), (48, 222)), ((48, 200), (30, 236)), ((48, 200), (66, 236)),      # hi-hat
                     ((112, 46), (150, 236)), ((146, 215), (134, 238)), ((150, 215), (164, 238)),  # crash
                     ((330, 62), (360, 132)),                                                    # ride
                     ((110, 170), (96, 236)), ((110, 170), (126, 236)),                         # snare
                     ((316, 210), (312, 236)), ((362, 210), (366, 236)),                        # floor tom legs
                     ((210, 225), (210, 238))):                                                 # kick pedal
            path.moveTo(*a)
            path.lineTo(*b)
        return path

    def _transform(self):
        scale = min(self.width() / VIEW_W, self.height() / VIEW_H)
        return QTransform().translate((self.width() - VIEW_W * scale) / 2,
                                      (self.height() - VIEW_H * scale) / 2).scale(scale, scale)

    def _visible(self):
        """The parts in drawing order (back to front). The hi-hat shows lifted while its open step is on."""
        hat = OPEN_HAT if self.target == OPEN_HAT else "hihat"
        return ["kick", "tom1", "tom2", "tom3", "snare", PEDAL, hat, "crash", "ride"]

    def part_at(self, pos):
        point = self._transform().inverted()[0].map(QPointF(pos))
        for part in reversed(self._visible()):
            if self.parts[part][0].contains(point) or (
                    part != "kick" and self.parts[part][0].boundingRect().adjusted(-4, -6, 4, 6).contains(point)):
                return part
        return None

    # ---------- events ----------

    def _tick(self):
        now = time.perf_counter()
        self._flash = {p: t for p, t in self._flash.items() if now - t < FLASH_S}
        if self.target or self._flash:
            self.update()

    def mouseMoveEvent(self, e):
        part = self.part_at(e.position())
        if part != self.hover:
            self.hover = part
            self.setCursor(Qt.PointingHandCursor if part else Qt.ArrowCursor)
            self.setToolTip(f"{PART_NAMES[part]}: click to set up just this one" if part else "")
            self.update()

    def leaveEvent(self, _):
        self.hover = None
        self.update()

    def mousePressEvent(self, e):
        part = self.part_at(e.position())
        if part and e.button() == Qt.LeftButton:
            self.part_clicked.emit(part)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setTransform(self._transform())
        now = time.perf_counter()
        pulse = 0.5 + 0.5 * math.sin(now * 5.5)

        p.setPen(QPen(qc(theme.FAINT), 2.2, Qt.SolidLine, Qt.RoundCap))
        p.drawPath(self._stands())
        floor = ellipse(210, 240, 190, 7)
        p.fillPath(floor, qc(theme.BORDER, 0.6))

        for part in self._visible():
            shape, details = self.parts[part]
            c = color(part)
            lit = part == self.target or (part == "hihat" and self.target == OPEN_HAT)
            hit = max((1 - (now - t) / FLASH_S for q, t in self._flash.items()
                       if q == part or (part == OPEN_HAT and q == "hihat")), default=0.0)
            if lit:  # glow: soft strokes around the shape, breathing
                for width, alpha in ((22, 0.10), (14, 0.18), (7, 0.30)):
                    p.strokePath(shape, QPen(qc(c, alpha * (0.6 + 0.8 * pulse)), width, Qt.SolidLine,
                                             Qt.RoundCap, Qt.RoundJoin))
            if lit:
                fill = qc(c, 0.55 + 0.25 * pulse)
            elif part in self.done or (part == OPEN_HAT and "hihat" in self.done):
                fill = qc(c, 0.28)
            else:
                fill = qc(theme.SURFACE_3 if part == self.hover else theme.PANEL_2)
            p.fillPath(shape, fill)
            if hit > 0:
                p.fillPath(shape, qc(c, 0.9 * hit))
            edge = c if (lit or part == self.hover or hit > 0) else theme.MUTED
            p.setPen(QPen(qc(edge, 0.95 if lit else 0.7), 1.6))
            p.setBrush(Qt.NoBrush)
            p.drawPath(shape)
            for d in details:
                p.drawPath(d)

        label = self.target or self.hover
        if label:  # the name of the drum to hit (or under the mouse), above it
            box = self.parts[label][0].boundingRect()
            f = QFont(p.font())
            f.setPointSizeF(9.5)
            f.setBold(True)
            p.setFont(f)
            text = PART_NAMES[label]
            w = p.fontMetrics().horizontalAdvance(text) + 16
            y = box.top() - 22 if label not in ("kick", PEDAL) else box.bottom() - 34
            if label == PEDAL:
                y = box.top() - 26
            rect = QRectF(min(max(4, box.center().x() - w / 2), VIEW_W - w - 4), max(2, y), w, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(qc(color(label) if label == self.target else theme.SURFACE_3))
            p.drawRoundedRect(rect, 9, 9)
            p.setPen(qc(theme.BG if label == self.target else theme.TEXT))
            p.drawText(rect, Qt.AlignCenter, text)
        p.end()


PARTS = LANES + [OPEN_HAT, PEDAL]
