"""Course page: the built-in lessons as a path of units, each with its lesson cards (stars, locks, the
lesson to play next highlighted). LessonCard is shared with Groove Lab and the home page."""

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QFont, QPainter, QPen
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ..course import all_lessons, load_course, next_lesson, unlocked
from . import theme
from .drawing import draw_grade, draw_stars, icon, qc
from .widgets import CardGrid

CARD_H = 108


class LessonCard(QPushButton):
    """A lesson: heading, title, difficulty grade, tempo and best stars; passed, locked or next up."""

    def __init__(self, lesson):
        super().__init__()
        self.lesson = lesson
        self.rating = lesson.rating()
        self.best, self.passed, self.next_up = None, False, False
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(170, CARD_H)
        self.setFocusPolicy(Qt.NoFocus)
        tip = getattr(lesson, "tip", "") or lesson.title
        why = ", ".join(self.rating.reasons)
        self.setToolTip(f"{tip}\n{self.rating.grade_name} {self.rating.level}/10" + (f": {why}" if why else ""))

    def height_for(self, _width):
        return CARD_H

    def set_state(self, best, is_unlocked, passed, next_up=False):
        self.best, self.passed, self.next_up = best, passed, next_up and is_unlocked and not passed
        self.setEnabled(is_unlocked)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        locked = not self.isEnabled()
        hover = self.underMouse() and not locked
        if locked:
            p.setOpacity(0.55)
        strong = self.next_up or hover
        border = theme.ACCENT if strong else theme.GOOD if self.passed else theme.BORDER
        p.setPen(QPen(qc(border, 0.9 if strong else 0.6 if self.passed else 1.0), 2 if self.next_up else 1,
                      Qt.DashLine if locked else Qt.SolidLine))
        p.setBrush(qc(theme.BG if locked else theme.SURFACE_3 if hover else theme.PANEL))
        p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), theme.RADIUS_CARD - 2, theme.RADIUS_CARD - 2)

        x, tw = 14, w - 28
        f = QFont(self.font())
        # top row: heading, and the state on the right
        f.setPointSizeF(8.5)
        f.setBold(True)
        p.setFont(f)
        state_w = 0
        if self.next_up:
            text = "NEXT UP"
            state_w = p.fontMetrics().horizontalAdvance(text) + 14
            pill = QRectF(w - 14 - state_w, 10, state_w, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(qc(theme.ACCENT))
            p.drawRoundedRect(pill, 9, 9)
            p.setPen(qc("#1a0f0b"))
            p.drawText(pill, Qt.AlignCenter, text)
        elif self.passed or locked:
            name, color, text = ("check", theme.GOOD, "Passed") if self.passed else ("lock", theme.MUTED, "Locked")
            state_w = p.fontMetrics().horizontalAdvance(text) + 18
            p.drawPixmap(round(w - 14 - state_w), 12, icon(name, color, 13))
            p.setPen(qc(color))
            p.drawText(QRectF(w - 14 - state_w + 17, 10, state_w - 17, 18), Qt.AlignLeft | Qt.AlignVCenter, text)
        heading = getattr(self.lesson, "heading", None) or f"Lesson {self.lesson.number}"
        p.setPen(qc(theme.FAINT))
        room = int(tw - state_w - 6)
        p.drawText(QRectF(x, 10, room, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(heading.upper(), Qt.ElideRight, room))
        # title, up to two lines
        f.setPointSizeF(10.5)
        p.setFont(f)
        p.setPen(qc(theme.TEXT))
        fm = p.fontMetrics()
        lines = [""]
        for word in getattr(self.lesson, "card_title", self.lesson.title).split():
            trial = f"{lines[-1]} {word}".strip()
            if fm.horizontalAdvance(trial) <= tw or not lines[-1]:
                lines[-1] = trial
            elif len(lines) < 2:
                lines.append(word)
            else:
                lines[-1] = fm.elidedText(f"{lines[-1]} {word} ...", Qt.ElideRight, tw)
                break
        for i, line in enumerate(lines):
            p.drawText(QRectF(x, 32 + i * 19, tw, 19), Qt.AlignLeft | Qt.AlignVCenter,
                       fm.elidedText(line, Qt.ElideRight, tw))
        # bottom row: grade, tempo, stars
        y = h - 28
        draw_grade(p, x, y, self.rating.grade)
        f.setPointSizeF(9)
        f.setBold(False)
        p.setFont(f)
        p.setPen(qc(theme.MUTED))
        p.drawText(QRectF(x + 24, y - 1, tw, 18), Qt.AlignLeft | Qt.AlignVCenter, f"{self.lesson.bpm:.0f} BPM")
        if self.best:
            draw_stars(p, w - 14 - 40, y + 2, self.best[0], size=12, gap=2)
        p.end()


class UnitMarker(QWidget):
    """The unit's stop on the course path: its number in a ring that fills as lessons are passed, and the
    line on to the next unit."""

    def __init__(self, number, last=False):
        super().__init__()
        self.number, self.last = number, last
        self.done, self.total = 0, 1
        self.setFixedWidth(48)

    def set_progress(self, done, total):
        self.done, self.total = done, max(1, total)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, r = self.width() / 2, 18
        complete = self.done >= self.total
        if not self.last:
            p.setPen(QPen(qc(theme.GOOD if complete else theme.BORDER), 2))
            p.drawLine(QPointF(cx, 4 + 2 * r + 6), QPointF(cx, self.height()))
        ring = QRectF(cx - r, 4, 2 * r, 2 * r)
        p.setPen(Qt.NoPen)
        p.setBrush(qc(theme.ACCENT_SOFT if 0 < self.done < self.total else theme.PANEL))
        p.drawEllipse(ring)
        inner = ring.adjusted(1.5, 1.5, -1.5, -1.5)
        p.setPen(QPen(qc(theme.BORDER), 3))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(inner)
        if self.done:
            p.setPen(QPen(qc(theme.GOOD), 3, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(inner, 90 * 16, -round(360 * 16 * min(1, self.done / self.total)))
        if complete:
            p.drawPixmap(round(cx - 8), round(4 + r - 8), icon("check", theme.GOOD, 16))
        else:
            f = QFont(self.font())
            f.setPointSizeF(11)
            f.setBold(True)
            p.setFont(f)
            p.setPen(qc(theme.TEXT))
            p.drawText(ring, Qt.AlignCenter, str(self.number))
        p.end()


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

        self.markers, self.unit_cards, self.unit_counts = [], [], []
        for u, unit in enumerate(self.units, 1):
            row = QHBoxLayout()
            row.setSpacing(14)
            marker = UnitMarker(u, last=u == len(self.units))
            row.addWidget(marker)
            col = QVBoxLayout()
            col.setSpacing(4)
            col.setContentsMargins(0, 6, 0, 26)
            top = QHBoxLayout()
            top.addWidget(QLabel(unit.title, objectName="h2"))
            count = QLabel(objectName="caption")
            top.addSpacing(8)
            top.addWidget(count, 0, Qt.AlignBottom)
            top.addStretch()
            col.addLayout(top)
            col.addWidget(QLabel(unit.about, objectName="muted", wordWrap=True))
            col.addSpacing(8)
            grid = CardGrid(min_width=190, gap=12, fill=True)
            cards = []
            for les in unit.lessons:
                card = LessonCard(les)
                card.clicked.connect(lambda _=False, les=les: self.play.emit(les))
                cards.append(card)
            grid.set_cards(cards)
            col.addWidget(grid)
            row.addLayout(col, 1)
            lay.addLayout(row)
            self.cards += cards
            self.markers.append(marker)
            self.unit_cards.append(cards)
            self.unit_counts.append(count)
        lay.addStretch()

    def _unlock_all_toggled(self, on):
        self.ctx.settings["course_unlock_all"] = on
        self.refresh()

    def refresh(self):
        progress = self.ctx.progress
        open_ids = unlocked(self.units, progress.passed, self.unlock_all.isChecked())
        nxt = self.next_to_play()
        n_passed = 0
        for card in self.cards:
            key = card.lesson.key
            passed = progress.passed(key)
            n_passed += passed
            card.set_state(progress.best(key), card.lesson.id in open_ids, passed,
                           next_up=nxt is not None and card.lesson.id == nxt.id)
        for marker, cards, count in zip(self.markers, self.unit_cards, self.unit_counts):
            done = sum(c.passed for c in cards)
            marker.set_progress(done, len(cards))
            count.setText(f"{done} of {len(cards)} passed")
        total = len(self.cards)
        self.summary.setText(f"{n_passed} of {total} lessons passed  ·  pass a lesson with at least one star "
                             "at 100% speed to unlock the next")
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

