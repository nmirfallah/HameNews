import json
import os
import tempfile
import unittest

import helpers
from helpers import cfg
from trendwatch import agencies
from trendwatch.kb import KBIndex, KBStore
from trendwatch.kb import seed


class SeedCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name

    def seeded(self, conf=None):
        seed.seed_all(self.root, conf or cfg())
        return KBStore(self.root)


class OutletSplitTests(unittest.TestCase):
    def test_single_outlet_entries_keep_their_names_and_domains_as_aliases(self):
        entry = next(e for e in agencies.AGENCIES if e[0] == "China")
        (o,) = seed.outlets_for(entry)
        self.assertEqual(o["name"], "Xinhua News Agency")
        self.assertIn("Xinhua", o["aliases"])
        self.assertIn("news.cn", o["aliases"])
        self.assertEqual(o["domains"], ["xinhuanet.com", "news.cn"])

    def test_entries_with_several_outlets_are_split_by_keywords(self):
        by_country = {c: {o["name"]: o for o in seed.outlets_for(e)} for e in agencies.AGENCIES
                      for c in [e[0]] if c in seed.SPLITS}
        iran = by_country["Iran"]
        self.assertEqual(set(iran), {"IRNA", "Tasnim News Agency", "Fars News Agency"})
        self.assertEqual(iran["IRNA"]["domains"], ["irna.ir"])
        self.assertIn("Islamic Republic News Agency", iran["IRNA"]["aliases"])
        self.assertIn("Tasnim", iran["Tasnim News Agency"]["aliases"])
        self.assertEqual(iran["Fars News Agency"]["domains"], ["farsnews.ir"])
        russia = by_country["Russia"]
        self.assertIn("Russia Today", russia["RT"]["aliases"])
        self.assertEqual(russia["RT"]["domains"], ["rt.com", "rt-english.com"])
        self.assertEqual(russia["TASS"]["domains"], ["tass.com"])
        qatar = by_country["Qatar"]
        self.assertEqual(qatar["Al Jazeera"]["domains"], ["aljazeera.com", "aljazeera.net"])
        self.assertIn("الجزيرة نت", qatar["Al Jazeera"]["aliases"])
        self.assertIn("QNA", qatar["Qatar News Agency"]["aliases"])
        uk = by_country["United Kingdom"]
        self.assertEqual(uk["PA Media"]["domains"], ["pa.media"])
        self.assertIn("Press Association", uk["PA Media"]["aliases"])
        self.assertEqual(uk["Reuters"]["domains"], ["reuters.com"])

    def test_every_listed_name_and_domain_ends_up_on_exactly_one_outlet(self):
        for entry in agencies.AGENCIES:
            outlets = seed.outlets_for(entry)
            labels = lambda o: {seed.norm(x) for x in [o["name"], *o["aliases"]]}
            for name in entry[2]:
                owners = [o["name"] for o in outlets if seed.norm(name) in labels(o)]
                self.assertEqual(len(owners), 1, f"{entry[0]}: {name} -> {owners}")
            self.assertEqual(sorted(d for o in outlets for d in o["domains"]), sorted(entry[3]), entry[0])


