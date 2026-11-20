import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

import helpers
from trendwatch.kb import KBError, KBStore
from trendwatch.kb import cli as kb_cli


class CliCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name

    def run_kb(self, *args):
        return kb_cli.execute(["--data-dir", self.root, *args])

    def seeded(self):
        self.run_kb("seed")


class ReadCommandTests(CliCase):
    def test_seed_reports_what_it_added_and_is_repeatable(self):
        first = self.run_kb("seed")
        self.assertRegex(first, r"Seeded: \d{3} entities and \d{2,3} claims added\.")
        self.assertEqual(self.run_kb("seed"), "Seeded: 0 entities and 0 claims added.")

    def test_stats_and_check(self):
        self.seeded()
        stats = self.run_kb("stats")
        self.assertIn("Entities: outlet", stats)
        self.assertIn("Claims by status: reported", stats)
        self.assertIn("state_linked", stats)
        self.assertRegex(self.run_kb("check"), r"Knowledge base is consistent: \d+ entities, \d+ claims, 0 observations\.")

    def test_check_fails_with_every_problem_listed(self):
        self.seeded()
        with open(os.path.join(self.root, "kb", "claims.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": "c_bad", "subject": "outlet:ghost", "predicate": "state_linked", "object": "state:ghost",
                                "object_kind": "entity", "status": "reported", "asserted_by": "x"}) + "\n")
        with self.assertRaises(KBError) as cm:
            self.run_kb("check")
        self.assertIn("subject 'outlet:ghost' does not exist", str(cm.exception))
        self.assertIn("object 'state:ghost' does not exist", str(cm.exception))

    def test_search(self):
        self.seeded()
        out = self.run_kb("search", "tasnim")
        self.assertIn("outlet:tasnim-news-agency  Tasnim News Agency  (outlet)", out)
        self.assertEqual(self.run_kb("search", "zzzzzz"), "Nothing matches 'zzzzzz'.")

    def test_show_an_outlet(self):
        self.seeded()
        out = self.run_kb("show", "Tasnim")
        self.assertIn("Tasnim News Agency  (outlet, id outlet:tasnim-news-agency)", out)
        self.assertIn("Also known as: Tasnim, tasnimnews.ir", out)
        self.assertIn("Country: Iran", out)
        self.assertIn("state_linked Iran  [reported]  said by HameNews agency list", out)
        self.assertIn("note: Described as state-run", out)
        self.assertNotIn("Disputed", out)

    def test_show_a_state_lists_what_points_to_it(self):
        self.seeded()
        out = self.run_kb("show", "Iran")
        self.assertIn("Claims that point to it:", out)
        self.assertIn("Tasnim News Agency state_linked Iran  [reported]", out)

    def test_show_includes_disputes_and_observations(self):
        self.seeded()
        self.run_kb("add-entity", "outlet", "Iran International")
        for status, by in (("reported", "A newspaper"), ("denied", "Iran International")):
            self.run_kb("add-claim", "Iran International", "funded_by", "Saudi Arabia", "--status", status, "--by", by)
        kb = KBStore(self.root)
        kb.set_observation("outlet:iran-international", "t", "T", "2026-11-10", {"Hawkish": 3})
        kb.save()
        out = self.run_kb("show", "Iran International")
        self.assertIn("Disputed (a denial exists next to another claim; neither is treated as the truth):", out)
        self.assertIn("reported (by A newspaper), denied (by Iran International)", out)
        self.assertIn("Observed on 1 topic(s) over 1 day(s), 3 labelled items. Framings seen: Hawkish 3", out)

    def test_tied_to_and_connections(self):
        self.seeded()
        out = self.run_kb("tied-to", "Iran", "--hops", "1")
        self.assertIn("Fars News Agency (outlet)  1 hop(s), weakest link: reported", out)
        self.assertIn("Fars News Agency --state_linked--> Iran [reported]", out)
        self.assertIn("Télam (outlet)  1 hop(s), weakest link: reported", self.run_kb("tied-to", "Argentina", "--hops", "1"))
        out = self.run_kb("connections", "IRNA", "--hops", "1")
        self.assertIn("Iran (state)", out)
        self.assertRegex(out, r"IRNA --(based_in|state_linked)--> Iran \[reported\]")   # two equal links; either path is valid

    def test_alleged_claims_are_followed_only_on_request(self):
        self.seeded()
        self.run_kb("add-entity", "outlet", "Some Blog")
        self.run_kb("add-claim", "Some Blog", "funded_by", "Iran", "--status", "alleged", "--by", "Critics")
        self.assertNotIn("Some Blog", self.run_kb("tied-to", "Iran", "--hops", "1"))
        out = self.run_kb("tied-to", "Iran", "--hops", "1", "--include-alleged")
        self.assertIn("Some Blog (outlet)  1 hop(s), weakest link: alleged", out)
        self.assertIn("following: documented, self_described, reported, alleged", out)

    def test_nothing_found_messages_say_which_statuses_were_followed(self):
        self.seeded()
        self.assertEqual(self.run_kb("tied-to", "Iran", "--hops", "0"),
                         "Nothing is tied to Iran by the claims followed (documented, self_described, reported).")
        self.assertEqual(self.run_kb("connections", "IRNA", "--hops", "0"),
                         "No connections found for IRNA (statuses followed: documented, self_described, reported).")

    def test_disputed_lists_both_sides_with_their_sources(self):
        self.run_kb("add-entity", "outlet", "O")
        self.run_kb("add-entity", "state", "S")
        self.run_kb("add-claim", "O", "funded_by", "S", "--status", "reported", "--by", "Paper", "--source", "https://p.example/1")
        self.run_kb("add-claim", "O", "funded_by", "S", "--status", "denied", "--by", "O")
        out = self.run_kb("disputed")
        self.assertIn("O funded_by S", out)
        self.assertIn("[reported] said by Paper  https://p.example/1", out)
        self.assertIn("[denied] said by O", out)
        self.assertEqual(kb_cli.execute(["--data-dir", tempfile.mkdtemp(), "disputed"]), "No disputed claims.")

    def test_sql(self):
        self.seeded()
        out = self.run_kb("sql", "SELECT subject_name, object_name FROM v_claims WHERE predicate = 'state_linked' "
                                 "AND object_name = 'Iran' ORDER BY subject_name")
        self.assertEqual(out.splitlines()[0], "subject_name | object_name")
        self.assertIn("Tasnim News Agency | Iran", out)
        self.assertTrue(out.endswith("(3 row(s))"))
        with self.assertRaises(KBError):
            self.run_kb("sql", "DELETE FROM claims")


