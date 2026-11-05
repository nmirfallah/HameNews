import tempfile
import unittest

from helpers import FRAMINGS, cfg, item
from trendwatch import profiles
from trendwatch.store import Store

FR = FRAMINGS["framings"]


def lab(label, evidence=""):
    return {"label": label, "confidence": 1.0, "evidence": evidence}


class SummarizeTests(unittest.TestCase):
    def test_building_until_enough_items(self):
        s = profiles.summarize({"f1": 2, "none": 1}, FR, 10, 0.6)
        self.assertEqual(s["label"], "building (3/10 items needed)")
        self.assertEqual((s["n"], s["confidence"]), (3, "-"))

    def test_mostly_neutral_when_few_framed_items(self):
        s = profiles.summarize({"none": 10, "f1": 2}, FR, 10, 0.6)
        self.assertEqual(s["label"], "no clear framing (mostly neutral)")
        self.assertEqual(s["confidence"], "low")

    def test_leans_with_share(self):
        s = profiles.summarize({"f1": 9, "f2": 1, "none": 5}, FR, 10, 0.6)
        self.assertEqual(s["label"], "leans: Celebratory (90% of framed)")
        self.assertEqual(s["confidence"], "low")

    def test_confidence_grows_with_sample_size(self):
        self.assertEqual(profiles.summarize({"f1": 20, "none": 5}, FR, 10, 0.6)["confidence"], "medium")
        self.assertEqual(profiles.summarize({"f1": 45}, FR, 10, 0.6)["confidence"], "high")
        # big sample but split opinion is never "high"
        self.assertEqual(profiles.summarize({"f1": 30, "f2": 15}, FR, 10, 0.6)["confidence"], "medium")

    def test_mixed_when_no_framing_reaches_the_threshold(self):
        s = profiles.summarize({"f1": 5, "f2": 4}, FR, 5, 0.6)
        self.assertEqual(s["label"], "mixed: Celebratory / Dismissive")

    def test_unknown_framing_id_falls_back_to_the_id(self):
        s = profiles.summarize({"f9": 10}, FR, 5, 0.6)
        self.assertIn("f9", s["label"])


class ProfileStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = Store(self._tmp.name)

    def test_keys_for_articles_and_posts(self):
        self.assertEqual(profiles.key_for(item(1, "article", "BBC")), "BBC")
        self.assertEqual(profiles.key_for(item(1, "post", "alice", platform="bluesky")), "bluesky:alice")

    def test_update_counts_by_label_and_skips_unclear(self):
        items = [item("1", outlet="BBC"), item("2", outlet="BBC"), item("3", outlet="BBC"),
                 item("4", outlet="BBC")]
        labels = {"1": lab("f1"), "2": lab("f2"), "3": lab("none"), "4": lab("unclear")}
        profiles.update(self.store, "t", items, labels)
        counts = self.store.read("profiles/outlets.json")["BBC"]["topics"]["t"]["counts"]
        self.assertEqual(counts, {"f1": 1, "f2": 1, "none": 1})

    def test_articles_and_posts_go_to_separate_files(self):
        items = [item("1", "article", "BBC"), item("2", "post", "alice", platform="bluesky")]
        profiles.update(self.store, "t", items, {"1": lab("f1"), "2": lab("f2")})
        self.assertIn("BBC", self.store.read("profiles/outlets.json"))
        self.assertIn("bluesky:alice", self.store.read("profiles/accounts.json"))
        self.assertNotIn("alice", self.store.read("profiles/outlets.json"))

    def test_same_item_is_never_counted_twice_across_runs(self):
        items = [item("1", outlet="BBC")]
        for _ in range(3):
            profiles.update(self.store, "t", items, {"1": lab("f1")})
        self.assertEqual(self.store.read("profiles/outlets.json")["BBC"]["topics"]["t"]["counts"], {"f1": 1})

    def test_counts_accumulate_over_days_and_topics_are_separate(self):
        profiles.update(self.store, "t", [item("1", outlet="BBC")], {"1": lab("f1")})
        profiles.update(self.store, "t", [item("2", outlet="BBC")], {"2": lab("f1")})
        profiles.update(self.store, "other", [item("3", outlet="BBC")], {"3": lab("f2")})
        topics = self.store.read("profiles/outlets.json")["BBC"]["topics"]
        self.assertEqual(topics["t"]["counts"], {"f1": 2})
        self.assertEqual(topics["other"]["counts"], {"f2": 1})

    def test_evidence_only_for_framed_items_and_capped_at_five(self):
        items = [item(str(i), outlet="BBC", url=f"http://x/{i}") for i in range(8)]
        labels = {str(i): lab("f1", f"quote {i}") for i in range(7)}
        labels["7"] = lab("none", "ignored")
        profiles.update(self.store, "t", items, labels)
        ev = self.store.read("profiles/outlets.json")["BBC"]["topics"]["t"]["evidence"]
        self.assertEqual(len(ev), 5)
        self.assertEqual(ev[0], {"framing": "f1", "quote": "quote 0", "url": "http://x/0"})

    def test_items_without_a_label_entry_are_ignored(self):
        profiles.update(self.store, "t", [item("1", outlet="BBC")], {})
        self.assertEqual(self.store.read("profiles/outlets.json"), {})


class RowsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = Store(self._tmp.name)
        self.cfg = cfg(analysis={"min_items_outlet": 2, "min_items_account": 4})

    def seed(self):
        items = [item(f"a{i}", outlet="BBC") for i in range(3)] + \
                [item(f"b{i}", outlet="Fox") for i in range(2)] + \
                [item(f"p{i}", "post", "alice", platform="bluesky") for i in range(3)]
        labels = {i.id: lab("f1", "q") for i in items}
        profiles.update(self.store, "t", items, labels)

    def test_rows_split_outlets_and_accounts_and_sort_by_size(self):
        self.seed()
        rows = profiles.rows(self.store, "t", FRAMINGS, self.cfg)
        self.assertEqual([r["name"] for r in rows["outlets"]], ["BBC", "Fox"])
        self.assertEqual([r["name"] for r in rows["accounts"]], ["bluesky:alice"])

    def test_thresholds_differ_for_outlets_and_accounts(self):
        self.seed()
        rows = profiles.rows(self.store, "t", FRAMINGS, self.cfg)
        self.assertTrue(rows["outlets"][0]["label"].startswith("leans"))
        self.assertTrue(rows["accounts"][0]["label"].startswith("building"))  # 3 posts < 4 needed

    def test_reference_ratings_are_matched_case_insensitively(self):
        self.seed()
        self.store.write("known_ratings.json", {"bbc": "AllSides: Center"})
        rows = profiles.rows(self.store, "t", FRAMINGS, self.cfg)
        self.assertEqual(rows["outlets"][0]["reference"], "AllSides: Center")
        self.assertEqual(rows["outlets"][1]["reference"], "")

    def test_only_entries_for_the_requested_topic(self):
        self.seed()
        rows = profiles.rows(self.store, "other-topic", FRAMINGS, self.cfg)
        self.assertEqual(rows, {"outlets": [], "accounts": []})

    def test_limit(self):
        items = [item(f"{o}{i}", outlet=f"O{o}") for o in range(5) for i in range(2)]
        profiles.update(self.store, "t", items, {i.id: lab("f1") for i in items})
        rows = profiles.rows(self.store, "t", FRAMINGS, self.cfg, limit=3)
        self.assertEqual(len(rows["outlets"]), 3)

    def test_evidence_is_trimmed_to_two_per_row(self):
        self.seed()
        rows = profiles.rows(self.store, "t", FRAMINGS, self.cfg)
        self.assertLessEqual(len(rows["outlets"][0]["evidence"]), 2)


if __name__ == "__main__":
    unittest.main()
