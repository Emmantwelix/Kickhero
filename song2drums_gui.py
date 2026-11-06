#!/usr/bin/env python3
"""
song2drums_gui.py — a window for song2drums.py: pick songs, adjust settings, press Convert.

    Double-click song2drums_gui.bat, or run:  python song2drums_gui.py

Every setting maps to a song2drums.py option and starts at the same default. Your last
settings are remembered in gui_settings.json next to this script.
"""

import json
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import song2drums  # noqa: E402

SETTINGS_FILE = HERE / "gui_settings.json"
STEP_NAMES = {1: "Extracting drums from the mix", 2: "Splitting the kit", 3: "Finding the tempo", 4: "Writing MIDI"}
GRIDS = {"Off (keep the natural feel)": 0, "1/8 notes": 8, "1/16 notes": 16, "1/32 notes": 32}

_defaults = song2drums.build_parser()
DEFAULTS = {
    "output": str(HERE / _defaults.get_default("output")),
    "auto_bpm": True,
    "bpm": 120.0,
    "align": not _defaults.get_default("no_align"),
    "grid": "Off (keep the natural feel)",
    "split_toms": not _defaults.get_default("no_split_toms"),
    "force": False,
    "keep_stems": False,
    "sensitivity": _defaults.get_default("sensitivity"),
    "gate": _defaults.get_default("gate"),
    "ref_gate": _defaults.get_default("ref_gate"),
    "bleed_db": _defaults.get_default("bleed_db"),
    "min_gap": _defaults.get_default("min_gap"),
    "hihat_open_ms": _defaults.get_default("hihat_open_ms"),
}

# (key, title, slider from, slider to, resolution, unit, explanation)
TUNING = [
    ("sensitivity", "Hit sensitivity", 0.02, 0.20, 0.01, "",
     "Left = more hits. Go left if soft notes (ghost notes, light hi-hats) are missing, "
     "right if you get notes that weren't played."),
    ("gate", "Quiet-hit cutoff", -60, -10, 1, "dB",
     "Ignore hits this much quieter than the loudest hit on the same drum. Left keeps quieter hits."),
    ("ref_gate", "Leakage cutoff", -60, -20, 1, "dB",
     "Ignore hits this much quieter than the loudest sound in the whole kit. Removes phantom cymbal "
     "and tom hits that are really other drums leaking through. Right removes more."),
    ("bleed_db", "Tom leakage filter", 0, 30, 1, "dB",
     "Drop a tom hit that lands on a kick or snare hit at least this much louder. 0 = off. "
     "Raise it if real tom fills go missing."),
    ("min_gap", "Shortest gap", 10, 100, 1, "ms",
     "Hits on one drum closer than this become one hit. Lower for fast rolls and flams, "
     "raise if single hits come out doubled."),
    ("hihat_open_ms", "Open hi-hat length", 0, 400, 10, "ms",
     "Hi-hat hits ringing longer than this become open hi-hat. 0 = all closed."),
]


