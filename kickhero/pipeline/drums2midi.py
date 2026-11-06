#!/usr/bin/env python3
"""
drums2midi.py — turn separated drum-piece stems (kick, snare, hi-hat, ...) into one drum MIDI file.

Usage:
    python drums2midi.py STEMS_FOLDER -o drums.mid [options]

Each .wav/.flac/.mp3 in STEMS_FOLDER is matched to a drum piece by its file name
(e.g. "song_(kick).wav" -> kick -> MIDI note 36). Every hit is found with onset
detection, its loudness becomes the velocity, and all pieces are written to one
General MIDI drum track (channel 10).
"""

import argparse
import re
from pathlib import Path

import librosa
import numpy as np
import pretty_midi

# File-name keyword -> General MIDI drum note. Checked in this order, first match wins.
KEYWORD_NOTES = [
    (r"kick|bass[ _-]?drum|\bbd\b", "kick", 36),
    (r"snare|\bsd\b", "snare", 38),
    (r"hi[ _-]?hat|\bhh\b", "hihat", 42),
    (r"ride", "ride", 51),
    (r"crash", "crash", 49),
    (r"cymbal", "cymbals", 49),
    (r"tom", "toms", 47),
]

HIHAT_OPEN = 46
TOM_NOTES_LOW_TO_HIGH = [43, 47, 50]  # floor tom, low-mid tom, high tom
AUDIO_EXTS = {".wav", ".flac", ".mp3", ".ogg", ".aiff", ".aif"}


def _match_text(text, overrides):
    for piece, note in overrides.items():
        if piece in text:
            return piece, note
    for pattern, piece, note in KEYWORD_NOTES:
        if re.search(pattern, text):
            return piece, note
    return None, None


def match_piece(filename, overrides):
    name = Path(filename).stem.lower()
    # Separator outputs tag the stem in brackets, e.g. "drums_(hh)_MDX23C...". Trust the
    # last bracketed tag first so words in the song title can't cause a wrong match.
    for tag in reversed(re.findall(r"\(([^)]+)\)", name)):
        piece, note = _match_text(tag, overrides)
        if piece:
            return piece, note
    return _match_text(name, overrides)


def attack_start(y, sr, s, ahead_ms=60.0, back_ms=10.0):
    """Where the hit found near sample s actually rises: a quarter of the way up from the quiet
    before it to its peak.

    Backtracking alone goes to the quietest point before an onset, which in a separated stem
    (smeared transients, bleed, the previous hit's tail) is often tens of ms early; and onset
    frames are ~6 ms apart, so the search starts a little before s."""
    a = max(0, s - int(back_ms / 1000 * sr))
    seg = np.abs(y[a:s + int(ahead_ms / 1000 * sr)])
    if seg.size == 0 or seg.max() == 0:
        return s
    floor = seg[:max(1, int(0.002 * sr))].max()
    env = np.maximum.accumulate(seg)
    return a + int(np.argmax(env >= floor + 0.25 * (env[-1] - floor)))


def detect_hits(y, sr, sensitivity, gate_db, min_gap_ms, ref_peak=None, ref_gate_db=-36.0):
    """Return (onset_times, peak_dB_relative_to_loudest_hit, onset_samples, peak_dB_relative_to_ref).

    With ref_peak (peak amplitude of the full drum mix), hits more than ref_gate_db below it are
    dropped too. The per-stem gate alone can't do this: a stem holding only bleed still has a
    "loudest hit", so its bleed would pass.
    """
    hop = 256
    pad = hop * 8  # silence in front so a hit at 0:00 still counts as an onset
    yp = np.concatenate([np.zeros(pad), y])
    env = librosa.onset.onset_strength(y=yp, sr=sr, hop_length=hop)
    onset_frames = librosa.onset.onset_detect(
        onset_envelope=env, sr=sr, hop_length=hop,
        backtrack=True, delta=sensitivity, units="frames",
    )
    onset_samples = np.clip(librosa.frames_to_samples(onset_frames, hop_length=hop) - pad, 0, None)
    onset_samples = np.array([attack_start(y, sr, s) for s in onset_samples], dtype=int)

    # Peak level in the first 50 ms after each onset
    win = int(0.05 * sr)
    peaks = np.array([np.max(np.abs(y[s:s + win])) if s < len(y) else 0.0 for s in onset_samples])
    if len(peaks) == 0 or peaks.max() == 0:
        return np.array([]), np.array([]), np.array([], dtype=int), np.array([])
    peak_db = 20 * np.log10(peaks / peaks.max() + 1e-12)
    abs_db = 20 * np.log10(peaks / (ref_peak or peaks.max()) + 1e-12)

    # Gate out quiet hits (usually bleed from other drums)
    keep = peak_db >= gate_db
    if ref_peak:
        keep &= abs_db >= ref_gate_db
    onset_samples, peak_db, abs_db = onset_samples[keep], peak_db[keep], abs_db[keep]

    # Enforce a minimum gap between hits
    min_gap = int(min_gap_ms / 1000 * sr)
    final_s, final_db, final_abs = [], [], []
    for s, db, ab in zip(onset_samples, peak_db, abs_db):
        if final_s and s - final_s[-1] < min_gap:
            if db > final_db[-1]:  # keep the louder of two close hits
                final_s[-1], final_db[-1], final_abs[-1] = s, db, ab
            continue
        final_s.append(s)
        final_db.append(db)
        final_abs.append(ab)

    final_s = np.array(final_s, dtype=int)
    return final_s / sr, np.array(final_db), final_s, np.array(final_abs)


