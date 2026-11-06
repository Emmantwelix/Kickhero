# PyInstaller spec: builds dist/Kickhero/Kickhero.exe (one folder, no console).
#   env\Scripts\python -m PyInstaller packaging\kickhero.spec --noconfirm
# The separation models are NOT bundled: they download to ~/.cache/audio-separator-models on first use.

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = SPECPATH + "/.."

datas, binaries, hiddenimports = [], [], []
for pkg in ("audio_separator", "librosa", "soxr", "pretty_midi", "rtmidi", "sounddevice"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
datas += collect_data_files("kickhero", includes=["assets/*", "course/*.json"])
# ffmpeg (LGPL build, fetched by packaging/build.py): audio-separator needs it to read and write audio
import os
_ff = os.path.join(ROOT, "build", "ffmpeg")
if os.path.exists(os.path.join(_ff, "ffmpeg.exe")):
    binaries.append((os.path.join(_ff, "ffmpeg.exe"), "ffmpeg"))
    datas.append((os.path.join(_ff, "LICENSE.txt"), "ffmpeg"))
else:
    print("WARNING: build/ffmpeg/ffmpeg.exe missing; the app will rely on ffmpeg being installed")
hiddenimports += ["kickhero.pipeline.song2drums", "kickhero.pipeline.drums2midi"]

a = Analysis(
    [ROOT + "/packaging/kickhero_main.py"],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython", "jupyter", "pytest", "PyQt5", "PyQt6"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Kickhero",
    icon=ROOT + "/kickhero/assets/kickhero.ico",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Kickhero")
