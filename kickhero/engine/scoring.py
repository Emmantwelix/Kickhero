"""Matching pad hits to lesson notes and grading them. Pure logic, no clocks or I/O.

Times passed in are lesson times (seconds at 100% speed). Grades are judged on the error the
player actually makes in real time, so at 50% speed a lesson-time error is halved before grading.
"""

from dataclasses import dataclass

WINDOWS = (("perfect", 0.030), ("good", 0.070), ("ok", 0.120))  # max real-time error, seconds
HIT_WINDOW = WINDOWS[-1][1]
POINTS = {"perfect": 1.0, "good": 0.75, "ok": 0.4, "miss": 0.0}
EXTRA_PENALTY = 0.25  # points lost per hit that matches no note
STARS = (0.60, 0.80, 0.95)  # accuracy for 1, 2, 3 stars
DYNAMIC_MISS_FACTOR = 0.6  # an accent played too soft (or ghost too loud) keeps this share of its points
HAT_MISS_FACTOR = 0.6      # same for a hi-hat played closed when it should be open, or the other way round

# Dynamics are judged against the player's own normal level, because kits differ a lot in how
# hard you must hit for a given velocity. Until enough normal hits are heard, assume this level:
DEFAULT_NORMAL_VELOCITY = 90
ACCENT_ABOVE = 10      # an accent must be at least this much louder than your normal level...
ACCENT_CEILING = 120   # ...or at least this loud (so hard hitters can still accent)
GHOST_BELOW = 0.70     # a ghost note must be under 70% of your normal level...
GHOST_FLOOR = 40       # ...or at most this loud


@dataclass
class Judgement:
    grade: str          # perfect / good / ok / miss / extra
    lane: str
    index: int          # note index in the lesson, -1 for an extra hit
    offset: float = 0.0  # real seconds; negative = early
    dynamic: str | None = None  # accent/ghost notes: "ok", "too_soft" or "too_loud"; None = not rated
    velocity: int = 0
    hat: str | None = None      # hi-hat notes: "ok", "open_it" or "close_it"; None = not rated


def judge_dynamic(dyn, velocity, normal_level):
    """Was an accent or ghost note played at the right strength? None for normal notes."""
    if dyn == "accent":
        return "ok" if velocity >= min(normal_level + ACCENT_ABOVE, ACCENT_CEILING) else "too_soft"
    if dyn == "ghost":
        return "ok" if velocity <= max(normal_level * GHOST_BELOW, GHOST_FLOOR) else "too_loud"
    return None


def judge_hat(note, opened):
    """Was a hi-hat note played open/closed as written? None if not rated (other lanes, or the kit
    can't tell open from closed)."""
    if note.lane != "hihat" or opened is None:
        return None
    if opened == note.open:
        return "ok"
    return "open_it" if note.open else "close_it"


def grade_for(real_error):
    for name, limit in WINDOWS:
        if abs(real_error) <= limit:
            return name
    return None


class PassScorer:
    """Scores one play-through of a list of notes (one loop pass)."""

    def __init__(self, notes, speed=1.0, lanes=None, region=None):
        self.notes = notes
        self.speed = speed
        self.slowest = speed  # the slowest speed any of this pass was played at (a mid-pass change)
        a, b = region if region else (float("-inf"), float("inf"))
        self.active = [i for i, n in enumerate(notes) if a <= n.t < b and (lanes is None or n.lane in lanes)]
        self.judged = {}   # note index -> Judgement
        self.extras = []
        self._sweep_from = 0  # position in self.active up to which misses are settled

    def candidate(self, lane, t):
        """(index, lesson-time error) of the nearest unjudged note on `lane` within the hit window."""
        window = HIT_WINDOW * self.speed
        best = None
        for i in self.active:
            n = self.notes[i]
            if n.t > t + window:
                break
            if n.lane == lane and i not in self.judged and abs(t - n.t) <= window:
                if best is None or abs(t - n.t) < abs(best[1]):
                    best = (i, t - n.t)
        return best

    def judge(self, index, t, grade=None, velocity=0, normal_level=None, opened=None):
        """velocity/normal_level given: also rate the dynamics of accent and ghost notes.
        opened given (True/False): also rate open vs closed on hi-hat notes."""
        note = self.notes[index]
        offset = (t - note.t) / self.speed
        dynamic = judge_dynamic(note.dyn, velocity, normal_level) if velocity and normal_level else None
        j = Judgement(grade or grade_for(offset) or "ok", note.lane, index, offset, dynamic, velocity,
                      judge_hat(note, opened))
        self.judged[index] = j
        return j

    def extra(self, lane):
        j = Judgement("extra", lane, -1)
        self.extras.append(j)
        return j

    def sweep(self, t):
        """Mark notes whose hit window has passed by lesson time t as missed; returns the new misses."""
        window = HIT_WINDOW * self.speed
        misses = []
        while self._sweep_from < len(self.active):
            i = self.active[self._sweep_from]
            if self.notes[i].t + window >= t:
                break
            if i not in self.judged:
                self.judged[i] = Judgement("miss", self.notes[i].lane, i)
                misses.append(self.judged[i])
            self._sweep_from += 1
        return misses

    def unjudged_until(self, t):
        """Active notes at or before lesson time t that nobody has hit yet (for wait mode)."""
        out = []
        for i in self.active:
            if self.notes[i].t > t:
                break
            if i not in self.judged:
                out.append(i)
        return out

    def summary(self):
        counts = {g: 0 for g in POINTS}
        lane_pts, lane_n = {}, {}
        dyn = {"ok": 0, "too_soft": 0, "too_loud": 0}
        hat = {"ok": 0, "open_it": 0, "close_it": 0}
        points = 0.0
        for i in self.active:
            j = self.judged.get(i)
            g = j.grade if j else "miss"
            counts[g] += 1
            pts = POINTS[g]
            if j and j.dynamic:
                dyn[j.dynamic] += 1
                if j.dynamic != "ok":
                    pts *= DYNAMIC_MISS_FACTOR
            if j and j.hat:
                hat[j.hat] += 1
                if j.hat != "ok":
                    pts *= HAT_MISS_FACTOR
            points += pts
            lane = self.notes[i].lane
            lane_pts[lane] = lane_pts.get(lane, 0.0) + pts
            lane_n[lane] = lane_n.get(lane, 0) + 1
        n = len(self.active)
        points -= EXTRA_PENALTY * len(self.extras)
        rated = sum(dyn.values())
        accuracy = max(0.0, points / n) if n else 1.0
        offsets = [j.offset for j in self.judged.values() if j.grade != "miss"]
        per_lane = {lane: lane_pts[lane] / lane_n[lane] for lane in lane_n}
        stars = sum(accuracy >= s for s in STARS) if n else 0  # no stars for a pass with nothing to play
        if rated:  # when dynamics are rated they limit the stars too: accents and ghosts are the point
            stars = min(stars, sum(dyn["ok"] / rated >= s for s in STARS))
        hats = sum(hat.values())
        if hats:  # same for opening and closing the hi-hat
            stars = min(stars, sum(hat["ok"] / hats >= s for s in STARS))
        return {
            "accuracy": accuracy,
            "stars": stars,
            "counts": counts,
            "extras": len(self.extras),
            "notes": n,
            "mean_offset_ms": 1000 * sum(offsets) / len(offsets) if offsets else 0.0,
            "per_lane": per_lane,
            "weakest_lane": min(per_lane, key=per_lane.get) if per_lane else None,
            "dynamics": dict(dyn, score=dyn["ok"] / rated) if rated else None,
            "hihat": dict(hat, score=hat["ok"] / hats) if hats else None,
        }
