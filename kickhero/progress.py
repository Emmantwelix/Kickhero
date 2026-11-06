"""Practice history in SQLite (%APPDATA%/Kickhero/progress.db): every finished run, best scores, streaks."""

import datetime as dt
import sqlite3

from .settings import data_dir


class Progress:
    def __init__(self, path=None):
        self.db = sqlite3.connect(str(path or data_dir() / "progress.db"))
        self.db.execute("""CREATE TABLE IF NOT EXISTS runs (
            lesson TEXT, played_at TEXT, speed REAL, accuracy REAL, stars INTEGER)""")
        self.db.commit()

    def record(self, lesson, speed, summary, when=None):
        when = when or dt.datetime.now()
        self.db.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?)",
                        (str(lesson), when.isoformat(timespec="seconds"), speed, summary["accuracy"],
                         summary["stars"]))
        self.db.commit()

    def best(self, lesson):
        """(stars, accuracy, speed) of the best full-speed-or-slower run, or None."""
        row = self.db.execute("SELECT stars, accuracy, speed FROM runs WHERE lesson = ? "
                              "ORDER BY speed >= 1.0 DESC, stars DESC, accuracy DESC LIMIT 1", (str(lesson),)).fetchone()
        return row

    def passed(self, lesson, min_speed=0.999):
        """At least one star at (close to) full speed."""
        return self.db.execute("SELECT 1 FROM runs WHERE lesson = ? AND speed >= ? AND stars >= 1 LIMIT 1",
                               (str(lesson), min_speed)).fetchone() is not None

    def streak(self, today=None):
        """Days in a row (ending today or yesterday) with at least one run."""
        days = {r[0][:10] for r in self.db.execute("SELECT played_at FROM runs")}
        day = today or dt.date.today()
        if day.isoformat() not in days:
            day -= dt.timedelta(days=1)
        n = 0
        while day.isoformat() in days:
            n += 1
            day -= dt.timedelta(days=1)
        return n
