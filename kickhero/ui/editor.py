"""Edit page: a song's whole drum part on a grid (bars left to right, one row per drum).

Click to add, drag to move (sideways = time, up/down = drum), right-click for strength, open hi-hat,
drum and bar 1. Plays back with the song. Saving overwrites the song's MIDI; the converted original
is kept (see engine.editing).
"""

import bisect
import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (QComboBox, QDialog, QDoubleSpinBox, QFrame, QHBoxLayout, QInputDialog, QLabel, QMenu,
                               QMessageBox, QPushButton, QScrollBar, QSlider, QVBoxLayout, QWidget)

from ..engine.editing import VELOCITY, load_part
from ..engine.lesson import Note, classify_dynamics
from ..engine.meter import COMMON_METERS, pulse
from ..engine.session import Session
from ..lanes import LANE_COLORS, LANE_NAMES, LANES
from . import theme
from .convert_settings import TEMPO_FIXES
from .drawing import gem_rect, gem_style, icon, note_marks, qc
from .fitting import ElidedLabel, FlowRow
from .widgets import KeysPopover, icon_button, state_icon

EDIT_KEYS = [("Click", "Add a note"), ("Drag", "Move it (up / down changes the drum)"), ("Double-click", "Delete it"),
             ("Right-click", "Strength, open hi-hat, drum, bar 1"), ("A  N  G", "Accent / normal / ghost"),
             ("O", "Open hi-hat"), ("Del", "Delete the selected notes"), ("Arrows", "Move the selected notes"),
             ("Ctrl+C / V", "Copy / paste bars"), ("Ctrl+Z / Y", "Undo / redo"), ("Ctrl+S", "Save"),
             ("Ctrl+wheel", "Zoom"), ("Space", "Play / stop")]
EDIT_MOUSE = ["Drag across the bar numbers to select bars: Play then loops them, and Ctrl+C copies them",
              "Drag on empty space to select several notes"]

RULER_H = 30
LABEL_W = 110
BOTTOM_PAD = 6
SNAPS = [("1/4", 4), ("1/8", 8), ("1/16", 16), ("1/32", 32), ("Off", 0)]
DRAG_PX = 4  # mouse movement before a press becomes a drag


