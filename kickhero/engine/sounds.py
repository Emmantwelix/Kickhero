"""Drum and metronome sounds.

Built-in kits are synthesized with numpy, so Kickhero ships no sample files (and no sample licences).
Users can also load their own samples: those files stay on their computer and are only read from there.
"""

import re
from pathlib import Path

import numpy as np

from ..lanes import OPEN_HAT, SOUNDS

KITS = {"classic": "Classic", "808": "808", "tight": "Tight"}
CUSTOM = "custom"
SAMPLE_EXTS = {".wav", ".flac", ".ogg", ".aif", ".aiff", ".mp3"}


def _env(n, sr, decay):
    return np.exp(-np.arange(n) / (decay * sr))


def _noise(n, seed):
    return np.random.default_rng(seed).uniform(-1, 1, n)


def _highpass(x, amount):
    """Crude high-pass: subtract a moving average. amount 0..1, higher = keeps more low end."""
    k = max(2, int(round(1 / (1 - amount))))
    return x - np.convolve(x, np.ones(k) / k, mode="same")


def _sweep(n, sr, f0, f1, decay):
    t = np.arange(n) / sr
    freq = f1 + (f0 - f1) * np.exp(-t / decay)
    return np.sin(2 * np.pi * np.cumsum(freq) / sr)


def _metal(n, sr, freqs):
    """Metallic tone: square waves at inharmonic frequencies (the classic analog cymbal trick)."""
    t = np.arange(n) / sr
    return sum(np.sign(np.sin(2 * np.pi * f * t)) for f in freqs) / len(freqs)


def click(sr, accent):
    """A bright tick (tone plus octave, a short noise transient, longer ring) so it cuts through a song."""
    n = int(0.06 * sr)
    t = np.arange(n) / sr
    f = 1600 if accent else 1000
    x = (np.sin(2 * np.pi * f * t) + 0.4 * np.sin(2 * np.pi * 2 * f * t)) / 1.2
    k = int(0.0015 * sr)
    x[:k] += 0.3 * _highpass(_noise(k, 7), 0.5)
    x = x * _env(n, sr, 0.015) * (1.0 if accent else 0.75)
    return np.clip(x, -1, 1).astype(np.float32)


def _classic(lane, sr):
    if lane == "kick":
        n = int(0.35 * sr)
        x = _sweep(n, sr, 160, 48, 0.03) * _env(n, sr, 0.12)
        x[: int(0.002 * sr)] += _noise(int(0.002 * sr), 1) * 0.5
    elif lane == "snare":
        n = int(0.25 * sr)
        x = 0.55 * _sweep(n, sr, 260, 180, 0.02) * _env(n, sr, 0.05)
        x += 0.6 * _highpass(_noise(n, 2), 0.7) * _env(n, sr, 0.07)
    elif lane == "hihat":
        n = int(0.09 * sr)
        x = _highpass(_noise(n, 3), 0.97) * _env(n, sr, 0.02)
    elif lane == OPEN_HAT:
        n = int(0.6 * sr)
        x = _highpass(_noise(n, 7), 0.97) * _env(n, sr, 0.16)
    elif lane == "ride":
        n = int(0.8 * sr)
        t = np.arange(n) / sr
        bell = sum(np.sin(2 * np.pi * f * t) for f in (3200, 4570, 5980)) / 3
        x = (0.5 * _highpass(_noise(n, 4), 0.95) + 0.25 * bell) * _env(n, sr, 0.25)
    elif lane == "crash":
        n = int(1.4 * sr)
        x = _highpass(_noise(n, 5), 0.93) * _env(n, sr, 0.45)
    else:  # toms
        f = {"tom1": 220, "tom2": 165, "tom3": 115}.get(lane, 160)
        n = int(0.4 * sr)
        x = _sweep(n, sr, f * 1.6, f, 0.04) * _env(n, sr, 0.14)
        x += 0.1 * _noise(n, 6) * _env(n, sr, 0.01)
    return x


