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


def test_riff_midi_file(tmp_path):
    """Some sites serve .mid downloads as RIFF MIDI (the standard file inside a RIFF wrapper)."""
    smf = make_midi(tmp_path / "plain.mid").read_bytes()
    pad = b"\0" if len(smf) % 2 else b""
    body = b"RMID" + b"data" + len(smf).to_bytes(4, "little") + smf + pad
    wrapped = tmp_path / "Wrapped.mid"
    wrapped.write_bytes(b"RIFF" + len(body).to_bytes(4, "little") + body)
    assert mi.read_drums(wrapped) == mi.read_drums(tmp_path / "plain.mid")


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


def test_sound_check_tells_kicks_from_snares():
    """Kick and snare on alternate beats match a recording as well a beat off; the sound of the hits
    under them settles it: low thumps under the kicks, noise bursts under the snares."""
    sr, beat = 22050, 0.5
    rnd = np.random.default_rng(0)
    y = np.zeros(sr * 40, dtype=np.float32)
    env = np.exp(-np.arange(int(0.08 * sr)) / (0.02 * sr))
    t = np.arange(4.0, 36.0, beat)
    lanes = ["kick" if i % 2 == 0 else "snare" for i in range(len(t))]
    for ti, lane in zip(t, lanes):
        n = len(env)
        hit = np.sin(2 * np.pi * 60 * np.arange(n) / sr) if lane == "kick" else rnd.standard_normal(n)
        y[int(ti * sr):int(ti * sr) + n] += 0.5 * env * hit
    times = t + rnd.uniform(-0.005, 0.005, len(t))
    tilt = mi.hit_tilt(y, sr, times)
    placed, moved = mi.sound_check(t, lanes, times, tilt, beat)
    assert placed - moved >= mi.SOUND_LEAD
    assert mi.fit_verdict(0.95, 0.94, (placed, moved)) == "good"
    assert mi.fit_verdict(0.94, 0.95, mi.sound_check(t + beat, lanes, times, tilt, beat)) == "beat_off"
    assert mi.fit_verdict(0.95, 0.94, None) == "unclear"
    assert mi.fit_verdict(0.95, 0.80, None) == "good"


def test_drums_model_is_picked_from_the_bag():
    """MIDI mode runs only htdemucs_ft's drum model; this hooks into the separator library's loader."""
    from audio_separator.separator.architectures import demucs_separator

    from kickhero.pipeline.song2drums import drums_model

    assert callable(demucs_separator.get_demucs_model)  # the name the hook replaces while separating

    class Bag:
        sources = ["drums", "bass", "other", "vocals"]
        models = ["drums-ft", "bass-ft", "other-ft", "vocals-ft"]
        weights = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]

    assert drums_model(Bag()) == "drums-ft"
    assert drums_model("single") == "single"


def test_backing_is_the_song_minus_its_drums(tmp_path):
    import soundfile as sf

    from kickhero.pipeline.song2drums import write_backing_minus_drums

    sr = 44100
    t = np.arange(sr * 3) / sr
    music = 0.3 * np.sin(2 * np.pi * 220 * t)
    drums = np.zeros_like(t)
    for k in range(12):
        s = int(k * 0.25 * sr)
        drums[s:s + 2000] += np.exp(-np.arange(2000) / 300) * np.random.default_rng(k).normal(0, 0.4, 2000)
    song = np.stack([music + drums, music + drums], 1)
    sf.write(tmp_path / "song.wav", song, sr)
    sf.write(tmp_path / "drums.wav", np.stack([drums, drums], 1) * 0.7, sr)  # stem written at another level
    write_backing_minus_drums(tmp_path / "song.wav", tmp_path / "drums.wav", tmp_path / "backing.ogg")
    back, bsr = sf.read(tmp_path / "backing.ogg", always_2d=True)
    n = min(len(back), len(music))
    residue = back[:n, 0] - music[:n] / max(np.abs(music).max(), 1.0)
    assert bsr == sr and np.sqrt(np.mean(residue ** 2)) < 0.01


def test_lined_up_song_keeps_the_intro():
    bar = 2.0
    # the file's start is 25.3 s into the recording (a long intro before the drums): bar 1 starts just
    # before the recording does, on the file's bar grid
    shift = mi.intro_shift(25.3, 0.0, bar)
    assert 0 <= shift < bar and (25.3 + shift) % bar == pytest.approx(0, abs=1e-9)
    assert mi.intro_shift(-1.0, 0.0, bar) == pytest.approx(1.0)  # the file starts before the recording
    assert mi.intro_shift(4.0, -0.5, bar) == pytest.approx(2.0)  # a note before the recording's start


def test_song_plays_to_the_end_of_its_backing_track(tmp_path):
    """The recording often goes on after the last drum note: the lesson lasts until it ends."""
    import soundfile as sf

    from kickhero.engine.lesson import from_notes

    sf.write(tmp_path / "backing.wav", np.zeros((44100 * 30, 2), dtype=np.float32), 44100)
    lesson = from_notes("x", BPM, [(0.0, "kick", 100), (10.0, "snare", 100)], backing=tmp_path / "backing.wav",
                        backing_offset=-2.0)  # the recording ends at lesson time 32 s
    assert lesson.length >= 32.0 > lesson.length - lesson.bar
    assert from_notes("x", BPM, [(0.0, "kick", 100), (10.0, "snare", 100)]).bars == 6
