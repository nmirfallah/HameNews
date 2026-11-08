import math
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

    def test_discovery_itself_never_caps_the_list(self):
        topics, _ = self.run_discover(self.REPLY, self.conf(min_platforms=1, topics_per_day=1))
        self.assertEqual([t["topic"] for t in topics], ["Album", "Solo"])

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


class TrendScoreTests(unittest.TestCase):
    def test_non_news_platforms_count_signals_and_news_counts_distinct_outlets(self):
        sigs = [Signal("a", "wikipedia"), Signal("b", "wikipedia"),
                Signal("h1", "news", source="BBC"), Signal("h2", "news", source="BBC"),
                Signal("h3", "news", source="CNN"), Signal("h4", "news", source="Fox")]
        score, outlets = discovery.trend_score(sigs)
        self.assertEqual(outlets, 3)
        self.assertEqual(score, round(math.log2(3) + math.log2(4), 2))

    def test_news_signals_without_an_outlet_count_individually(self):
        score, outlets = discovery.trend_score([Signal("x", "news"), Signal("y", "news")])
        self.assertEqual(outlets, 2)

    def test_breadth_and_volume_both_raise_the_score(self):
        one = discovery.trend_score([Signal("a", "wikipedia")])[0]
        two_platforms = discovery.trend_score([Signal("a", "wikipedia"), Signal("b", "google_trends")])[0]
        many_outlets = discovery.trend_score([Signal(f"h{i}", "news", source=f"O{i}") for i in range(20)])[0]
        self.assertGreater(two_platforms, one)
        self.assertGreater(many_outlets, two_platforms)  # 20 outlets on one story beat two stray mentions

    def test_empty(self):
        self.assertEqual(discovery.trend_score([]), (0.0, 0))


class QualificationAndRankingTests(unittest.TestCase):
    def setUp(self):
        self.news = [Signal(f"Iran war headline {i}", "news", source=f"Outlet{i}") for i in range(8)]
        self.other = [Signal("Album", "google_trends"), Signal("Album page", "wikipedia")]
        self.signals = {"all": lambda c: self.news + self.other}

    def discover(self, reply, **disc):
        conf = cfg(discovery=dict({"enabled_sources": ["all"], "topics_per_day": 3}, **disc))
        record = {}
        with mock.patch.dict(SIGNAL_SOURCES, self.signals, clear=True):
            topics = discovery.discover_topics(ScriptedLLM([reply]), conf, record=record)
        return topics, record

    REPLY = [{"topic": "Iran war", "keywords": ["Iran"], "signal_ids": list(range(8))},
             {"topic": "Album", "keywords": ["album"], "signal_ids": [8, 9]}]

    def test_a_big_news_only_story_qualifies_and_outranks_a_minor_two_platform_one(self):
        topics, _ = self.discover(self.REPLY)
        self.assertEqual([t["topic"] for t in topics], ["Iran war", "Album"])
        self.assertEqual((topics[0]["platforms"], topics[0]["n_outlets"]), (["news"], 8))
        self.assertEqual([t["rank"] for t in topics], [1, 2])

    def test_a_news_only_story_below_the_outlet_threshold_does_not_qualify(self):
        reply = [{"topic": "Small story", "signal_ids": [0, 1, 2]}, self.REPLY[1]]
        topics, record = self.discover(reply)
        self.assertEqual([t["topic"] for t in topics], ["Album"])
        small = next(c for c in record["clusters"] if c["topic"] == "Small story")
        self.assertFalse(small["qualified"])

    def test_the_outlet_threshold_is_configurable_and_can_be_switched_off(self):
        reply = [{"topic": "Small story", "signal_ids": [0, 1, 2]}, self.REPLY[1]]
        topics, _ = self.discover(reply, min_news_outlets=3)
        self.assertEqual({t["topic"] for t in topics}, {"Small story", "Album"})
        topics, _ = self.discover(reply, min_news_outlets=0)
        self.assertEqual([t["topic"] for t in topics], ["Album"])

    def test_each_topic_reports_its_trend_score_signals_and_a_sample_of_headlines(self):
        topics, _ = self.discover(self.REPLY)
        iran = topics[0]
        self.assertEqual(iran["n_signals"], 8)
        self.assertGreater(iran["trend_score"], topics[1]["trend_score"])
        self.assertEqual(len(iran["signals"]), 6)
        self.assertEqual(iran["signal_ids"], list(range(8)))

    def test_the_record_holds_every_signal_and_every_cluster(self):
        _, record = self.discover(self.REPLY + [{"topic": "Tiny", "signal_ids": [8]}])
        self.assertEqual(len(record["signals"]), 10)
        self.assertEqual(record["signals"][0], {"id": 0, "platform": "news", "name": "Iran war headline 0",
                                                "source": "Outlet0", "url": ""})
        self.assertEqual([c["topic"] for c in record["clusters"]], ["Iran war", "Album", "Tiny"])
        self.assertEqual(record["clusters"][0]["signal_ids"], list(range(8)))

    def test_every_qualifying_topic_is_returned_however_many(self):
        many = [{"topic": f"Topic {i}", "signal_ids": [8, 9]} for i in range(12)]
        topics, _ = self.discover(many, topics_per_day=3)
        self.assertEqual(len(topics), 12)


