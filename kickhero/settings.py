"""App settings and data folders. Settings live in %APPDATA%/Kickhero/settings.json."""

import json
import os
from pathlib import Path

APP_NAME = "Kickhero"
REPO_ROOT = Path(__file__).resolve().parent.parent


OLD_APP_NAME = "drum-coach"  # the working name before the first release


def data_dir():
    base = Path(os.environ.get("APPDATA") or Path.home() / ".config")
    d = base / APP_NAME
    old = base / OLD_APP_NAME
    if not d.exists() and old.is_dir():  # keep kit setup, latency and scores from before the rename
        try:
            old.rename(d)
        except OSError:
            pass
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_library_dir():
    """Running from source: the repo's drum_midi folder. Installed: Documents/Kickhero/drum_midi."""
    if (REPO_ROOT / "drum_midi").is_dir():
        return REPO_ROOT / "drum_midi"
    return Path.home() / "Documents" / APP_NAME / "drum_midi"


DEFAULTS = {
    "library_dir": "",          # empty = default_library_dir()
    "midi_device": "",          # last kit used
    "kits": {},                 # device name -> {note: lane or ""} (see kit/mapping.py)
    "latency_ms": 0.0,          # measured by calibration, subtracted from every pad hit
    "pad_sounds": False,        # the app plays drum sounds for pad hits (for kits without a sound module)
    "volume_metronome": 0.6,
    "volume_guide": 0.5,
    "volume_pads": 0.8,
    "volume_backing": 0.8,
    "course_unlock_all": False,
    "sound_kit": "classic",     # built-in kit name, or "custom"
    "custom_sounds": {},        # lane -> sample file on this computer (for sound_kit "custom")
    "convert": {},              # conversion options (see pipeline/worker.py DEFAULT_OPTIONS)
}


class Settings:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_dir() / "settings.json"
        self.data = json.loads(json.dumps(DEFAULTS))  # deep copy
        try:
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value
        self.save()

    def save(self):
        try:
            self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except OSError:
            pass

    @property
    def library_dir(self):
        return Path(self.data["library_dir"]) if self.data["library_dir"] else default_library_dir()
