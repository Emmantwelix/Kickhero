"""Practice screen: the lanes (with the song's progress strip on top), a transport bar at the bottom,
keyboard drumming and the results screen. Two modes: Practice (any speed, loops, wait mode) and Perform
(the whole song at 100% with no aids: the run that shows what you can play)."""

import time

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QActionGroup, QFont, QPainter
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QSizePolicy, QSlider,
                               QToolButton, QVBoxLayout, QWidget, QWidgetAction)

from ..engine.lesson import load_midi
from ..engine.session import Session
from ..lanes import LANE_NAMES
from . import theme
from .drawing import icon, qc
from .fitting import ElidedLabel
from .highway import Highway
from .widgets import KeysPopover, Popover, Segmented, StatRing, icon_button, state_icon

# Play without a kit: keyboard keys as pads
KEY_LANES = {
    Qt.Key_Space: "kick", Qt.Key_J: "snare", Qt.Key_K: "hihat", Qt.Key_L: "ride",
    Qt.Key_U: "crash", Qt.Key_I: "tom1", Qt.Key_O: "tom2", Qt.Key_P: "tom3",
}
# Speed buttons (also keys 1-4)
SPEEDS = [("Slow", 0.5), ("Medium", 0.75), ("Normal", 1.0), ("Max", 1.25)]
SPEED_KEYS = {Qt.Key_1: 0, Qt.Key_2: 1, Qt.Key_3: 2, Qt.Key_4: 3}
GRADE_TEXT = {"perfect": "Perfect", "good": "Good", "ok": "OK", "extra": "Extra hit"}
HELP_KEYS = [("Enter", "Start / stop"), ("Esc", "Stop"), ("1 – 4", "Slow, Medium, Normal, Max speed"),
             ("Space", "Kick"), ("J", "Snare"), ("K", "Hi-hat"), ("L", "Ride"), ("U", "Crash"), ("I  O  P", "Toms")]
HELP_MOUSE = ["Drag across the bar numbers above the lanes to loop those bars (double-click to clear)",
              "Click a drum's name to leave it out, its speaker to mute its sound"]

CONTROL_H = 36      # every control in the transport bar
COMPACT_W = 1180    # narrower than this, the transport's toggles show icons only (their names in tooltips)

PLAY_CSS = f"""
QPushButton#play {{ background: {theme.ACCENT}; border: none; border-radius: 26px; padding: 0; }}
QPushButton#play:hover {{ background: {theme.ACCENT_HOVER}; }}
QPushButton#play:pressed {{ background: #e86a4b; }}
"""


def labelled(title, *widgets):
    """Controls under a small caps heading, kept together on one line."""
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(5)
    v.addWidget(QLabel(title.upper(), objectName="group"))
    row = QHBoxLayout()
    row.setSpacing(6)
    for w in widgets:
        row.addWidget(w)
    v.addLayout(row)
    return box


def menu_button(icon_name, text, tip):
    """A toolbar button that opens a menu of settings."""
    b = QToolButton()
    b.setText(text + "  ▾")
    b.setIcon(state_icon(icon_name))
    b.setIconSize(QSize(16, 16))
    b.setToolTip(tip)
    b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    b.setPopupMode(QToolButton.InstantPopup)
    b.setFocusPolicy(Qt.NoFocus)
    b.setCursor(Qt.PointingHandCursor)
    b.setMenu(QMenu(b))
    return b


def volume_slider(menu, ctx, key, text):
    """A labelled 0-100% volume slider inside a menu, kept in step with the same setting elsewhere."""
    w = QWidget()
    row = QHBoxLayout(w)
    row.setContentsMargins(12, 4, 12, 4)
    row.setSpacing(10)
    name = QLabel(text)
    name.setFixedWidth(78)
    s = QSlider(Qt.Horizontal)
    s.setRange(0, 100)
    s.setFixedWidth(140)
    s.setFocusPolicy(Qt.NoFocus)  # keys stay with the practice screen (Space = kick, etc.)
    pct = QLabel(objectName="caption")
    pct.setFixedWidth(36)
    row.addWidget(name)
    row.addWidget(s)
    row.addWidget(pct)

    def show(v):
        s.blockSignals(True)
        s.setValue(round(v * 100))
        s.blockSignals(False)
        pct.setText(f"{round(v * 100)}%")
    show(ctx.settings[f"volume_{key}"])
    s.valueChanged.connect(lambda v: ctx.set_volume(key, v / 100))
    ctx.volume_changed.connect(lambda k, v: k == key and show(v))
    a = QWidgetAction(menu)
    a.setDefaultWidget(w)
    menu.addAction(a)
    return a


