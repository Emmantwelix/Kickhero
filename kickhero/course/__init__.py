"""The built-in course: lessons written as drum patterns in course/*.json, turned into practice lessons.

Pattern notation (one string per lane): 16 characters per bar, one per 16th note.
x = hit, X = accent, g = ghost note, o = open hi-hat (hi-hat lane only), . = rest, | separates bars.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..engine.lesson import from_notes
from ..lanes import LANES

STEPS_PER_BAR = 16
VELOCITY = {"x": 100, "X": 124, "g": 45, "o": 100}
OPEN = "o"
PASS_SPEED = 0.999   # a lesson counts as passed with 1+ star at 100% speed
COURSE_FILE = Path(__file__).with_name("beginner.json")


@dataclass
class CourseLesson:
    id: str
    title: str
    bpm: float
    pattern: dict
    repeats: int = 4
    tip: str = ""
    unit: str = ""
    number: str = ""  # e.g. "2.3"

    @property
    def key(self):
        """Progress key: course lessons are stored next to song paths in the progress database."""
        return f"course:{self.id}"

    def rating(self):
        """The lesson's Rating (E/M/H, why), worked out once."""
        if "_rating" not in self.__dict__:
            self.__dict__["_rating"] = self.to_lesson().rating()
        return self.__dict__["_rating"]

    def to_lesson(self):
        """Build the playable lesson: the pattern repeated `repeats` times."""
        bar_count = max(len(p.split("|")) for p in self.pattern.values())
        step = 60.0 / self.bpm / 4
        notes = []
        for lane, pattern in self.pattern.items():
            bars = pattern.split("|")
            for rep in range(self.repeats):
                for b in range(bar_count):
                    cells = bars[b % len(bars)]  # shorter patterns repeat
                    for i, ch in enumerate(cells):
                        if ch in VELOCITY:
                            t = ((rep * bar_count + b) * STEPS_PER_BAR + i) * step
                            notes.append((t, lane, VELOCITY[ch], ch == OPEN))
        return from_notes(f"{self.number}  {self.title}", self.bpm, notes, bars=bar_count * self.repeats)


@dataclass
class Unit:
    title: str
    about: str
    lessons: list = field(default_factory=list)


def load_course(path=COURSE_FILE):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    units = []
    for u, unit in enumerate(data["units"], 1):
        lessons = [CourseLesson(id=les["id"], title=les["title"], bpm=les["bpm"], pattern=les["pattern"],
                                repeats=les.get("repeats", 4), tip=les.get("tip", ""), unit=unit["title"],
                                number=f"{u}.{i}")
                   for i, les in enumerate(unit["lessons"], 1)]
        units.append(Unit(unit["title"], unit.get("about", ""), lessons))
    return units


def all_lessons(units):
    return [les for unit in units for les in unit.lessons]


def unlocked(units, passed, unlock_all=False):
    """Ids of lessons you may play: the first one, and each one after a passed lesson."""
    lessons = all_lessons(units)
    if unlock_all:
        return {les.id for les in lessons}
    out = {lessons[0].id} if lessons else set()
    for prev, les in zip(lessons, lessons[1:]):
        if passed(prev.key):
            out.add(les.id)
    return out


def next_lesson(units, lesson_id):
    lessons = all_lessons(units)
    ids = [les.id for les in lessons]
    i = ids.index(lesson_id) if lesson_id in ids else -1
    return lessons[i + 1] if 0 <= i < len(lessons) - 1 else None


def validate(units):
    """Problems in the course data, as readable strings (empty list = fine)."""
    problems, seen = [], set()
    for unit in units:
        for les in unit.lessons:
            if les.id in seen:
                problems.append(f"{les.number}: duplicate id {les.id}")
            seen.add(les.id)
            for lane, pattern in les.pattern.items():
                if lane not in LANES:
                    problems.append(f"{les.number}: unknown lane {lane}")
                for bar in pattern.split("|"):
                    if len(bar) != STEPS_PER_BAR or set(bar) - set(VELOCITY) - {"."}:
                        problems.append(f"{les.number} {lane}: bad bar {bar!r}")
                    elif OPEN in bar and lane != "hihat":
                        problems.append(f"{les.number} {lane}: only the hi-hat can be open")
    return problems
