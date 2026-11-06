"""Bluesky. Public endpoints may refuse unauthenticated search; if so, set BSKY_HANDLE and
BSKY_APP_PASSWORD (a free app password from Bluesky settings) and it will log in."""
import os

import requests

from ..http import get_json
from ..models import Item, Signal
from ..util import log

PUBLIC = "https://public.api.bsky.app"
PDS = "https://bsky.social"
_session = {}


def _base_and_headers():
    handle, pw = os.environ.get("BSKY_HANDLE"), os.environ.get("BSKY_APP_PASSWORD")
    if handle and pw:
        if "token" not in _session:
            try:
                r = requests.post(f"{PDS}/xrpc/com.atproto.server.createSession",
                                  json={"identifier": handle, "password": pw}, timeout=20)
                r.raise_for_status()
                _session["token"] = r.json()["accessJwt"]
            except (requests.RequestException, KeyError, ValueError) as e:
                log.warning("Bluesky login failed: %s", e)
                _session["token"] = None
        if _session["token"]:
            return PDS, {"Authorization": f"Bearer {_session['token']}"}
    return PUBLIC, {}


def signals(cfg):
    data = get_json(f"{PUBLIC}/xrpc/app.bsky.unspecced.getTrendingTopics", params={"limit": 25})
    topics = (data or {}).get("topics", [])
    return [Signal(name=t.get("topic", ""), platform="bluesky", score=float(len(topics) - i))
            for i, t in enumerate(topics) if t.get("topic")]


def search(topic, cfg):
    base, headers = _base_and_headers()
    skip_replies = cfg["collection"].get("skip_replies", True)
    items = []
    for q in [topic["topic"]] + list(topic.get("keywords", []))[:2]:
        data = get_json(f"{base}/xrpc/app.bsky.feed.searchPosts",
                        params={"q": q, "limit": 50, "sort": "latest"}, headers=headers)
        if data is None:
            log.warning("bluesky search unavailable (if unauthenticated, set BSKY_HANDLE/BSKY_APP_PASSWORD)")
            continue
        for p in data.get("posts", []):
            rec = p.get("record", {})
            if skip_replies and rec.get("reply"):
                continue
            handle = p.get("author", {}).get("handle", "unknown")
            rkey = p["uri"].rsplit("/", 1)[-1]
            eng = sum(p.get(k, 0) or 0 for k in ("likeCount", "repostCount", "replyCount", "quoteCount"))
            items.append(Item(id=p["uri"], kind="post", platform="bluesky", outlet=handle,
                              text=rec.get("text", ""),
                              url=f"https://bsky.app/profile/{handle}/post/{rkey}",
                              created_at=rec.get("createdAt", ""), engagement=eng,
                              lang=(rec.get("langs") or [""])[0]))
    log.info("bluesky: %d posts for %r", len(items), topic["topic"])
    return items