def setting(menu, text, tip="", checked=False):
    """A checkable menu item (works like a toggle button: toggled, isChecked, setVisible...)."""
    a = menu.addAction(text)
    a.setCheckable(True)
    a.setChecked(checked)
    a.setToolTip(tip)
    return a


class SpeedPopup(Popover):
    """A slider for any speed (30-150%, in 5% steps), opened from the button after the speed choices."""

    changed = Signal(float)

    def __init__(self, speed, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)
        row = QHBoxLayout()
        row.addWidget(QLabel("ANY SPEED", objectName="group"))
        row.addStretch()
        self.value = QLabel()
        self.value.setStyleSheet("font-weight: 600;")
        row.addWidget(self.value)
        lay.addLayout(row)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(6, 30)  # x 5% = 30% .. 150%
        self.slider.setPageStep(1)
        self.slider.setFixedWidth(260)
        self.slider.setValue(round(speed * 20))
        self.slider.valueChanged.connect(self._moved)
        lay.addWidget(self.slider)
        ends = QHBoxLayout()
        for text in ("30%", "100%", "150%"):
            ends.addWidget(QLabel(text, objectName="caption"))
            if text != "150%":
                ends.addStretch()
        lay.addLayout(ends)
        self._show(self.slider.value())

    def _show(self, v):
        self.value.setText(f"{v * 5}%")

    def _moved(self, v):
        self._show(v)
        self.changed.emit(v / 20)


class HelpPopup(KeysPopover):
    """Keys and mouse tips for the practice screen."""

    def __init__(self, parent=None):
        super().__init__(HELP_KEYS, HELP_MOUSE, "No kit? The keys above are your pads.", parent)


class GradeBar(QWidget):
    """The run's notes as one bar split by grade (perfect, good, OK, missed), extra hits after it."""

    PARTS = [("perfect", "Perfect"), ("good", "Good"), ("ok", "OK"), ("miss", "Missed")]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.counts = {}
        self.extras = 0
        self.setFixedHeight(46)
        self.setMinimumWidth(300)

    def set_counts(self, counts, extras):
        self.counts, self.extras = counts, extras
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        total = sum(self.counts.get(k, 0) for k, _ in self.PARTS) or 1
        w, x = float(self.width()), 0.0
        p.setPen(Qt.NoPen)
        p.setBrush(qc(theme.PANEL_2))
        p.drawRoundedRect(QRectF(0, 0, w, 10), 5, 5)
        p.setClipRect(QRectF(0, 0, w, 10))
        for key, _ in self.PARTS:
            n = self.counts.get(key, 0)
            seg = w * n / total
            if n:
                p.setBrush(qc(theme.GRADE_COLORS[key]))
                p.drawRect(QRectF(x, 0, seg + 0.5, 10))
            x += seg
        p.setClipping(False)
        x = 0.0
        legend = [(label, self.counts.get(key, 0), theme.GRADE_COLORS[key]) for key, label in self.PARTS]
        legend.append(("Extra", self.extras, theme.MUTED))
        bold, plain = QFont(p.font()), QFont(p.font())
        bold.setBold(True)
        for label, n, color in legend:
            p.setBrush(qc(color))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QRectF(x, 24, 8, 8))
            x += 13
            for text, font, pen in ((str(n), bold, theme.TEXT), (label, plain, theme.MUTED)):
                p.setFont(font)
                p.setPen(qc(pen))
                tw = p.fontMetrics().horizontalAdvance(text)
                p.drawText(QRectF(x, 16, tw + 2, 24), Qt.AlignLeft | Qt.AlignVCenter, text)
                x += tw + 4
            x += 14
        p.end()


