"""News via RSS: configured feeds, Google News search (several national editions), and
site-restricted Google News searches for outlets and national news agencies."""
import time
from urllib.parse import quote_plus, urlparse

from ..http import get_feed
from ..models import Item, Signal
from ..util import log, strip_html, term_in

GOOGLE_NEWS = "https://news.google.com/rss/search?q={q}&hl=en-{c}&gl={c}&ceid={c}:en"


def google_url(query, edition="US"):
    return GOOGLE_NEWS.format(q=quote_plus(query), c=edition)


def signals(cfg):
    """Headlines from the configured feeds, used as trend signals."""
    out = []
    per_feed = cfg["discovery"]["headlines_per_feed"]
    for f in cfg["news_feeds"]:
        feed = get_feed(f["url"])
        if not feed:
            continue
        for e in feed.entries[:per_feed]:
            title = strip_html(e.get("title", ""))
            if title:
                out.append(Signal(name=f"{title} [{f['name']}]", platform="news",
                                  score=1.0, url=e.get("link", "")))
    return out


def google_items(feed, limit=30, outlet=None, group=""):
    """Turn a Google News RSS feed into Items. Google puts the outlet in <source>."""
    items = []
    for e in (feed.entries[:limit] if feed else []):
        title = strip_html(e.get("title", ""))
        src = e.get("source") or {}
        name = outlet or src.get("title") or ""
        if " - " in title:
            head, tail = title.rsplit(" - ", 1)
            title, name = head, name or tail
        domain = urlparse(src.get("href", "")).netloc.lower().removeprefix("www.")
        if title and e.get("link"):
            items.append(Item(id=e["link"], kind="article", platform="news",
                              outlet=name or "unknown", text=title, url=e["link"],
                              created_at=e.get("published", ""), group=group, domain=domain))
    return items


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def search(topic, cfg):
    items = []
    keywords = list(topic.get("keywords", []))
    queries = [topic["topic"]] + keywords[:2]
    terms = [topic["topic"]] + keywords

    # 1) Google News from several national editions
    if cfg["collection"].get("google_news", True):
        for edition in cfg["collection"].get("google_news_editions", ["US"]):
            for q in queries:
                items += google_items(get_feed(google_url(q, edition)))
                time.sleep(0.2)

    # 2) Named outlets searched with a site: filter
    named = cfg.get("news_sites", [])
    for site in named:
        for q in queries:
            items += google_items(get_feed(google_url(f"{q} site:{site['site']}")), 20,
                                  outlet=site["name"], group=site.get("group", ""))
            time.sleep(0.2)

    # 3) National news agencies, several domains per query
    ag = cfg.get("agencies", {})
    if ag.get("enabled") and ag.get("search"):
        from ..agencies import site_domains
        skip = {s["site"] for s in named}
        domains = [d for d in site_domains() if d not in skip]
        for chunk in _chunks(domains, ag.get("site_chunk", 8)):
            sites = " OR ".join(f"site:{d}" for d in chunk)
            for q in queries[:2]:
                items += google_items(get_feed(google_url(f"{q} ({sites})")), 30)
                time.sleep(0.2)

    # 4) Your configured RSS feeds, filtered to the topic
    for f in cfg["news_feeds"]:
        feed = get_feed(f["url"])
        if not feed:
            continue
        for e in feed.entries:
            title = strip_html(e.get("title", ""))
            summary = strip_html(e.get("summary", ""))
            blob = f"{title} {summary}"
            if any(term_in(t, blob) for t in terms) and e.get("link"):
                text = title if len(summary) < len(title) + 10 else f"{title}. {summary}"
                items.append(Item(id=e["link"], kind="article", platform="news",
                                  outlet=f["name"], text=text, url=e["link"],
                                  created_at=e.get("published", ""), group=f.get("group", "")))
    log.info("news: %d articles for %r", len(items), topic["topic"])
    return items
