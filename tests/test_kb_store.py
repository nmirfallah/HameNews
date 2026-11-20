import json
import os
import tempfile
import unittest

import helpers  # noqa: F401
from trendwatch.kb import KBError, KBStore
from trendwatch.kb.schema import check_date, entity_id, norm


class FilesCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.kb = KBStore(self.root)

    def entity(self, type_, name, **kw):
        return self.kb.upsert_entity(type_, name, **kw)[0]

    def claim(self, subject, predicate, object_, **kw):
        kw.setdefault("status", "reported")
        kw.setdefault("asserted_by", "tester")
        return self.kb.add_claim(subject["id"], predicate, object_["id"] if isinstance(object_, dict) else object_, **kw)


class SchemaHelperTests(unittest.TestCase):
    def test_norm_ignores_case_accents_and_punctuation(self):
        self.assertEqual(norm("  Télam!! "), "telam")
        self.assertEqual(norm("Al-Jazeera  English"), "al jazeera english")
        self.assertEqual(norm("الجزيرة نت"), "الجزيرة نت")
        self.assertEqual(norm(None), "")

    def test_entity_ids_are_readable_and_stable(self):
        self.assertEqual(entity_id("outlet", "Al Jazeera"), "outlet:al-jazeera")
        self.assertEqual(entity_id("account", "bluesky:alice.bsky.social"), "account:bluesky-alice-bsky-social")
        self.assertEqual(entity_id("outlet", "الجزيرة"), "outlet:الجزيرة")
        self.assertEqual(entity_id("outlet", "!!!"), "outlet:x")

    def test_dates(self):
        self.assertEqual(check_date("2026-11-15", "d"), "2026-11-15")
        self.assertEqual(check_date("", "d"), "")
        for bad in ("2026-13-01", "15/11/2026", "2026-11-31", "yesterday"):
            with self.assertRaises(KBError, msg=bad):
                check_date(bad, "d")


class EntityTests(FilesCase):
    def test_create_and_enrich_without_overwriting(self):
        e, created = self.kb.upsert_entity("outlet", "IRNA", ["irna.ir", "IRNA "], country="Iran", notes="first")
        self.assertTrue(created)
        self.assertEqual((e["id"], e["aliases"], e["country"]), ("outlet:irna", ["irna.ir"], "Iran"))
        e2, created = self.kb.upsert_entity("outlet", "IRNA", ["Islamic Republic News Agency", "irna.ir"],
                                            country="Elsewhere", notes="second")
        self.assertFalse(created)
        self.assertEqual(e2["aliases"], ["irna.ir", "Islamic Republic News Agency"])
        self.assertEqual((e2["country"], e2["notes"]), ("Iran", "first"))      # existing values are kept

    def test_blank_fields_are_filled_in_later(self):
        self.kb.upsert_entity("outlet", "X")
        e, _ = self.kb.upsert_entity("outlet", "X", country="France")
        self.assertEqual(e["country"], "France")

    def test_a_name_and_a_valid_type_are_required(self):
        with self.assertRaises(KBError):
            self.kb.upsert_entity("outlet", "  ")
        with self.assertRaises(KBError) as cm:
            self.kb.upsert_entity("newspaper", "X")
        self.assertIn("outlet", str(cm.exception))

    def test_lookup_by_id_name_alias_and_part_of_a_name(self):
        irna = self.entity("outlet", "IRNA", aliases=["irna.ir", "Islamic Republic News Agency"])
        self.entity("outlet", "Iran International")
        self.assertEqual(self.kb.find_exact("outlet:irna"), [irna])
        self.assertEqual(self.kb.find_exact("IRNA"), [irna])
        self.assertEqual(self.kb.find_exact("irna.ir"), [irna])
        self.assertEqual(self.kb.find_exact("islamic republic news agency!"), [irna])
        self.assertEqual(self.kb.find_exact("Iran"), [])                        # exact only
        self.assertEqual([e["id"] for e in self.kb.resolve("Iran")], ["outlet:iran-international"])
        self.assertEqual(self.kb.resolve("ir"), [])                              # too short for a partial match
        self.assertEqual(self.kb.resolve(""), [])

    def test_exact_lookup_can_be_limited_to_a_type(self):
        self.entity("outlet", "Iran")
        state = self.entity("state", "Iran")
        self.assertEqual(self.kb.find_exact("Iran", "state"), [state])
        self.assertEqual(len(self.kb.find_exact("Iran")), 2)

    def test_one_explains_missing_and_ambiguous_names(self):
        self.entity("outlet", "Iran")
        self.entity("state", "Iran")
        with self.assertRaises(KBError) as cm:
            self.kb.one("Iran")
        self.assertIn("several entities", str(cm.exception))
        self.assertIn("outlet:iran", str(cm.exception))
        self.assertEqual(self.kb.one("Iran", "state")["id"], "state:iran")
        with self.assertRaises(KBError) as cm:
            self.kb.one("Nothing")
        self.assertIn("add-entity", str(cm.exception))


