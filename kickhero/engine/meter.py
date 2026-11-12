"""Time signatures ("meters") as text: "4/4", "6/8", or a repeating cycle of bars like "7/8,11/8".

Lessons measure time in quarter-note beats (60/bpm seconds), whatever the meter: a 6/8 bar is 3 beats,
a 5/8 bar 2.5. The click follows how drummers count: quarters in x/4, dotted quarters in compound
meters (6/8, 9/8, 12/8), eighths in odd /8 meters (5/8, 7/8).
"""

COMMON_METERS = ["4/4", "3/4", "2/4", "5/4", "6/8", "7/8", "9/8", "12/8"]


def _parts(meter):
    out = []
    for part in str(meter or "4/4").split(","):
        num, den = part.strip().split("/")
        num, den = int(num), int(den)
        if num <= 0 or den not in (1, 2, 4, 8, 16, 32):
            raise ValueError(meter)
        out.append((num, den))
    return out


def parse_meter(text, default="4/4"):
    """A clean meter string ("6/8", "7/8,11/8"), or `default` if `text` isn't one."""
    if not text or not str(text).strip():
        return default
    try:
        return ",".join(f"{n}/{d}" for n, d in _parts(text))
    except (ValueError, AttributeError):
        return default


def meter_beats(meter):
    """Quarter-note beats per bar: "7/4" -> 7, "6/8" -> 3. A changing meter ("7/8,11/8") is one bar of the
    whole cycle, so the bar lines repeat with the groove."""
    try:
        total = sum(n * 4 / d for n, d in _parts(meter))
    except (ValueError, AttributeError):
        return 4
    return int(total) if total == int(total) else total


def pulse(meter):
    """(beats per click, clicks per bar) for the metronome."""
    try:
        parts = _parts(meter)
    except (ValueError, AttributeError):
        return 1, 4
    if len(parts) == 1:
        num, den = parts[0]
        if den == 8 and num % 3 == 0 and num > 3:
            return 1.5, num // 3                      # compound: dotted quarters
        if den <= 4:
            return 4 / den, num                       # x/4, x/2: one click per written beat
    # odd eighths (5/8, 7/8), sixteenths, changing meters: count the smallest written note
    small = max(d for _, d in parts)
    step = 4 / small
    return step, round(meter_beats(meter) / step)


def is_common_time(meter):
    return parse_meter(meter) == "4/4"


def add_time_signature(pm, meter):
    """Put the meter into a pretty_midi.PrettyMIDI, so a DAW shows the same bars. Only a single meter is
    written: a changing one ("7/8,11/8") is left out."""
    import pretty_midi

    parts = _parts(parse_meter(meter))
    if len(parts) == 1:
        pm.time_signature_changes = [pretty_midi.TimeSignature(parts[0][0], parts[0][1], 0.0)]
