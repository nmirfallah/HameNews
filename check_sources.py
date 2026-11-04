#!/usr/bin/env python3
"""Smoke-test every data source (and optionally the AI model) before a real run.

  python check_sources.py                    # sources only, costs nothing
  python check_sources.py --subject "bitcoin"
  python check_sources.py --llm              # also make one tiny AI call (a fraction of a cent)
"""
import argparse
import sys
import logging

from trendwatch import sources
from trendwatch.config import load_config


def show(label, fn, *args):
    try:
        out = fn(*args)
    except Exception as e:
        print(f"  FAIL  {label}: {type(e).__name__}: {e}")
        return
    status = "ok  " if out else "EMPTY"
    print(f"  {status} {label}: {len(out)} results")
    for x in out[:2]:
        text = getattr(x, "name", None) or getattr(x, "text", "")
        print(f"          - {text[:90]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--subject", default="climate")
    ap.add_argument("--llm", action="store_true", help="also test the AI provider")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
        stream.reconfigure(encoding="utf-8", errors="replace")

    logging.basicConfig(level=logging.WARNING, format="        warning: %(message)s")
    cfg = load_config(args.config)

    print("Discovery sources (what is trending):")
    for name, fn in sources.SIGNAL_SOURCES.items():
        show(name, fn, cfg)

    topic = {"topic": args.subject, "keywords": [args.subject]}
    print(f"\nContent sources (articles/posts about {args.subject!r}):")
    for name, fn in sources.CONTENT_SOURCES.items():
        show(name, fn, topic, cfg)

    print("\nNews feeds (each configured RSS feed):")
    from urllib.parse import quote_plus
    from trendwatch.http import get_feed
    from trendwatch.sources.news import GOOGLE_NEWS
    for f in cfg["news_feeds"]:
        try:
            feed = get_feed(f["url"])
            n = len(feed.entries) if feed else 0
            print(f"  {'ok   ' if n else 'EMPTY'} {f['name']}: {n} entries  ({f['url']})")
        except Exception as e:
            print(f"  FAIL  {f['name']}: {type(e).__name__}: {e}")

    print(f"\nSite searches via Google News (about {args.subject!r}):")
    for site in cfg.get("news_sites", []):
        try:
            feed = get_feed(GOOGLE_NEWS.format(q=quote_plus(f"{args.subject} site:{site['site']}"), c="US"))
            n = len(feed.entries) if feed else 0
            print(f"  {'ok   ' if n else 'EMPTY'} {site['name']}: {n} results")
        except Exception as e:
            print(f"  FAIL  {site['name']}: {type(e).__name__}: {e}")

    ag = cfg.get("agencies", {})
    if ag.get("enabled"):
        from trendwatch.agencies import site_domains
        from trendwatch.sources.news import google_items, google_url
        domains = site_domains()
        print(f"\nNational news agencies ({len(domains)} domains, searched in chunks of "
              f"{ag.get('site_chunk', 8)}) for {args.subject!r}:")
        seen = {}
        for i in range(0, len(domains), ag.get("site_chunk", 8)):
            chunk = domains[i:i + ag.get("site_chunk", 8)]
            q = f"{args.subject} (" + " OR ".join(f"site:{d}" for d in chunk) + ")"
            try:
                found = google_items(get_feed(google_url(q)), 30)
            except Exception as e:
                print(f"  FAIL  {', '.join(chunk[:3])}...: {type(e).__name__}: {e}")
                continue
            print(f"  {'ok   ' if found else 'EMPTY'} {len(found):>2} results for: {', '.join(chunk)}")
            for it in found:
                seen.setdefault(it.outlet, it.domain)
        print(f"  Outlets that came back: {', '.join(sorted(seen)) or 'none'}")
        print("  Agencies on your list that returned nothing may publish little English content,")
        print("  have a different domain than listed, or not be indexed by Google News.")

    if args.llm:
        print("\nAI provider:")
        from trendwatch.llm import get_llm
        try:
            llm = get_llm(cfg["llm"])
            for tier in ("fast", "smart"):
                reply = llm.complete("Reply with one word.", "Say OK.", tier=tier, max_tokens=20)
                print(f"  ok   {tier} model {cfg['llm']['models'][tier]!r}: {reply.strip()[:40]!r}")
        except Exception as e:
            print(f"  FAIL  {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