class SplitTopicsTests(unittest.TestCase):
    def topics(self, n, watch=()):
        return [{"topic": f"T{i}", "watchlist": i in watch} for i in range(n)]

    def test_top_n_are_analysed_and_the_rest_are_listed(self):
        deep, rest = discovery.split_topics(self.topics(6), cfg(discovery={"topics_per_day": 2}))
        self.assertEqual(([t["topic"] for t in deep], [t["topic"] for t in rest]),
                         (["T0", "T1"], ["T2", "T3", "T4", "T5"]))

    def test_zero_means_analyse_everything(self):
        deep, rest = discovery.split_topics(self.topics(6), cfg(discovery={"topics_per_day": 0}))
        self.assertEqual((len(deep), rest), (6, []))

    def test_watchlist_topics_are_always_analysed(self):
        deep, rest = discovery.split_topics(self.topics(6, watch={5}), cfg(discovery={"topics_per_day": 2}))
        self.assertEqual([t["topic"] for t in deep], ["T0", "T1", "T5"])
        self.assertEqual(len(rest), 3)

    def test_fewer_topics_than_the_limit(self):
        deep, rest = discovery.split_topics(self.topics(2), cfg(discovery={"topics_per_day": 8}))
        self.assertEqual((len(deep), rest), (2, []))


class WatchlistTests(unittest.TestCase):
    SIGNALS = {"all": lambda c: [Signal("Hormuz talks", "news", source="BBC"), Signal("Album", "wikipedia"),
                                 Signal("Album drop", "google_trends")]}

    def discover(self, reply, watchlist):
        conf = cfg(discovery={"enabled_sources": ["all"], "watchlist": watchlist, "min_platforms": 2})
        llm = ScriptedLLM([reply])
        with mock.patch.dict(SIGNAL_SOURCES, self.SIGNALS, clear=True):
            return discovery.discover_topics(llm, conf), llm

    def test_the_prompt_lists_the_standing_topics(self):
        _, llm = self.discover([], ["Iran war", "Gaza"])
        self.assertIn("Standing topics the user always wants tracked: Iran war; Gaza", llm.calls[0]["prompt"])
        self.assertIn("exactly that name", llm.calls[0]["prompt"])

    def test_no_watchlist_means_no_such_line(self):
        _, llm = self.discover([], [])
        self.assertNotIn("Standing topics", llm.calls[0]["prompt"])

    def test_a_weak_matching_topic_is_flagged_and_kept_even_below_the_thresholds(self):
        reply = [{"topic": "iran WAR", "keywords": ["Iran"], "signal_ids": [0]},
                 {"topic": "Album", "signal_ids": [1, 2]}]
        topics, _ = self.discover(reply, ["Iran war"])
        iran = next(t for t in topics if t["topic"] == "iran WAR")
        self.assertTrue(iran["watchlist"])
        self.assertNotIn("needs_expand", iran)
        self.assertEqual(len(topics), 2)

    def test_a_standing_topic_nothing_matched_becomes_a_stub_ranked_last(self):
        topics, _ = self.discover([{"topic": "Album", "signal_ids": [1, 2]}], ["Iran war"])
        stub = topics[-1]
        self.assertEqual((stub["topic"], stub["watchlist"], stub["needs_expand"], stub["trend_score"]),
                         ("Iran war", True, True, 0.0))
        self.assertEqual((stub["rank"], stub["platforms"], stub["signals"]), (2, [], []))

    def test_blank_watchlist_entries_are_ignored(self):
        topics, _ = self.discover([{"topic": "Album", "signal_ids": [1, 2]}], ["", "  "])
        self.assertEqual([t["topic"] for t in topics], ["Album"])


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
