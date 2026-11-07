import unittest

import helpers  # noqa: F401
from trendwatch import report


def result(**over):
    base = {
        "topic": "Album Launch", "slug": "album-launch", "rank": 1,
        "summary": "A big album was released.",
        "platforms": ["google_trends", "wikipedia"], "n_signals": 3, "n_items": 24,
        "narratives": {
            "common": "A big album was released on Friday.",
            "common_links": [{"outlet": "AP", "url": "http://ap/1"}],
            "groups": [
                {"group": "Israeli media", "n_items": 3, "outlets": ["T1", "T2"],
                 "outlet_notes": ["T1: right (AI estimate)", "T2: center (config)"],
                 "languages": ["Arabic", "Persian"],
                 "distinct": "Calls it a triumph and stresses sales.",
                 "links": [{"outlet": "T1", "url": "http://t1/a"}]},
                {"group": "Iranian media", "n_items": 2, "outlets": ["P1"], "outlet_notes": [], "languages": [],
                 "distinct": "Plays down the sales figures.", "links": []},
                {"group": "UK media", "n_items": 2, "outlets": ["B1"], "outlet_notes": [], "languages": [],
                 "distinct": "", "links": []}],
            "conflicts": ["Israeli media says 10 million sold; Iranian media says 2 million."],
            "unclassified": 2},
        "divide": {"verdict": "strong", "kappa": 0.8, "n_items": 24, "n_framed": 16,
                   "shares": {"f1": 0.5, "f2": 0.5}, "counts": {"f1": 8, "f2": 8}},
        "framings": helpers.FRAMINGS,
        "narrative": "Neutral briefing text.",
        "rows": {"outlets": [{"name": "BBC", "n": 12, "label": "leans: Celebratory (90% of framed)",
                              "confidence": "medium", "reference": "AllSides: Center",
                              "evidence": [{"framing": "f1", "quote": "a triumph", "url": "http://bbc/1"}]}],
                 "accounts": []},
    }
    base.update(over)
    return base


