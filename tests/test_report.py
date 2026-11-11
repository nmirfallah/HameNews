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


ALSO = [{"rank": 3, "topic": "Krakow shooting", "summary": "A gunman opened fire.", "platforms": ["bluesky", "news"],
         "n_signals": 8, "n_outlets": 5,
         "signals": [{"platform": "news", "name": "Five killed in Krakow [BBC]", "url": "http://bbc/1", "source": "BBC"},
                     {"platform": "bluesky", "name": "Krakow", "url": "", "source": ""},
                     {"platform": "news", "name": "Evil <b>link</b>", "url": "javascript:alert(1)", "source": "X"}]},
        {"rank": 4, "topic": "Bare topic", "summary": "", "platforms": ["news"], "n_signals": 2, "n_outlets": 0,
         "signals": []}]


class AlsoTrendingTests(unittest.TestCase):
    def test_every_topic_appears_in_the_ranked_list_with_the_unanalysed_ones_marked(self):
        md = report.render("d", [result()], ALSO)
        self.assertIn("1. Album Launch\n", md)
        self.assertIn("3. Krakow shooting (headlines only)", md)
        self.assertIn("4. Bare topic (headlines only)", md)
        self.assertLess(md.index("1. Album Launch"), md.index("3. Krakow shooting"))

    def test_the_ranked_list_is_ordered_by_rank_even_when_results_and_extras_interleave(self):
        also = [dict(ALSO[0], rank=2), dict(ALSO[1], rank=5)]
        md = report.render("d", [result(rank=1), result(topic="Late", rank=4)], also)
        order = [md.index(x) for x in ("1. Album Launch", "2. Krakow shooting", "4. Late", "5. Bare topic")]
        self.assertEqual(order, sorted(order))

    def test_markdown_section(self):
        md = report.render("d", [result()], ALSO)
        self.assertIn("## Also trending (headlines only)", md)
        self.assertIn("topics_per_day", md)
        self.assertIn("### #3 Krakow shooting", md)
        self.assertIn("_Trending on bluesky, news (8 signals, 5 outlets)_", md)
        self.assertIn("A gunman opened fire.", md)
        self.assertIn("- [Five killed in Krakow [BBC]](http://bbc/1)", md)
        self.assertIn("- Krakow\n", md)                       # no url: plain text
        self.assertNotIn("](javascript:", md)                   # unsafe urls are never linked

    def test_no_extras_means_no_section(self):
        self.assertNotIn("Also trending", report.render("d", [result()]))
        self.assertNotIn("Also trending", report.render_html("d", [result()]))

    def test_html_section(self):
        html = report.render_html("d", [result()], ALSO)
        self.assertIn("<h2>Also trending (headlines only)</h2>", html)
        self.assertIn("Krakow shooting", html)
        self.assertIn("(8 signals, 5 outlets)", html)
        self.assertIn('<a href="http://bbc/1"', html)
        self.assertIn("(headlines only)", html)
        self.assertNotIn("javascript:", html)
        self.assertNotIn("<b>link</b>", html)                   # untrusted text is escaped

    def test_trend_line_shows_outlets_when_known_and_watchlist_topics_say_so(self):
        self.assertIn("(3 signals, 4 outlets)", report.render_topic(result(n_outlets=4)))
        watch = result(platforms=[], n_signals=0, watchlist=True)
        self.assertIn("Watchlist topic (no trend signals today)", report.render_topic(watch))
        self.assertIn("Subject chosen manually", report.render_topic(result(platforms=[], n_signals=0)))


