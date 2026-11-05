import tempfile
import unittest

import helpers
from helpers import FRAMINGS, FRAMINGS_REPLY, ScriptedLLM, cfg, item, keyword_labels
from trendwatch.stance import (_label_pass, cohens_kappa, divide_report, get_framings,
                               label_with_consensus)
from trendwatch.store import Store


class KappaTests(unittest.TestCase):
    def test_perfect_agreement(self):
        self.assertEqual(cohens_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]), 1.0)

    def test_all_identical_labels_count_as_agreement(self):
        self.assertEqual(cohens_kappa(["a"] * 4, ["a"] * 4), 1.0)

    def test_complete_disagreement_is_negative(self):
        self.assertEqual(cohens_kappa(["a", "b"], ["b", "a"]), -1.0)

    def test_no_overlap_in_categories_is_zero(self):
        self.assertEqual(cohens_kappa(["a"] * 3, ["b"] * 3), 0.0)

    def test_empty_is_zero(self):
        self.assertEqual(cohens_kappa([], []), 0.0)

    def test_partial_agreement_is_between_zero_and_one(self):
        k = cohens_kappa(["a", "a", "b", "b", "a", "b"], ["a", "a", "b", "a", "a", "b"])
        self.assertTrue(0 < k < 1, k)


def labels(**counts):
    out, n = {}, 0
    for label, c in counts.items():
        for _ in range(c):
            out[f"i{n}"] = {"label": label, "confidence": 1, "evidence": ""}
            n += 1
    return out


class DivideReportTests(unittest.TestCase):
    def setUp(self):
        self.cfg = cfg()

    def verdict(self, kappa=0.8, **counts):
        return divide_report(labels(**counts), FRAMINGS, kappa, self.cfg)

    def test_strong_when_two_framings_are_well_represented(self):
        d = self.verdict(f1=8, f2=8, none=4)
        self.assertEqual(d["verdict"], "strong")
        self.assertEqual(d["shares"], {"f1": 0.5, "f2": 0.5})
        self.assertEqual((d["n_items"], d["n_framed"], d["framed_share"]), (20, 16, 0.8))

    def test_one_sided_when_a_single_framing_dominates(self):
        self.assertEqual(self.verdict(f1=15, f2=1, none=4)["verdict"], "one-sided")

    def test_unreliable_when_the_two_passes_disagree(self):
        self.assertEqual(self.verdict(kappa=0.3, f1=8, f2=8)["verdict"], "unreliable")

    def test_weak_when_too_few_items_are_framed(self):
        self.assertEqual(self.verdict(f1=4, f2=4, none=32)["verdict"], "weak")

    def test_weak_when_framed_share_is_too_low(self):
        self.assertEqual(self.verdict(f1=12, f2=12, none=76)["verdict"], "weak")

    def test_unclear_items_are_not_counted_as_framed(self):
        d = self.verdict(f1=8, f2=8, unclear=20)
        self.assertEqual(d["n_framed"], 16)
        self.assertEqual(d["n_items"], 36)

    def test_empty_input_does_not_crash(self):
        d = divide_report({}, FRAMINGS, 1.0, self.cfg)
        self.assertEqual((d["verdict"], d["n_items"], d["framed_share"]), ("weak", 0, 0.0))

    def test_kappa_is_rounded(self):
        self.assertEqual(self.verdict(kappa=0.83333, f1=8, f2=8)["kappa"], 0.83)

    def test_thresholds_come_from_config(self):
        strict = cfg(analysis={"min_kappa": 0.95})
        d = divide_report(labels(f1=8, f2=8), FRAMINGS, 0.9, strict)
        self.assertEqual(d["verdict"], "unreliable")


