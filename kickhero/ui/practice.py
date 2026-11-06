"""Practice screen: controls, the scrolling lanes, keyboard drumming and the results panel."""

import time

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSlider,
                               QVBoxLayout, QWidget)

from ..engine.lesson import load_midi
from ..engine.session import Session
from ..lanes import LANE_NAMES
from . import theme
from .drawing import icon
from .highway import Highway
from .fitting import ElidedLabel, FlowRow

# Play without a kit: keyboard keys as pads
KEY_LANES = {
    Qt.Key_Space: "kick", Qt.Key_J: "snare", Qt.Key_K: "hihat", Qt.Key_L: "ride",
    Qt.Key_U: "crash", Qt.Key_I: "tom1", Qt.Key_O: "tom2", Qt.Key_P: "tom3",
}
# Speed buttons (also keys 1-4)
SPEEDS = [("Slow", 0.5), ("Medium", 0.75), ("Normal", 1.0), ("Max", 1.25)]
SPEED_KEYS = {Qt.Key_1: 0, Qt.Key_2: 1, Qt.Key_3: 2, Qt.Key_4: 3}
GRADE_TEXT = {"perfect": "Perfect", "good": "Good", "ok": "OK", "extra": "Extra hit"}


def toggle(text, checked=False, tip=""):
    b = QPushButton(text)
    b.setCheckable(True)
    b.setChecked(checked)
    b.setToolTip(tip)
    b.setFocusPolicy(Qt.NoFocus)
    return b


LEAD_W = 128    # Start and the back button: the same width, so the song title lines up above Speed
TOOL_GAP = 8    # between toolbar items
GROUP_GAP = 16  # extra space between toolbar groups


def group(title, *widgets):
    """A labelled group of controls that stays on one line when the toolbar wraps."""
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    label = QLabel(title, objectName="group")
    lay.addWidget(label)
    lay.addSpacing(2)
    for w in widgets:
        lay.addWidget(w)
    return box


class SpeedPopup(QFrame):
    """A slider for any speed (30-150%, in 5% steps), opened from the gear after the speed buttons."""

    changed = Signal(float)

    def __init__(self, speed, parent=None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("card")
        self.setAttribute(Qt.WA_DeleteOnClose)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)
        row = QHBoxLayout()
        row.addWidget(QLabel("Speed", objectName="group"))
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
            ends.addWidget(QLabel(text, objectName="muted"))
            if text != "150%":
                ends.addStretch()
        lay.addLayout(ends)
        self._show(self.slider.value())

    def _show(self, v):
        self.value.setText(f"{v * 5}%")

    def _moved(self, v):
        self._show(v)
        self.changed.emit(v / 20)