class ResultsPanel(QWidget):
    """The end of a run: a dimmed screen with the score card on top."""

    retry = Signal()
    retry_slower = Signal()
    closed = Signal()
    next_lesson = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground)
        self.setStyleSheet("ResultsPanel { background: rgba(8, 9, 13, 190); }")
        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignCenter)
        self.card = QFrame(objectName="card")
        self.card.setStyleSheet(f"QFrame#card {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER}; }}")
        self.card.setFixedWidth(640)
        outer.addWidget(self.card, 0, Qt.AlignCenter)
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(32, 26, 32, 26)
        lay.setSpacing(14)

        self.headline = QLabel(objectName="h1")
        self.badge = QLabel()
        self.badge.setStyleSheet(f"background: {theme.WARN}; color: #1a1406; border-radius: 10px; padding: 3px 10px; "
                                 "font-weight: 700;")
        head = QHBoxLayout()
        head.addWidget(self.headline)
        head.addStretch()
        head.addWidget(self.badge)
        lay.addLayout(head)
        self.subtitle = QLabel(objectName="muted")
        lay.addWidget(self.subtitle)

        mid = QHBoxLayout()
        mid.setSpacing(24)
        self.ring = StatRing(132)
        mid.addWidget(self.ring)
        right = QVBoxLayout()
        right.setSpacing(10)
        self.star_row = QHBoxLayout()
        self.star_row.setSpacing(6)
        self.stars = [QLabel() for _ in range(3)]
        for s in self.stars:
            self.star_row.addWidget(s)
        self.star_row.addStretch()
        right.addLayout(self.star_row)
        self.grades = GradeBar()
        right.addWidget(self.grades)
        self.timing = QLabel(objectName="muted")
        right.addWidget(self.timing)
        right.addStretch()
        mid.addLayout(right, 1)
        lay.addLayout(mid)

        self.advice = QLabel(wordWrap=True)
        self.advice.setStyleSheet(f"background: {theme.PANEL_2}; border-radius: 10px; padding: 10px 14px; "
                                  "line-height: 140%;")
        lay.addWidget(self.advice)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.next_btn = QPushButton("Next lesson")
        self.next_btn.setObjectName("primary")
        self.next_btn.clicked.connect(self.next_lesson.emit)
        self.retry_btn = QPushButton("Try again")
        self.retry_btn.clicked.connect(self.retry.emit)
        self.slower_btn = QPushButton("Try again slower")
        self.slower_btn.clicked.connect(self.retry_slower.emit)
        done = QPushButton("Done")
        done.setObjectName("flat")
        done.clicked.connect(self.closed.emit)
        row.addWidget(done)
        row.addStretch()
        for b in (self.slower_btn, self.retry_btn, self.next_btn):
            row.addWidget(b)
        lay.addLayout(row)
        self.hide()

    def show_summary(self, s, course_status=None, open_hats=False, personal_best=False, title="", speed=1.0,
                     assisted=False):
        """course_status: None for songs, else "passed", "too_slow", "failed" or "assisted".
        open_hats: the lesson has open hi-hats (explain if the kit couldn't tell open from closed)."""
        headline = {"passed": "Lesson passed!", "too_slow": "Nice! Now at full speed",
                    "failed": "Keep going", "assisted": "Run complete"}.get(course_status)
        if headline is None:
            headline = ["Keep practising", "Good start", "Great playing", "Superb!"][s["stars"]]
        self.headline.setText(headline)
        self.badge.setText("Personal best!")
        self.badge.setVisible(personal_best)
        parts = [title] if title else []
        parts.append(f"{speed * 100:.0f}% speed")
        if assisted:
            parts.append("wait mode (not counted towards your best)")
        self.subtitle.setText("  ·  ".join(parts))
        acc = s["accuracy"]
        self.ring.set_value(acc, theme.GOOD if s["stars"] >= 3 else theme.ACCENT if s["stars"] else theme.BAD,
                            "accuracy")
        for i, lbl in enumerate(self.stars):
            lbl.setPixmap(icon("star", theme.WARN if i < s["stars"] else theme.SURFACE_3, 30))
        self.grades.set_counts(s["counts"], s["extras"])
        off = s["mean_offset_ms"]
        side = "early" if off < 0 else "late"
        self.timing.setText(f"Timing: on average {abs(off):.0f} ms {side}" if abs(off) >= 3 else
                            "Timing: right in the pocket")
        tips = self._tips(s, course_status, open_hats)
        self.advice.setText("\n".join(tips))
        self.advice.setVisible(bool(tips))
        self.next_btn.setVisible(course_status == "passed")
        self.retry_btn.setObjectName("" if course_status == "passed" else "primary")
        self.retry_btn.style().unpolish(self.retry_btn)
        self.retry_btn.style().polish(self.retry_btn)
        self.slower_btn.setVisible(speed > 0.5 and s["stars"] < 3)
        self.show()
        self.raise_()

    @staticmethod
    def _tips(s, course_status, open_hats):
        tips = []
        off = s["mean_offset_ms"]
        if off < -12:
            tips.append(f"You're rushing a little: on average {abs(off):.0f} ms early.")
        elif off > 12:
            tips.append(f"You're dragging a little: on average {off:.0f} ms late.")
        if s["weakest_lane"] and s["per_lane"][s["weakest_lane"]] < 0.85 and len(s["per_lane"]) > 1:
            tips.append(f"Weakest part: {LANE_NAMES[s['weakest_lane']]}. Try turning the other drums off "
                        "to practise it alone.")
        d = s.get("dynamics")
        if d:
            msg = f"Dynamics: {d['score'] * 100:.0f}% right."
            if d["too_soft"] >= max(1, d["too_loud"]):
                msg += " Make the accents (notes with the > sign) clearly louder than the rest."
            elif d["too_loud"]:
                msg += " Play the ghost notes (small notes) much softer, barely touching the drum."
            tips.append(msg)
        h = s.get("hihat")
        if h:
            msg = f"Hi-hat: {h['score'] * 100:.0f}% opened and closed right."
            if h["open_it"] >= max(1, h["close_it"]):
                msg += " Lift your hi-hat foot on the notes with a circle."
            elif h["close_it"]:
                msg += " Keep the hi-hat pedal pressed down except on the notes with a circle."
            tips.append(msg)
        elif open_hats:
            tips.append("Open hi-hats weren't scored: your kit didn't report the hi-hat pedal. On kits without "
                        "one, just play the circled notes on the hi-hat.")
        if s["extras"] > s["notes"] * 0.1:
            tips.append("Lots of extra hits: check the pad setup under My kit if hits land on the wrong drum.")
        if course_status == "passed":
            tips.insert(0, "The next lesson is unlocked.")
        elif course_status == "too_slow":
            tips.insert(0, "Now play it at 100% speed to unlock the next lesson.")
        elif course_status == "failed":
            tips.insert(0, "Get at least one star at 100% speed to unlock the next lesson.")
        elif course_status == "assisted":
            tips.insert(0, "Wait mode helps you learn the notes; turn it off to pass the lesson.")
        return tips


