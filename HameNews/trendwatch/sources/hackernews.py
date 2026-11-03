"""Hacker News via the free Algolia API. Tech-skewed audience; comments carry the opinions."""
from ..http import get_json
from ..models import Item, Signal
from ..util import log, strip_html

API = "https://hn.algolia.com/api/v1"


def signals(cfg):
    data = get_json(f"{API}/search", params={"tags": "front_page", "hitsPerPage": 30})
    return [Signal(name=h["title"], platform="hackernews", score=float(h.get("points") or 0),
                   url=f"https://news.ycombinator.com/item?id={h.get('objectID')}")
            for h in (data or {}).get("hits", []) if h.get("title")]


def search(topic, cfg):
    items = []
    for q in [topic["topic"]] + list(topic.get("keywords", []))[:1]:
        data = get_json(f"{API}/search_by_date",
                        params={"query": q, "tags": "comment", "hitsPerPage": 30})
        for h in (data or {}).get("hits", []):
            text = strip_html(h.get("comment_text", ""))
            if not text:
                continue
            items.append(Item(id=f"hn:{h.get('objectID')}", kind="post", platform="hackernews",
                              outlet=h.get("author", "unknown"), text=text,
                              url=f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                              created_at=h.get("created_at", "")))
    log.info("hackernews: %d comments for %r", len(items), topic["topic"])
    return items
