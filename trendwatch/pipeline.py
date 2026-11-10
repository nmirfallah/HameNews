import json
from datetime import date

from . import groups, journal, languages, leanings, narratives, profiles, prompts, report
from .collect import collect
from .discovery import discover_topics, expand_subject, split_topics
from .stance import divide_report, get_framings, label_with_consensus
from .util import log, slugify


def analyze_topic(llm, topic, cfg, store, focus=None):
    topic = dict(topic, slug=slugify(topic["topic"]))
    try:
        languages.translate_keywords(llm, topic, cfg, store)   # so topics can be searched in other languages
    except Exception as e:
        log.warning("keyword translation step failed: %s", e)
    items = collect(topic, cfg)
    focus_ids = set()
    if focus:     # the chosen source's own items for this topic are always included
        mine = journal.focus_items_for_topic(focus, topic)
        focus_ids = {i.id for i in mine}
        have = {i.id for i in items}
        items += [i for i in mine if i.id not in have]
    res = {k: topic.get(k) for k in ("topic", "slug", "summary", "platforms", "n_signals", "n_outlets",
                                      "trend_score", "watchlist", "signals")}
    res["n_items"] = len(items)
    if focus:
        res["focus"] = {"source": focus["name"], "items": [journal.row_for(i) for i in items if i.id in focus_ids]}
    a = cfg["analysis"]

    try:
        languages.annotate(items)
        languages.translate_items(llm, items, store, cfg)       # non-English items -> English text_en
    except Exception as e:
        log.warning("language step failed: %s", e)

    # "Who says what": works even when there is too little data for stance labels.
    try:
        groups.assign_groups(llm, items, store, cfg)
        leanings.assign_leanings(llm, items, store, cfg)
        res["narratives"] = narratives.build(llm, topic["topic"], items, cfg)
    except Exception as e:
        log.warning("narratives step failed: %s", e)

    if len(items) < a["min_items_to_analyze"]:
        res["divide"] = {"verdict": "insufficient data", "note": f"Only {len(items)} items found."}
        return res

    framings = get_framings(llm, topic, items, store, cfg)
    res["framings"] = framings
    if len(framings["framings"]) < 2:
        res["divide"] = {"verdict": "no distinct framings",
                         "note": "The sample showed essentially one shared reaction."}
        return res

    labels, kappa = label_with_consensus(llm, topic["topic"], framings, items, cfg)
    divide = divide_report(labels, framings, kappa, cfg)
    res["divide"] = divide

    profiles.update(store, topic["slug"], items, labels)
    res["rows"] = profiles.rows(store, topic["slug"], framings, cfg)

    # Keep a small history so divides can be compared over days.
    saved = store.read(f"topics/{topic['slug']}.json", framings)
    saved.setdefault("history", []).append({"date": date.today().isoformat(), **{
        k: divide[k] for k in ("verdict", "kappa", "n_items", "n_framed")}})
    store.write(f"topics/{topic['slug']}.json", saved)

    stats = {"topic": topic["topic"], "summary": topic.get("summary", ""), "divide": divide,
             "framings": framings["framings"], "outlets": res["rows"]["outlets"],
             "accounts": res["rows"]["accounts"]}
    try:
        res["narrative"] = llm.complete(prompts.SYSTEM, prompts.narrative(stats),
                                        tier="smart", max_tokens=700)
    except Exception as e:
        log.warning("narrative failed: %s", e)
    return res


def _also_entry(t):
    return {k: t.get(k) for k in ("rank", "topic", "summary", "platforms", "n_signals", "n_outlets",
                                  "trend_score", "signals")}


def run(llm, cfg, store, subject=None, focus=None, only=False):
    day = date.today().isoformat()
    record, rest = {}, []
    if subject:
        deep = [expand_subject(llm, subject)]
        deep[0]["rank"] = 1
    else:
        existing = []   # readable names (the files are named by slug, which the model would imitate)
        for f in store.list_dir("topics"):
            if f.endswith(".json"):
                existing.append((store.read(f"topics/{f}", {}) or {}).get("topic") or f[:-5])
        topics = discover_topics(llm, cfg, existing, record,
                                 extra_signals=journal.focus_signals(focus) if focus else (),
                                 only_extra=bool(focus and only))
        deep, rest = split_topics(topics, cfg)
        if not cfg["discovery"].get("list_all_topics", True):
            rest = []
    if not deep:
        log.warning("nothing to analyse today")
        return None
    results = []
    for t in deep:
        if t.get("needs_expand"):      # a watchlist topic with no trend signals today: get its keywords first
            e = expand_subject(llm, t["topic"])
            t = dict(t, keywords=e["keywords"], summary=e["summary"])
        log.info("analysing topic #%s: %s", t.get("rank"), t["topic"])
        res = analyze_topic(llm, t, cfg, store, focus)
        res["rank"] = t.get("rank")
        results.append(res)

    also = [_also_entry(t) for t in rest]
    info = journal.focus_info(focus, results) if focus else None
    suffix = "-".join(slugify(x) for x in (subject, focus["source"] if focus else "") if x)
    name = f"reports/{day}-{suffix}.md" if suffix else f"reports/{day}.md"
    store.write_text(name, report.render(day, results, also, info))
    store.write_text(name.replace(".md", ".html"), report.render_html(day, results, also, info))
    store.write(name.replace(".md", ".json"), results)
    if record:
        _write_discovery_log(store, day, cfg, record, deep, rest)
    log.info("report written: %s (%d analysed, %d listed)", store.path(name), len(results), len(also))
    return name


def _write_discovery_log(store, day, cfg, record, deep, rest):
    """Everything discovery saw and what happened to each cluster, so 'why is X missing?' can be answered."""
    status = {t["topic"]: "analysed" for t in deep}
    status.update({t["topic"]: "listed only" for t in rest})
    for c in record.get("clusters", []):
        c["status"] = status.get(c["topic"], "below threshold")
    d = cfg["discovery"]
    record["date"] = day
    record["settings"] = {k: d.get(k) for k in ("topics_per_day", "min_platforms", "min_news_outlets",
                                                "candidate_topics", "watchlist")}
    store.write(f"discovery/{day}.json", record)
