import json
import sqlite3
from contextlib import closing
from pathlib import Path

from app.modules.m7_publish.supersede import apply_status, supersession


class RunStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def _entries(self, db):
        return [
            (rowid, json.loads(payload))
            for rowid, payload in db.execute("SELECT rowid, payload FROM runs ORDER BY rowid")
        ]

    def get(self, run_id):
        with closing(self.connect()) as db:
            entries = self._entries(db)
        found = next(((rowid, run) for rowid, run in entries if run["运行清单"]["批次"] == run_id), None)
        if found is None:
            return None
        return apply_status(found[1], self._statuses(entries)[run_id])

    def save(self, run_id, data):
        with closing(self.connect()) as db, db:
            result = db.execute(
                "INSERT OR IGNORE INTO runs VALUES (?, ?)", (run_id, json.dumps(data, ensure_ascii=False))
            )
            created = result.rowcount == 1
            payload = db.execute("SELECT payload FROM runs WHERE id=?", (run_id,)).fetchone()[0]
            entries = self._entries(db)
        return apply_status(json.loads(payload), self._statuses(entries)[run_id]), not created

    def entries(self):
        """按写入先后返回全部批次，供判断补签后哪一版仍然有效。"""
        with closing(self.connect()) as db:
            return self._entries(db)

    def history(self):
        with closing(self.connect()) as db:
            entries = self._entries(db)
        statuses = self._statuses(entries)
        history = []
        for _, run in reversed(entries):
            item = dict(run["运行清单"])
            item["版本状态"] = statuses[run["运行清单"]["批次"]]["状态"]
            history.append(item)
        return history[:40]

    @staticmethod
    def _statuses(entries):
        return supersession(entries)
