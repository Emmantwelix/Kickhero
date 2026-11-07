#!/usr/bin/env python3
"""
song2drums.py — fully hands-off: song(s) in, drum MIDI out.

    python song2drums.py song.mp3
    python song2drums.py ~/Music/to_transcribe/            # every song in a folder
    python song2drums.py ~/Music/to_transcribe/ --watch    # keep watching for new songs

For each song it:
  1. pulls the drum stem out of the mix          (Demucs htdemucs_ft)
  2. splits the drums into kick/snare/toms/hh/ride/crash   (MDX23C DrumSep)
  3. detects the tempo (unless you give --bpm)
  4. writes <song>_drums.mid via drums2midi.py

With --midi FILE (one song), steps 2-4 are replaced by lining that MIDI file's drum part up with
the song (see midi_import.py): a hand-made drum part, played along with the real track.

Output goes to drum_midi/<song name>/ by default. Songs that already have a MIDI file
are skipped, so re-running on a folder only processes new songs (use --force to redo).
Models download once (~1 GB total) to ~/.cache/audio-separator-models.

Part of the kickhero package; drums2midi.py sits next to it.
"""

import argparse
import datetime
import json
import re
import shutil
import time
from pathlib import Path

import numpy as np


DRUMS_MODEL = "htdemucs_ft.yaml"
KIT_MODEL = "MDX23C-DrumSep-aufr33-jarredou.ckpt"
SONG_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".aiff", ".aif", ".opus", ".wma"}
DEFAULT_MODEL_DIR = Path.home() / ".cache" / "audio-separator-models"


def resolve(path, output_dir):
    p = Path(path)
    return p if p.is_absolute() or p.exists() else Path(output_dir) / p


def write_backing(stems, path):
    """Mix the non-drum stems (bass, vocals, other) into one play-along track."""
    import soundfile as sf

    mix, sr = None, None
    for f in stems:
        y, sr = sf.read(str(f), dtype="float32", always_2d=True)
        mix = y if mix is None else mix[: len(y)] + y[: len(mix)]
    if mix is None:
        return False
    mix /= max(float(np.max(np.abs(mix))), 1.0)
    # libsndfile's Vorbis encoder crashes the whole process on large single writes: write in blocks
    with sf.SoundFile(str(path), "w", sr, mix.shape[1], format="OGG", subtype="VORBIS",
                      compression_level=0.1) as f:  # 0 = best quality; default (~0.4) is noticeably lossy
        for i in range(0, len(mix), 16384):
            f.write(mix[i:i + 16384])
    return True


def write_metadata(path, **info):
    """Sidecar <song>_drums.json: what the practice app needs to play the song along with the MIDI."""
    info["created"] = datetime.datetime.now().isoformat(timespec="seconds")
    Path(path).write_text(json.dumps(info, indent=2), encoding="utf-8")


def stem_name(path):
    """Separator outputs end in a bracketed stem tag, e.g. 'song_(Drums)_htdemucs_ft.wav' -> 'drums'."""
    tags = re.findall(r"\(([^)]+)\)", Path(path).stem)
    return tags[-1].lower() if tags else ""


def separate(model, audio_path, out_dir, model_dir, single_stem=None):
    from audio_separator.separator import Separator

    sep = Separator(
        output_dir=str(out_dir),
        model_file_dir=str(model_dir),
        output_format="WAV",
        output_single_stem=single_stem,
        log_level=30,  # warnings only
    )
    sep.load_model(model_filename=model)
    return [resolve(f, out_dir) for f in sep.separate(str(audio_path))]


