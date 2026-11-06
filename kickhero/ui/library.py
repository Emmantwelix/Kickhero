"""Songs page: add songs (they're converted in the background) and pick one to practise."""

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QMenu,
                               QMessageBox, QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from ..engine.lesson import load_midi, read_metadata
from ..pipeline.song2drums import DEFAULT_MODEL_DIR, SONG_EXTS
from ..pipeline.worker import ConvertJob
from .convert_settings import ConvertSettingsDialog


def song_files(paths):
    out = []
    for p in map(Path, paths):
        if p.is_dir():
            out += sorted(f for f in p.rglob("*") if f.suffix.lower() in SONG_EXTS)
        elif p.suffix.lower() in SONG_EXTS:
            out.append(p)
    return out


class LibraryPage(QWidget):
    practise = Signal(object)  # Path of the MIDI file

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.paths = []
        self.job = None
        self.queue = []
        self.setAcceptDrops(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(12)

        head = QHBoxLayout()
        title = QVBoxLayout()
        title.addWidget(QLabel("Songs", objectName="h1"))
        self.subtitle = QLabel(objectName="muted")
        title.addWidget(self.subtitle)
        head.addLayout(title)
        head.addStretch()
        add = QPushButton("+  Add songs...")
        add.clicked.connect(self.add_songs)
        settings = QPushButton("Conversion settings")
        settings.clicked.connect(self.edit_settings)
        folder = QPushButton("Open folder")
        folder.clicked.connect(self.open_folder)
        self.go = QPushButton("Practise  ▶")
        self.go.setObjectName("primary")
        self.go.clicked.connect(self._practise_selected)
        for b in (add, settings, folder, self.go):
            head.addWidget(b)
        lay.addLayout(head)

        # conversion progress (hidden when idle)
        self.card = QFrame(objectName="card")
        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(18, 12, 18, 14)
        row = QHBoxLayout()
        self.conv_status = QLabel()
        self.conv_status.setStyleSheet("font-weight: 600;")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_conversion)
        row.addWidget(self.conv_status, 1)
        row.addWidget(self.stop_btn)
        cl.addLayout(row)
        self.bar = QProgressBar(textVisible=False, maximum=1000)
        self.bar.setFixedHeight(8)
        cl.addWidget(self.bar)
        self.conv_note = QLabel(objectName="muted", wordWrap=True)
        cl.addWidget(self.conv_note)
        self.card.hide()
        lay.addWidget(self.card)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Song", "Tempo", "Length", "Difficulty", "Play-along", "Best"])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for c in range(1, 6):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.cellDoubleClicked.connect(lambda r, _: self.practise.emit(self.paths[r]))
        lay.addWidget(self.table, 1)

        self.empty = QLabel(objectName="muted", alignment=Qt.AlignCenter, wordWrap=True)
        lay.addWidget(self.empty)

    # ---------- song list ----------

    def refresh(self):
        folder = self.ctx.settings.library_dir
        files = sorted(Path(folder).rglob("*.mid")) if Path(folder).is_dir() else []
        selected = self._selected_path()
        self.paths = []
        self.table.setRowCount(0)
        for f in files:
            try:
                lesson = load_midi(f, quantize=16)
            except Exception:
                continue
            r = self.table.rowCount()
            self.table.insertRow(r)
            mins, secs = divmod(int(lesson.length), 60)
            best = self.ctx.progress.best(f)
            diff = lesson.difficulty()
            cells = [lesson.title, f"{lesson.bpm:.0f} BPM", f"{mins}:{secs:02d}",
                     "●" * ((diff + 1) // 2) + "○" * (5 - (diff + 1) // 2),
                     "♫" if lesson.backing else "",
                     ("★" * best[0] + "☆" * (3 - best[0]) + f"  {best[1] * 100:.0f}%") if best else "-"]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c:
                    item.setTextAlignment(Qt.AlignCenter)
                if c == 4 and not lesson.backing:
                    item.setToolTip("Convert this song again to add the play-along track")
                self.table.setItem(r, c, item)
            self.paths.append(f)
        n = len(self.paths)
        self.subtitle.setText(f"{n} song{'s' if n != 1 else ''}  ·  drag songs here, or click Add songs")
        self.empty.setText("" if n else "No songs yet. Click \"Add songs...\" or drag audio files (mp3, wav, flac...) "
                                          "onto this window. Each song takes a few minutes to convert.")
        self.empty.setVisible(not n)
        if n:
            self.table.selectRow(self.paths.index(selected) if selected in self.paths else 0)

    def _selected_path(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return self.paths[rows[0].row()] if rows and rows[0].row() < len(self.paths) else None

    def _practise_selected(self):
        p = self._selected_path()
        if p:
            self.practise.emit(p)

    def _context_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        path = self.paths[row]
        source = read_metadata(path).get("source")
        menu = QMenu(self)
        menu.addAction("Practise", lambda: self.practise.emit(path))
        if source and Path(source).exists():
            menu.addAction("Convert again (with the current conversion settings)", lambda: self.convert([source]))
        else:
            menu.addAction("Convert again: add the song file again (original not found)").setEnabled(False)
        menu.addAction("Show in folder", lambda: os.startfile(path.parent))
        menu.exec(self.table.viewport().mapToGlobal(pos))

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

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and song_files(u.toLocalFile() for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.convert([u.toLocalFile() for u in e.mimeData().urls()])

    def convert(self, paths):
        songs = song_files(p for p in paths if p)
        if not songs:
            return
        if self.job and self.job.running:
            self.queue += songs
            self.conv_note.setText(f"{len(self.queue)} more song(s) queued.")
            return
        out = self.ctx.settings.library_dir
        out.mkdir(parents=True, exist_ok=True)
        self.job = ConvertJob(songs, out, self.ctx.settings["convert"], self)
        self.job.status.connect(self.conv_status.setText)
        self.job.fraction.connect(lambda f: self.bar.setValue(int(f * 1000)))
        self.job.song_done.connect(lambda *_: self.refresh())
        self.job.finished.connect(self._job_finished)
        self.job.log.connect(lambda line: setattr(self, "_last_log", line))
        self._last_log = ""
        first_time = not (Path(DEFAULT_MODEL_DIR) / "htdemucs_ft.yaml").exists()
        self.conv_note.setText("First conversion: downloading the separation models (about 1 GB, once only)..."
                               if first_time else "Each song takes a few minutes. You can keep practising meanwhile.")
        self.bar.setValue(0)
        self.stop_btn.setEnabled(True)
        self.card.show()
        self.job.start()

    def stop_conversion(self):
        self.queue.clear()
        if self.job:
            self.job.stop()

    def _job_finished(self, ok, failed):
        self.refresh()
        if self.queue:
            nxt, self.queue = self.queue, []
            self.job = None
            self.convert(nxt)
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
        self.conv_note.setText("")

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
