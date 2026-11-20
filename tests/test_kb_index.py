import tempfile
import unittest

import helpers  # noqa: F401
from trendwatch.kb import KBError, KBIndex, KBStore


class GraphCase(unittest.TestCase):
    """A small graph:  A -owned_by-> C -owned_by-> S ;  B -state_linked-> S (alleged) ;  A -funded_by-> T (alleged)
    and a second route A -part_of-> M1/M2 -part_of-> S with different strengths."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.kb = KBStore(self._tmp.name)
        e = lambda t, n: self.kb.upsert_entity(t, n)[0]["id"]
        self.A, self.B = e("outlet", "Outlet A"), e("outlet", "Outlet B")
        self.C, self.S, self.T = e("company", "Company C"), e("state", "State S"), e("state", "State T")
        self.M1, self.M2, self.P = e("company", "Mid 1"), e("company", "Mid 2"), e("person", "Person P")
        self.acct = e("account", "bluesky:fan")
        self.claim(self.A, "owned_by", self.C, "documented")
        self.claim(self.C, "owned_by", self.S, "reported")
        self.claim(self.B, "state_linked", self.S, "alleged")
        self.claim(self.A, "funded_by", self.T, "alleged")
        self.index = KBIndex(self.kb)

    def claim(self, subject, predicate, object_, status, by="tester", **kw):
        return self.kb.add_claim(subject, predicate, object_, status=status, asserted_by=by, **kw)[0]

    def rebuild(self):
        self.index = KBIndex(self.kb)
        return self.index


class ClaimsAboutTests(GraphCase):
    def test_direction_and_ordering(self):
        self.claim(self.A, "funded_by", self.S, "reported")
        rows = self.index.claims_about(self.A)
        self.assertEqual([(c["direction"], c["predicate"]) for c in rows],
                         [("out", "funded_by"), ("out", "funded_by"), ("out", "owned_by")])
        self.assertEqual([c["status"] for c in rows[:2]], ["reported", "alleged"])      # strongest first
        self.assertEqual([c["direction"] for c in self.index.claims_about(self.S)], ["in", "in", "in"])
        self.assertEqual(len(self.index.claims_about(self.S, "out")), 0)


class ConnectionsTests(GraphCase):
    def names(self, results):
        return [r["name"] for r in results]

    def test_one_hop_follows_only_trusted_statuses_by_default(self):
        self.assertEqual(self.names(self.index.connections(self.A, 1)), ["Company C"])
        self.assertEqual(self.names(self.index.connections(self.A, 1, include=("documented", "reported", "alleged"))),
                         ["Company C", "State T"])

    def test_two_hops_reach_the_state_through_the_company_with_the_weakest_link_reported(self):
        rows = self.index.connections(self.A, 2)
        self.assertEqual([(r["name"], r["hops"], r["weakest"]) for r in rows],
                         [("Company C", 1, "documented"), ("State S", 2, "reported")])
        self.assertEqual([s["predicate"] for s in rows[1]["path"]], ["owned_by", "owned_by"])

    def test_links_can_be_followed_backwards(self):
        rows = self.index.connections(self.S, 2, include=("documented", "reported", "alleged"))
        self.assertEqual({r["name"] for r in rows}, {"Company C", "Outlet B", "Outlet A"})
        self.assertEqual(self.names(self.index.connections(self.S, 1, direction="out")), [])
        self.assertEqual(self.names(self.index.connections(self.C, 1, direction="in")), ["Outlet A"])

    def test_denied_claims_are_never_followed_even_when_listed(self):
        self.claim(self.B, "funded_by", self.T, "denied")
        rows = self.rebuild().connections(self.B, 1, include=("reported", "alleged", "denied"))
        self.assertEqual(self.names(rows), ["State S"])          # the alleged link is followed, the denial is not
        self.assertEqual(self.names(self.index.tied_to(self.T, 2, include=("alleged", "denied"), types=None)), ["Outlet A"])

    def test_predicates_can_be_restricted(self):
        rows = self.index.connections(self.A, 2, include=("documented", "reported", "alleged"), predicates=["funded_by"])
        self.assertEqual(self.names(rows), ["State T"])

    def test_cycles_do_not_loop_and_the_start_is_never_listed(self):
        self.claim(self.S, "part_of", self.A, "reported")
        rows = self.rebuild().connections(self.A, 5)
        self.assertEqual(len({r["entity"] for r in rows}), len(rows))
        self.assertNotIn(self.A, {r["entity"] for r in rows})

    def test_the_shortest_path_wins_and_among_equals_the_stronger_one(self):
        self.claim(self.A, "part_of", self.M1, "reported")
        self.claim(self.M1, "part_of", self.S, "reported")
        self.claim(self.A, "part_of", self.M2, "documented")
        self.claim(self.M2, "part_of", self.S, "documented")
        self.claim(self.A, "part_of", self.S, "reported")             # a direct (shorter) link, though weaker
        rows = {r["name"]: r for r in self.rebuild().connections(self.A, 2)}
        self.assertEqual(rows["State S"]["hops"], 1)
        # without the direct link, two routes of equal length: the documented one is chosen
        direct = next(c for c in self.kb.claims.values() if c["subject"] == self.A and c["object"] == self.S and c["predicate"] == "part_of")
        self.kb.remove_claim(direct["id"])
        self.kb.remove_claim(next(c["id"] for c in self.kb.claims.values() if c["subject"] == self.C and c["object"] == self.S))
        rows = {r["name"]: r for r in self.rebuild().connections(self.A, 2)}
        self.assertEqual((rows["State S"]["hops"], rows["State S"]["weakest"]), (2, "documented"))
        self.assertEqual(rows["State S"]["path"][0]["walk_to"], self.M2)

    def test_results_are_ordered_by_distance_then_strength_then_name(self):
        rows = self.index.connections(self.A, 2, include=("documented", "reported", "alleged"))
        self.assertEqual([(r["hops"], r["name"]) for r in rows], [(1, "Company C"), (1, "State T"), (2, "State S")])

    def test_unknown_entity(self):
        with self.assertRaises(KBError):
            self.index.connections("outlet:nope")


class TiedToTests(GraphCase):
    def test_outlets_tied_to_a_state_through_a_chain_of_owners(self):
        rows = self.index.tied_to(self.S, 2)
        self.assertEqual([(r["name"], r["hops"], r["weakest"]) for r in rows], [("Outlet A", 2, "reported")])
        chain = rows[0]["path"]
        self.assertEqual([(s["subject"], s["object"]) for s in chain], [(self.A, self.C), (self.C, self.S)])   # entity -> target

    def test_one_hop_is_not_enough_for_the_chain(self):
        self.assertEqual(self.index.tied_to(self.S, 1), [])

    def test_alleged_ties_only_count_when_asked_for(self):
        self.assertEqual([r["name"] for r in self.index.tied_to(self.S, 2)], ["Outlet A"])
        rows = self.index.tied_to(self.S, 2, include=("documented", "reported", "alleged"))
        self.assertEqual([(r["name"], r["hops"], r["weakest"]) for r in rows],
                         [("Outlet B", 1, "alleged"), ("Outlet A", 2, "reported")])      # nearest first

    def test_only_outlets_and_accounts_by_default_and_other_types_on_request(self):
        names = lambda rows: {r["name"] for r in rows}
        self.assertEqual(names(self.index.tied_to(self.S, 2)), {"Outlet A"})
        self.assertEqual(names(self.index.tied_to(self.S, 2, types=None)), {"Outlet A", "Company C"})

    def test_a_location_is_not_a_tie_and_employment_does_not_point_the_wrong_way(self):
        self.claim(self.B, "based_in", self.T, "documented")
        self.claim(self.T, "employs", self.P, "documented")
        rows = self.rebuild().tied_to(self.T, 2, include=("documented", "reported", "alleged"), types=None)
        self.assertEqual({r["name"] for r in rows}, {"Outlet A"})          # funded_by counts; based_in and employs do not

    def test_accounts_can_be_tied_too(self):
        self.claim(self.acct, "affiliated_with", self.B, "self_described")
        rows = self.rebuild().tied_to(self.S, 2, include=("documented", "reported", "self_described", "alleged"))
        self.assertIn("bluesky:fan", {r["name"] for r in rows})

    def test_unknown_target(self):
        with self.assertRaises(KBError):
            self.index.tied_to("state:nope")


class DisputeTests(GraphCase):
    def test_a_denial_next_to_another_claim_is_a_dispute(self):
        self.claim(self.B, "funded_by", self.T, "reported", by="A newspaper")
        self.claim(self.B, "funded_by", self.T, "denied", by="Outlet B")
        rows = self.rebuild().disputed()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["subject"], rows[0]["predicate"], rows[0]["object"]), (self.B, "funded_by", self.T))
        self.assertEqual([c["status"] for c in rows[0]["claims"]], ["reported", "denied"])

    def test_a_lone_denial_or_a_lone_allegation_is_not_a_dispute(self):
        self.claim(self.B, "funded_by", self.T, "denied")
        self.claim(self.A, "state_linked", self.S, "alleged")
        self.assertEqual(self.rebuild().disputed(), [])

    def test_different_objects_are_separate_triples(self):
        self.claim(self.B, "funded_by", self.T, "reported")
        self.claim(self.B, "funded_by", self.S, "denied")
        self.assertEqual(self.rebuild().disputed(), [])


class ProfileAndStatsTests(GraphCase):
    def test_profile_groups_claims_and_summarises_observations(self):
        self.kb.set_observation(self.A, "t1", "Topic 1", "2026-11-10", {"Hawkish": 3, "none": 1})
        self.kb.set_observation(self.A, "t2", "Topic 2", "2026-11-11", {"Hawkish": 1})
        self.claim(self.A, "funded_by", self.T, "denied")
        p = self.rebuild().profile(self.A)
        self.assertEqual(p["entity"]["name"], "Outlet A")
        self.assertEqual(len(p["out"]), 3)
        self.assertEqual(p["in"], [])
        self.assertEqual(p["observations"], {"days": 2, "topics": 2, "items": 5, "framings": {"Hawkish": 4, "none": 1}})
        self.assertEqual(len(p["disputes"]), 1)

    def test_observations_for_returns_parsed_rows(self):
        self.kb.set_observation(self.A, "t", "T", "2026-11-10", {"x": 2}, [{"quote": "é", "url": "u"}])
        rows = self.rebuild().observations_for(self.A)
        self.assertEqual((rows[0]["counts"], rows[0]["evidence"]), ({"x": 2}, [{"quote": "é", "url": "u"}]))

    def test_stats(self):
        s = self.index.stats()
        self.assertEqual(s["entities"], {"outlet": 2, "state": 2, "company": 3, "person": 1, "account": 1})
        self.assertEqual(s["claims_by_status"], {"alleged": 2, "documented": 1, "reported": 1})
        self.assertEqual(s["observations"], 0)


class SqlTests(GraphCase):
    def test_a_select_over_the_tables_and_the_readable_view(self):
        columns, rows = self.index.sql("SELECT subject_name, predicate, object_name, status FROM v_claims "
                                       "WHERE status = 'alleged' ORDER BY subject_name")
        self.assertEqual(columns, ["subject_name", "predicate", "object_name", "status"])
        self.assertEqual(rows, [("Outlet A", "funded_by", "State T", "alleged"), ("Outlet B", "state_linked", "State S", "alleged")])
        _, rows = self.index.sql("SELECT entity FROM aliases WHERE alias = 'Outlet A'")
        self.assertEqual(rows, [(self.A,)])
        _, rows = self.index.sql("WITH x AS (SELECT 1 AS n) SELECT n FROM x")
        self.assertEqual(rows, [(1,)])

    def test_the_limit_applies(self):
        _, rows = self.index.sql("SELECT id FROM claims", limit=2)
        self.assertEqual(len(rows), 2)

    def test_anything_that_could_change_or_escape_is_refused(self):
        for bad in ("DELETE FROM claims", "INSERT INTO claims VALUES (1)", "UPDATE claims SET status='x'",
                    "DROP TABLE claims", "PRAGMA query_only = OFF", "ATTACH DATABASE 'x.db' AS x",
                    "SELECT 1; DELETE FROM claims", "CREATE TABLE t (a)", "select * from claims; select 1"):
            with self.assertRaises(KBError, msg=bad):
                self.index.sql(bad)
        self.assertEqual(len(self.index.sql("SELECT * FROM claims")[1]), 4)

    def test_writes_hidden_inside_a_with_query_or_a_function_call_are_refused_by_the_guard(self):
        for bad in ("WITH x AS (SELECT 1) DELETE FROM claims", "WITH x AS (SELECT 1) UPDATE claims SET status = 'x'",
                    "SELECT load_extension('evil')", "SELECT 1 FROM claims WHERE 1; DROP TABLE claims"):
            with self.assertRaises(KBError, msg=bad) as cm:
                self.index.sql(bad)
            self.assertIn("read-only SELECT", str(cm.exception), bad)
        self.assertEqual(len(self.index.sql("SELECT * FROM claims")[1]), 4)       # nothing was damaged

    def test_sql_errors_become_readable_errors(self):
        with self.assertRaises(KBError) as cm:
            self.index.sql("SELECT nope FROM claims")
        self.assertIn("SQL error", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
