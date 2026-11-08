"""Answer "why is X not in the report?" from the saved discovery log."""
from collections import Counter


def _latest(store):
    files = sorted(f for f in store.list_dir("discovery") if f.endswith(".json"))
    return (files[-1], store.read(f"discovery/{files[-1]}")) if files else (None, None)


def explain(store, term):
    name, log = _latest(store)
    if not log:
        return ("There is no discovery log yet. Run `python run.py` once (without --subject) and then try again; "
                "each run saves everything its trend sources returned.")
    needle = term.lower().strip()
    hits = [s for s in log.get("signals", []) if needle in s["name"].lower()]
    cfg = log.get("settings", {})
    lines = [f"Discovery log: {name} ({len(log.get('signals', []))} signals, {len(log.get('clusters', []))} topics found)"]

    if not hits:
        lines += ["", f"No signal in that run mentions '{term}'. It never reached the topic step, so no ranking rule",
                  "excluded it: the sources simply did not return it that day. Ways to widen the net:",
                  "  - add it to discovery.watchlist in config.yaml so it is always analysed;",
                  "  - raise discovery.headlines_per_feed or add more news_feeds;",
                  "  - run `python check_sources.py` to see which sources respond."]
        return "\n".join(lines)

    by_platform = Counter(s["platform"] for s in hits)
    outlets = {s.get("source") for s in hits if s.get("source")}
    lines += ["", f"{len(hits)} signals mention '{term}' "
                  f"({', '.join(f'{k}: {v}' for k, v in by_platform.items())}; {len(outlets)} different outlets).",
              "Examples:"]
    lines += [f"  - ({s['platform']}) {s['name']}" for s in hits[:8]]

    ids = {s["id"] for s in hits}
    placed = []
    for c in log.get("clusters", []):
        n = len(ids & set(c.get("signal_ids", [])))
        if n:
            placed.append((n, c))
    lines.append("")
    if not placed:
        lines.append("The AI did not put any of these signals into a topic (it can drop signals that fit no group).")
        lines.append("Add the subject to discovery.watchlist, or raise discovery.candidate_topics.")
    for n, c in sorted(placed, key=lambda x: -x[0]):
        lines.append(f"  - {n} of them are in topic #{c.get('rank')} '{c['topic']}': {c.get('status', '?')} "
                     f"(trend score {c['trend_score']}, platforms {', '.join(c['platforms'])}, "
                     f"{c['n_outlets']} news outlets)")
        if c.get("status") == "below threshold":
            lines.append(f"      It needs {cfg.get('min_platforms')} platforms or {cfg.get('min_news_outlets')} "
                         "different news outlets to qualify.")
        if c.get("status") == "listed only":
            lines.append(f"      Only the top {cfg.get('topics_per_day')} topics get the full analysis; this one is "
                         "listed under 'Also trending'.")
    return "\n".join(lines)