def bleed_mask(times, abs_db, others, window_s=0.05, bleed_db=10.0):
    """True for hits that are real, False for hits within window_s of a hit on another
    piece that is at least bleed_db louder (i.e. that hit leaking into this stem)."""
    keep = np.ones(len(times), dtype=bool)
    for o_times, o_db in others:
        if len(o_times) == 0:
            continue
        for i, (t, db) in enumerate(zip(times, abs_db)):
            near = np.abs(o_times - t) < window_s
            if near.any() and o_db[near].max() - db >= bleed_db:
                keep[i] = False
    return keep


def db_to_velocity(peak_db, gate_db, vmin=20, vmax=127):
    frac = np.clip((peak_db - gate_db) / (0 - gate_db), 0, 1)
    return np.round(vmin + frac * (vmax - vmin)).astype(int)


def decay_ms(y, sr, start, next_start, drop_db=20):
    """How long a hit rings before falling drop_db below its peak (used for open vs closed hi-hat)."""
    end = min(next_start, start + int(1.0 * sr), len(y))
    seg = np.abs(y[start:end])
    if len(seg) < 64:
        return 0.0
    frame = 256
    rms = np.sqrt(np.convolve(seg ** 2, np.ones(frame) / frame, mode="valid"))
    peak_i = int(np.argmax(rms))
    thresh = rms[peak_i] * 10 ** (-drop_db / 20)
    below = np.where(rms[peak_i:] < thresh)[0]
    n = below[0] if len(below) else len(rms) - peak_i
    return n / sr * 1000


def spectral_centroid_at(y, sr, start):
    seg = y[start:start + int(0.08 * sr)]
    if len(seg) < 512:
        return 0.0
    return float(np.mean(librosa.feature.spectral_centroid(y=seg, sr=sr, n_fft=512, hop_length=128)))


def kmeans_1d(values, k, iters=50):
    values = np.asarray(values, dtype=float)
    k = min(k, len(np.unique(values)))
    centers = np.quantile(values, np.linspace(0, 1, k + 2)[1:-1])
    for _ in range(iters):
        labels = np.argmin(np.abs(values[:, None] - centers[None, :]), axis=1)
        new = np.array([values[labels == i].mean() if np.any(labels == i) else centers[i] for i in range(k)])
        if np.allclose(new, centers):
            break
        centers = new
    order = np.argsort(centers)  # rank clusters low -> high
    rank = np.empty_like(order)
    rank[order] = np.arange(k)
    return rank[labels], k


def quantize(times, bpm, grid):
    step = 60.0 / bpm * 4 / grid  # grid=16 -> sixteenth notes
    return np.round(times / step) * step


def loud(times, vels, frac=0.8):
    times, vels = np.asarray(times), np.asarray(vels)
    return times[vels >= frac * vels.max()] if len(vels) else times


def fit_backbeat_tempo(snare_times, snare_vels, bpm):
    """Halve bpm when the loud snares (the backbeat) land every 4 beats instead of every 2,
    i.e. the tempo estimate counted a half-time groove's half bar as a whole bar. Never doubles:
    syncopated snare accents (funk, breakbeats) also give short gaps, so that would misfire."""
    gaps = np.diff(loud(snare_times, snare_vels)) / (60.0 / bpm)
    if len(gaps) >= 3 and 3.5 < np.median(gaps) < 4.5:
        return bpm / 2
    return bpm


