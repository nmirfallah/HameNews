import tempfile
import unittest

import helpers  # noqa: F401
from trendwatch.explain import explain
from trendwatch.store import Store

LOG = {
    "date": "2026-11-07",
    "settings": {"topics_per_day": 3, "min_platforms": 2, "min_news_outlets": 5},
    "signals": [
        {"id": 0, "platform": "news", "name": "Iran war escalates [BBC]", "source": "BBC", "url": ""},
        {"id": 1, "platform": "news", "name": "Iranian missiles hit base [CNN]", "source": "CNN", "url": ""},
        {"id": 2, "platform": "wikipedia", "name": "Iran war", "source": "", "url": ""},
        {"id": 3, "platform": "news", "name": "Midterms results [NPR]", "source": "NPR", "url": ""},
        {"id": 4, "platform": "news", "name": "Tehran protests [AP]", "source": "AP", "url": ""},
        {"id": 5, "platform": "news", "name": "Unrelated sports story [ESPN]", "source": "ESPN", "url": ""},
    ],
    "clusters": [
        {"topic": "Midterms", "rank": 1, "trend_score": 4.2, "platforms": ["news", "wikipedia"], "n_outlets": 9,
         "signal_ids": [3], "status": "analysed"},
        {"topic": "Iran conflict", "rank": 5, "trend_score": 2.1, "platforms": ["news"], "n_outlets": 2,
         "signal_ids": [0, 1], "status": "below threshold"},
        {"topic": "Middle East", "rank": 4, "trend_score": 3.3, "platforms": ["news", "wikipedia"], "n_outlets": 6,
         "signal_ids": [2], "status": "listed only"},
    ],
}


class ExplainTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = Store(self._tmp.name)

    def test_without_a_log_it_says_how_to_make_one(self):
        out = explain(self.store, "Iran")
        self.assertIn("no discovery log yet", out)
        self.assertIn("python run.py", out)

    def test_a_term_no_source_returned_is_reported_as_never_seen_with_remedies(self):
        self.store.write("discovery/2026-11-07.json", LOG)
        out = explain(self.store, "Ukraine")
        self.assertIn("No signal in that run mentions 'Ukraine'", out)
        self.assertIn("watchlist", out)
        self.assertIn("headlines_per_feed", out)

    def test_hits_are_counted_by_platform_with_examples_and_outlets(self):
        self.store.write("discovery/2026-11-07.json", LOG)
        out = explain(self.store, "iran")                 # case-insensitive, matches 'Iranian' too
        self.assertIn("3 signals mention 'iran'", out)
        self.assertIn("news: 2", out)
        self.assertIn("wikipedia: 1", out)
        self.assertIn("2 different outlets", out)
        self.assertIn("(news) Iran war escalates [BBC]", out)

    def test_it_names_the_topic_and_fate_of_each_cluster_holding_the_signals(self):
        self.store.write("discovery/2026-11-07.json", LOG)
        out = explain(self.store, "Iran")
        self.assertIn("2 of them are in topic #5 'Iran conflict': below threshold", out)
        self.assertIn("1 of them are in topic #4 'Middle East': listed only", out)

    def test_below_threshold_says_what_it_needed(self):
        self.store.write("discovery/2026-11-07.json", LOG)
        out = explain(self.store, "Iran")
        self.assertIn("needs 2 platforms or 5 different news outlets", out)

    def test_listed_only_says_why(self):
        self.store.write("discovery/2026-11-07.json", LOG)
        out = explain(self.store, "Iran")
        self.assertIn("Only the top 3 topics get the full analysis", out)

    def test_signals_the_ai_put_in_no_topic_are_called_out(self):
        self.store.write("discovery/2026-11-07.json", LOG)
        out = explain(self.store, "Tehran")
        self.assertIn("1 signals mention 'Tehran'", out)
        self.assertIn("did not put any of these signals into a topic", out)

    def test_an_analysed_topic_has_no_hint_about_thresholds(self):
        self.store.write("discovery/2026-11-07.json", LOG)
        out = explain(self.store, "Midterms")
        self.assertIn("topic #1 'Midterms': analysed", out)
        self.assertNotIn("needs", out)

    def test_the_latest_log_is_used(self):
        old = dict(LOG, date="2026-11-01", signals=[{"id": 0, "platform": "news", "name": "Old story", "source": "X", "url": ""}],
                   clusters=[])
        self.store.write("discovery/2026-11-01.json", old)
        self.store.write("discovery/2026-11-07.json", LOG)
        out = explain(self.store, "Old story")
        self.assertIn("2026-11-07.json", out)
        self.assertIn("No signal", out)


if __name__ == "__main__":
    unittest.main()
