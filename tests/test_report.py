import unittest

import helpers  # noqa: F401
from trendwatch import report


def result(**over):
    base = {
        "topic": "Album Launch", "slug": "album-launch", "rank": 1,
        "summary": "A big album was released.",
        "platforms": ["google_trends", "wikipedia"], "n_signals": 3, "n_items": 24,
        "narratives": {
            "groups": [
                {"group": "Israeli media", "n_items": 3, "outlets": ["T1", "T2"],
                 "narrative": "According to Israeli media, it was big.",
                 "links": [{"outlet": "T1", "url": "http://t1/a"}]},
                {"group": "Iranian media", "n_items": 2, "outlets": ["P1"],
                 "narrative": "According to Iranian media, it was small.", "links": []}],
            "differences": "They use different terms.", "unclassified": 2},
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
        self.assertIn("### What each side says", md)
        self.assertIn("**Israeli media** (3 items; T1, T2)", md)
        self.assertIn("According to Israeli media, it was big.", md)
        self.assertIn("Sources: [T1](http://t1/a)", md)
        self.assertIn("**Where they differ:** They use different terms.", md)
        self.assertIn("2 items came from outlets whose origin is unknown", md)

    def test_manual_subject_says_so(self):
        self.assertIn("Subject chosen manually", report.render_topic(result(platforms=[], n_signals=0)))

    def test_fallback_when_no_narratives(self):
        md = report.render_topic(result(narratives=None))
        self.assertIn("Not enough attributable coverage", md)
        self.assertIn("24 items collected", md)
        md = report.render_topic(result(narratives={"groups": [], "differences": "", "unclassified": 0}))
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
        self.assertIn("What each side says", html)
        self.assertIn("According to Israeli media, it was big.", html)
        self.assertIn('<a href="http://t1/a" target="_blank" rel="noopener noreferrer">T1</a>', html)
        self.assertIn("Where they differ:", html)
        self.assertIn("<details><summary>Analysis details</summary>", html)
        self.assertIn("Divide verdict: strong", html)
        self.assertIn("AllSides: Center", html)

    def test_untrusted_text_is_escaped_everywhere(self):
        evil = "<img src=x onerror=alert(1)>"
        res = result(topic=evil, summary=evil, narrative=evil,
                     narratives={"groups": [{"group": evil, "n_items": 2, "outlets": [evil], "narrative": evil,
                                             "links": [{"outlet": evil, "url": "javascript:alert(1)"}]}],
                                 "differences": evil, "unclassified": 0},
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