def bar_align_shift(kicks, kick_vels, snares, snare_vels, earliest, bpm):
    """Seconds to add to every note so beat 1 lands on a bar line, leaving whole bars in front
    for any pickup notes. Beat 1 is the quarter-note position that best puts the kicks on 1 and 3
    and the snares on 2 and 4, on the 16th grid that best fits the kick and snare hits."""
    beat = 60.0 / bpm
    step, bar = beat / 4, beat * 4
    grid_times = np.concatenate([kicks, snares])
    phase = np.angle(np.mean(np.exp(2j * np.pi * grid_times / step))) / (2 * np.pi) * step

    def weight_per_16th(times, vels):  # velocity landing on each of the 16 sixteenths of a bar
        w = np.zeros(16)
        # cubed velocity, so loud backbeat hits outweigh many ghost notes
        np.add.at(w, np.round((np.asarray(times) - phase) / step).astype(int) % 16, (np.asarray(vels) / 127) ** 3)
        return w

    kw, sw = weight_per_16th(kicks, kick_vels), weight_per_16th(snares, snare_vels)
    # Beat 1 is the sixteenth r with kicks on r and r+8 (beats 1, 3), snares on r+4 and r+12 (2, 4).
    # The 1.01 prefers the bar that starts with a kick when beats 1 and 3 tie.
    score = [kw[r] * 1.01 + kw[(r + 8) % 16] + sw[(r + 4) % 16] + sw[(r + 12) % 16] for r in range(16)]
    r = int(np.argmax(score))
    first = phase + np.round((grid_times.min() - phase) / step) * step
    origin = first + ((r - np.round((first - phase) / step)) % 16) * step  # first beat 1 at/after `first`
    lead = np.ceil(max(0.0, origin - earliest - step / 2) / bar) * bar
    return lead - origin


