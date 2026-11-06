"""Latency calibration: you hit a pad along with metronome clicks; the typical gap between each
click and your hit is the delay of the whole chain (audio out + your ears + kit + USB MIDI in).
It is subtracted from every hit afterwards so on-time playing scores as on time."""

import statistics

MIN_HITS = 8


def measure_latency(click_times, hit_times, max_gap=0.25):
    """Return (latency_seconds, spread_seconds, hits_used) or None if there weren't enough hits.

    Each hit is paired with the nearest click; pairs further apart than max_gap are ignored.
    Spread is the median absolute deviation: small (< 15 ms) means a reliable measurement.
    """
    if not click_times:
        return None
    gaps = []
    for h in hit_times:
        c = min(click_times, key=lambda c: abs(h - c))
        if abs(h - c) <= max_gap:
            gaps.append(h - c)
    if len(gaps) < MIN_HITS:
        return None
    latency = statistics.median(gaps)
    spread = statistics.median(abs(g - latency) for g in gaps)
    return latency, spread, len(gaps)