def _808(lane, sr):
    """Drum-machine style: long booming kick, snappy snare, metallic hats and cymbals."""
    metal = (205.3, 304.4, 369.6, 522.7, 540.0, 800.0)
    if lane == "kick":
        n = int(0.9 * sr)
        x = _sweep(n, sr, 110, 46, 0.05) * _env(n, sr, 0.35)
        x = np.tanh(1.6 * x)
    elif lane == "snare":
        n = int(0.3 * sr)
        t = np.arange(n) / sr
        body = (np.sin(2 * np.pi * 180 * t) + 0.6 * np.sin(2 * np.pi * 330 * t)) * _env(n, sr, 0.04)
        x = 0.5 * body + 0.7 * _highpass(_noise(n, 12), 0.8) * _env(n, sr, 0.09)
    elif lane == "hihat":
        n = int(0.07 * sr)
        x = _highpass(_metal(n, sr, metal) + 0.4 * _noise(n, 13), 0.96) * _env(n, sr, 0.015)
    elif lane == OPEN_HAT:
        n = int(0.5 * sr)
        x = _highpass(_metal(n, sr, metal) + 0.4 * _noise(n, 15), 0.96) * _env(n, sr, 0.12)
    elif lane == "ride":
        n = int(0.9 * sr)
        x = _highpass(_metal(n, sr, [f * 1.5 for f in metal]), 0.95) * _env(n, sr, 0.3)
    elif lane == "crash":
        n = int(1.6 * sr)
        x = _highpass(_metal(n, sr, metal) + 0.8 * _noise(n, 14), 0.94) * _env(n, sr, 0.5)
    else:  # toms: pure pitched sweeps
        f = {"tom1": 260, "tom2": 190, "tom3": 130}.get(lane, 190)
        n = int(0.55 * sr)
        x = _sweep(n, sr, f * 1.3, f, 0.06) * _env(n, sr, 0.2)
    return x


def _tight(lane, sr):
    """Dry, short, closer to a damped acoustic kit."""
    if lane == "kick":
        n = int(0.22 * sr)
        x = _sweep(n, sr, 200, 58, 0.015) * _env(n, sr, 0.06)
        k = int(0.004 * sr)
        x[:k] += _highpass(_noise(k, 21), 0.6) * 0.8  # beater click
    elif lane == "snare":
        n = int(0.2 * sr)
        x = 0.4 * _sweep(n, sr, 300, 200, 0.01) * _env(n, sr, 0.03)
        x += 0.8 * _highpass(_noise(n, 22), 0.85) * _env(n, sr, 0.045)
    elif lane == "hihat":
        n = int(0.05 * sr)
        x = _highpass(_noise(n, 23), 0.99) * _env(n, sr, 0.01)
    elif lane == OPEN_HAT:
        n = int(0.4 * sr)
        x = _highpass(_noise(n, 27), 0.99) * _env(n, sr, 0.09)
    elif lane == "ride":
        n = int(0.6 * sr)
        t = np.arange(n) / sr
        ping = sum(np.sin(2 * np.pi * f * t) for f in (2800, 4100, 6200)) / 3
        x = (0.35 * _highpass(_noise(n, 24), 0.97) + 0.45 * ping) * _env(n, sr, 0.18)
    elif lane == "crash":
        n = int(1.1 * sr)
        x = _highpass(_noise(n, 25), 0.96) * _env(n, sr, 0.3)
    else:
        f = {"tom1": 200, "tom2": 150, "tom3": 100}.get(lane, 150)
        n = int(0.3 * sr)
        x = _sweep(n, sr, f * 1.8, f, 0.02) * _env(n, sr, 0.09)
        x += 0.25 * _highpass(_noise(n, 26), 0.7) * _env(n, sr, 0.008)
    return x


_KIT_FUNCS = {"classic": _classic, "808": _808, "tight": _tight}


def _finish(x):
    return (x / (np.max(np.abs(x)) + 1e-9) * 0.8).astype(np.float32)


def drum(lane, sr, kit="classic"):
    """One hit of the given lane (or OPEN_HAT) at full velocity, from a built-in kit."""
    return _finish(_KIT_FUNCS.get(kit, _classic)(lane, sr))


def read_audio(path, seconds=None):
    """(samples [n, channels] float32, sample rate). Also reads WAVs that wrap Ogg Vorbis data
    (format tag 0x674F, used by some sample libraries), which libsndfile rejects as malformed."""
    import io

    import soundfile as sf

    try:
        with sf.SoundFile(str(path)) as f:
            frames = int(seconds * f.samplerate) if seconds else -1
            return f.read(frames, dtype="float32", always_2d=True), f.samplerate
    except sf.LibsndfileError:
        data = Path(path).read_bytes()
        start = data.find(b"OggS")
        if start < 0:
            raise
        y, sr = sf.read(io.BytesIO(data[start:]), dtype="float32", always_2d=True)
        return (y[: int(seconds * sr)] if seconds else y), sr


def load_sample(path, sr, max_seconds=3.0):
    """A user sample as mono float32 at sr: leading silence trimmed, peak-normalised, faded out."""
    y, file_sr = read_audio(path)
    y = y.mean(axis=1)
    if file_sr != sr:
        import soxr

        y = soxr.resample(y, file_sr, sr).astype(np.float32)
    loud = np.nonzero(np.abs(y) > 0.02 * (np.max(np.abs(y)) + 1e-9))[0]
    if len(loud):
        y = y[max(0, loud[0] - int(0.001 * sr)):]
    y = y[: int(max_seconds * sr)]
    fade = min(len(y), int(0.02 * sr))
    if fade:
        y[-fade:] *= np.linspace(1, 0, fade)
    return _finish(y)


