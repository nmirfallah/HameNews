import json
import os
import tempfile
import unittest

import helpers  # noqa: F401
from trendwatch.store import Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = Store(self._tmp.name)

    def test_read_missing_returns_default(self):
        self.assertIsNone(self.store.read("nope.json"))
        self.assertEqual(self.store.read("nope.json", {"d": 1}), {"d": 1})

    def test_read_invalid_json_returns_default(self):
        with open(self.store.path("bad.json"), "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(self.store.read("bad.json", []), [])

    def test_write_creates_nested_dirs_and_round_trips_unicode(self):
        data = {"outlet": "Télam", "n": 3, "list": ["Ś", "日本"]}
        self.store.write("a/b/c.json", data)
        self.assertEqual(self.store.read("a/b/c.json"), data)
        with open(self.store.path("a/b/c.json"), encoding="utf-8") as f:
            self.assertIn("Télam", f.read())  # ensure_ascii=False keeps files readable

    def test_write_overwrites(self):
        self.store.write("x.json", {"v": 1})
        self.store.write("x.json", {"v": 2})
        self.assertEqual(self.store.read("x.json"), {"v": 2})

    def test_write_text(self):
        self.store.write_text("r/report.md", "# Hi é")
        with open(self.store.path("r/report.md"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "# Hi é")

    def test_list_dir_sorted_and_missing_dir(self):
        self.store.write("d/b.json", {})
        self.store.write("d/a.json", {})
        self.assertEqual(self.store.list_dir("d"), ["a.json", "b.json"])
        self.assertEqual(self.store.list_dir("missing"), [])

    def test_path_is_under_root(self):
        self.assertTrue(self.store.path("x/y.json").startswith(self._tmp.name))


if __name__ == "__main__":
    unittest.main()
