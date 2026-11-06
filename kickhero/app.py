"""Kickhero: turn songs into drum lessons and practise them on any electronic drum kit.

    python -m kickhero.app      (or double-click Kickhero.bat)
"""

import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QButtonGroup, QHBoxLayout, QLabel, QMainWindow, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from .engine.audio import AudioEngine
from .kit.mapping import load_kit, save_kit
from .kit.midi_input import MidiInput
from .progress import Progress
from .settings import Settings
from .ui import theme
from .ui.course import CoursePage
from .ui.kit_setup import KitPage
from .ui.library import LibraryPage
from .ui.practice import PracticePage

APP_TITLE = "Kickhero"
ICON = Path(__file__).with_name("assets") / "kickhero.png"


class AppContext(QObject):
    """Shared services: settings, audio, MIDI kit, progress. Turns raw kit notes into lane hits."""

    lane_hit = Signal(str, int, float)        # lane, velocity, latency-corrected perf time
    raw_note = Signal(int, int, float, object)  # note, velocity, perf, lane ("" ignored, None unknown)

    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.progress = Progress()
        self.audio = AudioEngine()
        for key in ("metronome", "guide", "pads", "backing"):
            self.audio.volume[key] = self.settings[f"volume_{key}"]
        self.audio.start()
        self.midi = MidiInput(preferred=self.settings["midi_device"])
        self.kit = load_kit(self.settings, self.settings["midi_device"])
        self.midi.connected.connect(self._device_connected)
        self.midi.hit.connect(self._on_midi)

    def _device_connected(self, name):
        if name:
            self.settings["midi_device"] = name
            self.kit = load_kit(self.settings, name)

    def save_kit(self):
        save_kit(self.settings, self.midi.port_name or self.settings["midi_device"] or "default", self.kit)

    def _on_midi(self, note, velocity, perf):
        lane = self.kit.lane_for(note)
        self.raw_note.emit(note, velocity, perf, lane)
        if lane:
            if self.settings["pad_sounds"]:
                self.audio.play_pad(lane, velocity)
            self.lane_hit.emit(lane, velocity, perf - self.settings["latency_ms"] / 1000)

    def keyboard_hit(self, lane):
        """A computer-keyboard 'pad' (no kit needed). Always audible, no latency correction."""
        self.audio.play_pad(lane, 110)
        self.lane_hit.emit(lane, 110, time.perf_counter())

    def set_volume(self, key, value):
        self.audio.volume[key] = value
        self.settings[f"volume_{key}"] = value

    def record_result(self, lesson_path, speed, summary):
        if lesson_path:
            self.progress.record(lesson_path, speed, summary)


class MainWindow(QMainWindow):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(APP_TITLE)
        self.resize(1280, 780)

        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        side = QWidget(objectName="sidebar")
        side.setFixedWidth(190)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 12)
        sl.setSpacing(2)
        sl.addWidget(QLabel("Kickhero", objectName="appname"))
        self.stack = QStackedWidget()
        self.library = LibraryPage(ctx)
        self.course = CoursePage(ctx)
        self.practice = PracticePage(ctx)
        self.kit = KitPage(ctx)
        for page in (self.library, self.course, self.practice, self.kit):
            self.stack.addWidget(page)

        self.nav = QButtonGroup(self)
        self.nav_for = {}
        for text, page in (("Songs", self.library), ("Course", self.course), ("My kit", self.kit)):
            b = QPushButton(text, objectName="nav", checkable=True)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, p=page: self.stack.setCurrentWidget(p))
            self.nav.addButton(b)
            self.nav_for[page] = b
            sl.addWidget(b)
        self.nav_for[self.library].setChecked(True)
        sl.addStretch()
        self.streak = QLabel(objectName="muted")
        self.streak.setContentsMargins(16, 0, 16, 0)
        sl.addWidget(self.streak)
        self.device = QLabel(objectName="muted", wordWrap=True)
        self.device.setContentsMargins(16, 0, 16, 0)
        sl.addWidget(self.device)
        h.addWidget(side)
        h.addWidget(self.stack, 1)

        self.library.practise.connect(self.open_lesson)
        self.course.play.connect(self.open_course_lesson)
        self.practice.back.connect(self._back_from_practice)
        self.practice.next_course_lesson.connect(self._next_course_lesson)
        ctx.lane_hit.connect(self._lane_hit)
        ctx.raw_note.connect(self.kit.on_note)
        ctx.midi.connected.connect(self._show_device)
        self._show_device(ctx.midi.port_name)
        self._show_streak()
        if ctx.audio.error:
            self.statusBar().showMessage(f"No sound output: {ctx.audio.error}")

    def open_lesson(self, path):
        self.practice.load(path)
        self.stack.setCurrentWidget(self.practice)
        self.practice.setFocus()

    def open_course_lesson(self, lesson):
        self.practice.load_course_lesson(lesson)
        self.stack.setCurrentWidget(self.practice)
        self.practice.setFocus()

    def _next_course_lesson(self):
        current = self.practice.course_lesson
        nxt = self.course.lesson_after(current) if current else None
        if nxt:
            self.open_course_lesson(nxt)
        else:
            self._back_from_practice()

    def _back_from_practice(self):
        page = self.course if self.practice.course_lesson else self.library
        self.stack.setCurrentWidget(page)
        self.nav_for[page].setChecked(True)
        self._show_streak()

    def _lane_hit(self, lane, velocity, perf):
        if self.stack.currentWidget() is self.practice:
            self.practice.on_hit(lane, velocity, perf)

    def _show_device(self, name):
        self.device.setText(f"🥁  {name}" if name else "No kit connected")

    def _show_streak(self):
        n = self.ctx.progress.streak()
        self.streak.setText(f"🔥  {n}-day streak" if n else "")

    def closeEvent(self, e):
        if not self.library.confirm_close():
            e.ignore()
            return
        self.ctx.audio.stop()
        self.ctx.midi.close()
        super().closeEvent(e)


def use_bundled_ffmpeg():
    """The packaged app ships ffmpeg (needed by the stem separator); put it first on PATH.
    Child processes (the converter) inherit it."""
    import os

    bundled = Path(getattr(sys, "_MEIPASS", "")) / "ffmpeg"
    if getattr(sys, "frozen", False) and (bundled / "ffmpeg.exe").exists():
        os.environ["PATH"] = str(bundled) + os.pathsep + os.environ.get("PATH", "")


def main():
    use_bundled_ffmpeg()
    if "--pipeline" in sys.argv:  # packaged app re-launched as the converter (see pipeline/worker.py)
        from .pipeline import song2drums

        sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:] if a != "--pipeline"]
        song2drums.main()
        return
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setWindowIcon(QIcon(str(ICON)))
    app.setStyleSheet(theme.STYLESHEET)
    ctx = AppContext()
    win = MainWindow(ctx)
    win.show()
    ctx.midi.rescan()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
