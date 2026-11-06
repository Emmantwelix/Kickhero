"""A lesson: the notes to play (time, lane, velocity) at a fixed tempo, in whole 4/4 bars."""

import math
from dataclasses import dataclass, field
from pathlib import Path

from ..lanes import NOTE_TO_LANE


@dataclass(frozen=True)
class Note:
    t: float        # seconds from the start of bar 1, at 100% speed
    lane: str
    velocity: int = 100


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
    """Build a lesson from (t, lane, velocity) tuples; bars defaults to just enough to fit them."""
    notes = sorted((Note(float(t), lane, int(v)) for t, lane, v in notes), key=lambda n: (n.t, n.lane))
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

    best = {}  # (lane, time) -> velocity; merges e.g. open + closed hi-hat on the same hit
    for inst in instruments:
        for n in inst.notes:
            lane = NOTE_TO_LANE.get(n.pitch)
            if lane is None:
                continue
            t = round(n.start / step) * step if step else n.start
            key = (lane, round(t / 0.02))  # notes on one lane within 20 ms are one hit
            if n.velocity > best.get(key, (0, 0))[1]:
                best[key] = (t, n.velocity)
    notes = [(t, lane, v) for (lane, _), (t, v) in best.items()]

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