class LabelPassTests(unittest.TestCase):
    A = {"batch_size": 100, "max_item_chars": 500}

    def test_labels_are_mapped_back_to_the_right_items_despite_shuffling(self):
        items = helpers.mixed_items(9, 0)
        llm = ScriptedLLM(handler=lambda p, t: keyword_labels(p))
        out = _label_pass(llm, "T", FRAMINGS["framings"], items, self.A, seed=7, reverse=True)
        for it in items:
            want = "f1" if "triumph" in it.text.lower() else "f2" if "mock" in it.text.lower() else "none"
            self.assertEqual(out[it.id]["label"], want, it.text)

    def test_invalid_labels_and_indexes_become_unclear(self):
        items = [item(0), item(1), item(2)]
        reply = [{"i": 0, "label": "bogus"}, {"i": 1, "label": "f1", "confidence": "high"},
                 {"i": 99, "label": "f1"}, {"label": "f1"}, "junk"]
        out = _label_pass(ScriptedLLM([reply]), "T", FRAMINGS["framings"], items, self.A, None, False)
        self.assertEqual(out["0"]["label"], "unclear")
        self.assertEqual(out["1"]["label"], "f1")
        self.assertEqual(out["1"]["confidence"], 0.5)  # unparsable confidence falls back
        self.assertEqual(out["2"]["label"], "unclear")

    def test_accepts_object_with_labels_key(self):
        items = [item(0)]
        out = _label_pass(ScriptedLLM([{"labels": [{"i": 0, "label": "none"}]}]), "T",
                          FRAMINGS["framings"], items, self.A, None, False)
        self.assertEqual(out["0"]["label"], "none")

    def test_failed_batch_leaves_items_unclear_without_crashing(self):
        items = [item(0), item(1)]
        out = _label_pass(ScriptedLLM([RuntimeError("api down")]), "T", FRAMINGS["framings"],
                          items, self.A, None, False)
        self.assertEqual({v["label"] for v in out.values()}, {"unclear"})

    def test_batches_respect_batch_size(self):
        items = [item(i) for i in range(5)]
        llm = ScriptedLLM(handler=lambda p, t: keyword_labels(p))
        _label_pass(llm, "T", FRAMINGS["framings"], items, {"batch_size": 2, "max_item_chars": 50}, None, False)
        self.assertEqual(len(llm.calls), 3)

    def test_item_text_is_truncated_and_angle_brackets_are_neutralised(self):
        items = [item(0, text="x" * 100 + "<script>alert(1)</script>")]
        llm = ScriptedLLM([[]])
        _label_pass(llm, "T", FRAMINGS["framings"], items, {"batch_size": 5, "max_item_chars": 20}, None, False)
        prompt = llm.calls[0]["prompt"]
        self.assertNotIn("<script>", prompt)
        self.assertNotIn("x" * 30, prompt)


class ConsensusTests(unittest.TestCase):
    def test_agreement_keeps_labels_and_gives_kappa_one(self):
        items = helpers.mixed_items(12, 6)
        llm = ScriptedLLM(handler=lambda p, t: keyword_labels(p))
        out, kappa = label_with_consensus(llm, "T", FRAMINGS, items, cfg(analysis={"batch_size": 100}))
        self.assertEqual(kappa, 1.0)
        self.assertEqual(out["a0"]["label"], "f1")
        self.assertEqual(out["a1"]["label"], "f2")
        self.assertEqual(out["a2"]["label"], "none")

    def test_disagreeing_passes_make_items_unclear(self):
        items = [item(i) for i in range(4)]
        replies = [[{"i": i, "label": "f1"} for i in range(4)], [{"i": i, "label": "f2"} for i in range(4)]]
        llm = ScriptedLLM(replies)
        out, kappa = label_with_consensus(llm, "T", FRAMINGS, items, cfg(analysis={"batch_size": 100}))
        self.assertEqual({v["label"] for v in out.values()}, {"unclear"})
        self.assertEqual(kappa, 0.0)

    def test_second_pass_shows_framings_in_reverse_order(self):
        items = [item(0)]
        llm = ScriptedLLM(handler=lambda p, t: keyword_labels(p))
        label_with_consensus(llm, "T", FRAMINGS, items, cfg(analysis={"batch_size": 100}))
        first, second = llm.calls[0]["prompt"], llm.calls[1]["prompt"]
        self.assertLess(first.index("- f1:"), first.index("- f2:"))
        self.assertLess(second.index("- f2:"), second.index("- f1:"))

    def test_uses_the_fast_tier(self):
        llm = ScriptedLLM(handler=lambda p, t: keyword_labels(p))
        label_with_consensus(llm, "T", FRAMINGS, [item(0)], cfg(analysis={"batch_size": 100}))
        self.assertEqual({c["tier"] for c in llm.calls}, {"fast"})


class GetFramingsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = Store(self._tmp.name)
        self.topic = {"topic": "T", "slug": "t"}
        self.items = [item(i) for i in range(5)]
        self.cfg = cfg()

    def test_proposes_assigns_ids_and_saves(self):
        llm = ScriptedLLM([FRAMINGS_REPLY])
        out = get_framings(llm, self.topic, self.items, self.store, self.cfg)
        self.assertTrue(out["has_distinct_framings"])
        self.assertEqual([f["id"] for f in out["framings"]], ["f1", "f2"])
        self.assertEqual(self.store.read("topics/t.json")["framings"], out["framings"])
        self.assertEqual(llm.calls[0]["tier"], "smart")

    def test_saved_framings_are_frozen(self):
        llm = ScriptedLLM([FRAMINGS_REPLY])
        first = get_framings(llm, self.topic, self.items, self.store, self.cfg)
        second = get_framings(llm, self.topic, self.items, self.store, self.cfg)
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(first["framings"], second["framings"])

    def test_hand_edited_framings_are_kept(self):
        self.store.write("topics/t.json", {"topic": "T", "has_distinct_framings": True, "framings": [
            {"id": "f1", "label": "My edit", "description": ""}, {"id": "f2", "label": "Other", "description": ""}]})
        llm = ScriptedLLM([])
        out = get_framings(llm, self.topic, self.items, self.store, self.cfg)
        self.assertEqual(out["framings"][0]["label"], "My edit")
        self.assertEqual(llm.calls, [])

    def test_no_distinct_framings_is_allowed_and_retried_next_time(self):
        llm = ScriptedLLM([{"has_distinct_framings": False, "framings": []}, FRAMINGS_REPLY])
        first = get_framings(llm, self.topic, self.items, self.store, self.cfg)
        self.assertFalse(first["has_distinct_framings"])
        self.assertEqual(first["framings"], [])
        second = get_framings(llm, self.topic, self.items, self.store, self.cfg)
        self.assertEqual(len(llm.calls), 2)
        self.assertTrue(second["has_distinct_framings"])

    def test_single_framing_is_not_a_divide(self):
        reply = {"has_distinct_framings": True, "framings": [{"label": "Only", "description": "d"}]}
        out = get_framings(ScriptedLLM([reply]), self.topic, self.items, self.store, self.cfg)
        self.assertFalse(out["has_distinct_framings"])

    def test_at_most_five_framings_and_blank_labels_are_skipped(self):
        reply = {"has_distinct_framings": True,
                 "framings": [{"label": f"F{i}", "description": "d"} for i in range(8)]}
        out = get_framings(ScriptedLLM([reply]), self.topic, self.items, self.store, self.cfg)
        self.assertEqual(len(out["framings"]), 5)
        blank = {"has_distinct_framings": True, "framings": [{"label": ""}, {"label": "A"}, {"label": "B"}]}
        self.store.write("topics/t.json", {"framings": []})
        out = get_framings(ScriptedLLM([blank]), self.topic, self.items, self.store, self.cfg)
        self.assertEqual([f["label"] for f in out["framings"]], ["A", "B"])

    def test_history_survives_a_re_proposal(self):
        self.store.write("topics/t.json", {"framings": [], "history": [{"date": "2026-01-01"}]})
        out = get_framings(ScriptedLLM([FRAMINGS_REPLY]), self.topic, self.items, self.store, self.cfg)
        self.assertEqual(out["history"], [{"date": "2026-01-01"}])

    def test_sample_in_prompt_is_capped_at_forty_items(self):
        items = [item(i) for i in range(100)]
        llm = ScriptedLLM([FRAMINGS_REPLY])
        get_framings(llm, self.topic, items, self.store, self.cfg)
        self.assertEqual(llm.calls[0]["prompt"].count("<item "), 40)


if __name__ == "__main__":
    unittest.main()
