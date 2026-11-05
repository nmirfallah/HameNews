import tempfile
import unittest

from helpers import ScriptedLLM, cfg, item
from trendwatch.groups import FILE, assign_groups
from trendwatch.store import Store


class GroupsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = Store(self._tmp.name)

    def test_posts_are_grouped_by_platform(self):
        items = [item(1, "post", "a", platform="bluesky"), item(2, "post", "b", platform="mastodon"),
                 item(3, "post", "c", platform="hackernews"), item(4, "post", "d", platform="other")]
        assign_groups(ScriptedLLM([]), items, self.store)
        self.assertEqual([i.group for i in items],
                         ["Bluesky posts", "Mastodon posts", "Hacker News comments", "other"])

    def test_unknown_outlets_are_classified_once_and_cached(self):
        llm = ScriptedLLM([[{"outlet": "Foo", "group": "Israeli media"}]])
        items = [item(1, outlet="Foo"), item(2, outlet="Bar")]
        assign_groups(llm, items, self.store)
        self.assertEqual([i.group for i in items], ["Israeli media", "Unknown"])
        self.assertEqual(self.store.read(FILE), {"Bar": "Unknown", "Foo": "Israeli media"})
        again = [item(3, outlet="foo")]  # lookup is case-insensitive
        assign_groups(llm, again, self.store)
        self.assertEqual(again[0].group, "Israeli media")
        self.assertEqual(len(llm.calls), 1)

    def test_hand_edited_cache_wins_and_is_not_overwritten(self):
        self.store.write(FILE, {"Foo": "My Group"})
        llm = ScriptedLLM([])
        items = [item(1, outlet="Foo")]
        assign_groups(llm, items, self.store)
        self.assertEqual(items[0].group, "My Group")
        self.assertEqual(llm.calls, [])

    def test_failed_classification_is_not_cached_so_it_is_retried(self):
        llm = ScriptedLLM([RuntimeError("down"), [{"outlet": "Foo", "group": "UK media"}]])
        first = [item(1, outlet="Foo")]
        assign_groups(llm, first, self.store)
        self.assertEqual(first[0].group, "Unknown")
        self.assertIsNone(self.store.read(FILE))
        second = [item(2, outlet="Foo")]
        assign_groups(llm, second, self.store)
        self.assertEqual(second[0].group, "UK media")

    def test_rows_for_outlets_that_were_not_asked_about_are_ignored(self):
        llm = ScriptedLLM([[{"outlet": "Evil", "group": "X"}, {"outlet": "Foo", "group": "Y"}]])
        assign_groups(llm, [item(1, outlet="Foo")], self.store)
        self.assertNotIn("Evil", self.store.read(FILE))

    def test_outlets_are_classified_in_batches_of_forty(self):
        llm = ScriptedLLM([[], []])
        assign_groups(llm, [item(i, outlet=f"O{i}") for i in range(45)], self.store)
        self.assertEqual(len(llm.calls), 2)

    def test_classification_uses_the_fast_tier(self):
        llm = ScriptedLLM([[]])
        assign_groups(llm, [item(1, outlet="Foo")], self.store)
        self.assertEqual(llm.calls[0]["tier"], "fast")

    def test_preassigned_groups_are_kept_and_not_sent_to_the_llm(self):
        llm = ScriptedLLM([])
        items = [item(1, outlet="Zed", group="Iranian media")]
        assign_groups(llm, items, self.store)
        self.assertEqual(items[0].group, "Iranian media")
        self.assertEqual(llm.calls, [])

    def test_outlet_overrides_are_case_insensitive_and_beat_existing_groups(self):
        c = cfg(outlet_groups={"Mine": ["Some Outlet"]})
        items = [item(1, outlet="some outlet", group="Old"), item(2, outlet="Al Jazeera English")]
        assign_groups(ScriptedLLM([]), items, self.store, c)
        self.assertEqual([i.group for i in items], ["Mine", "Qatar state-linked media"])

    def test_domain_match_includes_subdomains_but_not_lookalikes(self):
        c = cfg()
        items = [item(1, outlet="X", domain="english.news.cn"), item(2, outlet="X", domain="news.cn"),
                 item(3, outlet="X", domain="notnews.cn")]
        llm = ScriptedLLM([[]])
        assign_groups(llm, items, self.store, c)
        self.assertEqual(items[0].group, "China state-linked media")
        self.assertEqual(items[1].group, "China state-linked media")
        self.assertNotEqual(items[2].group, "China state-linked media")

    def test_domain_beats_outlet_name(self):
        c = cfg(outlet_groups={"Wrong": ["Odd Name"]})
        items = [item(1, outlet="Odd Name", domain="tass.com")]
        assign_groups(ScriptedLLM([]), items, self.store, c)
        self.assertEqual(items[0].group, "Russia state-linked media")

    def test_agency_names_need_no_llm_call(self):
        llm = ScriptedLLM([])
        items = [item(1, outlet="AFP"), item(2, outlet="AP News"), item(3, outlet="Xinhua")]
        assign_groups(llm, items, self.store, cfg())
        self.assertEqual([i.group for i in items], ["France public media", "United States independent media",
                                                    "China state-linked media"])
        self.assertEqual(llm.calls, [])

    def test_works_without_a_config(self):
        items = [item(1, "post", "a", platform="bluesky")]
        assign_groups(ScriptedLLM([]), items, self.store, None)
        self.assertEqual(items[0].group, "Bluesky posts")


if __name__ == "__main__":
    unittest.main()
