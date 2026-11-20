import tempfile
import unittest

import helpers  # noqa: F401
from trendwatch.kb import KBStore
from trendwatch.kb.background import Background


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.kb = KBStore(self._tmp.name)
        self.outlet = self.kb.upsert_entity("outlet", "Iran International", ["iranintl.com"])[0]
        self.state = self.kb.upsert_entity("state", "Saudi Arabia")[0]

    def claim(self, predicate, object_, status, by="x", **kw):
        self.kb.add_claim(self.outlet["id"], predicate, object_, status=status, asserted_by=by, **kw)

    def ref(self, name="Iran International", kind="article"):
        self.kb.save()
        return Background(self._tmp.name).reference(name, kind)

    def test_nothing_known_gives_an_empty_string(self):
        self.assertEqual(self.ref(), "")
        self.assertEqual(self.ref("Unknown Outlet"), "")

    def test_ties_are_described_with_their_status(self):
        self.claim("state_linked", self.state["id"], "reported")
        self.assertEqual(self.ref(), "state-linked to Saudi Arabia (reported)")

    def test_several_parts_are_joined_and_ordered(self):
        self.claim("funded_by", self.state["id"], "alleged")
        self.claim("owned_by", self.state["id"], "documented")
        self.claim("leaning", "center-right", "inferred", by="AI")
        self.assertEqual(self.ref(), "funded by Saudi Arabia (alleged); owned by Saudi Arabia (documented); leaning: center-right (inferred)")

    def test_a_denial_marks_the_claim_disputed_and_is_not_listed_as_a_tie(self):
        self.claim("funded_by", self.state["id"], "reported", by="A newspaper")
        self.claim("funded_by", self.state["id"], "denied", by="The outlet")
        self.assertEqual(self.ref(), "funded by Saudi Arabia (reported, disputed)")

    def test_a_lone_denial_is_not_shown_as_a_tie(self):
        self.claim("funded_by", self.state["id"], "denied")
        self.assertEqual(self.ref(), "")

    def test_the_strongest_leaning_claim_is_shown(self):
        self.claim("leaning", "right", "inferred", by="AI")
        self.claim("leaning", "center", "reported", by="user")
        self.assertEqual(self.ref(), "leaning: center (reported)")

    def test_lookup_works_by_alias_and_ignores_case(self):
        self.claim("state_linked", self.state["id"], "reported")
        self.assertEqual(self.ref("IRANINTL.com"), "state-linked to Saudi Arabia (reported)")

    def test_accounts_are_looked_up_as_accounts_and_ambiguous_names_give_nothing(self):
        acct = self.kb.upsert_entity("account", "bluesky:fan")[0]
        self.kb.add_claim(acct["id"], "affiliated_with", self.state["id"], status="self_described", asserted_by="bio")
        self.assertEqual(self.ref("bluesky:fan", "post"), "affiliated with Saudi Arabia (self_described)")
        self.assertEqual(self.ref("bluesky:fan", "article"), "")
        self.kb.upsert_entity("outlet", "Twin One", ["Twin"])
        self.kb.upsert_entity("outlet", "Twin Two", ["Twin"])
        self.assertEqual(self.ref("Twin"), "")

    def test_an_empty_knowledge_base_is_fine(self):
        self.assertEqual(Background(tempfile.mkdtemp()).reference("Anything"), "")


if __name__ == "__main__":
    unittest.main()
