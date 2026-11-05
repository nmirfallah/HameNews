import os
import unittest
from types import SimpleNamespace
from unittest import mock

import requests

import helpers
from helpers import cfg
from trendwatch.sources import bluesky, google_trends, hackernews, mastodon, news, wikipedia


def feed(*entries):
    return SimpleNamespace(entries=list(entries))


# ------------------------------------------------------------------ news
class GoogleItemsTests(unittest.TestCase):
    def entry(self, **over):
        e = {"title": "Headline here - BBC News", "link": "http://g/1", "published": "Mon",
             "source": {"title": "BBC News", "href": "https://www.bbc.com/news"}}
        e.update(over)
        return e

    def test_parses_outlet_title_domain_and_link(self):
        (it,) = news.google_items(feed(self.entry()))
        self.assertEqual((it.outlet, it.text, it.domain), ("BBC News", "Headline here", "bbc.com"))
        self.assertEqual((it.id, it.url, it.kind, it.platform), ("http://g/1", "http://g/1", "article", "news"))
        self.assertEqual(it.created_at, "Mon")

    def test_outlet_comes_from_title_suffix_when_source_is_missing(self):
        (it,) = news.google_items(feed(self.entry(source=None)))
        self.assertEqual((it.outlet, it.domain), ("BBC News", ""))

    def test_only_the_last_dash_splits_the_outlet(self):
        (it,) = news.google_items(feed(self.entry(title="A - B - Outlet", source={})))
        self.assertEqual((it.text, it.outlet), ("A - B", "Outlet"))

    def test_entries_without_link_or_title_are_skipped(self):
        out = news.google_items(feed(self.entry(link=""), self.entry(title=""), self.entry(link="http://g/2")))
        self.assertEqual([i.id for i in out], ["http://g/2"])

    def test_limit_forced_outlet_and_group(self):
        entries = [self.entry(link=f"http://g/{i}") for i in range(5)]
        out = news.google_items(feed(*entries), limit=2, outlet="Forced", group="G")
        self.assertEqual(len(out), 2)
        self.assertEqual({(i.outlet, i.group) for i in out}, {("Forced", "G")})

    def test_missing_feed_gives_no_items(self):
        self.assertEqual(news.google_items(None), [])

    def test_html_in_titles_is_stripped(self):
        (it,) = news.google_items(feed(self.entry(title="<b>Bold</b> &amp; plain - Out", source={})))
        self.assertEqual(it.text, "Bold & plain")

    def test_google_url_encodes_query_and_edition(self):
        url = news.google_url("a b & c", "GB")
        self.assertIn("q=a+b+%26+c", url)
        self.assertIn("hl=en-GB&gl=GB&ceid=GB:en", url)


class NewsSignalsTests(unittest.TestCase):
    def test_headlines_become_signals_and_failed_feeds_are_skipped(self):
        feeds = {"http://a": feed({"title": "<b>Hi</b>", "link": "l1"}, {"title": "Second", "link": "l2"}),
                 "http://b": None}
        conf = cfg(news_feeds=[{"name": "BBC", "url": "http://a"}, {"name": "X", "url": "http://b"}],
                   discovery={"headlines_per_feed": 1})
        with mock.patch.object(news, "get_feed", side_effect=lambda u: feeds[u]):
            out = news.signals(conf)
        self.assertEqual([(s.name, s.platform, s.url) for s in out], [("Hi [BBC]", "news", "l1")])