def detect_bpm(wav_path):
    """Tempo from the bar length: drum patterns repeat every bar, and that repeat is a much
    stronger, less ambiguous peak than the beat itself. Assumes 4/4 at 75-160 BPM (a bar of
    1.5-3.2 s); falls back to librosa's beat tracker if no bar-length repeat is found."""
    import librosa

    y, sr = librosa.load(str(wav_path), sr=22050, mono=True, duration=120)
    hop = 256
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    fps = sr / hop
    ac = librosa.autocorrelate(env - env.mean())
    ac /= ac[0]
    lo, hi = int(1.5 * fps), min(int(3.2 * fps), len(ac) - 2)
    peaks = [i for i in range(lo, hi + 1) if ac[i] >= ac[i - 1] and ac[i] >= ac[i + 1] and ac[i] > 0.2]
    if not peaks:
        tempo, _ = librosa.beat.beat_track(onset_envelope=env, sr=sr, hop_length=hop)
        return float(np.atleast_1d(tempo)[0])
    i = max(peaks, key=lambda k: ac[k])
    a, b, c = ac[i - 1], ac[i], ac[i + 1]
    shift = 0.5 * (a - c) / (a - 2 * b + c) if a - 2 * b + c else 0.0  # parabolic sub-frame peak
    return 4 * 60 / ((i + shift) / fps)


def process_song(song, args):
    name = getattr(args, "name", None) or song.stem
    song_dir = Path(args.output) / name
    midi_path = song_dir / f"{name}_drums.mid"
    if midi_path.exists() and not args.force:
        print(f"\n= {name}: already done, skipping ({midi_path})")
        return
    print(f"\n=== {name} ===")
    work = song_dir / "work"
    kit_dir = song_dir / "kit"
    for d in (work, kit_dir):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)

    t0 = time.time()
    steps = 2 if args.midi else 4
    print(f"[1/{steps}] Extracting drums from the mix...")
    outs = separate(DRUMS_MODEL, song, work, args.model_dir)
    drum_files = [f for f in outs if stem_name(f) == "drums"]
    if not drum_files:
        raise RuntimeError(f"Drum stem not produced; separator returned {outs}")
    drums_wav = song_dir / "drums.wav"
    shutil.move(str(drum_files[0]), drums_wav)  # fixed name, so the song title never confuses step 4
    backing = song_dir / "backing.ogg"
    has_backing = write_backing([f for f in outs if f not in drum_files], backing)

    if args.midi:
        from .midi_import import import_aligned

        print("[2/2] Lining up the MIDI file with the song...")
        _, (rate, off) = import_aligned(args.midi, drums_wav, song_dir, name, backing=backing.name if has_backing else None,
                                 source=str(Path(song).resolve()))
        print(f"{rate:.0%} of the MIDI's kick and snare notes line up with drums heard in the song "
              f"({off:.0%} a beat off)")
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(kit_dir, ignore_errors=True)
        if not args.keep_stems:
            drums_wav.unlink(missing_ok=True)
        print(f"Done in {time.time() - t0:.0f}s -> {midi_path}")
        return

    print("[2/4] Splitting the kit (kick, snare, toms, hh, ride, crash)...")
    separate(KIT_MODEL, drums_wav, kit_dir, args.model_dir)

    if args.bpm:
        bpm = args.bpm
        print(f"[3/4] Using tempo {bpm:g} BPM")
    else:
        bpm = detect_bpm(drums_wav)
        print(f"[3/4] Estimated tempo ~ {bpm:.1f} BPM (if the final tempo is wrong, set it yourself)")

    print("[4/4] Writing MIDI...")
    d2m_args = [str(kit_dir), "-o", str(midi_path), "--bpm", f"{bpm:.3f}", "--ref", str(drums_wav),
                "--ref-gate", str(args.ref_gate), "--bleed-db", str(args.bleed_db),
                "--sensitivity", str(args.sensitivity), "--gate", str(args.gate),
                "--min-gap", str(args.min_gap), "--hihat-open-ms", str(args.hihat_open_ms)]
    if args.quantize:
        d2m_args += ["--quantize", str(args.quantize)]
    if not args.bpm:
        d2m_args.append("--fit-tempo")
    if args.no_align:
        d2m_args.append("--no-align")
    if not args.no_split_toms:
        d2m_args.append("--split-toms")
    from . import drums2midi  # imported here so loading this module (e.g. from the GUI) stays fast

    result = drums2midi.main(d2m_args)
    write_metadata(
        midi_path.with_suffix(".json"), title=name, source=str(Path(song).resolve()),
        bpm=result["bpm"], shift=result["shift"], backing=backing.name if has_backing else None,
        settings={k: v for k, v in vars(args).items() if k not in ("inputs", "output", "model_dir", "watch")},
    )

    shutil.rmtree(work, ignore_errors=True)
    if not args.keep_stems:
        shutil.rmtree(kit_dir, ignore_errors=True)
        drums_wav.unlink(missing_ok=True)
    print(f"Done in {time.time() - t0:.0f}s -> {midi_path}")


