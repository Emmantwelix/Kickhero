"""Songs from ready-made MIDI files (e.g. downloaded transcriptions): keep the drum part, and optionally
line it up with a recording of the song so it plays along with the real track.

Without a recording the part is put on one steady tempo (tempo changes in the file are dropped, so the bar
lines and metronome stay on the notes). With one, the notes are moved onto the drums heard in the
recording: a best-fit start and tempo first, then small local corrections where the band speeds up or
slows down. Either way the song is written like a converted one: <name>/<name>_drums.mid + .json.
"""

import datetime
import io
import json
import math
import re
from pathlib import Path

import numpy as np

from ..engine.editing import backup_path
from ..lanes import HIHAT_PEDAL, NOTE_TO_LANE

NOTE_LEN = 0.05
# How much each drum counts when lining up with a recording: kick and snare carry the beat, hi-hats
# and rides repeat so evenly that on their own they fit at any eighth note
ALIGN_WEIGHT = {"kick": 1.0, "snare": 1.0, "tom1": 0.6, "tom2": 0.6, "tom3": 0.6, "crash": 0.6,
                "hihat": 0.25, "ride": 0.25}
MATCH_S = 0.05  # a note "matches" the recording if a drum hit is heard this close to it
# How a fit is judged: the share of kick and snare notes that match, against the same part moved a beat
# either way. Hit detection misses some hits in a busy drum stem, and steady drumming matches fairly well
# even a beat off, so the share alone says little; a fit that's right beats the moved part clearly.
CLEAR_LEAD = 0.10


class MidiImportError(ValueError):
    """The file can't be used (not a MIDI file, or no drum part in it)."""


def song_name(path):
    """A readable song name from a downloaded file name: 'Back-In-Black.mid' -> 'Back In Black'."""
    stem = Path(path).stem
    if " " not in stem:
        stem = re.sub(r"[-_]+", " ", stem)
    return re.sub(r"\s+", " ", stem).strip() or "Imported song"


def unwrap_rmid(data):
    """The standard MIDI file inside a RIFF MIDI (.rmi) file; other data is returned as it is. Some sites
    serve their .mid downloads in this wrapper."""
    if data[:4] == b"RIFF" and data[8:12] == b"RMID":
        i = 12
        while i + 8 <= len(data):
            size = int.from_bytes(data[i + 4:i + 8], "little")
            if data[i:i + 4] == b"data":
                return data[i + 8:i + 8 + size]
            i += 8 + size + (size & 1)
    return data


def read_drums(path):
    """The drum notes of a MIDI file. Returns (notes, info): notes are (seconds, beats, pitch, velocity)
    tuples (beats in quarter notes from the start of the file); info has the main tempo and whether the
    tempo changes. Hi-hat pedal notes are left out (they're the foot, under a ride or crash pattern)."""
    import pretty_midi

    try:
        pm = pretty_midi.PrettyMIDI(io.BytesIO(unwrap_rmid(Path(path).read_bytes())))
    except Exception as e:
        raise MidiImportError(f"This doesn't look like a MIDI file ({e}).") from e
    drums = [i for i in pm.instruments if i.is_drum]
    if not drums:
        raise MidiImportError("This MIDI file has no drum track.")
    notes = sorted((float(n.start), pm.time_to_tick(n.start) / pm.resolution, n.pitch, int(n.velocity))
                   for inst in drums for n in inst.notes
                   if n.pitch in NOTE_TO_LANE and n.pitch != HIHAT_PEDAL and n.velocity > 0)
    if not notes:
        raise MidiImportError("The drum track in this MIDI file has no notes the app can use.")
    times, tempi = pm.get_tempo_changes()
    if len(tempi) == 0:
        times, tempi = np.array([0.0]), np.array([120.0])
    end = max(notes[-1][0], float(times[-1])) + 1.0
    held = np.diff(np.append(times, end))
    main = float(tempi[int(np.argmax(held))])  # the tempo the song spends the most time at
    changes = bool(np.any(np.abs(tempi / main - 1) > 0.005))
    return notes, {"bpm": main, "tempo_changes": changes}


def write_song(folder, name, notes, bpm, shift=0.0, backing=None, **info):
    """Write <folder>/<name>_drums.mid (one drum track) and its sidecar .json; returns the MIDI path.
    notes are (seconds from bar 1, pitch, velocity)."""
    import pretty_midi

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    midi_path = folder / f"{name}_drums.mid"
    midi = pretty_midi.PrettyMIDI(initial_tempo=bpm)
    drums = pretty_midi.Instrument(program=0, is_drum=True, name="Drums")
    for t, pitch, vel in notes:
        drums.notes.append(pretty_midi.Note(velocity=int(vel), pitch=int(pitch), start=float(t),
                                            end=float(t) + NOTE_LEN))
    midi.instruments.append(drums)
    midi.write(str(midi_path))
    meta = dict(title=name, bpm=round(float(bpm), 3), shift=float(shift), backing=backing, **info)
    meta["created"] = datetime.datetime.now().isoformat(timespec="seconds")
    midi_path.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    old = backup_path(midi_path)  # the editor's copy of a part this one replaces: "Revert" would bring it back
    old.unlink(missing_ok=True)
    old.with_suffix(".json").unlink(missing_ok=True)
    return midi_path