class EditorGrid(QWidget):
    """The drum grid. Holds the view state (zoom, scroll, selection); edits go through the Part."""

    changed = Signal()           # the part was edited
    selection_changed = Signal()
    cursor_moved = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumHeight(360)
        self.part = None
        self.ppb = 70.0              # pixels per beat (zoom)
        self.scroll_x = 0.0
        self.grid = 16
        self.selected = set()        # EditNotes
        self.sel_bars = None         # (first, last) inclusive, chosen on the ruler
        self.cursor = 0.0            # seconds: where playback starts and paste goes
        self.playhead = None         # seconds while playing
        self.song_length = 0.0       # seconds of song audio (lesson time), to show bars past the last note
        self._dyn = {}
        self._times = []
        self._press = None           # (pos, note under the mouse or None, area)
        self._drag = None            # ("move", dt, dlane) / ("band", rect) / ("bars", first, last)
        self._just_added = None
        self._static = None          # the grid drawn without the playhead, reused while playing
        self._static_key = None
        self.scrollbar = QScrollBar(Qt.Horizontal, self)
        self.scrollbar.valueChanged.connect(self._scrolled)

    # ---------- state ----------

    def set_part(self, part):
        self.part = part
        self.selected.clear()
        self.sel_bars = None
        self.cursor = 0.0
        self.scroll_x = 0.0
        self.refresh()

    def refresh(self):
        """Call after the part changed: recompute dynamics (as practice shows them) and the scroll range."""
        part = self.part
        if part is None:
            return
        notes = part.notes
        dyns = classify_dynamics([Note(n.t, n.lane, n.velocity) for n in notes])
        self._dyn = {n: d.dyn for n, d in zip(notes, dyns)}
        self._times = [n.t for n in notes]
        self.selected &= set(notes)
        self._update_scrollbar()
        self.update()

    def total_bars(self):
        part = self.part
        song = math.ceil(self.song_length / part.bar) if self.song_length else 0
        return max(part.bars, song) + 2

    def _update_scrollbar(self):
        width = self.total_bars() * self.part.beats_per_bar * self.ppb
        view = max(1, self.width() - LABEL_W)
        self.scrollbar.setRange(0, max(0, int(width - view)))
        self.scrollbar.setPageStep(int(view))
        self.scrollbar.setSingleStep(int(self.ppb))
        self.scrollbar.setValue(int(self.scroll_x))

    def _scrolled(self, v):
        self.scroll_x = float(v)
        self.update()

    def set_zoom(self, ppb, anchor_x=None):
        """Zoom, keeping the time under anchor_x (default: the left edge) in place."""
        anchor_x = LABEL_W if anchor_x is None else anchor_x
        t = self.time_at(anchor_x)
        self.ppb = max(15.0, min(260.0, ppb))
        self._update_scrollbar()
        self.scrollbar.setValue(int(max(0.0, t / self.part.beat * self.ppb - (anchor_x - LABEL_W))))
        self.update()

    def show_time(self, t):
        """Scroll so time t is on screen (used to follow the playhead)."""
        x = self.x_of(t)
        if x < LABEL_W + 20 or x > self.width() - 40:
            self.scrollbar.setValue(int(t / self.part.beat * self.ppb - 60))

    # ---------- geometry ----------

    def lane_h(self):
        return max(26.0, (self.height() - RULER_H - BOTTOM_PAD - self.scrollbar.height()) / len(LANES))

    def lane_rect(self, i):
        h = self.lane_h()
        return QRectF(0, RULER_H + i * h, self.width(), h)

    def lane_at(self, y):
        i = int((y - RULER_H) // self.lane_h())
        return i if 0 <= i < len(LANES) else None

    def x_of(self, t):
        return LABEL_W + t / self.part.beat * self.ppb - self.scroll_x

    def time_at(self, x):
        return (x - LABEL_W + self.scroll_x) / self.ppb * self.part.beat

    def bar_at(self, x):
        return max(0, int(self.time_at(x) // self.part.bar))

    def base_w(self):
        return max(6.0, min(26.0, self.ppb / 4 * 0.7))

    def note_rect(self, n, dt=0.0, dlane=0):
        i = min(len(LANES) - 1, max(0, LANES.index(n.lane) + dlane))
        r = self.lane_rect(i)
        return gem_rect(self.x_of(n.t + dt), r.center().y(), self.base_w(), r.height(), self._dyn.get(n, "normal"))

    def visible_notes(self):
        t0, t1 = self.time_at(LABEL_W - 30), self.time_at(self.width() + 30)
        lo, hi = bisect.bisect_left(self._times, t0), bisect.bisect_right(self._times, t1)
        return self.part.notes[lo:hi]

    def note_at(self, pos):
        i = self.lane_at(pos.y())
        if i is None or pos.x() < LABEL_W:
            return None
        hits = [n for n in self.visible_notes()
                if n.lane == LANES[i] and self.note_rect(n).adjusted(-3, -4, 3, 4).contains(pos)]
        return min(hits, key=lambda n: abs(self.x_of(n.t) - pos.x())) if hits else None

    def step(self):
        return 4 * self.part.beat / self.grid if self.grid else self.part.beat / 8

    # ---------- painting ----------

    def resizeEvent(self, e):
        h = self.scrollbar.sizeHint().height()
        self.scrollbar.setGeometry(LABEL_W, self.height() - h, self.width() - LABEL_W, h)
        if self.part:
            self._update_scrollbar()
        super().resizeEvent(e)

    def update(self, *args):
        """Something besides the playhead changed: the grid image is drawn again (see set_playhead)."""
        self._static = None
        super().update(*args)

    def set_playhead(self, t):
        """Move the playhead without redrawing the grid (the notes are many when zoomed out, and
        drawing them every frame starves the audio)."""
        self.playhead = t
        super().update()

    def paintEvent(self, _):
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), dpr)
        if self._static is None or self._static_key != key:
            self._static = QPixmap(round(self.width() * dpr), round(self.height() * dpr))
            self._static.setDevicePixelRatio(dpr)
            self._static_key = key
            p = QPainter(self._static)
            self._paint_static(p)
            p.end()
        p = QPainter(self)
        p.drawPixmap(0, 0, self._static)
        if self.part and self.playhead is not None:
            x = self.x_of(self.playhead)
            if x >= LABEL_W:
                p.setPen(QPen(qc(theme.TEXT, 0.9), 2))
                p.drawLine(QPointF(x, RULER_H - 8), QPointF(x, self.lane_rect(len(LANES) - 1).bottom()))
        p.end()

    def _paint_static(self, p):
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), qc(theme.BG))
        if not self.part:
            return
        bottom = self.lane_rect(len(LANES) - 1).bottom()
        for i, lane in enumerate(LANES):
            r = self.lane_rect(i)
            p.fillRect(r, qc("#ffffff", 0.025 if i % 2 == 0 else 0.0))
        p.setClipRect(QRectF(LABEL_W, 0, self.width() - LABEL_W, self.height()))
        self._paint_ruler(p)
        self._paint_grid(p, bottom)
        self._paint_notes(p)
        if self._drag and self._drag[0] == "band":
            p.setPen(QPen(qc(theme.ACCENT, 0.9), 1, Qt.DashLine))
            p.setBrush(qc(theme.ACCENT, 0.10))
            p.drawRect(self._drag[1])
        x = self.x_of(self.cursor)
        p.setPen(QPen(qc(theme.ACCENT, 0.9), 2))
        p.drawLine(QPointF(x, RULER_H - 8), QPointF(x, bottom))
        p.setClipping(False)
        self._paint_labels(p, bottom)

    def _paint_ruler(self, p):
        part = self.part
        p.fillRect(QRectF(LABEL_W, 0, self.width(), RULER_H - 4), qc(theme.PANEL_2))
        sel = self._drag[1:] if self._drag and self._drag[0] == "bars" else self.sel_bars
        if sel:
            a, b = sorted(sel)
            x0, x1 = self.x_of(a * part.bar), self.x_of((b + 1) * part.bar)
            p.fillRect(QRectF(x0, 0, x1 - x0, RULER_H - 4), qc(theme.ACCENT, 0.30))
        p.setFont(QFont("Segoe UI", 8))
        p.setPen(qc(theme.MUTED))
        first, last = self.bar_at(LABEL_W), self.bar_at(self.width()) + 1
        every = max(1, math.ceil(40 / (4 * self.ppb)))  # keep the numbers from overlapping
        for b in range(first, min(last, self.total_bars()) + 1):
            if b % every == 0:
                p.drawText(QPointF(self.x_of(b * part.bar) + 4, RULER_H - 11), str(b + 1))

    def _paint_grid(self, p, bottom):
        part = self.part
        t0, t1 = self.time_at(LABEL_W), self.time_at(self.width())
        end = self.total_bars() * part.bar
        click = part.beat * pulse(part.meter)[0]  # stronger lines on the counted beats (dotted quarters in 6/8)
        sub = self.step() if self.grid and self.step() * self.ppb / part.beat >= 7 else min(part.beat, click)
        k = max(0, math.floor(t0 / sub))
        while k * sub <= min(t1, end):
            t = k * sub
            clicks, bars = t / click, t / part.bar
            on_beat = abs(clicks - round(clicks)) < 1e-6
            downbeat = abs(bars - round(bars)) < 1e-6
            p.setPen(QPen(qc("#ffffff", 0.22 if downbeat else 0.08 if on_beat else 0.035), 2 if downbeat else 1))
            p.drawLine(QPointF(self.x_of(t), RULER_H - (8 if downbeat else 0)), QPointF(self.x_of(t), bottom))
            k += 1

    def _paint_notes(self, p):
        moving = self._drag if self._drag and self._drag[0] == "move" else None
        size = min(6.0, self.lane_h() * 0.09)
        for n in self.visible_notes():
            color = LANE_COLORS[n.lane]
            dyn = self._dyn.get(n, "normal")
            rect = self.note_rect(n)
            sel = n in self.selected
            if moving and sel:  # the original place, faded
                p.setPen(QPen(qc(color, 0.4), 1, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(rect, 4, 4)
                continue
            gem_style(p, color, dyn)
            p.drawRoundedRect(rect, 4, 4)
            if sel:
                p.setPen(QPen(qc(theme.ACCENT), 2.5))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), 6, 6)
            if rect.height() > 14:
                note_marks(p, _Shown(dyn, n.open), rect, size)
        if moving:
            _, dt, dlane = moving
            for n in self.selected:
                rect = self.note_rect(n, dt, dlane)
                lane = LANES[min(len(LANES) - 1, max(0, LANES.index(n.lane) + dlane))]
                gem_style(p, LANE_COLORS[lane], self._dyn.get(n, "normal"))
                p.drawRoundedRect(rect, 4, 4)
                p.setPen(QPen(qc(theme.ACCENT), 2.5))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), 6, 6)

    def _paint_labels(self, p, bottom):
        p.fillRect(QRectF(0, 0, LABEL_W, self.height()), qc(theme.BG))
        p.setFont(QFont("Segoe UI", 9))
        for i, lane in enumerate(LANES):
            r = self.lane_rect(i)
            p.setPen(Qt.NoPen)
            p.setBrush(qc(LANE_COLORS[lane]))
            p.drawEllipse(QPointF(14, r.center().y()), 5, 5)
            p.setPen(qc(theme.TEXT))
            p.drawText(QRectF(26, r.top(), LABEL_W - 28, r.height()), Qt.AlignVCenter | Qt.AlignLeft,
                       LANE_NAMES[lane])
        p.setPen(QPen(qc(theme.BORDER), 1))
        p.drawLine(QPointF(LABEL_W, 0), QPointF(LABEL_W, bottom))

    # ---------- mouse ----------

    def mousePressEvent(self, e):
        if not self.part:
            return
        pos = e.position()
        self.setFocus()
        if pos.x() < LABEL_W:
            return
        if e.button() == Qt.RightButton:
            n = self.note_at(pos)
            if n is not None:
                if n not in self.selected:
                    self.selected = {n}
                    self.selection_changed.emit()
                    self.update()
                self.parent_page().note_menu(e.globalPosition().toPoint(), n)
            return
        if e.button() != Qt.LeftButton:
            return
        area = "ruler" if pos.y() < RULER_H else "lanes"
        note = self.note_at(pos) if area == "lanes" else None
        if note is not None:
            if e.modifiers() & Qt.ControlModifier:
                self.selected ^= {note}
            elif note not in self.selected:
                self.selected = {note}
            self.selection_changed.emit()
            self.update()
        self._press = (pos, note, area, bool(e.modifiers() & Qt.ControlModifier))

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._press is None:
            over = pos.x() >= LABEL_W and (pos.y() < RULER_H or self.note_at(pos) is not None)
            self.setCursor(Qt.PointingHandCursor if over else Qt.CrossCursor if pos.x() >= LABEL_W
                           else Qt.ArrowCursor)
            return
        start, note, area, _ctrl = self._press
        if self._drag is None and (pos - start).manhattanLength() < DRAG_PX:
            return
        if area == "ruler":
            self._drag = ("bars", self.bar_at(start.x()), self.bar_at(pos.x()))
        elif note is not None and note in self.selected:
            dt_raw = (pos.x() - start.x()) / self.ppb * self.part.beat
            if len(self.selected) == 1 and self.grid:  # one note: snap its new position
                dt = self.part.snap(note.t + dt_raw, self.grid) - note.t
            else:                                      # several: move by whole grid steps, keep their feel
                dt = round(dt_raw / self.step()) * self.step()
            dlane = round((pos.y() - start.y()) / self.lane_h())
            self._drag = ("move", dt, dlane)
        else:
            self._drag = ("band", QRectF(start, pos).normalized())
        self.update()

    def mouseReleaseEvent(self, e):
        if self._press is None:
            return
        start, note, area, ctrl = self._press
        drag, self._press, self._drag = self._drag, None, None
        part = self.part
        self._just_added = None
        if drag is None:  # a click
            if note is not None and not ctrl and len(self.selected) > 1:
                self.selected = {note}
                self.selection_changed.emit()
            if area == "ruler":
                self.cursor = self.bar_at(start.x()) * part.bar
                self.sel_bars = None
                self.cursor_moved.emit()
            elif note is None:
                i = self.lane_at(start.y())
                if i is not None:
                    added = part.add(part.snap(self.time_at(start.x()), self.grid), LANES[i])
                    if added:
                        self._just_added = added
                        self.selected = {added}
                        self.changed.emit()
                    elif not ctrl:
                        self.selected = set()
                    self.selection_changed.emit()
        elif drag[0] == "bars":
            a, b = sorted(drag[1:])
            self.sel_bars = (a, b)
            self.cursor = a * part.bar
            self.cursor_moved.emit()
        elif drag[0] == "move":
            _, dt, dlane = drag
            if dt or dlane:
                self.selected = set(part.move(list(self.selected), dt, dlane))
                self.changed.emit()
        elif drag[0] == "band":
            rect = drag[1]
            band = {n for n in self.visible_notes() if rect.intersects(self.note_rect(n))}
            self.selected = (self.selected | band) if ctrl else band
            self.selection_changed.emit()
        self.refresh()

    def mouseDoubleClickEvent(self, e):
        n = self.note_at(e.position())
        if n is not None and n != self._just_added:
            self.part.remove([n])
            self.selected.discard(n)
            self.changed.emit()
            self.refresh()

    def wheelEvent(self, e):
        if not self.part:
            return
        d = e.angleDelta().y() or e.angleDelta().x()
        if e.modifiers() & Qt.ControlModifier:
            self.set_zoom(self.ppb * (1.15 if d > 0 else 1 / 1.15), e.position().x())
        else:
            self.scrollbar.setValue(int(self.scroll_x - d / 120 * self.ppb * 2))

    def parent_page(self):
        w = self.parent()
        while w is not None and not isinstance(w, EditorPage):
            w = w.parent()
        return w


