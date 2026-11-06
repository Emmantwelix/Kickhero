"""Build Kickhero for Windows: bundled ffmpeg -> PyInstaller app folder -> Inno Setup installer.

    env\\Scripts\\python packaging\\build.py            (needs: pip install pyinstaller; Inno Setup 6 for the installer)

Output: build/dist/Kickhero/ (the app) and build/installer/Kickhero-Setup-<version>.exe
"""

import io
import shutil
import subprocess
import sys
import tomllib
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
# LGPL build of ffmpeg (audio-separator needs the ffmpeg executable); see THIRD_PARTY_LICENSES.md
FFMPEG_URL = ("https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
              "ffmpeg-n8.1-latest-win64-lgpl-8.1.zip")  # BtbN keeps the two newest releases; bump when it 404s
ISCC_PATHS = [Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"), Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
              Path.home() / r"AppData\Local\Programs\Inno Setup 6\ISCC.exe"]


def version():
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def download(url):
    """urllib with certifi's CA bundle; falls back to Windows' curl (system certificate store)."""
    try:
        import ssl

        import certifi

        ctx = ssl.create_default_context(cafile=certifi.where())
        return urllib.request.urlopen(url, timeout=300, context=ctx).read()
    except Exception as e:
        print(f"  urllib failed ({e.__class__.__name__}); trying curl...")
        return subprocess.run(["curl", "-fsSL", url], check=True, capture_output=True).stdout


def fetch_ffmpeg():
    dest = BUILD / "ffmpeg"
    if (dest / "ffmpeg.exe").exists():
        return
    print("Downloading ffmpeg (LGPL build)...")
    data = download(FFMPEG_URL)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            if name.endswith("/bin/ffmpeg.exe") or name.endswith("/LICENSE.txt"):
                (dest / Path(name).name).write_bytes(z.read(name))
    if not (dest / "ffmpeg.exe").exists():
        sys.exit("ffmpeg.exe not found in the download")


def pyinstaller():
    print("Building the app with PyInstaller...")
    subprocess.run([sys.executable, "-m", "PyInstaller", str(ROOT / "packaging" / "kickhero.spec"), "--noconfirm",
                    "--distpath", str(BUILD / "dist"), "--workpath", str(BUILD / "work")], check=True)
    for f in ("LICENSE", "THIRD_PARTY_LICENSES.md"):
        shutil.copy(ROOT / f, BUILD / "dist" / "Kickhero" / f)


def installer():
    iscc = next((p for p in ISCC_PATHS if p.exists()), None) or shutil.which("iscc")
    if not iscc:
        print("Inno Setup not found: skipping the installer (the app folder is in build/dist/Kickhero).")
        return
    print("Building the installer with Inno Setup...")
    subprocess.run([str(iscc), f"/DAppVersion={version()}", str(ROOT / "packaging" / "kickhero.iss")], check=True)


if __name__ == "__main__":
    fetch_ffmpeg()
    pyinstaller()
    installer()
    print("Done.")
