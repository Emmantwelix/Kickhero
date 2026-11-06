import json

import mido
import pytest

from kickhero.course.grooves import find_folder, load_grooves, meter_beats, part_to_lane

KEYMAP = {"note_to_part": {"24": {"part": "kick", "artic": "hit"}, "29": {"part": "snare", "artic": "rimshot"},
                           "30": {"part": "hihat", "artic": "closed_tip"}, "34": {"part": "hihat", "artic": "open_tip"},
                           "32": {"part": "hihat", "artic": "pedal"}, "75": {"part": "crash1", "artic": "choke"},
                           "72": {"part": "crash1", "artic": "hit"}}}


def vault(tmp_path, meter="4/4", bars=1, beats=((0, 24), (0, 30), (1, 29), (1.5, 34), (2, 32), (3, 75), (4, 72))):
    """A groove library with one groove: (beat, note) hits, 480 ticks per beat, no tempo in the file."""
    (tmp_path / "midi").mkdir()
    (tmp_path / "keymaps").mkdir()
    (tmp_path / "keymaps" / "bfd3.json").write_text(json.dumps(KEYMAP), encoding="utf-8")
    mid = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    events = sorted([(int(b * 480), "note_on", n) for b, n in beats] + [(int(b * 480) + 60, "note_off", n) for b, n in beats])
    now = 0
    for tick, kind, note in events:
        track.append(mido.Message(kind, note=note, velocity=100 if kind == "note_on" else 0, time=tick - now))
        now = tick
    mid.save(str(tmp_path / "midi" / "G1.mid"))
    meta = [{"id": "G1", "filename": "G1.mid", "display_name": "Test - Groove 01", "bpm": 120, "meter": meter,
             "bars": bars, "category": "Groove", "density": "Medium", "vibe": ["Straight"], "keymap": "BFD3",
             "source_title": "Test"},
            {"id": "G2", "filename": "missing.mid", "bpm": 100, "keymap": "BFD3"}]
    (tmp_path / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    return tmp_path


def test_meter_beats():
    assert meter_beats("4/4") == 4 and meter_beats("7/4") == 7 and meter_beats("6/8") == 3
    assert meter_beats("7/8,11/8") == 9 and meter_beats("5/8") == 2.5 and meter_beats("nonsense") == 4


def test_parts_become_lanes():
    assert part_to_lane("snare", "sidestick") == ("snare", False)
    assert part_to_lane("hihat", "half_shank") == ("hihat", True)
    assert part_to_lane("hihat", "quarter_tip") == ("hihat", False)
    assert part_to_lane("hihat", "pedal") is None          # the foot: not a stick note
    assert part_to_lane("floortom2", "rimshot") == ("tom3", False)
    assert part_to_lane("cymbal2", "bow") == ("crash", False)
    assert part_to_lane("ride1", "bell") == ("ride", False)
    assert part_to_lane("crash1", "choke") is None and part_to_lane("perc1", "hit") is None


def test_groove_lesson_maps_notes_and_repeats(tmp_path):
    folder = vault(tmp_path)
    assert find_folder(str(folder)) == folder
    (g,) = load_grooves(folder)                               # the entry without a file is skipped
    assert g.key == "groove:G1" and g.title == "Level 1 · Groove 1" and not g.odd_time
    les = g.to_lesson()
    assert les.bpm == 120 and les.beats_per_bar == 4 and les.bars == 8   # 1 bar, repeated to 8
    first = [(round(n.t, 3), n.lane, n.open) for n in les.notes if n.t < les.bar]
    # pedal and choke left out; the crash on beat 5 (the next pass's beat 1) is dropped
    assert first == [(0.0, "hihat", False), (0.0, "kick", False), (0.5, "snare", False), (0.75, "hihat", True)]
    assert len(les.notes) == 4 * 8


def test_odd_meter_and_longer_file_than_the_metadata_says(tmp_path):
    hits = [(b, 24) for b in range(0, 14)]                    # 14 beats of 7/4 = 2 bars; metadata says 1
    g = load_grooves(vault(tmp_path, meter="7/4", bars=1, beats=hits))[0]
    les = g.to_lesson()
    assert g.odd_time and les.beats_per_bar == 7
    assert les.bars == 8 and len(les.notes) == 14 * 4
    assert les.bar == pytest.approx(3.5)


def test_no_library_means_no_grooves(tmp_path):
    assert load_grooves(None) == [] and load_grooves(tmp_path) == []


def test_grooves_are_named_by_level(tmp_path):
    from kickhero.course.grooves import by_level

    folder = vault(tmp_path)
    (one,) = load_grooves(folder)
    grooves = [GrooveLike(one, i) for i in range(10)]
    ranked = by_level(grooves)
    assert [g.level for g in ranked] == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]   # easiest first, equal levels
    assert [g.title for g in ranked[:3]] == ["Level 1 · Groove 1", "Level 1 · Fill 1", "Level 2 · Groove 1"]


class GrooveLike:
    """A groove with a set difficulty (every other one a fill)."""

    def __init__(self, groove, n):
        self.id, self.bpm, self.n = f"G{n:02d}", groove.bpm, n
        self.category = "Fill" if n % 2 else "Groove"
        self.level, self.title = 0, ""

    def difficulty(self):
        return self.n
