"""My kit page: connection, pad setup wizard, latency calibration and sound options."""

import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton,
                               QScrollArea, QSlider, QVBoxLayout, QWidget)

from ..engine.lesson import Lesson
from ..engine.session import Session
from ..engine.sounds import CUSTOM, KITS, SAMPLE_EXTS, match_kit_folder
from ..kit.calibration import measure_latency
from ..kit.mapping import KitMap
from ..lanes import LANE_COLORS, LANE_NAMES, LANES, OPEN_HAT, SOUND_NAMES, SOUNDS
from . import theme
from .kit_diagram import PEDAL, KitDiagram

CAL_BPM = 100
CAL_BARS = 4

HIT_ZONES = "a few times, on every zone (head, rim, edge, bell)"

# Pad setup steps: (tile lit, what the notes heard are learned as, instruction)
WIZARD_STEPS = []
for _lane in LANES:
    if _lane == "hihat":
        WIZARD_STEPS += [
            ("hihat", "hihat", "keep the hi-hat pedal pressed down and hit your CLOSED HI-HAT " + HIT_ZONES + "."),
            ("hihat", OPEN_HAT, "lift your foot off the hi-hat pedal and hit your OPEN HI-HAT " + HIT_ZONES + ". "
                                "Skip this if you have no hi-hat pedal."),
            ("hihat", "", "press the HI-HAT PEDAL down with your foot a few times (the \"chick\"), without hitting "
                          "anything. Skip this if you have no hi-hat pedal."),
        ]
    else:
        WIZARD_STEPS.append((_lane, _lane, f"hit your {LANE_NAMES[_lane].upper()} {HIT_ZONES}."))


