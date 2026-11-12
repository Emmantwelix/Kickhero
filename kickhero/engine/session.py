"""One practice run: the transport (where in the lesson we are), looping, wait mode and scoring.

Time bookkeeping:
- `perf` is time.perf_counter() seconds: the master clock shared by MIDI input, audio and display.
- `u` is "unwrapped" lesson time: it keeps growing across loop passes and is negative-ish during
  the count-in. Pass p of the loop region [a, b) covers u in [a + p*L, b + p*L), L = b - a.
- Lesson time t = u - p*L is what notes and the scorer use.
Nothing here reads a clock; callers pass `now`, which keeps it testable.
"""

import bisect
import math
import statistics
from collections import deque

from ..lanes import LANES
from .scoring import DEFAULT_NORMAL_VELOCITY, HIT_WINDOW, PassScorer

AUTO_SPEED_STEP = 0.05
AUTO_SPEED_ACCURACY = 0.90


class Session:
    def __init__(self, lesson, speed=1.0, loop_bars=None, looping=False, lanes=None, wait_mode=False,
                 count_in_bars=1, auto_speed_up=False, target_speed=1.0, rate_dynamics=False,
                 speed_steps=None):
        self.lesson = lesson
        first, last = loop_bars or (0, lesson.bars)
        self.a, self.b = first * lesson.bar, last * lesson.bar
        self.L = self.b - self.a
        self.looping = looping
        self.lanes = set(lanes) if lanes else set(LANES)
        self.wait_mode = wait_mode
        self.count_in = count_in_bars * lesson.bar
        self.auto_speed_up = auto_speed_up
        self.target_speed = target_speed
        self.speed_steps = sorted(speed_steps) if speed_steps else None  # auto speed-up jumps between these
        self.rate_dynamics = rate_dynamics
        self._normal_hits = {}             # lane -> recent velocities of hits on normal notes
        self._normal_all = deque(maxlen=24)
        self._times = [n.t for n in lesson.notes]
        self._tp = None  # transport: (start_perf, u at start_perf, speed, paused u or None)
        self._initial_speed = speed
        self.scorers = {}
        self.finished_passes = set()
        self.done = False

    # ---------- transport ----------

    def start(self, now):
        self._tp = (now, self.a - self.count_in, self._initial_speed, None)

    @property
    def started(self):
        return self._tp is not None

    @property
    def speed(self):
        return self._tp[2] if self._tp else self._initial_speed

    @property
    def paused(self):
        return bool(self._tp and self._tp[3] is not None)

    def u_at(self, perf):
        if self._tp is None:
            return self.a - self.count_in
        start, anchor, speed, paused = self._tp
        return paused if paused is not None else anchor + (perf - start) * speed

    def set_speed(self, speed, now):
        if self._tp is None:
            self._initial_speed = speed
            return
        _, _, _, paused = self._tp
        self._tp = (now, self.u_at(now), speed, paused)  # re-anchor so the position doesn't jump
        u = self.u_at(now)
        current = self.pass_of(u)
        begun = not self.in_count_in(u)
        for p, sc in self.scorers.items():
            if p > current or (p == current and not begun):
                sc.speed = sc.slowest = speed
            elif p == current:  # mid-pass: judge the rest at the new speed, but the pass counts at the slowest
                sc.speed = speed
                sc.slowest = min(sc.slowest, speed)

    def _pause(self, u, now):
        start, anchor, speed, _ = self._tp
        self._tp = (start, anchor, speed, u)

    def _resume(self, now):
        _, _, speed, paused = self._tp
        self._tp = (now, paused, speed, None)

    # ---------- position helpers ----------

    def pass_of(self, u):
        return 0 if u < self.a else int((u - self.a) // self.L)

    def lesson_time(self, u):
        return u - self.pass_of(u) * self.L

    def in_count_in(self, u):
        return u < self.a

    def _passes(self, u0, u1):
        last = self.pass_of(u1) if self.looping else 0
        return range(self.pass_of(u0), last + 1)

    def notes_between(self, u0, u1):
        """Yield (u, note index, note, pass) for loop-region notes with u0 <= u < u1."""
        notes = self.lesson.notes
        for p in self._passes(u0, u1):
            lo, hi = max(u0 - p * self.L, self.a), min(u1 - p * self.L, self.b)
            if lo >= hi:
                continue
            for i in range(bisect.bisect_left(self._times, lo), bisect.bisect_left(self._times, hi)):
                yield notes[i].t + p * self.L, i, notes[i], p

    def beats_between(self, u0, u1):
        """Yield (u, is_downbeat) for every metronome beat with u0 <= u < u1, count-in included."""
        beat, bpb = self.lesson.beat * self.lesson.click_beats, self.lesson.clicks_per_bar
        start = self.a - self.count_in
        end = math.inf if self.looping else self.b
        k = math.ceil((max(u0, start) - self.a) / beat - 1e-9)
        while True:
            u = self.a + k * beat
            if u >= u1 or u >= end:
                return
            yield u, k % bpb == 0
            k += 1

    def scorer(self, p):
        if p not in self.scorers:
            self.scorers[p] = PassScorer(self.lesson.notes, self.speed, self.lanes, (self.a, self.b))
        return self.scorers[p]

    def judgement(self, p, index):
        sc = self.scorers.get(p)
        return sc.judged.get(index) if sc else None

    # ---------- input ----------

    def normal_level(self, lane):
        """The player's own normal hit strength on this lane (median of recent normal-note hits),
        falling back to all lanes, then to a default, until enough hits have been heard."""
        own = self._normal_hits.get(lane, ())
        if len(own) >= 3:
            return statistics.median(own)
        if len(self._normal_all) >= 3:
            return statistics.median(self._normal_all)
        return DEFAULT_NORMAL_VELOCITY

    def _learn_level(self, lane, velocity):
        self._normal_hits.setdefault(lane, deque(maxlen=16)).append(velocity)
        self._normal_all.append(velocity)

    def hit(self, lane, perf, velocity=0, opened=None):
        """A pad hit on `lane` at perf time (already latency-corrected). Returns a Judgement or None.
        velocity 0 = unknown (keyboard): dynamics aren't rated. opened: for hi-hat hits, whether the
        kit says the hi-hat was open (None = it can't tell); rated only in lessons with open hi-hats."""
        if self._tp is None or self.done or lane not in self.lanes:
            return None
        u = self.u_at(perf)
        p = self.pass_of(u)
        best = None
        for q in (p - 1, p, p + 1):
            if q < 0 or q in self.finished_passes or (q > 0 and not self.looping):
                continue
            c = self.scorer(q).candidate(lane, u - q * self.L)
            if c and (best is None or abs(c[1]) < abs(best[2])):
                best = (q, c[0], c[1])
        if best:
            q, i, _ = best
            note = self.lesson.notes[i]
            level = self.normal_level(lane) if self.rate_dynamics and velocity else None
            j = self.scorers[q].judge(i, u - q * self.L, grade="perfect" if self.paused else None,
                                      velocity=velocity, normal_level=level,
                                      opened=opened if self.lesson.has_open_hats else None)
            if velocity and note.dyn == "normal":
                self._learn_level(lane, velocity)
            return j
        if self.in_count_in(u) or (p > 0 and not self.looping) or p in self.finished_passes:
            return None
        return self.scorer(p).extra(lane)

    # ---------- per-frame update ----------

    def update(self, now):
        """Advance bookkeeping. Returns events: ("miss", j), ("pass", p, summary),
        ("finished", summary, slowest speed played) and ("speed", new_speed)."""
        if self._tp is None or self.done:
            return []
        events = []
        u = self.u_at(now)
        p = self.pass_of(u)

        if self.wait_mode:
            if self.paused:
                pu = self._tp[3]
                q = self.pass_of(pu)
                if not self.scorer(q).unjudged_until(pu - q * self.L + 1e-6):
                    self._resume(now)
            elif not self.in_count_in(u):
                sc = self.scorer(p)
                pending = sc.unjudged_until(u - p * self.L)
                if pending:
                    self._pause(self.lesson.notes[pending[0]].t + p * self.L, now)
        else:
            for q in (p - 1, p):
                if q >= 0 and q in self.scorers and q not in self.finished_passes:
                    events += [("miss", j) for j in self.scorers[q].sweep(u - q * self.L)]

        for q in (p - 1, p):
            if q < 0 or q in self.finished_passes or u - q * self.L <= self.b + HIT_WINDOW * self.speed:
                continue
            sc = self.scorer(q)
            events += [("miss", j) for j in sc.sweep(math.inf)]
            summary = sc.summary()
            self.finished_passes.add(q)
            events.append(("pass", q, summary))
            if not self.looping:
                self.done = True
                events.append(("finished", summary, sc.slowest))
                break
            if self.auto_speed_up and summary["accuracy"] >= AUTO_SPEED_ACCURACY and self.speed < self.target_speed:
                new = round(self.speed + AUTO_SPEED_STEP, 2)
                if self.speed_steps:
                    new = next((x for x in self.speed_steps if x > self.speed + 1e-9), new)
                new = min(self.target_speed, new)
                self.set_speed(new, now)
                events.append(("speed", new))
        return events