def bar_trim(first, bar):
    """How far to move a part so its first note lands in bar 1 (empty bars before it are dropped)."""
    return -math.floor(first / bar + 1e-3) * bar


def import_midi(midi_path, library, name=None):
    """Add a MIDI file's drum part to the library on a steady tempo; returns the new song's MIDI path."""
    notes, info = read_drums(midi_path)
    name = name or song_name(midi_path)
    beat = 60.0 / info["bpm"]
    first = min(n[1] for n in notes) * beat
    move = bar_trim(first, 4 * beat)
    out = [(b * beat + move, pitch, vel) for _, b, pitch, vel in notes]
    return write_song(Path(library) / name, name, out, info["bpm"], source=str(Path(midi_path).resolve()),
                      imported="midi")


# ---------- lining up with a recording ----------

def _train(times, weights, n, fps, sigma):
    """Hits as a smooth pulse train: n frames at fps, each hit a Gaussian bump sigma frames wide."""
    x = np.zeros(n)
    idx = np.round(np.asarray(times) * fps).astype(int)
    ok = (idx >= 0) & (idx < n)
    np.add.at(x, idx[ok], np.asarray(weights)[ok])
    k = np.arange(-4 * sigma, 4 * sigma + 1)
    return np.convolve(x, np.exp(-0.5 * (k / sigma) ** 2), mode="same")


def _best_lag(audio, src, weights, scales, fps, sigma, length, near=None):
    """For each tempo scale, slide the scaled MIDI over the recording; the best (score, scale, lag).
    near=(lag, reach): only lags within reach seconds of lag (a finer look at an earlier result)."""
    from scipy.signal import fftconvolve

    a = _train(audio[0], audio[1], int(length * fps) + 1, fps, sigma)
    best = (-1.0, 1.0, 0.0)
    for s in scales:
        m = _train(np.asarray(src) * s, weights, int(max(src) * s * fps) + 4 * sigma + 2, fps, sigma)
        corr = fftconvolve(a, m[::-1], mode="full") / (np.linalg.norm(m) or 1.0)
        if near:  # lag = (k - (len(m) - 1)) / fps
            lo = max(0, int((near[0] - near[1]) * fps) + len(m) - 1)
            hi = max(lo + 1, int((near[0] + near[1]) * fps) + len(m))
            corr = np.concatenate([np.full(lo, -np.inf), corr[lo:hi], np.full(max(0, len(corr) - hi), -np.inf)])
        k = int(np.argmax(corr))
        if corr[k] > best[0]:
            best = (float(corr[k]), float(s), (k - (len(m) - 1)) / fps)
    return best


def _local_offsets(pred, weights, audio, fps=100, sigma=2, win=8.0, reach=0.15):
    """Small corrections along the song: in 8 s windows, the shift (within +-reach s) that best lines the
    notes up with the recording. Returns a function: predicted time -> corrected time."""
    centers, offsets = [], []
    lags = np.arange(-int(reach * fps), int(reach * fps) + 1)
    for c in np.arange(pred.min() + win / 2, pred.max() - win / 4, win / 2):
        sel = np.abs(pred - c) <= win / 2
        if sel.sum() < 8:
            continue
        t0 = c - win / 2 - reach - 0.1
        n = int((win + 2 * reach + 0.2) * fps)
        m = _train(pred[sel] - t0, weights[sel], n, fps, sigma)
        near = (audio[0] > t0) & (audio[0] < t0 + n / fps)
        a = _train(audio[0][near] - t0, audio[1][near], n, fps, sigma)
        score = np.array([np.dot(np.roll(m, d), a) for d in lags])
        score *= 1 - 0.3 * np.abs(lags) / lags.max()  # if in doubt, the smaller correction
        if score.max() <= 0:
            continue
        centers.append(c)
        offsets.append(lags[int(np.argmax(score))] / fps)
    if not centers:
        return lambda t: t
    off = np.array(offsets)
    if len(off) >= 3:  # one odd window (a fill, a break) shouldn't bend the rest
        off = np.array([np.median(off[max(0, i - 1):i + 2]) for i in range(len(off))])
    return lambda t: t + np.interp(t, centers, off)


def _residual_fix(t, audio, win=4.0):
    """Last touch: the median distance to the nearest heard hit, smoothed over 4 s windows."""
    hits = np.sort(audio[0])
    if len(hits) < 2:
        return t
    i = np.clip(np.searchsorted(hits, t), 1, len(hits) - 1)
    near = np.where(np.abs(hits[i] - t) < np.abs(hits[i - 1] - t), hits[i], hits[i - 1])
    d = near - t
    ok = np.abs(d) < MATCH_S
    centers, offsets = [], []
    for c in np.arange(t.min(), t.max() + win, win / 2):
        sel = ok & (np.abs(t - c) <= win / 2)
        if sel.sum() >= 6:
            centers.append(c)
            offsets.append(float(np.median(d[sel])))
    return t + np.interp(t, centers, offsets) if centers else t


