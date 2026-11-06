"""Conversion settings dialog: the converter's options, explained in plain words."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QSlider, QVBoxLayout)

from ..pipeline.worker import DEFAULT_OPTIONS

# (key, title, from, to, step, unit, explanation)
TUNING = [
    ("sensitivity", "Hit sensitivity", 0.02, 0.20, 0.01, "",
     "Left = more hits. Go left if soft notes (ghost notes, light hi-hats) are missing, right if you get "
     "notes that weren't played."),
    ("gate", "Quiet-hit cutoff", -60, -10, 1, "dB",
     "Ignore hits this much quieter than the loudest hit on the same drum. Left keeps quieter hits."),
    ("ref_gate", "Leakage cutoff", -60, -20, 1, "dB",
     "Ignore hits this much quieter than the loudest sound in the whole kit. Removes phantom cymbal and tom "
     "hits that are really other drums leaking through. Right removes more."),
    ("bleed_db", "Tom leakage filter", 0, 30, 1, "dB",
     "Drop a tom hit that lands on a kick or snare hit at least this much louder. 0 = off. Raise it if real "
     "tom fills go missing."),
    ("min_gap", "Shortest gap", 10, 100, 1, "ms",
     "Hits on one drum closer than this become one hit. Lower for fast rolls and flams, raise if single hits "
     "come out doubled."),
    ("hihat_open_ms", "Open hi-hat length", 0, 400, 10, "ms",
     "Hi-hat hits ringing longer than this become open hi-hat. 0 = all closed."),
]
GRIDS = [("Off (keep the natural feel)", 0), ("1/8 notes", 8), ("1/16 notes", 16), ("1/32 notes", 32)]


class ConvertSettingsDialog(QDialog):
    def __init__(self, options, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Conversion settings")
        self.setMinimumWidth(620)
        self.values = dict(DEFAULT_OPTIONS, **(options or {}))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(10)
        lay.addWidget(QLabel("How songs are turned into drum parts", objectName="h2"))
        lay.addWidget(QLabel("The defaults work for most songs. Change them if a converted song has missing or "
                             "extra notes, then convert it again.", objectName="muted", wordWrap=True))

        self.align = QCheckBox("Start the groove on bar 1 (line beat 1 up with the bar lines)")
        self.split = QCheckBox("Split toms into high / mid / floor tom")
        self.grid = QComboBox()
        self.grid.addItems([g for g, _ in GRIDS])
        lay.addWidget(self.align)
        lay.addWidget(self.split)
        row = QHBoxLayout()
        row.addWidget(QLabel("Snap the saved MIDI to a grid:"))
        row.addWidget(self.grid)
        row.addStretch()
        lay.addLayout(row)
        lay.addWidget(QLabel("(Practice can snap notes by itself, so \"Off\" is usually best here.)",
                             objectName="muted"))

        g = QGridLayout()
        g.setHorizontalSpacing(12)
        self.sliders = {}
        r = 0
        for key, title, lo, hi, step, unit, text in TUNING:
            t = QLabel(title)
            t.setStyleSheet("font-weight: 600;")
            s = QSlider(Qt.Horizontal)
            s.setRange(round(lo / step), round(hi / step))
            val = QLabel()
            val.setFixedWidth(64)
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            s.valueChanged.connect(lambda v, val=val, step=step, unit=unit:
                                   val.setText(f"{round(v * step, 2):g} {unit}".strip()))
            self.sliders[key] = (s, step)
            g.addWidget(t, r, 0)
            g.addWidget(s, r, 1)
            g.addWidget(val, r, 2)
            hint = QLabel(text, objectName="muted", wordWrap=True)
            g.addWidget(hint, r + 1, 0, 1, 3)
            r += 2
        lay.addLayout(g)

        buttons = QHBoxLayout()
        reset = QPushButton("Reset to defaults")
        reset.clicked.connect(lambda: self._load(DEFAULT_OPTIONS))
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Save")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        buttons.addWidget(reset)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        lay.addLayout(buttons)
        self._load(self.values)

    def _load(self, o):
        self.align.setChecked(o["align"])
        self.split.setChecked(o["split_toms"])
        self.grid.setCurrentIndex([v for _, v in GRIDS].index(o["quantize"]) if o["quantize"] in (0, 8, 16, 32) else 0)
        for key, (s, step) in self.sliders.items():
            s.setValue(round(o[key] / step))
            s.valueChanged.emit(s.value())

    def result_options(self):
        out = {"align": self.align.isChecked(), "split_toms": self.split.isChecked(),
               "quantize": GRIDS[self.grid.currentIndex()][1]}
        for key, (s, step) in self.sliders.items():
            out[key] = round(s.value() * step, 2)
        return out