# File/folder name keywords per lane (checked in order). Toms are sorted high -> floor separately.
LANE_KEYWORDS = [
    ("kick", r"kick|\bbd\b|bass ?drum|\bkik\b"),
    ("snare", r"snare|\bsd\b|\bsnr\b|rim"),
    ("hihat", r"hi[ _-]?hat|\bhh\b|\bhat"),
    ("ride", r"ride"),
    ("crash", r"crash|cymbal|splash|china"),
    ("tom", r"tom"),
]


def lane_for_name(name):
    text = name.lower().replace("_", " ")
    for lane, pattern in LANE_KEYWORDS:
        if re.search(pattern, text):
            return lane
    return None


# Variations to skip when a plain version of the drum exists (an open hi-hat is not a hi-hat "hit")
AVOID = {
    "hihat": r"open|\boh\b|half|pedal|foot|chick",
    "snare": r"rim|side|stick|ghost|flam|roll|drag",
    "crash": r"splash|china|choke",
    "kick": r"sub|808 ?long",
}
OPEN_WORDS = r"open|\boh\b"  # an open hi-hat sample
_LAYER = re.compile(r"#\s*\d+|\bv\d+\b|\brr\d+\b|\bvel\w*\s*\d+|\(\d+\)")


def _family(path):
    """Sample name without velocity-layer / round-robin markers: 'Tom 2 Funk #5' -> 'tom 2 funk'."""
    return re.sub(r"\s+", " ", _LAYER.sub("", path.stem.lower().replace("_", " "))).strip()


def _attack_level(path):
    """RMS of the first 150 ms: picks the hardest-hit velocity layer whatever the file naming."""
    try:
        y, _ = read_audio(path, seconds=0.15)
        return float(np.sqrt(np.mean(y ** 2))) if len(y) else 0.0
    except Exception:
        return -1.0


def match_kit_folder(folder):
    """Pick one sample per lane from a folder of drum samples (searched recursively), by file and
    folder names. Skips variations (open hi-hat, rim shots...) when a plain sample exists, and
    within a drum takes the loudest velocity layer. An open hi-hat sample becomes the OPEN_HAT
    sound. Returns {lane or OPEN_HAT: path}."""
    folder = Path(folder)
    groups = {}
    for f in sorted(p for p in folder.rglob("*") if p.suffix.lower() in SAMPLE_EXTS):
        lane = lane_for_name(f.stem) or lane_for_name(str(f.relative_to(folder)))
        if lane:
            groups.setdefault(lane, []).append(f)

    found = {}
    for lane, files in groups.items():
        if lane == "tom":
            continue
        plain = [f for f in files if not re.search(AVOID.get(lane, r"$^"), _family(f))]
        files = plain or files
        first_family = _family(files[0])  # e.g. "kick 1" rather than mixing kick 1 and kick 2
        same = [f for f in files if _family(f) == first_family]
        found[lane] = max(same, key=_attack_level)

    opens = [f for f in groups.get("hihat", []) if re.search(OPEN_WORDS, _family(f))]
    if opens:
        same = [f for f in opens if _family(f) == _family(opens[0])]
        found[OPEN_HAT] = max(same, key=_attack_level)

    toms = groups.get("tom", [])
    if toms:
        families = {}
        for f in toms:
            families.setdefault(_family(f), []).append(f)

        def height(name):
            """Sort key, high toms first: named high/floor, else drum size (smaller = higher),
            else tom number."""
            if re.search(r"floor|low|\blo\b|big", name):
                return (2, 0, name)
            if re.search(r"high|\bhi\b|small|rack", name):
                return (0, 0, name)
            size = re.search(r"(\d+)\s*(?:in\b|inch|\")", name)
            number = re.search(r"tom\s*(\d+)", name)
            return (1, int(size.group(1)) if size else int(number.group(1)) if number else 99, name)

        order = sorted(families, key=height)
        picks = [order[0], order[len(order) // 2], order[-1]]
        for lane, fam in zip(("tom1", "tom2", "tom3"), picks):
            found[lane] = max(families[fam], key=_attack_level)
    return found


class SoundBank:
    def __init__(self, sr, kit="classic", custom=None):
        """kit: a built-in kit name, or CUSTOM to use `custom` = {lane: sample path}
        (lanes without a usable sample fall back to the Classic kit)."""
        self.sr = sr
        self.kit = kit
        self.clicks = {True: click(sr, True), False: click(sr, False)}
        self.errors = {}
        base = "classic" if kit == CUSTOM else kit
        self.drums = {sound: drum(sound, sr, base) for sound in SOUNDS}
        if kit == CUSTOM:
            for lane, path in (custom or {}).items():
                if lane in self.drums and path:
                    try:
                        self.drums[lane] = load_sample(path, sr)
                    except Exception as e:  # missing/unreadable file: keep the built-in sound
                        self.errors[lane] = str(e)
