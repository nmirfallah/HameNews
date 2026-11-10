import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import helpers
from helpers import ScriptedLLM, cfg, item
from trendwatch import journal
from trendwatch.models import Item
from trendwatch.store import Store


def feed(*entries, language=None):
    return SimpleNamespace(entries=list(entries), feed={"language": language} if language else {})


def entry(title, link, summary=""):
    return {"title": title, "summary": summary, "link": link, "published": "Mon"}


class ParseSourceTests(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(journal.parse_source("irna.ir"), {"kind": "domain", "domain": "irna.ir"})
        self.assertEqual(journal.parse_source("www.IRNA.ir/en/news")["domain"], "irna.ir")
        self.assertEqual(journal.parse_source("https://www.tasnimnews.ir/fa/rss"),
                         {"kind": "url", "url": "https://www.tasnimnews.ir/fa/rss", "domain": "tasnimnews.ir"})
        self.assertEqual(journal.parse_source("  Tasnim News Agency "), {"kind": "name", "name": "Tasnim News Agency"})

    def test_names_resolve_to_the_right_domain_even_when_an_entry_holds_several_outlets(self):
        c = cfg()
        for name, domain in [("Tasnim News Agency", "tasnimnews.ir"), ("Fars News Agency", "farsnews.ir"),
                             ("IRNA", "irna.ir"), ("Islamic Republic News Agency", "irna.ir"),
                             ("Al Jazeera", "aljazeera.com"), ("Qatar News Agency", "qna.org.qa"),
                             ("TASS", "tass.com"), ("The Grayzone", "thegrayzone.com")]:
            self.assertEqual(journal.domain_for_name(name, c), domain, name)
        self.assertEqual(journal.domain_for_name("No Such Outlet", c), "")


class FindFeedTests(unittest.TestCase):
    def run_find(self, html, feeds):
        page = SimpleNamespace(text=html) if html is not None else None
        tried = []

        def get_feed(url):
            tried.append(url)
            return feeds.get(url)

        with mock.patch.object(journal, "get", return_value=page), mock.patch.object(journal, "get_feed", side_effect=get_feed):
            return journal.find_feed("irna.ir"), tried

    def test_advertised_feeds_are_tried_first_and_relative_links_resolved(self):
        html = ('<head><link rel="stylesheet" href="/a.css">'
                '<link type="application/rss+xml" rel="alternate" title="x" href="/fa/rss?a=1&amp;b=2">'
                '<link rel="alternate" type="application/atom+xml" href="https://irna.ir/atom"></head>')
        good = feed(entry("t", "l"))
        (found, url), tried = self.run_find(html, {"https://irna.ir/fa/rss?a=1&b=2": good})
        self.assertIs(found, good)
        self.assertEqual(url, "https://irna.ir/fa/rss?a=1&b=2")
        self.assertEqual(tried, ["https://irna.ir/fa/rss?a=1&b=2"])

    def test_common_paths_are_tried_when_the_page_advertises_nothing(self):
        good = feed(entry("t", "l"))
        (found, url), tried = self.run_find("<html></html>", {"https://irna.ir/feed": good})
        self.assertEqual(url, "https://irna.ir/feed")
        self.assertEqual(tried, ["https://irna.ir/rss", "https://irna.ir/rss.xml", "https://irna.ir/feed"])

    def test_an_unreachable_homepage_still_tries_the_common_paths(self):
        (found, url), tried = self.run_find(None, {})
        self.assertEqual((found, url), (None, ""))
        self.assertGreaterEqual(len(tried), 4)

    def test_empty_feeds_do_not_count_and_the_number_of_attempts_is_capped(self):
        html = "".join(f'<link rel="alternate" type="application/rss+xml" href="/f{i}">' for i in range(20))
        empty = {f"https://irna.ir/f{i}": feed() for i in range(20)}
        (found, _), tried = self.run_find(html, empty)
        self.assertIsNone(found)
        self.assertEqual(len(tried), 8)


class CollectJournalTests(unittest.TestCase):
    def collect(self, source, *, feeds=None, page=None, conf=None, **kw):
        urls = []

        def get_feed(url):
            urls.append(url)
            return (feeds or {}).get(url)

        with mock.patch.object(journal, "get", return_value=page), mock.patch.object(journal, "get_feed", side_effect=get_feed):
            items, how = journal.collect_journal(source, conf or cfg(), **kw)
        return items, how, urls

    def test_a_configured_feed_is_found_by_name_or_domain(self):
        conf = cfg(news_feeds=[{"name": "BBC News", "url": "http://feeds.bbci.co.uk/news/rss.xml"}])
        feeds = {"http://feeds.bbci.co.uk/news/rss.xml": feed(entry("Headline", "http://b/1"), language="en-gb")}
        for source in ("BBC News", "bbci.co.uk"):
            items, how, _ = self.collect(source, feeds=feeds, conf=conf)
            self.assertIn("configured feed 'BBC News'", how, source)
            self.assertEqual((items[0].outlet, items[0].lang, items[0].text), ("BBC News", "en-gb", "Headline"))

    def test_a_feed_url_is_used_directly(self):
        feeds = {"https://x.com/rss": feed(entry("A", "http://x/1"), entry("B", "http://x/2"))}
        items, how, urls = self.collect("https://x.com/rss", feeds=feeds)
        self.assertEqual((len(items), how), (2, "the feed at https://x.com/rss"))
        self.assertEqual((items[0].outlet, items[0].domain), ("x.com", "x.com"))

    def test_a_domain_uses_a_discovered_feed_and_reads_its_declared_language(self):
        page = SimpleNamespace(text='<link rel="alternate" type="application/rss+xml" href="/fa/rss">')
        feeds = {"https://irna.ir/fa/rss": feed(entry("خبر یک", "http://i/1"), language="fa")}
        items, how, _ = self.collect("irna.ir", feeds=feeds, page=page)
        self.assertEqual(how, "a feed found at https://irna.ir/fa/rss")
        self.assertEqual((items[0].lang, items[0].outlet, items[0].domain), ("fa", "IRNA", "irna.ir"))

    def test_an_explicit_language_overrides_nothing_but_fills_gaps(self):
        feeds = {"https://irna.ir/rss": feed(entry("خبر", "http://i/1"))}
        items, _, _ = self.collect("irna.ir", feeds=feeds, page=None, lang="fa-IR")
        self.assertEqual(items[0].lang, "fa")

    def test_google_news_is_the_fallback_with_subject_and_language(self):
        url = journal.google_url("Iran site:irna.ir", "US", "fa")
        feeds = {url: feed({"title": "خبر - ایرنا", "link": "http://g/1", "source": {"title": "ایرنا"}})}
        items, how, urls = self.collect("irna.ir", feeds=feeds, subject="Iran", lang="fa")
        self.assertIn(url, urls)
        self.assertEqual(how, "a Google News search restricted to irna.ir in Persian")
        self.assertEqual((items[0].lang, items[0].outlet, items[0].text, items[0].domain), ("fa", "IRNA", "خبر", "irna.ir"))

    def test_google_fallback_without_language_searches_english(self):
        url = journal.google_url("site:irna.ir", "US", "en")
        feeds = {url: feed({"title": "Story - IRNA", "link": "http://g/1", "source": {}})}
        items, how, _ = self.collect("irna.ir", feeds=feeds)
        self.assertEqual(how, "a Google News search restricted to irna.ir")
        self.assertEqual(len(items), 1)

    def test_names_are_resolved_through_the_agency_list(self):
        feeds = {"https://tasnimnews.ir/rss": feed(entry("خبر", "http://t/1"))}
        items, how, _ = self.collect("Tasnim News Agency", feeds=feeds)
        self.assertIn("tasnimnews.ir", how)

    def test_nothing_found_says_so(self):
        items, how, _ = self.collect("irna.ir")
        self.assertEqual(items, [])
        self.assertIn("nothing", how)
        items, how, _ = self.collect("Unknown Outlet Name")
        self.assertEqual(items, [])

    def test_limit_and_incomplete_entries(self):
        entries = [entry(f"T{i}", f"http://x/{i}") for i in range(20)] + [entry("No link", "")]
        feeds = {"https://x.com/rss": feed(*entries)}
        items, _, _ = self.collect("https://x.com/rss", feeds=feeds, limit=3)
        self.assertEqual([i.text for i in items], ["T0", "T1", "T2"])
        items, _, _ = self.collect("https://x.com/rss", feeds={"https://x.com/rss": feed(entry("", "l"), entry("ok", "l2"))})
        self.assertEqual([i.text for i in items], ["ok"])

    def test_a_long_summary_is_appended_a_short_one_is_not(self):
        feeds = {"https://x.com/rss": feed(entry("Title", "l1", "A much longer summary sentence here"),
                                           entry("Title two", "l2", "short"))}
        items, _, _ = self.collect("https://x.com/rss", feeds=feeds)
        self.assertEqual([i.text for i in items], ["Title. A much longer summary sentence here", "Title two"])


class DisplayNameTests(unittest.TestCase):
    def test_agency_domains_get_readable_names(self):
        self.assertEqual(journal.display_name("irna.ir"), "IRNA")
        self.assertEqual(journal.display_name("tasnimnews.ir"), "Tasnim News Agency")
        self.assertEqual(journal.display_name("farsnews.ir"), "Fars News Agency")
        self.assertEqual(journal.display_name("aljazeera.com"), "Al Jazeera")
        self.assertEqual(journal.display_name("tass.com"), "TASS")

    def test_unknown_domains_keep_the_domain_or_the_fallback(self):
        self.assertEqual(journal.display_name("example.org"), "example.org")
        self.assertEqual(journal.display_name("example.org", "Example"), "Example")

    def test_the_names_it_picks_are_ones_the_group_matcher_knows(self):
        from trendwatch.groups import assign_groups
        for domain, group in [("irna.ir", "Iran state-linked media"), ("tasnimnews.ir", "Iran state-linked media"),
                              ("tass.com", "Russia state-linked media"), ("aljazeera.com", "Qatar state-linked media")]:
            it = Item(domain, "article", "news", journal.display_name(domain), "x")
            with tempfile.TemporaryDirectory() as d:
                assign_groups(ScriptedLLM([]), [it], Store(d), cfg())
            self.assertEqual(it.group, group, domain)


class FocusTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = Store(self._tmp.name)

    def items(self):
        return [Item("u1", "article", "news", "IRNA", "مذاکرات ایران و آمریکا", url="http://i/1", lang="fa", domain="irna.ir"),
                Item("u2", "article", "news", "IRNA", "قیمت نفت بالا رفت", url="http://i/2", lang="fa", domain="irna.ir"),
                Item("u3", "article", "news", "IRNA", "Football final tonight", url="http://i/3", lang="en", domain="irna.ir")]

    def focus(self):
        reply = [{"i": 0, "lang": "fa", "english": "Iran and America talks"}, {"i": 1, "lang": "fa", "english": "Oil price rose"}]
        llm = ScriptedLLM([reply])
        with mock.patch.object(journal, "collect_journal", return_value=(self.items(), "a feed found at x")):
            return journal.prepare_focus(llm, cfg(), self.store, "irna.ir"), llm

    def test_prepare_focus_translates_the_sources_items(self):
        focus, llm = self.focus()
        self.assertEqual((focus["source"], focus["name"], focus["found_via"]), ("irna.ir", "IRNA", "a feed found at x"))
        self.assertEqual([i.en for i in focus["items"]], ["Iran and America talks", "Oil price rose", "Football final tonight"])
        self.assertEqual(len(focus["rows"]), 3)
        self.assertEqual(llm.tasks(), ["translate_items"])

    def test_prepare_focus_with_nothing_found(self):
        with mock.patch.object(journal, "collect_journal", return_value=([], "nothing")):
            focus = journal.prepare_focus(ScriptedLLM([]), cfg(), self.store, "nope.example")
        self.assertEqual((focus["items"], focus["rows"], focus["name"]), ([], [], "nope.example"))

    def test_the_sources_headlines_become_english_news_signals(self):
        focus, _ = self.focus()
        sigs = journal.focus_signals(focus)
        self.assertEqual([(s.name, s.platform, s.source, s.url) for s in sigs[:1]],
                         [("Iran and America talks [IRNA]", "news", "IRNA", "http://i/1")])
        self.assertEqual(len(sigs), 3)

    def test_items_belong_to_a_topic_by_cluster_membership_or_keyword(self):
        focus, _ = self.focus()
        by_cluster = journal.focus_items_for_topic(focus, {"topic": "Zzz", "keywords": [], "focus_urls": ["http://i/2"]})
        self.assertEqual([i.url for i in by_cluster], ["http://i/2"])
        by_keyword = journal.focus_items_for_topic(focus, {"topic": "Iran talks", "keywords": ["Iran"], "focus_urls": []})
        self.assertEqual([i.url for i in by_keyword], ["http://i/1"])
        both = journal.focus_items_for_topic(focus, {"topic": "Iran", "keywords": ["oil"], "focus_urls": ["http://i/3"]})
        self.assertEqual(sorted(i.url for i in both), ["http://i/1", "http://i/2", "http://i/3"])
        self.assertEqual(journal.focus_items_for_topic(focus, {"topic": "Nothing", "keywords": []}), [])

    def test_keyword_matching_uses_whole_words_on_the_english_text(self):
        focus, _ = self.focus()
        self.assertEqual(journal.focus_items_for_topic(focus, {"topic": "AI", "keywords": ["Ir"]}), [])

    def test_row_for_carries_original_english_language_and_flags(self):
        focus, _ = self.focus()
        row = journal.row_for(focus["items"][0])
        self.assertEqual((row["original"], row["english"], row["lang_name"], row["url"]),
                         ("مذاکرات ایران و آمریکا", "Iran and America talks", "Persian", "http://i/1"))
        self.assertEqual(row["flags"], [])
        bad = Item("x", "article", "news", "IRNA", "متن", lang="fa")
        self.assertEqual(journal.row_for(bad)["flags"], ["no translation returned"])

    def test_focus_info_summarises_the_source_and_its_coverage(self):
        focus, _ = self.focus()
        results = [{"focus": {"items": [{}]}}, {"focus": {"items": []}}, {}]
        info = journal.focus_info(focus, results)
        self.assertEqual((info["name"], info["n_items"], info["topics_covered"], info["topics_total"]),
                         ("IRNA", 3, 1, 3))
        self.assertEqual(info["languages"], {"Persian": 2, "English": 1})
        self.assertEqual(info["flagged"], 0)


class CheckRowTests(unittest.TestCase):
    def row(self, **kw):
        base = {"original": "یک خبر مهم درباره مذاکرات امروز", "english": "An important news item about today's talks",
                "lang": "fa", "meta_lang": "fa"}
        base.update(kw)
        return base

    def test_a_clean_translation_has_no_flags(self):
        self.assertEqual(journal.check_row(self.row()), [])

    def test_english_rows_only_get_the_language_disagreement_check(self):
        self.assertEqual(journal.check_row(self.row(lang="en", english="", meta_lang="en")), [])
        self.assertEqual(journal.check_row(self.row(lang="en", english="", meta_lang="")), [])
        self.assertEqual(journal.check_row(self.row(lang="en", english="", meta_lang="de")),
                         ["the source said German but the model says English"])

    def test_missing_translation(self):
        self.assertEqual(journal.check_row(self.row(english="")), ["no translation returned"])
        self.assertEqual(journal.check_row(self.row(english="", meta_lang="ar")),
                         ["the source said Arabic but the model says Persian", "no translation returned"])

    def test_identical_to_the_original(self):
        flags = journal.check_row(self.row(original="Hamas", english="hamas "))
        self.assertIn("translation identical to the original", flags)

    def test_leftover_non_latin_script(self):
        flags = journal.check_row(self.row(english="Talks today خبر مهم درباره"))
        self.assertIn("English text still contains non-Latin script", flags)

    def test_suspicious_length(self):
        self.assertIn("translation length looks off", journal.check_row(self.row(english="Talks")))
        long = " ".join(["word"] * 60)
        self.assertIn("translation length looks off", journal.check_row(self.row(english=long)))
        # very short originals (or scripts without spaces) are not judged by length
        self.assertEqual(journal.check_row(self.row(original="خبر", english="News")), [])

    def test_language_disagreement_with_the_source_metadata(self):
        flags = journal.check_row(self.row(lang="ar", meta_lang="fa"))
        self.assertIn("the source said Persian but the model says Arabic", flags)
        self.assertEqual(journal.check_row(self.row(meta_lang="")), [])


class VerifyTests(unittest.TestCase):
    def rows(self):
        return [{"original": "a", "english": "A", "lang": "fa", "verdict": "", "note": ""},
                {"original": "b", "english": "", "lang": "fa", "verdict": "", "note": ""},
                {"original": "c<script>", "english": "C>", "lang": "ar", "verdict": "", "note": ""}]

    def test_verdicts_are_applied_to_translated_rows_only(self):
        rows = self.rows()
        llm = ScriptedLLM([[{"i": 0, "verdict": "Good"}, {"i": 1, "verdict": "wrong", "note": "x" * 300},
                            {"i": 5, "verdict": "good"}, {"i": 1, "verdict": "bogus"}, "junk", {"verdict": "good"}]])
        journal.verify(llm, rows)
        self.assertEqual(rows[0]["verdict"], "good")
        self.assertEqual(rows[1]["verdict"], "")           # the empty translation was never sent
        self.assertEqual(rows[2]["verdict"], "wrong")       # chunk index 1 is the third row
        self.assertLessEqual(len(rows[2]["note"]), 160)
        self.assertEqual(llm.calls[0]["tier"], "smart")

    def test_text_cannot_inject_markup_and_failures_are_tolerated(self):
        rows = self.rows()
        llm = ScriptedLLM([RuntimeError("down")])
        journal.verify(llm, rows)
        self.assertNotIn("<script>", llm.calls[0]["prompt"])
        self.assertEqual({r["verdict"] for r in rows}, {""})


class RunJournalTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = Store(self._tmp.name)

    def items(self):
        return [Item("p1", "article", "news", "irna.ir", "ایران و آمریکا گفتگو کردند", url="http://i/1", lang="fa"),
                Item("p2", "article", "news", "irna.ir", "Москва заявила о новых санкциях", url="http://i/2"),
                Item("e1", "article", "news", "irna.ir", "Talks resume today", url="http://i/3"),
                Item("m1", "article", "news", "irna.ir", "Hello there friends", url="http://i/4", lang="de")]

    def run_it(self, reply, items=None, **kw):
        llm = ScriptedLLM([reply] if reply is not None else [])
        with mock.patch.object(journal, "collect_journal", return_value=(items or self.items(), "a test feed")):
            return journal.run_journal(llm, cfg(), self.store, "irna.ir", **kw), llm

    REPLY = [{"i": 0, "lang": "fa", "english": "Iran and America held talks"},
             {"i": 1, "lang": "ru", "english": "Moscow announced new sanctions"},
             {"i": 2, "lang": "en", "english": "Hello there friends"}]

    def test_rows_show_original_english_language_and_how_the_language_was_found(self):
        result, _ = self.run_it(self.REPLY)
        rows = {r["n"]: r for r in result["rows"]}
        self.assertEqual((rows[1]["lang"], rows[1]["lang_how"], rows[1]["english"]),
                         ("fa", "source metadata", "Iran and America held talks"))
        self.assertEqual((rows[2]["lang"], rows[2]["lang_how"]), ("ru", "script/word guess"))
        self.assertEqual((rows[3]["lang"], rows[3]["lang_how"], rows[3]["english"]), ("en", "assumed English", ""))
        self.assertEqual((rows[4]["lang"], rows[4]["lang_how"]), ("en", "corrected by the model"))
        self.assertEqual(rows[4]["meta_lang"], "de")
        self.assertIn("the source said German but the model says English", rows[4]["flags"])

    def test_the_summary_counts_languages_translations_and_flags(self):
        result, _ = self.run_it(self.REPLY)
        s = result["summary"]
        self.assertEqual((s["items"], s["translated"], s["english"], s["flagged"]), (4, 2, 2, 1))
        self.assertEqual(s["languages"], {"Persian": 1, "Russian": 1, "English": 2})

    def test_three_files_are_written_and_the_html_is_safe_for_right_to_left_text(self):
        evil = [Item("x", "article", "news", "s", "<img src=x onerror=alert(1)> خبر", url="javascript:alert(1)", lang="fa")]
        result, _ = self.run_it([{"i": 0, "lang": "fa", "english": "<script>alert(1)</script>"}], evil)
        base = result["path"][:-5]
        for ext in (".html", ".md", ".json"):
            self.assertTrue(os.path.exists(self.store.path(base + ext)), ext)
        html = open(self.store.path(result["path"]), encoding="utf-8").read()
        self.assertIn("dir='auto'", html)
        self.assertIn("lang='fa'", html)
        self.assertNotIn("<img", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("javascript:", html)
        self.assertEqual(self.store.read(base + ".json")["summary"]["items"], 1)

    def test_translations_are_cached_unless_no_cache_is_requested(self):
        self.run_it(self.REPLY)
        self.assertIsNotNone(self.store.read("translations.json"))
        other = Store(tempfile.mkdtemp())
        self.store = other
        self.run_it(self.REPLY, use_cache=False)
        self.assertIsNone(other.read("translations.json"))

    def test_a_cached_translation_is_not_requested_again_but_no_cache_asks_again(self):
        self.run_it(self.REPLY)
        cached_run, fresh_run = ScriptedLLM([]), ScriptedLLM([self.REPLY])
        with mock.patch.object(journal, "collect_journal", side_effect=lambda *a, **k: (self.items(), "x")):
            journal.run_journal(cached_run, cfg(), self.store, "irna.ir")
            journal.run_journal(fresh_run, cfg(), self.store, "irna.ir", use_cache=False)
        self.assertEqual(cached_run.calls, [])        # everything came from the saved translations
        self.assertEqual(len(fresh_run.calls), 1)     # --no-cache translated again

    def test_a_test_run_translates_even_if_translation_is_off_in_the_config(self):
        llm = ScriptedLLM([self.REPLY])
        conf = cfg(languages={"translate": False})
        with mock.patch.object(journal, "collect_journal", return_value=(self.items(), "x")):
            result = journal.run_journal(llm, conf, self.store, "irna.ir")
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(result["rows"][0]["english"], "Iran and America held talks")

    def test_verify_adds_model_verdicts_to_the_report(self):
        reply = [{"i": 0, "verdict": "good"}, {"i": 1, "verdict": "minor", "note": "lost nuance"}]
        llm = ScriptedLLM([self.REPLY, reply])
        with mock.patch.object(journal, "collect_journal", return_value=(self.items(), "x")):
            result = journal.run_journal(llm, cfg(), self.store, "irna.ir", do_verify=True)
        self.assertEqual([r["verdict"] for r in result["rows"][:2]], ["good", "minor"])
        self.assertEqual(result["summary"]["verdicts"], {"good": 1, "minor": 1})
        self.assertEqual(llm.tasks(), ["translate_items", "verify_translations"])
        text = journal.render_text(result)
        self.assertIn("model review: minor - lost nuance", text)

    def test_nothing_found_returns_an_explanation_and_writes_nothing(self):
        with mock.patch.object(journal, "collect_journal", return_value=([], "nothing")):
            result = journal.run_journal(ScriptedLLM([]), cfg(), self.store, "nope.example")
        self.assertEqual(result["rows"], [])
        text = journal.render_text(result)
        self.assertIn("Nothing to translate", text)
        self.assertIn("--lang", text)
        self.assertEqual(self.store.list_dir("journal"), [])

    def test_the_console_text_shows_original_english_checks_and_the_saved_path(self):
        result, _ = self.run_it(self.REPLY)
        text = journal.render_text(result)
        self.assertIn("Source: irna.ir", text)
        self.assertIn("Found via: a test feed", text)
        self.assertIn("4 items (Persian 1, Russian 1, English 2); 2 translated, 1 flagged", text)
        self.assertIn("1. [Persian, source metadata]", text)
        self.assertIn("original: ایران و آمریکا گفتگو کردند", text)
        self.assertIn("English:  Iran and America held talks", text)
        self.assertIn("CHECK: the source said German but the model says English", text)
        self.assertIn("Saved: journal/", text)

    def test_markdown_report(self):
        result, _ = self.run_it(self.REPLY)
        md = journal.render_md(result)
        self.assertIn("# Translation check: irna.ir", md)
        self.assertIn("- English: Iran and America held talks", md)
        self.assertIn("(same as original)", md)

    def test_a_failed_translation_request_leaves_rows_flagged_not_crashed(self):
        result, _ = self.run_it(RuntimeError("down"))
        untranslated = [r for r in result["rows"] if r["lang"] != "en"]
        self.assertTrue(untranslated)
        self.assertTrue(all("no translation returned" in r["flags"] for r in untranslated))
        self.assertEqual(result["summary"]["translated"], 0)


if __name__ == "__main__":
    unittest.main()
