"""A lesson: the notes to play (time, lane, velocity, open hi-hat or not) at a fixed tempo, in whole 4/4 bars."""

import math
import statistics
from dataclasses import dataclass, field, replace
from pathlib import Path

from ..lanes import NOTE_TO_LANE, OPEN_HAT_NOTES


ACCENT_MIN = 116      # velocity from which a note can be an accent...
ACCENT_LANE_MAX = 108  # ...if the lane's typical (median) note is no louder than this
GHOST_MAX = 64        # velocity up to which a note can be a ghost note...
GHOST_RATIO = 0.65    # ...if it's also well below the lane's loudest note


@dataclass(frozen=True)
class Note:
    t: float        # seconds from the start of bar 1, at 100% speed
    lane: str
    velocity: int = 100
    dyn: str = "normal"  # "accent", "normal" or "ghost": how hard to play it
    open: bool = False   # hi-hat only: an open hi-hat


def classify_dynamics(notes):
    """Mark accents and ghost notes. Relative to each lane, so a lane where every hit is loud
    (common in converted songs) has no accents, while a soft note under loud backbeats is a ghost."""
    by_lane = {}
    for n in notes:
        by_lane.setdefault(n.lane, []).append(n.velocity)
    stats = {lane: (statistics.median(v), max(v)) for lane, v in by_lane.items()}
    out = []
    for n in notes:
        median, loudest = stats[n.lane]
        if n.velocity >= ACCENT_MIN and median <= ACCENT_LANE_MAX:
            dyn = "accent"
        elif n.velocity <= GHOST_MAX and n.velocity <= GHOST_RATIO * loudest:
            dyn = "ghost"
        else:
            dyn = "normal"
        out.append(replace(n, dyn=dyn))
    return out


@dataclass
class Lesson:
    title: str
    bpm: float
    notes: list = field(default_factory=list)  # sorted by time
    bars: int = 1
    beats_per_bar: int = 4
    source: Path | None = None
    backing: Path | None = None    # drumless audio to play along with (see pipeline metadata)
    backing_offset: float = 0.0    # seconds to add to lesson time to get backing-audio time

    @property
    def beat(self):
        return 60.0 / self.bpm

    @property
    def bar(self):
        return self.beat * self.beats_per_bar

    @property
    def length(self):
        return self.bars * self.bar

    @property
    def lanes_used(self):
        return {n.lane for n in self.notes}

    @property
    def has_dynamics(self):
        return any(n.dyn != "normal" for n in self.notes)

    @property
    def has_open_hats(self):
        return any(n.open for n in self.notes)

    def difficulty(self):
        """Rough 1-10 score from note density and how many limbs play at once."""
        if not self.notes:
            return 1
        per_sec = len(self.notes) / self.length
        onsets = {}
        for n in self.notes:
            onsets.setdefault(round(n.t, 2), set()).add(n.lane)
        poly = sum(len(v) for v in onsets.values()) / len(onsets)
        return max(1, min(10, round(per_sec * 0.45 + (poly - 1) * 2.5)))


def from_notes(title, bpm, notes, bars=None, **kw):
    """Build a lesson from (t, lane, velocity[, open]) tuples; bars defaults to just enough to fit them."""
    notes = classify_dynamics(sorted((Note(float(n[0]), n[1], int(n[2]), open=bool(n[3:] and n[3]))
                                      for n in notes), key=lambda n: (n.t, n.lane)))
    bar = 240.0 / bpm
    if bars is None:
        last = notes[-1].t if notes else 0.0
        bars = max(1, math.floor(last / bar + 1e-6) + 1)
    return Lesson(title=title, bpm=bpm, notes=notes, bars=bars, **kw)


def load_midi(path, quantize=0, title=None):
    """Load a drum MIDI file (e.g. one made by the converter). quantize=16 snaps to 16th notes."""
    import pretty_midi

    path = Path(path)
    pm = pretty_midi.PrettyMIDI(str(path))
    tempi = pm.get_tempo_changes()[1]
    bpm = float(tempi[0]) if len(tempi) else 120.0
    instruments = [i for i in pm.instruments if i.is_drum] or pm.instruments
    step = 60.0 / bpm * 4 / quantize if quantize else 0

    best = {}  # (lane, time) -> (time, velocity, open); merges e.g. open + closed hi-hat on the same hit
    for inst in instruments:
        for n in inst.notes:
            lane = NOTE_TO_LANE.get(n.pitch)
            if lane is None:
                continue
            t = round(n.start / step) * step if step else n.start
            key = (lane, round(t / 0.02))  # notes on one lane within 20 ms are one hit
            prev = best.get(key, (t, 0, False))
            is_open = n.pitch in OPEN_HAT_NOTES or prev[2]
            best[key] = (t, n.velocity, is_open) if n.velocity > prev[1] else (prev[0], prev[1], is_open)
    notes = [(t, lane, v, is_open) for (lane, _), (t, v, is_open) in best.items()]

    meta = read_metadata(path)
    backing = path.parent / meta["backing"] if meta.get("backing") else None
    if title is None:
        title = meta.get("title") or path.stem.removesuffix("_drums")
    # The MIDI was shifted so beat 1 sits on bar 1; the song audio needs the opposite shift
    return from_notes(title, bpm, notes, source=path,
                      backing=backing if backing and backing.exists() else None,
                      backing_offset=-float(meta.get("shift") or 0.0))


def read_metadata(midi_path):
    """The converter's sidecar <song>_drums.json (source song, tempo, alignment shift, backing track)."""
    import json

    try:
        return json.loads(Path(midi_path).with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
