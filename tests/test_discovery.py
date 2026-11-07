import unittest
from unittest import mock

from helpers import ScriptedLLM, cfg
from trendwatch import discovery
from trendwatch.models import Signal
from trendwatch.sources import SIGNAL_SOURCES


def sig(name, platform, score=1.0):
    return Signal(name, platform, score)


class CapSignalsTests(unittest.TestCase):
    def test_each_platform_keeps_its_top_scores(self):
        c = cfg(discovery={"signals_per_platform": 2, "news_signal_cap": 3})
        signals = [sig("a", "x", 1), sig("b", "x", 5), sig("c", "x", 3), sig("d", "x", 9)]
        out = discovery.cap_signals(signals, c)
        self.assertEqual([s.name for s in out], ["d", "b"])

    def test_news_has_its_own_cap_and_keeps_order_for_equal_scores(self):
        c = cfg(discovery={"signals_per_platform": 1, "news_signal_cap": 3})
        news = [sig(f"h{i}", "news", 1.0) for i in range(6)]
        out = discovery.cap_signals(news, c)
        self.assertEqual([s.name for s in out], ["h0", "h1", "h2"])


class GatherSignalsTests(unittest.TestCase):
    def test_failing_and_unknown_sources_are_skipped(self):
        def boom(c):
            raise RuntimeError("down")
        registry = {"good": lambda c: [sig("a", "good")], "bad": boom}
        conf = cfg(discovery={"enabled_sources": ["good", "bad", "missing"]})
        with mock.patch.dict(SIGNAL_SOURCES, registry, clear=True):
            out = discovery.gather_signals(conf)
        self.assertEqual([s.name for s in out], ["a"])


class DiscoverTopicsTests(unittest.TestCase):
    SIGNALS = {
        "google_trends": lambda c: [sig("Album drop", "google_trends")],
        "wikipedia": lambda c: [sig("New album", "wikipedia")],
        "mastodon": lambda c: [sig("#album", "mastodon")],
        "hackernews": lambda c: [sig("Random thing", "hackernews")],
    }

    def conf(self, **discovery_over):
        base = {"enabled_sources": list(self.SIGNALS), "topics_per_day": 3, "min_platforms": 2}
        base.update(discovery_over)
        return cfg(discovery=base)

    def run_discover(self, reply, conf=None, existing=()):
        llm = ScriptedLLM([reply])
        with mock.patch.dict(SIGNAL_SOURCES, self.SIGNALS, clear=True):
            topics = discovery.discover_topics(llm, conf or self.conf(), existing)
        return topics, llm

    REPLY = [
        {"topic": "Album", "keywords": ["album"], "signal_ids": [0, 1, 2, 99, "x"], "summary": "s"},
        {"topic": "Solo", "keywords": ["x"], "signal_ids": [3], "summary": ""},
        {"topic": "", "signal_ids": [0]},
        {"topic": "NoIds", "signal_ids": []},
    ]

    def test_only_multi_platform_topics_qualify_and_bad_ids_are_dropped(self):
        topics, _ = self.run_discover(self.REPLY)
        self.assertEqual([t["topic"] for t in topics], ["Album"])
        t = topics[0]
        self.assertEqual(t["platforms"], ["google_trends", "mastodon", "wikipedia"])
        self.assertEqual(t["n_signals"], 3)
        self.assertEqual(t["keywords"], ["album"])
        self.assertEqual(len(t["signals"]), 3)

    def test_falls_back_to_all_topics_when_none_qualify(self):
        topics, _ = self.run_discover(self.REPLY, self.conf(min_platforms=4))
        self.assertEqual([t["topic"] for t in topics], ["Album", "Solo"])

    def test_topics_per_day_caps_the_result(self):
        topics, _ = self.run_discover(self.REPLY, self.conf(min_platforms=1, topics_per_day=1))
        self.assertEqual([t["topic"] for t in topics], ["Album"])

    def test_ranking_prefers_more_platforms(self):
        reply = [{"topic": "Two", "signal_ids": [0, 1]},
                 {"topic": "Three", "signal_ids": [0, 1, 2]},
                 {"topic": "Four", "signal_ids": [0, 1, 2, 3]}]
        topics, _ = self.run_discover(reply)
        self.assertEqual([t["topic"] for t in topics], ["Four", "Three", "Two"])

    def test_equal_platform_counts_are_ranked_by_signal_count(self):
        signals = {"google_trends": lambda c: [sig("g1", "google_trends"), sig("g2", "google_trends")],
                   "wikipedia": lambda c: [sig("w1", "wikipedia")],
                   "mastodon": lambda c: [sig("m1", "mastodon")]}
        reply = [{"topic": "A", "signal_ids": [0, 2]}, {"topic": "B", "signal_ids": [0, 1, 3]}]
        llm = ScriptedLLM([reply])
        conf = cfg(discovery={"enabled_sources": list(signals), "min_platforms": 2})
        with mock.patch.dict(SIGNAL_SOURCES, signals, clear=True):
            topics = discovery.discover_topics(llm, conf)
        self.assertEqual([t["topic"] for t in topics], ["B", "A"])

    def test_repeated_signal_ids_do_not_inflate_the_count(self):
        topics, _ = self.run_discover([{"topic": "A", "signal_ids": [0, 0, 0, 1]}])
        self.assertEqual(topics[0]["n_signals"], 2)

    def test_accepts_an_object_with_a_topics_key(self):
        topics, _ = self.run_discover({"topics": self.REPLY})
        self.assertEqual([t["topic"] for t in topics], ["Album"])

    def test_prompt_lists_signals_and_existing_topics_and_uses_smart_tier(self):
        _, llm = self.run_discover(self.REPLY, existing=["existing-topic"])
        prompt = llm.calls[0]["prompt"]
        self.assertIn("[0] (google_trends) Album drop", prompt)
        self.assertIn("existing-topic", prompt)
        self.assertEqual(llm.calls[0]["tier"], "smart")

    def test_no_signals_means_no_llm_call(self):
        llm = ScriptedLLM([])
        conf = cfg(discovery={"enabled_sources": ["none"]})
        with mock.patch.dict(SIGNAL_SOURCES, {"none": lambda c: []}, clear=True):
            self.assertEqual(discovery.discover_topics(llm, conf), [])
        self.assertEqual(llm.calls, [])

    def test_keywords_are_capped_at_five_and_stringified(self):
        reply = [{"topic": "A", "keywords": list(range(9)), "signal_ids": [0, 1]}]
        topics, _ = self.run_discover(reply)
        self.assertEqual(topics[0]["keywords"], ["0", "1", "2", "3", "4"])


