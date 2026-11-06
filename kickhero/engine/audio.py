"""Audio output: metronome, guide notes, pad sounds and the backing track, all on the perf_counter clock.

The output callback works out the perf_counter time at which its buffer will actually reach the
speakers (PortAudio's DAC time, converted to perf_counter), then renders every click and note that
falls inside that buffer at the exact sample. So sound lines up with the display and with MIDI hits.
"""

import threading
import time

import numpy as np

from ..lanes import OPEN_HAT
from .sounds import SoundBank

CHOKE_FADE_S = 0.008  # a closed hi-hat cuts a ringing open hi-hat off over this long
RESYNC_S = 0.015  # backing track jumps to the transport position only if they drift further apart than this


def _pick_device():
    """Prefer WASAPI (lowest latency on Windows); fall back to the system default."""
    import sounddevice as sd

    try:
        for i, api in enumerate(sd.query_hostapis()):
            if "WASAPI" in api["name"] and api["default_output_device"] >= 0:
                return api["default_output_device"]
    except Exception:
        pass
    return None


class AudioEngine:
    def __init__(self, kit="classic", custom_sounds=None):
        self.kit = kit
        self.custom_sounds = custom_sounds or {}
        self.session = None          # engine.session.Session currently playing, or None
        self.metronome = True
        self.guide_all = False       # also play the notes of lanes you are practising
        self.muted = set()           # lanes never played back (the speaker buttons on the practice screen)
        self.volume = {"metronome": 0.6, "guide": 0.5, "pads": 0.8, "backing": 0.8}
        self.backing = None          # (mono float32 array at self.sr, offset seconds)
        self.backing_on = True
        self.error = None
        self._voices = []            # [samples, position, gain]
        self._pending = []           # pad sounds to start ASAP: (samples, gain)
        self._lock = threading.Lock()
        self._stream = None
        self.sr = 48000
        self.bank = None
        self.output_latency = 0.0
        self._frames = 0             # samples rendered since the stream started
        self._clock_base = None      # perf_counter time of sample 0 (averaged)
        self._clock_n = 0
        self._backing_pos = None     # next backing-track sample to play

    def start(self):
        try:
            import sounddevice as sd

            device = _pick_device()
            sr = int(sd.query_devices(device, "output")["default_samplerate"]) if device is not None else 48000
            self.sr = sr
            self.bank = SoundBank(sr, self.kit, self.custom_sounds)
            self._stream = sd.OutputStream(device=device, samplerate=sr, channels=2, dtype="float32",
                                           blocksize=256, latency="low", callback=self._callback)
            self._stream.start()
            self.output_latency = self._stream.latency
        except Exception as e:  # no audio device: the app still works, silently
            self.error = str(e)
            self.bank = self.bank or SoundBank(self.sr, self.kit, self.custom_sounds)

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def set_kit(self, kit, custom_sounds=None):
        """Switch drum sounds. Returns {lane: error} for custom samples that couldn't be loaded."""
        self.kit, self.custom_sounds = kit, custom_sounds or {}
        bank = SoundBank(self.sr, kit, self.custom_sounds)
        self.bank = bank  # the audio thread picks up the new bank on its next buffer
        return bank.errors

    def play_pad(self, lane, velocity):
        """Play a drum sound right away (pad sounds for kits without their own sound module).
        lane can also be OPEN_HAT."""
        if self.bank:
            with self._lock:
                self._pending.append((self.bank.drums[lane], self.volume["pads"] * (velocity / 127) ** 1.5))

    def play_click(self, accent=True):
        if self.bank:
            with self._lock:
                self._pending.append((self.bank.clicks[accent], self.volume["metronome"]))

    def load_backing(self, path, offset):
        """Load a play-along track (stereo, resampled to the output rate). path=None clears it."""
        self.backing = None
        self._backing_pos = None
        if path is None:
            return
        import soundfile as sf

        y, sr = sf.read(str(path), dtype="float32", always_2d=True)
        if y.shape[1] == 1:
            y = np.repeat(y, 2, axis=1)
        y = y[:, :2]
        if sr != self.sr:
            import soxr  # high-quality resampler (installed with librosa)

            y = soxr.resample(y, sr, self.sr).astype(np.float32)
        self.backing = (np.ascontiguousarray(y), offset)

    # ---------- audio thread ----------

    def _buffer_time(self, t, frames):
        """perf_counter time at which this buffer's first sample reaches the speakers.

        PortAudio's per-buffer DAC timestamps jitter by several ms (and WASAPI delivers buffers in
        bursts), so instead we count samples, which is exact and continuous, and map the sample
        count onto perf_counter with a slowly averaged offset."""
        now = time.perf_counter()
        dac = t.outputBufferDacTime
        measured = dac + (now - t.currentTime) if dac > 0 else now + self.output_latency
        n0 = self._frames
        self._frames += frames
        est = measured - n0 / self.sr
        self._clock_n += 1
        if self._clock_base is None:
            self._clock_base = est
        else:  # running mean at first, then a slow average that still follows clock drift
            self._clock_base += (est - self._clock_base) / min(self._clock_n, 400)
        return self._clock_base + n0 / self.sr

    def _callback(self, out, frames, t, status):
        p0 = self._buffer_time(t, frames)
        p1 = p0 + frames / self.sr
        mix = np.zeros(frames, dtype=np.float32)

        with self._lock:
            pending, self._pending = self._pending, []
        voices = self._voices
        for samples, gain in pending:
            voices.append([samples, -0, gain])

        s = self.session
        if s is not None and s.started and not s.paused:
            u0, u1 = s.u_at(p0), s.u_at(p1)
            span = (u1 - u0) or 1e-9
            if self.metronome:
                for u, accent in s.beats_between(u0, u1):
                    voices.append([self.bank.clicks[accent], -int((u - u0) / span * frames),
                                   self.volume["metronome"]])
            for u, i, n, p in s.notes_between(u0, u1):
                if (self.guide_all or n.lane not in s.lanes) and n.lane not in self.muted:
                    sound = OPEN_HAT if n.open else n.lane
                    voices.append([self.bank.drums[sound], -int((u - u0) / span * frames),
                                   self.volume["guide"] * (n.velocity / 127) ** 1.5])
            backing = self._mix_backing(s, u0, frames)
        else:
            backing = None
            self._backing_pos = None

        self._choke(voices)
        alive = []
        for v in voices:
            samples, pos, gain = v
            start = max(0, -pos)            # negative pos = starts later inside this buffer
            src = max(0, pos)
            n = min(frames - start, len(samples) - src)
            if n > 0:
                mix[start:start + n] += samples[src:src + n] * gain
            v[1] = pos + frames
            if v[1] < len(samples):
                alive.append(v)
        self._voices = alive
        out[:, 0] = mix
        out[:, 1] = mix
        if backing is not None:
            out += backing
        np.clip(out, -1, 1, out=out)

    def _choke(self, voices):
        """A closed hi-hat stops a ringing open hi-hat, like closing the pedal on a real kit.
        A voice's position is negative while it waits to start inside this buffer."""
        drums = self.bank.drums
        closes = [max(0, -v[1]) for v in voices if v[0] is drums["hihat"]]
        if not closes:
            return
        fade = int(CHOKE_FADE_S * self.sr)
        for v in voices:
            if v[0] is not drums[OPEN_HAT]:
                continue
            start = max(0, -v[1])
            later = [c for c in closes if c > start]
            if later:
                cut = v[1] + min(later) + fade  # sample index in the open hat where it has faded out
                x = v[0][:max(0, cut)].copy()
                k = min(fade, len(x))
                x[len(x) - k:] *= np.linspace(1, 0, k, dtype=np.float32)
                v[0] = x

    def _mix_backing(self, s, u0, frames):
        """The drumless song for this buffer (stereo), or None. Only at 100% speed (slowed audio needs
        time-stretching). Uses lesson time, so loops jump back with the notes and the count-in plays
        the bar before.

        Reads on continuously from the previous buffer; only re-syncs to the transport position when
        they disagree by more than RESYNC_S (start, loop wrap, speed change, wait-mode pause)."""
        if self.backing is None or not self.backing_on or abs(s.speed - 1.0) > 1e-3:
            self._backing_pos = None
            return None
        samples, offset = self.backing
        t0 = s.lesson_time(u0) if s.looping else u0
        target = int(round((t0 + offset) * self.sr))
        pos = self._backing_pos
        if pos is None or abs(target - pos) > RESYNC_S * self.sr:
            pos = target
        self._backing_pos = pos + frames
        if pos + frames <= 0 or pos >= len(samples):
            return None
        buf = np.zeros((frames, 2), dtype=np.float32)
        a, b = max(pos, 0), min(pos + frames, len(samples))
        buf[a - pos:b - pos] = samples[a:b] * self.volume["backing"]
        return buf