class MarkdownTests(unittest.TestCase):
    def test_report_header_and_ranked_list(self):
        md = report.render("2026-01-01", [result(), result(topic="Other", rank=2)])
        self.assertIn("# HameNews report 2026-01-01", md)
        self.assertIn("## Trending now", md)
        self.assertIn("1. Album Launch", md)
        self.assertIn("2. Other", md)
        self.assertIn("not what is true", report.NOTE)

    def test_topic_section(self):
        md = report.render_topic(result())
        self.assertIn("## #1 Album Launch", md)
        self.assertIn("_Trending on google_trends, wikipedia (3 signals)_", md)
        self.assertIn("### The main story", md)
        self.assertIn("A big album was released on Friday.", md)
        self.assertIn("Sources: [AP](http://ap/1)", md)
        self.assertIn("### How each side differs", md)
        self.assertIn("**Israeli media** (3 items; T1, T2)", md)
        self.assertIn("Calls it a triumph and stresses sales.", md)
        self.assertIn("Sources: [T1](http://t1/a)", md)
        self.assertIn("Outlet leanings: T1: right (AI estimate); T2: center (config)", md)
        self.assertIn("Translated from: Arabic, Persian", md)
        self.assertIn("### Points of disagreement", md)
        self.assertIn("- Israeli media says 10 million sold; Iranian media says 2 million.", md)
        self.assertIn("2 items came from outlets whose origin is unknown", md)

    def test_the_one_line_topic_summary_is_dropped_when_a_main_story_exists(self):
        self.assertNotIn("A big album was released.", report.render_topic(result()))
        self.assertNotIn("A big album was released.</p>", report.render_html("d", [result()]).replace(
            "A big album was released on Friday.", ""))

    def test_the_one_line_topic_summary_is_kept_when_there_is_no_main_story(self):
        res = result()
        res["narratives"].update(common="", common_links=[])
        self.assertIn("A big album was released.\n", report.render_topic(res))
        self.assertIn("<p>A big album was released.</p>", report.render_html("d", [res]))
        self.assertIn("A big album was released.\n", report.render_topic(result(narratives=None)))

    def test_sections_come_in_the_right_order(self):
        md = report.render_topic(result())
        order = [md.index(h) for h in ("### The main story", "### How each side differs",
                                       "### Points of disagreement", "### Analysis details")]
        self.assertEqual(order, sorted(order))

    def test_groups_with_nothing_distinct_are_listed_in_one_line_not_given_a_block(self):
        md = report.render_topic(result())
        self.assertIn("Reported much the same as the main story: UK media", md)
        self.assertNotIn("**UK media**", md)

    def test_every_group_block_shows_only_its_own_text(self):
        md = report.render_topic(result())
        self.assertEqual(md.count("A big album was released on Friday."), 1)

    def test_without_a_main_story_or_conflicts_those_headings_are_left_out(self):
        res = result()
        res["narratives"].update(common="", common_links=[], conflicts=[])
        md = report.render_topic(res)
        self.assertNotIn("### The main story", md)
        self.assertNotIn("### Points of disagreement", md)
        self.assertIn("### How each side differs", md)

    def test_only_a_main_story_when_every_group_is_similar(self):
        res = result()
        for g in res["narratives"]["groups"]:
            g["distinct"] = ""
        md = report.render_topic(res)
        self.assertIn("### The main story", md)
        self.assertNotIn("### How each side differs", md)
        self.assertIn("Reported much the same as the main story: Israeli media, Iranian media, UK media", md)

    def test_manual_subject_says_so(self):
        self.assertIn("Subject chosen manually", report.render_topic(result(platforms=[], n_signals=0)))

    def test_fallback_when_no_narratives(self):
        md = report.render_topic(result(narratives=None))
        self.assertIn("Not enough attributable coverage", md)
        self.assertIn("24 items collected", md)
        md = report.render_topic(result(narratives={"common": "", "common_links": [], "groups": [],
                                                    "conflicts": [], "unclassified": 0}))
        self.assertIn("Not enough attributable coverage", md)

    def test_analysis_details(self):
        md = report.render_topic(result())
        self.assertIn("### Analysis details", md)
        self.assertIn("**Divide verdict: strong**", md)
        self.assertIn("kappa 0.8", md)
        self.assertIn("16/24 items", md)
        self.assertIn("| Celebratory | d1 | 50% |", md)
        self.assertIn("Neutral briefing text.", md)
        self.assertIn("| BBC | 12 | leans: Celebratory (90% of framed) | medium | AllSides: Center |", md)
        self.assertIn("“a triumph” (http://bbc/1)", md)

    def test_verdict_with_note_and_no_stats(self):
        md = report.render_topic(result(divide={"verdict": "insufficient data", "note": "Only 2 items found."},
                                        framings={}, rows=None, narrative=None))
        self.assertIn("**Divide verdict: insufficient data**", md)
        self.assertIn("Only 2 items found.", md)
        self.assertNotIn("kappa", md)

    def test_groups_without_translations_show_no_translation_line(self):
        res = result()
        res["narratives"]["groups"][0]["languages"] = []
        self.assertNotIn("Translated from", report.render_topic(res).split("Iranian media")[0])

    def test_the_report_warns_that_other_languages_are_machine_translated(self):
        self.assertIn("machine-translated", report.NOTE)

    def test_the_report_explains_where_leaning_labels_come_from(self):
        self.assertIn("AI estimate", report.NOTE)
        self.assertIn("your own ratings", report.NOTE)

    def test_empty_tables_say_no_data(self):
        md = report.render_topic(result(rows={"outlets": [], "accounts": []}))
        self.assertIn("_No data yet._", md)

    def test_render_with_no_topics(self):
        md = report.render("2026-01-01", [])
        self.assertIn("## Trending now", md)


