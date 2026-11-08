"""Kickhero: turn songs into drum lessons and practise them on any electronic drum kit.

    python -m kickhero.app      (or double-click Kickhero.bat)
"""

import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton,
                               QVBoxLayout, QWidget)

from .engine.audio import AudioEngine
from .kit.mapping import load_kit, save_kit
from .kit.midi_input import MidiInput
from .lanes import OPEN_HAT
from .progress import Progress
from .settings import Settings, data_dir
from .ui import theme
from .ui.course import CoursePage
from .ui.drawing import icon, stylesheet
from .ui.editor import EditorPage
from .ui.fitting import PageStack
from .ui.grooves import GroovesPage
from .ui.kit_setup import KitPage
from .ui.home import HomePage
from .ui.library import LibraryPage
from .ui.practice import PracticePage

APP_TITLE = "Kickhero"
ICON = Path(__file__).with_name("assets") / "kickhero.png"


class AppContext(QObject):
    """Shared services: settings, audio, MIDI kit, progress. Turns raw kit notes into lane hits."""

    lane_hit = Signal(str, int, float, object)  # lane, velocity, latency-corrected perf, hi-hat open (None = ?)
    raw_note = Signal(int, int, float, object)  # note, velocity, perf, lane ("" ignored, None unknown)

    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.progress = Progress()
        self.audio = AudioEngine(self.settings["sound_kit"], self.settings["custom_sounds"])
        for key in ("metronome", "guide", "pads", "backing"):
            self.audio.volume[key] = self.settings[f"volume_{key}"]
        self.audio.start()
        self.midi = MidiInput(preferred=self.settings["midi_device"])
        self.kit = load_kit(self.settings, self.settings["midi_device"])
        self.midi.connected.connect(self._device_connected)
        self.midi.hit.connect(self._on_midi)
        self.midi.pedal.connect(self._on_pedal)
        self.pedal = None          # last hi-hat pedal position (CC4), None until the kit sends one
        self.kit_opens = False     # has this kit sent an open hi-hat note yet?

    def _device_connected(self, name):
        self.pedal, self.kit_opens = None, False
        if name:
            self.settings["midi_device"] = name
            self.kit = load_kit(self.settings, name)

    def save_kit(self):
        save_kit(self.settings, self.midi.port_name or self.settings["midi_device"] or "default", self.kit)

    def _on_pedal(self, value):
        self.pedal = value

    def _on_midi(self, note, velocity, perf):
        lane = self.kit.lane_for(note)
        self.raw_note.emit(note, velocity, perf, lane)
        if lane:
            opened = None
            if lane == "hihat":
                self.kit_opens |= self.kit.is_open_hat(note)
                opened = self.kit.hat_open(note, self.pedal, self.kit_opens)
            if self.settings["pad_sounds"]:
                self.audio.play_pad(OPEN_HAT if opened else lane, velocity)
            self.lane_hit.emit(lane, velocity, perf - self.settings["latency_ms"] / 1000, opened)

    def keyboard_hit(self, lane):
        """A computer-keyboard 'pad' (no kit needed). Always audible, no latency correction.
        Velocity 0 = unknown, so dynamics aren't rated for keyboard hits."""
        self.audio.play_pad(lane, 110)
        self.lane_hit.emit(lane, 0, time.perf_counter(), None)

    def set_kit(self, kit, custom_sounds):
        """Switch the app's drum sounds; returns {lane: error} for samples that failed to load."""
        self.settings["sound_kit"] = kit
        return self.audio.set_kit(kit, custom_sounds)

    def set_volume(self, key, value):
        self.audio.volume[key] = value
        self.settings[f"volume_{key}"] = value

    def record_result(self, lesson_path, speed, summary, assisted=False):
        if lesson_path:
            self.progress.record(lesson_path, speed, summary, assisted=assisted)


def nav_icon(name):
    """A sidebar icon: muted, and full white on the page you're on."""
    ic = QIcon()
    ic.addPixmap(icon(name, theme.MUTED, 18), QIcon.Normal, QIcon.Off)
    ic.addPixmap(icon(name, theme.TEXT, 18), QIcon.Normal, QIcon.On)
    ic.addPixmap(icon(name, theme.TEXT, 18), QIcon.Active, QIcon.Off)
    return ic


