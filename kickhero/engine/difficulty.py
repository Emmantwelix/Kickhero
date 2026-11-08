"""How hard a drum part is to play, 1-10.

Each bar is rated on what makes drumming hard, then the song is rated mostly on its hardest bars,
so a long sparse intro doesn't make a song with a hard chorus look easy:

- hand speed: hand strokes per second in the bar, and the fastest burst of four strokes in a row
- kick speed: the fastest two kicks in a row (double kicks)
- limbs at once: how many drums are played together on average
- moving around: snare/tom changes that involve a tom (fills)
- syncopation: kicks and snares on the in-between sixteenths ("e" and "a")
- ghost notes and open hi-hats: extra control on top of the pattern
"""

import statistics
from dataclasses import dataclass

HANDS = {"crash", "hihat", "ride", "snare", "tom1", "tom2", "tom3"}
MOVERS = {"snare", "tom1", "tom2", "tom3"}
PEAK_SHARE = 0.2    # the song's hardest fifth of bars...
PEAK_WEIGHT = 0.65  # ...counts this much, its typical (median) bar the rest


def bar_features(notes, start, beat, bar):
    """What one bar asks of you. notes: the bar's notes; start: when the bar starts; beat, bar: lengths (s)."""
    moments = {}
    for n in notes:
        moments.setdefault(round(n.t, 3), []).append(n)
    times = sorted(moments)
    hand_times = [t for t in times for n in moments[t] if n.lane in HANDS]
    burst = max((3 / (b - a) for a, b in zip(hand_times, hand_times[3:]) if b - a > 0.01), default=0.0)
    kicks = [t for t in times if any(n.lane == "kick" for n in moments[t])]
    kick_gaps = [b - a for a, b in zip(kicks, kicks[1:]) if b - a > 0.02]
    movers = [n.lane for t in times for n in moments[t] if n.lane in MOVERS]
    sixteenth = beat / 4
    return {
        "hands": len(hand_times) / bar,
        "burst": burst,
        "kick": 1 / min(kick_gaps) if kick_gaps else 0.0,
        "limbs": statistics.mean(len({n.lane for n in moments[t]}) for t in times),
        "moves": sum(1 for a, b in zip(movers, movers[1:]) if a != b and "tom" in a + b),
        "sync": sum(1 for t in times if round((t - start) / sixteenth) % 2 == 1
                    and any(n.lane in ("kick", "snare") and n.dyn != "ghost" for n in moments[t])),
        "ghosts": sum(1 for n in notes if n.dyn == "ghost"),
        "opens": sum(1 for n in notes if n.open),
    }


WEIGHTS = {  # factor: (points per unit, most units counted)
    "hands": (0.30, None), "burst": (0.10, 20), "kick": (0.35, 10), "limbs": (1.5, None),
    "moves": (0.25, 10), "sync": (0.15, 8), "ghosts": (0.10, 12), "opens": (0.25, 4),
}

# Why a song is hard, in words: factor -> (shown when the hardest bars average at least this, text)
REASONS = {
    "burst": (10, "Fast runs and fills"),
    "hands": (6, "Busy hands"),
    "kick": (5, "Quick double kicks"),
    "limbs": (1.6, "Hands and feet together"),
    "moves": (3, "Fills around the toms"),
    "sync": (3, "Off-beat kick and snare"),
    "ghosts": (4, "Ghost notes"),
    "opens": (1, "Open hi-hats"),
}

GRADES = [(3, "E", "Easy"), (6, "M", "Medium"), (10, "H", "Hard")]  # highest 1-10 level for each grade


def points(f):
    """How much each factor adds to a bar's score."""
    out = {}
    for key, (weight, cap) in WEIGHTS.items():
        value = f[key] - 1 if key == "limbs" else f[key]
        out[key] = weight * (min(value, cap) if cap else value)
    return out


def bar_score(f):
    return sum(points(f).values())


@dataclass(frozen=True)
class Rating:
    score: float     # unrounded, about 0-10, for ranking
    level: int       # 1-10
    reasons: tuple   # what makes it hard, biggest first (at most 3)
    hardest: float   # when its hardest bar starts (s), or 0

    @property
    def grade(self):
        """"E", "M" or "H"."""
        return grade(self.level)[0]

    @property
    def grade_name(self):
        return grade(self.level)[1]


def grade(level):
    """(letter, name) for a 1-10 level."""
    return next((letter, name) for top, letter, name in GRADES if level <= top)


def rate(notes, beat, bar):
    """Rating of notes (sorted Note objects) at `beat`/`bar` seconds."""
    bars = {}
    for n in notes:
        bars.setdefault(int(n.t // bar), []).append(n)
    if not bars:
        return Rating(0.0, 1, (), 0.0)
    rated = sorted(((bar_score(f), i, f) for i, ns in bars.items() for f in [bar_features(ns, i * bar, beat, bar)]),
                   key=lambda r: (r[0], -r[1]))
    top = rated[-max(1, round(len(rated) * PEAK_SHARE)):]
    peak = statistics.mean(r[0] for r in top)
    score = PEAK_WEIGHT * peak + (1 - PEAK_WEIGHT) * statistics.median(r[0] for r in rated)
    level = max(1, min(10, round(1 + 0.75 * score)))
    feats = {k: statistics.mean(r[2][k] for r in top) for k in WEIGHTS}
    pts = points(feats)
    shown = [k for k, (least, _) in REASONS.items() if feats[k] >= least]
    if "burst" in shown and "hands" in shown:
        shown.remove("hands")
    reasons = tuple(REASONS[k][1] for k in sorted(shown, key=lambda k: -pts[k])[:3])
    return Rating(score, level, reasons, rated[-1][1] * bar)


def difficulty_score(notes, beat, bar):
    """Unrounded difficulty (about 0-10), for ranking."""
    return rate(notes, beat, bar).score


def difficulty(notes, beat, bar):
    """1-10."""
    return rate(notes, beat, bar).level