class ResultsPanel(QFrame):
    retry = Signal()
    retry_slower = Signal()
    closed = Signal()
    next_lesson = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("card")
        self.setStyleSheet(f"QFrame#card {{ background: {theme.PANEL}; border: 1px solid {theme.ACCENT}; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 22, 28, 22)
        lay.setSpacing(8)
        self.stars = QLabel(alignment=Qt.AlignCenter)
        self.stars.setStyleSheet(f"font-size: 30pt; color: {theme.WARN};")
        self.accuracy = QLabel(alignment=Qt.AlignCenter)
        self.accuracy.setStyleSheet("font-size: 22pt; font-weight: 700;")
        self.counts = QLabel(alignment=Qt.AlignCenter)
        self.counts.setObjectName("muted")
        self.advice = QLabel(alignment=Qt.AlignCenter, wordWrap=True)
        for w in (self.stars, self.accuracy, self.counts, self.advice):
            lay.addWidget(w)
        row = QHBoxLayout()
        self.next_btn = QPushButton("Next lesson  ▶")
        self.next_btn.setObjectName("primary")
        self.next_btn.clicked.connect(self.next_lesson.emit)
        row.addWidget(self.next_btn)
        for text, sig in (("Try again", self.retry), ("Try again slower", self.retry_slower), ("Close", self.closed)):
            b = QPushButton(text)
            b.clicked.connect(sig.emit)
            row.addWidget(b)
        lay.addSpacing(6)
        lay.addLayout(row)
        self.setFixedWidth(560)
        self.hide()

    def show_summary(self, s, course_status=None, open_hats=False):
        """open_hats: the lesson has open hi-hats (explain if the kit couldn't tell open from closed)."""
        """course_status: None for songs, else "passed", "too_slow" or "failed"."""
        self.stars.setText("★" * s["stars"] + "☆" * (3 - s["stars"]))
        self.accuracy.setText(f"{s['accuracy'] * 100:.0f}% accuracy")
        c = s["counts"]
        self.counts.setText(f"Perfect {c['perfect']}   ·   Good {c['good']}   ·   OK {c['ok']}   ·   "
                            f"Missed {c['miss']}   ·   Extra {s['extras']}")
        tips = []
        off = s["mean_offset_ms"]
        if off < -12:
            tips.append(f"You're rushing a little: on average {abs(off):.0f} ms early.")
        elif off > 12:
            tips.append(f"You're dragging a little: on average {off:.0f} ms late.")
        else:
            tips.append("Your timing is centred nicely.")
        if s["weakest_lane"] and s["per_lane"][s["weakest_lane"]] < 0.85 and len(s["per_lane"]) > 1:
            tips.append(f"Weakest part: {LANE_NAMES[s['weakest_lane']]}. Try turning the other lanes off "
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
            tips.insert(0, "Lesson passed! The next lesson is unlocked.")
        elif course_status == "too_slow":
            tips.insert(0, "Good! Now play it at 100% speed to unlock the next lesson.")
        elif course_status == "failed":
            tips.insert(0, "Get at least one star at 100% speed to unlock the next lesson.")
        self.next_btn.setVisible(course_status == "passed")
        self.advice.setText("\n".join(tips))
        self.adjustSize()
        self.show()
        self.raise_()


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
        self.loop_bars = None
        self.lanes = None
        self.setFocusPolicy(Qt.StrongFocus)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 12)
        root.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(0)
        back = self.back_btn = QPushButton("←  Songs")
        back.setFocusPolicy(Qt.NoFocus)
        back.setFixedWidth(LEAD_W)
        back.clicked.connect(self._go_back)
        self.title = ElidedLabel(objectName="h2")
        self.info = ElidedLabel(objectName="muted")
        top.addWidget(back)
        top.addSpacing(GROUP_GAP + 2 * TOOL_GAP)  # the same gap as Start -> Speed below, so the title sits above it
        top.addWidget(self.title)
        top.addSpacing(14)
        top.addWidget(self.info)
        top.addStretch(1)
        root.addLayout(top)

        bar = FlowRow(spacing=TOOL_GAP)
        self.play_btn = QPushButton("▶  Start")
        self.play_btn.setObjectName("primary")
        self.play_btn.setFixedWidth(LEAD_W)
        self.play_btn.setFocusPolicy(Qt.NoFocus)
        self.play_btn.clicked.connect(self.toggle_play)
        bar.addWidget(self.play_btn)
        bar.addSpacing(GROUP_GAP)
        self.speed_group = QButtonGroup(self)
        self.speed_group.setExclusive(True)
        speeds = []
        for i, (name, value) in enumerate(SPEEDS):
            b = toggle(name, tip=f"{value * 100:.0f}% speed  (key {i + 1})")
            self.speed_group.addButton(b, i)
            speeds.append(b)
        self.speed_more = QPushButton()
        self.speed_more.setIcon(QIcon(icon("gear", theme.TEXT, 16)))
        self.speed_more.setToolTip("Any speed: a slider from 30% to 150%")
        self.speed_more.setCheckable(True)  # shown "on" while the speed is not one of the four buttons
        self.speed_more.setFocusPolicy(Qt.NoFocus)
        self.speed_more.clicked.connect(self._speed_popup)
        speed_box = group("Speed", *speeds, self.speed_more)
        self.speed_group.idClicked.connect(lambda i: self.set_speed(SPEEDS[i][1]))
        self.speed = 0.75
        self.speed_group.button(1).setChecked(True)
        self.loop_btn = toggle("Loop", tip="Repeat the song, or the bars you drag-select on the strip above the lanes")
        self.auto_btn = toggle("Auto speed-up", tip="While looping: move up to the next speed (Slow → Medium → Normal) after every pass of 90% or better")
        self.wait_btn = toggle("Wait for me", tip="The music stops at each note until you hit it. No timing pressure.")
        self.metro_btn = toggle("Metronome", True)
        self.guide_btn = toggle("Hear the part", tip="The app plays the drum part too, so you can hear how it goes")
        self.song_btn = toggle("Song", True, tip="Play the song without its drums, so you are the drummer "
                                                 "(plays at 100% speed only)")
        self.dyn_btn = toggle("Rate dynamics", tip="Score how hard you hit: accents (notes with the > sign) louder than normal, "
                                                   "ghost notes (hollow notes) softer")
        self.loop_btn.toggled.connect(self._restart_if_running)
        self.auto_btn.toggled.connect(self._restart_if_running)
        self.wait_btn.toggled.connect(self._restart_if_running)
        self.metro_btn.toggled.connect(lambda on: setattr(ctx.audio, "metronome", on))
        self.guide_btn.toggled.connect(lambda on: setattr(ctx.audio, "guide_all", on))
        self.song_btn.toggled.connect(lambda on: setattr(ctx.audio, "backing_on", on))
        self.dyn_btn.toggled.connect(self._restart_if_running)
        self.timing = QComboBox()
        self.timing.addItems(["Snapped to 1/16", "Original feel"])
        self.timing.setFocusPolicy(Qt.NoFocus)
        self.timing.setToolTip("Clean timing is easier to learn from; original feel keeps the drummer's groove")
        self.timing.currentIndexChanged.connect(lambda _: self.path and self.load(self.path))
        self.timing.setVisible(False)
        self.scoring = group("Scoring", self.dyn_btn, self.timing)
        # Start | Speed | Sound | Scoring | Practice. Speed and Sound are one widget, so a narrow window
        # wraps them together; Scoring follows Sound
        speed_sound = QWidget()
        pair = QHBoxLayout(speed_sound)
        pair.setContentsMargins(0, 0, 0, 0)
        pair.setSpacing(GROUP_GAP + 2 * TOOL_GAP)
        pair.addWidget(speed_box)
        pair.addWidget(group("Sound", self.metro_btn, self.guide_btn, self.song_btn))
        bar.addWidget(speed_sound)
        bar.addSpacing(GROUP_GAP)
        bar.addWidget(self.scoring)
        bar.addSpacing(GROUP_GAP)
        bar.addWidget(group("Practice", self.loop_btn, self.auto_btn, self.wait_btn))
        root.addWidget(bar)

        self.highway = Highway()
        self.highway.loop_selected.connect(self._loop_selected)
        self.highway.loop_cleared.connect(self._loop_cleared)
        self.highway.lane_toggled.connect(self._lane_toggled)
        self.highway.lane_muted.connect(self._lane_muted)
        root.addWidget(self.highway, 1)

        hint = QLabel("Drag across bar numbers to loop them (double-click to clear)  ·  Click a drum name to turn it "
                      "off, its speaker to mute it  ·  Enter = start/stop  ·  1–4 = speed  ·  No kit? Keys: Space kick, "
                      "J snare, K hi-hat, L ride, U crash, I / O / P toms", objectName="hint", wordWrap=True)
        root.addWidget(hint)

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
        self._set_lesson(load_midi(path, quantize=16 if self.timing.currentIndex() == 0 else 0))
        self.timing.show()
        self.scoring.show()
        self.back_btn.setText("←  Songs")

    def load_course_lesson(self, course_lesson):
        self.path, self.course_lesson = None, course_lesson
        self.set_speed(1.0)
        self._set_lesson(course_lesson.to_lesson())
        self.timing.hide()
        self.scoring.setVisible(self.lesson.has_dynamics)
        self.back_btn.setText("←  " + ("Groove Lab" if course_lesson.key.startswith("groove:") else "Course"))
        self.highway.status = self._idle_text()

    def _idle_text(self):
        tip = self.course_lesson.tip + "\n\n" if self.course_lesson else ""
        return tip + "Press Start (or Enter) when you're ready"

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
        self.info.setText(f"{self.lesson.bpm:.0f} BPM  ·  {self.lesson.bars} bars  ·  {mins}:{secs:02d}  ·  "
                          f"{len(self.lesson.notes)} notes")
        self.highway.set_lesson(self.lesson)
        try:
            self.ctx.audio.load_backing(self.lesson.backing, self.lesson.backing_offset)
        except Exception:
            self.ctx.audio.load_backing(None, 0)
        self.song_btn.setVisible(self.lesson.backing is not None)
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
        s.start(time.perf_counter() + 0.15)  # small lead so the first count-in click isn't cut off
        self.session = s
        self.highway.session = s
        self.highway.status = ""
        self.highway.combo = 0
        self.ctx.audio.session = s
        self.play_btn.setText("■  Stop")
        self.setFocus()

    def stop(self):
        self.ctx.audio.session = None
        self.session = None
        self.highway.session = None
        self.highway.status = self._idle_text() if self.lesson else ""
        self.highway.combo = 0
        self.highway.popups.clear()
        self.play_btn.setText("▶  Start")

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
                    speed = self.speed
                    self.ctx.record_result(self.key, speed, ev[1])
                    status = None
                    if self.course_lesson:
                        full = speed >= 0.999
                        status = "passed" if ev[1]["stars"] and full else "too_slow" if ev[1]["stars"] else "failed"
                        self.course_passed.emit()
                    self.results.show_summary(ev[1], status, "hihat" in s.lanes and self.lesson.has_open_hats)
                    self._place_results()
        if self.isVisible():
            self.highway.update()

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
        elif e.key() in SPEED_KEYS:
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
            self.song_btn.setText("Song" if full else "Song (at 100%)")
            self.song_btn.setEnabled(full)

    def set_speed(self, value):
        self._show_speed(value)
        if self.session:
            self.session.set_speed(value, time.perf_counter())

    def _show_speed(self, value):
        """Light up the button for this speed; any other speed (the slider, or auto speed-up between
        presets) lights the gear button, which then shows the percentage."""
        self.speed = value
        self.speed_group.setExclusive(False)
        preset = False
        for i, (_, v) in enumerate(SPEEDS):
            on = abs(v - value) < 1e-3
            self.speed_group.button(i).setChecked(on)
            preset |= on
        self.speed_group.setExclusive(True)
        self.speed_more.setChecked(not preset)
        self.speed_more.setText("" if preset else f" {value * 100:.0f}%")
        self._update_song_hint()

    def _speed_popup(self):
        self.speed_more.setChecked(not any(abs(v - self.speed) < 1e-3 for _, v in SPEEDS))  # a click toggles it
        popup = SpeedPopup(self.speed, self)
        popup.changed.connect(self.set_speed)
        popup.move(self.speed_more.mapToGlobal(self.speed_more.rect().bottomLeft()) + QPoint(0, 6))
        popup.show()

    def _slower(self):
        return max([v for _, v in SPEEDS if v < self.speed - 1e-3], default=SPEEDS[0][1])

    @staticmethod
    def _speed_name(value):
        return next((f"{n} ({v * 100:.0f}%)" for n, v in SPEEDS if abs(v - value) < 1e-3), f"{value * 100:.0f}%")

    def _loop_selected(self, a, b):
        self.loop_bars = (a, b)
        self.highway.preview_from = a * self.lesson.bar
        self.loop_btn.setChecked(True)   # restarts if running
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
        r = self.results
        r.move((self.width() - r.width()) // 2, (self.height() - r.height()) // 2)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_results()

    def hideEvent(self, e):
        self.stop()
        super().hideEvent(e)

