"""Google's public 'trending now' RSS feed. Unofficial; if it stops working it just returns nothing."""
import re

from ..http import get_feed
from ..models import Signal


def signals(cfg):
    geo = cfg["discovery"].get("google_trends_geo", "US")
    feed = get_feed(f"https://trends.google.com/trending/rss?geo={geo}")
    out = []
    for e in (feed.entries if feed else []):
        digits = re.sub(r"\D", "", str(e.get("ht_approx_traffic", "")))
        out.append(Signal(name=e.get("title", ""), platform="google_trends",
                          score=float(digits or 1), url=e.get("link", "")))
    return [s for s in out if s.name]
