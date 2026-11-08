"""Drawing pieces shared by the practice lanes and the editor: note gems, notation marks, icons."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPen

from . import theme

GEM_H = 0.6  # every note is the same size: this share of the lane's height, base_w wide
INK = "#14161f"  # the accent sign drawn on a note


def qc(hex_color, alpha=1.0):
    c = QColor(hex_color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def gem_rect(x, center_y, base_w, lane_h, dyn=None):
    """A note's rectangle (the same for every dynamic: the look shows it, not the size)."""
    h = lane_h * GEM_H
    return QRectF(x - base_w / 2, center_y - h / 2, base_w, h)


def gem_style(p, color, dyn):
    """Pen and brush for a note still to play: normal filled, accent filled with a white edge (and the
    accent sign inside, see note_marks), ghost hollow."""
    if dyn == "ghost":
        p.setPen(QPen(qc(color, 0.95), 2))
        p.setBrush(Qt.NoBrush)
    elif dyn == "accent":
        p.setPen(QPen(qc("#ffffff", 0.95), 2.5))
        p.setBrush(qc(color, 1.0))
    else:
        p.setPen(Qt.NoPen)
        p.setBrush(qc(color, 0.85))


def note_marks(p, note, rect, size):
    """The accent sign (>) inside an accented note; the open hi-hat circle above an open one."""
    if note.dyn == "accent":
        accent_mark(p, rect, min(size, rect.width() * 0.3, rect.height() * 0.3))
    if note.open:
        open_mark(p, rect.center().x(), rect.top() - 3, size)