class HtmlTests(unittest.TestCase):
    def test_page_structure(self):
        html = report.render_html("2026-01-01", [result(), result(topic="Other", rank=2)])
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertIn("<title>HameNews 2026-01-01</title>", html)
        self.assertIn("width=device-width", html)
        self.assertIn("prefers-color-scheme:dark", html)
        self.assertIn("<li>Album Launch</li>", html)
        self.assertIn("#1</span> Album Launch", html)

    def test_sides_links_and_details(self):
        html = report.render_html("d", [result()])
        self.assertIn("<h3>The main story</h3>", html)
        self.assertIn("A big album was released on Friday.", html)
        self.assertIn('<a href="http://ap/1" target="_blank" rel="noopener noreferrer">AP</a>', html)
        self.assertIn("<h3>How each side differs</h3>", html)
        self.assertIn("Calls it a triumph and stresses sales.", html)
        self.assertIn('<a href="http://t1/a" target="_blank" rel="noopener noreferrer">T1</a>', html)
        self.assertIn("Outlet leanings: T1: right (AI estimate); T2: center (config)", html)
        self.assertIn("Translated from: Arabic, Persian", html)
        self.assertIn("<h3>Points of disagreement</h3>", html)
        self.assertIn("<li>Israeli media says 10 million sold; Iranian media says 2 million.</li>", html)
        self.assertIn("Reported much the same as the main story: UK media", html)
        self.assertIn("<details><summary>Analysis details</summary>", html)
        self.assertIn("Divide verdict: strong", html)
        self.assertIn("AllSides: Center", html)

    def test_the_main_story_is_shown_once(self):
        self.assertEqual(report.render_html("d", [result()]).count("A big album was released on Friday."), 1)

    def test_untrusted_text_is_escaped_everywhere(self):
        evil = "<img src=x onerror=alert(1)>"
        res = result(topic=evil, summary=evil, narrative=evil,
                     narratives={"common": evil, "common_links": [{"outlet": evil, "url": "javascript:alert(1)"}],
                                 "groups": [{"group": evil, "n_items": 2, "outlets": [evil], "outlet_notes": [evil],
                                             "languages": [evil], "distinct": evil,
                                             "links": [{"outlet": evil, "url": "javascript:alert(1)"}]}],
                                 "conflicts": [evil], "unclassified": 0},
                     rows={"outlets": [{"name": evil, "n": 3, "label": evil, "confidence": evil,
                                        "reference": evil,
                                        "evidence": [{"framing": "f1", "quote": evil, "url": "data:text/html,x"}]}],
                           "accounts": []})
        html = report.render_html("d", [res])
        self.assertNotIn("<img", html)
        self.assertNotIn("javascript:", html)
        self.assertNotIn("data:text/html", html)
        self.assertIn("&lt;img", html)

    def test_only_http_links_become_anchors(self):
        self.assertEqual(report._safe_url("https://x.org/a"), "https://x.org/a")
        self.assertEqual(report._safe_url("http://x.org"), "http://x.org")
        for bad in ("javascript:alert(1)", "ftp://x", "", None, 5):
            self.assertEqual(report._safe_url(bad), "")
        self.assertEqual(report._link("label", "javascript:x"), "label")
        self.assertIn('href="https://x.org"', report._link("label", "https://x.org"))

    def test_quotes_in_urls_cannot_break_out_of_the_attribute(self):
        out = report._link("l", 'http://x.org/"onmouseover="alert(1)')
        self.assertNotIn('"onmouseover="', out)

    def test_html_handles_missing_sections(self):
        html = report.render_html("d", [result(narratives=None, rows=None, framings={}, narrative=None,
                                                divide={"verdict": "weak", "note": "n"})])
        self.assertIn("Not enough attributable coverage", html)
        self.assertIn("Divide verdict: weak", html)


if __name__ == "__main__":
    unittest.main()