class TidyTopicNameTests(unittest.TestCase):
    def test_slugs_become_readable_text(self):
        self.assertEqual(discovery.tidy_topic_name("tesla-cybertruck-wind-down"), "Tesla cybertruck wind down")
        self.assertEqual(discovery.tidy_topic_name("2026-us-midterm-elections"), "2026 us midterm elections")

    def test_real_titles_are_left_alone(self):
        for name in ("Tesla Cybertruck production ends", "COVID-19", "covid-19", "Iran-Israel war",
                     "Stephen Miller named chief of staff", "AI regulation"):
            self.assertEqual(discovery.tidy_topic_name(name), name)

    def test_blank_and_none(self):
        self.assertEqual(discovery.tidy_topic_name(None), "")
        self.assertEqual(discovery.tidy_topic_name("  "), "")

    def test_discovered_slug_names_are_tidied(self):
        reply = [{"topic": "tesla-cybertruck-wind-down", "keywords": ["tesla"], "signal_ids": [0, 1]}]
        llm = ScriptedLLM([reply])
        signals = {"a": lambda c: [sig("x", "a")], "b": lambda c: [sig("y", "b")]}
        conf = cfg(discovery={"enabled_sources": ["a", "b"], "min_platforms": 2})
        with mock.patch.dict(SIGNAL_SOURCES, signals, clear=True):
            topics = discovery.discover_topics(llm, conf)
        self.assertEqual(topics[0]["topic"], "Tesla cybertruck wind down")


class ExpandSubjectTests(unittest.TestCase):
    def test_uses_fields_from_the_reply(self):
        llm = ScriptedLLM([{"topic": "Climate change", "keywords": ["a", "b"], "summary": "s"}])
        out = discovery.expand_subject(llm, "climate")
        self.assertEqual((out["topic"], out["keywords"], out["summary"]), ("Climate change", ["a", "b"], "s"))
        self.assertEqual(out["signals"], [])
        self.assertEqual(llm.calls[0]["tier"], "fast")

    def test_missing_fields_fall_back_to_the_subject(self):
        out = discovery.expand_subject(ScriptedLLM([{}]), "climate")
        self.assertEqual((out["topic"], out["keywords"]), ("climate", ["climate"]))

    def test_keywords_capped_at_five(self):
        out = discovery.expand_subject(ScriptedLLM([{"keywords": list("abcdefg")}]), "x")
        self.assertEqual(len(out["keywords"]), 5)


if __name__ == "__main__":
    unittest.main()
