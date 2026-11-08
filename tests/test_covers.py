import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage  # noqa: E402

from kickhero.ui.covers import find_cover, generated_tile, split_title  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def app():
    yield QGuiApplication.instance() or QGuiApplication([])


def png_bytes(w, h, color):
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(color))
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def song_folder(tmp_path, source):
    folder = tmp_path / "Song - Artist"
    folder.mkdir()
    midi = folder / "Song - Artist_drums.mid"
    midi.write_bytes(b"")
    midi.with_suffix(".json").write_text(json.dumps({"source": str(source)}), encoding="utf-8")
    return midi


def test_split_title():
    assert split_title("Chop Suey - System of a Down") == ("Chop Suey", "System of a Down")
    assert split_title("Hey - Ho - Band") == ("Hey - Ho", "Band")
    assert split_title("break beat") == ("break beat", "")
    assert split_title(" - Artist") == ("- Artist", "")


def test_front_cover_from_the_song_file_is_cached_square(tmp_path):
    mutagen_id3 = pytest.importorskip("mutagen.id3")
    source = tmp_path / "song.mp3"
    source.write_bytes(b"")
    tag = mutagen_id3.ID3()
    tag.add(mutagen_id3.APIC(encoding=3, mime="image/png", type=0, desc="other", data=png_bytes(20, 20, "#0000ff")))
    tag.add(mutagen_id3.APIC(encoding=3, mime="image/png", type=3, desc="front", data=png_bytes(300, 200, "#ff0000")))
    tag.save(str(source))
    midi = song_folder(tmp_path, source)
    cover = find_cover(midi)
    assert cover == midi.parent / "cover.jpg"
    img = QImage(str(cover))
    assert img.width() == img.height() == 480
    assert QColor(img.pixel(240, 240)).red() > 200  # the front cover, not the other picture
    source.unlink()
    assert find_cover(midi) == cover  # cached


def test_no_art_or_no_song_file_means_no_cover(tmp_path):
    source = tmp_path / "plain.wav"
    source.write_bytes(b"RIFF0000WAVE")
    assert find_cover(song_folder(tmp_path, source)) is None
    source.unlink()
    assert find_cover(tmp_path / "Song - Artist" / "Song - Artist_drums.mid") is None


def test_generated_tile_is_stable_per_song():
    a, b = generated_tile("Everlong - Foo Fighters", 64), generated_tile("Everlong - Someone Else", 64)
    assert a.size().width() == 64 and a == b  # the colour comes from the song name
    assert generated_tile("In the End - Linkin Park", 64) != a
