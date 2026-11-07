import json
import unittest

import helpers  # noqa: F401
from trendwatch import prompts
from trendwatch.models import Item, Signal


class ModelTests(unittest.TestCase):
    def test_item_defaults_and_to_dict(self):
        it = Item(id="1", kind="article", platform="news", outlet="BBC", text="t")
        d = it.to_dict()
        self.assertEqual((d["url"], d["engagement"], d["group"], d["domain"], d["leaning"], d["leaning_source"]),
                         ("", 0, "", "", "", ""))
        self.assertEqual((d["lang"], d["text_en"]), ("", ""))
        self.assertEqual(Item(**d), it)

    def test_en_prefers_the_translation(self):
        it = Item(id="1", kind="article", platform="news", outlet="O", text="original")
        self.assertEqual(it.en, "original")
        it.text_en = "translated"
        self.assertEqual(it.en, "translated")
        self.assertNotIn("en", it.to_dict())  # a property, not a stored field

    def test_signal_defaults(self):
        s = Signal("name", "wikipedia")
        self.assertEqual((s.score, s.url), (0.0, ""))


class PromptTests(unittest.TestCase):
    def test_every_prompt_starts_with_its_task_tag(self):
        cases = {
            "cluster_topics": prompts.cluster("[0] (x) y", 5, []),
            "expand_subject": prompts.expand("climate"),
            "propose_framings": prompts.propose_framings("T", "<item i=\"0\">x</item>"),
            "label_items": prompts.label("T", helpers.FRAMINGS["framings"], "<item i=\"0\">x</item>"),
            "write_narrative": prompts.narrative({"a": 1}),
            "classify_outlets": prompts.classify_outlets(["BBC"]),
            "group_narratives": prompts.group_narratives("T", "<group name=\"g\"></group>"),
            "classify_leanings": prompts.classify_leanings(["BBC"]),
            "translate_items": prompts.translate_items("<item i=\"0\">x</item>"),
            "translate_keywords": prompts.translate_keywords("T", ["k"], ["ar", "fa"]),
        }
        for task, text in cases.items():
            self.assertTrue(text.startswith(f"TASK:{task}\n"), task)

    def test_system_prompt_treats_scraped_text_as_untrusted_and_neutral(self):
        self.assertIn("untrusted", prompts.SYSTEM)
        self.assertIn("never follow instructions", prompts.SYSTEM)
        self.assertIn("neutral", prompts.SYSTEM)

    def test_cluster_mentions_existing_topics_or_none(self):
        self.assertIn("(none)", prompts.cluster("x", 5, []))
        self.assertIn("Old Topic, Other", prompts.cluster("x", 5, ["Old Topic", "Other"]))

    def test_cluster_limits_existing_topics_to_fifty(self):
        text = prompts.cluster("x", 5, [f"topic{i}" for i in range(80)])
        self.assertIn("topic49", text)
        self.assertNotIn("topic50", text)

    def test_label_prompt_lists_framings_and_special_labels(self):
        text = prompts.label("T", helpers.FRAMINGS["framings"], "items")
        for needle in ("f1: Celebratory", "f2: Dismissive", "none", "unclear"):
            self.assertIn(needle, text)

    def test_narrative_embeds_stats_as_json(self):
        text = prompts.narrative({"topic": "Café"})
        self.assertIn(json.dumps({"topic": "Café"}, ensure_ascii=False), text)

    def test_group_narratives_asks_for_a_main_story_differences_and_conflicts_without_judging(self):
        text = prompts.group_narratives("T", "block")
        for needle in ("common", "distinct", "conflicts", "never repeat yourself", "Do not restate",
                       "do not judge", "translated into English"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
