"""Conversion options, explained in plain words.

Shown when songs are added (with a per-batch tempo choice) and from the Conversion settings button.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QPushButton, QRadioButton, QScrollArea, QSlider, QVBoxLayout,
                               QWidget)

from ..engine.meter import COMMON_METERS, parse_meter
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
# Quick fixes for a wrongly detected tempo: the usual mistakes are double, half, or a triplet feel (x4/3)
TEMPO_FIXES = [("½×", 0.5), ("¾×", 0.75), ("1½×", 1.5), ("2×", 2.0)]
MAX_LISTED = 6


class ConvertSettingsDialog(QDialog):
    """With `songs` it asks how to convert them (tempo + options); without, it edits the saved defaults.
    `detected_bpm` (converting a song again) offers one-click fixes for the tempo found last time."""

    def __init__(self, options, parent=None, songs=None, detected_bpm=None, meter=None):
        super().__init__(parent)
        self.songs = list(songs or [])
        self.setWindowTitle("Convert songs" if self.songs else "Conversion settings")
        self.setMinimumWidth(620)
        self.setSizeGripEnabled(True)
        self.values = dict(DEFAULT_OPTIONS, **(options or {}))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(10)
        if self.songs:
            n = len(self.songs)
            lay.addWidget(QLabel(f"Convert {n} song{'s' if n != 1 else ''}", objectName="h2"))
            names = [p.stem for p in self.songs[:MAX_LISTED]]
            if n > MAX_LISTED:
                names.append(f"... and {n - MAX_LISTED} more")
            lay.addWidget(QLabel("\n".join(names), objectName="muted", wordWrap=True))
            lay.addWidget(self._tempo_box(detected_bpm, meter))
        else:
            lay.addWidget(QLabel("How songs are turned into drum parts", objectName="h2"))
            lay.addWidget(QLabel("The defaults work for most songs. Change them if a converted song has missing or "
                                 "extra notes, then convert it again.", objectName="muted", wordWrap=True))

        self.more_btn = QPushButton()
        self.more_btn.setCheckable(True)
        self.more_btn.setStyleSheet("text-align: left;")
        self.more_btn.toggled.connect(self._show_more)
        if self.songs:
            lay.addWidget(self.more_btn)
        self.more = QWidget()
        more = QVBoxLayout(self.more)
        more.setContentsMargins(0, 0, 14, 0)  # keep text clear of the scrollbar
        more.setSpacing(10)
        # the fine-tuning list is taller than small screens: it scrolls, and the dialog never outgrows the screen
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.more)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        self.more.setAutoFillBackground(False)
        self.scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        lay.addWidget(self.scroll, 1)

        self.align = QCheckBox("Start the groove on bar 1 (line beat 1 up with the bar lines)")
        self.split = QCheckBox("Split toms into high / mid / floor tom")
        self.grid = QComboBox()
        self.grid.addItems([g for g, _ in GRIDS])
        more.addWidget(QLabel("BAR LINES AND DRUMS", objectName="group"))
        more.addWidget(self.align)
        more.addWidget(self.split)
        row = QHBoxLayout()
        row.addWidget(QLabel("Snap the saved MIDI to a grid"))
        row.addWidget(self.grid)
        row.addStretch()
        more.addLayout(row)
        more.addWidget(QLabel("Practice can snap notes by itself, so \"Off\" is usually best here.",
                              objectName="caption", wordWrap=True))
        more.addSpacing(8)
        more.addWidget(QLabel("FINDING THE HITS", objectName="group"))

        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(4)
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
            hint = QLabel(text, objectName="caption", wordWrap=True)
            hint.setContentsMargins(0, 0, 0, 8)
            g.addWidget(hint, r + 1, 0, 1, 3)
            r += 2
        more.addLayout(g)

        buttons = QHBoxLayout()
        reset = QPushButton("Reset to defaults", objectName="flat")
        reset.clicked.connect(lambda: self._load(DEFAULT_OPTIONS))
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Convert" if self.songs else "Save")
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        buttons.addWidget(reset)
        if self.songs:
            buttons.addWidget(QLabel("Fine-tuning is remembered for next time.", objectName="muted"))
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        lay.addLayout(buttons)
        self._load(self.values)
        self.more_btn.setChecked(not self.songs)
        self._show_more(not self.songs)

    def _tempo_box(self, detected_bpm, meter=None):
        box = QFrame(objectName="card")
        g = QGridLayout(box)
        g.setContentsMargins(14, 10, 14, 12)
        t = QLabel("Tempo")
        t.setStyleSheet("font-weight: 600;")
        g.addWidget(t, 0, 0, 1, 4)
        self.auto_bpm = QRadioButton("Detect it automatically")
        self.manual_bpm = QRadioButton("I know it:")
        group = QButtonGroup(box)
        group.addButton(self.auto_bpm)
        group.addButton(self.manual_bpm)
        self.bpm = QDoubleSpinBox(decimals=1, minimum=30, maximum=300)
        self.bpm.setValue(round(detected_bpm, 1) if detected_bpm else 120)
        self.bpm.setFixedWidth(100)
        self.manual_bpm.toggled.connect(self.bpm.setEnabled)
        self.auto_bpm.setChecked(True)
        self.bpm.setEnabled(False)
        g.addWidget(self.auto_bpm, 1, 0, 1, 4)
        g.addWidget(self.manual_bpm, 2, 0)
        g.addWidget(self.bpm, 2, 1)
        g.addWidget(QLabel("BPM"), 2, 2)
        sig = QHBoxLayout()
        sig.addWidget(QLabel("Time signature:"))
        self.meter = QComboBox(editable=True)
        self.meter.addItems(COMMON_METERS)
        self.meter.setCurrentText(parse_meter(meter) if meter else "4/4")
        self.meter.setFixedWidth(90)
        self.meter.setToolTip("Most songs are 4/4. Pick 3/4 for a waltz, 6/8 or 12/8 for a swaying feel; "
                              "type any other, like 7/8. It can't be detected, and can be changed later in the editor")
        sig.addWidget(self.meter)
        sig.addStretch()
        g.addLayout(sig, 5, 0, 1, 4)
        if detected_bpm:
            fixes = QHBoxLayout()
            fixes.addWidget(QLabel(f"Found last time: {detected_bpm:.0f} BPM.  Try:", objectName="muted"))
            for text, factor in TEMPO_FIXES:
                b = QPushButton(f"{text}  {detected_bpm * factor:.0f}")
                b.clicked.connect(lambda _=False, v=detected_bpm * factor: self._pick_bpm(v))
                fixes.addWidget(b)
            fixes.addStretch()
            g.addLayout(fixes, 3, 0, 1, 4)
        g.setColumnStretch(3, 1)
        many = " It is used for every song in this list." if len(self.songs) > 1 else ""
        g.addWidget(QLabel("Set it yourself if the detected tempo comes out wrong (e.g. double, half, or 3/4 of it "
                           "for songs with a swung or triplet feel)." + many, objectName="muted", wordWrap=True),
                    4, 0, 1, 4)
        return box

    def _pick_bpm(self, value):
        self.manual_bpm.setChecked(True)
        self.bpm.setValue(round(value, 1))

    def _show_more(self, on):
        self.scroll.setVisible(on)
        self.more_btn.setText(("▾" if on else "▸") + "  Fine-tuning (missing or extra notes, grid, toms)")
        screen = (self.screen() or self.parentWidget().screen()).availableGeometry()
        self.setMaximumHeight(screen.height() - 40)
        want = self.sizeHint().height()
        if on:  # room for the whole list if the screen allows, else scroll
            want += self.more.sizeHint().height() - self.scroll.sizeHint().height()
        self.resize(max(self.width(), 620), min(want, screen.height() - 80))

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

    def meter_choice(self):
        """The time signature chosen for this batch."""
        return parse_meter(self.meter.currentText()) if self.songs else "4/4"

    def tempo(self):
        """The tempo chosen for this batch, or None to detect it."""
        return round(self.bpm.value(), 1) if self.songs and self.manual_bpm.isChecked() else None
