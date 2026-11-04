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
