"""Grooves: real drum grooves from a groove library installed on this computer, played like course lessons.

The grooves aren't part of Kickhero. They're read from where the library is installed: a folder with
metadata.json (one entry per groove: file, name, tempo, meter, bars, style), midi/*.mid and
keymaps/<keymap>.json (which drum each MIDI note is). Takefuji Groove Vault is laid out this way.
"""

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from ..engine.lesson import from_notes, merge_hits
from ..lanes import NOTE_TO_LANE, OPEN_HAT_NOTES

DEFAULT_FOLDERS = [Path(r"C:\Program Files\TakefujiGrooveVault\Resources"),
                   Path(r"C:\Program Files (x86)\TakefujiGrooveVault\Resources")]
MIN_BARS = 8  # short grooves repeat until the lesson is at least this long
LEVELS = 5    # grooves are ranked by difficulty and split into this many levels

TOMS = {"hightom1": "tom1", "hightom2": "tom1", "midtom1": "tom2", "midtom2": "tom2",
        "floortom1": "tom3", "floortom2": "tom3"}
CYMBALS = {"crash1", "crash2", "cymbal1", "cymbal2", "cymbal3"}
OPEN_HAT_ARTICS = {"open_tip", "open_shank", "half_tip", "half_shank", "threequarter_tip", "threequarter_shank"}
FOOT_HAT_ARTICS = {"pedal", "splash"}  # played with the foot: not a note to hit with a stick


def part_to_lane(part, artic):
    """(lane, open hi-hat) for a key map's drum part and articulation, or None to leave the note out."""
    if part == "kick":
        return "kick", False
    if part == "snare":
        return "snare", False
    if part == "hihat":
        if artic in FOOT_HAT_ARTICS:
            return None
        return "hihat", artic in OPEN_HAT_ARTICS
    if part in TOMS:
        return TOMS[part], False
    if artic == "choke":
        return None
    if part in CYMBALS:
        return "crash", False
    if part == "ride1":
        return "ride", False
    return None  # percussion


