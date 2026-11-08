"""Adding a song from a ready-made MIDI file: name it, and optionally pick a recording to play along with."""

from pathlib import Path

from PySide6.QtWidgets import (QButtonGroup, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QRadioButton, QVBoxLayout)

from ..lanes import LANE_NAMES, LANES, NOTE_TO_LANE
from ..pipeline.midi_import import read_drums, song_name
from ..pipeline.song2drums import SONG_EXTS
from .fitting import ElidedLabel

BAD_NAME = '<>:"/\\|?*'


class MidiImportDialog(QDialog):
    """Raises MidiImportError (from read_drums) if the file has no usable drum part."""

    def __init__(self, midi_path, parent=None):
        super().__init__(parent)
        self.midi_path = Path(midi_path)
        notes, info = read_drums(self.midi_path)
        self.audio = None
        self.setWindowTitle("Add MIDI file")
        self.setFixedWidth(560)  # a set width, so the height can follow the wrapped text
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(10)
        lay.addWidget(QLabel("Add a song from a MIDI file", objectName="h2"))
        used = {NOTE_TO_LANE[n[2]] for n in notes}
        drums = ", ".join(LANE_NAMES[lane] for lane in LANES if lane in used)
        about = f"{self.midi_path.name}  ·  {len(notes)} drum notes  ·  {info['bpm']:.0f} BPM  ·  {drums}"
        lay.addWidget(ElidedLabel(about, objectName="muted"))
        if info["tempo_changes"]:
            lay.addWidget(QLabel("The tempo changes during this file.", objectName="muted"))

        lay.addWidget(QLabel("Song name", objectName="group"))
        self.name = QLineEdit(song_name(self.midi_path))
        self.name.textChanged.connect(self._update)
        lay.addWidget(self.name)

        lay.addSpacing(6)
        lay.addWidget(QLabel("Play along with", objectName="group"))
        self.only = QRadioButton("The drum part only (ready straight away)")
        self.with_song = QRadioButton("The song itself: pick its audio file")
        group = QButtonGroup(self)
        for b in (self.only, self.with_song):
            group.addButton(b)
            lay.addWidget(b)
        self.only.setChecked(True)
        row = QHBoxLayout()
        row.setContentsMargins(26, 0, 0, 0)
        self.pick = QPushButton("Choose song file...")
        self.pick.clicked.connect(self._choose)
        self.picked = ElidedLabel(objectName="muted")
        row.addWidget(self.pick)
        row.addWidget(self.picked, 1)
        lay.addLayout(row)
        self.explain = QLabel(objectName="muted", wordWrap=True)
        lay.addWidget(self.explain)
        group.buttonToggled.connect(self._update)

        lay.addSpacing(6)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton("Add song")
        self.ok.setObjectName("primary")
        self.ok.setDefault(True)
        self.ok.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(self.ok)
        lay.addLayout(buttons)
        self._update()

    def showEvent(self, e):
        super().showEvent(e)
        self._update()  # sized again now its real width is known, so no text is squeezed

    def _choose(self):
        exts = " ".join(f"*{e}" for e in sorted(SONG_EXTS))
        start = str(self.audio.parent if self.audio else Path.home() / "Music")
        path, _ = QFileDialog.getOpenFileName(self, "The song's audio file", start, f"Audio ({exts})")
        if path:
            self.audio = Path(path)
            self.with_song.setChecked(True)
        self._update()

    def _update(self, *_):
        song = self.with_song.isChecked()
        self.picked.setText(self.audio.name if self.audio else "No file chosen")
        if song:
            self.explain.setText("The drums are taken out of the song (a few minutes, like converting a song), "
                                 "then the MIDI's notes are lined up with the drums in the recording. "
                                 "Use the same version of the song the MIDI was made from.")
        else:
            self.explain.setText("The drum part is put on one steady tempo. You hear the drum sounds and the "
                                 "metronome, but no song.")
        self.explain.setMinimumHeight(self.explain.heightForWidth(self.width() - 44))  # never clip the text
        self.adjustSize()
        self.ok.setText("Add and line up" if song else "Add song")
        self.ok.setEnabled(bool(self.song_name()) and (not song or self.audio is not None))

    def song_name(self):
        name = "".join(c for c in self.name.text() if c not in BAD_NAME).strip().rstrip(".")
        return name

    def audio_path(self):
        return self.audio if self.with_song.isChecked() else None
