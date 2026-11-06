import math
import random

import pytest

from kickhero.engine.lesson import from_notes
from kickhero.engine.session import Session
from kickhero.kit.calibration import measure_latency
from kickhero.kit.mapping import KitMap

BPM = 120  # beat = 0.5 s, bar = 2 s


def rock_beat(bars=2):
    """Kick on 1 and 3, snare on 2 and 4, eighth-note hi-hats."""
    notes = []
    for bar in range(bars):
        for eighth in range(8):
            t = bar * 2 + eighth * 0.25
            notes.append((t, "hihat", 90))
            if eighth in (0, 4):
                notes.append((t, "kick", 110))
            if eighth in (2, 6):
                notes.append((t, "snare", 110))
    return from_notes("rock", BPM, notes, bars=bars)


def play(session, lesson, offset=0.0, jitter=0.0, skip=(), start=100.0, seed=1):
    """Simulate a drummer: hit every note at its time + offset (+ random jitter), in real time."""
    rnd = random.Random(seed)
    session.start(start)
    speed = session.speed
    perf0 = start + session.count_in / speed  # perf time of lesson time 0 (= loop start a)
    hits = sorted(
        (perf0 + (n.t - session.a) / speed + offset + rnd.uniform(-jitter, jitter), n.lane)
        for i, n in enumerate(lesson.notes) if i not in skip and session.a <= n.t < session.b
    )
    events, judgements = [], []
    for perf, lane in hits:
        events += session.update(perf)
        judgements.append(session.hit(lane, perf))
    end = perf0 + (session.L + 1.0) / speed
    events += session.update(end)
    return judgements, events


def test_perfect_play_scores_100():
    lesson = rock_beat()
    s = Session(lesson)
    judgements, events = play(s, lesson)
    assert all(j.grade == "perfect" for j in judgements)
    finished = [e for e in events if e[0] == "finished"]
    assert finished and finished[0][1]["accuracy"] == 1.0 and finished[0][1]["stars"] == 3


def test_late_play_reports_offset_and_grade():
    lesson = rock_beat()
    s = Session(lesson)
    judgements, events = play(s, lesson, offset=0.05)
    assert all(j.grade == "good" for j in judgements)
    summary = events[-1][1]
    assert summary["mean_offset_ms"] == pytest.approx(50, abs=1)


def test_half_speed_judges_real_time_error():
    lesson = rock_beat()
    s = Session(lesson, speed=0.5)
    judgements, events = play(s, lesson, offset=0.025)  # 25 ms real error at half speed
    assert all(j.grade == "perfect" for j in judgements)
    assert events[-1][1]["mean_offset_ms"] == pytest.approx(25, abs=1)


def test_misses_and_extras_cost_accuracy():
    lesson = rock_beat()
    s = Session(lesson)
    s.start(0.0)
    perf0 = s.count_in
    # hit only the snares, plus one stray kick that matches nothing
    for n in lesson.notes:
        if n.lane == "snare":
            s.update(perf0 + n.t)
            s.hit("snare", perf0 + n.t)
    assert s.hit("kick", perf0 + 0.37).grade == "extra"
    events = s.update(perf0 + lesson.length + 1)
    summary = [e for e in events if e[0] == "finished"][0][1]
    assert summary["counts"]["perfect"] == 4
    assert summary["counts"]["miss"] == len(lesson.notes) - 4
    assert summary["extras"] == 1
    assert summary["weakest_lane"] in ("hihat", "kick")


def test_muted_lanes_are_not_scored():
    lesson = rock_beat()
    s = Session(lesson, lanes=["kick", "snare"])
    s.start(0.0)
    events = s.update(s.count_in + lesson.length + 1)
    summary = [e for e in events if e[0] == "finished"][0][1]
    assert summary["notes"] == 8  # 4 kicks + 4 snares, hi-hats ignored
    assert s.hit("hihat", s.count_in + 0.25) is None


def test_loop_passes_and_auto_speed_up():
    lesson = rock_beat(bars=4)
    s = Session(lesson, speed=0.6, loop_bars=(1, 2), looping=True, auto_speed_up=True)
    s.start(0.0)
    passes, speeds = [], []
    perf = 0.0
    while len(passes) < 3:
        u = s.u_at(perf)
        p = s.pass_of(u)
        # hit every note of the current and next pass when its time comes
        for nu, i, n, q in s.notes_between(u, s.u_at(perf + 0.01)):
            s.hit(n.lane, perf)
        for e in s.update(perf):
            if e[0] == "pass":
                passes.append(e[2]["accuracy"])
            if e[0] == "speed":
                speeds.append(e[1])
        perf += 0.01
    assert all(a > 0.9 for a in passes)
    assert speeds[:2] == [0.65, 0.7]
    assert all(n.t >= 2 and n.t < 4 for n in [lesson.notes[i] for i in s.scorer(0).active])


def test_wait_mode_pauses_until_hit():
    lesson = rock_beat()
    s = Session(lesson, wait_mode=True)
    s.start(0.0)
    s.update(s.count_in + 0.1)          # first notes (t=0) are due: transport pauses on them
    assert s.paused and s.u_at(999) == pytest.approx(0.0)
    s.hit("kick", 5.0)
    s.update(5.0)
    assert s.paused                      # hi-hat at t=0 still missing
    s.hit("hihat", 6.0)
    s.update(6.0)
    assert not s.paused and s.u_at(6.0) == pytest.approx(0.0)
    assert s.u_at(6.1) == pytest.approx(0.1)


def test_beats_include_count_in_and_accent_downbeats():
    lesson = rock_beat()
    s = Session(lesson)
    beats = list(s.beats_between(-10, 100))
    assert len(beats) == 4 + 8           # 1 bar count-in + 2 bars
    assert [acc for _, acc in beats[:5]] == [True, False, False, False, True]
    assert beats[0][0] == pytest.approx(-2.0)


def test_latency_calibration():
    clicks = [i * 0.6 for i in range(16)]
    rnd = random.Random(3)
    hits = [c + 0.045 + rnd.uniform(-0.01, 0.01) for c in clicks[2:]]
    latency, spread, used = measure_latency(clicks, hits)
    assert latency == pytest.approx(0.045, abs=0.006) and spread < 0.01 and used == 14
    assert measure_latency(clicks, hits[:3]) is None


def test_kit_map_defaults_and_learning():
    kit = KitMap()
    assert kit.lane_for(38) == "snare" and kit.lane_for(36) == "kick"
    assert kit.lane_for(44) == ""        # hi-hat pedal ignored
    assert kit.lane_for(99) is None
    kit.learn(99, "tom1")
    assert KitMap.from_json(kit.to_json()).lane_for(99) == "tom1"


def test_difficulty_grows_with_density():
    easy = from_notes("e", 80, [(i * 0.75, "snare", 100) for i in range(8)])
    hard = rock_beat()
    assert easy.difficulty() < hard.difficulty()
    assert not math.isnan(hard.difficulty())
