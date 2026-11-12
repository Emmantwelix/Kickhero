"""Time signatures: the meter model, lessons, the click, the editor, MIDI import, the converter's bar 1."""

import json

import numpy as np
import pretty_midi
import pytest

from kickhero.course import CourseLesson, validate, Unit
from kickhero.engine.editing import EditNote, load_part
from kickhero.engine.lesson import from_notes, load_midi
from kickhero.engine.meter import meter_beats, parse_meter, pulse
from kickhero.engine.session import Session
from kickhero.pipeline import midi_import as mi
from kickhero.pipeline.drums2midi import bar_align_shift

BPM = 120  # beat = 0.5 s


def test_pulse_and_beats():
    assert pulse("4/4") == (1, 4) and pulse("3/4") == (1, 3) and pulse("2/2") == (2, 2)
    assert pulse("6/8") == (1.5, 2) and pulse("12/8") == (1.5, 4) and pulse("9/8") == (1.5, 3)
    assert pulse("5/8") == (0.5, 5) and pulse("7/8") == (0.5, 7)
    assert pulse("7/8,11/8") == (0.5, 18)
    assert meter_beats("6/8") == 3 and meter_beats("5/8") == 2.5 and meter_beats("12/8") == 6
    assert parse_meter(" 6/8 ") == "6/8" and parse_meter("waltz") == "4/4" and parse_meter("3/5") == "4/4"
    assert parse_meter("", None) is None


def test_lesson_bars_follow_the_meter():
    notes = [(t * 0.5, "snare", 100) for t in range(12)]  # 12 beats
    assert from_notes("w", BPM, notes, meter="3/4").bars == 4
    assert from_notes("c", BPM, notes).bars == 3
    les = from_notes("s", BPM, notes, meter="6/8")
    assert les.bar == pytest.approx(1.5) and les.bars == 4


def clicks(lesson, bars=2):
    s = Session(lesson, count_in_bars=0)
    return list(s.beats_between(0, bars * lesson.bar - 1e-9))


def test_click_in_6_8_is_on_dotted_quarters():
    les = from_notes("x", BPM, [(0, "kick", 100)], bars=4, meter="6/8")
    c = clicks(les)
    assert [round(u, 6) for u, _ in c] == [0, 0.75, 1.5, 2.25]
    assert [d for _, d in c] == [True, False, True, False]


def test_click_in_5_8_and_3_4():
    c = clicks(from_notes("x", BPM, [(0, "kick", 100)], bars=4, meter="5/8"))
    assert len(c) == 10 and [d for _, d in c].count(True) == 2 and c[5] == (pytest.approx(1.25), True)
    c = clicks(from_notes("x", BPM, [(0, "kick", 100)], bars=4, meter="3/4"))
    assert [d for _, d in c] == [True, False, False] * 2


def song(tmp_path, meta_meter=None, midi_meter=None):
    folder = tmp_path / "Song"
    folder.mkdir(parents=True)
    pm = pretty_midi.PrettyMIDI(initial_tempo=BPM)
    if midi_meter:
        pm.time_signature_changes = [pretty_midi.TimeSignature(*midi_meter, 0.0)]
    inst = pretty_midi.Instrument(program=0, is_drum=True)
    for i in range(12):
        inst.notes.append(pretty_midi.Note(velocity=100, pitch=36 if i % 3 == 0 else 38, start=i * 0.5,
                                           end=i * 0.5 + 0.05))
    pm.instruments.append(inst)
    mid = folder / "Song_drums.mid"
    pm.write(str(mid))
    meta = {"title": "Song", "bpm": BPM, "shift": 0.0}
    if meta_meter:
        meta["meter"] = meta_meter
    mid.with_suffix(".json").write_text(json.dumps(meta), encoding="utf-8")
    return mid


def test_load_midi_reads_the_sidecar_then_the_file(tmp_path):
    assert load_midi(song(tmp_path / "a")).meter == "4/4"
    assert load_midi(song(tmp_path / "b", midi_meter=(3, 4))).meter == "3/4"
    assert load_midi(song(tmp_path / "c", meta_meter="6/8", midi_meter=(3, 4))).meter == "6/8"