class NewsSearchTests(unittest.TestCase):
    TOPIC = {"topic": "T", "keywords": ["k1", "k2", "k3"]}

    def run_search(self, conf, feeds=None):
        urls = []

        def fake(url):
            urls.append(url)
            return (feeds or {}).get(url, feed())

        with mock.patch.object(news, "get_feed", side_effect=fake), \
                mock.patch.object(news.time, "sleep"):
            items = news.search(self.TOPIC, conf)
        return items, urls

    def base(self, **over):
        c = dict(collection={"google_news_editions": ["US", "GB"], "google_news": True},
                 news_feeds=[], news_sites=[{"name": "S", "site": "s.com"}],
                 agencies={"enabled": True, "search": True, "site_chunk": 4})
        c.update(over)
        return cfg(**c)

    def test_request_counts_editions_sites_and_agency_chunks(self):
        from trendwatch.agencies import site_domains
        chunks = -(-len(site_domains()) // 4)
        _, urls = self.run_search(self.base())
        self.assertEqual(len(urls), 2 * 3 + 1 * 3 + chunks * 2)

    def test_urls_contain_editions_site_filters_and_or_chunks(self):
        _, urls = self.run_search(self.base())
        self.assertTrue(any("ceid=GB:en" in u for u in urls))
        self.assertTrue(any("site%3As.com" in u for u in urls))
        self.assertTrue(any("+OR+site%3A" in u for u in urls))

    def test_agencies_can_be_switched_off_and_google_news_too(self):
        _, urls = self.run_search(self.base(agencies={"enabled": False}))
        self.assertEqual(len(urls), 6 + 3)
        _, urls = self.run_search(self.base(agencies={"enabled": False},
                                            collection={"google_news": False}))
        self.assertEqual(len(urls), 3)

    def test_domains_already_searched_by_name_are_not_repeated_in_chunks(self):
        conf = self.base(news_sites=[{"name": "TASS", "site": "tass.com"}])
        _, urls = self.run_search(conf)
        chunk_urls = [u for u in urls if "+OR+" in u]
        self.assertFalse(any("site%3Atass.com" in u for u in chunk_urls))

    def test_site_search_forces_the_outlet_name_and_group(self):
        conf = self.base(collection={"google_news": False}, agencies={"enabled": False},
                         news_sites=[{"name": "Forced", "site": "s.com", "group": "G"}])
        entry = {"title": "Story - Whatever", "link": "http://x/1", "source": {"title": "Other"}}
        url = news.google_url("T site:s.com")
        items, _ = self.run_search(conf, {url: feed(entry)})
        self.assertEqual({(i.outlet, i.group, i.text) for i in items}, {("Forced", "G", "Story")})

    def test_configured_feeds_are_filtered_by_whole_word_topic_terms(self):
        entries = [
            {"title": "Climate talks resume", "summary": "Delegates said negotiators will meet again soon", "link": "l1"},
            {"title": "Sports", "summary": "football", "link": "l2"},
            {"title": "AI rules", "summary": "he said so", "link": "l3"},
            {"title": "Said nothing", "summary": "", "link": "l4"},
            {"title": "Climate no link", "summary": "", "link": ""},
        ]
        conf = cfg(collection={"google_news": False}, news_sites=[], agencies={"enabled": False},
                   news_feeds=[{"name": "BBC", "url": "http://bbc/rss", "group": "UK media"}])
        self.TOPIC = {"topic": "Climate", "keywords": ["AI"]}
        items, _ = self.run_search(conf, {"http://bbc/rss": feed(*entries)})
        self.assertEqual([i.id for i in items], ["l1", "l3"])
        self.assertEqual({(i.outlet, i.group) for i in items}, {("BBC", "UK media")})
        self.assertEqual(items[0].text, "Climate talks resume. Delegates said negotiators will meet again soon")
        self.assertEqual(items[1].text, "AI rules")  # short summary is not appended


# -------------------------------------------------------------- mastodon
class MastodonTests(unittest.TestCase):
    def fake_get_json(self, routes, calls=None):
        def fake(url, params=None, headers=None):
            if calls is not None:
                calls.append(url)
            for suffix, payload in routes.items():
                if suffix in url:
                    return payload
            return None
        return fake

    def test_signals_from_tags_and_links(self):
        routes = {"/trends/tags": [{"name": "x", "url": "u", "history": [{"uses": "5"}]}, {"name": "y"}],
                  "/trends/links": [{"title": "L", "url": "u3", "history": []}, {"url": "u4"}]}
        with mock.patch.object(mastodon, "get_json", self.fake_get_json(routes)):
            out = mastodon.signals(cfg())
        self.assertEqual([(s.name, s.score) for s in out], [("#x", 5.0), ("#y", 1.0), ("L", 1.0)])
        self.assertEqual({s.platform for s in out}, {"mastodon"})

    def test_signals_tolerate_failed_requests(self):
        with mock.patch.object(mastodon, "get_json", return_value=None):
            self.assertEqual(mastodon.signals(cfg()), [])

    def test_tags_are_alphanumeric_deduplicated_and_capped_at_three(self):
        self.assertEqual(mastodon._tags({"topic": "AI regulation", "keywords": ["AI Act", "EU", "extra"]}),
                         ["AIregulation", "AIAct", "EU"])
        self.assertEqual(mastodon._tags({"topic": "EU", "keywords": ["eu", "!!!"]}), ["EU"])

    def status(self, **over):
        s = {"uri": "u1", "url": "http://m/1", "content": "<p>Hello <b>world</b></p>", "created_at": "t",
             "account": {"acct": "a@x"}, "favourites_count": 1, "reblogs_count": 2, "replies_count": 3}
        s.update(over)
        return s

    def test_search_parses_posts_and_skips_replies_and_empty_posts(self):
        statuses = [self.status(), self.status(uri="u2", in_reply_to_id="5"), self.status(uri="u3", content="<p></p>"),
                    self.status(uri=None, url="http://m/4")]
        calls = []
        routes = {"/timelines/tag/AIregulation": statuses}
        with mock.patch.object(mastodon, "get_json", self.fake_get_json(routes, calls)):
            items = mastodon.search({"topic": "AI regulation", "keywords": []}, cfg(mastodon_instance="fosstodon.org"))
        self.assertEqual([i.id for i in items], ["u1", "http://m/4"])
        self.assertEqual((items[0].text, items[0].outlet, items[0].engagement, items[0].kind),
                         ("Hello world", "a@x", 6, "post"))
        self.assertTrue(all("fosstodon.org" in c for c in calls))

    def test_replies_can_be_kept(self):
        routes = {"/timelines/tag/": [self.status(in_reply_to_id="5")]}
        with mock.patch.object(mastodon, "get_json", self.fake_get_json(routes)):
            items = mastodon.search({"topic": "T", "keywords": []}, cfg(collection={"skip_replies": False}))
        self.assertEqual(len(items), 1)


# ------------------------------------------------------------ hackernews
class HackerNewsTests(unittest.TestCase):
    def test_signals(self):
        payload = {"hits": [{"title": "A", "points": 10, "objectID": "1"}, {"title": "", "objectID": "2"},
                            {"title": "B", "points": None, "objectID": "3"}]}
        with mock.patch.object(hackernews, "get_json", return_value=payload):
            out = hackernews.signals(cfg())
        self.assertEqual([(s.name, s.score) for s in out], [("A", 10.0), ("B", 0.0)])
        self.assertEqual(out[0].url, "https://news.ycombinator.com/item?id=1")

    def test_signals_with_failed_request(self):
        with mock.patch.object(hackernews, "get_json", return_value=None):
            self.assertEqual(hackernews.signals(cfg()), [])

    def test_search_returns_comments_as_posts(self):
        payload = {"hits": [{"comment_text": "<p>Nice &amp; good</p>", "objectID": "9", "author": "bob",
                             "created_at": "t"}, {"comment_text": "", "objectID": "10", "author": "x"}]}
        seen = []

        def fake(url, params=None, headers=None):
            seen.append(params)
            return payload

        with mock.patch.object(hackernews, "get_json", side_effect=fake):
            items = hackernews.search({"topic": "T", "keywords": ["k1", "k2"]}, cfg())
        self.assertEqual(len(seen), 2)  # topic + first keyword
        self.assertEqual({p["tags"] for p in seen}, {"comment"})
        it = items[0]
        self.assertEqual((it.id, it.text, it.outlet, it.kind, it.platform),
                         ("hn:9", "Nice & good", "bob", "post", "hackernews"))
        self.assertEqual(it.url, "https://news.ycombinator.com/item?id=9")


# ------------------------------------------------------------- wikipedia
class WikipediaTests(unittest.TestCase):
    def payload(self, names):
        return {"items": [{"articles": [{"article": n, "views": 100 - i} for i, n in enumerate(names)]}]}

    def test_filters_non_article_pages(self):
        names = ["Main_Page", "Special:Search", "Deaths_in_2026", "-", "Wikipedia:About", "Foo_Bar", "Template:X"]
        with mock.patch.object(wikipedia, "get_json", return_value=self.payload(names)):
            out = wikipedia.signals(cfg())
        self.assertEqual([(s.name, s.score, s.platform) for s in out], [("Foo Bar", 95.0, "wikipedia")])
        self.assertEqual(out[0].url, "https://en.wikipedia.org/wiki/Foo_Bar")

    def test_capped_at_sixty(self):
        with mock.patch.object(wikipedia, "get_json", return_value=self.payload([f"A{i}" for i in range(100)])):
            self.assertEqual(len(wikipedia.signals(cfg())), 60)

    def test_bad_payloads_give_nothing(self):
        for bad in (None, {}, {"items": []}, {"items": [{}]}):
            with mock.patch.object(wikipedia, "get_json", return_value=bad):
                self.assertEqual(wikipedia.signals(cfg()), [], bad)

    def test_requests_a_past_day_from_the_pageviews_api(self):
        with mock.patch.object(wikipedia, "get_json", return_value=None) as g:
            wikipedia.signals(cfg())
        url = g.call_args[0][0]
        self.assertIn("/metrics/pageviews/top/en.wikipedia/all-access/", url)


# --------------------------------------------------------- google trends
class GoogleTrendsTests(unittest.TestCase):
    def test_scores_come_from_approximate_traffic(self):
        entries = [{"title": "A", "ht_approx_traffic": "200+", "link": "l"},
                   {"title": "B", "ht_approx_traffic": "1,000+"}, {"title": "C"},
                   {"title": "", "ht_approx_traffic": "5"}]
        with mock.patch.object(google_trends, "get_feed", return_value=feed(*entries)):
            out = google_trends.signals(cfg())
        self.assertEqual([(s.name, s.score) for s in out], [("A", 200.0), ("B", 1000.0), ("C", 1.0)])
        self.assertEqual({s.platform for s in out}, {"google_trends"})

    def test_country_comes_from_config(self):
        with mock.patch.object(google_trends, "get_feed", return_value=None) as g:
            self.assertEqual(google_trends.signals(cfg(discovery={"google_trends_geo": "GB"})), [])
        self.assertIn("geo=GB", g.call_args[0][0])


# --------------------------------------------------------------- bluesky
class BlueskyTests(unittest.TestCase):
    def setUp(self):
        bluesky._session.clear()
        self.addCleanup(bluesky._session.clear)

    def post(self, **over):
        p = {"uri": "at://did:plc:x/app.bsky.feed.post/abc123", "author": {"handle": "a.bsky.social"},
             "record": {"text": "hi", "createdAt": "t"}, "likeCount": 1, "repostCount": 2,
             "replyCount": 3, "quoteCount": 4}
        p.update(over)
        return p

    def run_search(self, posts, conf=None, topic=None):
        calls = []

        def fake(url, params=None, headers=None):
            calls.append({"url": url, "params": params, "headers": headers})
            return {"posts": posts}

        with mock.patch.object(bluesky, "get_json", side_effect=fake):
            items = bluesky.search(topic or {"topic": "T", "keywords": ["k"]}, conf or cfg())
        return items, calls

    def no_credentials(self):
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("BSKY_HANDLE", None)
        os.environ.pop("BSKY_APP_PASSWORD", None)

    def test_unauthenticated_search_uses_the_public_host(self):
        self.no_credentials()
        items, calls = self.run_search([self.post()])
        self.assertTrue(calls[0]["url"].startswith(bluesky.PUBLIC))
        self.assertEqual(calls[0]["headers"], {})
        self.assertEqual(len(calls), 2)  # topic + one keyword
        it = items[0]
        self.assertEqual((it.url, it.engagement, it.outlet, it.kind, it.platform),
                         ("https://bsky.app/profile/a.bsky.social/post/abc123", 10, "a.bsky.social", "post", "bluesky"))

    def test_replies_are_skipped_unless_configured(self):
        self.no_credentials()
        reply = self.post(record={"text": "r", "reply": {"parent": {}}})
        items, _ = self.run_search([reply], topic={"topic": "T", "keywords": []})
        self.assertEqual(items, [])
        items, _ = self.run_search([reply], cfg(collection={"skip_replies": False}), {"topic": "T", "keywords": []})
        self.assertEqual(len(items), 1)

    def test_login_with_app_password_uses_the_pds_and_caches_the_token(self):
        ok = mock.Mock()
        ok.json.return_value = {"accessJwt": "tok"}
        with mock.patch.dict(os.environ, {"BSKY_HANDLE": "me.bsky.social", "BSKY_APP_PASSWORD": "pw"}), \
                mock.patch.object(bluesky.requests, "post", return_value=ok) as post:
            _, calls = self.run_search([self.post()])
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args[1]["json"], {"identifier": "me.bsky.social", "password": "pw"})
        self.assertTrue(calls[0]["url"].startswith(bluesky.PDS))
        self.assertEqual(calls[0]["headers"], {"Authorization": "Bearer tok"})
        self.assertEqual(calls[1]["headers"], {"Authorization": "Bearer tok"})

    def test_failed_login_falls_back_to_the_public_host(self):
        with mock.patch.dict(os.environ, {"BSKY_HANDLE": "me", "BSKY_APP_PASSWORD": "pw"}), \
                mock.patch.object(bluesky.requests, "post", side_effect=requests.ConnectionError("down")):
            _, calls = self.run_search([self.post()])
        self.assertTrue(calls[0]["url"].startswith(bluesky.PUBLIC))

    def test_refused_search_returns_no_items_without_crashing(self):
        self.no_credentials()
        with mock.patch.object(bluesky, "get_json", return_value=None):
            self.assertEqual(bluesky.search({"topic": "T", "keywords": []}, cfg()), [])

    def test_trending_topics_become_signals(self):
        payload = {"topics": [{"topic": "A"}, {"topic": "B"}, {"topic": ""}]}
        with mock.patch.object(bluesky, "get_json", return_value=payload):
            out = bluesky.signals(cfg())
        self.assertEqual([(s.name, s.score) for s in out], [("A", 3.0), ("B", 2.0)])
        with mock.patch.object(bluesky, "get_json", return_value=None):
            self.assertEqual(bluesky.signals(cfg()), [])


if __name__ == "__main__":
    unittest.main()