def load_settings():
    s = dict(DEFAULTS)
    try:
        s.update({k: v for k, v in json.loads(SETTINGS_FILE.read_text()).items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return s


class App:
    def __init__(self, root):
        self.root = root
        self.proc = None
        self.lines = queue.Queue()
        s = load_settings()
        self.vars = {}
        for key, val in s.items():
            var = {bool: tk.BooleanVar, float: tk.DoubleVar, int: tk.DoubleVar}.get(type(val), tk.StringVar)()
            var.set(val)
            self.vars[key] = var
        if s["grid"] not in GRIDS:
            self.vars["grid"].set(DEFAULTS["grid"])

        root.title("Song to Drum MIDI")
        style = ttk.Style()
        style.configure("Hint.TLabel", foreground="#666666", font=("Segoe UI", 9))
        style.configure("Head.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("Big.TButton", font=("Segoe UI", 11, "bold"), padding=(18, 6))

        # Left: songs, output, run, progress. Right: settings.
        outer = ttk.Frame(root, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)

        self._songs_section(outer).grid(row=0, column=0, sticky="nsew")
        self._output_section(outer).grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self._run_section(outer).grid(row=2, column=0, sticky="ew", pady=(12, 0))
        self._log_section(outer).grid(row=3, column=0, sticky="nsew", pady=(8, 0))
        self._settings_section(outer).grid(row=0, column=1, rowspan=4, sticky="nsew", padx=(12, 0))

        songs_dir = HERE / "songs"
        if songs_dir.is_dir():
            self._add_item(songs_dir)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self._poll_output)

    # ---------- layout ----------

    def _songs_section(self, parent):
        box = ttk.LabelFrame(parent, text=" 1. Songs to convert ", padding=8)
        box.columnconfigure(0, weight=1)
        self.song_list = tk.Listbox(box, height=6, width=40, selectmode="extended", activestyle="none",
                                    font=("Segoe UI", 10))
        self.song_list.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.song_list.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.song_list.config(yscrollcommand=sb.set)
        btns = ttk.Frame(box)
        btns.grid(row=0, column=2, sticky="n", padx=(8, 0))
        for text, cmd in (("Add songs...", self.add_files), ("Add a folder...", self.add_folder),
                          ("Remove", self.remove_selected), ("Clear", self.clear_songs)):
            ttk.Button(btns, text=text, command=cmd, width=15).pack(fill="x", pady=1)
        ttk.Label(box, style="Hint.TLabel", wraplength=440, justify="left",
                  text="A folder means every song inside it. Songs that already have a MIDI file are "
                       "skipped unless you tick \"Redo songs\" in Settings.").grid(row=1, column=0, columnspan=3,
                                                                                    sticky="w", pady=(4, 0))
        self.paths = []
        return box

    def _output_section(self, parent):
        box = ttk.LabelFrame(parent, text=" 2. Save MIDI files to ", padding=8)
        box.columnconfigure(0, weight=1)
        ttk.Entry(box, textvariable=self.vars["output"]).grid(row=0, column=0, sticky="ew")
        ttk.Button(box, text="Browse...", command=self.pick_output).grid(row=0, column=1, padx=(6, 0))
        ttk.Button(box, text="Open folder", command=self.open_output).grid(row=0, column=2, padx=(6, 0))
        return box

    def _settings_section(self, parent):
        box = ttk.LabelFrame(parent, text=" Settings ", padding=(8, 4, 8, 8))
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        tabs = ttk.Notebook(box)
        tabs.grid(row=0, column=0, sticky="nsew")
        tabs.add(self._basics_tab(tabs), text="  Basics  ")
        tabs.add(self._tuning_tab(tabs), text="  Fine-tuning  ")
        return box

    def _hint(self, parent, text, row, span=3, indent=22):
        lbl = ttk.Label(parent, text=text, style="Hint.TLabel", wraplength=400, justify="left")
        lbl.grid(row=row, column=0, columnspan=span, sticky="w", padx=(indent, 0), pady=(0, 8))
        return lbl

    def _basics_tab(self, parent):
        f = ttk.Frame(parent, padding=10)
        f.columnconfigure(2, weight=1)
        r = 0
        ttk.Label(f, text="Tempo", style="Head.TLabel").grid(row=r, column=0, sticky="w")
        r += 1
        ttk.Radiobutton(f, text="Detect it automatically", variable=self.vars["auto_bpm"], value=True,
                        command=self._sync_bpm).grid(row=r, column=0, columnspan=3, sticky="w")
        r += 1
        ttk.Radiobutton(f, text="I know it:", variable=self.vars["auto_bpm"], value=False,
                        command=self._sync_bpm).grid(row=r, column=0, sticky="w")
        self.bpm_spin = ttk.Spinbox(f, from_=30, to=300, increment=1, width=7, textvariable=self.vars["bpm"])
        self.bpm_spin.grid(row=r, column=1, sticky="w")
        ttk.Label(f, text="BPM").grid(row=r, column=2, sticky="w", padx=(4, 0))
        r += 1
        self._hint(f, "Set it yourself if the detected tempo comes out wrong (e.g. double or half speed).", r)
        self._sync_bpm()

        r += 1
        ttk.Label(f, text="Timing", style="Head.TLabel").grid(row=r, column=0, sticky="w")
        r += 1
        ttk.Checkbutton(f, text="Start the groove on bar 1 (line beat 1 up with the bar lines)",
                        variable=self.vars["align"]).grid(row=r, column=0, columnspan=3, sticky="w")
        r += 1
        self._hint(f, "Turn off to keep the MIDI in sync with the original song's timing instead.", r)
        r += 1
        ttk.Label(f, text="Snap notes to grid:").grid(row=r, column=0, sticky="w")
        ttk.Combobox(f, textvariable=self.vars["grid"], values=list(GRIDS), state="readonly",
                     width=26).grid(row=r, column=1, columnspan=2, sticky="w")
        r += 1
        self._hint(f, "Off keeps the drummer's natural feel. 1/16 is right for most songs.", r)

        r += 1
        ttk.Label(f, text="Other", style="Head.TLabel").grid(row=r, column=0, sticky="w")
        for key, text in (("split_toms", "Split toms into floor / mid / high tom notes"),
                          ("force", "Redo songs that already have a MIDI file"),
                          ("keep_stems", "Keep the separated drum audio (to listen to, or re-run faster)")):
            r += 1
            ttk.Checkbutton(f, text=text, variable=self.vars[key]).grid(row=r, column=0, columnspan=3, sticky="w")
        return f

    def _tuning_tab(self, parent):
        f = ttk.Frame(parent, padding=10)
        f.columnconfigure(1, weight=1)
        r = 0
        for key, title, lo, hi, res, unit, text in TUNING:
            ttk.Label(f, text=title, style="Head.TLabel").grid(row=r, column=0, sticky="w")
            value = ttk.Label(f, width=7, anchor="e")
            value.grid(row=r, column=2, sticky="e")
            var = self.vars[key]

            def on_move(_=None, var=var, res=res, unit=unit, value=value):
                v = round(round(var.get() / res) * res, 2)
                if v != var.get():  # snap to the step; the check stops the trace calling us forever
                    var.set(v)
                value.config(text=f"{v:g} {unit}".strip())

            ttk.Scale(f, from_=lo, to=hi, variable=var, command=on_move).grid(row=r, column=1, sticky="ew", padx=8)
            on_move()
            var.trace_add("write", lambda *_, cb=on_move: cb())
            r += 1
            self._hint(f, text, r, indent=0)
            r += 1
        ttk.Button(f, text="Reset to defaults", command=self.reset_tuning).grid(row=r, column=0, sticky="w")
        return f

    def _run_section(self, parent):
        f = ttk.Frame(parent)
        f.columnconfigure(2, weight=1)
        self.run_btn = ttk.Button(f, text="3. Convert", style="Big.TButton", command=self.start)
        self.run_btn.grid(row=0, column=0, rowspan=2)
        self.stop_btn = ttk.Button(f, text="Stop", command=self.stop, state="disabled")
        self.stop_btn.grid(row=0, column=1, rowspan=2, padx=(6, 12))
        self.status = ttk.Label(f, text="Ready.")
        self.status.grid(row=0, column=2, sticky="w")
        self.progress = ttk.Progressbar(f, mode="determinate")
        self.progress.grid(row=1, column=2, sticky="ew", pady=(3, 0))
        return f

    def _log_section(self, parent):
        box = ttk.LabelFrame(parent, text=" Details ", padding=4)
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        self.log = tk.Text(box, height=8, wrap="word", font=("Consolas", 9), state="disabled",
                           relief="flat", background="#f7f7f7")
        self.log.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.log.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.log.config(yscrollcommand=sb.set)
        return box

    # ---------- song list / folders ----------

    def _add_item(self, path):
        path = Path(path)
        if path in self.paths:
            return
        self.paths.append(path)
        label = f"[folder]  {path}   (all songs inside)" if path.is_dir() else path.name
        self.song_list.insert("end", label)

    def add_files(self):
        exts = " ".join(f"*{e}" for e in sorted(song2drums.SONG_EXTS))
        for p in filedialog.askopenfilenames(title="Choose songs", filetypes=[("Audio", exts), ("All files", "*.*")]):
            self._add_item(p)

    def add_folder(self):
        p = filedialog.askdirectory(title="Choose a folder of songs")
        if p:
            self._add_item(p)

    def remove_selected(self):
        for i in reversed(self.song_list.curselection()):
            self.song_list.delete(i)
            del self.paths[i]

    def clear_songs(self):
        self.song_list.delete(0, "end")
        self.paths.clear()

    def pick_output(self):
        p = filedialog.askdirectory(title="Save MIDI files to", initialdir=self.vars["output"].get())
        if p:
            self.vars["output"].set(p)

    def open_output(self):
        out = Path(self.vars["output"].get())
        out.mkdir(parents=True, exist_ok=True)
        os.startfile(out)

    # ---------- settings ----------

    def _sync_bpm(self):
        self.bpm_spin.config(state="disabled" if self.vars["auto_bpm"].get() else "normal")

    def reset_tuning(self):
        for key, *_ in TUNING:
            self.vars[key].set(DEFAULTS[key])

    def settings(self):
        out = {}
        for k, v in self.vars.items():
            try:
                out[k] = v.get()
            except tk.TclError:  # e.g. a half-typed number in the BPM box
                out[k] = DEFAULTS[k]
        return out

    def save_settings(self):
        try:
            SETTINGS_FILE.write_text(json.dumps(self.settings(), indent=2))
        except OSError:
            pass

    def build_args(self, s):
        args = [str(p) for p in self.paths] + ["-o", s["output"]]
        if not s["auto_bpm"]:
            args += ["--bpm", f"{s['bpm']:g}"]
        if GRIDS.get(s["grid"]):
            args += ["--quantize", str(GRIDS[s["grid"]])]
        for key in ("sensitivity", "gate", "ref_gate", "bleed_db", "min_gap", "hihat_open_ms"):
            args += ["--" + key.replace("_", "-"), f"{s[key]:g}"]
        for key, flag, on in (("align", "--no-align", False), ("split_toms", "--no-split-toms", False),
                              ("force", "--force", True), ("keep_stems", "--keep-stems", True)):
            if s[key] == on:
                args.append(flag)
        return args

    # ---------- running ----------

    def start(self):
        if not self.paths:
            messagebox.showinfo("No songs", "Add some songs (or a folder of songs) first.")
            return
        s = self.settings()
        if not s["auto_bpm"] and not 30 <= s["bpm"] <= 300:
            messagebox.showerror("Tempo", "Enter a tempo between 30 and 300 BPM, or choose automatic.")
            return
        self.save_settings()

        python = Path(sys.executable)
        if python.name.lower() == "pythonw.exe":  # need the console version to read its output
            python = python.with_name("python.exe")
        cmd = [str(python), "-u", str(HERE / "song2drums.py")] + self.build_args(s)
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        self.proc = subprocess.Popen(
            cmd, cwd=HERE, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        threading.Thread(target=self._read_output, args=(self.proc,), daemon=True).start()

        self.total = self.done = self.step = 0
        self.song_name = ""
        self.stopped = False
        self.progress.config(value=0, maximum=1)
        self._log_clear()
        self._log("Starting...\n")
        self.status.config(text="Looking for songs...")
        self.run_btn.config(state="disabled")
        self.stop_btn.config(state="normal")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.stopped = True
            self.proc.terminate()

    def _read_output(self, proc):
        for line in proc.stdout:  # text mode turns tqdm's \r updates into separate lines
            self.lines.put(line.rstrip("\n"))
        proc.wait()
        self.lines.put(None)

    def _poll_output(self):
        try:
            while True:
                line = self.lines.get_nowait()
                if line is None:
                    self._finished()
                else:
                    self._handle_line(line)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_output)

    def _handle_line(self, line):
        if "%|" in line:  # a model progress bar: show it in the status, not the log
            m = re.search(r"(\d+)%\|", line)
            if m and self.song_name:
                self._set_status(f"{STEP_NAMES.get(self.step, '')}... {m.group(1)}%")
            return
        if not line.strip():  # mostly leftovers of progress bars
            return
        self._log(("\n" if line.startswith("===") else "") + line + "\n")
        if m := re.search(r"(\d+) song\(s\) found, (\d+) already done, (\d+) to process", line):
            self.total = int(m.group(3))
            self.progress.config(maximum=max(self.total * 4, 1))
            if self.total == 0:
                self.status.config(text="Nothing to do: every song already has a MIDI file.")
        elif m := re.match(r"=== (.*) ===$", line):
            self.song_name, self.step = m.group(1), 0
            self._set_status("Starting")
        elif m := re.match(r"\[(\d)/4\]", line):
            self.step = int(m.group(1))
            self._set_status(STEP_NAMES[self.step] + "...")
            self.progress.config(value=self.done * 4 + self.step - 1)
        elif line.startswith("Done in") or line.startswith("!! "):
            self.done += 1
            self.progress.config(value=self.done * 4)

    def _set_status(self, text):
        n = min(self.done + 1, max(self.total, 1))
        self.status.config(text=f"Song {n} of {self.total}: {self.song_name[:50]}  -  {text}")

    def _finished(self):
        code = self.proc.returncode if self.proc else 0
        self.proc = None
        self.run_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        if self.stopped:
            self.status.config(text="Stopped.")
            self._log("\nStopped.\n")
        elif code != 0:
            self.status.config(text="Something went wrong - see the details below.")
        elif self.total:
            self.progress.config(value=self.progress["maximum"])
            self.status.config(text=f"Finished. {self.done} song(s) processed - click \"Open folder\" to see them.")

    def _log(self, text):
        self.log.config(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.config(state="disabled")

    def _log_clear(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    def on_close(self):
        if self.proc and self.proc.poll() is None:
            if not messagebox.askyesno("Still converting", "A conversion is running. Stop it and close?"):
                return
            self.proc.terminate()
        self.save_settings()
        self.root.destroy()


def main():
    try:  # sharp text on high-DPI Windows screens
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
