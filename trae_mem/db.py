import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


def _default_db_path() -> Path:
    env = os.environ.get("TRAE_MEM_DB")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("TRAE_MEM_HOME")
    if base:
        return Path(base).expanduser() / "trae_mem.sqlite3"
    home = Path.home()
    if os.access(str(home), os.W_OK):
        return home / ".trae-mem" / "trae_mem.sqlite3"
    return Path.cwd() / ".trae-mem" / "trae_mem.sqlite3"


def _ensure_parent_dir(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class SearchHit:
    id: str
    ts: int
    kind: str
    tool_name: Optional[str]
    session_id: str
    snippet: str
    score: float


class TraeMemDB:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            chosen = _default_db_path()
            try:
                _ensure_parent_dir(chosen)
            except PermissionError:
                chosen = Path.cwd() / ".trae-mem" / "trae_mem.sqlite3"
                _ensure_parent_dir(chosen)
            self.db_path = chosen
        else:
            self.db_path = db_path
            _ensure_parent_dir(self.db_path)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")

    def close(self) -> None:
        self._conn.close()

    def init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
              id TEXT PRIMARY KEY,
              started_at INTEGER NOT NULL,
              ended_at INTEGER,
              project_path TEXT,
              meta_json TEXT
            );

            CREATE TABLE IF NOT EXISTS observations (
              id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              ts INTEGER NOT NULL,
              kind TEXT NOT NULL,
              tool_name TEXT,
              content TEXT NOT NULL,
              private INTEGER NOT NULL DEFAULT 0,
              tags_json TEXT,
              FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_observations_session_ts
              ON observations(session_id, ts);

            CREATE TABLE IF NOT EXISTS summaries (
              id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              level TEXT NOT NULL,
              content TEXT NOT NULL,
              FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_summaries_session_level
              ON summaries(session_id, level);
            """
        )
        self._conn.commit()

        existing = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='observations_fts'"
        ).fetchone()
        if existing:
            return

        try:
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE observations_fts USING fts5(
                  id UNINDEXED,
                  session_id UNINDEXED,
                  kind,
                  tool_name,
                  content,
                  tokenize = 'trigram'
                )
                """
            )
            self._conn.commit()
            return
        except sqlite3.OperationalError:
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE observations_fts USING fts5(
                  id UNINDEXED,
                  session_id UNINDEXED,
                  kind,
                  tool_name,
                  content,
                  tokenize = 'unicode61'
                )
                """
            )
            self._conn.commit()

    def new_session(self, project_path: Optional[str] = None, meta: Optional[dict[str, Any]] = None) -> str:
        session_id = uuid.uuid4().hex
        started_at = int(time.time())
        meta_json = json.dumps(meta or {}, ensure_ascii=False)
        self._conn.execute(
            "INSERT INTO sessions(id, started_at, project_path, meta_json) VALUES (?, ?, ?, ?)",
            (session_id, started_at, project_path, meta_json),
        )
        self._conn.commit()
        return session_id

    def end_session(self, session_id: str) -> None:
        ended_at = int(time.time())
        self._conn.execute("UPDATE sessions SET ended_at=? WHERE id=?", (ended_at, session_id))
        self._conn.commit()

    def add_observation(
        self,
        session_id: str,
        kind: str,
        content: str,
        tool_name: Optional[str] = None,
        tags: Optional[dict[str, Any]] = None,
        private: bool = False,
        ts: Optional[int] = None,
    ) -> str:
        obs_id = uuid.uuid4().hex
        ts_i = int(ts or time.time())
        tags_json = json.dumps(tags or {}, ensure_ascii=False)
        private_i = 1 if private else 0
        self._conn.execute(
            """
            INSERT INTO observations(id, session_id, ts, kind, tool_name, content, private, tags_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (obs_id, session_id, ts_i, kind, tool_name, content, private_i, tags_json),
        )
        if not private:
            self._conn.execute(
                """
                INSERT INTO observations_fts(id, session_id, kind, tool_name, content)
                VALUES (?, ?, ?, ?, ?)
                """,
                (obs_id, session_id, kind, tool_name or "", content),
            )
        self._conn.commit()
        return obs_id

    def add_summary(self, session_id: str, level: str, content: str) -> str:
        summary_id = uuid.uuid4().hex
        created_at = int(time.time())
        self._conn.execute(
            "INSERT INTO summaries(id, session_id, created_at, level, content) VALUES (?, ?, ?, ?, ?)",
            (summary_id, session_id, created_at, level, content),
        )
        self._conn.commit()
        return summary_id

    def get_session(self, session_id: str) -> Optional[sqlite3.Row]:
        cur = self._conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,))
        return cur.fetchone()

    def get_recent_sessions(self, project_path: Optional[str], limit: int = 10) -> list[sqlite3.Row]:
        if project_path:
            cur = self._conn.execute(
                """
                SELECT * FROM sessions
                WHERE project_path=?
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (project_path, limit),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?",
                (limit,),
            )
        return list(cur.fetchall())

    def get_latest_summary(self, session_id: str, level: str = "brief") -> Optional[sqlite3.Row]:
        cur = self._conn.execute(
            """
            SELECT * FROM summaries
            WHERE session_id=? AND level=?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (session_id, level),
        )
        return cur.fetchone()

    def get_observations(
        self, ids: Iterable[str]
    ) -> list[sqlite3.Row]:
        ids_list = list(ids)
        if not ids_list:
            return []
        placeholders = ",".join("?" for _ in ids_list)
        cur = self._conn.execute(
            f"SELECT * FROM observations WHERE id IN ({placeholders})",
            ids_list,
        )
        rows = list(cur.fetchall())
        rows.sort(key=lambda r: r["ts"])
        return rows

    def get_observations_by_session(
        self, session_id: str, limit: int = 500
    ) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            """
            SELECT * FROM observations
            WHERE session_id=?
            ORDER BY ts ASC
            LIMIT ?
            """,
            (session_id, limit),
        )
        return list(cur.fetchall())

    def search(self, query: str, limit: int = 20) -> list[SearchHit]:
        q = query.strip()
        if not q:
            return []
        hits: list[SearchHit] = []
        try:
            cur = self._conn.execute(
                """
                SELECT
                  o.id AS id,
                  o.ts AS ts,
                  o.kind AS kind,
                  o.tool_name AS tool_name,
                  o.session_id AS session_id,
                  snippet(observations_fts, 4, '[', ']', '…', 12) AS snip,
                  bm25(observations_fts) AS score
                FROM observations_fts
                JOIN observations o ON o.id = observations_fts.id
                WHERE observations_fts MATCH ?
                ORDER BY score
                LIMIT ?
                """,
                (q, limit),
            )
            for r in cur.fetchall():
                hits.append(
                    SearchHit(
                        id=r["id"],
                        ts=r["ts"],
                        kind=r["kind"],
                        tool_name=r["tool_name"] if r["tool_name"] else None,
                        session_id=r["session_id"],
                        snippet=r["snip"],
                        score=float(r["score"]),
                    )
                )
        except sqlite3.OperationalError:
            hits = []

        if hits:
            return hits

        like = f"%{q}%"
        cur2 = self._conn.execute(
            """
            SELECT id, ts, kind, tool_name, session_id, content
            FROM observations
            WHERE private=0 AND content LIKE ?
            ORDER BY ts DESC
            LIMIT ?
            """,
            (like, limit),
        )
        for r in cur2.fetchall():
            content = r["content"] or ""
            snip = content if len(content) <= 120 else content[:119] + "…"
            hits.append(
                SearchHit(
                    id=r["id"],
                    ts=r["ts"],
                    kind=r["kind"],
                    tool_name=r["tool_name"] if r["tool_name"] else None,
                    session_id=r["session_id"],
                    snippet=snip,
                    score=0.0,
                )
            )
        return hits

    def timeline(self, observation_id: str, window: int = 10) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT session_id, ts FROM observations WHERE id=?",
            (observation_id,),
        )
        row = cur.fetchone()
        if not row:
            return []
        session_id = row["session_id"]
        ts = row["ts"]
        cur2 = self._conn.execute(
            """
            SELECT * FROM observations
            WHERE session_id=?
              AND ts BETWEEN ? AND ?
            ORDER BY ts ASC
            """,
            (session_id, ts - window * 60, ts + window * 60),
        )
        return list(cur2.fetchall())