class SeedAgenciesTests(SeedCase):
    def test_first_run_adds_entities_and_claims_and_a_second_run_adds_nothing(self):
        first = seed.seed_all(self.root, cfg())
        self.assertGreater(first["entities_added"], 100)
        self.assertGreater(first["claims_added"], 90)
        self.assertEqual(seed.seed_all(self.root, cfg()), {"entities_added": 0, "claims_added": 0})

    def test_the_store_is_healthy_after_seeding(self):
        self.assertEqual(self.seeded().check(), [])

    def test_one_outlet_entity_per_agency_outlet_plus_the_configured_single_outlets(self):
        kb = self.seeded()
        outlets = [e for e in kb.entities.values() if e["type"] == "outlet"]
        expected = sum(len(seed.outlets_for(e)) for e in agencies.AGENCIES) + 1          # + The Grayzone
        self.assertEqual(len(outlets), expected)
        self.assertEqual({e["country"] for e in outlets if e["name"] == "The Grayzone"}, {""})

    def test_every_agency_name_and_domain_resolves_to_one_outlet_of_the_right_country(self):
        kb = self.seeded()
        for country, _, names, domains in agencies.AGENCIES:
            for label in [*names, *domains]:
                found = kb.find_exact(label, "outlet")
                self.assertEqual(len(found), 1, f"{country}: {label} -> {[e['id'] for e in found]}")
                self.assertEqual(found[0]["country"], country, label)

    def test_claims_follow_the_ownership_kind(self):
        kb = self.seeded()
        predicates = lambda name: {c["predicate"] for c in kb.claims_of(kb.find_exact(name, "outlet")[0]["id"], "out")}
        self.assertEqual(predicates("Tasnim News Agency"), {"based_in", "state_linked"})
        self.assertEqual(predicates("Agence France-Presse"), {"based_in", "publicly_funded_by"})
        self.assertEqual(predicates("Deutsche Presse-Agentur"), {"based_in"})                 # independent: no state tie
        self.assertEqual(predicates("Associated Press"), {"based_in"})
        self.assertEqual(predicates("Korean Central News Agency"), {"based_in", "state_linked"})  # no domain, still seeded

    def test_seeded_claims_are_honest_about_their_strength_and_origin(self):
        kb = self.seeded()
        for c in kb.claims.values():
            self.assertEqual((c["status"], c["asserted_by"], c["object_kind"]), ("reported", seed.SEED_AGENCY, "entity"))
            self.assertEqual(c["added_by"], "seed:agencies")
        ties = [c for c in kb.claims.values() if c["predicate"] in ("state_linked", "publicly_funded_by")]
        self.assertTrue(ties and all("Verify against a primary source" in c["note"] for c in ties))

    def test_countries_become_state_entities_with_common_aliases(self):
        kb = self.seeded()
        self.assertEqual(kb.find_exact("USA", "state")[0]["name"], "United States")
        self.assertEqual(kb.find_exact("Britain", "state")[0]["name"], "United Kingdom")
        self.assertEqual(kb.find_exact("Czechia", "state")[0]["name"], "Czech Republic")
        self.assertEqual(len(kb.find_exact("Iran", "state")), 1)

    def test_the_state_linked_outlets_of_iran_are_found_by_a_tie_query(self):
        kb = self.seeded()
        iran = kb.find_exact("Iran", "state")[0]["id"]
        names = {r["name"] for r in KBIndex(kb).tied_to(iran, 1)}
        self.assertEqual(names, {"IRNA", "Tasnim News Agency", "Fars News Agency"})
        qatar = kb.find_exact("Qatar", "state")[0]["id"]
        self.assertEqual({r["name"] for r in KBIndex(kb).tied_to(qatar, 1)}, {"Qatar News Agency", "Al Jazeera"})

    def test_edits_survive_reseeding(self):
        kb = self.seeded()
        irna = kb.find_exact("IRNA", "outlet")[0]
        irna["notes"] = "my own note"
        irna["country"] = "Edited"
        kb._dirty.add("entities")
        kb.save()
        seed.seed_all(self.root, cfg())
        again = KBStore(self.root).find_exact("IRNA", "outlet")[0]
        self.assertEqual((again["notes"], again["country"]), ("my own note", "Edited"))

    def test_a_claim_you_added_is_never_touched(self):
        kb = self.seeded()
        iran_intl = kb.upsert_entity("outlet", "Iran International")[0]
        saudi = kb.find_exact("Saudi Arabia", "state")[0]
        kb.add_claim(iran_intl["id"], "funded_by", saudi["id"], status="reported", asserted_by="A newspaper",
                     source_url="https://example.com/a")
        kb.save()
        seed.seed_all(self.root, cfg())
        self.assertEqual(len([c for c in KBStore(self.root).claims.values() if c["predicate"] == "funded_by"]), 1)


