import copy
import os
import tempfile
import unittest

import helpers
from trendwatch import sources
from trendwatch.config import DEFAULTS, build_config, deep_merge, load_config


class DeepMergeTests(unittest.TestCase):
    def test_dicts_merge_and_lists_are_replaced(self):
        base = {"a": {"b": 1, "c": 2}, "l": [1, 2]}
        out = deep_merge(base, {"a": {"b": 9}, "l": [3]})
        self.assertEqual(out, {"a": {"b": 9, "c": 2}, "l": [3]})

    def test_inputs_are_not_mutated(self):
        base = {"a": {"b": 1}}
        snapshot = copy.deepcopy(base)
        out = deep_merge(base, {"a": {"b": 2}})
        out["a"]["b"] = 3
        self.assertEqual(base, snapshot)

    def test_none_override(self):
        self.assertEqual(deep_merge({"a": 1}, None), {"a": 1})


class BuildConfigTests(unittest.TestCase):
    def test_defaults_do_not_leak_between_calls(self):
        before = copy.deepcopy(DEFAULTS)
        build_config({"analysis": {"min_kappa": 0.9}})
        self.assertEqual(DEFAULTS, before)

    def test_agencies_are_merged_into_groups_and_domains(self):
        cfg = build_config({})
        self.assertEqual(cfg["domain_groups"]["tass.com"], "Russia state-linked media")
        self.assertIn("China state-linked media", cfg["outlet_groups"])
        self.assertIn("Al Jazeera", cfg["outlet_groups"]["Qatar state-linked media"])
        self.assertIn("The Grayzone", cfg["outlet_groups"])

    def test_user_outlet_groups_are_added_and_merged(self):
        cfg = build_config({"outlet_groups": {"My Group": ["X"], "Qatar state-linked media": ["QNA Extra"]}})
        self.assertEqual(cfg["outlet_groups"]["My Group"], ["X"])
        self.assertIn("QNA Extra", cfg["outlet_groups"]["Qatar state-linked media"])
        self.assertIn("Al Jazeera", cfg["outlet_groups"]["Qatar state-linked media"])

    def test_agencies_can_be_disabled(self):
        cfg = build_config({"agencies": {"enabled": False}})
        self.assertEqual(cfg["domain_groups"], {})
        self.assertNotIn("China state-linked media", cfg["outlet_groups"])
        self.assertIn("Qatar state-linked media", cfg["outlet_groups"])  # manual groups stay

    def test_default_source_names_exist_in_the_registries(self):
        for name in DEFAULTS["discovery"]["enabled_sources"]:
            self.assertIn(name, sources.SIGNAL_SOURCES, name)
        for name in DEFAULTS["collection"]["sources"]:
            self.assertIn(name, sources.CONTENT_SOURCES, name)

    def test_leaning_defaults(self):
        cfg = build_config({})
        self.assertEqual(cfg["leanings"], {"enabled": True, "split_groups": True})
        self.assertEqual(cfg["outlet_leanings"], {})
        self.assertEqual(build_config({"outlet_leanings": {"X": "left"}})["outlet_leanings"], {"X": "left"})

    def test_language_defaults(self):
        cfg = build_config({})
        self.assertTrue(cfg["languages"]["translate"])
        self.assertTrue(cfg["languages"]["search_native"])
        codes = {e["lang"] for e in cfg["languages"]["editions"]}
        self.assertTrue({"ar", "he", "ru"} <= codes)
        for site in cfg["news_sites"]:
            if site["name"] in ("Tasnim News Agency", "Fars News Agency"):
                self.assertIn("fa", site["langs"])
        replaced = build_config({"languages": {"editions": [{"country": "JP", "lang": "ja"}]}})
        self.assertEqual(replaced["languages"]["editions"], [{"country": "JP", "lang": "ja"}])
        self.assertTrue(replaced["languages"]["translate"])  # the rest of the section is kept

    def test_default_models_exist_for_both_tiers(self):
        self.assertEqual(set(DEFAULTS["llm"]["models"]), {"fast", "smart"})


class LoadConfigTests(unittest.TestCase):
    def _write(self, text):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "c.yaml")
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def test_partial_yaml_falls_back_to_defaults(self):
        cfg = load_config(self._write("discovery:\n  topics_per_day: 7\n"))
        self.assertEqual(cfg["discovery"]["topics_per_day"], 7)
        self.assertEqual(cfg["discovery"]["min_platforms"], DEFAULTS["discovery"]["min_platforms"])

    def test_empty_yaml_gives_defaults(self):
        cfg = load_config(self._write(""))
        self.assertEqual(cfg["analysis"], DEFAULTS["analysis"])

    def test_the_shipped_config_yaml_is_valid(self):
        cfg = load_config(os.path.join(helpers.ROOT, "config.yaml"))
        self.assertEqual(cfg["llm"]["provider"], "anthropic")
        self.assertTrue(cfg["llm"]["models"]["fast"])
        self.assertTrue(cfg["llm"]["models"]["smart"])
        self.assertGreaterEqual(cfg["collection"]["max_articles"], 1)


if __name__ == "__main__":
    unittest.main()
