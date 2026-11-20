import tempfile
import unittest

import helpers
from helpers import FRAMINGS, item
from trendwatch.kb import KBStore
from trendwatch.kb.record import record_observations


def lab(label, evidence=""):
    return {"label": label, "confidence": 1.0, "evidence": evidence}


class RecordTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.kb = KBStore(self._tmp.name)

    def record(self, items, labels, day="2026-11-10", kb=None):
        return record_observations(kb or self.kb, day, "album", "Album Launch", items, labels, FRAMINGS)

    def obs(self, entity, day="2026-11-10"):
        return self.kb.observations[(entity, "album", day)]

    def test_counts_are_aggregated_per_outlet_with_readable_framing_names(self):
        items = [item(i, outlet="BBC") for i in range(4)]
        labels = {"0": lab("f1", "a triumph"), "1": lab("f1"), "2": lab("f2", "mock it"), "3": lab("none")}
        self.assertEqual(self.record(items, labels), 1)
        row = self.obs("outlet:bbc")
        self.assertEqual(row["counts"], {"Celebratory": 2, "Dismissive": 1, "none": 1})
        self.assertEqual((row["n_items"], row["topic_name"]), (4, "Album Launch"))

    def test_unclear_and_unlabelled_items_are_left_out(self):
        items = [item(0, outlet="BBC"), item(1, outlet="BBC"), item(2, outlet="Fox")]
        self.record(items, {"0": lab("unclear"), "1": lab("f1")})
        self.assertEqual(self.obs("outlet:bbc")["counts"], {"Celebratory": 1})
        self.assertNotIn(("outlet:fox", "album", "2026-11-10"), self.kb.observations)

    def test_accounts_are_recorded_with_their_platform(self):
        post = item(0, "post", "alice.bsky.social", platform="bluesky")
        self.record([post], {"0": lab("f2")})
        self.assertEqual(self.obs("account:bluesky-alice-bsky-social")["counts"], {"Dismissive": 1})
        self.assertEqual(self.kb.entities["account:bluesky-alice-bsky-social"]["name"], "bluesky:alice.bsky.social")

    def test_a_known_alias_or_domain_lands_on_the_existing_outlet(self):
        outlet = self.kb.upsert_entity("outlet", "Associated Press", ["AP News", "apnews.com"])[0]
        self.record([item(0, outlet="AP News")], {"0": lab("f1")})
        self.assertIn((outlet["id"], "album", "2026-11-10"), self.kb.observations)
        self.assertEqual(len([e for e in self.kb.entities.values() if e["type"] == "outlet"]), 1)

    def test_new_outlets_are_created_with_their_domain_as_an_alias(self):
        self.record([item(0, outlet="New Daily", domain="newdaily.example")], {"0": lab("f1")})
        self.assertEqual(self.kb.entities["outlet:new-daily"]["aliases"], ["newdaily.example"])

    def test_evidence_is_limited_and_skips_none_labels(self):
        items = [item(i, outlet="BBC", url=f"http://x/{i}") for i in range(5)]
        labels = {"0": lab("none", "ignored"), "1": lab("f1", "one"), "2": lab("f1", "two"), "3": lab("f1", "three"),
                  "4": lab("f2")}
        self.record(items, labels)
        ev = self.obs("outlet:bbc")["evidence"]
        self.assertEqual([e["quote"] for e in ev], ["one", "two"])
        self.assertEqual(ev[0], {"framing": "Celebratory", "quote": "one", "url": "http://x/1"})

    def test_rerunning_the_same_day_replaces_it_and_a_new_day_adds_a_row(self):
        items = [item(0, outlet="BBC")]
        self.record(items, {"0": lab("f1")})
        self.record(items, {"0": lab("f1")})
        self.assertEqual(len(self.kb.observations), 1)
        self.assertEqual(self.obs("outlet:bbc")["n_items"], 1)           # not 2
        self.record(items, {"0": lab("f2")})                              # the same day, relabelled: replaced, not merged
        self.assertEqual(self.obs("outlet:bbc")["counts"], {"Dismissive": 1})
        self.assertEqual(len(self.kb.observations), 1)
        self.record(items, {"0": lab("f2")}, day="2026-11-11")
        self.assertEqual(len(self.kb.observations), 2)

    def test_nothing_labelled_records_nothing(self):
        self.assertEqual(self.record([item(0, outlet="BBC")], {}), 0)
        self.assertEqual(self.kb.observations, {})


if __name__ == "__main__":
    unittest.main()
