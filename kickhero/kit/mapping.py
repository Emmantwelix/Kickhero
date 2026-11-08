"""Which pad is which: maps the MIDI notes a kit sends onto practice lanes.

Every kit starts from the General MIDI layout, which most kits follow. The setup wizard then
"learns" the kit: you hit a pad while a lane is highlighted and that note joins the lane.
A note mapped to "" is ignored (e.g. the hi-hat pedal chick).
"""

from ..lanes import HIHAT_PEDAL, LANES, NOTE_TO_LANE, OPEN_HAT, OPEN_HAT_NOTES

REPORTS_OPEN = "reports_open"  # key in the saved map: the pad setup learned this kit's open hi-hat note(s)


class KitMap:
    """note -> lane. The open hi-hat is stored as OPEN_HAT: it plays on the hi-hat lane, but the note
    itself says the hat was open (kits with a hi-hat pedal send a different note while it's lifted)."""

    def __init__(self, notes=None):
        self.notes = dict(NOTE_TO_LANE)
        self.notes.update({n: OPEN_HAT for n in OPEN_HAT_NOTES})
        self.notes[HIHAT_PEDAL] = ""
        self.reports_open = False
        if notes:
            self.notes.update({int(n): lane for n, lane in notes.items()})

    def lane_for(self, note):
        """Lane name, "" for an ignored note, or None if the note is unknown."""
        lane = self.notes.get(note)
        return "hihat" if lane == OPEN_HAT else lane

    def learn(self, note, lane):
        if lane not in LANES and lane not in ("", OPEN_HAT):
            raise ValueError(f"unknown lane {lane!r}")
        self.notes[note] = lane
        if lane == OPEN_HAT:
            self.reports_open = True

    def notes_for(self, lane):
        return sorted(n for n, ln in self.notes.items() if ln == lane)

    def is_open_hat(self, note):
        return self.notes.get(note) == OPEN_HAT

    def hat_open(self, note, pedal=None, seen_open=False):
        """Was a hi-hat hit open? True/False, or None when the kit can't tell (no hi-hat pedal).
        Kits with a pedal send an open-hat note while it's lifted, and/or the pedal position as CC4
        (`pedal`, 0 = fully open). Once the kit is known to send open notes (learned in the pad setup,
        or `seen_open` during this session), its other hi-hat notes really mean closed."""
        if self.is_open_hat(note):
            return True
        if pedal is not None:
            return pedal < 64
        if self.reports_open or seen_open:
            return False
        return None

    def to_json(self):
        data = {str(n): lane for n, lane in sorted(self.notes.items())}
        if self.reports_open:
            data[REPORTS_OPEN] = True
        return data

    @classmethod
    def from_json(cls, data):
        m = cls()
        m.notes = {int(n): lane for n, lane in data.items() if n.isdigit()}
        m.reports_open = bool(data.get(REPORTS_OPEN))
        if OPEN_HAT not in m.notes.values():  # saved before open hats were learned: GM open notes
            m.notes.update({n: OPEN_HAT for n in OPEN_HAT_NOTES if m.notes.get(n) == "hihat"})
        return m


def load_kit(settings, device):
    data = settings["kits"].get(device)
    return KitMap.from_json(data) if data else KitMap()


def save_kit(settings, device, kit):
    kits = dict(settings["kits"])
    kits[device] = kit.to_json()
    settings["kits"] = kits
