"""Editing a song's drum part: the notes of a converted MIDI file, with undo, saved back in place.

Pure logic (no Qt), used by the editor page. Times are seconds from the start of bar 1, as in
engine.lesson. The song audio stays where it is: tempo changes keep note times (only the bar
grid moves), and moving the whole part also moves the backing-track alignment (`shift`).
"""

import datetime
import json
import math
import shutil
from dataclasses import dataclass, replace
from pathlib import Path

from ..lanes import LANE_TO_NOTE, LANES, NOTE_TO_LANE, OPEN_HAT_NOTES
from .lesson import MERGE_S, from_notes, merge_hits, read_metadata

VELOCITY = {"accent": 124, "normal": 100, "ghost": 45}  # same as the course's X / x / g
NOTE_LEN = 0.05      # MIDI note length, as written by the converter
SAME_HIT = MERGE_S   # notes on one drum closer than this are one hit (as practice merges them)
OPEN_PITCH = 46
UNDO_LIMIT = 200


@dataclass(frozen=True)
class EditNote:
    t: float
    lane: str
    velocity: int = VELOCITY["normal"]
    open: bool = False
    pitch: int | None = None  # the MIDI note it was loaded from (kept on save), None = lane default

    def midi_pitch(self):
        if self.lane == "hihat" and self.open:
            return self.pitch if self.pitch in OPEN_HAT_NOTES else OPEN_PITCH
        if self.pitch is not None and NOTE_TO_LANE.get(self.pitch) == self.lane \
                and not (self.lane == "hihat" and self.pitch in OPEN_HAT_NOTES):
            return self.pitch
        return LANE_TO_NOTE[self.lane]


def backup_path(midi_path):
    """Where the converted original is kept: <song>_drums.original.mid (+ .json)."""
    p = Path(midi_path)
    return p.with_name(p.stem + ".original.mid")


def is_backup(path):
    return Path(path).name.endswith(".original.mid")


