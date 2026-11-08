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
    assert "--bpm" not in args
    assert build_args(["a.mp3"], "out", {"bpm": 100.0})[-2:] == ["--bpm", "100"]


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
    assert [n.open for n in lesson.notes if n.lane == "hihat"] == [True]  # ...and it's an open one
    assert lesson.has_open_hats


def test_progress_best_and_streak(tmp_path):
    p = Progress(tmp_path / "p.db")
    today = dt.date(2026, 11, 6)
    for days_ago, acc, stars in ((0, 0.9, 2), (1, 0.97, 3), (2, 0.5, 0), (4, 0.8, 2)):
        when = dt.datetime.combine(today - dt.timedelta(days=days_ago), dt.time(12))
        p.record("song.mid", 1.0, {"accuracy": acc, "stars": stars}, when=when)
    assert p.best("song.mid")[:2] == (3, 0.97)
    assert p.streak(today) == 3
    assert p.best("other.mid") is None


def test_wait_mode_runs_count_for_the_streak_but_not_the_best(tmp_path):
    p = Progress(tmp_path / "p.db")
    today = dt.date(2026, 11, 6)
    p.record("song.mid", 1.0, {"accuracy": 1.0, "stars": 3}, when=dt.datetime.combine(today, dt.time(12)),
             assisted=True)
    assert p.best("song.mid") is None and not p.passed("song.mid")
    assert p.streak(today) == 1
    p.record("song.mid", 1.0, {"accuracy": 0.8, "stars": 2})
    assert p.best("song.mid")[:2] == (2, 0.8) and p.passed("song.mid")
    p.db.close()
    assert Progress(tmp_path / "p.db").best("song.mid")[:2] == (2, 0.8)  # reopening keeps the column


def test_hits_are_placed_where_they_rise_not_in_the_quiet_before():
    import numpy as np

    from kickhero.pipeline.drums2midi import detect_hits

    sr = 44100
    rng = np.random.default_rng(0)
    y = rng.normal(0, 0.01, sr * 4)                       # bleed under the hits
    times = [0.5, 1.0, 1.31, 1.5, 2.25, 3.0]
    for t in times:
        k = np.arange(int(0.2 * sr))
        hit = np.exp(-k / (0.05 * sr)) * rng.normal(0, 1, len(k))
        hit[:88] *= np.linspace(0, 1, 88)                 # 2 ms attack
        s = int(t * sr)
        y[s:s + len(k)] += hit
    found = detect_hits(y, sr, 0.07, -30, 30)[0]
    assert len(found) == len(times)
    assert np.abs(found - times).max() < 0.006


def test_history_lists_counted_runs_oldest_first(tmp_path):
    p = Progress(tmp_path / "p.db")
    day = dt.datetime(2026, 11, 6, 12)
    for i, (acc, assisted) in enumerate([(0.5, False), (1.0, True), (0.7, False)]):
        p.record("song.mid", 1.0, {"accuracy": acc, "stars": 1}, when=day + dt.timedelta(minutes=i), assisted=assisted)
    assert [r[1] for r in p.history("song.mid")] == [0.5, 0.7]
    assert [r[1] for r in p.history("song.mid", limit=1)] == [0.7]


def test_practice_time_days_played_and_recent(tmp_path):
    p = Progress(tmp_path / "p.db")
    day = dt.date(2026, 11, 6)
    at = lambda d, h=12: dt.datetime.combine(d, dt.time(h))  # noqa: E731
    p.add_time(90, when=at(day))
    p.add_time(30, when=at(day, 23))
    p.add_time(45, when=at(day - dt.timedelta(days=2)))
    assert p.seconds_on(day) == 120 and p.seconds_on(day - dt.timedelta(days=1)) == 0
    p.record("a.mid", 1.0, {"accuracy": 0.5, "stars": 1}, when=at(day - dt.timedelta(days=4)))
    p.record("b.mid", 1.0, {"accuracy": 0.5, "stars": 1}, when=at(day - dt.timedelta(days=1)))
    p.record("a.mid", 1.0, {"accuracy": 0.6, "stars": 1}, when=at(day))
    assert p.days_played(day - dt.timedelta(days=3), day) == {day, day - dt.timedelta(days=1),
                                                             day - dt.timedelta(days=2)}
    assert [k for k, _ in p.recent()] == ["a.mid", "b.mid"]


def test_home_helpers():
    from kickhero.ui.home import ago, greeting

    assert [greeting(h) for h in (7, 13, 21, 2)] == ["Good morning", "Good afternoon", "Good evening",
                                                    "Good evening"]
    today = dt.date(2026, 11, 8)
    assert ago("2026-11-08T09:00:00", today) == "today"
    assert ago("2026-11-07T23:00:00", today) == "yesterday"
    assert ago("2026-11-01T10:00:00", today) == "7 days ago"