class PracticePage(QWidget):
    back = Signal()
    course_passed = Signal()       # a course run finished (course page refreshes its stars/locks)
    next_course_lesson = Signal()

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.path = None
        self.course_lesson = None   # set when playing a course lesson instead of a song
        self.lesson = None
        self.session = None
        self._played_from = None  # perf_counter when play was pressed (for practice time)
        self.loop_bars = None
        self.lanes = None
        self.perform = False        # Perform mode: whole song, 100%, no loop or wait
        self._practice_speed = 0.75
        self.setFocusPolicy(Qt.StrongFocus)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 14, 20, 16)
        root.setSpacing(12)

        # top: back, title, Practice | Perform
        top = QHBoxLayout()
        top.setSpacing(12)
        self.back_btn = icon_button("back", "Songs", flat=True)
        self.back_btn.clicked.connect(self._go_back)
        top.addWidget(self.back_btn)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title = ElidedLabel(objectName="h2")
        self.info = ElidedLabel(objectName="caption")
        titles.addWidget(self.title)
        titles.addWidget(self.info)
        top.addLayout(titles, 1)
        self.mode = Segmented(["Practice", "Perform"],
                              tips=["Any speed, loops and wait mode: work on it bit by bit",
                                    "The whole song at full speed, no help: the run that counts"])
        self.mode.set_index(0)
        self.mode.selected.connect(self._set_mode)
        top.addWidget(self.mode)
        root.addLayout(top)

        self.highway = Highway()
        self.highway.loop_selected.connect(self._loop_selected)
        self.highway.loop_cleared.connect(self._loop_cleared)
        self.highway.lane_toggled.connect(self._lane_toggled)
        self.highway.lane_muted.connect(self._lane_muted)
        root.addWidget(self.highway, 1)

        # bottom: the transport bar
        bar = QFrame(objectName="bar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(18)
        self.play_btn = QPushButton(objectName="play")
        self.play_btn.setStyleSheet(PLAY_CSS)
        self.play_btn.setFixedSize(52, 52)
        self.play_btn.setIconSize(QSize(22, 22))
        self.play_btn.setFocusPolicy(Qt.NoFocus)
        self.play_btn.setCursor(Qt.PointingHandCursor)
        self.play_btn.clicked.connect(self.toggle_play)
        lay.addWidget(self.play_btn)

        self.speed_seg = Segmented([n for n, _ in SPEEDS],
                                   tips=[f"{v * 100:.0f}% speed  (key {i + 1})" for i, (_, v) in enumerate(SPEEDS)])
        self.speed_seg.selected.connect(lambda i: self.set_speed(SPEEDS[i][1]))
        self.speed_more = icon_button("sliders", tip="Any speed: a slider from 30% to 150%", checkable=True)
        self.speed_more.clicked.connect(self._speed_popup)
        self.speed_seg.add_widget(self.speed_more)
        self.speed = 0.75
        self.speed_seg.set_index(1)
        lay.addWidget(labelled("Speed", self.speed_seg))

        self.loop_btn = icon_button("loop", "Loop", checkable=True,
                                    tip="Repeat the song, or the bars you drag-select above the lanes")
        self.wait_btn = icon_button("wait", "Wait for me", checkable=True,
                                    tip="The music stops at each note until you hit it. No timing pressure "
                                        "(these runs don't count towards your best).")
        lay.addWidget(labelled("Practice", self.loop_btn, self.wait_btn))

        self.metro_btn = icon_button("metronome", "Click", checkable=True, checked=True, tip="Metronome")
        self.sound_btn = menu_button("speaker", "Sound", "What you hear while you play")
        sound = self.sound_btn.menu()
        self.song_btn = setting(sound, "Play along with the song", checked=True,
                                tip="The song without its drums, so you are the drummer (100% speed only)")
        self.guide_btn = setting(sound, "Hear the drum part", tip="The app plays the drum part too, so you can hear how it goes")
        sound.addSeparator()
        self.song_vol = volume_slider(sound, ctx, "backing", "Song")
        volume_slider(sound, ctx, "metronome", "Click")
        volume_slider(sound, ctx, "guide", "Drum part")
        volume_slider(sound, ctx, "pads", "Pad sounds")
        lay.addWidget(labelled("Sound", self.metro_btn, self.sound_btn))
        lay.addStretch(1)

        self.options_btn = menu_button("sliders", "Options", "Scoring and practice settings")
        opts = self.options_btn.menu()
        self.auto_btn = setting(opts, "Auto speed-up while looping",
                                tip="Move up to the next speed (Slow → Medium → Normal) after every pass of 90% or better")
        self.dyn_btn = setting(opts, "Rate dynamics (accents and ghost notes)",
                               tip="Score how hard you hit: accents louder than normal, ghost notes softer")
        opts.addSeparator()
        self.timing_group = QActionGroup(self)
        self.timing_snap = setting(opts, "Timing: snapped to 1/16", checked=True,
                                   tip="Clean timing is easier to learn from")
        self.timing_feel = setting(opts, "Timing: original feel", tip="Keeps the drummer's groove")
        for a in (self.timing_snap, self.timing_feel):
            self.timing_group.addAction(a)
        self.timing_group.triggered.connect(lambda _: self.path and self.load(self.path))
        self.help_btn = icon_button("help", flat=True, tip="Keys and tips")
        self.help_btn.clicked.connect(self._show_help)
        lay.addWidget(labelled("More", self.options_btn, self.help_btn))
        # its full width mustn't set the window's minimum: narrow windows switch it to icons only instead
        bar.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        bar.setMinimumHeight(bar.sizeHint().height())
        root.addWidget(bar)
        self.speed_seg.setFixedHeight(CONTROL_H)
        self._labelled = {b: (b.text(), b.toolTip()) for b in (self.loop_btn, self.wait_btn, self.metro_btn,
                                                                self.sound_btn, self.options_btn)}
        for b in (*self._labelled, self.help_btn):
            b.setFixedHeight(CONTROL_H)
        self._compact = None
        self._show_playing(False)

        self.loop_btn.toggled.connect(self._loop_toggled)
        self.auto_btn.toggled.connect(self._restart_if_running)
        self.wait_btn.toggled.connect(self._restart_if_running)
        self.metro_btn.toggled.connect(lambda on: setattr(ctx.audio, "metronome", on))
        self.guide_btn.toggled.connect(lambda on: setattr(ctx.audio, "guide_all", on))
        self.song_btn.toggled.connect(lambda on: setattr(ctx.audio, "backing_on", on))
        self.dyn_btn.toggled.connect(self._restart_if_running)

        self.results = ResultsPanel(self)
        self.results.retry.connect(self.start)
        self.results.closed.connect(self.stop)
        self.results.retry_slower.connect(lambda: (self.set_speed(self._slower()), self.start()))
        self.results.closed.connect(self.results.hide)
        self.results.next_lesson.connect(self.next_course_lesson.emit)

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self.timer.start(8)

    # ---------- loading ----------

    def load(self, path):
        """Practise a converted song (a drum MIDI file)."""
        self.path, self.course_lesson = path, None
        self._set_lesson(load_midi(path, quantize=16 if self.timing_snap.isChecked() else 0))
        for a in (self.timing_snap, self.timing_feel):
            a.setVisible(True)
        self.back_btn.setText("Songs")

    def load_course_lesson(self, course_lesson):
        self.path, self.course_lesson = None, course_lesson
        self.set_speed(1.0)
        self._set_lesson(course_lesson.to_lesson())
        for a in (self.timing_snap, self.timing_feel):
            a.setVisible(False)
        self.back_btn.setText("Groove Lab" if course_lesson.key.startswith("groove:") else "Course")
        self.highway.status = self._idle_text()

    def _idle_text(self):
        tip = self.course_lesson.tip + "\n\n" if self.course_lesson else ""
        if self.perform:
            tip += "Perform: the whole song at full speed, no help. This is the run that counts.\n\n"
        return tip + "Press play (or Enter) when you're ready"

    @property
    def key(self):
        """What results are stored under: the song's MIDI path, or the course lesson key."""
        return self.course_lesson.key if self.course_lesson else self.path

    def _set_lesson(self, lesson):
        self.stop()
        self.lesson = lesson
        self.lanes = set(self.lesson.lanes_used)
        self.loop_bars = None
        self.highway.preview_from = 0.0
        self.highway.active_lanes = self.lanes
        self.ctx.audio.muted.clear()
        self.highway.muted = self.ctx.audio.muted
        self.title.setText(self.lesson.title)
        mins, secs = divmod(int(self.lesson.length), 60)
        meter = "" if self.lesson.meter == "4/4" else f"{self.lesson.meter}  ·  "
        self.info.setText(f"{self.lesson.bpm:.0f} BPM  ·  {meter}{mins}:{secs:02d}  ·  {self.lesson.bars} bars  ·  "
                          f"{len(self.lesson.notes)} notes")
        self.highway.set_lesson(self.lesson)
        try:
            self.ctx.audio.load_backing(self.lesson.backing, self.lesson.backing_offset)
        except Exception:
            self.ctx.audio.load_backing(None, 0)
        self.song_btn.setVisible(self.lesson.backing is not None)
        # Hide the widget too: a hidden QWidgetAction alone leaves its slider painted over the next row
        self.song_vol.setVisible(self.lesson.backing is not None)
        self.song_vol.defaultWidget().setVisible(self.lesson.backing is not None)
        self._update_song_hint()
        # Course lessons rate dynamics by default; converted songs' (and grooves') dynamics are only a guide
        self.dyn_btn.setVisible(self.lesson.has_dynamics)
        self.dyn_btn.blockSignals(True)
        self.dyn_btn.setChecked(self.lesson.has_dynamics and self.course_lesson is not None
                                and getattr(self.course_lesson, "rate_dynamics", True))
        self.dyn_btn.blockSignals(False)
        self.highway.status = self._idle_text()
        self.results.hide()

    # ---------- transport ----------

    def toggle_play(self):
        self.stop() if self.session else self.start()

    def start(self):
        if not self.lesson:
            return
        self.results.hide()
        s = Session(self.lesson, speed=self.speed, loop_bars=self.loop_bars,
                    looping=self.loop_btn.isChecked(), lanes=self.lanes, wait_mode=self.wait_btn.isChecked(),
                    auto_speed_up=self.auto_btn.isChecked(),
                    rate_dynamics=self.dyn_btn.isChecked() and self.dyn_btn.isVisible(),
                    speed_steps=[v for _, v in SPEEDS])
        self._log_time()
        s.start(time.perf_counter() + 0.15)  # small lead so the first count-in click isn't cut off
        self._played_from = time.perf_counter()
        self.session = s
        self.highway.session = s
        self.highway.status = ""
        self.highway.combo = 0
        self.ctx.audio.session = s
        self._show_playing(True)
        self.setFocus()

    def stop(self):
        self._log_time()
        self.ctx.audio.session = None
        self.session = None
        self.highway.session = None
        self.highway.status = self._idle_text() if self.lesson else ""
        self.highway.combo = 0
        self.highway.popups.clear()
        self._show_playing(False)

    def _log_time(self):
        """Add the time since play was pressed to today's practice (for the daily goal on Home)."""
        if self.session and self._played_from is not None:
            seconds = time.perf_counter() - self._played_from
            if seconds >= 2:
                self.ctx.progress.add_time(seconds)
        self._played_from = None

    def _show_playing(self, playing):
        self.play_btn.setIcon(state_icon("stop" if playing else "play", 22, off="#1a0f0b", on="#1a0f0b"))
        self.play_btn.setToolTip("Stop  (Enter)" if playing else "Play  (Enter)")

    def _restart_if_running(self, *_):
        if self.session:
            self.start()

    def _tick(self):
        s = self.session
        if s:
            for ev in s.update(time.perf_counter()):
                kind = ev[0]
                if kind == "miss":
                    self.highway.combo = 0
                elif kind == "pass" and s.looping:
                    summ = ev[2]
                    self.highway.popup(f"Pass {ev[1] + 1}: {summ['accuracy'] * 100:.0f}%  "
                                       + "★" * summ["stars"], theme.TEXT)
                elif kind == "speed":
                    self._show_speed(ev[1])
                    self.highway.popup(f"Speed up! {self._speed_name(ev[1])}", theme.ACCENT)
                elif kind == "finished":
                    self.stop()
                    self.highway.status = ""
                    speed, summ, assisted = self.speed, ev[1], s.wait_mode
                    best = self._is_personal_best(speed, summ) if summ["notes"] and not assisted else False
                    if summ["notes"]:  # nothing to play (e.g. every drum turned off) isn't a result
                        self.ctx.record_result(self.key, speed, summ, assisted=assisted)
                    status = None
                    if self.course_lesson:
                        full = speed >= 0.999
                        status = ("assisted" if assisted else "passed" if summ["stars"] and full
                                  else "too_slow" if summ["stars"] else "failed")
                        self.course_passed.emit()
                    self.results.show_summary(summ, status, "hihat" in s.lanes and self.lesson.has_open_hats,
                                              personal_best=best, title=self.lesson.title, speed=speed,
                                              assisted=assisted)
                    if self.perform:
                        self.results.slower_btn.hide()
                    self._place_results()
        if self.isVisible():
            self.highway.update()

    def _is_personal_best(self, speed, summ):
        """Better than every earlier (counted) run of this song or lesson: full speed first, then stars, accuracy."""
        if not self.key or not summ["stars"]:
            return False
        prev = self.ctx.progress.best(self.key)
        if prev is None:
            return True
        return (speed >= 0.999, summ["stars"], summ["accuracy"]) > (prev[2] >= 0.999, prev[0], prev[1])

    # ---------- hits ----------

    def on_hit(self, lane, velocity, perf, opened=None):
        s = self.session
        if s is None or not s.started:
            self.highway.flash(lane, "#ffffff")
            return
        j = s.hit(lane, perf, velocity, opened)
        if j is None:
            self.highway.flash(lane, "#ffffff")
            return
        color = theme.GRADE_COLORS.get(j.grade, theme.TEXT)
        self.highway.flash(lane, color)
        if j.grade == "extra":
            self.highway.combo = 0
            self.highway.popup("Extra", color, lane)
            return
        self.highway.combo += 1
        if j.grade == "perfect":
            text = "Perfect"
        else:
            text = f"{'Early' if j.offset < 0 else 'Late'} {abs(j.offset) * 1000:.0f} ms"
        if j.dynamic == "ok":
            text += "  ·  accent!" if self.lesson.notes[j.index].dyn == "accent" else "  ·  nice ghost"
        elif j.dynamic == "too_soft":
            text, color = text + "  ·  hit harder", theme.WARN
        elif j.dynamic == "too_loud":
            text, color = text + "  ·  softer", theme.WARN
        if j.hat == "ok" and self.lesson.notes[j.index].open:
            text += "  ·  open!"
        elif j.hat == "open_it":
            text, color = text + "  ·  open it", theme.WARN
        elif j.hat == "close_it":
            text, color = text + "  ·  close it", theme.WARN
        self.highway.popup(text, color, lane)

    def keyPressEvent(self, e):
        if e.isAutoRepeat():
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.toggle_play()
        elif e.key() == Qt.Key_Escape:
            self.stop()
        elif e.key() in SPEED_KEYS and not self.perform:
            self.set_speed(SPEEDS[SPEED_KEYS[e.key()]][1])
        elif e.key() in KEY_LANES:
            lane = KEY_LANES[e.key()]
            self.ctx.keyboard_hit(lane)
        else:
            super().keyPressEvent(e)

    # ---------- controls ----------

    def _update_song_hint(self):
        if self.lesson and self.lesson.backing is not None:
            full = abs(self.speed - 1.0) < 1e-3
            self.song_btn.setText("Play along with the song" if full else "Play along with the song (100% speed only)")
            self.song_btn.setEnabled(full)

    def set_speed(self, value):
        self._show_speed(value)
        if self.session:
            self.session.set_speed(value, time.perf_counter())

    def _show_speed(self, value):
        """Light up the button for this speed; any other speed (the slider, or auto speed-up between
        presets) lights the gear button, which then shows the percentage."""
        self.speed = value
        i = next((i for i, (_, v) in enumerate(SPEEDS) if abs(v - value) < 1e-3), -1)
        self.speed_seg.set_index(i)
        self.speed_more.setChecked(i < 0)
        self.speed_more.setText("" if i >= 0 else f" {value * 100:.0f}%")
        self._update_song_hint()

    def _speed_popup(self):
        self.speed_more.setChecked(not any(abs(v - self.speed) < 1e-3 for _, v in SPEEDS))  # a click toggles it
        popup = SpeedPopup(self.speed, self)
        popup.changed.connect(self.set_speed)
        popup.show_under(self.speed_more, above=True)

    def _show_help(self):
        HelpPopup(self).show_under(self.help_btn, above=True)

    def _set_mode(self, i):
        """Practice (0) or Perform (1): Perform plays the whole song at 100% with loop, wait mode and speed
        changes locked, and puts back your practice speed when you leave it."""
        perform = i == 1
        if perform == self.perform:
            return
        self.stop()
        self.results.hide()
        self.perform = perform
        if perform:
            self._practice_speed = self.speed
            self.loop_btn.setChecked(False)   # also clears a loop selection
            self.wait_btn.setChecked(False)
            self.auto_btn.setChecked(False)
            self.set_speed(1.0)
        else:
            self.set_speed(self._practice_speed)
        for w in (self.speed_seg, self.loop_btn, self.wait_btn):
            w.setEnabled(not perform)
        self.auto_btn.setEnabled(not perform)
        self.highway.status = self._idle_text() if self.lesson else ""
        self.highway.update()

    def _slower(self):
        return max([v for _, v in SPEEDS if v < self.speed - 1e-3], default=SPEEDS[0][1])

    @staticmethod
    def _speed_name(value):
        return next((f"{n} ({v * 100:.0f}%)" for n, v in SPEEDS if abs(v - value) < 1e-3), f"{value * 100:.0f}%")

    def _loop_selected(self, a, b):
        if self.perform:
            return
        self.loop_bars = (a, b)
        self.highway.preview_from = a * self.lesson.bar
        self.loop_btn.setChecked(True)   # restarts if running
        self._restart_if_running()

    def _loop_toggled(self, on):
        if not on and self.loop_bars:  # loop off: back to the whole song, not one pass of the selection
            self._loop_cleared()
        else:
            self._restart_if_running()

    def _loop_cleared(self):
        self.loop_bars = None
        self.highway.preview_from = 0.0
        self._restart_if_running()
        self.highway.update()

    def _lane_toggled(self, lane):
        if lane in self.lanes:
            if len(self.lanes) > 1:
                self.lanes.discard(lane)
        else:
            self.lanes.add(lane)
        if self.session:
            self.start()
        self.highway.update()

    def _lane_muted(self, lane):
        """Silence a drum's playback ("Hear the part", turned-off lanes); your own pad hits still sound."""
        muted = self.ctx.audio.muted
        muted.symmetric_difference_update({lane})
        self.highway.update()

    def _go_back(self):
        self.stop()
        self.results.hide()
        self.back.emit()

    def _place_results(self):
        self.results.setGeometry(self.rect())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        compact = self.width() < COMPACT_W
        if compact != self._compact:
            self._compact = compact
            for b, (text, tip) in self._labelled.items():
                b.setText("" if compact else text)
                b.setToolTip(f"{text.replace('  ▾', '')}: {tip}" if compact else tip)
        self._place_results()

    def hideEvent(self, e):
        self.stop()
        super().hideEvent(e)