class _Shown:
    """What note_marks needs to draw a note's marks: its dynamic and open flag."""

    def __init__(self, dyn, open_):
        self.dyn, self.open = dyn, open_


class TempoDialog(QDialog):
    """Fix the tempo (notes keep their place in the song) and move the whole part (where bar 1 starts)."""

    def __init__(self, part, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tempo and bar 1")
        self.part = part
        self.move_by = 0.0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(10)
        lay.addWidget(QLabel("Tempo", objectName="h2"))
        row = QHBoxLayout()
        self.bpm = QDoubleSpinBox(decimals=1, minimum=30, maximum=300)
        self.bpm.setValue(round(part.bpm, 1))
        self.bpm.setFixedWidth(100)
        row.addWidget(self.bpm)
        row.addWidget(QLabel("BPM   Try:"))
        for text, factor in TEMPO_FIXES:
            b = QPushButton(f"{text}  {part.bpm * factor:.0f}")
            b.clicked.connect(lambda _=False, v=part.bpm * factor: self.bpm.setValue(round(v, 1)))
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        lay.addWidget(QLabel("Time signature", objectName="h2"))
        row = QHBoxLayout()
        self.meter = QComboBox(editable=True)
        self.meter.addItems(COMMON_METERS if part.meter in COMMON_METERS else [part.meter] + COMMON_METERS)
        self.meter.setCurrentText(part.meter)
        self.meter.setFixedWidth(100)
        self.meter.setToolTip("Beats per bar / note value, e.g. 3/4 for a waltz, 6/8 or 12/8 for a swaying feel. "
                              "Type any other, like 11/8")
        row.addWidget(self.meter)
        row.addStretch()
        lay.addLayout(row)
        lay.addWidget(QLabel("The notes stay where they are in the song; only the bar lines change.",
                             objectName="muted", wordWrap=True))
        lay.addWidget(QLabel("Move everything", objectName="h2"))
        row = QHBoxLayout()
        for text, beats in (("◀ 1 beat", -1), ("◀ 1/16", -0.25), ("1/16 ▶", 0.25), ("1 beat ▶", 1)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, k=beats: self._nudge(k))
            row.addWidget(b)
        self.moved = QLabel(objectName="muted")
        row.addWidget(self.moved)
        row.addStretch()
        lay.addLayout(row)
        lay.addWidget(QLabel("Use this if beat 1 isn't on the bar lines. The song audio moves with the notes, so "
                             "they stay together. Tip: right-click a note → \"Set bar 1 here\".",
                             objectName="muted", wordWrap=True))
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Apply")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        lay.addLayout(buttons)
        self._nudge(0)

    def _nudge(self, beats):
        self.move_by += beats * self.part.beat
        sixteenths = self.move_by / (self.part.beat / 4)
        self.moved.setText(f"Moved: {sixteenths:+g} sixteenths" if abs(sixteenths) > 1e-6 else "")


class EditorPage(QWidget):
    back = Signal()
    saved = Signal(object)      # Path of the saved MIDI
    practise = Signal(object)   # Path

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.part = None
        self.session = None
        self._audio_state = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 20, 28, 16)
        lay.setSpacing(10)

        top = QHBoxLayout()
        self.back_btn = icon_button("back", "Songs", flat=True)
        self.back_btn.clicked.connect(self._go_back)
        top.addWidget(self.back_btn)
        top.addSpacing(6)
        self.title = ElidedLabel(objectName="h2")
        top.addWidget(self.title)
        self.info = ElidedLabel(objectName="muted")
        top.addWidget(self.info)
        top.addStretch()
        self.practise_btn = QPushButton("  Practise", objectName="primary")
        self.practise_btn.setIcon(icon("play", "#1a0f0b", 14))
        self.practise_btn.clicked.connect(self._practise)
        top.addWidget(self.practise_btn)
        lay.addLayout(top)

        toolbar = QFrame(objectName="bar")
        tl = QVBoxLayout(toolbar)
        tl.setContentsMargins(10, 8, 10, 8)
        bar = FlowRow(spacing=8)
        tl.addWidget(bar)
        self.play_btn = icon_button("play", "Play",
                                    tip="Play from the orange cursor, or loop the bars selected on the ruler (Space)")
        self.play_btn.clicked.connect(self.toggle_play)
        bar.addWidget(self.play_btn)
        self.click_btn = icon_button("metronome", "Click", tip="Metronome while playing back", checkable=True)
        bar.addWidget(self.click_btn)
        bar.addSpacing(14)
        bar.addWidget(QLabel("Snap", objectName="muted"))
        self.snap = QComboBox()
        for name, _ in SNAPS:
            self.snap.addItem(name)
        self.snap.setCurrentIndex(2)
        self.snap.currentIndexChanged.connect(lambda i: setattr(self.grid, "grid", SNAPS[i][1]) or self.grid.update())
        bar.addWidget(self.snap)
        bar.addWidget(QLabel("Zoom", objectName="muted"))
        self.zoom = QSlider(Qt.Horizontal)
        self.zoom.setRange(15, 260)
        self.zoom.setValue(70)
        self.zoom.setFixedWidth(110)
        self.zoom.valueChanged.connect(lambda v: self.grid.part and self.grid.set_zoom(v))
        bar.addWidget(self.zoom)
        bar.addSpacing(14)
        self.undo_btn = icon_button("undo", tip="Undo (Ctrl+Z)")
        self.undo_btn.clicked.connect(self.undo)
        self.redo_btn = icon_button("redo", tip="Redo (Ctrl+Y)")
        self.redo_btn.clicked.connect(self.redo)
        tempo = icon_button("metronome", "Tempo && bar 1...",
                            tip="Fix the tempo or time signature, or move where bar 1 starts")
        tempo.clicked.connect(self.edit_tempo)
        for b in (self.undo_btn, self.redo_btn, tempo):
            bar.addWidget(b)
        bar.addSpacing(14)
        self.revert_btn = QPushButton("Revert to converted", objectName="flat")
        self.revert_btn.setToolTip("Throw away all edits and go back to the converter's version")
        self.revert_btn.clicked.connect(self.revert)
        bar.addWidget(self.revert_btn)
        self.save_btn = QPushButton("Save")
        self.save_btn.setObjectName("primary")
        self.save_btn.setToolTip("Save (Ctrl+S)")
        self.save_btn.clicked.connect(self.save)
        bar.addWidget(self.save_btn)
        self.help_btn = icon_button("help", flat=True, tip="Keys and tips")
        self.help_btn.clicked.connect(lambda: KeysPopover(EDIT_KEYS, EDIT_MOUSE, parent=self).show_under(self.help_btn))
        bar.addWidget(self.help_btn)
        lay.addWidget(toolbar)

        self.grid = EditorGrid(self)
        self.grid.changed.connect(self._changed)
        self.grid.selection_changed.connect(self._show_selection)
        self.grid.cursor_moved.connect(self._show_selection)
        lay.addWidget(self.grid, 1)

        self.status = QLabel(objectName="muted")
        lay.addWidget(self.status)

        for keys, fn in (("Ctrl+Z", self.undo), ("Ctrl+Y", self.redo), ("Ctrl+Shift+Z", self.redo),
                         ("Ctrl+S", self.save), ("Ctrl+C", self.copy_bars), ("Ctrl+V", self.paste_bars),
                         ("Ctrl+A", self.select_all)):
            QShortcut(QKeySequence(keys), self, fn, context=Qt.WidgetWithChildrenShortcut)

        for kind in (QPushButton, QComboBox, QSlider):
            for w in self.findChildren(kind):
                w.setFocusPolicy(Qt.NoFocus)  # keys (Space, arrows, Delete) always go to the grid

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self._tick)

    # ---------- loading / saving ----------

    def load(self, path):
        self.stop()
        self.part = load_part(path)
        self.grid.song_length = 0.0
        try:  # the song audio, for playback (and to show bars past the last note)
            self.ctx.audio.load_backing(self.part.backing, self.part.backing_offset)
            if self.ctx.audio.backing is not None:
                self.grid.song_length = len(self.ctx.audio.backing[0]) / self.ctx.audio.sr - self.part.backing_offset
        except Exception:
            self.ctx.audio.load_backing(None, 0)
        self.grid.set_part(self.part)
        self.grid.set_zoom(self.zoom.value())
        self.title.setText(self.part.title)
        self._changed(edited=False)
        self.grid.setFocus()

    def _changed(self, edited=True):
        part = self.part
        if part is None:
            return
        self.grid.refresh()
        self.info.setText(f"{part.bpm:.1f} BPM  ·  {part.meter}  ·  {part.bars} bars  ·  {len(part.notes)} notes"
                          + ("  ·  edited, not saved" if part.dirty else ""))
        self.save_btn.setEnabled(part.dirty)
        self.undo_btn.setEnabled(part.can_undo())
        self.redo_btn.setEnabled(part.can_redo())
        self.revert_btn.setVisible(part.has_backup())
        self._show_selection()
        if edited and self.session:  # hear the edit straight away
            self.play(restart=True)

    def save(self):
        if self.part and self.part.dirty:
            self.part.save()
            self._changed(edited=False)
            self.saved.emit(self.part.path)

    def revert(self):
        ans = QMessageBox.question(self, "Revert to converted",
                                   "Throw away all your edits to this song and go back to the converter's version?")
        if ans == QMessageBox.Yes:
            self.stop()
            path = self.part.path
            self.part.revert()
            self.load(path)
            self.saved.emit(path)

    def confirm_leave(self):
        """True if it's fine to leave the page (saved, discarded or nothing to save)."""
        if not (self.part and self.part.dirty):
            return True
        ans = QMessageBox.question(self, "Unsaved edits", f"Save your edits to \"{self.part.title}\"?",
                                   QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if ans == QMessageBox.Save:
            self.save()
            return True
        if ans == QMessageBox.Discard:
            self.part = load_part(self.part.path)
            return True
        return False

    def _go_back(self):
        if self.confirm_leave():
            self.stop()
            self.back.emit()

    def _practise(self):
        if self.confirm_leave():
            self.stop()
            self.practise.emit(self.part.path)

    # ---------- editing commands ----------

    def _sel(self):
        return sorted(self.grid.selected, key=lambda n: n.t)

    def _apply(self, new):
        self.grid.selected = set(new)
        self._changed()

    def undo(self):
        if self.part and self.part.can_undo():
            self._keeping_selection(self.part.undo)

    def redo(self):
        if self.part and self.part.can_redo():
            self._keeping_selection(self.part.redo)

    def _keeping_selection(self, fn):
        """Run an undo/redo, then reselect the notes still at the same time on the same drum."""
        keys = {(round(n.t, 4), n.lane) for n in self.grid.selected}
        fn()
        self.grid.selected = {n for n in self.part.notes if (round(n.t, 4), n.lane) in keys}
        self._changed()

    def select_all(self):
        if self.part:
            self.grid.selected = set(self.part.notes)
            self.grid.update()
            self._show_selection()

    def copy_bars(self):
        part, grid = self.part, self.grid
        if not part:
            return
        if grid.sel_bars:
            a, b = grid.sel_bars
        elif grid.selected:
            a, b = (int(min(n.t for n in grid.selected) // part.bar), int(max(n.t for n in grid.selected) // part.bar))
        else:
            return
        part.copy_bars(a, b)
        self.status.setText(f"Copied bar{'s' if b > a else ''} {a + 1}{f'-{b + 1}' if b > a else ''}. Click a bar "
                            "number to put the cursor there, then Ctrl+V to paste.")

    def paste_bars(self):
        if self.part and self.part.clipboard:
            at = int(round(self.grid.cursor / self.part.bar))
            self._apply(self.part.paste_bars(at))

    def set_dynamic(self, dyn):
        if self.grid.selected:
            self._apply(self.part.set_velocity(self._sel(), VELOCITY[dyn]))

    def set_velocity(self):
        sel = self._sel()
        if not sel:
            return
        v, ok = QInputDialog.getInt(self, "Velocity", "How hard (1 = softest, 127 = hardest):",
                                    sel[0].velocity, 1, 127)
        if ok:
            self._apply(self.part.set_velocity(sel, v))

    def toggle_open(self):
        hats = [n for n in self._sel() if n.lane == "hihat"]
        if hats:
            self._apply(self.part.set_open(hats, not all(n.open for n in hats)))

    def set_lane(self, lane):
        if self.grid.selected:
            self._apply(self.part.set_lane(self._sel(), lane))

    def delete(self):
        if self.grid.selected:
            self.part.remove(self._sel())
            self.grid.selected = set()
            self._changed()

    def nudge(self, steps=0, lanes=0):
        if self.grid.selected:
            self._apply(self.part.move(self._sel(), steps * self.grid.step(), lanes))

    def bar_one_here(self, note):
        self.part.bar_one_at(note)
        self.grid.selected = set()
        self.grid.cursor = 0.0
        self._changed()

    def edit_tempo(self):
        if not self.part:
            return
        dlg = TempoDialog(self.part, self)
        if dlg.exec():
            if dlg.move_by:
                self.part.shift_all(dlg.move_by)
            self.part.set_bpm(dlg.bpm.value())
            self.part.set_meter(dlg.meter.currentText())
            self.grid.selected = set()
            self._changed()

    def note_menu(self, global_pos, note):
        menu = QMenu(self)
        for dyn, text in (("accent", "Accent (hit hard)   A"), ("normal", "Normal   N"), ("ghost", "Ghost (very soft)   G")):
            menu.addAction(text, lambda d=dyn: self.set_dynamic(d))
        menu.addAction("Velocity...", self.set_velocity)
        if any(n.lane == "hihat" for n in self.grid.selected):
            menu.addAction("Open / closed hi-hat   O", self.toggle_open)
        menu.addSeparator()
        move = menu.addMenu("Move to drum")
        for lane in LANES:
            act = move.addAction(LANE_NAMES[lane], lambda ln=lane: self.set_lane(ln))
            act.setEnabled(any(n.lane != lane for n in self.grid.selected))
        menu.addAction("Set bar 1 here", lambda: self.bar_one_here(note))
        menu.addSeparator()
        menu.addAction("Delete   Del", self.delete)
        menu.exec(global_pos)

    def keyPressEvent(self, e):
        key = e.key()
        if key == Qt.Key_Space:
            self.toggle_play()
        elif key in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete()
        elif key == Qt.Key_A:
            self.set_dynamic("accent")
        elif key == Qt.Key_N:
            self.set_dynamic("normal")
        elif key == Qt.Key_G:
            self.set_dynamic("ghost")
        elif key == Qt.Key_O:
            self.toggle_open()
        elif key in (Qt.Key_Left, Qt.Key_Right):
            self.nudge(steps=-1 if key == Qt.Key_Left else 1)
        elif key in (Qt.Key_Up, Qt.Key_Down):
            self.nudge(lanes=-1 if key == Qt.Key_Up else 1)
        elif key == Qt.Key_Escape:
            self.grid.selected = set()
            self.grid.sel_bars = None
            self.grid.update()
            self._show_selection()
        else:
            super().keyPressEvent(e)

    def _show_selection(self):
        part, sel = self.part, self._sel()
        if part is None:
            return
        if len(sel) == 1:
            n = sel[0]
            beats = n.t / part.beat
            bpb = part.beats_per_bar
            bar, beat = int(beats // bpb + 1e-9) + 1, beats % bpb + 1
            kind = self.grid._dyn.get(n, "normal")
            hat = (", open" if n.open else ", closed") if n.lane == "hihat" else ""
            text = f"{LANE_NAMES[n.lane]}{hat}  ·  bar {bar}, beat {beat:.2f}  ·  velocity {n.velocity} ({kind})"
        elif sel:
            text = f"{len(sel)} notes selected"
        else:
            text = "Nothing selected"
        if self.grid.sel_bars:
            a, b = self.grid.sel_bars
            bars = f"bar {a + 1}" if a == b else f"bars {a + 1}-{b + 1}"
            text += f"  ·  {bars} selected (Play loops, Ctrl+C copies)"
        text += f"  ·  cursor at bar {int(round(self.grid.cursor / part.bar)) + 1}"
        self.status.setText(text)

    # ---------- playback ----------

    def toggle_play(self):
        self.stop() if self.session else self.play()

    def play(self, restart=False):
        """Play the edited part with the song, from the cursor's bar (or loop the selected bars)."""
        if not self.part or not self.part.notes:
            return
        audio = self.ctx.audio
        resume_at = self.grid.playhead if restart and self.session else None
        if self._audio_state is None:
            self._audio_state = (audio.guide_all, audio.metronome, set(audio.muted))
        lesson = self.part.to_lesson()
        if audio.backing is not None:  # keep the song aligned after "move everything"
            audio.backing = (audio.backing[0], self.part.backing_offset)
        sel = self.grid.sel_bars
        last = max(lesson.bars, math.ceil(self.grid.song_length / lesson.bar) if self.grid.song_length else 0)
        if sel:
            bars, looping = (sel[0], sel[1] + 1), True
        else:
            start = int(round(self.grid.cursor / lesson.bar))
            if resume_at is not None:
                start = int(resume_at // lesson.bar)
            bars, looping = (min(start, last - 1), max(last, start + 1)), False
        s = Session(lesson, loop_bars=bars, looping=looping, count_in_bars=0)
        s.start(time.perf_counter() + 0.05)
        audio.guide_all, audio.metronome = True, self.click_btn.isChecked()
        audio.muted.clear()
        self.session = s
        audio.session = s
        self.play_btn.setText("Stop")
        self.play_btn.setIcon(state_icon("stop"))
        self.timer.start(15)

    def stop(self):
        audio = self.ctx.audio
        audio.session = None
        self.session = None
        self.timer.stop()
        if self._audio_state is not None:
            audio.guide_all, audio.metronome, muted = self._audio_state
            audio.muted.clear()
            audio.muted.update(muted)
            self._audio_state = None
        self.grid.playhead = None
        self.grid.update()
        self.play_btn.setText("Play")
        self.play_btn.setIcon(state_icon("play"))

    def _tick(self):
        s = self.session
        if s is None:
            return
        now = time.perf_counter()
        if any(ev[0] == "finished" for ev in s.update(now)):
            self.stop()
            return
        t = max(0.0, s.lesson_time(s.u_at(now)))
        self.grid.show_time(t)
        self.grid.set_playhead(t)

    def hideEvent(self, e):
        self.stop()
        super().hideEvent(e)
