"""Which pad is which: maps the MIDI notes a kit sends onto practice lanes.

Every kit starts from the General MIDI layout, which most kits follow. The setup wizard then
"learns" the kit: you hit a pad while a lane is highlighted and that note joins the lane.
A note mapped to "" is ignored (e.g. the hi-hat pedal chick).
"""

from ..lanes import HIHAT_PEDAL, LANES, NOTE_TO_LANE


class KitMap:
    def __init__(self, notes=None):
        self.notes = dict(NOTE_TO_LANE)
        self.notes[HIHAT_PEDAL] = ""
        if notes:
            self.notes.update({int(n): lane for n, lane in notes.items()})

    def lane_for(self, note):
        """Lane name, "" for an ignored note, or None if the note is unknown."""
        return self.notes.get(note)

    def learn(self, note, lane):
        if lane not in LANES and lane != "":
            raise ValueError(f"unknown lane {lane!r}")
        self.notes[note] = lane

    def notes_for(self, lane):
        return sorted(n for n, ln in self.notes.items() if ln == lane)

    def to_json(self):
        return {str(n): lane for n, lane in sorted(self.notes.items())}

    @classmethod
    def from_json(cls, data):
        m = cls()
        m.notes = {int(n): lane for n, lane in data.items()}
        return m


def load_kit(settings, device):
    data = settings["kits"].get(device)
    return KitMap.from_json(data) if data else KitMap()


def save_kit(settings, device, kit):
    kits = dict(settings["kits"])
    kits[device] = kit.to_json()
    settings["kits"] = kits
