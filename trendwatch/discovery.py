"""Stage 1: decide WHAT to analyse (manual subject, or auto-discovered from trend signals)."""
import math
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


def trend_score(signals):
    """How strongly a topic is trending: breadth and volume together. Each platform adds log2(1 + count),
    where for news the count is the number of DIFFERENT outlets, so 20 outlets on one story outweigh two
    stray mentions elsewhere. Returns (score, distinct news outlets)."""
    by_platform = defaultdict(list)
    for sig in signals:
        by_platform[sig.platform].append(sig)
    total, news_outlets = 0.0, 0
    for platform, sigs in by_platform.items():
        if platform == "news":
            count = news_outlets = len({s.source or s.name for s in sigs})
        else:
            count = len(sigs)
        total += math.log2(1 + count)
    return round(total, 2), news_outlets


def _sample(signals, limit=6):
    """A few example headlines, rotating through platforms so one source does not fill the list."""
    by_platform = defaultdict(list)
    for sig in signals:
        by_platform[sig.platform].append(sig)
    out = []
    while len(out) < limit and any(by_platform.values()):
        for platform in list(by_platform):
            if by_platform[platform] and len(out) < limit:
                sig = by_platform[platform].pop(0)
                out.append({"platform": sig.platform, "name": sig.name, "url": sig.url, "source": sig.source})
    return out


def discover_topics(llm, cfg, existing_topic_names=(), record=None, extra_signals=(), only_extra=False):
    """Return EVERY qualifying topic, ranked by trend score (not capped; see split_topics).

    If `record` is a dict it is filled with the signals and all clusters, for the discovery log."""
    extra = list(extra_signals)
    signals = extra if only_extra else cap_signals(gather_signals(cfg), cfg) + extra
    if not signals:
        log.warning("no trend signals collected")
        return []
    d = cfg["discovery"]
    extra_urls = {s.url for s in extra if s.url}
    watchlist = [str(w).strip() for w in d.get("watchlist", []) if str(w).strip()]
    listing = "\n".join(f"[{i}] ({s.platform}) {clip(s.name, 120)}" for i, s in enumerate(signals))
    data = llm.complete_json(prompts.SYSTEM,
                             prompts.cluster(listing, d["candidate_topics"], list(existing_topic_names), watchlist),
                             tier="smart", max_tokens=8000)
    if isinstance(data, dict):
        data = data.get("topics", [])
    watch_names = {w.lower(): w for w in watchlist}

    topics = []
    for t in data:
        ids = list(dict.fromkeys(  # valid ids only, duplicates removed, order kept
            i for i in t.get("signal_ids", []) if isinstance(i, int) and 0 <= i < len(signals)))
        if not ids or not t.get("topic"):
            continue
        sigs = [signals[i] for i in ids]
        score, outlets = trend_score(sigs)
        name = tidy_topic_name(t["topic"])
        topics.append({
            "topic": name,
            "keywords": [str(k) for k in t.get("keywords", [])][:5],
            "summary": t.get("summary", ""),
            "platforms": sorted({s.platform for s in sigs}),
            "n_signals": len(ids),
            "n_outlets": outlets,
            "trend_score": score,
            "watchlist": name.lower() in watch_names,
            "signal_ids": ids,
            "signals": _sample(sigs),
            "focus_urls": [s.url for s in sigs if s.url in extra_urls],
        })

    # Qualify by breadth (several platforms) OR by many different outlets covering it.
    def qualifies(t):
        return (only_extra or t["watchlist"] or len(t["platforms"]) >= d["min_platforms"]
                or t["n_outlets"] >= d.get("min_news_outlets", 0) > 0)

    for t in topics:
        t["qualified"] = qualifies(t)
    pool = [t for t in topics if t["qualified"]] or topics
    pool.sort(key=lambda t: (-t["trend_score"], -t["n_signals"]))

    # Standing topics nothing matched today are still analysed (flagged, with no trend signals).
    found = {t["topic"].lower() for t in pool}
    for key, name in watch_names.items():
        if key not in found:
            pool.append({"topic": name, "keywords": [], "summary": "", "platforms": [], "n_signals": 0,
                         "n_outlets": 0, "trend_score": 0.0, "watchlist": True, "qualified": True,
                         "signal_ids": [], "signals": [], "needs_expand": True})
    for rank, t in enumerate(pool, 1):
        t["rank"] = rank

    if record is not None:
        record["signals"] = [{"id": i, "platform": s.platform, "name": s.name, "source": s.source, "url": s.url}
                             for i, s in enumerate(signals)]
        in_pool = {id(t) for t in pool}
        record["clusters"] = [{"topic": t["topic"], "rank": t.get("rank"), "trend_score": t["trend_score"],
                               "platforms": t["platforms"], "n_outlets": t["n_outlets"],
                               "watchlist": t["watchlist"], "signal_ids": t["signal_ids"],
                               "qualified": id(t) in in_pool} for t in topics + [x for x in pool if x.get("needs_expand")]]
    return pool


def split_topics(topics, cfg):
    """(analysed in depth, only listed). Watchlist topics are always analysed."""
    n = cfg["discovery"].get("topics_per_day", 0)
    if not n or n <= 0:
        return list(topics), []
    deep = [t for i, t in enumerate(topics) if i < n or t.get("watchlist")]
    ids = {id(t) for t in deep}
    return deep, [t for t in topics if id(t) not in ids]


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
