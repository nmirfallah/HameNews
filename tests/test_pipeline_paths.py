import re
import tempfile
import unittest
from datetime import date
from unittest import mock

import helpers
from helpers import (FRAMINGS_REPLY, ScriptedLLM, cfg, keyword_labels, leaning_reply, mixed_items,
                     task_handler)
from trendwatch import pipeline
from trendwatch.models import Signal
from trendwatch.sources import CONTENT_SOURCES, SIGNAL_SOURCES
from trendwatch.store import Store


def classify(prompt):
    return [{"outlet": n, "group": "Group A"} for n in re.findall(r"^- (.+)$", prompt, re.M)]


def narratives(prompt):
    groups = re.findall(r'<group name="([^"]+)"', prompt)
    first = re.search(r'<item i="(\d+)"', prompt)
    return {"common": "Main story.", "common_item_ids": [int(first.group(1))],
            "groups": [{"group": g, "distinct": f"{g} adds x", "item_ids": [int(first.group(1))]} for g in groups],
            "conflicts": ["d"]}


def handler(**over):
    base = dict(expand_subject={"topic": "Album", "keywords": ["album"], "summary": "s"},
                propose_framings=FRAMINGS_REPLY, label_items=keyword_labels, classify_outlets=classify,
                classify_leanings=lambda p: leaning_reply(p, {"Outlet0": "right", "Outlet1": "left"}),
                group_narratives=narratives, write_narrative="Neutral text.",
                translate_keywords={}, translate_items=[])
    base.update(over)
    return task_handler(**base)


class PipelineTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = Store(self._tmp.name)
        self.cfg = cfg(collection={"sources": ["fake"]}, analysis={"batch_size": 100},
                       discovery={"enabled_sources": ["fake"], "min_platforms": 2})

    def content(self, items):
        p = mock.patch.dict(CONTENT_SOURCES, {"fake": lambda t, c: items}, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def signals(self, signals):
        p = mock.patch.dict(SIGNAL_SOURCES, {"fake": lambda c: signals}, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def analyze(self, llm):
        return pipeline.analyze_topic(llm, {"topic": "Album", "keywords": ["album"], "summary": "s",
                                            "platforms": ["a", "b"], "n_signals": 2, "signals": []},
                                      self.cfg, self.store)


class AnalyzeTopicTests(PipelineTestCase):
    def test_too_few_items_stops_before_any_framing_work(self):
        self.content(mixed_items(2, 0))
        llm = ScriptedLLM(handler=handler())
        res = self.analyze(llm)
        self.assertEqual(res["divide"]["verdict"], "insufficient data")
        self.assertEqual(res["n_items"], 2)
        self.assertIsNone(res["narratives"])
        self.assertNotIn("propose_framings", llm.tasks())
        self.assertNotIn("label_items", llm.tasks())

    def test_narratives_are_built_even_when_there_is_too_little_data_for_labels(self):
        self.content(mixed_items(4, 0))  # >= 3 items for narratives, < 8 for stance analysis
        res = self.analyze(ScriptedLLM(handler=handler()))
        self.assertEqual(res["divide"]["verdict"], "insufficient data")
        self.assertTrue(res["narratives"]["groups"])

    def test_no_distinct_framings_skips_labelling_and_profiles(self):
        self.content(mixed_items(10, 0))
        llm = ScriptedLLM(handler=handler(propose_framings={"has_distinct_framings": False, "framings": []}))
        res = self.analyze(llm)
        self.assertEqual(res["divide"]["verdict"], "no distinct framings")
        self.assertNotIn("label_items", llm.tasks())
        self.assertIsNone(self.store.read("profiles/outlets.json"))
        self.assertTrue(res["narratives"]["groups"])

    def test_a_crashing_narratives_step_does_not_stop_the_analysis(self):
        self.content(mixed_items(12, 6))
        with mock.patch.object(pipeline.narratives, "build", side_effect=RuntimeError("boom")):
            res = self.analyze(ScriptedLLM(handler=handler()))
        self.assertNotIn("narratives", res)
        self.assertEqual(res["divide"]["verdict"], "strong")

    def test_full_analysis_updates_profiles_and_history(self):
        self.content(mixed_items(12, 6))
        res = self.analyze(ScriptedLLM(handler=handler()))
        self.assertEqual(res["slug"], "album")
        self.assertIn("Outlet0", self.store.read("profiles/outlets.json"))
        self.assertIn("bluesky:user0", self.store.read("profiles/accounts.json"))
        history = self.store.read("topics/album.json")["history"]
        self.assertEqual([h["verdict"] for h in history], ["strong"])
        self.assertEqual(res["narrative"], "Neutral text.")

    def test_a_failing_final_summary_is_tolerated(self):
        self.content(mixed_items(12, 6))
        res = self.analyze(ScriptedLLM(handler=handler(write_narrative=RuntimeError("down"))))
        self.assertNotIn("narrative", res)
        self.assertEqual(res["divide"]["verdict"], "strong")


class LanguageIntegrationTests(PipelineTestCase):
    def persian_items(self):
        out = []
        for i in range(2):
            out.append(helpers.item(f"fa{i}", "article", "Tasnim News Agency", "گفتگوهای ایران آغاز شد",
                                    url=f"http://t/{i}", lang="fa"))
        return out

    def translations(self, prompt):
        return [{"i": int(m.group(1)), "lang": "fa", "english": f"Translated headline {m.group(1)}"}
                for m in re.finditer(r'<item i="(\d+)"', prompt)]

    def test_non_english_items_are_translated_grouped_and_reported(self):
        self.content(mixed_items(12, 6) + self.persian_items())
        keywords = lambda p: {"fa": ["ایران"], "ar": ["إيران"]}
        llm = ScriptedLLM(handler=handler(translate_items=self.translations, translate_keywords=keywords))
        res = self.analyze(llm)
        groups = {g["group"]: g for g in res["narratives"]["groups"]}
        self.assertEqual(groups["Iran state-linked media"]["languages"], ["Persian"])
        by_task = {}
        for c in llm.calls:
            by_task.setdefault(c["prompt"].split("\n")[0], []).append(c["prompt"])
        for prompt in by_task["TASK:group_narratives"] + by_task["TASK:label_items"]:
            self.assertNotIn("گفتگوهای", prompt)          # analysis sees English only
        self.assertTrue(any("Translated headline" in p for p in by_task["TASK:group_narratives"]))
        cached = self.store.read("translations.json")
        self.assertEqual({v["lang"] for v in cached.values()}, {"fa"})
        self.assertEqual({v["english"] for v in cached.values()}, {"Translated headline 0", "Translated headline 1"})
        self.assertEqual(self.store.read("keyword_translations.json")["album"]["fa"], ["ایران"])

    def test_translations_are_cached_across_runs(self):
        self.content(mixed_items(12, 6) + self.persian_items())
        llm = ScriptedLLM(handler=handler(translate_items=self.translations))
        self.analyze(llm)
        before = llm.tasks().count("translate_items")
        self.analyze(llm)
        self.assertEqual(llm.tasks().count("translate_items"), before)

    def test_a_failing_translation_step_does_not_stop_the_analysis(self):
        self.content(mixed_items(12, 6) + self.persian_items())
        llm = ScriptedLLM(handler=handler(translate_items=RuntimeError("down"), translate_keywords=RuntimeError("down")))
        res = self.analyze(llm)
        self.assertEqual(res["divide"]["verdict"], "strong")
        self.assertTrue(res["narratives"]["groups"])

    def test_translation_can_be_turned_off(self):
        self.cfg = cfg(collection={"sources": ["fake"]}, analysis={"batch_size": 100},
                       languages={"translate": False, "search_native": False}, news_sites=[])
        self.content(mixed_items(12, 6) + self.persian_items())
        llm = ScriptedLLM(handler=handler())
        self.analyze(llm)
        self.assertNotIn("translate_items", llm.tasks())
        self.assertNotIn("translate_keywords", llm.tasks())


class DiscoveryRunTests(PipelineTestCase):
    # Signals are numbered after being grouped by platform, so they are listed here in that order:
    # ids 0-2 google_trends, 3-5 wikipedia, 6 mastodon, 7 hackernews.
    SIGNALS = [Signal("a", "google_trends"), Signal("d", "google_trends"), Signal("f", "google_trends"),
               Signal("b", "wikipedia"), Signal("e", "wikipedia"), Signal("g", "wikipedia"),
               Signal("c", "mastodon"), Signal("lone", "hackernews")]
    CLUSTERS = [{"topic": "Big", "keywords": ["big"], "summary": "Big story", "signal_ids": [0, 3, 6]},
                {"topic": "Medium", "keywords": ["medium"], "summary": "Medium story", "signal_ids": [1, 4]},
                {"topic": "Small", "keywords": ["small"], "summary": "Small story", "signal_ids": [2, 5]},
                {"topic": "Lonely", "keywords": ["lonely"], "summary": "One platform only", "signal_ids": [7]}]

    def setUp(self):
        super().setUp()
        self.content(mixed_items(12, 6))
        self.signals(self.SIGNALS)

    def run_it(self, watch=(), **disc):
        self.cfg = cfg(collection={"sources": ["fake"]}, analysis={"batch_size": 100},
                       discovery=dict({"enabled_sources": ["fake"], "min_platforms": 2, "watchlist": list(watch)}, **disc))
        llm = ScriptedLLM(handler=handler(cluster_topics=self.CLUSTERS))
        name = pipeline.run(llm, self.cfg, self.store)
        return name, llm

    def test_only_the_top_n_are_analysed_and_the_rest_are_listed_with_their_ranks(self):
        name, llm = self.run_it(topics_per_day=2)
        res = self.store.read(name.replace(".md", ".json"))
        self.assertEqual([(r["topic"], r["rank"]) for r in res], [("Big", 1), ("Medium", 2)])
        with open(self.store.path(name), encoding="utf-8") as f:
            md = f.read()
        self.assertIn("## Also trending (headlines only)", md)
        self.assertIn("### #3 Small", md)
        self.assertIn("3. Small (headlines only)", md)
        self.assertNotIn("Lonely", md)       # one platform and no big outlet count: below the threshold
        self.assertEqual(llm.tasks().count("propose_framings"), 2)  # deep analysis only for the two

    def test_zero_analyses_every_qualifying_topic_and_has_no_extras_section(self):
        name, _ = self.run_it(topics_per_day=0)
        res = self.store.read(name.replace(".md", ".json"))
        self.assertEqual([r["topic"] for r in res], ["Big", "Medium", "Small"])
        with open(self.store.path(name), encoding="utf-8") as f:
            self.assertNotIn("Also trending", f.read())

    def test_the_extras_list_can_be_switched_off(self):
        name, _ = self.run_it(topics_per_day=1, list_all_topics=False)
        with open(self.store.path(name), encoding="utf-8") as f:
            self.assertNotIn("Also trending", f.read())

    def test_the_html_report_has_the_extras_too(self):
        name, _ = self.run_it(topics_per_day=1)
        with open(self.store.path(name.replace(".md", ".html")), encoding="utf-8") as f:
            html = f.read()
        self.assertIn("Also trending (headlines only)", html)
        self.assertIn("Medium", html)
        self.assertIn("Small", html)

    def test_a_discovery_log_records_every_signal_cluster_and_its_fate(self):
        name, _ = self.run_it(topics_per_day=2)
        log = self.store.read(f"discovery/{date.today().isoformat()}.json")
        self.assertEqual(len(log["signals"]), 8)
        fates = {c["topic"]: c["status"] for c in log["clusters"]}
        self.assertEqual(fates, {"Big": "analysed", "Medium": "analysed", "Small": "listed only",
                                 "Lonely": "below threshold"})
        self.assertEqual(log["settings"]["topics_per_day"], 2)
        self.assertEqual(log["settings"]["min_news_outlets"], 5)
        self.assertEqual(log["date"], date.today().isoformat())

    def test_a_watchlist_topic_no_signal_matched_is_still_analysed_and_flagged(self):
        llm_handler = handler(cluster_topics=self.CLUSTERS,
                              expand_subject={"topic": "Iran war", "keywords": ["Iran", "Tehran"], "summary": "s"})
        self.cfg = cfg(collection={"sources": ["fake"]}, analysis={"batch_size": 100},
                       discovery={"enabled_sources": ["fake"], "min_platforms": 2, "topics_per_day": 1,
                                  "watchlist": ["Iran war"]})
        llm = ScriptedLLM(handler=llm_handler)
        name = pipeline.run(llm, self.cfg, self.store)
        res = self.store.read(name.replace(".md", ".json"))
        self.assertEqual([r["topic"] for r in res], ["Big", "Iran war"])   # beyond the top-1 limit, but forced in
        self.assertTrue(res[1]["watchlist"])
        self.assertEqual(llm.tasks().count("expand_subject"), 1)
        with open(self.store.path(name), encoding="utf-8") as f:
            self.assertIn("Watchlist topic (no trend signals today)", f.read())
        log = self.store.read(f"discovery/{date.today().isoformat()}.json")
        self.assertEqual({c["topic"]: c["status"] for c in log["clusters"]}["Iran war"], "analysed")

    def test_subject_mode_writes_no_discovery_log_and_no_extras(self):
        self.content(mixed_items(12, 6))
        pipeline.run(ScriptedLLM(handler=handler()), self.cfg, self.store, subject="Album")
        self.assertEqual(self.store.list_dir("discovery"), [])


class RunTests(PipelineTestCase):
    def test_subject_mode_writes_three_report_files(self):
        self.content(mixed_items(12, 6))
        llm = ScriptedLLM(handler=handler())
        name = pipeline.run(llm, self.cfg, self.store, subject="Album")
        self.assertEqual(name, f"reports/{date.today().isoformat()}-album.md")
        for ext in (".md", ".html", ".json"):
            self.assertTrue(self.store.list_dir("reports"), ext)
        self.assertEqual(sorted(f.rsplit(".", 1)[1] for f in self.store.list_dir("reports")),
                         ["html", "json", "md"])
        self.assertEqual(llm.tasks()[0], "expand_subject")
        self.assertEqual(self.store.read(name.replace(".md", ".json"))[0]["rank"], 1)

    def test_each_run_appends_to_the_topic_history_without_reproposing_framings(self):
        self.content(mixed_items(12, 6))
        llm = ScriptedLLM(handler=handler())
        pipeline.run(llm, self.cfg, self.store, subject="Album")
        pipeline.run(llm, self.cfg, self.store, subject="Album")
        self.assertEqual(len(self.store.read("topics/album.json")["history"]), 2)
        self.assertEqual(llm.tasks().count("propose_framings"), 1)

    def test_discovery_mode_ranks_topics_and_passes_existing_topic_names(self):
        self.content(mixed_items(12, 6))
        self.signals([Signal("a", "google_trends"), Signal("b", "wikipedia"), Signal("c", "wikipedia")])
        self.store.write("topics/old-topic.json", {"framings": []})
        cluster = [{"topic": "Album", "keywords": ["album"], "signal_ids": [0, 1, 2], "summary": "s"}]
        llm = ScriptedLLM(handler=handler(cluster_topics=cluster))
        name = pipeline.run(llm, self.cfg, self.store)
        self.assertEqual(name, f"reports/{date.today().isoformat()}.md")
        cluster_prompt = next(c["prompt"] for c in llm.calls if c["prompt"].startswith("TASK:cluster_topics"))
        self.assertIn("old-topic", cluster_prompt)

    def test_the_model_is_shown_readable_topic_names_not_file_name_slugs(self):
        self.content(mixed_items(12, 6))
        self.signals([Signal("a", "google_trends"), Signal("b", "wikipedia")])
        self.store.write("topics/tesla-cybertruck-wind-down.json", {"topic": "Tesla Cybertruck wind-down"})
        self.store.write("topics/legacy.json", {"framings": []})  # no stored name: falls back to the file name
        llm = ScriptedLLM(handler=handler(cluster_topics=[{"topic": "X", "keywords": [], "signal_ids": [0, 1]}]))
        pipeline.run(llm, self.cfg, self.store)
        prompt = next(c["prompt"] for c in llm.calls if c["prompt"].startswith("TASK:cluster_topics"))
        self.assertIn("Tesla Cybertruck wind-down", prompt)
        self.assertNotIn("tesla-cybertruck-wind-down", prompt)
        self.assertIn("legacy", prompt)

    def test_nothing_trending_means_no_report(self):
        self.signals([])
        llm = ScriptedLLM(handler=handler())
        self.assertIsNone(pipeline.run(llm, self.cfg, self.store))
        self.assertEqual(llm.calls, [])
        self.assertEqual(self.store.list_dir("reports"), [])

    def test_several_topics_get_consecutive_ranks(self):
        self.content(mixed_items(12, 6))
        self.signals([Signal("a", "google_trends"), Signal("b", "wikipedia"), Signal("c", "mastodon"),
                      Signal("d", "google_trends"), Signal("e", "wikipedia")])
        cluster = [{"topic": "Big", "keywords": ["big"], "signal_ids": [0, 1, 2]},
                   {"topic": "Small", "keywords": ["small"], "signal_ids": [3, 4]}]
        llm = ScriptedLLM(handler=handler(cluster_topics=cluster))
        name = pipeline.run(llm, self.cfg, self.store)
        res = self.store.read(name.replace(".md", ".json"))
        self.assertEqual([(r["topic"], r["rank"]) for r in res], [("Big", 1), ("Small", 2)])


if __name__ == "__main__":
    unittest.main()
