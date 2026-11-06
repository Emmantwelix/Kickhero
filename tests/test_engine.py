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


def play_loop(s, n_passes):
    """Hit every note on time until n_passes loop passes are done; returns (accuracies, speed changes)."""
    s.start(0.0)
    passes, speeds = [], []
    perf = 0.0
    while len(passes) < n_passes:
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
    return passes, speeds


def test_loop_passes_and_auto_speed_up():
    lesson = rock_beat(bars=4)
    s = Session(lesson, speed=0.6, loop_bars=(1, 2), looping=True, auto_speed_up=True)
    passes, speeds = play_loop(s, 3)
    assert all(a > 0.9 for a in passes)
    assert speeds[:2] == [0.65, 0.7]
    assert all(n.t >= 2 and n.t < 4 for n in [lesson.notes[i] for i in s.scorer(0).active])


def test_auto_speed_up_steps_through_presets():
    s = Session(rock_beat(bars=4), speed=0.5, loop_bars=(1, 2), looping=True, auto_speed_up=True,
                speed_steps=[0.5, 0.75, 1.0, 1.25])
    _, speeds = play_loop(s, 4)
    assert speeds == [0.75, 1.0]  # stops at the target (normal) speed, never auto-jumps to max


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


# ---------- dynamics ----------

from kickhero.engine.lesson import classify_dynamics, Note  # noqa: E402
from kickhero.engine.scoring import judge_dynamic  # noqa: E402


def paradiddle(bars=2):
    """Sixteenth notes on the snare, the first of each group of four accented (lesson 7.4)."""
    return from_notes("pd", BPM, [(i * 0.125, "snare", 124 if i % 4 == 0 else 100) for i in range(16 * bars)],
                      bars=bars)


def test_classify_dynamics_relative_to_lane():
    les = paradiddle()
    assert [n.dyn for n in les.notes[:4]] == ["accent", "normal", "normal", "normal"]
    loud_lane = classify_dynamics([Note(i, "hihat", 120) for i in range(8)] + [Note(9, "hihat", 50)])
    assert {n.dyn for n in loud_lane[:8]} == {"normal"}       # every hit loud: nothing stands out as accent
    assert loud_lane[8].dyn == "ghost"


def test_judge_dynamic_adapts_to_players_level():
    assert judge_dynamic("accent", 85, normal_level=70) == "ok"         # quiet kit: 15 above normal is an accent
    assert judge_dynamic("accent", 75, normal_level=70) == "too_soft"
    assert judge_dynamic("accent", 121, normal_level=118) == "ok"       # hard hitter: ceiling still allows accents
    assert judge_dynamic("ghost", 45, normal_level=90) == "ok"
    assert judge_dynamic("ghost", 80, normal_level=90) == "too_loud"
    assert judge_dynamic("normal", 30, normal_level=90) is None


def play_dynamics(session, lesson, normal, accent):
    session.start(0.0)
    perf0 = session.count_in
    for n in lesson.notes:
        session.update(perf0 + n.t)
        session.hit(n.lane, perf0 + n.t, accent if n.dyn == "accent" else normal)
    return [e for e in session.update(perf0 + lesson.length + 1) if e[0] == "finished"][0][1]


def test_session_rates_dynamics_against_learned_level():
    les = paradiddle()
    good = play_dynamics(Session(les, rate_dynamics=True), les, normal=70, accent=90)
    assert good["dynamics"]["score"] >= 0.85 and good["accuracy"] >= 0.97  # first accent judged before level known
    flat = play_dynamics(Session(les, rate_dynamics=True), les, normal=70, accent=72)
    assert flat["dynamics"]["too_soft"] == 8 and flat["accuracy"] < good["accuracy"]
    assert flat["stars"] == 0 and good["stars"] >= 2  # all accents flat: no stars, however good the timing
    unrated = play_dynamics(Session(les), les, normal=70, accent=72)
    assert unrated["dynamics"] is None and unrated["accuracy"] == 1.0


def test_keyboard_hits_never_rate_dynamics():
    les = paradiddle()
    s = Session(les, rate_dynamics=True)
    s.start(0.0)
    j = s.hit("snare", s.count_in, velocity=0)
    assert j.grade == "perfect" and j.dynamic is None


# ---------- open hi-hat ----------

from kickhero.kit.mapping import hat_open  # noqa: E402


def open_and4(bars=2):
    """Eighth-note hi-hats with an open one on the "and" of 4 (course lesson 9.1)."""
    return from_notes("oh", BPM, [(i * 0.25, "hihat", 100, i % 8 == 7) for i in range(8 * bars)], bars=bars)


def play_hats(lesson, opened_for):
    s = Session(lesson)
    s.start(0.0)
    for n in lesson.notes:
        s.update(s.count_in + n.t)
        s.hit(n.lane, s.count_in + n.t, 100, opened_for(n))
    return [e for e in s.update(s.count_in + lesson.length + 1) if e[0] == "finished"][0][1]


def test_open_hihat_is_rated_when_the_kit_can_tell():
    les = open_and4()
    assert les.has_open_hats and sum(n.open for n in les.notes) == 2
    right = play_hats(les, lambda n: n.open)
    assert right["hihat"] == {"ok": 16, "open_it": 0, "close_it": 0, "score": 1.0} and right["accuracy"] == 1.0
    never_open = play_hats(les, lambda n: False)
    assert never_open["hihat"]["open_it"] == 2 and never_open["accuracy"] < 1.0
    assert never_open["accuracy"] >= 0.95 and never_open["stars"] == 2  # 14 of 16 right (87.5%) caps the stars
    always_open = play_hats(les, lambda n: True)
    assert always_open["hihat"]["close_it"] == 14
    no_pedal = play_hats(les, lambda n: None)  # kit can't tell: not rated, no penalty
    assert no_pedal["hihat"] is None and no_pedal["accuracy"] == 1.0
    plain = play_hats(rock_beat(), lambda n: True)  # lessons without open hats never rate it
    assert plain["hihat"] is None


def test_hat_open_from_kit_notes_and_pedal():
    assert hat_open(46) is True and hat_open(26) is True
    assert hat_open(42) is None                    # a kit that never sent an open note may have no pedal
    assert hat_open(42, kit_opens=True) is False
    assert hat_open(42, pedal=127) is False
    assert hat_open(99, pedal=10) is True and hat_open(99, pedal=120) is False  # custom note: pedal decides
    assert hat_open(99) is None


def test_muted_lanes_are_never_played_back():
    import time
    from types import SimpleNamespace

    import numpy as np

    from kickhero.engine.audio import AudioEngine
    from kickhero.engine.sounds import SoundBank

    les = rock_beat()
    eng = AudioEngine()
    eng.bank = SoundBank(eng.sr, "classic")
    eng.metronome, eng.guide_all = False, True
    eng.muted = {"hihat", "snare"}
    s = Session(les)
    s.start(time.perf_counter())  # the audio callback reads the real clock
    eng.session = s
    played = []
    eng._choke = lambda voices: played.extend(v[0] for v in voices)  # peek at the voices started
    out = np.zeros((eng.sr * 6, 2), np.float32)
    eng._callback(out, len(out), SimpleNamespace(outputBufferDacTime=0, currentTime=0), None)
    drums = eng.bank.drums
    assert any(x is drums["kick"] for x in played)
    assert not any(x is drums["hihat"] or x is drums["snare"] for x in played)
