import io
import struct

import numpy as np
import soundfile as sf

from kickhero.engine.sounds import KITS, CUSTOM, SoundBank, load_sample, match_kit_folder, read_audio
from kickhero.lanes import LANES, OPEN_HAT

SR = 48000


def tone(path, level, seconds=0.3, sr=44100):
    t = np.arange(int(seconds * sr)) / sr
    sf.write(str(path), (level * np.sin(2 * np.pi * 200 * t) * np.exp(-t * 8)).astype("float32"), sr)


def test_every_builtin_kit_has_every_drum():
    for kit in KITS:
        bank = SoundBank(SR, kit)
        for lane in LANES:
            x = bank.drums[lane]
            assert x.dtype == np.float32 and len(x) > SR * 0.03, (kit, lane)
            assert 0.5 < np.max(np.abs(x)) <= 0.81
    assert not np.allclose(SoundBank(SR, "808").drums["kick"][:2000], SoundBank(SR, "classic").drums["kick"][:2000])


def test_kit_folder_matching(tmp_path):
    kit = tmp_path / "My Kit"
    kit.mkdir()
    for i, level in enumerate((0.1, 0.9, 0.4), 1):           # velocity layers: #2 is the hardest hit
        tone(kit / f"Kick 1 Funk #{i}.wav", level)
    tone(kit / "Kick 2 Funk #1.wav", 1.0)                      # a second kick family is ignored
    tone(kit / "Snare Rim #1.wav", 1.0)                         # rim shot loses to the plain snare
    tone(kit / "Snare Hit #1.wav", 0.5)
    tone(kit / "HH Open #1.wav", 1.0)
    tone(kit / "HH Closed #1.wav", 0.5)
    tone(kit / "Ride #1.wav", 0.5)
    for size in (16, 8, 12):                                    # toms named by size, in no order
        tone(kit / f"{size} inch tom.wav", 0.5)
    found = {lane: p.name for lane, p in match_kit_folder(tmp_path).items()}
    assert found["kick"] == "Kick 1 Funk #2.wav"
    assert found["snare"] == "Snare Hit #1.wav"
    assert found["hihat"] == "HH Closed #1.wav"
    assert (found["tom1"], found["tom2"], found["tom3"]) == ("8 inch tom.wav", "12 inch tom.wav", "16 inch tom.wav")
    assert "crash" not in found


def test_custom_bank_falls_back_for_missing_files(tmp_path):
    tone(tmp_path / "k.wav", 0.5)
    bank = SoundBank(SR, CUSTOM, {"kick": str(tmp_path / "k.wav"), "snare": str(tmp_path / "missing.wav")})
    assert "snare" in bank.errors and "kick" not in bank.errors
    assert len(bank.drums["kick"]) == len(load_sample(tmp_path / "k.wav", SR))


def test_reads_wav_wrapping_ogg_vorbis(tmp_path):
    """Some sample libraries store Ogg Vorbis inside a WAV (format tag 0x674F); libsndfile rejects it."""
    buf = io.BytesIO()
    t = np.arange(22050) / 44100
    with sf.SoundFile(buf, "w", 44100, 1, format="OGG", subtype="VORBIS") as f:
        f.write((0.5 * np.sin(2 * np.pi * 300 * t)).astype("float32"))
    ogg = buf.getvalue()
    fmt = struct.pack("<HHIIHH", 0x674F, 1, 44100, 44100 * 2, 2, 16)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(ogg)) + ogg
    path = tmp_path / "wrapped.wav"
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    y, sr = read_audio(path)
    assert sr == 44100 and abs(len(y) - 22050) < 2000 and np.max(np.abs(y)) > 0.4


def test_open_hihat_sound_rings_longer_and_comes_from_folders(tmp_path):
    for kit in KITS:
        bank = SoundBank(SR, kit)
        assert len(bank.drums[OPEN_HAT]) > 3 * len(bank.drums["hihat"]), kit
    tone(tmp_path / "HH Closed #1.wav", 0.5)
    tone(tmp_path / "HH Open #1.wav", 0.4)
    tone(tmp_path / "HH Open #2.wav", 0.9)
    found = match_kit_folder(tmp_path)
    assert found["hihat"].name == "HH Closed #1.wav" and found[OPEN_HAT].name == "HH Open #2.wav"


def test_closed_hihat_chokes_a_ringing_open_one():
    from kickhero.engine.audio import AudioEngine

    eng = AudioEngine()
    eng.bank = SoundBank(SR, "classic")
    open_hat, closed = eng.bank.drums[OPEN_HAT], eng.bank.drums["hihat"]
    voices = [[open_hat, 1000, 1.0], [closed, -200, 1.0]]  # open rang for 1000 samples; closed starts 200 in
    eng._choke(voices)
    assert 1200 < len(voices[0][0]) <= 1200 + int(0.01 * SR) and voices[0][0][-1] == 0
    later_open = [[open_hat, -300, 1.0], [closed, -200, 1.0]]  # an open hit after the closed one keeps ringing
    eng._choke(later_open)
    assert later_open[0][0] is open_hat
