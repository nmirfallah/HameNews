"""News via RSS: configured feeds plus Google News search (many outlets, several national editions)."""
from urllib.parse import quote_plus

from ..http import get_feed
from ..models import Item, Signal
from ..util import log, strip_html, term_in

GOOGLE_NEWS = "https://news.google.com/rss/search?q={q}&hl=en-{c}&gl={c}&ceid={c}:en"


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


def search(topic, cfg):
    items = []
    keywords = list(topic.get("keywords", []))
    terms = [topic["topic"]] + keywords

    if cfg["collection"].get("google_news", True):
        for edition in cfg["collection"].get("google_news_editions", ["US"]):
            for q in [topic["topic"]] + keywords[:2]:
                feed = get_feed(GOOGLE_NEWS.format(q=quote_plus(q), c=edition))
                if not feed:
                    continue
                for e in feed.entries[:30]:
                    title = strip_html(e.get("title", ""))
                    outlet = (e.get("source") or {}).get("title") or ""
                    if " - " in title:
                        head, tail = title.rsplit(" - ", 1)
                        title, outlet = head, outlet or tail
                    if title and e.get("link"):
                        items.append(Item(id=e["link"], kind="article", platform="news",
                                          outlet=outlet or "unknown", text=title,
                                          url=e["link"], created_at=e.get("published", "")))

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
                                  created_at=e.get("published", ""),
                                  group=f.get("group", "")))
    log.info("news: %d articles for %r", len(items), topic["topic"])
    return items
