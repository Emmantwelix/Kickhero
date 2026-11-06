import json

import pretty_midi
import pytest

from kickhero.engine.editing import VELOCITY, EditNote, Part, backup_path, is_backup, load_part
from kickhero.engine.lesson import load_midi

BPM = 120  # bar = 2 s, sixteenth = 0.125 s


def song(tmp_path, notes=((0.0, 36, 110), (0.5, 38, 105), (0.5, 42, 90), (1.0, 46, 95), (2.0, 36, 112)),
         shift=-0.3):
    folder = tmp_path / "Song"
    folder.mkdir()
    pm = pretty_midi.PrettyMIDI(initial_tempo=BPM)
    inst = pretty_midi.Instrument(program=0, is_drum=True)
    for t, pitch, v in notes:
        inst.notes.append(pretty_midi.Note(velocity=v, pitch=pitch, start=t, end=t + 0.05))
    pm.instruments.append(inst)
    mid = folder / "Song_drums.mid"
    pm.write(str(mid))
    (folder / "backing.ogg").write_bytes(b"")
    mid.with_suffix(".json").write_text(json.dumps({"title": "Song", "bpm": BPM, "shift": shift,
                                                    "backing": "backing.ogg"}), encoding="utf-8")
    return mid


def test_load_part_keeps_every_note(tmp_path):
    part = load_part(song(tmp_path))
    assert part.bpm == pytest.approx(BPM) and part.shift == -0.3 and part.title == "Song"
    assert [(n.lane, n.open) for n in part.notes] == [("kick", False), ("hihat", False), ("snare", False),
                                                      ("hihat", True), ("kick", False)]  # same time: top lane first
    assert part.bars == 2 and part.backing.name == "backing.ogg"


def test_add_remove_move_with_snapping_and_undo(tmp_path):
    part = load_part(song(tmp_path))
    n = part.add(part.snap(0.27, 16), "snare")
    assert n.t == pytest.approx(0.25) and part.dirty
    assert part.add(0.25, "snare") is None                       # no doubled hit
    (moved,) = part.move([n], dt=0.13, dlane=1, grid=16)         # snare -> next lane down (high tom)
    assert moved.t == pytest.approx(0.375) and moved.lane == "tom1"
    part.remove([moved])
    assert not any(m.lane == "tom1" for m in part.notes)
    part.undo()
    assert any(m.lane == "tom1" for m in part.notes)
    part.undo()
    part.undo()
    assert len(part.notes) == 5 and part.can_redo()
    part.redo()
    assert len(part.notes) == 6


def test_moving_onto_a_note_merges_them(tmp_path):
    part = load_part(song(tmp_path))
    kick2 = part.notes[-1]
    part.move([kick2], dt=-2.0)
    assert [n.t for n in part.notes if n.lane == "kick"] == [0.0]


def test_dynamics_drum_and_open_hat(tmp_path):
    part = load_part(song(tmp_path))
    snare = next(n for n in part.notes if n.lane == "snare")
    (ghost,) = part.set_velocity([snare], VELOCITY["ghost"])
    assert ghost.velocity == 45
    (tom,) = part.set_lane([ghost], "tom3")
    assert tom.lane == "tom3" and tom.midi_pitch() == 43
    hat = next(n for n in part.notes if n.lane == "hihat" and not n.open)
    (opened,) = part.set_open([hat], True)
    assert opened.open and opened.midi_pitch() == 46
    assert part.set_open([tom], True)[0].open is False            # only hi-hats open
    (closed,) = part.set_lane([opened], "ride")
    assert not closed.open


def test_copy_and_paste_bars_replaces_the_target(tmp_path):
    part = load_part(song(tmp_path))
    part.copy_bars(0, 0)
    pasted = part.paste_bars(1)
    assert len(pasted) == 4
    bar2 = sorted((round(n.t - 2.0, 3), n.lane) for n in part.notes if 2.0 <= n.t < 4.0)
    bar1 = sorted((round(n.t, 3), n.lane) for n in part.notes if n.t < 2.0)
    assert bar2 == bar1                                           # the old kick at 2.0 was replaced


def test_tempo_keeps_times_and_shift_keeps_audio_in_sync(tmp_path):
    part = load_part(song(tmp_path))
    times = [n.t for n in part.notes]
    part.set_bpm(90)
    assert [n.t for n in part.notes] == times and part.bar == pytest.approx(240 / 90)
    audio = [n.t + part.backing_offset for n in part.notes]        # where each note is in the song audio
    part.shift_all(0.25)
    assert [n.t + part.backing_offset for n in part.notes] == pytest.approx(audio)
    snare = next(n for n in part.notes if n.lane == "snare")       # now at 0.75 s
    part.bar_one_at(snare)
    assert next(n for n in part.notes if n.lane == "snare").t == pytest.approx(0.0)
    assert len(part.notes) == 4                                    # only the first kick was before it
    part.undo()
    part.undo()
    part.undo()
    assert part.bpm == pytest.approx(BPM) and part.shift == pytest.approx(-0.3)


def test_save_round_trip_backup_and_revert(tmp_path):
    mid = song(tmp_path)
    part = load_part(mid)
    part.add(1.5, "crash", VELOCITY["accent"])
    part.set_bpm(100)
    part.shift_all(0.125)
    part.save()
    assert not part.dirty and part.has_backup() and is_backup(backup_path(mid))
    lesson = load_midi(mid)
    assert lesson.bpm == pytest.approx(100)
    assert lesson.backing_offset == pytest.approx(-(-0.3 + 0.125))
    crash = next(n for n in lesson.notes if n.lane == "crash")
    assert crash.t == pytest.approx(1.625, abs=1e-3) and crash.velocity == 124
    assert [n.open for n in lesson.notes if n.lane == "hihat"] == [False, True]
    meta = json.loads(mid.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["backing"] == "backing.ogg" and "edited" in meta

    part.add(3.0, "snare")
    part.save()                                                    # the backup stays the converted original
    assert load_midi(backup_path(mid)).bpm == pytest.approx(BPM)
    reverted = part.revert()
    assert reverted.bpm == pytest.approx(BPM) and len(reverted.notes) == 5 and reverted.shift == -0.3


def test_new_notes_get_the_lane_default_pitch():
    assert EditNote(0, "snare").midi_pitch() == 38
    assert EditNote(0, "hihat", open=True).midi_pitch() == 46
    assert EditNote(0, "hihat", pitch=46, open=False).midi_pitch() == 42  # closed now: not the open note
    assert EditNote(0, "kick", pitch=35).midi_pitch() == 35


def test_empty_part_has_one_bar(tmp_path):
    assert Part(tmp_path / "x.mid", [], 100).bars == 1


def test_load_part_merges_hits_like_practice(tmp_path):
    mid = song(tmp_path, notes=((0.0, 42, 80), (0.012, 46, 100), (0.5, 38, 100), (0.505, 38, 60)))
    part = load_part(mid)
    assert len(part.notes) == len(load_midi(mid).notes) == 2
    hat = part.notes[0]
    assert hat.open and hat.velocity == 100


def test_paste_replaces_hits_right_next_to_the_pasted_bars(tmp_path):
    mid = song(tmp_path, notes=((0.0, 36, 100), (3.99, 36, 100), (4.01, 36, 100)))  # kicks hugging bar 3
    part = load_part(mid)
    part.copy_bars(0, 0)
    part.paste_bars(2)                    # pastes a kick at 4.0, between the two
    assert [round(n.t, 2) for n in part.notes] == [0.0, 4.0]
    part.save()
    assert len(load_midi(mid).notes) == len(part.notes)
