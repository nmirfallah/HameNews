"""Markdown report rendering."""


def _table(rows, kind):
    if not rows:
        return "_No data yet._\n"
    out = [f"| {kind} | Posts/articles | Label | Confidence | Reference rating |",
           "|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['name']} | {r['n']} | {r['label']} | {r['confidence']} | {r['reference'] or ''} |")
    return "\n".join(out) + "\n"


def render_topic(res):
    lines = [f"## {res['topic']}", ""]
    if res.get("summary"):
        lines += [res["summary"], ""]
    if res.get("platforms"):
        lines += [f"**Trending on:** {', '.join(res['platforms'])} ({res['n_signals']} signals)", ""]
    lines += [f"**Collected:** {res['n_items']} items", ""]

    if res.get("narrative"):
        lines += [res["narrative"].strip(), ""]

    d = res.get("divide")
    if d:
        lines += [f"**Divide verdict: {d['verdict']}**"]
        if "kappa" in d:
            lines += [f"(labeler agreement kappa {d['kappa']}; "
                      f"{d['n_framed']}/{d['n_items']} items took a clear framing)"]
        else:
            lines += [d.get("note", "")]
        lines.append("")

    fr = res.get("framings", {}).get("framings", [])
    if fr and res.get("divide", {}).get("counts"):
        lines += ["| Framing | Meaning | Share of framed items |", "|---|---|---|"]
        for f in fr:
            share = res["divide"]["shares"].get(f["id"], 0)
            lines.append(f"| {f['label']} | {f['description']} | {share:.0%} |")
        lines.append("")

    if res.get("rows"):
        lines += ["### Outlets", _table(res["rows"]["outlets"], "Outlet"),
                  "### Accounts", _table(res["rows"]["accounts"], "Account")]
        quotes = [(r["name"], e) for k in ("outlets", "accounts") for r in res["rows"][k]
                  for e in r["evidence"]]
        if quotes:
            lines.append("### Evidence")
            for name, e in quotes[:8]:
                lines.append(f"- **{name}**: “{e['quote']}” ({e['url']})")
            lines.append("")
    return "\n".join(lines)


def render(day, results):
    head = [f"# Trend report {day}", "",
            "_Labels describe how coverage and posts on a topic are framed, judged by an AI from "
            "headlines and short snippets. They are not verdicts on a source in general. "
            "Check the evidence before trusting any label._", ""]
    return "\n".join(head + [render_topic(r) for r in results])