def main(argv=None):
    p = argparse.ArgumentParser(description="Convert separated drum stems into a drum MIDI file.")
    p.add_argument("folder", help="Folder containing kick/snare/hihat/... stems")
    p.add_argument("-o", "--output", default="drums.mid", help="Output MIDI path (default: drums.mid)")
    p.add_argument("--bpm", type=float, default=120.0, help="Song tempo written to the MIDI file (default 120)")
    p.add_argument("--quantize", type=int, default=0, metavar="GRID",
                   help="Snap hits to a grid, e.g. 16 for sixteenths (requires correct --bpm). Default: off")
    p.add_argument("--sensitivity", type=float, default=0.07,
                   help="Onset threshold. Lower = more hits detected (try 0.03-0.15). Default 0.07")
    p.add_argument("--gate", type=float, default=-30.0,
                   help="Ignore hits quieter than this many dB below the loudest hit in that stem. Default -30")
    p.add_argument("--min-gap", type=float, default=30.0, help="Minimum ms between two hits on one piece. Default 30")
    p.add_argument("--hihat-open-ms", type=float, default=0.0,
                   help="Hi-hat hits ringing longer than this (ms) become open hi-hat (46). Try 150. Default: off")
    p.add_argument("--ref", metavar="AUDIO",
                   help="Full drum stem the kit was split from. Enables --ref-gate and --bleed-db")
    p.add_argument("--ref-gate", type=float, default=-36.0,
                   help="With --ref: ignore hits more than this many dB below the drum stem's peak. Default -36")
    p.add_argument("--bleed-db", type=float, default=10.0,
                   help="With --ref: drop tom hits within 50 ms of a kick/snare hit at least this many dB "
                        "louder (snare/kick bleed). 0 = off. Default 10")
    p.add_argument("--no-align", action="store_true",
                   help="Keep the original timing instead of moving beat 1 onto a bar line")
    p.add_argument("--fit-tempo", action="store_true",
                   help="Treat --bpm as an estimate: halve/double it so the snare backbeat falls on 2 and 4")
    p.add_argument("--split-toms", action="store_true",
                   help="Split a single toms stem into floor/low-mid/high toms by pitch")
    p.add_argument("--map", action="append", default=[], metavar="NAME=NOTE",
                   help="Override/add a mapping, e.g. --map perc=39. Repeatable")
    args = p.parse_args(argv)

    overrides = {}
    for m in args.map:
        name, note = m.split("=")
        overrides[name.strip().lower()] = int(note)

    folder = Path(args.folder)
    files = sorted(f for f in folder.iterdir() if f.suffix.lower() in AUDIO_EXTS)
    if not files:
        raise SystemExit(f"No audio files found in {folder}")

    midi = pretty_midi.PrettyMIDI(initial_tempo=args.bpm)
    drums = pretty_midi.Instrument(program=0, is_drum=True, name="Drums")
    note_len = 0.05

    ref_peak = None
    if args.ref:
        ref_peak = float(np.max(np.abs(librosa.load(args.ref, sr=None, mono=True)[0]))) or None

    # Pass 1: find hits on every stem (the bleed check needs all of them)
    stems = []
    for f in files:
        piece, note = match_piece(f.name, overrides)
        if piece is None:
            print(f"  skip  {f.name}  (no drum keyword in the name; use --map)")
            continue
        y, sr = librosa.load(str(f), sr=None, mono=True)
        hits = detect_hits(y, sr, args.sensitivity, args.gate, args.min_gap, ref_peak, args.ref_gate)
        stems.append((f, piece, note, y, sr, hits))

    # Pass 2: drop bleed, classify, write
    for f, piece, note, y, sr, (times, peak_db, starts, abs_db) in stems:
        if piece == "toms" and ref_peak and args.bleed_db > 0 and len(times):
            others = [(h[0], h[3]) for _, pc, _, _, _, h in stems if pc in ("kick", "snare")]
            keep = bleed_mask(times, abs_db, others, bleed_db=args.bleed_db)
            times, peak_db, starts = times[keep], peak_db[keep], starts[keep]
        if len(times) == 0:
            print(f"  {piece:8s} {f.name}: no hits found")
            continue
        vels = db_to_velocity(peak_db, args.gate)
        notes = np.full(len(times), note)

        if piece == "hihat" and args.hihat_open_ms > 0:
            nexts = list(starts[1:]) + [len(y)]
            for i, (s, n) in enumerate(zip(starts, nexts)):
                if decay_ms(y, sr, s, n) > args.hihat_open_ms:
                    notes[i] = HIHAT_OPEN

        if piece == "toms" and args.split_toms and len(times) >= 2:
            cents = [spectral_centroid_at(y, sr, s) for s in starts]
            ranks, k = kmeans_1d(cents, 3)
            tom_set = TOM_NOTES_LOW_TO_HIGH if k == 3 else [43, 50][:k]
            notes = np.array([tom_set[r] for r in ranks])

        for t, v, n in zip(times, vels, notes):
            drums.notes.append(pretty_midi.Note(velocity=int(v), pitch=int(n), start=float(t), end=float(t) + note_len))

        summary = ", ".join(f"note {n}: {c}" for n, c in zip(*np.unique(notes, return_counts=True)))
        print(f"  {piece:8s} {f.name}: {len(times)} hits ({summary})")

    if not drums.notes:
        raise SystemExit("No hits found in any stem")

    kicks = [(n.start, n.velocity) for n in drums.notes if n.pitch == 36]
    snares = [(n.start, n.velocity) for n in drums.notes if n.pitch == 38]
    if args.fit_tempo and snares:
        bpm = fit_backbeat_tempo(*zip(*snares), args.bpm)
        if bpm != args.bpm:
            print(f"  tempo: using {bpm:.1f} BPM (the snare backbeat shows {args.bpm:.1f} was double-time)")
            args.bpm = bpm
            midi = pretty_midi.PrettyMIDI(initial_tempo=bpm)

    # Put beat 1 on a bar line, so the DAW's bars and beats line up with the groove
    shift = 0.0
    if not args.no_align and len(kicks) + len(snares) >= 4:
        kt, kv = zip(*kicks) if kicks else ((), ())
        st, sv = zip(*snares) if snares else ((), ())
        earliest = min(n.start for n in drums.notes)
        shift = bar_align_shift(np.array(kt), kv, np.array(st), sv, earliest, args.bpm)
        for n in drums.notes:
            n.start += shift
            n.end += shift
        print(f"  aligned: beat 1 moved to a bar line (all notes shifted {shift:+.3f}s)")

    if args.quantize:
        for n in drums.notes:
            n.start = float(quantize(n.start, args.bpm, args.quantize))
            n.end = n.start + note_len

    drums.notes.sort(key=lambda n: (n.start, n.pitch))
    midi.instruments.append(drums)
    midi.write(args.output)
    print(f"\nWrote {len(drums.notes)} notes to {args.output}")
    return {"bpm": args.bpm, "shift": float(shift), "notes": len(drums.notes)}


if __name__ == "__main__":
    main()