def match_rate(t, audio_times):
    """Share of the note times that have a drum hit in the recording within MATCH_S."""
    hits = np.sort(audio_times)
    t = np.unique(np.round(t, 3))
    if not len(hits) or not len(t):
        return 0.0
    i = np.clip(np.searchsorted(hits, t), 1, max(1, len(hits) - 1))
    d = np.minimum(np.abs(hits[np.minimum(i, len(hits) - 1)] - t), np.abs(hits[i - 1] - t))
    return float(np.mean(d < MATCH_S))


def drum_hits(drums_wav):
    """Times and loudness of the hits heard in a drum stem."""
    import librosa

    from .drums2midi import detect_hits

    y, sr = librosa.load(str(drums_wav), sr=22050, mono=True)
    times, peak_db, _, _ = detect_hits(y, sr, sensitivity=0.03, gate_db=-40.0, min_gap_ms=30.0)
    return np.asarray(times), 10 ** (np.asarray(peak_db) / 20), len(y) / sr


def align(notes, info, audio_times, audio_weights, length):
    """Where each note (from read_drums) is heard in the recording. Tries the file's own timing and its
    beats on one steady tempo, each stretched 0.8x-1.25x; the best fit is then corrected locally.
    Returns (times in the recording, grid tempo there, where the file's start falls in the recording,
    the first note's distance from the file's start on that grid, (match rate, match rate a beat off))."""
    audio = (np.asarray(audio_times), np.asarray(audio_weights))
    weights = np.array([ALIGN_WEIGHT[NOTE_TO_LANE[p]] * (0.4 + 0.6 * v / 127) for _, _, p, v in notes])
    beat = 60.0 / info["bpm"]
    sources = {"seconds": np.array([n[0] for n in notes])}
    if info["tempo_changes"]:
        sources["beats"] = np.array([n[1] for n in notes]) * beat
    best = None
    for kind, src in sources.items():
        coarse = _best_lag(audio, src, weights, np.arange(0.80, 1.25, 0.0005), 20, 2, length)
        fine = _best_lag(audio, src, weights, coarse[1] + np.arange(-0.001, 0.0011, 0.0001), 100, 3, length,
                         near=(coarse[2], 0.12))
        if best is None or fine[0] > best[0]:
            best = (*fine, kind, src)
    _, scale, lag, kind, src = best
    pred = src * scale + lag
    t = _local_offsets(pred, weights, audio)(pred)
    t = _residual_fix(t, audio)
    origin = float(lag + np.interp(lag, pred, t - pred))  # the file's start, corrected like the notes near it
    # scored on kick and snare: a drum stem's hit detection misses many hi-hats and cymbals (under other
    # cymbals, or together with a kick), so counting those would make a good fit look poor
    beat_keepers = np.array([NOTE_TO_LANE[n[2]] in ("kick", "snare") for n in notes])
    scored = t[beat_keepers] if beat_keepers.sum() >= 8 else t
    beat_there = 60.0 * scale / info["bpm"]
    off = max(match_rate(scored + d, audio[0]) for d in (-beat_there, beat_there))
    return t, info["bpm"] / scale, origin, float(pred.min() - lag), (match_rate(scored, audio[0]), off)


def intro_shift(origin, earliest, bar):
    """The shift (lesson time = recording time + shift) that keeps the whole recording, intro included:
    bar 1 is the file's bar that starts at, or just before, the start of the recording (or before the
    earliest note, if a note comes before that). `origin`: where the file's start falls in the recording."""
    return -origin + math.ceil((origin - earliest) / bar - 1e-3) * bar


def import_aligned(midi_path, drums_wav, folder, name, backing=None, source=None):
    """Write the MIDI's drum part lined up with a recording whose drum stem is drums_wav (and drumless
    mix `backing`, a file name in `folder`). Returns (MIDI path, (match rate, match rate a beat off))."""
    notes, info = read_drums(midi_path)
    times, weights, length = drum_hits(drums_wav)
    if len(times) < 8:
        raise MidiImportError("Hardly any drums can be heard in this recording, so the MIDI can't be lined up.")
    t, bpm, origin, _, fit = align(notes, info, times, weights, length)
    shift = intro_shift(origin, min(0.0, float(t.min())), 240.0 / bpm)
    out = [(float(ti) + shift, pitch, vel) for ti, (_, _, pitch, vel) in zip(t, notes)]
    path = write_song(folder, name, out, bpm, shift=shift, backing=backing, source=source,
                      midi_source=str(Path(midi_path).resolve()), imported="midi", match=round(fit[0], 3),
                      match_beat_off=round(fit[1], 3))
    return path, fit
