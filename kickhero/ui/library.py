"""Songs page: a grid of song cards (search, sort, filters) with a detail panel for the selected song; add songs
(they're converted in the background) or MIDI files."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu,
                               QMessageBox, QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ..engine.editing import is_backup
from ..engine.difficulty import Rating
from ..engine.lesson import load_midi, read_metadata
from ..pipeline.midi_import import CLEAR_LEAD, MidiImportError, fit_verdict, import_midi
from ..pipeline.song2drums import DEFAULT_MODEL_DIR, SONG_EXTS
from ..pipeline.worker import ConvertJob
from . import theme
from .convert_settings import ConvertSettingsDialog
from .covers import CoverLoader, generated_tile, split_title
from .drawing import DIFFICULTY_COLORS, draw_grade, draw_stars, icon, mix, qc
from .fitting import ElidedLabel
from .midi_import import MidiImportDialog
from .widgets import CardGrid, HoverFade, Sparkline, chip, icon_button, rounded_pixmap

MIDI_EXTS = {".mid", ".midi", ".rmi"}

SORTS = [("Recently added", lambda s: -s.added), ("Title A-Z", lambda s: s.song.lower()),
         ("Artist A-Z", lambda s: (s.artist.lower() or "￿", s.song.lower())),
         ("Easiest first", lambda s: (s.difficulty, s.song.lower())),
         ("Hardest first", lambda s: (-s.difficulty, s.song.lower()))]

FIT_TEXT = {"good": (theme.GOOD, "The MIDI file lines up with the recording"),
            "unclear": (theme.WARN, "The MIDI file may not line up with the recording: check it, and fix it with Edit"),
            "beat_off": (theme.WARN, "The MIDI file may be a beat off from the recording: check it, and move it "
                                     "with Edit")}


def song_files(paths):
    out = []
    for p in map(Path, paths):
        if p.is_dir():
            out += sorted(f for f in p.rglob("*") if f.suffix.lower() in SONG_EXTS)
        elif p.suffix.lower() in SONG_EXTS:
            out.append(p)
    return out


def midi_files(paths):
    return [p for p in map(Path, paths) if p.suffix.lower() in MIDI_EXTS and p.is_file()]


def mmss(seconds):
    mins, secs = divmod(int(seconds), 60)
    return f"{mins}:{secs:02d}"


@dataclass
class Song:
    path: Path
    title: str
    bpm: float
    length: float
    meter: str
    rating: Rating
    notes: int
    backing: bool
    best: tuple | None    # (stars, accuracy, speed)
    added: float          # when the drum part was made (for "recently added")
    meta: dict = field(default_factory=dict)

    @property
    def song(self):
        return split_title(self.title)[0]

    @property
    def artist(self):
        return split_title(self.title)[1]

    @property
    def length_text(self):
        return mmss(self.length)

    @property
    def difficulty(self):
        return self.rating.score

    def fit(self):
        """How well an imported MIDI file lines up with the recording ("good", ...), or None."""
        m = self.meta
        if "fit" in m:
            return m["fit"]
        if "match" in m and "match_beat_off" in m:
            sound = (m["sound"], m["sound_beat_off"]) if "sound" in m else None
            return fit_verdict(m["match"], m["match_beat_off"], sound)
        return None


def load_songs(folder, progress):
    """Every song (drum part) in the library folder, with its best score."""
    folder = Path(folder)
    files = sorted(f for f in folder.rglob("*.mid") if not is_backup(f)) if folder.is_dir() else []
    songs = []
    for f in files:
        try:
            lesson = load_midi(f, quantize=16)
        except Exception:
            continue
        try:
            added = f.stat().st_ctime
        except OSError:
            added = 0.0
        songs.append(Song(path=f, title=lesson.title, bpm=lesson.bpm, length=lesson.length, meter=lesson.meter,
                          rating=lesson.rating(), notes=len(lesson.notes), backing=bool(lesson.backing),
                          best=progress.best(f), added=added, meta=read_metadata(f)))
    return songs


class SongCard(QWidget):
    """One song: cover art, title, artist, tempo and length, difficulty and best stars. Click to select,
    double-click (or the play button on hover) to practise."""

    clicked = Signal(object)
    play = Signal(object)
    menu = Signal(object, object)  # song, global pos

    TEXT_H = 74

    def __init__(self, song, parent=None):
        super().__init__(parent)
        self.song = song
        self.image = None
        self.selected = False
        self.hover = False
        self.fade = HoverFade(self)
        self._pm = None
        self.setAttribute(Qt.WA_Hover)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        tip = song.title + ("\nPlays along with the song" if song.backing else "")
        self.setToolTip(tip)

    def height_for(self, width):
        return width + self.TEXT_H

    def set_image(self, img):
        self.image = img
        self._pm = None
        self.update()

    def set_selected(self, on):
        if on != self.selected:
            self.selected = on
            self.update()

    def _play_rect(self):
        w = self.width()
        return QRectF(w - 52, w - 52, 40, 40)

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            if self.hover and self._play_rect().contains(e.position()):
                self.play.emit(self.song)
            else:
                self.clicked.emit(self.song)
        elif e.button() == Qt.RightButton:
            self.clicked.emit(self.song)
            self.menu.emit(self.song, e.globalPosition().toPoint())

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.play.emit(self.song)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = 12
        card = QRectF(0.5, 0.5, w - 1, h - 1)
        t = self.fade.t
        p.setPen(QPen(qc(theme.ACCENT) if self.selected else mix(theme.BORDER, theme.SURFACE_3, t),
                      2 if self.selected else 1))
        p.setBrush(qc(theme.PANEL_2) if self.selected else mix(theme.PANEL, theme.PANEL_2, t))
        p.drawRoundedRect(card, r, r)
        # cover
        if self.image is not None:
            if self._pm is None or self._pm.deviceIndependentSize().width() != w - 2:
                self._pm = rounded_pixmap(self.image, w - 2, w - 2, r - 1, top_only=True)
            p.drawPixmap(1, 1, self._pm)
        else:
            path = QPainterPath()
            path.addRoundedRect(QRectF(1, 1, w - 2, w - 2 + r), r - 1, r - 1)
            p.setClipPath(path)
            p.fillRect(QRectF(1, 1, w - 2, w - 2), qc(theme.PANEL_2))
            p.setClipping(False)
        if self.song.backing:  # play-along badge
            p.setPen(Qt.NoPen)
            p.setBrush(qc("#000000", 0.55))
            badge = QRectF(10, 10, 26, 22)
            p.drawRoundedRect(badge, 11, 11)
            p.drawPixmap(round(badge.x() + 6), round(badge.y() + 4), icon("note", "#ffffff", 14))
        if self.song.best:  # best stars
            p.setPen(Qt.NoPen)
            p.setBrush(qc("#000000", 0.55))
            badge = QRectF(w - 64, 10, 54, 22)
            p.drawRoundedRect(badge, 11, 11)
            draw_stars(p, badge.x() + 7, badge.y() + 5, self.song.best[0], size=12, gap=1)
        if self.hover:  # play button
            pr = self._play_rect()
            p.setPen(Qt.NoPen)
            p.setBrush(qc(theme.ACCENT))
            p.drawEllipse(pr)
            p.drawPixmap(round(pr.x() + 11), round(pr.y() + 10), icon("play", "#1a0f0b", 20))
        # text
        x, y, tw = 12, w + 8, w - 24
        f = p.font()
        f.setPointSizeF(10.5)
        f.setBold(True)
        p.setFont(f)
        p.setPen(qc(theme.TEXT))
        p.drawText(QRectF(x, y, tw, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(self.song.song, Qt.ElideRight, tw))
        f.setPointSizeF(9)
        f.setBold(False)
        p.setFont(f)
        p.setPen(qc(theme.MUTED))
        p.drawText(QRectF(x, y + 20, tw, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(self.song.artist or " ", Qt.ElideRight, tw))
        y += 44
        draw_grade(p, x, y, self.song.rating.grade)
        p.setPen(qc(theme.FAINT))
        odd = "" if self.song.meter == "4/4" else f" · {self.song.meter}"
        meta = f"{self.song.bpm:.0f} BPM{odd} · {self.song.length_text}"
        p.drawText(QRectF(x + 24, y, tw - 24, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(meta, Qt.ElideRight, tw - 24))
        p.end()


class DetailPanel(QFrame):
    """The selected song: big cover, details, best score and recent runs, and what you can do with it."""

    WIDTH = 284
    COVER = 112

    def __init__(self, page):
        super().__init__(objectName="card")
        self.page = page
        self.song = None
        self.setFixedWidth(self.WIDTH)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(widgetResizable=True, frameShape=QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(14)
        self.cover = QLabel()
        self.cover.setFixedSize(self.COVER, self.COVER)
        top.addWidget(self.cover, 0, Qt.AlignTop)
        names = QVBoxLayout()
        names.setSpacing(4)
        self.title = QLabel(objectName="h2", wordWrap=True)
        self.artist = QLabel(objectName="muted", wordWrap=True)
        names.addWidget(self.title)
        names.addWidget(self.artist)
        names.addStretch()
        top.addLayout(names, 1)
        lay.addLayout(top)
        lay.addSpacing(6)
        self.go = QPushButton("  Practise", objectName="primary")
        self.go.setIcon(icon("play", "#1a0f0b", 14))
        self.go.setCursor(Qt.PointingHandCursor)
        self.go.clicked.connect(lambda: self.song and page.practise.emit(self.song.path))
        lay.addWidget(self.go)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.edit_btn = icon_button("edit", "Edit drum part", "Fix the drum part: add, move or delete notes, "
                                    "dynamics, tempo and bar 1")
        self.edit_btn.clicked.connect(lambda: self.song and page.edit.emit(self.song.path))
        self.more_btn = icon_button("more", tip="More: convert again, show in folder")
        self.more_btn.clicked.connect(lambda: self.song and page.song_menu(
            self.song, self.more_btn.mapToGlobal(self.more_btn.rect().bottomLeft())))
        row.addWidget(self.edit_btn, 1)
        row.addWidget(self.more_btn)
        lay.addLayout(row)
        lay.addSpacing(6)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        self.stats = {}
        for i, (key, label) in enumerate((("tempo", "Tempo"), ("length", "Length"), ("level", "Difficulty"),
                                          ("notes", "Notes"))):
            cell = QVBoxLayout()
            cell.setSpacing(0)
            cell.addWidget(QLabel(label.upper(), objectName="group"))
            self.stats[key] = QLabel(objectName="h3")
            cell.addWidget(self.stats[key])
            grid.addLayout(cell, i // 2, i % 2)
        lay.addLayout(grid)
        self.why = QLabel(objectName="caption", wordWrap=True)
        self.why.setTextFormat(Qt.RichText)
        lay.addWidget(self.why)
        self.playalong = QLabel(objectName="caption", wordWrap=True)
        lay.addWidget(self.playalong)
        self.fit = QLabel(objectName="caption", wordWrap=True)
        lay.addWidget(self.fit)
        lay.addSpacing(4)
        lay.addWidget(QLabel("BEST SCORE", objectName="group"))
        self.best = QLabel(objectName="h3", wordWrap=True)
        self.best.setTextFormat(Qt.RichText)
        lay.addWidget(self.best)
        self.runs_label = QLabel(objectName="caption")
        lay.addWidget(self.runs_label)
        self.spark = Sparkline(44)
        lay.addWidget(self.spark)
        lay.addStretch()

    def show_song(self, song, image):
        self.song = song
        image = image if image is not None else generated_tile(song.title)
        self.cover.setPixmap(rounded_pixmap(image, self.COVER, self.COVER, 10))
        self.title.setText(song.song)
        self.artist.setText(song.artist)
        self.artist.setVisible(bool(song.artist))
        self.stats["tempo"].setText(f"{song.bpm:.0f} BPM" + ("" if song.meter == "4/4" else f"  ·  {song.meter}"))
        self.stats["length"].setText(song.length_text)
        r = song.rating
        self.stats["level"].setTextFormat(Qt.RichText)
        self.stats["level"].setText(f"<span style='color:{DIFFICULTY_COLORS[r.grade]}'>{r.grade_name}</span> "
                                    f"<span style='color:{theme.MUTED}'>{r.level}/10</span>")
        why = ", ".join([r.reasons[0]] + [x[0].lower() + x[1:] for x in r.reasons[1:]]) if r.reasons             else "A steady, simple beat"
        hardest = f"<br>Hardest part around {mmss(r.hardest)}" if r.reasons and r.hardest else ""
        self.why.setText(f"<b>Why:</b> {why}.{hardest}")
        self.stats["notes"].setText(f"{song.notes:,}")
        self.playalong.setText("Plays along with the song itself (its drums taken out)." if song.backing else
                               "No play-along track. Convert the song again to add one.")
        fit = song.fit()
        self.fit.setVisible(fit in FIT_TEXT)
        if fit in FIT_TEXT:
            color, text = FIT_TEXT[fit]
            self.fit.setText(f"<span style='color:{color}'>●</span>&nbsp; {text}")
        if song.best:
            stars, acc, speed = song.best
            star_html = "".join(f"<span style='color:{theme.WARN if i < stars else theme.FAINT}'>★</span>"
                                for i in range(3))
            at = "" if speed >= 0.999 else f" <span style='color:{theme.MUTED}'>at {speed * 100:.0f}% speed</span>"
            self.best.setText(f"{star_html}&nbsp; {acc * 100:.0f}%{at}")
        else:
            self.best.setText(f"<span style='color:{theme.MUTED}'>Not played yet</span>")
        runs = self.page.ctx.progress.history(song.path)
        self.spark.set_values([r[1] for r in runs])
        self.spark.setVisible(len(runs) > 1)
        self.runs_label.setText(f"Accuracy over your last {len(runs)} runs" if len(runs) > 1 else "")
        self.runs_label.setVisible(len(runs) > 1)


class LibraryPage(QWidget):
    practise = Signal(object)  # Path of the MIDI file
    edit = Signal(object)      # Path of the MIDI file

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.songs = []        # every song in the library
        self.shown = []        # after search and filters, sorted
        self.cards = {}        # path -> SongCard
        self.images = {}       # path -> QImage (cover or generated)
        self.selected = None   # Path
        self.job = None
        self.queue = []
        self.covers = CoverLoader(self)
        self.covers.found.connect(self._cover_found)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(14)

        head = QHBoxLayout()
        head.setSpacing(10)
        title = QVBoxLayout()
        title.setSpacing(2)
        title.addWidget(QLabel("Songs", objectName="h1"))
        self.subtitle = ElidedLabel(objectName="muted")
        title.addWidget(self.subtitle)
        head.addLayout(title, 1)
        self.search = QLineEdit(placeholderText="Search songs or artists")
        self.search.addAction(icon("search", theme.MUTED, 16), QLineEdit.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(240)
        self.search.textChanged.connect(self._apply)
        head.addWidget(self.search)
        add = QPushButton("  Add", objectName="primary")
        add.setIcon(icon("plus", "#1a0f0b", 14))
        add.setCursor(Qt.PointingHandCursor)
        add_menu = QMenu(add)
        add_menu.addAction("Song file (mp3, wav, flac...)...", self.add_songs)
        add_menu.addAction("MIDI file of a song...", self.add_midi)
        add.setMenu(add_menu)
        head.addWidget(add)
        more = icon_button("more", tip="Conversion settings, songs folder")
        more_menu = QMenu(more)
        more_menu.addAction("Conversion settings...", self.edit_settings)
        more_menu.addAction("Open songs folder", self.open_folder)
        more.clicked.connect(lambda: more_menu.exec(more.mapToGlobal(more.rect().bottomLeft())))
        head.addWidget(more)
        lay.addLayout(head)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.f_backing = chip("Play-along", "Songs you can play along with (the song with its drums taken out)")
        self.f_new = chip("Not played", "Songs you haven't played yet")
        self.f_improve = chip("Under 3 stars", "Songs you haven't got 3 stars on yet")
        for c in (self.f_backing, self.f_new, self.f_improve):
            c.toggled.connect(self._apply)
            filters.addWidget(c)
        filters.addStretch()
        filters.addWidget(QLabel("Sort", objectName="caption"))
        self.sort = QComboBox()
        self.sort.addItems([name for name, _ in SORTS])
        self.sort.currentIndexChanged.connect(self._apply)
        filters.addWidget(self.sort)
        lay.addLayout(filters)

        body = QHBoxLayout()
        body.setSpacing(20)
        self.scroll = QScrollArea(widgetResizable=True, frameShape=QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(0, 0, 6, 0)
        self.grid = CardGrid(min_width=136, gap=14)
        hl.addWidget(self.grid)
        hl.addStretch()
        self.scroll.setWidget(holder)
        body.addWidget(self.scroll, 1)

        self.empty = QWidget()
        el = QVBoxLayout(self.empty)
        el.addStretch()
        empty_icon = QLabel(alignment=Qt.AlignCenter)
        empty_icon.setPixmap(icon("songs", theme.FAINT, 48))
        el.addWidget(empty_icon)
        self.empty_title = QLabel(objectName="h2", alignment=Qt.AlignCenter)
        el.addWidget(self.empty_title)
        self.empty_text = QLabel(objectName="muted", alignment=Qt.AlignCenter, wordWrap=True)
        self.empty_text.setMaximumWidth(460)
        el.addWidget(self.empty_text, 0, Qt.AlignHCenter)
        self.empty_btn = QPushButton("  Add a song", objectName="primary")
        self.empty_btn.setIcon(icon("plus", "#1a0f0b", 14))
        self.empty_btn.clicked.connect(self.add_songs)
        el.addWidget(self.empty_btn, 0, Qt.AlignHCenter)
        el.addStretch()
        body.addWidget(self.empty, 1)

        self.detail = DetailPanel(self)
        body.addWidget(self.detail)
        lay.addLayout(body, 1)

        # conversion progress (hidden when idle): a slim card at the bottom
        self.card = QFrame(objectName="card")
        cl = QHBoxLayout(self.card)
        cl.setContentsMargins(16, 10, 12, 10)
        cl.setSpacing(14)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.conv_status = ElidedLabel()
        self.conv_status.setStyleSheet("font-weight: 600;")
        self.conv_note = QLabel(objectName="caption", wordWrap=True)
        texts.addWidget(self.conv_status)
        texts.addWidget(self.conv_note)
        cl.addLayout(texts, 3)
        self.bar = QProgressBar(textVisible=False, maximum=1000)
        self.bar.setFixedHeight(6)
        cl.addWidget(self.bar, 2)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_conversion)
        cl.addWidget(self.stop_btn)
        self.close_btn = icon_button("close", tip="Hide", flat=True)
        self.close_btn.clicked.connect(self.card.hide)
        cl.addWidget(self.close_btn)
        self.card.hide()
        lay.addWidget(self.card)

    # ---------- song list ----------

    def refresh(self):
        self.songs = load_songs(self.ctx.settings.library_dir, self.ctx.progress)
        old = self.cards
        self.cards = {}
        for s in self.songs:
            card = old.get(s.path)
            if card is not None:
                card.song = s
                card.update()
            else:
                card = SongCard(s)
                card.clicked.connect(lambda song: self.select(song.path))
                card.play.connect(lambda song: self.practise.emit(song.path))
                card.menu.connect(self.song_menu)
            self.cards[s.path] = card
            cover = self.covers.request(s.path)
            if cover:
                self.images[s.path] = QImage(cover)
            elif s.path not in self.images:
                self.images[s.path] = generated_tile(s.title)  # until (or unless) its art turns up
            card.set_image(self.images[s.path])
        for path, card in old.items():
            if path not in self.cards:
                card.deleteLater()
        n = len(self.songs)
        self.subtitle.setText(f"{n} song{'s' if n != 1 else ''}  ·  drag songs or MIDI files here to add them")
        self._apply()

    def _cover_found(self, path, cover):
        path = Path(path)
        if cover and path in self.cards:
            self.images[path] = QImage(cover)
            self.cards[path].set_image(self.images[path])
            if path == self.selected:
                self._show_detail()

    def _apply(self, *_):
        """Search, filter and sort the cards."""
        words = self.search.text().lower().split()
        shown = []
        for s in self.songs:
            if words and not all(w in s.title.lower() for w in words):
                continue
            if self.f_backing.isChecked() and not s.backing:
                continue
            if self.f_new.isChecked() and s.best:
                continue
            if self.f_improve.isChecked() and s.best and s.best[0] >= 3:
                continue
            shown.append(s)
        shown.sort(key=SORTS[self.sort.currentIndex()][1])
        self.shown = shown
        self.grid.set_cards([self.cards[s.path] for s in shown])
        any_songs = bool(self.songs)
        self.scroll.setVisible(bool(shown))
        self.empty.setVisible(not shown)
        self.detail.setVisible(bool(shown))
        if not any_songs:
            self.empty_title.setText("Add your first song")
            self.empty_text.setText("Add a song file (mp3, wav, flac...) or drag it onto this window: it's turned "
                                    "into a drum lesson in a few minutes. Have a MIDI file of a song? Use Add, "
                                    "then MIDI file.")
        else:
            self.empty_title.setText("No songs match")
            self.empty_text.setText("Try another search, or turn off a filter.")
        self.empty_btn.setVisible(not any_songs)
        paths = [s.path for s in shown]
        if shown:
            self.select(self.selected if self.selected in paths else paths[0])

    def select(self, path):
        self.selected = path
        for p, card in self.cards.items():
            card.set_selected(p == path)
        self._show_detail()
        card = self.cards.get(path)
        if card is not None and card.isVisible():
            self.scroll.ensureWidgetVisible(card, 0, 16)

    def _show_detail(self):
        song = next((s for s in self.songs if s.path == self.selected), None)
        if song is not None:
            self.detail.show_song(song, self.images.get(song.path))

    def _selected_path(self):
        return self.selected if any(s.path == self.selected for s in self.shown) else None

    def _practise_selected(self):
        p = self._selected_path()
        if p:
            self.practise.emit(p)

    def song_menu(self, song, pos):
        path = song.path
        meta = read_metadata(path)
        source = meta.get("source")
        menu = QMenu(self)
        menu.addAction("Practise", lambda: self.practise.emit(path))
        menu.addAction("Edit drum part...", lambda: self.edit.emit(path))
        if source and Path(source).exists():
            menu.addAction("Convert again (fix the tempo, missing or extra notes)...",
                           lambda: self.convert([source], detected_bpm=meta.get("bpm"), meter=meta.get("meter")))
        else:
            menu.addAction("Convert again: add the song file again (original not found)").setEnabled(False)
        menu.addAction("Show in folder", lambda: os.startfile(path.parent))
        menu.exec(pos)

    def keyPressEvent(self, e):
        paths = [s.path for s in self.shown]
        if not paths or self.selected not in paths:
            return super().keyPressEvent(e)
        i, cols = paths.index(self.selected), self.grid.columns
        step = {Qt.Key_Left: -1, Qt.Key_Right: 1, Qt.Key_Up: -cols, Qt.Key_Down: cols}.get(e.key())
        if step is not None:
            self.select(paths[max(0, min(len(paths) - 1, i + step))])
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.practise.emit(self.selected)
        else:
            super().keyPressEvent(e)

    def open_folder(self):
        folder = self.ctx.settings.library_dir
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)

    def showEvent(self, e):
        self.refresh()
        super().showEvent(e)

    # ---------- adding / converting ----------

    def add_songs(self):
        exts = " ".join(f"*{e}" for e in sorted(SONG_EXTS))
        files, _ = QFileDialog.getOpenFileNames(self, "Add songs", str(Path.home() / "Music"),
                                                f"Audio ({exts});;All files (*.*)")
        if files:
            self.convert(files)

    def add_midi(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add MIDI files", str(Path.home() / "Downloads"),
                                                "MIDI files (*.mid *.midi *.rmi);;All files (*.*)")
        for f in files:
            self.import_midi(f)

    def import_midi(self, midi_path):
        """Ask for a name and (optionally) the song's audio, then add the MIDI file's drum part."""
        try:
            dlg = MidiImportDialog(midi_path, self)
        except MidiImportError as e:
            QMessageBox.warning(self, "Can't use this MIDI file", f"{Path(midi_path).name}: {e}")
            return
        if not dlg.exec():
            return
        name, audio = dlg.song_name(), dlg.audio_path()
        library = self.ctx.settings.library_dir
        target = library / name / f"{name}_drums.mid"
        if target.exists() and QMessageBox.question(
                self, "Replace song?", f"\"{name}\" is already in your songs. Replace its drum part with this "
                                      "MIDI file's?") != QMessageBox.Yes:
            return
        if audio:
            self._start([audio], {"midi": str(midi_path), "name": name})
            return
        try:
            path = import_midi(midi_path, library, name)
        except (MidiImportError, OSError) as e:
            QMessageBox.warning(self, "Can't use this MIDI file", str(e))
            return
        self.refresh()
        if path in self.cards:
            self.select(path)

    def dragEnterEvent(self, e):
        urls = [u.toLocalFile() for u in e.mimeData().urls()] if e.mimeData().hasUrls() else []
        if song_files(urls) or midi_files(urls):
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = [u.toLocalFile() for u in e.mimeData().urls()]
        for f in midi_files(urls):
            self.import_midi(f)
        self.convert([u for u in urls if Path(u).suffix.lower() not in MIDI_EXTS])

    def convert(self, paths, detected_bpm=None, meter=None):
        """Ask how to convert the songs (tempo, fine-tuning), then convert them or queue them."""
        songs = song_files(p for p in paths if p)
        if not songs:
            return
        dlg = ConvertSettingsDialog(self.ctx.settings["convert"], self, songs=songs, detected_bpm=detected_bpm,
                                    meter=meter)
        if not dlg.exec():
            return
        self.ctx.settings["convert"] = dlg.result_options()
        self._start(songs, dict(dlg.result_options(), bpm=dlg.tempo(), meter=dlg.meter_choice()))

    def _start(self, songs, options):
        if self.job and self.job.running:
            self.queue.append((songs, options))
            n = sum(len(s) for s, _ in self.queue)
            self.conv_note.setText(f"{n} more song{'s' if n != 1 else ''} queued.")
            return
        out = self.ctx.settings.library_dir
        out.mkdir(parents=True, exist_ok=True)
        self.job = ConvertJob(songs, out, options, self)
        self.job.status.connect(self.conv_status.setText)
        self.job.fraction.connect(lambda f: self.bar.setValue(int(f * 1000)))
        self.job.song_done.connect(lambda *_: self.refresh())
        self.job.finished.connect(self._job_finished)
        self.job.log.connect(self._log_line)
        self._last_log = self._match = self._fit = ""
        first_time = not (Path(DEFAULT_MODEL_DIR) / "htdemucs_ft.yaml").exists()
        self.conv_note.setText("First conversion: downloading the separation models (about 1 GB, once only)..."
                               if first_time else "Each song takes a few minutes. You can keep practising meanwhile.")
        self.bar.setValue(0)
        self.stop_btn.setEnabled(True)
        self.card.show()
        self.job.start()

    def _log_line(self, line):
        self._last_log = line
        if "line up with drums heard in the song" in line:
            self._match = line
        elif line.startswith("Fit: "):
            self._fit = line[5:].strip()

    def stop_conversion(self):
        self.queue.clear()
        if self.job:
            self.job.stop()

    def _job_finished(self, ok, failed):
        self.refresh()
        if self.queue:
            self.job = None
            self._start(*self.queue.pop(0))
            return
        self.stop_btn.setEnabled(False)
        if failed:
            self.conv_status.setText(f"Finished: {ok} converted, {failed} failed or stopped.")
            self.bar.setValue(1000)
            self.conv_note.setText(f"Last message from the converter: {self._last_log}" if self._last_log else "")
            return
        else:
            self.conv_status.setText(f"Finished: {ok} song{'s' if ok != 1 else ''} ready to practise.")
        self.bar.setValue(1000)
        self.conv_note.setText(self._match_note())

    def _match_note(self):
        """After lining up a MIDI file: how well it fits the recording (a poor fit is usually another version)."""
        m = re.match(r"(\d+)%.*\((\d+)%", self._match)
        if not m:
            return ""
        pct, off = int(m.group(1)), int(m.group(2))
        fit = self._fit or ("good" if pct - off >= CLEAR_LEAD * 100 else "unclear")
        if fit == "good":
            return f"The MIDI file lines up with the song: {pct}% of its kick and snare notes match the recording."
        if fit == "beat_off":
            return ("The MIDI file may be a beat off from the song: its kick notes sound like snares there. "
                    "Check it in Practise, and move it with Edit if needed.")
        return ("The MIDI file doesn't line up clearly with the song. It may be a different version or "
                "arrangement: check it in Practise, and fix it with Edit if needed.")

    def edit_settings(self):
        dlg = ConvertSettingsDialog(self.ctx.settings["convert"], self)
        if dlg.exec():
            self.ctx.settings["convert"] = dlg.result_options()

    def busy(self):
        return bool(self.job and self.job.running)

    def confirm_close(self):
        if not self.busy():
            return True
        ans = QMessageBox.question(self, "Still converting", "A song is still being converted. Stop it and quit?")
        if ans == QMessageBox.Yes:
            self.stop_conversion()
            return True
        return False
