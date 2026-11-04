"""Report rendering: Markdown (for GitHub) and a self-contained HTML page (for your browser)."""
import html as _html

NOTE = ("Summaries and labels are written by an AI from headlines and short snippets. They describe "
        "what each group of sources says, not what is true, and they can be wrong. "
        "Open the linked sources before relying on any of it.")


def _trend_line(res):
    if res.get("platforms"):
        return f"Trending on {', '.join(res['platforms'])} ({res['n_signals']} signals)"
    return "Subject chosen manually"


def _rows_md(rows, kind):
    if not rows:
        return "_No data yet._\n"
    out = [f"| {kind} | Items | Label | Confidence | Reference rating |", "|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['name']} | {r['n']} | {r['label']} | {r['confidence']} | {r['reference'] or ''} |")
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------ Markdown
def render_topic(res):
    lines = [f"## #{res.get('rank', '?')} {res['topic']}", "", f"_{_trend_line(res)}_", ""]
    if res.get("summary"):
        lines += [res["summary"], ""]

    nar = res.get("narratives")
    if nar and nar["groups"]:
        lines += ["### What each side says", ""]
        for g in nar["groups"]:
            lines.append(f"**{g['group']}** ({g['n_items']} items; {', '.join(g['outlets'])})  ")
            lines.append(g["narrative"])
            if g["links"]:
                lines.append("Sources: " + ", ".join(f"[{l['outlet']}]({l['url']})" for l in g["links"]))
            lines.append("")
        if nar.get("differences"):
            lines += [f"**Where they differ:** {nar['differences']}", ""]
        if nar.get("unclassified"):
            lines += [f"_{nar['unclassified']} items came from outlets whose origin is unknown "
                      "and are not attributed to any side._", ""]
    else:
        lines += [f"_Not enough attributable coverage to summarise by source group "
                  f"({res['n_items']} items collected)._", ""]

    d = res.get("divide")
    if d:
        lines += ["### Analysis details", f"**Divide verdict: {d['verdict']}**"]
        if "kappa" in d:
            lines.append(f"(labeller agreement kappa {d['kappa']}; "
                         f"{d['n_framed']}/{d['n_items']} items took a clear framing)")
        elif d.get("note"):
            lines.append(d["note"])
        lines.append("")
    fr = res.get("framings", {}).get("framings", [])
    if fr and (d or {}).get("shares"):
        lines += ["| Framing | Meaning | Share of framed items |", "|---|---|---|"]
        for f in fr:
            lines.append(f"| {f['label']} | {f['description']} | {d['shares'].get(f['id'], 0):.0%} |")
        lines.append("")
    if res.get("narrative"):
        lines += [res["narrative"].strip(), ""]
    if res.get("rows"):
        lines += ["**Outlets**", "", _rows_md(res["rows"]["outlets"], "Outlet"),
                  "**Accounts**", "", _rows_md(res["rows"]["accounts"], "Account")]
        quotes = [(r["name"], e) for k in ("outlets", "accounts") for r in res["rows"][k]
                  for e in r["evidence"]]
        for name, e in quotes[:8]:
            lines.append(f"- **{name}**: “{e['quote']}” ({e['url']})")
        lines.append("")
    return "\n".join(lines)


def render(day, results):
    head = [f"# HameNews report {day}", "", f"_{NOTE}_", "", "## Trending now", ""]
    head += [f"{r.get('rank', i)}. {r['topic']}" for i, r in enumerate(results, 1)] + [""]
    return "\n".join(head + [render_topic(r) for r in results])


# ---------------------------------------------------------------------- HTML
def _e(x):
    return _html.escape(str(x if x is not None else ""), quote=True)


def _safe_url(u):
    return u if isinstance(u, str) and u.startswith(("http://", "https://")) else ""


def _link(label, url):
    u = _safe_url(url)
    return f'<a href="{_e(u)}" target="_blank" rel="noopener noreferrer">{_e(label)}</a>' if u else _e(label)


def _rows_html(rows, kind):
    if not rows:
        return "<p class='muted'>No data yet.</p>"
    body = "".join(
        f"<tr><td>{_e(r['name'])}</td><td>{_e(r['n'])}</td><td>{_e(r['label'])}</td>"
        f"<td>{_e(r['confidence'])}</td><td>{_e(r['reference'])}</td></tr>" for r in rows)
    return (f"<div class='scroll'><table><tr><th>{_e(kind)}</th><th>Items</th><th>Label</th>"
            f"<th>Confidence</th><th>Reference</th></tr>{body}</table></div>")