class ClaimTests(FilesCase):
    def setUp(self):
        super().setUp()
        self.outlet = self.entity("outlet", "Iran International")
        self.state = self.entity("state", "Saudi Arabia")

    def test_a_full_claim(self):
        c, created = self.claim(self.outlet, "funded_by", self.state, source_url="https://example.com/a",
                                published="2018-10-31", valid_from="2016-01-01", note="n", asserted_by="The  Guardian")
        self.assertTrue(created)
        self.assertEqual((c["subject"], c["predicate"], c["object"], c["object_kind"], c["status"], c["asserted_by"]),
                         ("outlet:iran-international", "funded_by", "state:saudi-arabia", "entity", "reported", "The Guardian"))
        self.assertTrue(c["id"].startswith("c_"))
        self.assertEqual(c["added_by"], "user")

    def test_the_same_claim_twice_is_a_no_op_but_a_different_source_is_a_new_claim(self):
        first, _ = self.claim(self.outlet, "funded_by", self.state, source_url="https://a.example/1")
        again, created = self.claim(self.outlet, "funded_by", self.state, source_url="https://a.example/1", asserted_by="TESTER")
        self.assertEqual((again["id"], created), (first["id"], False))
        other, created = self.claim(self.outlet, "funded_by", self.state, source_url="https://b.example/2")
        self.assertTrue(created)
        self.assertNotEqual(other["id"], first["id"])
        self.assertEqual(len(self.kb.claims), 2)

    def test_a_denial_is_its_own_claim(self):
        a, _ = self.claim(self.outlet, "funded_by", self.state, status="reported", asserted_by="A newspaper")
        d, created = self.claim(self.outlet, "funded_by", self.state, status="denied", asserted_by="Iran International")
        self.assertTrue(created)
        self.assertNotEqual(a["id"], d["id"])

    def test_validation_errors_say_what_to_fix(self):
        bad = [
            (dict(predicate="nonsense"), "predicate"),
            (dict(status="proven"), "status"),
            (dict(asserted_by="  "), "asserted_by"),
            (dict(source_url="ftp://x"), "http"),
            (dict(published="soon"), "published"),
            (dict(valid_from="2020-05-01", valid_to="2019-01-01"), "valid_to"),
        ]
        for override, word in bad:
            args = dict(predicate="funded_by", status="reported", asserted_by="x")
            args.update(override)
            with self.assertRaises(KBError, msg=override) as cm:
                self.kb.add_claim(self.outlet["id"], args.pop("predicate"), self.state["id"], **args)
            self.assertIn(word, str(cm.exception))

    def test_subject_and_object_must_exist_and_cannot_be_the_same(self):
        with self.assertRaises(KBError):
            self.kb.add_claim("outlet:nope", "funded_by", self.state["id"], status="reported", asserted_by="x")
        with self.assertRaises(KBError):
            self.kb.add_claim(self.outlet["id"], "funded_by", "state:nope", status="reported", asserted_by="x")
        with self.assertRaises(KBError):
            self.kb.add_claim(self.outlet["id"], "funded_by", self.outlet["id"], status="reported", asserted_by="x")

    def test_leaning_takes_a_value_from_the_scale(self):
        c, _ = self.kb.add_claim(self.outlet["id"], "leaning", "center-right", status="inferred", asserted_by="AI")
        self.assertEqual((c["object"], c["object_kind"]), ("center-right", "value"))
        for bad in ("sideways", "", "Right"):
            with self.assertRaises(KBError, msg=bad):
                self.kb.add_claim(self.outlet["id"], "leaning", bad, status="inferred", asserted_by="AI")

    def test_claims_can_be_listed_by_direction_and_removed(self):
        c, _ = self.claim(self.outlet, "funded_by", self.state)
        self.assertEqual(self.kb.claims_of(self.outlet["id"], "out"), [c])
        self.assertEqual(self.kb.claims_of(self.outlet["id"], "in"), [])
        self.assertEqual(self.kb.claims_of(self.state["id"], "in"), [c])
        self.assertEqual(self.kb.claims_of(self.state["id"], "out"), [])
        self.assertEqual(len(self.kb.claims_of(self.state["id"])), 1)
        self.kb.remove_claim(c["id"])
        self.assertEqual(self.kb.claims, {})
        with self.assertRaises(KBError):
            self.kb.remove_claim(c["id"])