def load_keymap(path):
    """MIDI note -> (lane, open) from a key map file (note_to_part); None when the file is missing."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    out = {}
    for note, v in data.get("note_to_part", {}).items():
        mapped = part_to_lane(v.get("part", ""), v.get("artic", ""))
        if mapped:
            out[int(note)] = mapped
    return out


GM_KEYMAP = {n: (lane, n in OPEN_HAT_NOTES) for n, lane in NOTE_TO_LANE.items() if n != 44}


def meter_beats(meter):
    """Quarter-note beats per bar: "7/4" -> 7, "6/8" -> 3. A changing meter ("7/8,11/8") is one bar of the
    whole cycle, so the bar lines repeat with the groove."""
    total = 0.0
    for part in str(meter or "4/4").split(","):
        try:
            num, den = part.strip().split("/")
            total += int(num) * 4 / int(den)
        except ValueError:
            return 4
    return int(total) if total == int(total) else total


@dataclass
class GrooveLesson:
    id: str
    title: str
    bpm: float
    path: Path
    keymap: dict
    meter: str = "4/4"
    bars: int | None = None
    category: str = "Groove"
    density: str = ""
    vibe: list = field(default_factory=list)
    track: str = ""
    level: int = 1
    unit: str = "Groove Lab"
    rate_dynamics: bool = False  # played by a human: dynamics are there, but rating them is optional

    @property
    def key(self):
        return f"groove:{self.id}"  # the library's id, so progress stays put when names change

    @property
    def number(self):
        return f"Level {self.level}"

    @property
    def heading(self):
        return f"{self.meter}  ·  {self.density}".rstrip(" ·")

    @property
    def card_title(self):
        """The title on its card, which sits under its level's heading: "Groove 14" or "Fill 3"."""
        return self.title.split(" · ", 1)[-1]

    @property
    def odd_time(self):
        return self.meter.replace(" ", "") != "4/4"

    @property
    def tip(self):
        styles = ", ".join(self.vibe)
        return f"{self.title}: {self.category.lower()} in {self.meter}" + (f"  ·  {styles}" if styles else "")

    def difficulty(self):
        """How hard it is to play: the lesson's difficulty (hand and kick speed, limbs at once, fills,
        syncopation...), plus a step for odd time signatures."""
        return self.rating().score + (1.5 if self.odd_time else 0)

    def rating(self):
        """The lesson's Rating (E/M/H, why), worked out once."""
        if "_rating" not in self.__dict__:
            self.__dict__["_rating"] = self.to_lesson().rating()
        return self.__dict__["_rating"]

    def to_lesson(self):
        """The groove, repeated until the lesson is MIN_BARS bars long (twice at least)."""
        import mido

        mid = mido.MidiFile(str(self.path))
        beat_s = 60.0 / self.bpm
        hits = []
        for track in mid.tracks:
            tick = 0
            for msg in track:
                tick += msg.time
                if msg.type == "note_on" and msg.velocity and msg.note in self.keymap:
                    lane, open_ = self.keymap[msg.note]
                    hits.append((tick / mid.ticks_per_beat, lane, msg.velocity, open_))
        bpb = meter_beats(self.meter)
        last = max((h[0] for h in hits), default=0.0)
        # the metadata's bar count, unless the file is longer (a hit right on the end is the next pass's beat 1)
        bars = self.bars if self.bars and last < self.bars * bpb + 1 / 16 else math.floor(last / bpb + 1e-6) + 1
        length = bars * bpb
        hits = [h for h in hits if h[0] < length - 1 / 16]  # a hit on the very end is the next pass's first
        repeats = max(2, math.ceil(MIN_BARS / bars))
        notes = [((h[0] + rep * length) * beat_s, *h[1:]) for rep in range(repeats) for h in hits]
        return from_notes(self.title, self.bpm, merge_hits(notes), bars=bars * repeats, beats_per_bar=bpb,
                          source=self.path)


def find_folder(chosen=""):
    """The groove library folder: the one chosen in the settings, else a usual install place."""
    for folder in ([Path(chosen)] if chosen else []) + DEFAULT_FOLDERS:
        if (folder / "metadata.json").exists():
            return folder
    return None


def load_grooves(folder):
    """GrooveLessons for every groove in the library whose MIDI file and key map are there."""
    if folder is None:
        return []
    folder = Path(folder)
    try:
        entries = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    keymaps, out = {}, []
    for e in entries:
        path = folder / "midi" / str(e.get("filename", ""))
        name = str(e.get("keymap") or "gm").lower()
        if name not in keymaps:
            keymaps[name] = GM_KEYMAP if name == "gm" else load_keymap(folder / "keymaps" / f"{name}.json")
        if not path.is_file() or not keymaps[name] or not e.get("bpm"):
            continue
        out.append(GrooveLesson(
            id=str(e.get("id") or path.stem), title=str(e.get("display_name") or path.stem), bpm=float(e["bpm"]),
            path=path, keymap=keymaps[name], meter=str(e.get("meter") or "4/4"), bars=e.get("bars"),
            category=str(e.get("category") or "Groove"), density=str(e.get("density") or ""),
            vibe=list(e.get("vibe") or []), track=str(e.get("source_title") or "")))
    return by_level(out)


def by_level(grooves):
    """Rank grooves easiest first, split them into LEVELS equal levels and name them by level:
    "Level 2 · Groove 14", "Level 2 · Fill 3"."""
    ranked = sorted(grooves, key=lambda g: (g.difficulty(), g.bpm, g.id))
    counts = {}
    for i, g in enumerate(ranked):
        g.level = i * LEVELS // max(1, len(ranked)) + 1
        kind = "Fill" if g.category == "Fill" else "Groove"
        counts[g.level, kind] = counts.get((g.level, kind), 0) + 1
        g.title = f"Level {g.level} · {kind} {counts[g.level, kind]}"
    return ranked