class WriteCommandTests(CliCase):
    def test_add_entity_then_a_sourced_claim_by_name(self):
        self.seeded()
        self.assertEqual(self.run_kb("add-entity", "outlet", "Iran International", "--alias", "iranintl.com",
                                     "--country", "United Kingdom"), "Added outlet:iran-international.")
        self.assertEqual(self.run_kb("add-entity", "outlet", "Iran International", "--notes", "x"), "Updated outlet:iran-international.")
        out = self.run_kb("add-claim", "Iran International", "funded_by", "Saudi Arabia", "--status", "reported",
                          "--by", "The Guardian", "--source", "https://example.com/a", "--published", "2018-10-31",
                          "--note", "per documents")
        self.assertIn("Added claim c_", out)
        self.assertIn("funded_by Saudi Arabia  [reported]  said by The Guardian, 2018-10-31", out)
        self.assertIn("source: https://example.com/a", out)
        kb = KBStore(self.root)
        (claim,) = [c for c in kb.claims.values() if c["predicate"] == "funded_by"]
        self.assertEqual((claim["subject"], claim["object"], claim["source_url"], claim["added_by"]),
                         ("outlet:iran-international", "state:saudi-arabia", "https://example.com/a", "user"))
        self.assertIn("Already present", self.run_kb("add-claim", "Iran International", "funded_by", "Saudi Arabia",
                                                     "--status", "reported", "--by", "The Guardian",
                                                     "--source", "https://example.com/a"))

    def test_a_leaning_claim_takes_a_value_not_an_entity(self):
        self.run_kb("add-entity", "outlet", "Foo")
        out = self.run_kb("add-claim", "Foo", "leaning", "right", "--status", "reported", "--by", "user")
        self.assertIn("leaning right  [reported]", out)
        with self.assertRaises(KBError):
            self.run_kb("add-claim", "Foo", "leaning", "sideways", "--status", "reported", "--by", "user")

    def test_unknown_and_ambiguous_names_are_explained(self):
        self.run_kb("add-entity", "outlet", "Iran")
        self.run_kb("add-entity", "state", "Iran")
        with self.assertRaises(KBError) as cm:
            self.run_kb("add-claim", "Nobody", "funded_by", "Iran", "--status", "reported", "--by", "x")
        self.assertIn("add-entity", str(cm.exception))
        with self.assertRaises(KBError) as cm:
            self.run_kb("add-claim", "Iran", "based_in", "Iran", "--status", "reported", "--by", "x")
        self.assertIn("matches several entities", str(cm.exception))

    def test_bad_input_is_rejected_by_the_parser_or_the_validator(self):
        self.run_kb("add-entity", "outlet", "A")
        self.run_kb("add-entity", "state", "S")
        with contextlib.redirect_stderr(io.StringIO()):
            for bad in (["add-claim", "A", "funded_by", "S", "--status", "proven", "--by", "x"],
                        ["add-claim", "A", "rules", "S", "--status", "reported", "--by", "x"],
                        ["add-entity", "newspaper", "X"], ["add-claim", "A", "funded_by", "S", "--status", "reported"]):
                with self.assertRaises(SystemExit, msg=bad):
                    self.run_kb(*bad)
        with self.assertRaises(KBError):
            self.run_kb("add-claim", "A", "funded_by", "S", "--status", "reported", "--by", "x", "--source", "not-a-url")

    def test_remove_claim(self):
        self.run_kb("add-entity", "outlet", "A")
        self.run_kb("add-entity", "state", "S")
        out = self.run_kb("add-claim", "A", "funded_by", "S", "--status", "reported", "--by", "x")
        cid = out.split("claim ")[1].split(":")[0]
        self.assertEqual(self.run_kb("remove-claim", cid), f"Removed {cid}.")
        self.assertEqual(KBStore(self.root).claims, {})
        with self.assertRaises(KBError):
            self.run_kb("remove-claim", cid)


class MainTests(CliCase):
    def test_main_prints_results_and_turns_errors_into_a_short_message(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            kb_cli.main(["--data-dir", self.root, "stats"])
        self.assertIn("Entities: none", out.getvalue())
        with self.assertRaises(SystemExit) as cm:
            kb_cli.main(["--data-dir", self.root, "show", "Nothing"])
        self.assertTrue(str(cm.exception).startswith("Error: No entity matches 'Nothing'"))

    def test_the_command_file_runs_as_a_script(self):
        done = subprocess.run([sys.executable, os.path.join(helpers.ROOT, "kb.py"), "--data-dir", self.root, "seed"],
                              capture_output=True, text=True, cwd=helpers.ROOT)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Seeded:", done.stdout)
        done = subprocess.run([sys.executable, os.path.join(helpers.ROOT, "kb.py"), "--data-dir", self.root, "show", "zzz"],
                              capture_output=True, text=True, cwd=helpers.ROOT)
        self.assertEqual(done.returncode, 1)
        self.assertIn("Error:", done.stderr)


if __name__ == "__main__":
    unittest.main()
