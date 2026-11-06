"""The practice view: one lane per drum, notes scrolling right-to-left onto a hit line."""

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..lanes import LANE_COLORS, LANE_NAMES, LANES
from . import theme

STRIP_H = 38        # bar/progress strip at the top
LABEL_W = 132       # lane names on the left
HIT_FRAC = 0.16     # hit line position, fraction of the scrolling area
BEATS_AHEAD = 6     # how far ahead you can read
FLASH_S = 0.18
POPUP_S = 0.7


def qc(hex_color, alpha=1.0):
    c = QColor(hex_color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


class Highway(QWidget):
    loop_selected = Signal(int, int)    # first bar, last bar (exclusive), 0-based
    loop_cleared = Signal()
    lane_toggled = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(320)
        self.setMouseTracking(True)
        self.session = None
        self.lesson = None
        self.lanes = list(LANES)       # lanes drawn
        self.active_lanes = set(LANES)  # lanes being practised (others drawn as outlines)
        self.flashes = {}       # lane -> (perf, color)
        self.popups = {}        # lane -> (text, color, perf): timing feedback next to the hit target
        self.combo = 0
        self.status = ""        # big centred message when not playing
        self._drag_from = None
        self._drag_to = None

    # ---------- public ----------

    def set_lesson(self, lesson):
        self.lesson = lesson
        used = lesson.lanes_used if lesson else set()
        self.lanes = [ln for ln in LANES if ln in used] or list(LANES)
        self.session = None
        self.update()

    def flash(self, lane, color):
        self.flashes[lane] = (time.perf_counter(), color)

    def popup(self, text, color, lane=None):
        """Show feedback beside a lane's hit target, or (lane=None) as a banner above the lanes."""
        self.popups[lane] = (text, color, time.perf_counter())

    # ---------- geometry ----------

    def _lane_rect(self, idx):
        top = STRIP_H + 8
        cap = 110.0 if len(self.lanes) <= 3 else 78.0  # few lanes (early lessons): make them bigger
        lane_h = min(cap, (self.height() - top - 8) / max(1, len(self.lanes)))
        total = lane_h * len(self.lanes)
        top += max(0.0, (self.height() - top - 8 - total) / 2)
        return QRectF(0, top + idx * lane_h, self.width(), lane_h)

    def _hit_x(self):
        return LABEL_W + HIT_FRAC * (self.width() - LABEL_W)

    def _px_per_beat(self):
        return (self.width() - self._hit_x()) / BEATS_AHEAD

    def _bar_at(self, x):
        if not self.lesson:
            return 0
        frac = (x - 12) / max(1, self.width() - 24)
        return max(0, min(self.lesson.bars - 1, int(frac * self.lesson.bars)))

    # ---------- mouse: loop selection on the strip, lane toggles on the labels ----------

    def mousePressEvent(self, e):
        p = e.position()
        if p.y() < STRIP_H and self.lesson:
            self._drag_from = self._drag_to = self._bar_at(p.x())
            self.update()
            return
        if p.x() < LABEL_W:
            for i, lane in enumerate(self.lanes):
                if self._lane_rect(i).contains(p):
                    self.lane_toggled.emit(lane)

    def mouseMoveEvent(self, e):
        if self._drag_from is not None:
            self._drag_to = self._bar_at(e.position().x())
            self.update()
        p = e.position()
        self.setCursor(Qt.PointingHandCursor if p.y() < STRIP_H or p.x() < LABEL_W else Qt.ArrowCursor)

    def mouseReleaseEvent(self, e):
        if self._drag_from is not None:
            a, b = sorted((self._drag_from, self._drag_to))
            self._drag_from = self._drag_to = None
            self.loop_selected.emit(a, b + 1)

    def mouseDoubleClickEvent(self, e):
        if e.position().y() < STRIP_H:
            self._drag_from = None
            self.loop_cleared.emit()

    # ---------- painting ----------

    def paintEvent(self, _):
        now = time.perf_counter()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0, QColor("#161927"))
        grad.setColorAt(1, QColor(theme.BG))
        p.fillRect(self.rect(), grad)
        if not self.lesson:
            p.end()
            return

        s = self.session
        u_now = s.u_at(now) if s else 0.0
        self._paint_strip(p, s, u_now)
        self._paint_lanes(p, now)
        if s:
            self._paint_grid(p, s, u_now)
            self._paint_notes(p, s, u_now)
        self._paint_hit_line(p, now)
        self._paint_popups(p, now)
        self._paint_overlay_text(p, s, u_now)
        p.end()

    def _paint_strip(self, p, s, u_now):
        les = self.lesson
        x0, x1 = 12.0, self.width() - 12.0
        bar_w = (x1 - x0) / les.bars
        y, hh = 8.0, STRIP_H - 16.0
        p.setPen(Qt.NoPen)
        p.setBrush(qc(theme.PANEL_2))
        p.drawRoundedRect(QRectF(x0, y, x1 - x0, hh), 5, 5)

        if self._drag_from is not None:
            a, b = sorted((self._drag_from, self._drag_to))
            loop = (a, b + 1)
        elif s and (s.looping or s.a > 0 or s.b < les.length - 1e-6):
            loop = (round(s.a / les.bar), round(s.b / les.bar))
        else:
            loop = None
        if loop:
            p.setBrush(qc(theme.ACCENT, 0.28))
            p.drawRoundedRect(QRectF(x0 + loop[0] * bar_w, y, (loop[1] - loop[0]) * bar_w, hh), 5, 5)

        if s and s.started and not s.in_count_in(u_now):
            t = min(s.lesson_time(u_now), les.length)
            p.setBrush(qc(theme.TEXT, 0.12))
            p.drawRoundedRect(QRectF(x0, y, t / les.length * (x1 - x0), hh), 5, 5)
            px = x0 + t / les.length * (x1 - x0)
            p.setBrush(qc(theme.TEXT))
            p.drawRect(QRectF(px - 1, y - 3, 2, hh + 6))

        p.setPen(qc(theme.MUTED))
        p.setFont(QFont("Segoe UI", 8))
        step = max(1, math.ceil(les.bars / max(1, (x1 - x0) / 34)))
        for i in range(0, les.bars, step):
            p.drawText(QRectF(x0 + i * bar_w + 3, y, 30, hh), Qt.AlignVCenter | Qt.AlignLeft, str(i + 1))

    def _paint_lanes(self, p, now):
        for i, lane in enumerate(self.lanes):
            r = self._lane_rect(i)
            active = lane in self.active_lanes
            p.setPen(Qt.NoPen)
            p.setBrush(qc("#ffffff", 0.025 if i % 2 == 0 else 0.0))
            p.drawRect(r)
            fl = self.flashes.get(lane)
            if fl and now - fl[0] < FLASH_S:
                a = 1 - (now - fl[0]) / FLASH_S
                p.setBrush(qc(fl[1], 0.22 * a))
                p.drawRect(QRectF(0, r.top(), self._hit_x() + 40, r.height()))
            # label
            color = LANE_COLORS[lane]
            p.setBrush(qc(color, 1.0 if active else 0.25))
            p.drawEllipse(QPointF(18, r.center().y()), 6, 6)
            p.setPen(qc(theme.TEXT if active else theme.MUTED))
            p.setFont(QFont("Segoe UI", 10, QFont.DemiBold if active else QFont.Normal))
            name = LANE_NAMES[lane] + ("" if active else "  (off)")
            p.drawText(QRectF(32, r.top(), LABEL_W - 36, r.height()), Qt.AlignVCenter | Qt.AlignLeft, name)
        p.setPen(QPen(qc(theme.BORDER), 1))
        p.drawLine(QPointF(LABEL_W, STRIP_H), QPointF(LABEL_W, self.height()))

    def _x_of(self, u, u_now):
        return self._hit_x() + (u - u_now) / self.lesson.beat * self._px_per_beat()

    def _visible(self, u_now):
        beat = self.lesson.beat
        behind = (self._hit_x() - LABEL_W) / self._px_per_beat() * beat
        return u_now - behind, u_now + BEATS_AHEAD * beat + beat

    def _paint_grid(self, p, s, u_now):
        u0, u1 = self._visible(u_now)
        top = self._lane_rect(0).top()
        bottom = self._lane_rect(len(self.lanes) - 1).bottom()
        p.setFont(QFont("Segoe UI", 8))
        for u, downbeat in s.beats_between(u0, u1):
            x = self._x_of(u, u_now)
            if x < LABEL_W:
                continue
            p.setPen(QPen(qc("#ffffff", 0.16 if downbeat else 0.05), 2 if downbeat else 1))
            p.drawLine(QPointF(x, top), QPointF(x, bottom))
            if downbeat and not s.in_count_in(u):
                bar_no = round(s.lesson_time(u) / self.lesson.bar) + 1
                if bar_no <= self.lesson.bars:
                    p.setPen(qc(theme.MUTED))
                    p.drawText(QPointF(x + 4, top - 2), str(bar_no))
        if s.looping:  # loop start markers
            k = math.ceil((u0 - s.a) / s.L)
            while s.a + k * s.L < u1:
                x = self._x_of(s.a + k * s.L, u_now)
                if x > LABEL_W and k > 0:
                    p.setPen(QPen(qc(theme.ACCENT, 0.6), 2, Qt.DashLine))
                    p.drawLine(QPointF(x, top), QPointF(x, bottom))
                k += 1

    def _paint_notes(self, p, s, u_now):
        u0, u1 = self._visible(u_now)
        ppb = self._px_per_beat()
        gem_w = max(10.0, min(30.0, ppb / 4 * 0.62))
        lane_idx = {ln: i for i, ln in enumerate(self.lanes)}
        for u, i, n, pas in s.notes_between(u0, u1):
            if n.lane not in lane_idx:
                continue
            r = self._lane_rect(lane_idx[n.lane])
            x = self._x_of(u, u_now)
            if x < LABEL_W - gem_w:
                continue
            gem_h = r.height() * 0.58
            rect = QRectF(x - gem_w / 2, r.center().y() - gem_h / 2, gem_w, gem_h)
            j = s.judgement(pas, i)
            active = n.lane in self.active_lanes
            color = LANE_COLORS[n.lane]
            if not active:
                p.setPen(QPen(qc(color, 0.35), 1.5))
                p.setBrush(Qt.NoBrush)
            elif j is None:
                p.setPen(Qt.NoPen)
                p.setBrush(qc(color, 0.45 + 0.55 * n.velocity / 127))
            elif j.grade == "miss":
                p.setPen(QPen(qc(theme.BAD, 0.9), 2))
                p.setBrush(qc(theme.BAD, 0.18))
            else:
                fade = max(0.0, 1 - max(0.0, self._hit_x() - x) / 140)
                gc = theme.GRADE_COLORS[j.grade]
                p.setPen(QPen(qc(gc, fade), 2))
                p.setBrush(qc(gc, 0.55 * fade))
                grow = 1 + 0.25 * (1 - fade)
                rect = QRectF(x - gem_w * grow / 2, r.center().y() - gem_h * grow / 2, gem_w * grow, gem_h * grow)
            p.drawRoundedRect(rect, 6, 6)

    def _paint_hit_line(self, p, now):
        x = self._hit_x()
        top = self._lane_rect(0).top()
        bottom = self._lane_rect(len(self.lanes) - 1).bottom()
        p.setPen(QPen(qc(theme.TEXT, 0.75), 2))
        p.drawLine(QPointF(x, top), QPointF(x, bottom))
        for i, lane in enumerate(self.lanes):
            r = self._lane_rect(i)
            fl = self.flashes.get(lane)
            lit = fl and now - fl[0] < FLASH_S
            p.setPen(QPen(qc(fl[1] if lit else LANE_COLORS[lane], 1.0 if lit else 0.5), 3 if lit else 2))
            p.setBrush(qc(fl[1], 0.35) if lit else Qt.NoBrush)
            gh = r.height() * 0.62
            p.drawRoundedRect(QRectF(x - 17, r.center().y() - gh / 2, 34, gh), 8, 8)

    def _paint_popups(self, p, now):
        x = self._hit_x()
        lane_idx = {ln: i for i, ln in enumerate(self.lanes)}
        for lane, (text, color, t0) in self.popups.items():
            age = now - t0
            hold = POPUP_S * (3 if lane is None else 1)
            if age > hold or (lane is not None and lane not in lane_idx):
                continue
            p.setPen(qc(color, 1 - age / hold))
            if lane is None:  # banner (loop pass scores, speed changes)
                p.setFont(QFont("Segoe UI", 13, QFont.Bold))
                p.drawText(QRectF(x + 30, STRIP_H + 2, 400, 26), Qt.AlignLeft | Qt.AlignVCenter, text)
                continue
            r = self._lane_rect(lane_idx[lane])
            p.setFont(QFont("Segoe UI", 10, QFont.Bold))
            p.drawText(QRectF(x + 22, r.top() + 2 - age * 14, 150, r.height() * 0.4), Qt.AlignLeft | Qt.AlignVCenter,
                       text)
        if self.combo >= 4:
            p.setPen(qc(theme.TEXT, 0.85))
            p.setFont(QFont("Segoe UI", 13, QFont.Bold))
            p.drawText(QRectF(self.width() - 180, STRIP_H + 2, 168, 26), Qt.AlignRight | Qt.AlignVCenter,
                       f"{self.combo} in a row")

    def _paint_overlay_text(self, p, s, u_now):
        msg, big = self.status, False
        if s and s.started and s.in_count_in(u_now):
            msg, big = str(math.ceil((s.a - u_now) / self.lesson.beat - 1e-6)), True
        elif s and s.paused:
            want = sorted({s.lesson.notes[i].lane for i in s.scorer(s.pass_of(u_now))
                           .unjudged_until(s.lesson_time(u_now) + 1e-6)})
            msg = "Waiting for: " + " + ".join(LANE_NAMES[ln] for ln in want)
        if not msg:
            return
        area = QRectF(self._hit_x() + 30, self._lane_rect(0).top(), self.width() - self._hit_x() - 60,
                      self._lane_rect(len(self.lanes) - 1).bottom() - self._lane_rect(0).top())
        p.setPen(qc(theme.TEXT, 0.9))
        p.setFont(QFont("Segoe UI", 56 if big else 15, QFont.Bold))
        p.drawText(area, Qt.AlignCenter | Qt.TextWordWrap, msg)
