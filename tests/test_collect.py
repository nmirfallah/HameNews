import unittest
from unittest import mock

from helpers import cfg, item
from trendwatch.collect import _round_robin, collect
from trendwatch.sources import CONTENT_SOURCES

TOPIC = {"topic": "T", "keywords": ["k"]}


class RoundRobinTests(unittest.TestCase):
    def test_alternates_between_buckets(self):
        items = [item("a1", outlet="A"), item("a2", outlet="A"), item("a3", outlet="A"), item("b1", outlet="B")]
        out = _round_robin(items, lambda i: i.outlet, 3)
        self.assertEqual([i.id for i in out], ["a1", "b1", "a2"])

    def test_limit_larger_than_available(self):
        items = [item("a1", outlet="A"), item("b1", outlet="B")]
        self.assertEqual(len(_round_robin(items, lambda i: i.outlet, 10)), 2)

    def test_empty(self):
        self.assertEqual(_round_robin([], lambda i: i.outlet, 5), [])


class CollectTests(unittest.TestCase):
    def run_collect(self, sources, **collection):
        conf = cfg(collection=dict(collection, sources=list(sources)))
        with mock.patch.dict(CONTENT_SOURCES, sources, clear=True):
            return collect(TOPIC, conf)

    def test_duplicates_across_sources_are_dropped(self):
        a = lambda t, c: [item("1", outlet="A"), item("2", outlet="A")]
        b = lambda t, c: [item("2", outlet="B"), item("3", outlet="B")]
        out = self.run_collect({"a": a, "b": b})
        self.assertEqual(sorted(i.id for i in out), ["1", "2", "3"])

    def test_blank_text_and_blank_ids_are_skipped(self):
        src = lambda t, c: [item("1", text="  "), item("", text="x"), item("3", text="ok")]
        self.assertEqual([i.id for i in self.run_collect({"s": src})], ["3"])

    def test_unknown_source_names_are_ignored(self):
        conf = cfg(collection={"sources": ["nope", "s"]})
        with mock.patch.dict(CONTENT_SOURCES, {"s": lambda t, c: [item("1")]}, clear=True):
            self.assertEqual(len(collect(TOPIC, conf)), 1)

    def test_a_failing_source_does_not_stop_the_others(self):
        def boom(t, c):
            raise RuntimeError("down")
        out = self.run_collect({"bad": boom, "good": lambda t, c: [item("1")]})
        self.assertEqual([i.id for i in out], ["1"])

    def test_articles_are_capped_round_robin_across_outlets(self):
        arts = [item(f"a{i}", outlet="A") for i in range(5)] + [item(f"b{i}", outlet="B") for i in range(5)]
        out = self.run_collect({"s": lambda t, c: arts}, max_articles=4)
        self.assertEqual([i.id for i in out], ["a0", "b0", "a1", "b1"])

    def test_posts_keep_the_most_engaging_and_follow_articles(self):
        posts = [item(f"p{i}", "post", f"u{i}", engagement=i) for i in range(6)]
        src = lambda t, c: posts + [item("art", "article", "A")]
        out = self.run_collect({"s": src}, max_posts=3)
        self.assertEqual([i.id for i in out], ["art", "p5", "p4", "p3"])

    def test_nothing_found_returns_empty_list(self):
        self.assertEqual(self.run_collect({"s": lambda t, c: []}), [])


if __name__ == "__main__":
    unittest.main()
