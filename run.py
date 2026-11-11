#!/usr/bin/env python3
"""HameNews: what is trending, and what each side says about it.

  python run.py                              # auto-discover today's trending topics
  python run.py --subject "AI regulation"    # analyse one subject you choose
  python run.py --open                       # ...and open the HTML report in your browser
  python run.py --open-latest                # just open the newest report, no analysis
  python run.py --why "Iran"                 # why is (or is not) this story in the latest report?
  python run.py --email                      # ...and email the report to the people in emails.yaml
  python run.py -j irna.ir --open            # normal analysis, plus what this source reported on every topic
  python run.py -j irna.ir --only --open     # analyse ONLY this source (what is it covering, how does it frame it)
  python run.py -j irna.ir --translation-only   # just test language detection + translation on that source
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
    ap.add_argument("--email", action="store_true",
                    help="email the finished report to the recipients in emails.yaml (needs SMTP_USERNAME/SMTP_PASSWORD)")
    ap.add_argument("--open-latest", action="store_true", help="open the newest HTML report and exit")
    ap.add_argument("-j", "--journal", metavar="SOURCE",
                    help="focus on one source: a domain (irna.ir), an outlet name, or a feed URL. Its articles are "
                         "translated and added to the analysis of every topic")
    ap.add_argument("--only", action="store_true",
                    help="with -j: analyse only that source (its own headlines decide the topics)")
    ap.add_argument("--translation-only", action="store_true",
                    help="with -j: do not analyse news, just show the source's items next to their translations")
    ap.add_argument("-n", "--limit", type=int, default=None,
                    help="with -j: how many of the source's items to fetch (default 40; 10 with --translation-only)")
    ap.add_argument("--lang", metavar="CODE", help="with -j: ask Google News for pages in this language (e.g. fa, ar, ru)")
    ap.add_argument("--no-cache", action="store_true", help="with -j: ignore saved translations and translate again")
    ap.add_argument("--verify", action="store_true",
                    help="with -j: also have a stronger model grade each translation (a few extra requests)")
    ap.add_argument("--why", metavar="TERM", help="explain what happened to a story in the latest discovery log")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    store = Store(args.data_dir)
    if args.why:
        from trendwatch.explain import explain as explain_story   # not `explain`: that name is the error helper
        return print(explain_story(store, args.why))
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
        if args.journal and args.translation_only:
            from trendwatch.journal import render_text, run_journal
            result = run_journal(get_llm(cfg["llm"]), cfg, store, args.journal, subject=args.subject or "",
                                 lang=args.lang or "", limit=args.limit or 10, use_cache=not args.no_cache,
                                 do_verify=args.verify)
            print(render_text(result))
            if result["rows"] and args.open:
                open_in_browser(store.path(result["path"]))
            return
        llm, focus = get_llm(cfg["llm"]), None
        if args.journal:
            from trendwatch.journal import prepare_focus, render_text
            focus = prepare_focus(llm, cfg, store, args.journal, lang=args.lang or "", limit=args.limit or 40,
                                  use_cache=not args.no_cache)
            if not focus["items"]:
                sys.exit(render_text({"source": args.journal, "found_via": focus["found_via"], "rows": []}))
            if args.only:   # nothing but this source: no other collection or discovery sources
                cfg["collection"]["sources"] = []
                cfg["news_sites"] = []
                cfg["languages"]["search_native"] = False
                cfg["analysis"]["min_items_to_analyze"] = min(cfg["analysis"]["min_items_to_analyze"], 4)
        name = run(llm, cfg, store, subject=args.subject, focus=focus, only=bool(args.journal and args.only))
    except Exception as e:
        message = explain(e)
        if message is None:
            raise
        sys.exit(f"\nError: {message}")
    if name and args.open:
        open_in_browser(store.path(name.replace(".md", ".html")))
    if name and args.email:
        from trendwatch.emailer import EmailError, send_report
        try:
            summary = send_report(args.data_dir, os.path.join(os.path.dirname(os.path.abspath(args.config)), "emails.yaml"))
        except EmailError as e:
            sys.exit(f"\nError: {e}")
        print(summary.get("skipped") or f"Emailed {summary['sent']} recipient(s): {', '.join(summary['recipients'])}")


if __name__ == "__main__":
    main()
