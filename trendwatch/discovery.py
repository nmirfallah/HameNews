"""Stage 1: decide WHAT to analyse (manual subject, or auto-discovered from trend signals)."""
import re
from collections import defaultdict

from . import prompts
from .sources import SIGNAL_SOURCES
from .util import clip, log


def tidy_topic_name(name):
    """Turn a hyphenated slug the model sometimes returns ('tesla-cybertruck-wind-down') into readable text."""
    name = str(name or "").strip()
    if name.count("-") >= 2 and re.fullmatch(r"[a-z0-9-]+", name):
        name = name.replace("-", " ")
        name = name[:1].upper() + name[1:]
    return name


def gather_signals(cfg):
    out = []
    for name in cfg["discovery"]["enabled_sources"]:
        fn = SIGNAL_SOURCES.get(name)
        if fn is None:
            log.warning("unknown discovery source %r", name)
            continue
        try:
            sigs = fn(cfg)
        except Exception as e:  # one broken source must never kill the run
            log.warning("discovery source %s failed: %s", name, e)
            continue
        log.info("discovery %s: %d signals", name, len(sigs))
        out.extend(sigs)
    return out


def cap_signals(signals, cfg):
    d = cfg["discovery"]
    groups = defaultdict(list)
    for s in signals:
        groups[s.platform].append(s)
    out = []
    for platform, sigs in groups.items():
        cap = d["news_signal_cap"] if platform == "news" else d["signals_per_platform"]
        out.extend(sorted(sigs, key=lambda s: -s.score)[:cap])
    return out


def discover_topics(llm, cfg, existing_topic_names=()):
    signals = cap_signals(gather_signals(cfg), cfg)
    if not signals:
        log.warning("no trend signals collected")
        return []
    d = cfg["discovery"]
    listing = "\n".join(f"[{i}] ({s.platform}) {clip(s.name, 120)}" for i, s in enumerate(signals))
    data = llm.complete_json(prompts.SYSTEM,
                             prompts.cluster(listing, d["candidate_topics"], list(existing_topic_names)),
                             tier="smart", max_tokens=4000)
    if isinstance(data, dict):
        data = data.get("topics", [])

    topics = []
    for t in data:
        ids = list(dict.fromkeys(  # valid ids only, duplicates removed, order kept
            i for i in t.get("signal_ids", []) if isinstance(i, int) and 0 <= i < len(signals)))
        if not ids or not t.get("topic"):
            continue
        platforms = sorted({signals[i].platform for i in ids})
        topics.append({
            "topic": tidy_topic_name(t["topic"]),
            "keywords": [str(k) for k in t.get("keywords", [])][:5],
            "summary": t.get("summary", ""),
            "platforms": platforms,
            "n_signals": len(ids),
            "signals": [{"platform": signals[i].platform, "name": signals[i].name} for i in ids[:8]],
        })

    # "Trending" = showing up on several independent platforms, then by number of signals.
    qualified = [t for t in topics if len(t["platforms"]) >= d["min_platforms"]]
    pool = qualified or topics
    pool.sort(key=lambda t: (-len(t["platforms"]), -t["n_signals"]))
    return pool[: d["topics_per_day"]]


def expand_subject(llm, subject):
    data = llm.complete_json(prompts.SYSTEM, prompts.expand(subject), tier="fast", max_tokens=500)
    return {
        "topic": data.get("topic") or subject,
        "keywords": [str(k) for k in data.get("keywords", [])][:5] or [subject],
        "summary": data.get("summary", ""),
        "platforms": [],
        "n_signals": 0,
        "signals": [],
    }