class SeedConfigTests(SeedCase):
    def test_a_group_named_after_its_first_name_becomes_one_outlet_with_aliases(self):
        grayzone = self.seeded().find_exact("Grayzone", "outlet")
        self.assertEqual(len(grayzone), 1)
        self.assertEqual((grayzone[0]["name"], grayzone[0]["aliases"]), ("The Grayzone", ["Grayzone", "thegrayzone.com"]))

    def test_groups_that_are_not_a_single_outlet_are_ignored(self):
        kb = self.seeded(cfg(outlet_groups={"My Group": ["Alpha", "Beta"]}))
        self.assertEqual(kb.find_exact("Alpha"), [])
        kb = self.seeded(cfg(outlet_groups={"Gamma": ["Gamma", "Gamma Daily"]}))
        self.assertEqual(kb.find_exact("Gamma Daily", "outlet")[0]["name"], "Gamma")


class SeedLeaningTests(SeedCase):
    def write_cache(self, data):
        with open(os.path.join(self.root, "outlet_leanings.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def leanings(self, kb, name):
        e = kb.find_exact(name, "outlet")[0]
        return [(c["object"], c["status"], c["asserted_by"]) for c in kb.claims_of(e["id"], "out") if c["predicate"] == "leaning"]

    def test_ai_estimates_user_edits_and_config_ratings_become_leaning_claims_with_their_origin(self):
        self.write_cache({"Foo Daily": {"leaning": "right", "source": "AI estimate"}, "Bar Post": "center-left",
                          "Unsure": {"leaning": "", "source": "AI estimate"}, "Baz": {"leaning": "unknown"}})
        kb = self.seeded(cfg(outlet_leanings={"Qux Times": "Left"}))
        self.assertEqual(self.leanings(kb, "Foo Daily"), [("right", "inferred", "HameNews AI estimate")])
        self.assertEqual(self.leanings(kb, "Bar Post"), [("center-left", "reported", "user (outlet_leanings.json)")])
        self.assertEqual(self.leanings(kb, "Qux Times"), [("left", "reported", "user (config.yaml)")])
        self.assertEqual(kb.find_exact("Unsure"), [])
        self.assertEqual(kb.find_exact("Baz"), [])

    def test_a_leaning_for_a_known_alias_lands_on_the_existing_outlet(self):
        self.write_cache({"AP News": {"leaning": "center", "source": "AI estimate"}})
        kb = self.seeded()
        self.assertEqual(self.leanings(kb, "Associated Press"), [("center", "inferred", "HameNews AI estimate")])
        self.assertEqual(len([e for e in kb.entities.values() if e["name"] == "AP News"]), 0)

    def test_a_changed_estimate_adds_a_claim_and_keeps_the_history(self):
        self.write_cache({"Foo Daily": {"leaning": "right", "source": "AI estimate"}})
        self.seeded()
        self.write_cache({"Foo Daily": {"leaning": "center-right", "source": "AI estimate"}})
        kb = self.seeded()
        self.assertEqual({l[0] for l in self.leanings(kb, "Foo Daily")}, {"right", "center-right"})

    def test_reseeding_the_same_leanings_adds_nothing(self):
        self.write_cache({"Foo Daily": {"leaning": "right", "source": "AI estimate"}})
        self.seeded()
        self.assertEqual(seed.seed_all(self.root, cfg()), {"entities_added": 0, "claims_added": 0})

    def test_an_ambiguous_name_is_skipped_not_guessed(self):
        kb = self.seeded()
        kb.upsert_entity("outlet", "Twin One", aliases=["Twin"])
        kb.upsert_entity("outlet", "Twin Two", aliases=["Twin"])
        kb.save()
        self.write_cache({"Twin": {"leaning": "left", "source": "AI estimate"}})
        before = len(KBStore(self.root).claims)
        seed.seed_all(self.root, cfg())
        self.assertEqual(len(KBStore(self.root).claims), before)

    def test_a_missing_or_corrupt_cache_file_is_fine(self):
        self.assertEqual(self.seeded().check(), [])
        with open(os.path.join(self.root, "outlet_leanings.json"), "w", encoding="utf-8") as f:
            f.write("{broken")
        self.assertEqual(self.seeded().check(), [])


if __name__ == "__main__":
    unittest.main()