def accent_mark(p, rect, size):
    """The music accent sign (>) in the middle of a note."""
    x, y = rect.center().x(), rect.center().y()
    p.setPen(QPen(qc(INK, 0.9), max(1.5, size * 0.45), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    p.drawPolyline([QPointF(x - size * 0.6, y - size), QPointF(x + size * 0.6, y), QPointF(x - size * 0.6, y + size)])


def open_mark(p, x, bottom, size):
    """The open hi-hat sign (a small circle) above a note."""
    p.setPen(QPen(qc("#ffffff", 0.95), 2))
    p.setBrush(Qt.NoBrush)
    rad = size * 0.75
    p.drawEllipse(QPointF(x, bottom - rad), rad, rad)


def icon(name, color, size=16):
    """A small line icon as a QPixmap (instead of emoji, which look different on every system):
    lock, check, flame, note, gear, dot, and the outline icons in _line_icon."""
    from PySide6.QtGui import QGuiApplication, QPainter, QPainterPath, QPixmap

    dpr = QGuiApplication.primaryScreen().devicePixelRatio() if QGuiApplication.primaryScreen() else 1.0
    pm = QPixmap(round(size * dpr), round(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 16  # drawn on a 16 x 16 grid
    pen = QPen(qc(color), 1.6 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    if name == "lock":
        p.drawArc(QRectF(4.5 * s, 2 * s, 7 * s, 8 * s), 0, 180 * 16)
        p.drawLine(QPointF(4.5 * s, 6 * s), QPointF(4.5 * s, 7.5 * s))
        p.drawLine(QPointF(11.5 * s, 6 * s), QPointF(11.5 * s, 7.5 * s))
        p.setPen(Qt.NoPen)
        p.setBrush(qc(color))
        p.drawRoundedRect(QRectF(3 * s, 7.5 * s, 10 * s, 7 * s), 1.5 * s, 1.5 * s)
    elif name == "check":
        p.setPen(QPen(qc(color), 2 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline([QPointF(3 * s, 8.5 * s), QPointF(6.5 * s, 12 * s), QPointF(13 * s, 4.5 * s)])
    elif name == "flame":
        path = QPainterPath(QPointF(8 * s, 1.5 * s))
        path.cubicTo(QPointF(9 * s, 5 * s), QPointF(13.5 * s, 7 * s), QPointF(13 * s, 10.5 * s))
        path.cubicTo(QPointF(12.5 * s, 14 * s), QPointF(10 * s, 15 * s), QPointF(8 * s, 15 * s))
        path.cubicTo(QPointF(5 * s, 15 * s), QPointF(3 * s, 13 * s), QPointF(3 * s, 10.5 * s))
        path.cubicTo(QPointF(3 * s, 8 * s), QPointF(5 * s, 7 * s), QPointF(5.5 * s, 5 * s))
        path.cubicTo(QPointF(6.5 * s, 6 * s), QPointF(7 * s, 7 * s), QPointF(7 * s, 8 * s))
        path.cubicTo(QPointF(8.5 * s, 6 * s), QPointF(8.5 * s, 4 * s), QPointF(8 * s, 1.5 * s))
        p.setPen(Qt.NoPen)
        p.setBrush(qc(color))
        p.drawPath(path)
    elif name == "note":
        p.setPen(Qt.NoPen)
        p.setBrush(qc(color))
        p.drawEllipse(QRectF(2.5 * s, 10 * s, 5.5 * s, 4.5 * s))
        p.drawRect(QRectF(6.6 * s, 2 * s, 1.5 * s, 10.5 * s))
        p.setPen(pen)
        p.drawLine(QPointF(7.4 * s, 2.5 * s), QPointF(12.5 * s, 5.5 * s))
    elif name == "gear":
        import math
        path = QPainterPath()
        for k in range(16):  # 8 teeth: alternate outer and inner radius
            a = math.pi * 2 * (k / 16) - math.pi / 16
            r = 7 * s if k % 2 == 0 else 5.2 * s
            for da in (0, math.pi / 16):
                pt = QPointF(8 * s + r * math.cos(a + da), 8 * s + r * math.sin(a + da))
                path.moveTo(pt) if path.elementCount() == 0 else path.lineTo(pt)
        path.closeSubpath()
        path.addEllipse(QPointF(8 * s, 8 * s), 2.3 * s, 2.3 * s)  # the hole (odd-even fill leaves it empty)
        p.setPen(Qt.NoPen)
        p.setBrush(qc(color))
        p.drawPath(path)
    elif name == "dot":
        p.setPen(Qt.NoPen)
        p.setBrush(qc(color))
        p.drawEllipse(QRectF(4 * s, 4 * s, 8 * s, 8 * s))
    else:
        _line_icon(p, name, s, color)
    p.end()
    return pm


def _line_icon(p, name, s, color):
    """The outline icons (navigation and transport), on the same 16 x 16 grid as icon()."""
    pt = lambda x, y: QPointF(x * s, y * s)  # noqa: E731
    fill = lambda: (p.setPen(Qt.NoPen), p.setBrush(qc(color)))  # noqa: E731
    if name == "home":
        p.drawPolyline([pt(2, 7.5), pt(8, 2.5), pt(14, 7.5)])
        p.drawPolyline([pt(3.8, 6.3), pt(3.8, 13.5), pt(12.2, 13.5), pt(12.2, 6.3)])
        p.drawLine(pt(8, 13.5), pt(8, 10))
    elif name == "songs":  # a list with a note
        for y in (3.5, 7, 10.5):
            p.drawLine(pt(2, y), pt(8.5, y))
        p.drawLine(pt(12.5, 3), pt(12.5, 11.5))
        p.drawLine(pt(12.5, 3), pt(14.5, 4.2))
        fill()
        p.drawEllipse(QRectF(9 * s, 10.3 * s, 3.8 * s, 3.2 * s))
    elif name == "course":  # a path of steps
        p.drawPolyline([pt(2, 13.5), pt(6, 13.5), pt(6, 9.5), pt(10, 9.5), pt(10, 5.5), pt(14, 5.5)])
        fill()
        p.drawEllipse(QRectF(12.2 * s, 1.5 * s, 3 * s, 3 * s))
    elif name == "groove":  # a wave
        from PySide6.QtGui import QPainterPath
        path = QPainterPath(pt(1.5, 8))
        path.cubicTo(pt(3.5, 2), pt(5.5, 2), pt(6.5, 8))
        path.cubicTo(pt(7.5, 14), pt(9.5, 14), pt(10.5, 8))
        path.cubicTo(pt(11.2, 4.5), pt(13, 4.5), pt(14.5, 8))
        p.drawPath(path)
    elif name == "kit":  # a drum with sticks
        p.drawEllipse(QRectF(2.5 * s, 6 * s, 11 * s, 3.5 * s))
        p.drawLine(pt(2.5, 7.8), pt(2.5, 12))
        p.drawLine(pt(13.5, 7.8), pt(13.5, 12))
        p.drawArc(QRectF(2.5 * s, 10.2 * s, 11 * s, 3.5 * s), 180 * 16, 180 * 16)
        p.drawLine(pt(5, 1.5), pt(7.5, 6.5))
        p.drawLine(pt(11, 1.5), pt(8.5, 6.5))
    elif name == "play":
        fill()
        p.drawPolygon([pt(4.5, 2.5), pt(13.5, 8), pt(4.5, 13.5)])
    elif name == "pause":
        fill()
        p.drawRoundedRect(QRectF(3.5 * s, 2.5 * s, 3 * s, 11 * s), s, s)
        p.drawRoundedRect(QRectF(9.5 * s, 2.5 * s, 3 * s, 11 * s), s, s)
    elif name == "stop":
        fill()
        p.drawRoundedRect(QRectF(3.5 * s, 3.5 * s, 9 * s, 9 * s), 1.5 * s, 1.5 * s)
    elif name == "loop":
        p.drawArc(QRectF(2 * s, 3 * s, 12 * s, 10 * s), 30 * 16, 150 * 16)
        p.drawArc(QRectF(2 * s, 3 * s, 12 * s, 10 * s), 210 * 16, 150 * 16)
        p.drawPolyline([pt(10.5, 2.5), pt(13.2, 4.8), pt(10.8, 6.8)])
        p.drawPolyline([pt(5.5, 13.5), pt(2.8, 11.2), pt(5.2, 9.2)])
    elif name == "metronome":
        p.drawPolygon([pt(5.5, 2), pt(10.5, 2), pt(13, 14), pt(3, 14)])
        p.drawLine(pt(8, 11), pt(12, 4))
        p.drawLine(pt(4, 11), pt(12, 11))
    elif name == "speaker":
        p.drawPolygon([pt(2, 6), pt(5, 6), pt(9, 2.5), pt(9, 13.5), pt(5, 10), pt(2, 10)])
        p.drawArc(QRectF(8 * s, 5 * s, 4.5 * s, 6 * s), -60 * 16, 120 * 16)
        p.drawArc(QRectF(8 * s, 2.5 * s, 7 * s, 11 * s), -60 * 16, 120 * 16)
    elif name == "wait":  # an hourglass
        p.drawPolyline([pt(4, 2), pt(12, 2), pt(4, 14), pt(12, 14), pt(4, 2)])
    elif name == "plus":
        p.drawLine(pt(8, 3), pt(8, 13))
        p.drawLine(pt(3, 8), pt(13, 8))
    elif name == "edit":  # a pencil
        p.drawPolygon([pt(10.5, 2.5), pt(13.5, 5.5), pt(5.5, 13.5), pt(2.5, 13.5), pt(2.5, 10.5)])
        p.drawLine(pt(9, 4), pt(12, 7))
    elif name == "search":
        p.drawEllipse(QRectF(2.5 * s, 2.5 * s, 8 * s, 8 * s))
        p.drawLine(pt(9.5, 9.5), pt(13.5, 13.5))
    elif name == "back":
        p.drawLine(pt(13, 8), pt(3, 8))
        p.drawPolyline([pt(7.5, 3.5), pt(3, 8), pt(7.5, 12.5)])
    elif name == "more":
        fill()
        for x in (3.5, 8, 12.5):
            p.drawEllipse(QRectF((x - 1.3) * s, 6.7 * s, 2.6 * s, 2.6 * s))
    elif name == "help":
        p.drawEllipse(QRectF(1.8 * s, 1.8 * s, 12.4 * s, 12.4 * s))
        p.drawArc(QRectF(6 * s, 4.3 * s, 4 * s, 4 * s), -40 * 16, 220 * 16)
        p.drawLine(pt(8, 8.6), pt(8, 9.6))
        fill()
        p.drawEllipse(QRectF(7.2 * s, 10.8 * s, 1.6 * s, 1.6 * s))
    elif name == "star":
        import math
        fill()
        p.drawPolygon([pt(8 + (6.5 if k % 2 == 0 else 2.8) * math.sin(k * math.pi / 5),
                          8.6 - (6.5 if k % 2 == 0 else 2.8) * math.cos(k * math.pi / 5)) for k in range(10)])
    elif name == "close":  # an x
        p.drawLine(pt(4, 4), pt(12, 12))
        p.drawLine(pt(12, 4), pt(4, 12))
    elif name == "folder":
        p.drawPolyline([pt(2, 13), pt(2, 3.5), pt(6, 3.5), pt(7.5, 5.5), pt(14, 5.5), pt(14, 13), pt(2, 13)])
    elif name == "sliders":  # settings
        for y, x in ((4, 10), (8, 5), (12, 11)):
            p.drawLine(pt(2, y), pt(14, y))
            p.save()
            fill()
            p.drawEllipse(QRectF((x - 1.8) * s, (y - 1.8) * s, 3.6 * s, 3.6 * s))
            p.restore()
    else:
        raise ValueError(f"no icon {name!r}")


def speaker(p, rect, muted):
    """Speaker icon; crossed out (and red) when muted."""
    color = qc(theme.BAD) if muted else qc(theme.MUTED)
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    x, cy, s = rect.left() + 3, rect.center().y(), rect.height() / 22
    p.drawRect(QRectF(x, cy - 3 * s, 4 * s, 6 * s))
    p.drawPolygon([QPointF(x + 3 * s, cy - 3 * s), QPointF(x + 9 * s, cy - 8 * s),
                   QPointF(x + 9 * s, cy + 8 * s), QPointF(x + 3 * s, cy + 3 * s)])
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(color, 1.8))
    if muted:
        p.drawLine(QPointF(x + 12 * s, cy - 4 * s), QPointF(x + 19 * s, cy + 4 * s))
        p.drawLine(QPointF(x + 12 * s, cy + 4 * s), QPointF(x + 19 * s, cy - 4 * s))
    else:
        for k in (1, 2):
            rad = 4 * k * s
            p.drawArc(QRectF(x + 8 * s - rad, cy - rad, 2 * rad, 2 * rad), -50 * 16, 100 * 16)