class Part:
    def __init__(self, path, notes, bpm, shift=0.0, title="", backing=None):
        self.path = Path(path)
        self.notes = sorted(notes, key=lambda n: (n.t, LANES.index(n.lane)))
        self.bpm = float(bpm)
        self.shift = float(shift)
        self.title = title
        self.backing = backing
        self.dirty = False
        self._undo, self._redo = [], []
        self.clipboard = None  # (bar count, [notes relative to the first copied bar])

    # ---------- grid ----------

    @property
    def beat(self):
        return 60.0 / self.bpm

    @property
    def bar(self):
        return 4 * self.beat

    @property
    def bars(self):
        """Bars with notes in them (at least 1)."""
        last = max((n.t for n in self.notes), default=0.0)
        return max(1, math.floor(last / self.bar + 1e-6) + 1)

    def snap(self, t, grid):
        """Round t to the nearest 1/grid note (grid 16 = sixteenths; 0 = no snapping)."""
        if not grid:
            return t
        step = self.bar / grid
        return round(t / step) * step

    @property
    def backing_offset(self):
        return -self.shift

    # ---------- undo ----------

    def _push(self):
        self._undo.append((list(self.notes), self.bpm, self.shift))
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()
        self.dirty = True

    def _set(self, notes):
        self.notes = sorted(notes, key=lambda n: (n.t, LANES.index(n.lane)))

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo(self):
        if self._undo:
            self._redo.append((list(self.notes), self.bpm, self.shift))
            notes, self.bpm, self.shift = self._undo.pop()
            self._set(notes)
            self.dirty = True

    def redo(self):
        if self._redo:
            self._undo.append((list(self.notes), self.bpm, self.shift))
            notes, self.bpm, self.shift = self._redo.pop()
            self._set(notes)
            self.dirty = True

    # ---------- note edits (each returns the new versions of the notes it touched) ----------

    def note_at(self, t, lane, tolerance):
        """The note on `lane` nearest to t within tolerance seconds, or None."""
        near = [n for n in self.notes if n.lane == lane and abs(n.t - t) <= tolerance]
        return min(near, key=lambda n: abs(n.t - t)) if near else None

    def add(self, t, lane, velocity=VELOCITY["normal"], open_=False):
        if t < 0 or self.note_at(t, lane, SAME_HIT):
            return None
        self._push()
        note = EditNote(t, lane, velocity, open_ and lane == "hihat")
        self._set(self.notes + [note])
        return note

    def remove(self, notes):
        gone = set(notes)
        if not gone:
            return []
        self._push()
        self._set([n for n in self.notes if n not in gone])
        return []

    def _replace(self, notes, change):
        """Swap each of `notes` for change(note) (None drops it), merging hits that end up together."""
        old = set(notes)
        if not old:
            return []
        self._push()
        new = [m for m in (change(n) for n in self.notes if n in old) if m is not None and m.t >= 0]
        keep = [n for n in self.notes if n not in old
                and not any(m.lane == n.lane and abs(m.t - n.t) < SAME_HIT for m in new)]
        self._set(keep + new)
        return new

    def move(self, notes, dt=0.0, dlane=0, grid=0):
        """Move notes by dt seconds (then snapped) and dlane lanes down (negative = up)."""
        def change(n):
            i = min(len(LANES) - 1, max(0, LANES.index(n.lane) + dlane))
            lane = LANES[i]
            return replace(n, t=self.snap(n.t + dt, grid) if dt else n.t, lane=lane,
                           open=n.open and lane == "hihat")
        return self._replace(notes, change)

    def set_lane(self, notes, lane):
        return self._replace(notes, lambda n: replace(n, lane=lane, open=n.open and lane == "hihat"))

    def set_velocity(self, notes, velocity):
        velocity = max(1, min(127, int(velocity)))
        return self._replace(notes, lambda n: replace(n, velocity=velocity))

    def set_open(self, notes, open_):
        return self._replace(notes, lambda n: replace(n, open=open_ and n.lane == "hihat"))

    # ---------- bars ----------

    def copy_bars(self, first, last):
        """Copy bars first..last (0-based, inclusive)."""
        a, b = first * self.bar, (last + 1) * self.bar
        self.clipboard = (last - first + 1, [replace(n, t=n.t - a) for n in self.notes if a <= n.t < b - 1e-9])

    def paste_bars(self, at_bar):
        """Replace bars at_bar.. with the copied bars. Returns the pasted notes."""
        if not self.clipboard:
            return []
        count, copied = self.clipboard
        a = at_bar * self.bar
        b = a + count * self.bar
        self._push()
        pasted = [replace(n, t=n.t + a) for n in copied]
        keep = [n for n in self.notes if not a <= n.t < b - 1e-9
                and not any(m.lane == n.lane and abs(m.t - n.t) < SAME_HIT for m in pasted)]
        self._set(keep + pasted)
        return pasted

    # ---------- tempo and bar 1 ----------

    def set_bpm(self, bpm):
        """Correct the tempo. Notes keep their times (they follow the song audio); the bars move."""
        if bpm > 0 and abs(bpm - self.bpm) > 1e-6:
            self._push()
            self.bpm = float(bpm)

    def shift_all(self, dt):
        """Move the whole part (and its alignment with the song audio, so they stay in sync).
        Notes moved before bar 1 are dropped."""
        if not dt:
            return
        self._push()
        self.shift += dt
        self._set([replace(n, t=n.t + dt) for n in self.notes if n.t + dt >= 0])

    def bar_one_at(self, note):
        """Move everything so `note` lands on the start of the bar it's nearest to."""
        target = max(0.0, round(note.t / self.bar) * self.bar)
        self.shift_all(target - note.t)

    # ---------- practice / files ----------

    def to_lesson(self):
        return from_notes(self.title, self.bpm, [(n.t, n.lane, n.velocity, n.open) for n in self.notes],
                          source=self.path, backing=self.backing, backing_offset=self.backing_offset)

    def has_backup(self):
        return backup_path(self.path).exists()

    def save(self):
        """Write the MIDI and its sidecar in place. The first save keeps the converted original."""
        import pretty_midi

        backup = backup_path(self.path)
        if not backup.exists():
            shutil.copy2(self.path, backup)
            if self.path.with_suffix(".json").exists():
                shutil.copy2(self.path.with_suffix(".json"), backup.with_suffix(".json"))
        midi = pretty_midi.PrettyMIDI(initial_tempo=self.bpm)
        drums = pretty_midi.Instrument(program=0, is_drum=True, name="Drums")
        for n in self.notes:
            drums.notes.append(pretty_midi.Note(velocity=int(n.velocity), pitch=n.midi_pitch(),
                                                start=float(n.t), end=float(n.t) + NOTE_LEN))
        midi.instruments.append(drums)
        midi.write(str(self.path))
        meta = read_metadata(self.path)
        meta.update(bpm=round(self.bpm, 3), shift=self.shift,
                    edited=datetime.datetime.now().isoformat(timespec="seconds"))
        self.path.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        self.dirty = False

    def revert(self):
        """Put the converted original back (keeps the backup, so it can be reverted to again)."""
        backup = backup_path(self.path)
        shutil.copy2(backup, self.path)
        if backup.with_suffix(".json").exists():
            shutil.copy2(backup.with_suffix(".json"), self.path.with_suffix(".json"))
        return load_part(self.path)


def load_part(midi_path):
    """Load a drum MIDI file for editing. Times are kept exactly (no snapping); hits on one drum that
    practice treats as one (e.g. closed + open hi-hat together) are merged the same way, so the
    editor shows what you'll practise."""
    import pretty_midi

    path = Path(midi_path)
    pm = pretty_midi.PrettyMIDI(str(path))
    tempi = pm.get_tempo_changes()[1]
    meta = read_metadata(path)
    bpm = float(tempi[0]) if len(tempi) else float(meta.get("bpm") or 120.0)
    hits = [(float(n.start), NOTE_TO_LANE[n.pitch], int(n.velocity), n.pitch in OPEN_HAT_NOTES, n.pitch)
            for inst in [i for i in pm.instruments if i.is_drum] or pm.instruments
            for n in inst.notes if n.pitch in NOTE_TO_LANE]
    notes = [EditNote(*h) for h in merge_hits(hits)]
    backing = path.parent / meta["backing"] if meta.get("backing") else None
    title = meta.get("title") or path.stem.removesuffix("_drums")
    return Part(path, notes, bpm, float(meta.get("shift") or 0.0), title,
                backing if backing and backing.exists() else None)
