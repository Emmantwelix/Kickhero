"""Song cover art: the picture embedded in the user's own song file (cached as cover.jpg next to the drum part),
or a generated tile with the song's initials. Nothing is downloaded."""

import hashlib
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPen

from ..engine.lesson import read_metadata

COVER_NAME = "cover.jpg"
COVER_PX = 480  # cached size (square)


def split_title(title):
    """("Song", "Artist") from a "Song - Artist" name; the artist is "" when the name has none."""
    song, sep, artist = title.rpartition(" - ")
    return (song.strip(), artist.strip()) if sep and song.strip() else (title.strip(), "")


def cover_file(midi_path):
    return Path(midi_path).parent / COVER_NAME


def embedded_art(audio_path):
    """The bytes of the picture inside an audio file (MP3/ID3, FLAC, M4A, OGG), front cover first, or None."""
    try:
        import mutagen
        from mutagen.id3 import ID3, ID3NoHeaderError
    except ImportError:
        return None
    try:
        f = mutagen.File(str(audio_path))
    except Exception:
        f = None
    pics = []  # (front cover?, data)
    tags = getattr(f, "tags", None)
    if f is None or tags is None:  # e.g. an MP3 mutagen can't read frames of: try its ID3 tag alone
        try:
            tags = ID3(str(audio_path))
        except (ID3NoHeaderError, Exception):
            tags = None
    if tags is not None and hasattr(tags, "getall"):  # ID3
        pics += [(p.type == 3, p.data) for p in tags.getall("APIC")]
    for p in getattr(f, "pictures", None) or []:  # FLAC
        pics.append((p.type == 3, p.data))
    if tags is not None and "covr" in tags:  # MP4
        pics += [(True, bytes(c)) for c in tags["covr"]]
    if tags is not None and "metadata_block_picture" in tags:  # Ogg Vorbis / Opus
        import base64

        from mutagen.flac import Picture
        for b in tags["metadata_block_picture"]:
            try:
                p = Picture(base64.b64decode(b))
                pics.append((p.type == 3, p.data))
            except Exception:
                pass
    pics.sort(key=lambda p: not p[0])
    return pics[0][1] if pics else None


def save_cover(data, dest, px=COVER_PX):
    """Scale picture bytes to a centred px x px square and save as JPEG. False if they aren't a picture."""
    img = QImage.fromData(data)
    if img.isNull():
        return False
    img = img.scaled(px, px, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    img = img.copy((img.width() - px) // 2, (img.height() - px) // 2, px, px)
    return img.save(str(dest), "JPG", 88)


def find_cover(midi_path):
    """The cached cover of a song, extracting it from the song file the first time. None if there's no art."""
    dest = cover_file(midi_path)
    if dest.exists():
        return dest
    source = read_metadata(midi_path).get("source")
    if not source or not Path(source).is_file():
        return None
    data = embedded_art(source)
    if data and save_cover(data, dest):
        return dest
    return None


def generated_tile(title, px=COVER_PX):
    """A tile for songs without art: a diagonal gradient picked from the name, with the song's initials."""
    song, _ = split_title(title)
    h = int(hashlib.md5(song.lower().encode("utf-8")).hexdigest()[:8], 16)
    hue = h % 360
    c1 = QColor.fromHsl(hue, 120, 92)
    c2 = QColor.fromHsl((hue + 40 + (h >> 9) % 60) % 360, 140, 46)
    img = QImage(px, px, QImage.Format_RGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, px, px)
    g.setColorAt(0, c1)
    g.setColorAt(1, c2)
    p.fillRect(img.rect(), g)
    # concentric rings in a corner (a drum seen from above); the initials go bottom left, clear of badges
    p.setPen(QPen(QColor(255, 255, 255, 26), px * 0.025))
    for k in range(1, 5):
        r = px * 0.16 * k
        p.drawEllipse(QPointF(px * 0.85, px * 0.15), r, r)
    words = [w for w in song.replace("-", " ").split() if w[:1].isalnum()]
    initials = "".join(w[0] for w in words[:2]).upper() or "?"
    f = QFont()
    f.setPixelSize(round(px * 0.3))
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor(255, 255, 255, 230))
    p.drawText(QRectF(px * 0.1, px * 0.45, px * 0.8, px * 0.47), Qt.AlignLeft | Qt.AlignBottom, initials)
    p.end()
    return img


class _Job(QRunnable):
    def __init__(self, loader, path):
        super().__init__()
        self.loader, self.path = loader, path

    def run(self):
        try:
            found = find_cover(self.path)
        except Exception:
            found = None
        self.loader.found.emit(str(self.path), str(found) if found else "")


class CoverLoader(QObject):
    """Finds covers off the UI thread (song files can be slow to read, e.g. on a network drive):
    request(path) emits found(midi path, cover path or "") once per path."""

    found = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.done = {}
        self.found.connect(self._store)  # a method of this (UI-thread) object, so it's queued to the UI thread

    def _store(self, path, cover):
        self.done[path] = cover

    def request(self, midi_path):
        """The cover path if already known ("" for none), otherwise None and found is emitted later."""
        key = str(midi_path)
        if key in self.done:
            return self.done[key]
        if cover_file(midi_path).exists():
            self.done[key] = str(cover_file(midi_path))
            return self.done[key]
        self.done[key] = None  # in progress
        self.pool.start(_Job(self, midi_path))
        return None

    def forget(self, midi_path):
        self.done.pop(str(midi_path), None)
