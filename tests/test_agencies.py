import re
import unittest

import helpers  # noqa: F401
from trendwatch import agencies
from trendwatch.config import build_config


class AgencyDataTests(unittest.TestCase):
    def test_every_entry_is_well_formed(self):
        for country, kind, names, domains in agencies.AGENCIES:
            self.assertTrue(country, country)
            self.assertIn(kind, agencies.LABEL, country)
            self.assertTrue(names, country)
            self.assertEqual(len(set(n.lower() for n in names)), len(names), f"duplicate name in {country}")
            for d in domains:
                self.assertRegex(d, r"^[a-z0-9.-]+\.[a-z]{2,}$", d)
                self.assertFalse(d.startswith(("http", "www.")), d)

    def test_no_domain_or_name_belongs_to_two_entries(self):
        domains, names = {}, {}
        for country, _, ns, ds in agencies.AGENCIES:
            for d in ds:
                self.assertNotIn(d, domains, f"{d}: {country} and {domains.get(d)}")
                domains[d] = country
            for n in ns:
                self.assertNotIn(n.lower(), names, f"{n}: {country} and {names.get(n.lower())}")
                names[n.lower()] = country

    def test_countries_are_unique_per_kind_only_via_group_names(self):
        for group in agencies.outlet_groups():
            self.assertRegex(group, r"^.+ (state-linked|public|independent) media$")

    def test_ambiguous_short_acronyms_stay_out(self):
        names = {n.lower() for _, _, ns, _ in agencies.AGENCIES for n in ns}
        for risky in ("cna", "map", "ina", "mena", "bss", "bna", "beta", "app", "nan", "kna", "pna"):
            self.assertNotIn(risky, names)

    def test_requested_outlets_are_present_in_the_right_groups(self):
        groups = agencies.outlet_groups()
        in_group = lambda g, n: n in groups[g]
        self.assertTrue(in_group("Qatar state-linked media", "Al Jazeera"))
        self.assertTrue(in_group("Russia state-linked media", "RT"))
        self.assertTrue(in_group("Iran state-linked media", "Tasnim News Agency"))
        self.assertTrue(in_group("Iran state-linked media", "Fars News Agency"))
        self.assertTrue(in_group("Iran state-linked media", "Islamic Republic News Agency"))
        self.assertTrue(in_group("China state-linked media", "Xinhua"))

    def test_ownership_kinds_follow_the_source_table(self):
        kinds = {c: k for c, k, _, _ in agencies.AGENCIES}
        self.assertEqual(kinds["China"], "state")
        self.assertEqual(kinds["Germany"], "independent")
        self.assertEqual(kinds["United States"], "independent")
        self.assertEqual(kinds["France"], "public")
        self.assertEqual(kinds["South Korea"], "public")

    def test_group_name(self):
        self.assertEqual(agencies.group_name("France", "public"), "France public media")
        self.assertEqual(agencies.group_name("China", "state"), "China state-linked media")

    def test_derived_tables_are_consistent(self):
        dg = agencies.domain_groups()
        self.assertEqual(len(dg), len(agencies.site_domains()))
        self.assertEqual(set(dg), set(agencies.site_domains()))
        self.assertTrue(set(dg.values()) <= set(agencies.outlet_groups()))
        self.assertEqual(dg["tass.com"], "Russia state-linked media")
        self.assertEqual(dg["afp.com"], "France public media")

    def test_enough_agencies_are_listed(self):
        self.assertGreaterEqual(len(agencies.AGENCIES), 55)
        self.assertGreaterEqual(len(agencies.site_domains()), 55)

    def test_merged_config_keeps_every_agency_name(self):
        cfg = build_config({})
        merged = {n for names in cfg["outlet_groups"].values() for n in names}
        for _, _, names, _ in agencies.AGENCIES:
            for n in names:
                self.assertIn(n, merged)


if __name__ == "__main__":
    unittest.main()
