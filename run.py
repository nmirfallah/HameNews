#!/usr/bin/env python3
"""HameNews: what is trending, and what each side says about it.

  python run.py                              # auto-discover today's trending topics
  python run.py --subject "AI regulation"    # analyse one subject you choose
  python run.py --open                       # ...and open the HTML report in your browser
  python run.py --open-latest                # just open the newest report, no analysis
"""
import argparse
import logging
import os
import sys
import webbrowser
from pathlib import Path

from trendwatch.config import load_config
from trendwatch.llm import get_llm
from trendwatch.pipeline import run
from trendwatch.store import Store


def explain(error):
    """A short, actionable message for the errors people hit most often; None for anything else."""
    low, status = str(error).lower(), getattr(error, "status_code", None)
    if "credit balance is too low" in low:
        return ("Your Anthropic API credit balance is too low.\n"
                "Add credit at console.anthropic.com > Plans & Billing (in the same organization as your API key), "
                "wait a minute, and run again.\nA Claude chat subscription does not include API credit.")
    if status == 401 or "invalid x-api-key" in low:
        return ("The API key was rejected. Check that ANTHROPIC_API_KEY holds a valid key "
                "(PowerShell: $env:ANTHROPIC_API_KEY = \"your_key\") and that it was not revoked.")
    if status == 404 and "model" in low:
        return ("The API says that model name does not exist for your account.\n"
                "Edit llm.models in config.yaml (fast and smart) to model names you have access to.")
    if status == 429 or "rate limit" in low:
        return "The API is rate-limiting this key. Wait a minute and run again, or lower collection.max_articles."
    if isinstance(error, RuntimeError) and "environment variable" in low:
        return str(error)
    return None


def open_in_browser(path):
    webbrowser.open(Path(path).resolve().as_uri())
    print(f"Opened {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject", help="analyse this subject instead of auto-discovering topics")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--topics", type=int, help="override discovery.topics_per_day")
    ap.add_argument("--open", action="store_true", help="open the HTML report when finished")
    ap.add_argument("--open-latest", action="store_true", help="open the newest HTML report and exit")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    store = Store(args.data_dir)
    if args.open_latest:
        reports = [f for f in store.list_dir("reports") if f.endswith(".html")]
        if not reports:
            sys.exit("No reports yet. Run: python run.py")
        newest = max(reports, key=lambda f: os.path.getmtime(store.path(f"reports/{f}")))
        return open_in_browser(store.path(f"reports/{newest}"))

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for noisy in ("httpx", "httpcore", "anthropic", "openai"):   # their per-request INFO lines bury real warnings
        logging.getLogger(noisy).setLevel(logging.WARNING)
    cfg = load_config(args.config)
    if args.topics:
        cfg["discovery"]["topics_per_day"] = args.topics
    try:
        name = run(get_llm(cfg["llm"]), cfg, store, subject=args.subject)
    except Exception as e:
        message = explain(e)
        if message is None:
            raise
        sys.exit(f"\nError: {message}")
    if name and args.open:
        open_in_browser(store.path(name.replace(".md", ".html")))


if __name__ == "__main__":
    main()
