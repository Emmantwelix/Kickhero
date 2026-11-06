import pytest

from kickhero.course import all_lessons, load_course, next_lesson, unlocked, validate
from kickhero.progress import Progress


def test_course_data_is_valid():
    units = load_course()
    assert validate(units) == []
    assert len(units) == 8 and len(all_lessons(units)) >= 25


def test_every_lesson_builds_and_fits_its_bars():
    for les in all_lessons(load_course()):
        lesson = les.to_lesson()
        assert lesson.notes, les.id
        assert lesson.notes[-1].t < lesson.length
        assert lesson.bpm == les.bpm


def test_pattern_timing_and_velocity():
    units = load_course()
    les = next(l for l in all_lessons(units) if l.id == "ghost-intro")
    lesson = les.to_lesson()
    beat = 60 / les.bpm
    snares = [n for n in lesson.notes if n.lane == "snare"][:2]
    # "...gX..." : ghost on the 4th sixteenth, accent on beat 2
    assert snares[0].t == pytest.approx(3 * beat / 4) and snares[0].velocity == 45
    assert snares[1].t == pytest.approx(beat) and snares[1].velocity == 124
    assert lesson.bars == 4


def test_shorter_lane_patterns_repeat_per_bar():
    les = next(l for l in all_lessons(load_course()) if l.id == "kick-two-bar")
    lesson = les.to_lesson()
    assert lesson.bars == 6  # 2-bar pattern x 3 repeats
    assert sum(n.lane == "snare" for n in lesson.notes) == 12  # 1-bar snare part fills all 6 bars


def test_unlocking_follows_passes(tmp_path):
    units = load_course()
    lessons = all_lessons(units)
    p = Progress(tmp_path / "p.db")
    assert unlocked(units, p.passed) == {lessons[0].id}
    p.record(lessons[0].key, 0.8, {"accuracy": 0.99, "stars": 3})   # too slow to count
    assert unlocked(units, p.passed) == {lessons[0].id}
    p.record(lessons[0].key, 1.0, {"accuracy": 0.7, "stars": 1})
    assert unlocked(units, p.passed) == {lessons[0].id, lessons[1].id}
    assert unlocked(units, p.passed, unlock_all=True) == {les.id for les in lessons}
    assert next_lesson(units, lessons[0].id) is lessons[1]
    assert next_lesson(units, lessons[-1].id) is None
