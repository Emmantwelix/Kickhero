"""Home page: today's practice goal, streak and course progress, a card to pick up where you left off, and rows of
songs and lessons to play next."""

import datetime as dt
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QProgressBar, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from ..course import all_lessons, unlocked
from . import theme
from .course import LessonCard
from .covers import CoverLoader, generated_tile
from .drawing import icon, qc
from .library import SongCard, load_songs
from .widgets import CardGrid, StatRing, icon_button, rounded_pixmap

GOALS = (5, 10, 15, 20, 30, 45, 60)  # daily goal choices, minutes


def greeting(hour):
    return "Good morning" if 5 <= hour < 12 else "Good afternoon" if 12 <= hour < 18 else "Good evening"


def ago(when, today=None):
    """"today", "yesterday", "3 days ago" for an ISO time."""
    today = today or dt.date.today()
    days = (today - dt.date.fromisoformat(when[:10])).days
    return "today" if days <= 0 else "yesterday" if days == 1 else f"{days} days ago"


class WeekDots(QWidget):
    """The last 7 days as dots under their initials: filled on days you played."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self.days = []  # (date, played)

    def set_days(self, days):
        self.days = days
        self.update()

    def paintEvent(self, _):
        if not self.days:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        step = min(34, self.width() / len(self.days))
        f = p.font()
        f.setPointSizeF(8)
        p.setFont(f)
        today = dt.date.today()
        for i, (day, played) in enumerate(self.days):
            x = i * step
            p.setPen(qc(theme.TEXT if day == today else theme.FAINT))
            p.drawText(QRectF(x, 0, step, 14), Qt.AlignCenter, "MTWTFSS"[day.weekday()])
            c = QRectF(x + step / 2 - 9, 18, 18, 18)
            if played:
                p.setPen(Qt.NoPen)
                p.setBrush(qc(theme.ACCENT))
                p.drawEllipse(c)
                p.drawPixmap(round(c.x() + 3), round(c.y() + 3), icon("check", "#1a0f0b", 12))
            else:
                p.setPen(qc(theme.SURFACE_3 if day != today else theme.FAINT, 1.0))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(c.adjusted(1, 1, -1, -1))
        p.end()


def section(title, link=None, on_link=None):
    """A row heading, with an optional link on the right ("See all")."""
    row = QHBoxLayout()
    row.addWidget(QLabel(title, objectName="h2"))
    row.addStretch()
    if link:
        b = QPushButton(link, objectName="flat")
        b.setCursor(Qt.PointingHandCursor)
        b.setFocusPolicy(Qt.NoFocus)
        b.clicked.connect(on_link)
        row.addWidget(b)
    return row


class HomePage(QWidget):
    practise = Signal(object)      # Path of a song's MIDI file
    play_lesson = Signal(object)   # CourseLesson or GrooveLesson
    show_page = Signal(str)        # "songs", "course", "grooves"

    def __init__(self, ctx, course, grooves, parent=None):
        super().__init__(parent)
        self.ctx, self.course, self.grooves = ctx, course, grooves
        self.songs = []
        self.song_cards = {}  # (row, path) -> SongCard: a song can be in both rows
        self.images = {}
        self.covers = CoverLoader(self)
        self.covers.found.connect(self._cover_found)
        self._continue = None  # what the Continue card plays: ("song", path) or ("lesson", lesson)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(widgetResizable=True, frameShape=QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        body = QWidget(objectName="root")
        scroll.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(28, 24, 28, 28)
        lay.setSpacing(14)

        self.hello = QLabel(objectName="h1")
        lay.addWidget(self.hello)
        self.hello_sub = QLabel(objectName="muted")
        lay.addWidget(self.hello_sub)
        lay.addSpacing(4)

        # today: goal, streak, course
        stats = QHBoxLayout()
        stats.setSpacing(16)
        goal = QFrame(objectName="card")
        gl = QHBoxLayout(goal)
        gl.setContentsMargins(18, 16, 18, 16)
        gl.setSpacing(16)
        self.ring = StatRing(92)
        gl.addWidget(self.ring)
        gcol = QVBoxLayout()
        gcol.setSpacing(4)
        gcol.addWidget(QLabel("DAILY GOAL", objectName="group"))
        self.goal_title = QLabel(objectName="h3", wordWrap=True)
        self.goal_text = QLabel(objectName="caption", wordWrap=True)
        gcol.addWidget(self.goal_title)
        gcol.addWidget(self.goal_text)
        gcol.addStretch()
        self.goal_btn = QPushButton("Change goal", objectName="flat")
        self.goal_btn.setCursor(Qt.PointingHandCursor)
        self.goal_btn.setFocusPolicy(Qt.NoFocus)
        menu = QMenu(self.goal_btn)
        for m in GOALS:
            menu.addAction(f"{m} minutes a day", lambda m=m: self._set_goal(m))
        self.goal_btn.setMenu(menu)
        gcol.addWidget(self.goal_btn, 0, Qt.AlignLeft)
        gl.addLayout(gcol, 1)
        stats.addWidget(goal, 1)

        streak = QFrame(objectName="card")
        sl = QVBoxLayout(streak)
        sl.setContentsMargins(18, 16, 18, 16)
        sl.setSpacing(4)
        sl.addWidget(QLabel("STREAK", objectName="group"))
        srow = QHBoxLayout()
        srow.setSpacing(8)
        flame = QLabel()
        flame.setPixmap(icon("flame", theme.ACCENT, 20))
        srow.addWidget(flame)
        self.streak_title = QLabel(objectName="h3")
        srow.addWidget(self.streak_title, 1)
        sl.addLayout(srow)
        self.week = WeekDots()
        sl.addWidget(self.week)
        sl.addStretch()
        stats.addWidget(streak, 1)

        course_card = QFrame(objectName="card")
        cl = QVBoxLayout(course_card)
        cl.setContentsMargins(18, 16, 18, 16)
        cl.setSpacing(6)
        cl.addWidget(QLabel("COURSE", objectName="group"))
        self.course_title = QLabel(objectName="h3")
        cl.addWidget(self.course_title)
        self.course_bar = QProgressBar(textVisible=False)
        self.course_bar.setFixedHeight(6)
        cl.addWidget(self.course_bar)
        self.course_next = QLabel(objectName="caption", wordWrap=True)
        cl.addWidget(self.course_next)
        cl.addStretch()
        open_course = QPushButton("Open course", objectName="flat")
        open_course.setCursor(Qt.PointingHandCursor)
        open_course.setFocusPolicy(Qt.NoFocus)
        open_course.clicked.connect(lambda: self.show_page.emit("course"))
        cl.addWidget(open_course, 0, Qt.AlignLeft)
        stats.addWidget(course_card, 1)
        lay.addLayout(stats)

        # pick up where you left off
        self.cont = QFrame(objectName="card")
        ct = QHBoxLayout(self.cont)
        ct.setContentsMargins(16, 16, 20, 16)
        ct.setSpacing(18)
        self.cont_cover = QLabel()
        self.cont_cover.setFixedSize(88, 88)
        ct.addWidget(self.cont_cover)
        ccol = QVBoxLayout()
        ccol.setSpacing(3)
        self.cont_label = QLabel(objectName="group")
        self.cont_title = QLabel(objectName="h2")
        self.cont_sub = QLabel(objectName="muted")
        ccol.addStretch()
        for w in (self.cont_label, self.cont_title, self.cont_sub):
            ccol.addWidget(w)
        ccol.addStretch()
        ct.addLayout(ccol, 1)
        self.cont_btn = QPushButton("  Practise", objectName="primary")
        self.cont_btn.setIcon(icon("play", "#1a0f0b", 14))
        self.cont_btn.setCursor(Qt.PointingHandCursor)
        self.cont_btn.clicked.connect(self._play_continue)
        ct.addWidget(self.cont_btn)
        lay.addWidget(self.cont)

        # next lessons in the course
        lay.addSpacing(6)
        lay.addLayout(section("Next in the course", "See all", lambda: self.show_page.emit("course")))
        self.lessons_grid = QGridLayout()
        self.lessons_grid.setSpacing(12)
        for c in range(4):
            self.lessons_grid.setColumnStretch(c, 1)
        lay.addLayout(self.lessons_grid)
        self.lesson_cards = []

        # songs
        self.improve_head = QWidget()
        ih = QVBoxLayout(self.improve_head)
        ih.setContentsMargins(0, 6, 0, 0)
        ih.addLayout(section("Keep improving", "All songs", lambda: self.show_page.emit("songs")))
        lay.addWidget(self.improve_head)
        self.improve = CardGrid(min_width=150, gap=14, max_rows=1)
        lay.addWidget(self.improve)
        recent_head = QWidget()
        rh = QVBoxLayout(recent_head)
        rh.setContentsMargins(0, 6, 0, 0)
        rh.addLayout(section("Recently added songs", "All songs", lambda: self.show_page.emit("songs")))
        lay.addWidget(recent_head)
        self.recent = CardGrid(min_width=150, gap=14, max_rows=1)
        lay.addWidget(self.recent)
        self.no_songs = QFrame(objectName="card")
        nl = QHBoxLayout(self.no_songs)
        nl.setContentsMargins(18, 14, 18, 14)
        nl.addWidget(QLabel("No songs yet: add a song file and it's turned into a drum lesson in a few minutes.",
                            objectName="muted", wordWrap=True), 1)
        add = icon_button("plus", "Add a song", "Go to Songs to add one")
        add.clicked.connect(lambda: self.show_page.emit("songs"))
        nl.addWidget(add)
        lay.addWidget(self.no_songs)
        lay.addStretch()

    # ---------- filling in ----------

    def refresh(self):
        now = dt.datetime.now()
        self.hello.setText(greeting(now.hour))
        progress = self.ctx.progress
        self._show_goal()
        n = progress.streak()
        self.streak_title.setText(f"{n}-day streak" if n else "No streak yet")
        today = dt.date.today()
        first = today - dt.timedelta(days=6)
        played = progress.days_played(first, today)
        self.week.set_days([(first + dt.timedelta(days=i), first + dt.timedelta(days=i) in played) for i in range(7)])

        units = self.course.units
        lessons = all_lessons(units)
        passed = sum(progress.passed(les.key) for les in lessons)
        self.course_title.setText(f"{passed} of {len(lessons)} lessons passed")
        self.course_bar.setMaximum(max(1, len(lessons)))
        self.course_bar.setValue(passed)
        nxt = self.course.next_to_play()
        self.course_next.setText(f"Next: {nxt.number}  {nxt.title}" if nxt else "Course complete!")

        self.songs = load_songs(self.ctx.settings.library_dir, progress)
        self._show_continue()
        self._show_lessons(nxt)
        self._show_songs()

    def _show_goal(self):
        goal = int(self.ctx.settings.data.get("daily_goal_min", 10))
        mins = self.ctx.progress.seconds_on() / 60
        done = mins >= goal
        self.ring.set_value(mins / goal, theme.GOOD if done else theme.ACCENT, f"of {goal} min", f"{int(mins)}")
        if done:
            self.goal_title.setText("Goal reached!")
            self.goal_text.setText(f"{int(mins)} minutes played today. Nice work.")
            self.hello_sub.setText("You've hit today's goal. Anything more is a bonus.")
        else:
            left = max(1, round(goal - mins))
            self.goal_title.setText(f"{left} minute{'s' if left != 1 else ''} to go")
            self.goal_text.setText("Time spent playing counts, finished or not.")
            self.hello_sub.setText("Ready to play? Here's where to start today." if mins < 0.5 else
                                   "Keep going: you're on your way to today's goal.")

    def _set_goal(self, minutes):
        self.ctx.settings["daily_goal_min"] = minutes
        self._show_goal()

    def _lesson_for(self, key):
        if key.startswith("course:"):
            return next((les for les in all_lessons(self.course.units) if les.key == key), None)
        if key.startswith("groove:"):
            return next((g for g in self.grooves.grooves if g.key == key), None)
        return None

    def _show_continue(self):
        """The most recent song or lesson that still exists; or, before any practice, the course's first lesson."""
        progress = self.ctx.progress
        by_path = {str(s.path): s for s in self.songs}
        for key, when in progress.recent(20):
            song = by_path.get(key)
            lesson = None if song else self._lesson_for(key)
            if song is None and lesson is None:
                continue
            best = progress.best(key)
            stars = f"best {'★' * best[0]}{'☆' * (3 - best[0])}  {best[1] * 100:.0f}%" if best else "no score yet"
            self.cont_label.setText("PICK UP WHERE YOU LEFT OFF")
            if song:
                self._continue = ("song", song.path)
                self.cont_title.setText(song.song)
                self.cont_sub.setText(f"{song.artist + '  ·  ' if song.artist else ''}played {ago(when)}  ·  {stars}")
                image = self._image(song)
            else:
                self._continue = ("lesson", lesson)
                where = "Groove Lab" if key.startswith("groove:") else "Course"
                # a groove's title already says its level ("Level 3 · Groove 12")
                self.cont_title.setText(lesson.title if key.startswith("groove:") else
                                        f"{lesson.number}  {lesson.title}")
                self.cont_sub.setText(f"{where}  ·  played {ago(when)}  ·  {stars}")
                image = generated_tile(lesson.title)
            self.cont_cover.setPixmap(rounded_pixmap(image, 88, 88, 10))
            self.cont.show()
            return
        nxt = self.course.next_to_play()
        if nxt is None:
            self.cont.hide()
            return
        self._continue = ("lesson", nxt)
        self.cont_label.setText("START HERE")
        self.cont_title.setText(f"{nxt.number}  {nxt.title}")
        self.cont_sub.setText("The first lesson of the course: a few minutes, at your own speed")
        self.cont_cover.setPixmap(rounded_pixmap(generated_tile(nxt.title), 88, 88, 10))
        self.cont.show()

    def _play_continue(self):
        if not self._continue:
            return
        kind, what = self._continue
        (self.practise if kind == "song" else self.play_lesson).emit(what)

    def _show_lessons(self, nxt):
        """The next four course lessons from the first one not yet passed."""
        for card in self.lesson_cards:
            card.deleteLater()
        self.lesson_cards = []
        lessons = all_lessons(self.course.units)
        start = lessons.index(nxt) if nxt in lessons else 0
        open_ids = unlocked(self.course.units, self.ctx.progress.passed,
                            bool(self.ctx.settings.data.get("course_unlock_all")))
        for i, les in enumerate(lessons[start:start + 4]):
            card = LessonCard(les)
            card.setMinimumSize(130, 92)  # four in a row, even in a narrow window
            card.set_state(self.ctx.progress.best(les.key), les.id in open_ids, self.ctx.progress.passed(les.key))
            card.clicked.connect(lambda _=False, les=les: self.play_lesson.emit(les))
            self.lessons_grid.addWidget(card, 0, i)
            self.lesson_cards.append(card)

    def _card(self, row, song):
        card = self.song_cards.get((row, song.path))
        if card is None:
            card = SongCard(song)
            card.clicked.connect(lambda s: self.practise.emit(s.path))
            card.play.connect(lambda s: self.practise.emit(s.path))
            self.song_cards[(row, song.path)] = card
        card.song = song
        card.set_image(self._image(song))
        return card

    def _image(self, song):
        cover = self.covers.request(song.path)
        if cover:
            self.images[song.path] = QImage(cover)
        return self.images.setdefault(song.path, generated_tile(song.title))

    def _cover_found(self, path, cover):
        path = Path(path)
        if cover:
            self.images[path] = QImage(cover)
            for (_, p), card in self.song_cards.items():
                if p == path:
                    card.set_image(self.images[path])

    def _show_songs(self):
        improve = sorted((s for s in self.songs if s.best and s.best[0] < 3), key=lambda s: -s.best[1])
        recent = sorted(self.songs, key=lambda s: -s.added)[:8]
        self.improve_head.setVisible(bool(improve))
        self.improve.setVisible(bool(improve))
        self.improve.set_cards([self._card("improve", s) for s in improve[:8]])
        self.recent.set_cards([self._card("recent", s) for s in recent])
        self.recent.setVisible(bool(recent))
        self.no_songs.setVisible(not self.songs)
        shown = {id(c) for c in self.improve.cards + self.recent.cards}
        self.song_cards = {k: c for k, c in self.song_cards.items() if id(c) in shown}  # set_cards deleted the rest

    def showEvent(self, e):
        self.refresh()
        super().showEvent(e)
