import tempfile
import unittest

from helpers import ScriptedLLM, cfg, item
from trendwatch.leanings import BUCKET, FILE, LEANINGS, assign_leanings, clean
from trendwatch.store import Store


class CleanTests(unittest.TestCase):
    def test_valid_values_and_normalisation(self):
        for v in LEANINGS:
            self.assertEqual(clean(v), v)
        self.assertEqual(clean(" Center Left "), "center-left")
        self.assertEqual(clean("CENTER_RIGHT"), "center-right")
        self.assertEqual(clean("centre-left"), "center-left")
        self.assertEqual(clean("lean right"), "center-right")
        self.assertEqual(clean("Centrist"), "center")

    def test_anything_else_is_unknown(self):
        for v in ("unknown", "", None, "far-out", 5, "state-aligned"):
            self.assertEqual(clean(v), "")

    def test_every_leaning_has_a_bucket(self):
        self.assertEqual(set(BUCKET), set(LEANINGS))
        self.assertEqual({BUCKET[v] for v in LEANINGS}, {"left-leaning", "centrist", "right-leaning"})


class AssignLeaningsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = Store(self._tmp.name)

    def reply(self, **mapping):
        return [{"outlet": k, "leaning": v} for k, v in mapping.items()]

    def test_ai_estimates_are_applied_cached_and_labelled(self):
        llm = ScriptedLLM([self.reply(Foo="right", Bar="center-left")])
        items = [item(1, outlet="Foo"), item(2, outlet="Bar")]
        assign_leanings(llm, items, self.store, cfg())
        self.assertEqual([(i.leaning, i.leaning_source) for i in items],
                         [("right", "AI estimate"), ("center-left", "AI estimate")])
        self.assertEqual(self.store.read(FILE)["Foo"], {"leaning": "right", "source": "AI estimate"})
        self.assertEqual(llm.calls[0]["tier"], "fast")

    def test_cached_outlets_are_not_asked_again_and_lookup_ignores_case(self):
        llm = ScriptedLLM([self.reply(Foo="right")])
        assign_leanings(llm, [item(1, outlet="Foo")], self.store, cfg())
        again = [item(2, outlet="foo")]
        assign_leanings(llm, again, self.store, cfg())
        self.assertEqual(again[0].leaning, "right")
        self.assertEqual(len(llm.calls), 1)

    def test_config_ratings_beat_the_cache_and_the_ai(self):
        self.store.write(FILE, {"Foo": {"leaning": "right", "source": "AI estimate"}})
        llm = ScriptedLLM([])
        conf = cfg(outlet_leanings={"foo": "Left", "Baz": "center"})
        items = [item(1, outlet="Foo"), item(2, outlet="Baz")]
        assign_leanings(llm, items, self.store, conf)
        self.assertEqual([(i.leaning, i.leaning_source) for i in items], [("left", "config"), ("center", "config")])
        self.assertEqual(llm.calls, [])

    def test_hand_edited_plain_string_entries_are_accepted_and_kept(self):
        self.store.write(FILE, {"Foo": "center-right"})
        llm = ScriptedLLM([])
        items = [item(1, outlet="Foo")]
        assign_leanings(llm, items, self.store, cfg())
        self.assertEqual((items[0].leaning, items[0].leaning_source), ("center-right", "user"))
        self.assertEqual(llm.calls, [])
        self.assertEqual(self.store.read(FILE), {"Foo": "center-right"})  # untouched

    def test_unknown_missing_and_invalid_answers_leave_the_leaning_empty(self):
        llm = ScriptedLLM([self.reply(A="unknown", B="sideways")])  # C is missing from the reply
        items = [item(1, outlet="A"), item(2, outlet="B"), item(3, outlet="C")]
        assign_leanings(llm, items, self.store, cfg())
        self.assertEqual([(i.leaning, i.leaning_source) for i in items], [("", "")] * 3)
        self.assertEqual({v["leaning"] for v in self.store.read(FILE).values()}, {"unknown"})
        assign_leanings(llm, [item(4, outlet="A")], self.store, cfg())
        self.assertEqual(len(llm.calls), 1)  # "unknown" is remembered, not re-asked

    def test_rows_for_outlets_that_were_not_asked_are_ignored(self):
        llm = ScriptedLLM([self.reply(Evil="right", Foo="left")])
        assign_leanings(llm, [item(1, outlet="Foo")], self.store, cfg())
        self.assertNotIn("Evil", self.store.read(FILE))

    def test_a_failed_call_is_not_cached_and_is_retried(self):
        llm = ScriptedLLM([RuntimeError("down"), self.reply(Foo="left")])
        first = [item(1, outlet="Foo")]
        assign_leanings(llm, first, self.store, cfg())
        self.assertEqual(first[0].leaning, "")
        self.assertIsNone(self.store.read(FILE))
        second = [item(2, outlet="Foo")]
        assign_leanings(llm, second, self.store, cfg())
        self.assertEqual(second[0].leaning, "left")

    def test_posts_are_never_given_a_leaning(self):
        llm = ScriptedLLM([])
        posts = [item(1, "post", "alice", platform="bluesky")]
        assign_leanings(llm, posts, self.store, cfg(outlet_leanings={"alice": "left"}))
        self.assertEqual(posts[0].leaning, "")
        self.assertEqual(llm.calls, [])

    def test_can_be_disabled(self):
        llm = ScriptedLLM([])
        items = [item(1, outlet="Foo")]
        assign_leanings(llm, items, self.store, cfg(leanings={"enabled": False}))
        self.assertEqual((items[0].leaning, llm.calls), ("", []))

    def test_outlets_are_classified_in_batches_of_forty(self):
        llm = ScriptedLLM([[], []])
        assign_leanings(llm, [item(i, outlet=f"O{i}") for i in range(45)], self.store, cfg())
        self.assertEqual(len(llm.calls), 2)

    def test_prompt_asks_for_unknown_instead_of_guessing(self):
        llm = ScriptedLLM([[]])
        assign_leanings(llm, [item(1, outlet="Foo")], self.store, cfg())
        prompt = llm.calls[0]["prompt"]
        self.assertTrue(prompt.startswith("TASK:classify_leanings"))
        self.assertIn("unknown", prompt)
        self.assertIn("Do not guess", prompt)
        self.assertIn("- Foo", prompt)

    def test_accepts_an_object_with_an_outlets_key(self):
        llm = ScriptedLLM([{"outlets": self.reply(Foo="right")}])
        items = [item(1, outlet="Foo")]
        assign_leanings(llm, items, self.store, cfg())
        self.assertEqual(items[0].leaning, "right")


if __name__ == "__main__":
    unittest.main()