def card(title, subtitle=""):
    f = QFrame(objectName="card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(20, 16, 20, 18)
    lay.setSpacing(8)
    lay.addWidget(QLabel(title, objectName="h2"))
    if subtitle:
        lay.addWidget(QLabel(subtitle, objectName="muted", wordWrap=True))
    return f, lay


def wizard_step_for(heard, note, step, velocity):
    """Record a pad-setup hit and return the step the note belongs to: the one where it was hit the most
    (then the loudest, then the earliest). A stray hit or crosstalk from another pad can't steal a note."""
    hits, loudest = heard.setdefault(note, {}).get(step, (0, 0))
    heard[note][step] = (hits + 1, max(loudest, velocity))
    return max(heard[note], key=lambda st: (*heard[note][st], -st))


def step_part(step):
    """The part of the kit drawing a pad setup step lights up."""
    tile_lane, learn_as, _ = WIZARD_STEPS[step]
    return {OPEN_HAT: OPEN_HAT, "": PEDAL}.get(learn_as, tile_lane)


def wizard_step_name(step):
    tile_lane, learn_as, _ = WIZARD_STEPS[step]
    return {OPEN_HAT: "Open hi-hat", "": "Hi-hat pedal"}.get(learn_as, LANE_NAMES[tile_lane])


class PadTile(QFrame):
    def __init__(self, lane):
        super().__init__()
        self.lane = lane
        self.setMinimumSize(120, 64)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        self.name = QLabel(LANE_NAMES[lane])
        self.name.setStyleSheet("font-weight: 600;")
        self.notes = QLabel(objectName="muted")
        lay.addWidget(self.name)
        lay.addWidget(self.notes)
        self._off = QTimer(self, singleShot=True, interval=160)
        self._off.timeout.connect(lambda: self.set_state("normal"))
        self.set_state("normal")

    def set_state(self, state):
        c = LANE_COLORS[self.lane]
        bg = {"normal": theme.PANEL_2, "lit": c, "target": theme.SELECT}[state]
        border = c if state != "normal" else theme.BORDER
        self.setStyleSheet(f"PadTile {{ background: {bg}; border: 2px solid {border}; border-radius: 10px; }}")
        self.name.setStyleSheet(f"font-weight: 600; color: {'#14161f' if state == 'lit' else theme.TEXT};")
        self.notes.setStyleSheet(f"color: {'#14161f' if state == 'lit' else theme.MUTED};")

    def blink(self):
        self.set_state("lit")
        self._off.start()


class KitPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.wizard_step = None  # index into WIZARD_STEPS while the pad setup runs
        self.wizard_heard = {}   # note -> {step: (hits, loudest velocity)} during this pad setup
        self.wizard_single = False  # setting up one drum only (clicked on the kit drawing)
        self.cal = None  # running calibration: dict

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(widgetResizable=True, frameShape=QFrame.NoFrame)
        outer.addWidget(scroll)
        body = QWidget(objectName="root")
        scroll.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)
        lay.addWidget(QLabel("My kit", objectName="h1"))

        # --- connection ---
        c, cl = card("Connection", "Plug your kit in with its USB cable and switch it on. It shows up here "
                                   "automatically; any kit that sends MIDI over USB works.")
        row = QHBoxLayout()
        self.status = QLabel(wordWrap=True)
        self.devices = QComboBox()
        self.devices.setMinimumWidth(200)
        self.devices.activated.connect(lambda _: ctx.midi.open(self.devices.currentText()))
        row.addWidget(self.status, 1)
        row.addWidget(QLabel("Device"))
        row.addWidget(self.devices)
        cl.addLayout(row)
        lay.addWidget(c)

        # --- pads ---
        c, cl = card("Pads", "Hit any pad: it lights up on the kit below. If the wrong drum lights up (or none), "
                             "run the pad setup, or click a drum to set up just that one.")
        self.diagram = KitDiagram()
        self.diagram.setFixedHeight(270)
        self.diagram.part_clicked.connect(self.setup_part)
        cl.addWidget(self.diagram)
        grid = QGridLayout()
        grid.setSpacing(8)
        self.tiles = {}
        for i, lane in enumerate(LANES):
            t = PadTile(lane)
            self.tiles[lane] = t
            grid.addWidget(t, i // 4, i % 4)
        cl.addLayout(grid)
        self.last = QLabel("Last hit: -", objectName="muted")
        cl.addWidget(self.last)
        self.wizard_text = QLabel(wordWrap=True)
        self.wizard_text.setStyleSheet(f"font-size: 11pt; color: {theme.ACCENT}; font-weight: 600;")
        self.wizard_text.hide()
        cl.addWidget(self.wizard_text)
        row = QHBoxLayout()
        self.setup_btn = QPushButton("Set up my pads...")
        self.setup_btn.setObjectName("primary")
        self.setup_btn.clicked.connect(lambda: self.start_wizard())
        self.next_btn = QPushButton("Next drum")
        self.next_btn.clicked.connect(self.wizard_next)
        self.skip_btn = QPushButton("My kit doesn't have this")
        self.skip_btn.clicked.connect(self.wizard_skip)
        self.cancel_btn = QPushButton("Finish")
        self.cancel_btn.clicked.connect(self.end_wizard)
        self.reset_btn = QPushButton("Reset to standard layout")
        self.reset_btn.clicked.connect(self.reset_map)
        for b in (self.setup_btn, self.next_btn, self.skip_btn, self.cancel_btn, self.reset_btn):
            row.addWidget(b)
        row.addStretch()
        cl.addLayout(row)
        lay.addWidget(c)

        # --- timing ---
        c, cl = card("Timing", "Every kit and computer adds a little delay between hitting a pad and the app "
                               "hearing it. Measure it once so your on-time playing scores as on time.")
        row = QHBoxLayout()
        self.latency_label = QLabel()
        self.latency_label.setStyleSheet("font-size: 11pt; font-weight: 600;")
        self.cal_btn = QPushButton("Measure delay...")
        self.cal_btn.setObjectName("primary")
        self.cal_btn.clicked.connect(self.start_calibration)
        row.addWidget(self.latency_label)
        row.addStretch()
        row.addWidget(self.cal_btn)
        cl.addLayout(row)
        self.cal_text = QLabel(objectName="muted", wordWrap=True)
        cl.addWidget(self.cal_text)
        lay.addWidget(c)

        # --- sound ---
        c, cl = card("Sound")
        self.pad_sounds = QCheckBox("Play drum sounds from this app")
        self.pad_sounds.setChecked(ctx.settings["pad_sounds"])
        self.pad_sounds.toggled.connect(lambda on: ctx.settings.__setitem__("pad_sounds", on))
        cl.addWidget(self.pad_sounds)
        cl.addWidget(QLabel("Turn this on if your kit makes no sound of its own, or you're listening through the "
                            "computer.", objectName="caption", wordWrap=True))
        vol = QGridLayout()
        for r, (key, text) in enumerate((("metronome", "Metronome"), ("pads", "Drum sounds"),
                                         ("guide", "\"Hear the part\" playback"))):
            s = QSlider(Qt.Horizontal)
            s.setRange(0, 100)
            s.setValue(int(ctx.settings[f"volume_{key}"] * 100))
            s.valueChanged.connect(lambda v, k=key: ctx.set_volume(k, v / 100))
            vol.addWidget(QLabel(text), r, 0)
            vol.addWidget(s, r, 1)
        cl.addLayout(vol)
        lay.addWidget(c)

        # --- drum sounds ---
        c, cl = card("Drum sounds", "The sounds used when the app plays drums: \"Hear the part\", lanes you've "
                                    "turned off, and pad hits (if turned on above). Click ▶ to listen.")
        row = QHBoxLayout()
        row.addWidget(QLabel("Kit"))
        self.kit_choice = QComboBox()
        for key, name in KITS.items():
            self.kit_choice.addItem(name, key)
        self.kit_choice.addItem("My own sounds", CUSTOM)
        self.kit_choice.setCurrentIndex(max(0, self.kit_choice.findData(ctx.settings["sound_kit"])))
        self.kit_choice.currentIndexChanged.connect(lambda _: self._apply_kit())
        row.addWidget(self.kit_choice)
        self.folder_btn = QPushButton("Load a kit folder...")
        self.folder_btn.setToolTip("Pick a folder of drum samples: one sample per drum is chosen by file name "
                                   "(kick, snare, hat...), taking the hardest-hit layer")
        self.folder_btn.clicked.connect(self._load_kit_folder)
        row.addWidget(self.folder_btn)
        row.addStretch()
        cl.addLayout(row)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        self.sound_rows = {}
        for r, lane in enumerate(SOUNDS):
            play = QPushButton("▶")
            play.setFixedWidth(40)
            play.clicked.connect(lambda _=False, ln=lane: ctx.audio.play_pad(ln, 115))
            name = QLabel(SOUND_NAMES[lane])
            file_label = QLabel(objectName="muted")
            choose = QPushButton("Choose...")
            choose.clicked.connect(lambda _=False, ln=lane: self._choose_sample(ln))
            clear = QPushButton("Built-in")
            clear.setToolTip("Use the built-in sound for this drum")
            clear.clicked.connect(lambda _=False, ln=lane: self._set_sample(ln, None))
            for col, w in enumerate((play, name, file_label, choose, clear)):
                grid.addWidget(w, r, col)
            self.sound_rows[lane] = (file_label, choose, clear)
        grid.setColumnStretch(2, 1)
        cl.addLayout(grid)
        self.sound_note = QLabel(objectName="muted", wordWrap=True)
        cl.addWidget(self.sound_note)
        cl.addWidget(QLabel("Your own sounds stay on this computer: Kickhero only reads them from where they are.",
                            objectName="muted", wordWrap=True))
        lay.addWidget(c)
        lay.addStretch()
        self._refresh_sounds()

        ctx.midi.ports_changed.connect(self._ports_changed)
        ctx.midi.connected.connect(lambda _: self._refresh_status())
        self._ports_changed(ctx.midi.ports)
        self._show_wizard_buttons(False)
        self._refresh_notes()
        self._refresh_latency()

        self.cal_timer = QTimer(self, interval=50)
        self.cal_timer.timeout.connect(self._calibration_tick)

    # ---------- connection ----------

    def _ports_changed(self, ports):
        self.devices.clear()
        self.devices.addItems(ports or ["(no MIDI devices found)"])
        self.devices.setEnabled(bool(ports))
        self._refresh_status()

    def _refresh_status(self):
        name = self.ctx.midi.port_name
        if name:
            self.status.setText(f"<span style='color:{theme.GOOD}'>●</span>  Connected: <b>{name}</b>")
            self.devices.setCurrentText(name)
        else:
            self.status.setText(f"<span style='color:{theme.BAD}'>●</span>  No kit found. Plug it in "
                                "and switch it on (you can also play with the keyboard).")
        self._refresh_notes()

    # ---------- pads ----------

    def _refresh_notes(self):
        kit = self.ctx.kit
        for lane, tile in self.tiles.items():
            notes = kit.notes_for(lane)
            text = ("notes " + ", ".join(map(str, notes[:6])) + ("..." if len(notes) > 6 else "")
                    if notes else "not set")
            if lane == "hihat" and kit.notes_for(OPEN_HAT):
                text += "\nopen " + ", ".join(map(str, kit.notes_for(OPEN_HAT)[:4]))
            tile.notes.setText(text)

    def on_note(self, note, velocity, perf, lane):
        """Every incoming kit note (raw), whether or not it's mapped."""
        if self.wizard_step is not None:
            step = wizard_step_for(self.wizard_heard, note, self.wizard_step, velocity)
            tile_lane, learn_as, _ = WIZARD_STEPS[step]
            self.ctx.kit.learn(note, learn_as)
            self.ctx.save_kit()
            self._refresh_notes()
            lane = tile_lane if learn_as else ""
            self.diagram.set_done(step_part(st) for heard in self.wizard_heard.values() for st in heard)
            if step != self.wizard_step:  # a stray hit (or crosstalk) on a pad set up in another step
                self.last.setText(f"Last hit: note {note}, velocity {velocity}  →  kept as "
                                  f"{wizard_step_name(step)} (you played it more in that step)")
                self.diagram.flash(step_part(step))
                if lane:
                    self.tiles[lane].blink()
                return
        if self.cal is not None:
            self.cal["hits"].append(perf)
        if lane:
            self.tiles[lane].blink()
            self.diagram.flash(OPEN_HAT if self.ctx.kit.is_open_hat(note) else lane)
            name = "Open hi-hat" if self.ctx.kit.is_open_hat(note) else LANE_NAMES[lane]
            self.last.setText(f"Last hit: note {note}, velocity {velocity}  →  {name}")
        elif lane == "":
            self.diagram.flash(PEDAL)
            self.last.setText(f"Last hit: note {note}, velocity {velocity}  →  ignored (hi-hat pedal)")
        else:
            self.last.setText(f"Last hit: note {note}, velocity {velocity}  →  not assigned. Run the pad setup.")

    def start_wizard(self, first=0, single=False):
        if self.wizard_step is None:
            self.wizard_heard = {}
            self.diagram.set_done(())
        self.wizard_single = single
        self._show_wizard_buttons(True)
        self._wizard_goto(first)

    def setup_part(self, part):
        """A drum clicked on the kit drawing: go to its step (or set up just that drum)."""
        step = next(i for i in range(len(WIZARD_STEPS)) if step_part(i) == part)
        if self.wizard_step is not None and not self.wizard_single:
            self._wizard_goto(step)
        else:
            self.start_wizard(step, single=True)

    def _wizard_goto(self, i):
        for t in self.tiles.values():
            t.set_state("normal")
        if i >= len(WIZARD_STEPS):
            self.end_wizard()
            return
        self.wizard_step = i
        tile_lane, _, text = WIZARD_STEPS[i]
        self.tiles[tile_lane].set_state("target")
        self.diagram.set_target(step_part(i))
        if self.wizard_single:
            self.wizard_text.setText(f"{text[0].upper()}{text[1:]} Then press Done.")
        else:
            self.wizard_text.setText(f"Step {i + 1} of {len(WIZARD_STEPS)}: {text[0].upper()}{text[1:]} "
                                     "Then press Next drum.")
        self.wizard_text.show()

    def wizard_next(self):
        if self.wizard_single:
            self.end_wizard()
        else:
            self._wizard_goto(self.wizard_step + 1)

    def wizard_skip(self):
        self.wizard_next()

    def end_wizard(self):
        self.wizard_step = None
        self.wizard_single = False
        self.diagram.set_target(None)
        self.diagram.set_done(())
        self.wizard_text.hide()
        for t in self.tiles.values():
            t.set_state("normal")
        self._show_wizard_buttons(False)
        self.ctx.save_kit()

    def _show_wizard_buttons(self, on):
        for b in (self.next_btn, self.skip_btn, self.cancel_btn):
            b.setVisible(on)
        self.next_btn.setText("Done" if self.wizard_single else "Next drum")
        self.skip_btn.setVisible(on and not self.wizard_single)
        self.cancel_btn.setVisible(on and not self.wizard_single)
        self.setup_btn.setVisible(not on)
        self.reset_btn.setVisible(not on)

    def reset_map(self):
        self.ctx.kit = KitMap()
        self.ctx.save_kit()
        self._refresh_notes()

    # ---------- drum sounds ----------

    def _custom(self):
        return dict(self.ctx.settings["custom_sounds"])

    def _apply_kit(self, note=""):
        kit = self.kit_choice.currentData()
        errors = self.ctx.set_kit(kit, self._custom())
        if errors:
            failed = ", ".join(SOUND_NAMES[ln] for ln in errors)
            note = f"{note}  Couldn't load: {failed} (using the built-in sound instead).".strip()
        self.sound_note.setText(note)
        self._refresh_sounds()

    def _refresh_sounds(self):
        custom = self.kit_choice.currentData() == CUSTOM
        sounds = self._custom()
        self.folder_btn.setVisible(custom)
        for lane, (label, choose, clear) in self.sound_rows.items():
            path = sounds.get(lane)
            if custom and path:
                label.setText(Path(path).name)
                label.setToolTip(path)
            else:
                label.setText(f"built-in ({self.kit_choice.currentText() if not custom else 'Classic'})")
                label.setToolTip("")
            choose.setVisible(custom)
            clear.setVisible(custom and bool(path))

    def _set_sample(self, lane, path):
        sounds = self._custom()
        if path:
            sounds[lane] = str(path)
        else:
            sounds.pop(lane, None)
        self.ctx.settings["custom_sounds"] = sounds
        self._apply_kit()

    def _choose_sample(self, lane):
        exts = " ".join(f"*{e}" for e in sorted(SAMPLE_EXTS))
        start = self._custom().get(lane) or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, f"Sound for {SOUND_NAMES[lane]}", str(Path(start).parent),
                                              f"Audio ({exts});;All files (*.*)")
        if path:
            self._set_sample(lane, path)
            self.ctx.audio.play_pad(lane, 115)

    def _load_kit_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder of drum samples", str(Path.home()))
        if not folder:
            return
        found = match_kit_folder(folder)
        if not found:
            self.sound_note.setText("No drum samples recognised in that folder (file names need words like kick, "
                                    "snare, hat, tom, ride, crash).")
            return
        sounds = self._custom()
        sounds.update({lane: str(p) for lane, p in found.items()})
        self.ctx.settings["custom_sounds"] = sounds
        missing = [SOUND_NAMES[ln] for ln in SOUNDS if ln not in found]
        self._apply_kit(f"Loaded {len(found)} sounds from {Path(folder).name}."
                        + (f" Not found: {', '.join(missing)}." if missing else ""))

    # ---------- latency calibration ----------

    def _refresh_latency(self):
        ms = self.ctx.settings["latency_ms"]
        self.latency_label.setText(f"Delay correction: {ms:.0f} ms" if ms else "Delay correction: not measured yet")

    def start_calibration(self):
        audio = self.ctx.audio
        lesson = Lesson(title="calibration", bpm=CAL_BPM, notes=[], bars=CAL_BARS)
        s = Session(lesson, count_in_bars=1)
        start = time.perf_counter() + 0.3
        s.start(start)
        self.cal = {"session": s, "start": start, "hits": [], "metronome": audio.metronome}
        audio.metronome = True
        audio.session = s
        self.cal_btn.setEnabled(False)
        self.cal_text.setText("Listen to the first 4 clicks, then hit any pad exactly on each of the next 16 "
                              "clicks.")
        self.cal_timer.start()

    def _calibration_tick(self):
        cal = self.cal
        s = cal["session"]
        lesson = s.lesson
        end = cal["start"] + s.count_in + lesson.length + 0.4
        now = time.perf_counter()
        if now < end:
            beats_left = int((end - 0.4 - now) / lesson.beat) + 1
            self.cal_text.setText(f"Hit a pad on every click...  {beats_left} clicks to go"
                                  if now > cal["start"] + s.count_in - 0.2 else "Listen to the count-in...")
            return
        self.cal_timer.stop()
        self.ctx.audio.session = None
        self.ctx.audio.metronome = cal["metronome"]
        self.cal = None
        self.cal_btn.setEnabled(True)
        clicks = [cal["start"] + s.count_in + k * lesson.beat for k in range(CAL_BARS * lesson.beats_per_bar)]
        result = measure_latency(clicks, cal["hits"])
        if result is None:
            self.cal_text.setText("Not enough hits were heard. Check the kit is connected (a tile lights up when "
                                  "you hit a pad) and try again.")
            return
        latency, spread, used = result
        if spread > 0.025:
            self.cal_text.setText(f"The hits were too uneven to measure reliably (±{spread * 1000:.0f} ms). "
                                  "Try again, hitting exactly with each click.")
            return
        self.ctx.settings["latency_ms"] = round(latency * 1000, 1)
        self._refresh_latency()
        self.cal_text.setText(f"Measured {latency * 1000:.0f} ms from {used} hits (consistent to "
                              f"±{spread * 1000:.0f} ms). Saved.")
