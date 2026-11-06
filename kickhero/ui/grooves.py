"""Groove Lab page: real drum grooves from a groove library installed on this computer (see course.grooves),
by level, with filters. Nothing is locked: play them in any order."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from ..course.grooves import LEVELS, find_folder, load_grooves
from .course import LessonCard
from .fitting import FlowRow


FILTERS = {  # name -> [(button text, test on a GrooveLesson)]
    "kind": [("All", lambda g: True), ("Grooves", lambda g: g.category != "Fill"),
             ("Fills", lambda g: g.category == "Fill")],
    "meter": [("Any time", lambda g: True), ("4/4", lambda g: not g.odd_time), ("Odd time", lambda g: g.odd_time)],
    "density": [("Any density", lambda g: True)] + [(d, lambda g, d=d: g.density == d)
                                                     for d in ("Sparse", "Medium", "Dense")],
}


class GroovesPage(QWidget):
    play = Signal(object)  # GrooveLesson

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.grooves = []
        self.cards = []
        self.choice = {name: 0 for name in FILTERS}
        self.open_levels = {1}  # levels shown expanded (click a level's header to open or close it)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(widgetResizable=True, frameShape=QFrame.NoFrame)
        outer.addWidget(scroll)
        body = QWidget(objectName="root")
        scroll.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(QLabel("Groove Lab", objectName="h1"))
        head.addStretch()
        self.folder_btn = QPushButton("Choose groove folder...")
        self.folder_btn.setToolTip("The groove library's Resources folder (it holds metadata.json, midi and keymaps)")
        self.folder_btn.setFocusPolicy(Qt.NoFocus)
        self.folder_btn.clicked.connect(self._choose_folder)
        head.addWidget(self.folder_btn)
        lay.addLayout(head)
        self.about = QLabel(objectName="muted", wordWrap=True)
        lay.addWidget(self.about)
        self.filters = FlowRow(spacing=6)
        self.filter_btns = []
        for name, options in FILTERS.items():
            group = QButtonGroup(self)
            for i, (text, _) in enumerate(options):
                b = QPushButton(text, checkable=True, checked=i == 0)
                b.setFocusPolicy(Qt.NoFocus)
                group.addButton(b, i)
                self.filters.addWidget(b)
                self.filter_btns.append(b)
            group.idClicked.connect(lambda i, n=name: self._filter(n, i))
            self.filters.addSpacing(14)
        lay.addWidget(self.filters)
        self.list = QVBoxLayout()
        self.list.setSpacing(8)
        lay.addLayout(self.list)
        lay.addStretch()
        self.load()

    def load(self):
        folder = find_folder(self.ctx.settings.data.get("groove_folder", ""))
        self.grooves = load_grooves(folder)
        if self.grooves:
            self.about.setText(f"{len(self.grooves)} grooves and fills played by a real drummer, in {LEVELS} levels "
                               "from easiest to hardest. Play them in any order; short ones repeat until the lesson "
                               "is at least 8 bars.")
        else:
            self.about.setText("Practise grooves played by a real drummer: choose your groove library's folder "
                               "(the one holding metadata.json).")
        for b in self.filter_btns:
            b.setVisible(bool(self.grooves))
        self._build()

    def _choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Groove library folder",
                                                  self.ctx.settings.data.get("groove_folder", ""))
        if folder:
            self.ctx.settings["groove_folder"] = folder
            self.load()
            self.refresh()

    def _toggle_level(self, level):
        self.open_levels ^= {level}
        self._build()
        self.refresh()

    def _filter(self, name, i):
        self.choice[name] = i
        self._build()
        self.refresh()

    def shown(self):
        tests = [FILTERS[name][i][1] for name, i in self.choice.items()]
        return [g for g in self.grooves if all(t(g) for t in tests)]

    def _build(self):
        while self.list.count():
            item = self.list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.cards = []
        by_level = {}
        for g in self.shown():
            by_level.setdefault(g.level, []).append(g)
        for level, grooves in sorted(by_level.items()):
            box = QWidget()
            col = QVBoxLayout(box)
            col.setContentsMargins(0, 6, 0, 0)
            col.setSpacing(6)
            lo, hi = min(g.bpm for g in grooves), max(g.bpm for g in grooves)
            bpm = f"{lo:.0f}" if lo == hi else f"{lo:.0f}-{hi:.0f}"
            ends = {1: "  ·  easiest", LEVELS: "  ·  hardest"}.get(level, "")
            is_open = level in self.open_levels
            done = sum(self.ctx.progress.passed(g.key) for g in grooves)
            header = QPushButton(f"{'▾' if is_open else '▸'}   Level {level}{ends}   ·   {len(grooves)} grooves   ·   "
                                 f"{bpm} BPM   ·   {done} passed", objectName="level")
            header.setCursor(Qt.PointingHandCursor)
            header.setFocusPolicy(Qt.NoFocus)
            header.clicked.connect(lambda _=False, lv=level: self._toggle_level(lv))
            col.addWidget(header)
            self.list.addWidget(box)
            if not is_open:
                continue
            grid = QGridLayout()
            grid.setSpacing(10)
            for i, g in enumerate(grooves):
                card = LessonCard(g)
                card.clicked.connect(lambda _=False, g=g: self.play.emit(g))
                grid.addWidget(card, i // 4, i % 4)
                self.cards.append(card)
            for c in range(4):
                grid.setColumnStretch(c, 1)
            col.addLayout(grid)
        if self.grooves and not by_level:
            self.list.addWidget(QLabel("No grooves match these filters.", objectName="muted"))

    def refresh(self):
        progress = self.ctx.progress
        for card in self.cards:
            card.set_state(progress.best(card.lesson.key), True, progress.passed(card.lesson.key))

    def showEvent(self, e):
        self.refresh()
        super().showEvent(e)

    def lesson_after(self, groove):
        """The next groove in the list as filtered (None after the last)."""
        shown = self.shown()
        ids = [g.id for g in shown]
        i = ids.index(groove.id) if groove.id in ids else -1
        return shown[i + 1] if 0 <= i < len(shown) - 1 else None
