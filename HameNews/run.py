#!/usr/bin/env python3
"""Daily trend + framing analysis.

  python run.py                         # auto-discover today's trending topics
  python run.py --subject "AI regulation"   # analyse one subject you choose
"""
import argparse
import logging

from trendwatch.config import load_config
from trendwatch.llm import get_llm
from trendwatch.pipeline import run
from trendwatch.store import Store


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject", help="analyse this subject instead of auto-discovering topics")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--topics", type=int, help="override discovery.topics_per_day")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = load_config(args.config)
    if args.topics:
        cfg["discovery"]["topics_per_day"] = args.topics
    run(get_llm(cfg["llm"]), cfg, Store(args.data_dir), subject=args.subject)


if __name__ == "__main__":
    main()
