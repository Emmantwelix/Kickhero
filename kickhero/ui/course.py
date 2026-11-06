"""Course page: the built-in lessons by unit, with stars and locks."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from ..course import all_lessons, load_course, next_lesson, unlocked
from . import theme


class LessonCard(QPushButton):
    def __init__(self, lesson):
        super().__init__()
        self.lesson = lesson
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(200, 92)
        self.setFocusPolicy(Qt.NoFocus)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        self.num = QLabel(objectName="muted")
        self.title = QLabel(lesson.title, wordWrap=True)
        self.title.setStyleSheet("font-weight: 600; background: transparent;")
        self.meta = QLabel(objectName="muted")
        for w in (self.num, self.title, self.meta):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
            lay.addWidget(w)

    def set_state(self, best, is_unlocked, passed):
        stars = best[0] if best else 0
        self.num.setText(f"Lesson {self.lesson.number}" + ("   🔒" if not is_unlocked else ""))
        self.meta.setText(f"{self.lesson.bpm:.0f} BPM    " + ("★" * stars + "☆" * (3 - stars) if best else ""))
        self.setEnabled(is_unlocked)
        border = theme.GOOD if passed else theme.BORDER
        self.setStyleSheet(f"""
            LessonCard {{ background: {theme.PANEL}; border: 1px solid {border}; border-radius: 12px;
                          text-align: left; }}
            LessonCard:hover {{ border-color: {theme.ACCENT}; }}
            LessonCard:disabled {{ background: {theme.BG}; }}
            QLabel {{ background: transparent; }}""")
        self.meta.setStyleSheet(f"color: {theme.WARN if best else theme.MUTED}; background: transparent;")


class CoursePage(QWidget):
    play = Signal(object)  # CourseLesson

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.units = load_course()
        self.cards = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(widgetResizable=True, frameShape=QFrame.NoFrame)
        outer.addWidget(scroll)
        body = QWidget(objectName="root")
        scroll.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(10)

        head = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(QLabel("Course", objectName="h1"))
        self.summary = QLabel(objectName="muted")
        col.addWidget(self.summary)
        head.addLayout(col)
        head.addStretch()
        self.unlock_all = QCheckBox("Unlock all lessons")
        self.unlock_all.setToolTip("For drummers who already know the basics: skip ahead to any lesson")
        self.unlock_all.setChecked(bool(ctx.settings.data.get("course_unlock_all")))
        self.unlock_all.toggled.connect(self._unlock_all_toggled)
        self.continue_btn = QPushButton()
        self.continue_btn.setObjectName("primary")
        self.continue_btn.clicked.connect(self._continue)
        head.addWidget(self.unlock_all)
        head.addSpacing(12)
        head.addWidget(self.continue_btn)
        lay.addLayout(head)

        for unit in self.units:
            lay.addSpacing(10)
            lay.addWidget(QLabel(unit.title, objectName="h2"))
            lay.addWidget(QLabel(unit.about, objectName="muted", wordWrap=True))
            grid = QGridLayout()
            grid.setSpacing(10)
            for i, les in enumerate(unit.lessons):
                card = LessonCard(les)
                card.clicked.connect(lambda _=False, les=les: self.play.emit(les))
                grid.addWidget(card, i // 4, i % 4)
                self.cards.append(card)
            for c in range(4):
                grid.setColumnStretch(c, 1)
            lay.addLayout(grid)
        lay.addStretch()

    def _unlock_all_toggled(self, on):
        self.ctx.settings["course_unlock_all"] = on
        self.refresh()

    def refresh(self):
        progress = self.ctx.progress
        open_ids = unlocked(self.units, progress.passed, self.unlock_all.isChecked())
        n_passed = 0
        for card in self.cards:
            key = card.lesson.key
            passed = progress.passed(key)
            n_passed += passed
            card.set_state(progress.best(key), card.lesson.id in open_ids, passed)
        total = len(self.cards)
        self.summary.setText(f"{n_passed} of {total} lessons passed  ·  pass a lesson with at least one star "
                             "at 100% speed to unlock the next")
        nxt = self.next_to_play()
        self.continue_btn.setText(f"Continue: {nxt.number} {nxt.title}  ▶" if nxt else "Course complete!")
        self.continue_btn.setEnabled(nxt is not None)

    def next_to_play(self):
        """The first unlocked lesson not yet passed."""
        progress = self.ctx.progress
        open_ids = unlocked(self.units, progress.passed, self.unlock_all.isChecked())
        for les in all_lessons(self.units):
            if les.id in open_ids and not progress.passed(les.key):
                return les
        return None

    def lesson_after(self, lesson):
        return next_lesson(self.units, lesson.id)

    def _continue(self):
        nxt = self.next_to_play()
        if nxt:
            self.play.emit(nxt)

    def showEvent(self, e):
        self.refresh()
        super().showEvent(e)
