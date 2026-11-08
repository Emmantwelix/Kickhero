"""A lesson: the notes to play (time, lane, velocity, open hi-hat or not) at a fixed tempo, in whole 4/4 bars."""

import math
import statistics
from dataclasses import dataclass, field, replace
from pathlib import Path

from ..lanes import NOTE_TO_LANE, OPEN_HAT_NOTES
from .difficulty import difficulty, difficulty_score, rate


ACCENT_MIN = 116      # velocity from which a note can be an accent...
ACCENT_LANE_MAX = 108  # ...if the lane's typical (median) note is no louder than this
GHOST_MAX = 64        # velocity up to which a note can be a ghost note...
GHOST_RATIO = 0.65    # ...if it's also well below the lane's loudest note
MERGE_S = 0.020       # hits on one drum closer than this are one hit (e.g. closed + open hi-hat together)


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

    def rating(self):
        """Difficulty level, E/M/H grade and what makes it hard (see engine/difficulty.py)."""
        return rate(self.notes, self.beat, self.bar)

    def difficulty_score(self):
        """Unrounded difficulty, for ranking (see engine/difficulty.py)."""
        return difficulty_score(self.notes, self.beat, self.bar)

    def difficulty(self):
        """1-10, from the hardest bars: hand and kick speed, limbs at once, fills, syncopation, ghost
        notes and open hi-hats (see engine/difficulty.py)."""
        return difficulty(self.notes, self.beat, self.bar)


def merge_hits(hits):
    """hits: (t, lane, velocity, open, *extra) tuples. On each drum, a hit within MERGE_S of the
    previous one is merged into it: the louder hit's time, velocity and extras, open if either was."""
    out, last = [], {}
    for h in sorted(hits, key=lambda h: h[0]):
        i = last.get(h[1])
        if i is not None and h[0] - out[i][0] < MERGE_S:
            loud = h if h[2] > out[i][2] else out[i]
            out[i] = (loud[0], loud[1], loud[2], bool(h[3] or out[i][3]), *loud[4:])
        else:
            last[h[1]] = len(out)
            out.append(tuple(h))
    return out


def from_notes(title, bpm, notes, bars=None, **kw):
    """Build a lesson from (t, lane, velocity[, open]) tuples; bars defaults to just enough to fit them,
    and with a backing track, to play the song to its end (it often goes on after the last drum note)."""
    notes = classify_dynamics(sorted((Note(float(n[0]), n[1], int(n[2]), open=bool(n[3:] and n[3]))
                                      for n in notes), key=lambda n: (n.t, n.lane)))
    bar = 240.0 / bpm
    if bars is None:
        last = notes[-1].t if notes else 0.0
        bars = max(1, math.floor(last / bar + 1e-6) + 1)
        end = backing_end(kw.get("backing"), kw.get("backing_offset", 0.0))
        if end:
            bars = max(bars, math.ceil(end / bar - 1e-3))
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

    hits = []
    for inst in instruments:
        for n in inst.notes:
            lane = NOTE_TO_LANE.get(n.pitch)
            if lane is not None:
                t = round(n.start / step) * step if step else n.start
                hits.append((t, lane, n.velocity, n.pitch in OPEN_HAT_NOTES))
    notes = merge_hits(hits)  # e.g. a closed + open hi-hat on the same hit

    meta = read_metadata(path)
    backing = path.parent / meta["backing"] if meta.get("backing") else None
    if title is None:
        title = meta.get("title") or path.stem.removesuffix("_drums")
    # The MIDI was shifted so beat 1 sits on bar 1; the song audio needs the opposite shift
    return from_notes(title, bpm, notes, source=path,
                      backing=backing if backing and backing.exists() else None,
                      backing_offset=-float(meta.get("shift") or 0.0))


def backing_end(backing, backing_offset):
    """Lesson time at which a backing track ends (None without one, or if it can't be read)."""
    if not backing:
        return None
    try:
        import soundfile as sf

        return sf.info(str(backing)).duration - backing_offset
    except Exception:
        return None


def read_metadata(midi_path):
    """The converter's sidecar <song>_drums.json (source song, tempo, alignment shift, backing track)."""
    import json

    try:
        return json.loads(Path(midi_path).with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
