"""Practice screen: controls, the scrolling lanes, keyboard drumming and the results panel."""

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout,
                               QWidget)

from ..engine.lesson import load_midi
from ..engine.session import Session
from ..lanes import LANE_NAMES
from . import theme
from .highway import Highway

# Play without a kit: keyboard keys as pads
KEY_LANES = {
    Qt.Key_Space: "kick", Qt.Key_J: "snare", Qt.Key_K: "hihat", Qt.Key_L: "ride",
    Qt.Key_U: "crash", Qt.Key_I: "tom1", Qt.Key_O: "tom2", Qt.Key_P: "tom3",
}
GRADE_TEXT = {"perfect": "Perfect", "good": "Good", "ok": "OK", "extra": "Extra hit"}


def toggle(text, checked=False, tip=""):
    b = QPushButton(text)
    b.setCheckable(True)
    b.setChecked(checked)
    b.setToolTip(tip)
    b.setFocusPolicy(Qt.NoFocus)
    return b


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

    def show_summary(self, s, course_status=None):
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
        back = self.back_btn = QPushButton("←  Songs")
        back.setFocusPolicy(Qt.NoFocus)
        back.clicked.connect(self._go_back)
        self.title = QLabel(objectName="h2")
        self.info = QLabel(objectName="muted")
        top.addWidget(back)
        top.addSpacing(10)
        top.addWidget(self.title)
        top.addSpacing(10)
        top.addWidget(self.info)
        top.addStretch()
        root.addLayout(top)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.play_btn = QPushButton("▶  Start")
        self.play_btn.setObjectName("primary")
        self.play_btn.setFocusPolicy(Qt.NoFocus)
        self.play_btn.clicked.connect(self.toggle_play)
        bar.addWidget(self.play_btn)
        bar.addSpacing(12)
        bar.addWidget(QLabel("Speed"))
        self.speed = QSlider(Qt.Horizontal)
        self.speed.setRange(8, 30)  # x5% -> 40..150%
        self.speed.setValue(14)
        self.speed.setFixedWidth(150)
        self.speed.setFocusPolicy(Qt.NoFocus)
        self.speed.valueChanged.connect(self._speed_changed)
        self.speed_label = QLabel("70%")
        self.speed_label.setFixedWidth(42)
        bar.addWidget(self.speed)
        bar.addWidget(self.speed_label)
        bar.addSpacing(12)
        self.loop_btn = toggle("Loop", tip="Repeat the song, or the bars you drag-select on the strip above the lanes")
        self.auto_btn = toggle("Auto speed-up", tip="While looping: +5% speed after every pass of 90% or better")
        self.wait_btn = toggle("Wait for me", tip="The music stops at each note until you hit it. No timing pressure.")
        self.metro_btn = toggle("Metronome", True)
        self.guide_btn = toggle("Hear the part", tip="The app plays the drum part too, so you can hear how it goes")
        self.song_btn = toggle("Song", True, tip="Play the song without its drums, so you are the drummer "
                                                 "(plays at 100% speed only)")
        for b in (self.loop_btn, self.auto_btn, self.wait_btn, self.metro_btn, self.guide_btn, self.song_btn):
            bar.addWidget(b)
        self.loop_btn.toggled.connect(self._restart_if_running)
        self.auto_btn.toggled.connect(self._restart_if_running)
        self.wait_btn.toggled.connect(self._restart_if_running)
        self.metro_btn.toggled.connect(lambda on: setattr(ctx.audio, "metronome", on))
        self.guide_btn.toggled.connect(lambda on: setattr(ctx.audio, "guide_all", on))
        self.song_btn.toggled.connect(lambda on: setattr(ctx.audio, "backing_on", on))
        bar.addStretch()
        self.timing = QComboBox()
        self.timing.addItems(["Clean timing (snapped to 1/16)", "Original feel"])
        self.timing.setFocusPolicy(Qt.NoFocus)
        self.timing.setToolTip("Clean timing is easier to learn from; original feel keeps the drummer's groove")
        self.timing.currentIndexChanged.connect(lambda _: self.path and self.load(self.path))
        self.timing.setVisible(False)
        bar.addWidget(self.timing)
        root.addLayout(bar)

        self.highway = Highway()
        self.highway.loop_selected.connect(self._loop_selected)
        self.highway.loop_cleared.connect(self._loop_cleared)
        self.highway.lane_toggled.connect(self._lane_toggled)
        root.addWidget(self.highway, 1)

        hint = QLabel("Drag across bar numbers to loop them (double-click to clear)  ·  Click a drum name to turn it "
                      "off  ·  Enter = start/stop  ·  No kit? Keys: Space kick, J snare, K hi-hat, L ride, U crash, "
                      "I / O / P toms", objectName="hint", wordWrap=True)
        root.addWidget(hint)

        self.results = ResultsPanel(self)
        self.results.retry.connect(self.start)
        self.results.closed.connect(self.stop)
        self.results.retry_slower.connect(lambda: (self.speed.setValue(max(8, self.speed.value() - 2)), self.start()))
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
        self.back_btn.setText("←  Songs")

    def load_course_lesson(self, course_lesson):
        self.path, self.course_lesson = None, course_lesson
        self.speed.setValue(20)
        self._set_lesson(course_lesson.to_lesson())
        self.timing.hide()
        self.back_btn.setText("←  Course")
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
        self.highway.active_lanes = self.lanes
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
        self.highway.status = self._idle_text()
        self.results.hide()

    # ---------- transport ----------

    def toggle_play(self):
        self.stop() if self.session else self.start()

    def start(self):
        if not self.lesson:
            return
        self.results.hide()
        s = Session(self.lesson, speed=self.speed.value() * 0.05, loop_bars=self.loop_bars,
                    looping=self.loop_btn.isChecked(), lanes=self.lanes, wait_mode=self.wait_btn.isChecked(),
                    auto_speed_up=self.auto_btn.isChecked())
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
                    self.speed.blockSignals(True)
                    self.speed.setValue(round(ev[1] / 0.05))
                    self.speed.blockSignals(False)
                    self.speed_label.setText(f"{ev[1] * 100:.0f}%")
                    self._update_song_hint()
                    self.highway.popup(f"Speed up! {ev[1] * 100:.0f}%", theme.ACCENT)
                elif kind == "finished":
                    self.stop()
                    self.highway.status = ""
                    speed = self.speed.value() * 0.05
                    self.ctx.record_result(self.key, speed, ev[1])
                    status = None
                    if self.course_lesson:
                        full = speed >= 0.999
                        status = "passed" if ev[1]["stars"] and full else "too_slow" if ev[1]["stars"] else "failed"
                        self.course_passed.emit()
                    self.results.show_summary(ev[1], status)
                    self._place_results()
        if self.isVisible():
            self.highway.update()

    # ---------- hits ----------

    def on_hit(self, lane, velocity, perf):
        s = self.session
        if s is None or not s.started:
            self.highway.flash(lane, "#ffffff")
            return
        j = s.hit(lane, perf)
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
            self.highway.popup("Perfect", color, lane)
        else:
            self.highway.popup(f"{'Early' if j.offset < 0 else 'Late'} {abs(j.offset) * 1000:.0f} ms", color, lane)

    def keyPressEvent(self, e):
        if e.isAutoRepeat():
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.toggle_play()
        elif e.key() == Qt.Key_Escape:
            self.stop()
        elif e.key() in KEY_LANES:
            lane = KEY_LANES[e.key()]
            self.ctx.keyboard_hit(lane)
        else:
            super().keyPressEvent(e)

    # ---------- controls ----------

    def _update_song_hint(self):
        if self.lesson and self.lesson.backing is not None:
            full = self.speed.value() == 20
            self.song_btn.setText("Song" if full else "Song (at 100%)")
            self.song_btn.setEnabled(full)

    def _speed_changed(self, v):
        self.speed_label.setText(f"{v * 5}%")
        self._update_song_hint()
        if self.session:
            self.session.set_speed(v * 0.05, time.perf_counter())

    def _loop_selected(self, a, b):
        self.loop_bars = (a, b)
        self.loop_btn.setChecked(True)   # restarts if running
        self._restart_if_running()

    def _loop_cleared(self):
        self.loop_bars = None
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