def find_songs(inputs, output_root):
    out_root = Path(output_root).resolve()
    songs = []
    for item in inputs:
        p = Path(item).expanduser()
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.suffix.lower() in SONG_EXTS and out_root not in f.resolve().parents:
                    songs.append(f)
        elif p.is_file():
            songs.append(p)
        else:
            print(f"Not found: {item}")
    return songs


def is_done(song, args):
    return (Path(args.output) / song.stem / f"{song.stem}_drums.mid").exists() and not args.force


def run_all(args, quiet=False):
    songs = find_songs(args.inputs, args.output)
    todo = [s for s in songs if not is_done(s, args)]
    # In watch mode, leave files alone until they've stopped changing (still copying/downloading)
    todo = [s for s in todo if time.time() - s.stat().st_mtime > 15 or not quiet]
    if not quiet:
        print(f"{len(songs)} song(s) found, {len(songs) - len(todo)} already done, {len(todo)} to process")
    failed = []
    for song in todo:
        try:
            process_song(song, args)
        except Exception as e:  # keep going with the rest of a batch
            print(f"!! {song.name} failed: {e}")
            failed.append(song.name)
    if failed:
        print(f"\n{len(failed)} song(s) failed: {', '.join(failed)}")
    return songs


def build_parser():
    p = argparse.ArgumentParser(description="Song(s) in, drum MIDI out. Fully automatic.")
    p.add_argument("inputs", nargs="+", help="Song files and/or folders of songs")
    p.add_argument("-o", "--output", default="drum_midi", help="Output folder (default: drum_midi)")
    p.add_argument("--bpm", type=float, help="Tempo for the MIDI file. Default: auto-detect")
    p.add_argument("--quantize", type=int, default=0, metavar="GRID", help="Snap to grid, e.g. 16. Default: off")
    p.add_argument("--keep-stems", action="store_true", help="Keep drums.wav and the kit stems")
    p.add_argument("--force", action="store_true", help="Redo songs that already have a MIDI file")
    p.add_argument("--watch", action="store_true", help="Keep running and process new songs as they appear")
    p.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR), help="Where models are cached")
    p.add_argument("--midi", help="A ready-made MIDI file of the song: line its drum part up with the song "
                                  "instead of transcribing the drums (one song only)")
    p.add_argument("--name", help="Song name (and folder) to use instead of the file name (one song only)")
    # Pass-through tuning for drums2midi
    p.add_argument("--sensitivity", type=float, default=0.07)
    p.add_argument("--gate", type=float, default=-30.0)
    p.add_argument("--min-gap", type=float, default=30.0)
    p.add_argument("--ref-gate", type=float, default=-36.0,
                   help="Ignore hits more than this many dB below the drum stem's peak (default -36)")
    p.add_argument("--bleed-db", type=float, default=10.0,
                   help="Drop tom hits this many dB quieter than a nearby kick/snare hit, 0 = off (default 10)")
    p.add_argument("--hihat-open-ms", type=float, default=150.0, help="Open hi-hat threshold, 0 = off (default 150)")
    p.add_argument("--no-align", action="store_true",
                   help="Keep the song's original timing instead of moving beat 1 onto a bar line")
    p.add_argument("--no-split-toms", action="store_true", help="Put all toms on one note instead of floor/mid/high")
    return p


def main():
    args = build_parser().parse_args()
    if (args.midi or args.name) and (len(args.inputs) != 1 or not Path(args.inputs[0]).is_file()):
        raise SystemExit("--midi and --name go with exactly one song file")

    Path(args.model_dir).mkdir(parents=True, exist_ok=True)
    run_all(args)
    if args.watch:
        print("\nWatching for new songs (Ctrl+C to stop)...")
        try:
            while True:
                time.sleep(30)
                run_all(args, quiet=True)  # finished songs are skipped automatically
        except KeyboardInterrupt:
            print("Stopped.")


if __name__ == "__main__":
    main()
