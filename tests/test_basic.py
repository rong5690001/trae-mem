import os
import tempfile
import unittest
from pathlib import Path

from trae_mem.compress import contains_private, remove_private
from trae_mem.db import TraeMemDB


class TraeMemBasicTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "mem.sqlite3"
        self.db = TraeMemDB(self.db_path)
        self.db.init_schema()

    def tearDown(self) -> None:
        self.db.close()
        self.tmpdir.cleanup()

    def test_private_redaction(self) -> None:
        s = "a<private>secret</private>b"
        self.assertTrue(contains_private(s))
        self.assertEqual(remove_private(s), "ab")

    def test_session_write_search_timeline(self) -> None:
        sid = self.db.new_session(project_path="/tmp/p")
        obs1 = self.db.add_observation(sid, kind="user", content="我要实现预加载策略")
        obs2 = self.db.add_observation(sid, kind="tool", tool_name="Grep", content="搜索 preload")
        self.db.end_session(sid)

        hits = self.db.search("预加载", limit=10)
        self.assertTrue(any(h.id == obs1 for h in hits) or any("预加载" in h.snippet for h in hits))

        tl = self.db.timeline(obs2, window=60)
        ids = [r["id"] for r in tl]
        self.assertIn(obs1, ids)
        self.assertIn(obs2, ids)


if __name__ == "__main__":
    unittest.main()