def test_part_meter_bars_undo_and_save(tmp_path):
    part = load_part(song(tmp_path))
    assert part.meter == "4/4" and part.bars == 3  # 6 s of notes
    part.set_meter("3/4")
    assert part.bar == pytest.approx(1.5) and part.bars == 4
    assert part.snap(0.13, 16) == pytest.approx(0.125)  # sixteenths stay sixteenths
    part.copy_bars(1, 1)
    pasted = part.paste_bars(3)
    assert sorted(round(n.t, 3) for n in pasted) == [4.5, 5.0, 5.5]
    part.undo()
    part.undo()
    assert part.meter == "4/4"
    part.redo()
    assert part.meter == "3/4"
    part.save()
    assert load_part(part.path).meter == "3/4"
    les = load_midi(part.path)
    assert les.meter == "3/4" and les.bars == 4
    assert pretty_midi.PrettyMIDI(str(part.path)).time_signature_changes[0].numerator == 3
    assert part.to_lesson().meter == "3/4"


def test_import_midi_keeps_its_time_signature(tmp_path):
    pm = pretty_midi.PrettyMIDI(initial_tempo=BPM)
    pm.time_signature_changes = [pretty_midi.TimeSignature(3, 4, 0.0)]
    kit = pretty_midi.Instrument(0, is_drum=True)
    for b in range(1, 9):  # an empty first bar of 3/4 (1.5 s), then a waltz
        for k in range(3):
            t = b * 1.5 + k * 0.5
            kit.notes.append(pretty_midi.Note(100, 36 if k == 0 else 38, t, t + 0.05))
    pm.instruments.append(kit)
    pm.write(str(tmp_path / "Waltz.mid"))
    les = load_midi(mi.import_midi(tmp_path / "Waltz.mid", tmp_path / "lib"))
    assert les.meter == "3/4" and les.bars == 8
    assert min(n.t for n in les.notes) == pytest.approx(0.0, abs=1e-3)  # the empty 3/4 bar trimmed


def test_course_lessons_in_other_meters():
    les = CourseLesson("w", "Waltz", 120, {"kick": "x...........", "snare": "....x...x..."}, repeats=2, meter="3/4")
    lesson = les.to_lesson()
    assert lesson.meter == "3/4" and lesson.bars == 2
    assert [n.t for n in lesson.notes if n.lane == "kick"] == [0.0, 1.5]
    bad = CourseLesson("b", "Bad", 120, {"kick": "x..............."}, meter="3/4", number="1.1")
    problems = validate([Unit("u", "", [bad])])
    assert len(problems) == 1 and "12" in problems[0]


def test_bar_one_in_4_4_and_3_4():
    beat = 60 / BPM
    # 4/4 rock beat starting 0.3 s in: kicks on 1 and 3, snares on 2 and 4
    k = np.array([0.3 + b * 2 + i * 1.0 for b in range(8) for i in (0, 2)]) - 0.5  # pickup: starts on beat 4
    k = k[k >= 0]
    s = np.array([0.3 + b * 2 + i * 0.5 for b in range(8) for i in (1, 3)])
    shift = bar_align_shift(k, [110] * len(k), s, [110] * len(s), min(k.min(), s.min()), BPM)
    assert ((s[0] + shift) / beat) % 4 == pytest.approx(1, abs=1e-6)
    # 3/4 waltz: kick on 1, snares on 2 and 3, starting on a snare
    k = np.array([0.2 + b * 1.5 for b in range(1, 10)])
    s = np.array([0.2 + b * 1.5 + i * 0.5 for b in range(10) for i in (1, 2)])
    shift = bar_align_shift(k, [110] * len(k), s, [90] * len(s), s.min(), BPM, "3/4")
    phase = (k + shift) / 1.5 % 1
    assert np.allclose(np.minimum(phase, 1 - phase), 0, atol=1e-6)
    assert s.min() + shift >= 0
