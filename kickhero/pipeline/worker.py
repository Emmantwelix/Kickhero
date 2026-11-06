"""Runs song conversions in a background process and reports progress as Qt signals.

The conversion runs in its own process (heavy PyTorch work, and it can be stopped instantly).
From source that's `python -m kickhero.pipeline.song2drums`; in the packaged app the exe is
started again with `--pipeline` (see app.main).
"""

import os
import re
import sys

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from ..settings import REPO_ROOT

STEP_NAMES = {1: "Separating the drums from the song", 2: "Splitting the kit", 3: "Finding the tempo",
              4: "Writing the drum part"}

# Conversion options (stored in settings["convert"]) -> song2drums.py flags
DEFAULT_OPTIONS = {
    "align": True, "split_toms": True, "quantize": 0,
    "sensitivity": 0.07, "gate": -30.0, "ref_gate": -36.0, "bleed_db": 10.0, "min_gap": 30.0,
    "hihat_open_ms": 150.0,
}


def build_args(songs, output, options):
    o = dict(DEFAULT_OPTIONS, **(options or {}))
    args = [str(s) for s in songs] + ["-o", str(output), "--force"]
    for key in ("sensitivity", "gate", "ref_gate", "bleed_db", "min_gap", "hihat_open_ms"):
        args += ["--" + key.replace("_", "-"), f"{float(o[key]):g}"]
    if o.get("bpm"):  # chosen per batch, never stored in the settings
        args += ["--bpm", f"{float(o['bpm']):g}"]
    if o["quantize"]:
        args += ["--quantize", str(int(o["quantize"]))]
    if not o["align"]:
        args.append("--no-align")
    if not o["split_toms"]:
        args.append("--no-split-toms")
    return args


def pipeline_command(args):
    if getattr(sys, "frozen", False):
        return sys.executable, ["--pipeline", *args]
    return sys.executable, ["-u", "-m", "kickhero.pipeline.song2drums", *args]


class ConvertJob(QObject):
    status = Signal(str)          # human-readable "Song 1 of 3: ... - Splitting the kit 40%"
    fraction = Signal(float)      # overall progress 0..1
    log = Signal(str)             # every output line
    song_done = Signal(str, bool)  # song name, success
    finished = Signal(int, int)   # songs converted, songs failed

    def __init__(self, songs, output, options=None, parent=None):
        super().__init__(parent)
        self.songs = list(songs)
        self.total = len(self.songs)
        self.done = self.failed = self.step = 0
        self.name = ""
        self._buf = ""
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUNBUFFERED", "1")
        self.proc.setProcessEnvironment(env)
        if not getattr(sys, "frozen", False):
            self.proc.setWorkingDirectory(str(REPO_ROOT))
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._finished)
        self.program, self.args = pipeline_command(build_args(self.songs, output, options))

    def start(self):
        self.status.emit("Starting...")
        self.proc.start(self.program, self.args)

    def stop(self):
        if self.proc.state() != QProcess.NotRunning:
            self.proc.kill()

    @property
    def running(self):
        return self.proc.state() != QProcess.NotRunning

    def _read(self):
        self._buf += bytes(self.proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        parts = re.split(r"[\r\n]", self._buf)
        self._buf = parts.pop()  # keep an incomplete last line
        for line in parts:
            if line.strip():
                self._line(line.rstrip())

    def _line(self, line):
        if "%|" in line:  # progress bar from the separation models
            m = re.search(r"(\d+)%\|", line)
            if m and self.name:
                pct = int(m.group(1))
                self._status(f"{STEP_NAMES.get(self.step, 'Working')}... {pct}%")
                if self.step in (1, 2):  # the two slow steps: count their progress
                    self._fraction(self.step - 1 + pct / 100)
            return
        self.log.emit(line)
        if m := re.match(r"=== (.*) ===$", line):
            self.name, self.step = m.group(1), 0
            self._status("Starting...")
        elif m := re.match(r"\[(\d)/4\]", line):
            self.step = int(m.group(1))
            self._status(STEP_NAMES[self.step] + "...")
            self._fraction(self.step - 1)
        elif line.startswith("Done in"):
            self.done += 1
            self._fraction(0, song_finished=True)
            self.song_done.emit(self.name, True)
        elif line.startswith("!! "):
            self.done += 1
            self.failed += 1
            self._fraction(0, song_finished=True)
            self.song_done.emit(self.name, False)

    def _status(self, text):
        n = min(self.done + 1, self.total)
        self.status.emit(f"Song {n} of {self.total}: {self.name}  -  {text}")

    def _fraction(self, steps_in_song, song_finished=False):
        # steps 1 and 2 are ~95% of the time; weight the song as 2 units
        per_song = 0.0 if song_finished else min(steps_in_song, 2) / 2
        self.fraction.emit(min(1.0, (self.done + per_song) / max(1, self.total)))

    def _finished(self, code, _status):
        if self._buf.strip():
            self._line(self._buf.strip())
        converted = self.done - self.failed
        self.finished.emit(converted, self.total - converted)  # a crash or Stop counts the rest as failed