def _topic_html(res):
    h = [f"<section class='topic'><h2><span class='rank'>#{_e(res.get('rank', '?'))}</span> "
         f"{_e(res['topic'])}</h2><p class='muted'>{_e(_trend_line(res))}</p>"]
    if res.get("summary"):
        h.append(f"<p>{_e(res['summary'])}</p>")

    nar = res.get("narratives")
    if nar and nar["groups"]:
        h.append("<h3>What each side says</h3>")
        for g in nar["groups"]:
            links = " · ".join(_link(l["outlet"], l["url"]) for l in g["links"])
            h.append(
                f"<div class='side'><div class='side-name'>{_e(g['group'])} "
                f"<span class='muted'>({_e(g['n_items'])} items: {_e(', '.join(g['outlets']))})</span></div>"
                f"<p>{_e(g['narrative'])}</p>"
                + (f"<p class='src'>Sources: {links}</p>" if links else "") + "</div>")
        if nar.get("differences"):
            h.append(f"<p class='diff'><strong>Where they differ:</strong> {_e(nar['differences'])}</p>")
        if nar.get("unclassified"):
            h.append(f"<p class='muted'>{_e(nar['unclassified'])} items came from outlets whose origin "
                     "is unknown and are not attributed to any side.</p>")
    else:
        h.append(f"<p class='muted'>Not enough attributable coverage to summarise by source group "
                 f"({_e(res['n_items'])} items collected).</p>")

    d = res.get("divide")
    inner = []
    if d:
        detail = (f"labeller agreement kappa {d['kappa']}; {d['n_framed']}/{d['n_items']} items took a "
                  f"clear framing") if "kappa" in d else d.get("note", "")
        inner.append(f"<p><strong>Divide verdict: {_e(d['verdict'])}</strong> "
                     f"<span class='muted'>{_e(detail)}</span></p>")
    fr = res.get("framings", {}).get("framings", [])
    if fr and (d or {}).get("shares"):
        rows = "".join(f"<tr><td>{_e(f['label'])}</td><td>{_e(f['description'])}</td>"
                       f"<td>{d['shares'].get(f['id'], 0):.0%}</td></tr>" for f in fr)
        inner.append("<div class='scroll'><table><tr><th>Framing</th><th>Meaning</th>"
                     f"<th>Share of framed items</th></tr>{rows}</table></div>")
    if res.get("narrative"):
        inner.append(f"<p>{_e(res['narrative'].strip())}</p>")
    if res.get("rows"):
        inner += ["<h4>Outlets</h4>", _rows_html(res["rows"]["outlets"], "Outlet"),
                  "<h4>Accounts</h4>", _rows_html(res["rows"]["accounts"], "Account")]
        quotes = [(r["name"], e) for k in ("outlets", "accounts") for r in res["rows"][k]
                  for e in r["evidence"]]
        if quotes:
            inner.append("<h4>Evidence</h4><ul>" + "".join(
                f"<li><strong>{_e(n)}</strong>: “{_e(e['quote'])}” {_link('source', e['url'])}</li>"
                for n, e in quotes[:8]) + "</ul>")
    if inner:
        h.append("<details><summary>Analysis details</summary>" + "".join(inner) + "</details>")
    h.append("</section>")
    return "".join(h)


CSS = """
:root{--bg:#fff;--fg:#1c1c1e;--muted:#6b6b70;--card:#f5f5f7;--line:#d8d8dd;--accent:#0b5fff}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--fg:#ececef;--muted:#9a9aa2;--card:#1e1e22;--line:#34343a;--accent:#6ea2ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:860px;margin:0 auto;padding:24px 16px 64px}
h1{margin:0 0 4px}h2{margin:0 0 4px}h3{margin:20px 0 8px}h4{margin:16px 0 6px}
.muted{color:var(--muted);font-size:.92em}.note{color:var(--muted);font-size:.9em;margin:8px 0 20px}
.rank{color:var(--accent)}ol.toc{padding-left:22px}
.topic{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:20px 0}
.side{border-left:4px solid var(--accent);padding:2px 0 2px 14px;margin:14px 0}
.side-name{font-weight:600}.side p{margin:4px 0}.src{font-size:.9em}
.diff{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px 12px}
a{color:var(--accent)}details{margin-top:16px}summary{cursor:pointer;font-weight:600}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:.92em}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
"""


def render_html(day, results):
    toc = "".join(f"<li>{_e(r['topic'])}</li>" for r in results)
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>HameNews {_e(day)}</title><style>{CSS}</style></head><body><main>"
            f"<h1>HameNews</h1><p class='muted'>{_e(day)}</p><p class='note'>{_e(NOTE)}</p>"
            f"<h3>Trending now</h3><ol class='toc'>{toc}</ol>"
            + "".join(_topic_html(r) for r in results) + "</main></body></html>")
