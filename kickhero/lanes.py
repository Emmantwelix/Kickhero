"""The drum lanes shown on the practice screen, and how General MIDI drum notes map onto them."""

# Top to bottom on screen: cymbals first, kick last
LANES = ["crash", "hihat", "ride", "snare", "tom1", "tom2", "tom3", "kick"]

LANE_NAMES = {
    "crash": "Crash", "hihat": "Hi-hat", "ride": "Ride", "snare": "Snare",
    "tom1": "High tom", "tom2": "Mid tom", "tom3": "Floor tom", "kick": "Kick",
}

LANE_COLORS = {  # hex, readable on the dark theme
    "crash": "#f2c14e", "hihat": "#4ecdc4", "ride": "#a3d977", "snare": "#ff6b6b",
    "tom1": "#c08cff", "tom2": "#9d7bff", "tom3": "#7a6cff", "kick": "#ff9f43",
}

# General MIDI percussion notes per lane
GM_NOTES = {
    "kick": [35, 36],
    "snare": [37, 38, 40],
    "hihat": [22, 26, 42, 44, 46],  # 22/26: closed/open hi-hat edge on many Roland-style kits
    "ride": [51, 53, 59],
    "crash": [49, 52, 55, 57],
    "tom1": [48, 50],
    "tom2": [45, 47],
    "tom3": [41, 43],
}

NOTE_TO_LANE = {n: lane for lane, notes in GM_NOTES.items() for n in notes}

# Representative note per lane, for writing lessons back out as MIDI
LANE_TO_NOTE = {"kick": 36, "snare": 38, "hihat": 42, "ride": 51, "crash": 49, "tom1": 50, "tom2": 47, "tom3": 43}

HIHAT_PEDAL = 44  # foot "chick": in a lesson it's a hi-hat note, but from a kit it's ignored by default

# An open hi-hat is played on the hi-hat lane, but sounds different and (with a hi-hat pedal) is a
# different stroke: notes carry an `open` flag, and the app has a separate sound for it.
OPEN_HAT = "hihat_open"
OPEN_HAT_NOTES = {46, 26}
CLOSED_HAT_NOTES = {42, 22}

# Every sound the app can play: one per lane, plus the open hi-hat (listed after the hi-hat)
SOUNDS = LANES[:2] + [OPEN_HAT] + LANES[2:]
SOUND_NAMES = dict(LANE_NAMES, **{OPEN_HAT: "Open hi-hat"})
