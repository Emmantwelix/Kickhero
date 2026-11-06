import datetime as dt
import json

import pretty_midi
import pytest

from kickhero.engine.lesson import load_midi
from kickhero.pipeline.song2drums import stem_name, write_metadata
from kickhero.pipeline.worker import build_args
from kickhero.progress import Progress


def write_midi(path, bpm=100, hits=((0.0, 36), (0.6, 38), (0.6, 42), (0.6, 46), (1.2, 36))):
    pm = pretty_midi.PrettyMIDI(initial_tempo=bpm)
    inst = pretty_midi.Instrument(program=0, is_drum=True)
    for t, pitch in hits:
        inst.notes.append(pretty_midi.Note(velocity=100, pitch=pitch, start=t, end=t + 0.05))
    pm.instruments.append(inst)
    pm.write(str(path))


def test_stem_name_uses_last_bracket_tag():
    assert stem_name("Kick (Live)_(Drums)_htdemucs_ft.wav") == "drums"
    assert stem_name("song_(Vocals)_htdemucs_ft.wav") == "vocals"
    assert stem_name("plain.wav") == ""


def test_build_args_defaults_and_options():
    args = build_args(["a.mp3"], "out", {"quantize": 16, "align": False, "sensitivity": 0.05})
    assert args[:4] == ["a.mp3", "-o", "out", "--force"]
    assert args[args.index("--sensitivity") + 1] == "0.05"
    assert args[args.index("--quantize") + 1] == "16"
    assert "--no-align" in args and "--no-split-toms" not in args


def test_lesson_reads_sidecar_metadata(tmp_path):
    song = tmp_path / "Song"
    song.mkdir()
    mid = song / "Song_drums.mid"
    write_midi(mid)
    (song / "backing.ogg").write_bytes(b"")  # existence is all load_midi checks
    write_metadata(mid.with_suffix(".json"), title="My Song", bpm=100, shift=-5.25, backing="backing.ogg")
    lesson = load_midi(mid)
    assert lesson.title == "My Song"
    assert lesson.backing == song / "backing.ogg"
    assert lesson.backing_offset == pytest.approx(5.25)
    assert json.loads(mid.with_suffix(".json").read_text())["created"]


def test_lesson_without_metadata_and_hihat_merge(tmp_path):
    mid = tmp_path / "x_drums.mid"
    write_midi(mid)
    lesson = load_midi(mid, quantize=16)
    assert lesson.title == "x" and lesson.backing is None
    assert lesson.bpm == pytest.approx(100)
    # closed + open hi-hat on the same hit become one hi-hat note
    assert sorted(n.lane for n in lesson.notes) == ["hihat", "kick", "kick", "snare"]


def test_progress_best_and_streak(tmp_path):
    p = Progress(tmp_path / "p.db")
    today = dt.date(2026, 11, 6)
    for days_ago, acc, stars in ((0, 0.9, 2), (1, 0.97, 3), (2, 0.5, 0), (4, 0.8, 2)):
        when = dt.datetime.combine(today - dt.timedelta(days=days_ago), dt.time(12))
        p.record("song.mid", 1.0, {"accuracy": acc, "stars": stars}, when=when)
    assert p.best("song.mid")[:2] == (3, 0.97)
    assert p.streak(today) == 3
    assert p.best("other.mid") is None
