"""Drum and metronome sounds, synthesized with numpy so the app ships no sample files."""

import numpy as np


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


def click(sr, accent):
    n = int(0.03 * sr)
    t = np.arange(n) / sr
    tone = np.sin(2 * np.pi * (1600 if accent else 1000) * t)
    return (tone * _env(n, sr, 0.006) * (0.9 if accent else 0.6)).astype(np.float32)


def drum(lane, sr):
    """One hit of the given lane at full velocity."""
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
    x = x / (np.max(np.abs(x)) + 1e-9) * 0.8
    return x.astype(np.float32)


class SoundBank:
    def __init__(self, sr):
        from ..lanes import LANES
        self.sr = sr
        self.clicks = {True: click(sr, True), False: click(sr, False)}
        self.drums = {lane: drum(lane, sr) for lane in LANES}
