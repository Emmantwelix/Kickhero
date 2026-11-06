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


@dataclass
class Judgement:
    grade: str          # perfect / good / ok / miss / extra
    lane: str
    index: int          # note index in the lesson, -1 for an extra hit
    offset: float = 0.0  # real seconds; negative = early


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

    def judge(self, index, t, grade=None):
        offset = (t - self.notes[index].t) / self.speed
        j = Judgement(grade or grade_for(offset) or "ok", self.notes[index].lane, index, offset)
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
        for i in self.active:
            j = self.judged.get(i)
            g = j.grade if j else "miss"
            counts[g] += 1
            lane = self.notes[i].lane
            lane_pts[lane] = lane_pts.get(lane, 0.0) + POINTS[g]
            lane_n[lane] = lane_n.get(lane, 0) + 1
        n = len(self.active)
        points = sum(POINTS[g] * c for g, c in counts.items()) - EXTRA_PENALTY * len(self.extras)
        accuracy = max(0.0, points / n) if n else 1.0
        offsets = [j.offset for j in self.judged.values() if j.grade != "miss"]
        per_lane = {lane: lane_pts[lane] / lane_n[lane] for lane in lane_n}
        return {
            "accuracy": accuracy,
            "stars": sum(accuracy >= s for s in STARS),
            "counts": counts,
            "extras": len(self.extras),
            "notes": n,
            "mean_offset_ms": 1000 * sum(offsets) / len(offsets) if offsets else 0.0,
            "per_lane": per_lane,
            "weakest_lane": min(per_lane, key=per_lane.get) if per_lane else None,
        }
