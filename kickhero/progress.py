"""Practice history in SQLite (%APPDATA%/Kickhero/progress.db): every finished run, best scores, streaks."""

import datetime as dt
import sqlite3

from .settings import data_dir


class Progress:
    def __init__(self, path=None):
        self.db = sqlite3.connect(str(path or data_dir() / "progress.db"))
        self.db.execute("""CREATE TABLE IF NOT EXISTS runs (
            lesson TEXT, played_at TEXT, speed REAL, accuracy REAL, stars INTEGER)""")
        # assisted: played in wait mode (the music waits for every note), which says nothing about timing
        if "assisted" not in [r[1] for r in self.db.execute("PRAGMA table_info(runs)")]:
            self.db.execute("ALTER TABLE runs ADD COLUMN assisted INTEGER NOT NULL DEFAULT 0")
        # time spent playing (every run, finished or stopped), for the daily goal
        self.db.execute("CREATE TABLE IF NOT EXISTS practice_time (played_at TEXT, seconds REAL)")
        self.db.commit()

    def record(self, lesson, speed, summary, when=None, assisted=False):
        when = when or dt.datetime.now()
        self.db.execute("INSERT INTO runs (lesson, played_at, speed, accuracy, stars, assisted) VALUES (?, ?, ?, ?, ?, ?)",
                        (str(lesson), when.isoformat(timespec="seconds"), speed, summary["accuracy"],
                         summary["stars"], int(assisted)))
        self.db.commit()

    def best(self, lesson):
        """(stars, accuracy, speed) of the best full-speed-or-slower run (wait-mode runs don't count), or None."""
        row = self.db.execute("SELECT stars, accuracy, speed FROM runs WHERE lesson = ? AND NOT assisted "
                              "ORDER BY speed >= 1.0 DESC, stars DESC, accuracy DESC LIMIT 1", (str(lesson),)).fetchone()
        return row

    def history(self, lesson, limit=30):
        """The last runs that count (not wait mode), oldest first: (played_at, accuracy, speed, stars)."""
        rows = self.db.execute("SELECT played_at, accuracy, speed, stars FROM runs WHERE lesson = ? AND NOT assisted "
                               "ORDER BY played_at DESC, rowid DESC LIMIT ?", (str(lesson), limit)).fetchall()
        return rows[::-1]

    def passed(self, lesson, min_speed=0.999):
        """At least one star at (close to) full speed, without wait mode."""
        return self.db.execute("SELECT 1 FROM runs WHERE lesson = ? AND speed >= ? AND stars >= 1 AND NOT assisted "
                               "LIMIT 1", (str(lesson), min_speed)).fetchone() is not None

    def add_time(self, seconds, when=None):
        when = when or dt.datetime.now()
        self.db.execute("INSERT INTO practice_time (played_at, seconds) VALUES (?, ?)",
                        (when.isoformat(timespec="seconds"), float(seconds)))
        self.db.commit()

    def seconds_on(self, day=None):
        """Seconds played on a day (default today)."""
        day = (day or dt.date.today()).isoformat()
        row = self.db.execute("SELECT SUM(seconds) FROM practice_time WHERE substr(played_at, 1, 10) = ?",
                              (day,)).fetchone()
        return row[0] or 0.0

    def days_played(self, first, last):
        """The days from first to last (dates, inclusive) with any run or practice time."""
        a, b = first.isoformat(), (last + dt.timedelta(days=1)).isoformat()
        rows = self.db.execute("SELECT played_at FROM runs WHERE played_at >= ? AND played_at < ? UNION "
                               "SELECT played_at FROM practice_time WHERE played_at >= ? AND played_at < ?",
                               (a, b, a, b))
        return {dt.date.fromisoformat(r[0][:10]) for r in rows}

    def recent(self, limit=10):
        """Lessons and songs played most recently first: (key, last played_at)."""
        return self.db.execute("SELECT lesson, MAX(played_at) AS last FROM runs GROUP BY lesson "
                               "ORDER BY last DESC LIMIT ?", (limit,)).fetchall()

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