class ObservationTests(FilesCase):
    def test_an_observation_replaces_the_same_days_entry(self):
        e = self.entity("outlet", "BBC")
        self.kb.set_observation(e["id"], "iran-war", "Iran war", "2026-11-10", {"Hawkish": 2, "none": 1})
        row = self.kb.set_observation(e["id"], "iran-war", "Iran war", "2026-11-10", {"Hawkish": 5})
        self.assertEqual(len(self.kb.observations), 1)
        self.assertEqual((row["n_items"], row["counts"]), (5, {"Hawkish": 5}))
        stored = self.kb.observations[(e["id"], "iran-war", "2026-11-10")]
        self.assertEqual((stored["n_items"], stored["counts"]), (5, {"Hawkish": 5}))      # what is kept, not just what is returned
        self.kb.set_observation(e["id"], "iran-war", "Iran war", "2026-11-11", {"Hawkish": 1})
        self.assertEqual(len(self.kb.observations), 2)

    def test_evidence_is_capped_and_unknown_entities_rejected(self):
        e = self.entity("outlet", "BBC")
        row = self.kb.set_observation(e["id"], "t", "T", "2026-11-10", {"a": 1}, [{"q": i} for i in range(5)])
        self.assertEqual(len(row["evidence"]), 2)
        with self.assertRaises(KBError):
            self.kb.set_observation("outlet:nope", "t", "T", "2026-11-10", {"a": 1})


class PersistenceTests(FilesCase):
    def populate(self):
        a, b = self.entity("outlet", "Télam", aliases=["Telam"]), self.entity("state", "Argentina")
        self.claim(a, "state_linked", b, note="é — ünï")
        self.kb.set_observation(a["id"], "t", "T", "2026-11-10", {"x": 1})
        self.kb.save()

    def test_round_trip_preserves_everything_including_unicode(self):
        self.populate()
        again = KBStore(self.root)
        self.assertEqual(again.entities, self.kb.entities)
        self.assertEqual(again.claims, self.kb.claims)
        self.assertEqual(again.observations, self.kb.observations)
        with open(again.path("claims"), encoding="utf-8") as f:
            self.assertIn("é — ünï", f.read())            # stored readably, not as \u escapes

    def test_files_are_sorted_and_one_json_object_per_line(self):
        for name in ("Zeta", "Alpha", "Mid"):
            self.entity("outlet", name)
        self.kb.save()
        lines = open(self.kb.path("entities"), encoding="utf-8").read().splitlines()
        self.assertEqual([json.loads(l)["id"] for l in lines], ["outlet:alpha", "outlet:mid", "outlet:zeta"])
        self.assertTrue(all(l == json.dumps(json.loads(l), ensure_ascii=False, sort_keys=True) for l in lines))

    def test_saving_twice_gives_identical_files(self):
        self.populate()
        first = open(self.kb.path("claims"), "rb").read()
        again = KBStore(self.root)
        again._dirty.add("claims")
        again.save()
        self.assertEqual(open(again.path("claims"), "rb").read(), first)

    def test_only_changed_files_are_rewritten_and_no_temp_files_remain(self):
        self.populate()
        before = os.path.getmtime(self.kb.path("claims"))
        os.utime(self.kb.path("claims"), (before - 1000, before - 1000))
        self.kb.upsert_entity("outlet", "Another")
        self.kb.save()
        self.assertEqual(os.path.getmtime(self.kb.path("claims")), before - 1000)   # claims untouched
        self.assertEqual([f for f in os.listdir(self.kb.dir) if f.endswith(".tmp")], [])

    def test_nothing_is_written_when_nothing_changed(self):
        self.assertFalse(self.kb.dirty)
        self.kb.save()
        self.assertFalse(os.path.exists(self.kb.dir))

    def test_a_corrupted_line_is_reported_with_its_number(self):
        os.makedirs(os.path.join(self.root, "kb"))
        with open(os.path.join(self.root, "kb", "claims.jsonl"), "w", encoding="utf-8") as f:
            f.write('{"id": "c_1", "subject": "a"}\n{not json}\n')
        with self.assertRaises(KBError) as cm:
            KBStore(self.root)
        self.assertIn("line 2", str(cm.exception))


class IntegrityCheckTests(FilesCase):
    def test_a_healthy_store_has_no_problems(self):
        a, b = self.entity("outlet", "A"), self.entity("state", "S")
        self.claim(a, "state_linked", b)
        self.assertEqual(self.kb.check(), [])

    def test_hand_edits_that_break_the_rules_are_found(self):
        a = self.entity("outlet", "A")
        self.kb.entities["x:1"] = {"id": "x:1", "type": "alien", "name": "X", "aliases": []}
        self.kb.claims["c_bad"] = {"id": "c_bad", "subject": "outlet:ghost", "predicate": "rules", "object": "state:ghost",
                                   "object_kind": "entity", "status": "certain", "asserted_by": "",
                                   "valid_from": "2020-02-01", "valid_to": "2020-01-01"}
        self.kb.observations[("outlet:ghost", "t", "2026-01-01")] = {"entity": "outlet:ghost", "topic": "t",
                                                                      "date": "2026-01-01", "counts": {}, "n_items": 0}
        text = "\n".join(self.kb.check())
        for needle in ("unknown type 'alien'", "unknown predicate 'rules'", "unknown status 'certain'",
                       "subject 'outlet:ghost' does not exist", "object 'state:ghost' does not exist", "no asserted_by",
                       "valid_to is before valid_from", "observation outlet:ghost/t/2026-01-01: entity does not exist"):
            self.assertIn(needle, text)
        self.assertIn(a["id"], self.kb.entities)


if __name__ == "__main__":
    unittest.main()
