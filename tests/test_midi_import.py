"""Songs from ready-made MIDI files: the drum part on its own, and lined up with a recording."""

import numpy as np
import pretty_midi
import pytest

from kickhero.engine.editing import backup_path
from kickhero.engine.lesson import load_midi
from kickhero.pipeline import midi_import as mi

BPM = 120.0
BEAT = 60 / BPM


def make_midi(path, bars=24, intro_bars=2, tempo_change=None, drums=True):
    """A rock beat from bar `intro_bars`, a bass track, and optionally a tempo change (beat, bpm)."""
    pm = pretty_midi.PrettyMIDI(initial_tempo=BPM)
    if tempo_change:
        beat, bpm = tempo_change
        res = pm.resolution
        pm._tick_scales = [(0, 60.0 / (BPM * res)), (beat * res, 60.0 / (bpm * res))]
        pm._update_tick_to_time(bars * 4 * res + res)
    kit = pretty_midi.Instrument(0, is_drum=True)
    for b in range(intro_bars, bars):
        for e in range(8):
            beat = b * 4 + e / 2
            t = pm.tick_to_time(int(beat * pm.resolution))
            kit.notes.append(pretty_midi.Note(80, 42, t, t + 0.05))
            if e % 4 == 0:
                kit.notes.append(pretty_midi.Note(110, 36, t, t + 0.05))
            if e % 4 == 2:
                kit.notes.append(pretty_midi.Note(115, 38, t, t + 0.05))
            if e == 2:
                kit.notes.append(pretty_midi.Note(90, 44, t, t + 0.05))  # hi-hat pedal: left out
    bass = pretty_midi.Instrument(33)
    bass.notes.append(pretty_midi.Note(90, 40, 0.0, 1.0))
    pm.instruments += [kit, bass] if drums else [bass]
    pm.write(str(path))
    return path


def test_song_name():
    assert mi.song_name("Back-In-Black.mid") == "Back In Black"
    assert mi.song_name("AC_DC - Back In Black.mid") == "AC_DC - Back In Black"


def test_plain_import(tmp_path):
    midi = make_midi(tmp_path / "Some-Song.mid")
    path = mi.import_midi(midi, tmp_path / "lib")
    assert path == tmp_path / "lib" / "Some Song" / "Some Song_drums.mid"
    lesson = load_midi(path)
    assert lesson.bpm == pytest.approx(BPM, abs=0.01)
    assert lesson.title == "Some Song"
    assert lesson.backing is None
    assert lesson.lanes_used == {"kick", "snare", "hihat"}  # bass ignored, pedal hi-hat left out
    assert min(n.t for n in lesson.notes) == pytest.approx(0.0, abs=1e-3)  # empty intro bars trimmed
    assert lesson.bars == 22
    assert sum(n.lane == "snare" for n in lesson.notes) == 22 * 2


def test_tempo_change_is_flattened(tmp_path):
    midi = make_midi(tmp_path / "Faster.mid", tempo_change=(64, 150.0))
    notes, info = mi.read_drums(midi)
    assert info["tempo_changes"] and info["bpm"] == pytest.approx(BPM, abs=0.01)
    lesson = load_midi(mi.import_midi(midi, tmp_path / "lib"))
    # every snare still on beat 2 or 4 of a bar after the change
    for n in lesson.notes:
        if n.lane == "snare":
            assert (n.t / lesson.beat) % 4 == pytest.approx(round((n.t / lesson.beat) % 4), abs=1e-3)
            assert round((n.t / lesson.beat) % 4) in (1, 3)


def test_no_drums(tmp_path):
    with pytest.raises(mi.MidiImportError):
        mi.read_drums(make_midi(tmp_path / "x.mid", drums=False))
    (tmp_path / "bad.mid").write_bytes(b"not midi")
    with pytest.raises(mi.MidiImportError):
        mi.read_drums(tmp_path / "bad.mid")


def test_import_replaces_editor_backup(tmp_path):
    midi = make_midi(tmp_path / "Song.mid")
    path = mi.import_midi(midi, tmp_path / "lib")
    backup_path(path).write_bytes(path.read_bytes())
    mi.import_midi(midi, tmp_path / "lib")
    assert not backup_path(path).exists()


def test_align_to_recording(tmp_path):
    """The recording starts 1.7 s later, runs 2% faster and drifts by up to 40 ms."""
    midi = make_midi(tmp_path / "Song.mid", bars=40)
    notes, info = mi.read_drums(midi)
    rng = np.random.default_rng(0)
    heard = np.array([1.7 + n[0] / 1.02 + 0.04 * np.sin(n[0] / 12) for n in notes])
    times = np.unique(np.round(heard + rng.normal(0, 0.003, len(heard)), 4))
    t, bpm, origin, first, (rate, off) = mi.align(notes, info, times, np.ones(len(times)), heard.max() + 3)
    assert bpm == pytest.approx(BPM * 1.02, rel=0.005)
    assert np.median(np.abs(t - heard)) < 0.006
    assert rate > 0.95
    assert first / (240 / bpm) == pytest.approx(2.0, abs=1e-3)  # two empty bars before the first note
    assert origin == pytest.approx(1.7, abs=0.05)


def test_wrong_recording_is_not_a_clear_fit(tmp_path):
    """Drums that have nothing to do with the MIDI file: no fit beats the part moved a beat."""
    midi = make_midi(tmp_path / "Song.mid", bars=40)
    notes, info = mi.read_drums(midi)
    times = np.sort(np.random.default_rng(3).uniform(0, 90, 400))
    *_, (rate, off) = mi.align(notes, info, times, np.ones(len(times)), 92)
    assert rate - off < mi.CLEAR_LEAD
