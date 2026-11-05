"""Offline end-to-end tests: fake LLM that answers each TASK, fake data sources, no network.
Run everything with:  python -m unittest discover -s tests -v"""
import json
import re
import tempfile
import unittest

import helpers
from helpers import cfg
from trendwatch import sources
from trendwatch.llm.base import LLM
from trendwatch.models import Signal
from trendwatch.pipeline import run
from trendwatch.store import Store


class FakeLLM(LLM):
    """Deterministic answers for every task the pipeline asks for."""

    def __init__(self):
        super().__init__({"fast": "fake-fast", "smart": "fake-smart"})
        self.calls = []

    def complete(self, system, prompt, tier="fast", max_tokens=2000):
        task = re.match(r"TASK:(\w+)", prompt).group(1)
        self.calls.append(task)
        if task == "cluster_topics":
            return json.dumps([
                {"topic": "Album Launch", "keywords": ["album", "launch"], "signal_ids": [0, 1, 2],
                 "summary": "A big album was released."},
                {"topic": "Lonely Signal", "keywords": ["x"], "signal_ids": [3], "summary": "."}])
        if task == "propose_framings":
            return "```json\n" + json.dumps(helpers.FRAMINGS_REPLY) + "\n```"
        if task == "label_items":
            return json.dumps(helpers.keyword_labels(prompt))
        if task == "classify_outlets":
            names = re.findall(r"^- (.+)$", prompt, re.M)
            return json.dumps([{"outlet": n, "group": "Israeli media" if n == "Outlet0" else "Iranian media"}
                               for n in names])
        if task == "group_narratives":
            gs = re.findall(r'<group name="([^"]+)"', prompt)
            first = re.search(r'<item i="(\d+)"', prompt)
            return json.dumps({"groups": [{"group": g, "narrative": f"According to {g}, it was covered.",
                                           "item_ids": [int(first.group(1))]} for g in gs],
                               "differences": "They use different terms."})
        if task == "write_narrative":
            return "Neutral briefing text."
        raise AssertionError(f"unexpected task {task}")


def fake_signals(cfg_):
    return [Signal("Album drop", "google_trends", 10), Signal("New album", "wikipedia", 9),
            Signal("album launch", "mastodon", 5), Signal("Something else", "hackernews", 1)]


def fake_content(topic, cfg_):
    return helpers.mixed_items(24, 10)


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        saved = (dict(sources.SIGNAL_SOURCES), dict(sources.CONTENT_SOURCES))
        self.addCleanup(self._restore, saved)
        sources.SIGNAL_SOURCES.clear()
        sources.SIGNAL_SOURCES["fake"] = fake_signals
        sources.CONTENT_SOURCES.clear()
        sources.CONTENT_SOURCES["fake"] = fake_content
        self.cfg = cfg(discovery={"enabled_sources": ["fake"], "topics_per_day": 3},
                       collection={"sources": ["fake"]},
                       analysis={"min_items_outlet": 5, "min_items_account": 5})
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = Store(self._tmp.name)

    @staticmethod
    def _restore(saved):
        for registry, original in zip((sources.SIGNAL_SOURCES, sources.CONTENT_SOURCES), saved):
            registry.clear()
            registry.update(original)

    def test_auto_discovery_to_report_and_no_double_counting(self):
        llm = FakeLLM()
        name = run(llm, self.cfg, self.store)
        res = self.store.read(name.replace(".md", ".json"))
        # "Lonely Signal" trends on one platform only, so it is filtered out
        self.assertEqual([r["topic"] for r in res], ["Album Launch"])
        div = res[0]["divide"]
        self.assertEqual((div["verdict"], div["kappa"]), ("strong", 1.0))
        outlets = res[0]["rows"]["outlets"]
        self.assertEqual(len(outlets), 2)
        self.assertTrue(all(o["n"] == 12 for o in outlets), outlets)
        self.assertTrue(all(not o["label"].startswith("building") for o in outlets))

        run(llm, self.cfg, self.store)  # same items again must not inflate the counts
        prof = self.store.read("profiles/outlets.json")
        total = sum(sum(t["counts"].values()) for e in prof.values() for t in e["topics"].values())
        self.assertEqual(total, 24)
        self.assertEqual(llm.calls.count("propose_framings"), 1)  # framings are frozen

    def test_report_names_each_side_and_is_written_as_markdown_html_and_json(self):
        llm = FakeLLM()
        name = run(llm, self.cfg, self.store)
        res = self.store.read(name.replace(".md", ".json"))[0]
        names = {g["group"] for g in res["narratives"]["groups"]}
        self.assertTrue({"Israeli media", "Iranian media", "Bluesky posts"} <= names, names)
        self.assertEqual(res["rank"], 1)
        self.assertTrue(res["narratives"]["differences"])
        self.assertTrue(all(g["links"] for g in res["narratives"]["groups"]))
        # outlet classification is cached and editable; a second run must not ask again
        self.assertEqual(self.store.read("outlet_groups.json")["Outlet0"], "Israeli media")
        run(llm, self.cfg, self.store)
        self.assertEqual(llm.calls.count("classify_outlets"), 1)
        with open(self.store.path(name), encoding="utf-8") as f:
            md = f.read()
        self.assertIn("### What each side says", md)
        self.assertIn("**Israeli media**", md)
        with open(self.store.path(name.replace(".md", ".html")), encoding="utf-8") as f:
            html = f.read()
        self.assertIn("According to Israeli media", html)
        self.assertTrue(html.startswith("<!doctype html>"))


if __name__ == "__main__":
    unittest.main()
