"""The practice view: one lane per drum, notes scrolling right-to-left onto a hit line."""

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..lanes import LANE_COLORS, LANE_NAMES, LANES
from . import theme
from .drawing import accent_mark, gem_rect, gem_style, note_marks, open_mark, qc, speaker

STRIP_H = 38        # bar/progress strip at the top
LABEL_W = 156       # lane names (and mute buttons) on the left
MUTE_W = 22         # speaker button at the right end of each lane label
HIT_FRAC = 0.16     # hit line position, fraction of the scrolling area
BEATS_AHEAD = 6     # how far ahead you can read
FLASH_S = 0.18
POPUP_S = 0.7
MISSED = "#5a5e6e"  # a note you missed (hit notes turn theme.GOOD green)


class Highway(QWidget):
    loop_selected = Signal(int, int)    # first bar, last bar (exclusive), 0-based
    loop_cleared = Signal()
    lane_toggled = Signal(str)
    lane_muted = Signal(str)            # speaker button: silence/unsilence that drum's playback

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(320)
        self.setMouseTracking(True)
        self.session = None
        self.lesson = None
        self.lanes = list(LANES)       # lanes drawn
        self.active_lanes = set(LANES)  # lanes being practised (others drawn as outlines)
        self.muted = set()              # lanes whose playback is silenced (speaker button)
        self.flashes = {}       # lane -> (perf, color)
        self.popups = {}        # lane -> (text, color, perf): timing feedback next to the hit target
        self.combo = 0
        self.status = ""        # big centred message when not playing
        self.preview_from = 0.0  # lesson seconds the notes are shown from before Start (the loop start)
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
        """Lanes start just under the bar strip (room for the bar numbers); any spare height is left
        below them rather than as a gap above."""
        top = STRIP_H + 18
        bottom = 8 + (24 if self._has_legend() else 0)
        cap = 120.0 if len(self.lanes) <= 3 else 84.0  # few lanes (early lessons): make them bigger
        lane_h = min(cap, (self.height() - top - bottom) / max(1, len(self.lanes)))
        return QRectF(0, top + idx * lane_h, self.width(), lane_h)

    def _has_legend(self):
        """Accents, ghost notes or open hi-hats get a legend under the lanes."""
        return bool(self.lesson and (self.lesson.has_dynamics or self.lesson.has_open_hats))

    def _mute_rect(self, idx):
        r = self._lane_rect(idx)
        return QRectF(LABEL_W - MUTE_W - 6, r.center().y() - MUTE_W / 2, MUTE_W, MUTE_W)

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
                if self._mute_rect(i).adjusted(-4, -4, 4, 4).contains(p):
                    self.lane_muted.emit(lane)
                elif self._lane_rect(i).contains(p):
                    self.lane_toggled.emit(lane)

    def mouseMoveEvent(self, e):
        if self._drag_from is not None:
            self._drag_to = self._bar_at(e.position().x())
            self.update()
        p = e.position()
        self.setCursor(Qt.PointingHandCursor if p.y() < STRIP_H or p.x() < LABEL_W else Qt.ArrowCursor)
        tip = ""
        if p.x() < LABEL_W:
            for i, lane in enumerate(self.lanes):
                if self._mute_rect(i).adjusted(-4, -4, 4, 4).contains(p):
                    tip = f"{'Unmute' if lane in self.muted else 'Mute'} the {LANE_NAMES[lane].lower()} playback"
                elif self._lane_rect(i).contains(p):
                    tip = f"Turn the {LANE_NAMES[lane].lower()} {'on' if lane not in self.active_lanes else 'off'}"
        self.setToolTip(tip)

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
        grad.setColorAt(0, QColor(theme.PANEL))
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
        else:
            self._paint_preview(p)
        self._paint_hit_line(p, now)
        self._paint_legend(p)
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
            p.drawText(QRectF(32, r.top(), LABEL_W - MUTE_W - 42, r.height()), Qt.AlignVCenter | Qt.AlignLeft, name)
            speaker(p, self._mute_rect(i), lane in self.muted)
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
        base_w = max(10.0, min(30.0, ppb / 4 * 0.62))
        lane_idx = {ln: i for i, ln in enumerate(self.lanes)}
        for u, i, n, pas in s.notes_between(u0, u1):
            if n.lane not in lane_idx:
                continue
            r = self._lane_rect(lane_idx[n.lane])
            x = self._x_of(u, u_now)
            if x < LABEL_W - base_w:
                continue
            rect = gem_rect(x, r.center().y(), base_w, r.height(), n.dyn)
            gem_w, gem_h = rect.width(), rect.height()
            j = s.judgement(pas, i)
            active = n.lane in self.active_lanes
            color = LANE_COLORS[n.lane]
            if not active:
                p.setPen(QPen(qc(color, 0.35), 1.5))
                p.setBrush(Qt.NoBrush)
            elif j is None:
                gem_style(p, color, n.dyn)
            elif j.grade == "miss":  # missed: the note turns grey
                p.setPen(Qt.NoPen)
                p.setBrush(qc(MISSED, 0.9))
            else:  # hit: the note turns green, with a short pop as it's hit (yellow edge: wrong strength)
                wrong_strength = j.dynamic in ("too_soft", "too_loud")
                p.setPen(QPen(qc(theme.WARN), 2.5) if wrong_strength else Qt.NoPen)
                p.setBrush(qc(theme.GOOD, 0.95))
                grow = 1 + 0.3 * max(0.0, 1 - abs(self._hit_x() - x) / 60)
                rect = QRectF(x - gem_w * grow / 2, r.center().y() - gem_h * grow / 2, gem_w * grow, gem_h * grow)
            p.drawRoundedRect(rect, 6, 6)
            if active and j is None:
                note_marks(p, n, rect, min(9.0, r.height() * 0.08))

    def _paint_preview(self, p):
        """Before Start: the first bars (from the loop start), so you can read the part before playing."""
        les = self.lesson
        ppb = self._px_per_beat()
        base_w = max(10.0, min(30.0, ppb / 4 * 0.62))
        lane_idx = {ln: i for i, ln in enumerate(self.lanes)}
        top, bottom = self._lane_rect(0).top(), self._lane_rect(len(self.lanes) - 1).bottom()
        start = self.preview_from
        p.setFont(QFont("Segoe UI", 8))
        beat = math.ceil(start / les.beat - 1e-6)
        while (beat * les.beat - start) / les.beat <= BEATS_AHEAD + 1:
            x = self._hit_x() + (beat * les.beat - start) / les.beat * ppb
            downbeat = beat % les.beats_per_bar == 0
            p.setPen(QPen(qc("#ffffff", 0.16 if downbeat else 0.05), 2 if downbeat else 1))
            p.drawLine(QPointF(x, top), QPointF(x, bottom))
            bar_no = round(beat / les.beats_per_bar) + 1
            if downbeat and bar_no <= les.bars:
                p.setPen(qc(theme.MUTED))
                p.drawText(QPointF(x + 4, top - 2), str(bar_no))
            beat += 1
        end = start + (BEATS_AHEAD + 1) * les.beat
        for n in les.notes:
            if n.t < start - 1e-6 or n.lane not in lane_idx:
                continue
            if n.t > end:
                break
            r = self._lane_rect(lane_idx[n.lane])
            x = self._hit_x() + (n.t - start) / les.beat * ppb
            rect = gem_rect(x, r.center().y(), base_w, r.height(), n.dyn)
            if n.lane in self.active_lanes:
                gem_style(p, LANE_COLORS[n.lane], n.dyn)
            else:
                p.setPen(QPen(qc(LANE_COLORS[n.lane], 0.35), 1.5))
                p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect, 6, 6)
            if n.lane in self.active_lanes:
                note_marks(p, n, rect, min(9.0, r.height() * 0.08))

    def _paint_legend(self, p):
        """Explains accents, ghost notes and open hi-hats when the lesson has any."""
        if not self._has_legend():
            return
        y = self._lane_rect(len(self.lanes) - 1).bottom() + 4
        x = LABEL_W + 12
        p.setFont(QFont("Segoe UI", 9))
        if self.lesson.has_open_hats:
            open_mark(p, x + 6, y + 15, 7)
            label = "open hi-hat: lift your hi-hat foot"
            p.setPen(qc(theme.MUTED))
            p.drawText(QRectF(x + 18, y, 260, 18), Qt.AlignVCenter | Qt.AlignLeft, label)
            x += 18 + p.fontMetrics().horizontalAdvance(label) + 24
        items = (("accent", "accent: hit hard"), ("normal", "normal"), ("ghost", "ghost: very soft"))
        for dyn, label in items if self.lesson.has_dynamics else ():
            w, h = 12, 16
            rect = QRectF(x, y + 1, w, h)
            gem_style(p, theme.TEXT, dyn)
            p.drawRoundedRect(rect, 3, 3)
            if dyn == "accent":
                accent_mark(p, rect, 3.5)
            p.setPen(qc(theme.MUTED))
            p.drawText(QRectF(x + w + 6, y, 120, 18), Qt.AlignVCenter | Qt.AlignLeft, label)
            x += w + 6 + p.fontMetrics().horizontalAdvance(label) + 16

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
            # the target: a faint dashed frame (a hollow note in the lane's colour is a ghost note)
            p.setPen(QPen(qc(fl[1], 1.0), 3) if lit else QPen(qc(theme.TEXT, 0.3), 1.5, Qt.DashLine))
            p.setBrush(qc(fl[1], 0.35) if lit else Qt.NoBrush)
            gh = r.height() * 0.72
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
        top, bottom = self._lane_rect(0).top(), self._lane_rect(len(self.lanes) - 1).bottom()
        if s and s.started and s.in_count_in(u_now):
            # the count-in, left of the hit line: nothing has scrolled past yet, so it hides no notes
            count = str(math.ceil((s.a - u_now) / self.lesson.beat - 1e-6))
            p.setPen(qc(theme.TEXT, 0.9))
            p.setFont(QFont("Segoe UI", 48, QFont.Bold))
            p.drawText(QRectF(LABEL_W, top, self._hit_x() - LABEL_W - 20, bottom - top), Qt.AlignCenter, count)
            return
        msg = self.status
        if s and s.paused:
            want = sorted({s.lesson.notes[i].lane for i in s.scorer(s.pass_of(u_now))
                           .unjudged_until(s.lesson_time(u_now) + 1e-6)})
            msg = "Waiting for: " + " + ".join(LANE_NAMES[ln] for ln in want)
        if not msg:
            return
        # under the lanes (and legend) when there's room, so it doesn't cover the notes; else over them,
        # on a panel so it stays readable
        p.setFont(QFont("Segoe UI", 14, QFont.Bold))
        below = bottom + (24 if self._has_legend() else 0) + 12
        if self.height() - below - 8 >= 90:
            avail = QRectF(LABEL_W + 20, below, self.width() - LABEL_W - 40, self.height() - below - 8)
        else:
            left = self._hit_x() + 40
            avail = QRectF(left, top, self.width() - left - 40, bottom - top)
        text_rect = p.fontMetrics().boundingRect(avail.toRect(), Qt.AlignCenter | Qt.TextWordWrap, msg)
        box = QRectF(text_rect).adjusted(-24, -16, 24, 16)
        p.setPen(QPen(qc(theme.BORDER), 1))
        p.setBrush(qc(theme.PANEL, 0.94))
        p.drawRoundedRect(box, 12, 12)
        p.setPen(qc(theme.TEXT, 0.95))
        p.drawText(avail, Qt.AlignCenter | Qt.TextWordWrap, msg)