class EmailHtmlTests(unittest.TestCase):
    def render(self, **kw):
        return report.render_email_html("2026-11-10", [result()], ALSO, kw.get("focus"))

    def test_it_uses_only_what_email_clients_support(self):
        html = self.render()
        for banned in ("<style", "<details", "<script", "var(--", "prefers-color-scheme", "<summary"):
            self.assertNotIn(banned, html)
        self.assertIn('style="', html)
        self.assertTrue(html.startswith("<!doctype html>"))

    def test_everything_a_reader_needs_is_expanded_in_the_body(self):
        html = self.render()
        for needle in ("Trending now", "Album Launch", "The main story", "A big album was released on Friday.",
                       "How each side differs", "Israeli media", "Calls it a triumph and stresses sales.",
                       "Points of disagreement", "Israeli media says 10 million sold; Iranian media says 2 million.",
                       "Reported much the same as the main story: UK media", "Also trending (headlines only)",
                       "Krakow shooting", "The full report with tables is attached."):
            self.assertIn(needle, html)

    def test_the_main_story_appears_once_and_the_one_line_summary_is_dropped(self):
        html = self.render()
        self.assertEqual(html.count("A big album was released on Friday."), 1)
        self.assertNotIn("A big album was released.<", html)

    def test_ranked_list_marks_headline_only_topics(self):
        html = self.render()
        self.assertIn('<li value="1"', html)
        self.assertIn('<li value="3"', html)
        self.assertIn("(headlines only)", html)

    def test_links_are_safe_and_untrusted_text_is_escaped(self):
        evil = "<img src=x onerror=alert(1)>"
        res = result(topic=evil, narratives={"common": evil, "common_links": [{"outlet": evil, "url": "javascript:alert(1)"}],
                                             "groups": [{"group": evil, "n_items": 2, "outlets": [evil], "outlet_notes": [evil],
                                                         "languages": [evil], "distinct": evil, "links": [{"outlet": "x", "url": "data:text/html,x"}]}],
                                             "conflicts": [evil], "unclassified": 0})
        html = report.render_email_html("d", [res], [dict(ALSO[0], summary=evil)])
        self.assertNotIn("<img", html)
        self.assertNotIn("javascript:", html)
        self.assertNotIn("data:text/html", html)
        self.assertIn("&lt;img", html)

    def test_real_links_are_clickable_and_coloured_inline(self):
        html = self.render()
        self.assertIn('<a href="http://t1/a" style="color:#0b5fff">T1</a>', html)
        self.assertIn('<a href="http://bbc/1"', html)

    def test_leanings_and_translations_are_shown_under_each_side(self):
        html = self.render()
        self.assertIn("Outlet leanings: T1: right (AI estimate); T2: center (config)", html)
        self.assertIn("Translated from: Arabic, Persian", html)

    def test_the_focus_source_summary_and_items_appear(self):
        info = {"name": "IRNA", "n_items": 9, "languages": {"Persian": 9}, "topics_covered": 1, "topics_total": 2, "flagged": 0}
        res = result(focus={"source": "IRNA", "items": [{"english": "Talks resume", "original": "مذاکرات", "lang": "fa",
                                                         "lang_name": "Persian", "url": "http://i/1", "flags": []}]})
        html = report.render_email_html("d", [res], (), info)
        self.assertIn("Focus source: IRNA.", html)
        self.assertIn("What IRNA reported", html)
        self.assertIn("Talks resume", html)
        self.assertIn("original: مذاکرات", html)

    def test_a_topic_without_attributable_coverage_says_so(self):
        html = report.render_email_html("d", [result(narratives=None)])
        self.assertIn("Not enough attributable coverage", html)

    def test_no_topics_still_renders(self):
        html = report.render_email_html("2026-11-10", [])
        self.assertIn("HameNews", html)
        self.assertNotIn("Also trending", html)

    def test_it_is_far_smaller_than_the_full_report_because_tables_stay_in_the_attachment(self):
        self.assertNotIn("<table", self.render())
        self.assertIn("<table", report.render_html("d", [result()], ALSO))


class HtmlTests(unittest.TestCase):
    def test_page_structure(self):
        html = report.render_html("2026-01-01", [result(), result(topic="Other", rank=2)])
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertIn("<title>HameNews 2026-01-01</title>", html)
        self.assertIn("width=device-width", html)
        self.assertIn("prefers-color-scheme:dark", html)
        self.assertIn("<li value='1'>Album Launch", html)
        self.assertIn("<li value='2'>Other", html)
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
