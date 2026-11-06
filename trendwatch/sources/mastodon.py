"""Mastodon public trends and hashtag timelines (no key needed on most servers)."""
import re

from ..http import get_json
from ..models import Item, Signal
from ..util import log, strip_html


def _today_uses(entry):
    try:
        return float(entry["history"][0]["uses"])
    except (KeyError, IndexError, ValueError, TypeError):
        return 1.0


def signals(cfg):
    inst = cfg["mastodon_instance"]
    out = []
    for e in get_json(f"https://{inst}/api/v1/trends/tags") or []:
        out.append(Signal(name="#" + e.get("name", ""), platform="mastodon",
                          score=_today_uses(e), url=e.get("url", "")))
    for e in get_json(f"https://{inst}/api/v1/trends/links") or []:
        if e.get("title"):
            out.append(Signal(name=e["title"], platform="mastodon",
                              score=_today_uses(e), url=e.get("url", "")))
    return out


def _tags(topic):
    cands = [topic["topic"]] + list(topic.get("keywords", []))[:3]
    tags = []
    for c in cands:
        t = re.sub(r"[^A-Za-z0-9]", "", c)
        if t and t.lower() not in [x.lower() for x in tags]:
            tags.append(t)
    return tags[:3]


def search(topic, cfg):
    inst = cfg["mastodon_instance"]
    skip_replies = cfg["collection"].get("skip_replies", True)
    items = []
    for tag in _tags(topic):
        data = get_json(f"https://{inst}/api/v1/timelines/tag/{tag}", params={"limit": 40})
        for s in data or []:
            if skip_replies and s.get("in_reply_to_id"):
                continue
            text = strip_html(s.get("content", ""))
            if not text:
                continue
            acct = (s.get("account") or {}).get("acct", "unknown")
            eng = sum(s.get(k, 0) or 0 for k in ("favourites_count", "reblogs_count", "replies_count"))
            items.append(Item(id=s.get("uri") or s.get("url", ""), kind="post", platform="mastodon",
                              outlet=acct, text=text, url=s.get("url", ""),
                              created_at=s.get("created_at", ""), engagement=eng,
                              lang=s.get("language") or ""))
    log.info("mastodon: %d posts for %r", len(items), topic["topic"])
    return items