class MainWindow(QMainWindow):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(APP_TITLE)
        self.resize(1280, 780)
        self.setMinimumSize(960, 620)  # the smallest size every page is laid out for

        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        side = QWidget(objectName="sidebar")
        side.setFixedWidth(208)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 20, 0, 14)
        sl.setSpacing(2)
        brand = QHBoxLayout()
        brand.setContentsMargins(22, 0, 16, 18)
        brand.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(QIcon(str(ICON)).pixmap(26, 26))
        brand.addWidget(logo)
        brand.addWidget(QLabel(APP_TITLE, objectName="appname"), 1)
        sl.addLayout(brand)
        self.stack = PageStack()
        self.library = LibraryPage(ctx)
        self.course = CoursePage(ctx)
        self.grooves = GroovesPage(ctx)
        self.practice = PracticePage(ctx)
        self.kit = KitPage(ctx)
        self.editor = EditorPage(ctx)
        self.home = HomePage(ctx, self.course, self.grooves)
        for page in (self.home, self.library, self.course, self.grooves, self.practice, self.kit, self.editor):
            self.stack.addWidget(page)

        self.nav = QButtonGroup(self)
        self.nav_for = {}
        for text, name, page in (("Home", "home", self.home), ("Songs", "songs", self.library),
                                 ("Course", "course", self.course),
                                 ("Groove Lab", "groove", self.grooves), ("My kit", "kit", self.kit)):
            b = QPushButton(text, objectName="nav", checkable=True)
            b.setIcon(nav_icon(name))
            b.setIconSize(QSize(18, 18))
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, p=page: self.go_to(p))
            self.nav.addButton(b)
            self.nav_for[page] = b
            sl.addWidget(b)
        self.nav_for[self.home].setChecked(True)
        self.return_to = self.home  # the page the play screen goes back to
        sl.addStretch()
        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background: {theme.BORDER}; margin: 0 18px;")
        sl.addWidget(rule)
        sl.addSpacing(8)
        self.streak = QPushButton(objectName="status")
        self.streak.setEnabled(False)  # just a label (a button only to show the icon beside the text)
        sl.addWidget(self.streak)
        self.device = QPushButton(objectName="status")
        self.device.setCursor(Qt.PointingHandCursor)
        self.device.setFocusPolicy(Qt.NoFocus)
        self.device.clicked.connect(lambda: self.go_to(self.kit))
        sl.addWidget(self.device)
        h.addWidget(side)
        h.addWidget(self.stack, 1)
        self.side = side
        # the play screen takes the whole window, like a game: the sidebar comes back when you leave it
        self.stack.currentChanged.connect(lambda _: side.setVisible(self.stack.currentWidget() is not self.practice))

        self.home.practise.connect(self.open_lesson)
        self.home.play_lesson.connect(self.open_course_lesson)
        self.home.show_page.connect(lambda name: self.go_to({"songs": self.library, "course": self.course,
                                                             "grooves": self.grooves}[name]))
        self.library.practise.connect(self.open_lesson)
        self.library.edit.connect(self.open_editor)
        self.editor.back.connect(lambda: self.go_to(self.library))
        self.editor.practise.connect(self.open_lesson)
        self.editor.saved.connect(self._song_saved)
        self.course.play.connect(self.open_course_lesson)
        self.grooves.play.connect(self.open_course_lesson)
        self.practice.back.connect(self._back_from_practice)
        self.practice.next_course_lesson.connect(self._next_course_lesson)
        ctx.lane_hit.connect(self._lane_hit)
        ctx.raw_note.connect(self.kit.on_note)
        ctx.midi.connected.connect(self._show_device)
        self._show_device(ctx.midi.port_name)
        self._show_streak()
        if ctx.audio.error:
            self.statusBar().showMessage(f"No sound output: {ctx.audio.error}")

    def go_to(self, page):
        """Switch page from the sidebar (asks first when leaving the editor with unsaved edits)."""
        if self.stack.currentWidget() is self.editor and page is not self.editor and not self.editor.confirm_leave():
            self.nav_for[self.library].setChecked(True)
            return
        self.stack.setCurrentWidget(page)
        if page in self.nav_for:
            self.nav_for[page].setChecked(True)

    def open_editor(self, path):
        self.editor.load(path)
        self.stack.setCurrentWidget(self.editor)
        self.nav_for[self.library].setChecked(True)

    def _song_saved(self, path):
        self.library.refresh()
        if self.practice.path == path:
            self.practice.load(path)

    def open_lesson(self, path):
        self.practice.load(path)
        self._show_practice(self.library)

    def open_course_lesson(self, lesson):
        self.practice.load_course_lesson(lesson)
        self._show_practice(self._lesson_page(lesson))

    def _show_practice(self, page):
        """Open the play screen; back returns to Home if it was opened from there, otherwise to `page`."""
        if self.stack.currentWidget() is not self.practice:
            self.return_to = self.home if self.stack.currentWidget() is self.home else page
        if self.return_to is self.home:
            self.practice.back_btn.setText("Home")
        self.stack.setCurrentWidget(self.practice)
        self.nav_for[self.return_to].setChecked(True)
        self.practice.setFocus()

    def _next_course_lesson(self):
        current = self.practice.course_lesson
        nxt = self._lesson_page(current).lesson_after(current) if current else None
        if nxt:
            self.open_course_lesson(nxt)
        else:
            self._back_from_practice()

    def _lesson_page(self, lesson):
        """The page a course lesson or groove was opened from."""
        return self.grooves if lesson.key.startswith("groove:") else self.course

    def _back_from_practice(self):
        current = self.practice.course_lesson
        page = self.return_to if self.return_to is self.home else self._lesson_page(current) if current             else self.library
        self.stack.setCurrentWidget(page)
        self.nav_for[page].setChecked(True)
        self._show_streak()

    def _lane_hit(self, lane, velocity, perf, opened):
        if self.stack.currentWidget() is self.practice:
            self.practice.on_hit(lane, velocity, perf, opened)

    def _show_device(self, name):
        """The kit in use (green dot) or none (red); click it for My kit."""
        self.device.setIcon(QIcon(icon("dot", theme.GOOD if name else theme.BAD, 14)))
        self.device.setText(name or "No kit connected")
        self.device.setToolTip(("Connected: " + name if name else "No kit found") + ". Click for My kit.")

    def _show_streak(self):
        n = self.ctx.progress.streak()
        self.streak.setVisible(bool(n))
        flame = QIcon()
        for mode in (QIcon.Normal, QIcon.Disabled):  # a label-like (disabled) button would grey the icon
            flame.addPixmap(icon("flame", theme.ACCENT, 14), mode)
        self.streak.setIcon(flame)
        self.streak.setText(f"{n}-day streak")

    def closeEvent(self, e):
        if not self.library.confirm_close() or not self.editor.confirm_leave():
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
    app.setStyleSheet(stylesheet(data_dir() / "ui"))
    ctx = AppContext()
    win = MainWindow(ctx)
    win.show()
    ctx.midi.rescan()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
