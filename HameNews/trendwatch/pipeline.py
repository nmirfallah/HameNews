import json
from datetime import date

from . import groups, narratives, profiles, prompts, report
from .collect import collect
from .discovery import discover_topics, expand_subject
from .stance import divide_report, get_framings, label_with_consensus
from .util import log, slugify


def analyze_topic(llm, topic, cfg, store):
    topic = dict(topic, slug=slugify(topic["topic"]))
    items = collect(topic, cfg)
    res = {k: topic.get(k) for k in ("topic", "slug", "summary", "platforms", "n_signals", "signals")}
    res["n_items"] = len(items)
    a = cfg["analysis"]

    # "Who says what": works even when there is too little data for stance labels.
    try:
        groups.assign_groups(llm, items, store)
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


def run(llm, cfg, store, subject=None):
    day = date.today().isoformat()
    if subject:
        topics = [expand_subject(llm, subject)]
    else:
        existing = [f[:-5] for f in store.list_dir("topics") if f.endswith(".json")]
        topics = discover_topics(llm, cfg, existing)
    if not topics:
        log.warning("nothing to analyse today")
        return None
    results = []
    for rank, t in enumerate(topics, 1):   # topics arrive sorted by how much they are trending
        log.info("analysing topic #%d: %s", rank, t["topic"])
        res = analyze_topic(llm, t, cfg, store)
        res["rank"] = rank
        results.append(res)
    name = f"reports/{day}-{slugify(subject)}.md" if subject else f"reports/{day}.md"
    store.write_text(name, report.render(day, results))
    store.write_text(name.replace(".md", ".html"), report.render_html(day, results))
    store.write(name.replace(".md", ".json"), results)
    log.info("report written: %s", store.path(name))
    return name
