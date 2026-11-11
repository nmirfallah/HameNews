"""Report rendering: Markdown (for GitHub) and a self-contained HTML page (for your browser)."""
import html as _html

NOTE = ("Summaries and labels are written by an AI from headlines and short snippets. They describe "
        "what each group of sources says, not what is true, and they can be wrong. "
        "Left/right labels are your own ratings where you set them; otherwise they are an AI estimate of "
        "the outlet's usual editorial line and are marked as such. "
        "Items in other languages are machine-translated into English, and quotes from them are translations. "
        "Open the linked sources before relying on any of it.")


def _counts(n_signals, n_outlets):
    return f"{n_signals} signals" + (f", {n_outlets} outlets" if n_outlets else "")


def _trend_line(res):
    if res.get("platforms"):
        return f"Trending on {', '.join(res['platforms'])} ({_counts(res['n_signals'], res.get('n_outlets'))})"
    if res.get("watchlist"):
        return "Watchlist topic (no trend signals today)"
    return "Subject chosen manually"


def _rows_md(rows, kind):
    if not rows:
        return "_No data yet._\n"
    out = [f"| {kind} | Items | Label | Confidence | Reference rating |", "|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['name']} | {r['n']} | {r['label']} | {r['confidence']} | {r['reference'] or ''} |")
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------ Markdown
def _focus_md(focus):
    if not focus:
        return []
    if not focus["items"]:
        return [f"### What {focus['source']} reported", "", f"_Nothing on this topic in the items fetched from {focus['source']}._", ""]
    lines = [f"### What {focus['source']} reported", ""]
    for r in focus["items"]:
        text = r["english"] or r["original"]
        link = f"[{text}]({r['url']})" if str(r.get("url", "")).startswith(("http://", "https://")) else text
        extra = f" ({r['lang_name']}; original: {r['original']})" if r["lang"] != "en" else ""
        lines.append(f"- {link}{extra}")
        lines += [f"  - CHECK: {f}" for f in r.get("flags", [])]
    lines.append("")
    return lines


def _focus_summary_md(info):
    if not info:
        return []
    langs = ", ".join(f"{k} {v}" for k, v in info["languages"].items())
    return [f"## Focus source: {info['name']}", "", f"Found via: {info['found_via']}.",
            f"{info['n_items']} items fetched ({langs}); the translation checks flagged {info['flagged']}; "
            f"it appears in {info['topics_covered']} of {info['topics_total']} analysed topics.", ""]


def render_topic(res):
    lines = [f"## #{res.get('rank', '?')} {res['topic']}", "", f"_{_trend_line(res)}_", ""]
    nar = res.get("narratives")
    if res.get("summary") and not (nar and nar.get("common")):  # the main story replaces the one-liner
        lines += [res["summary"], ""]
    lines += _focus_md(res.get("focus"))

    if nar and (nar["groups"] or nar.get("common")):
        if nar.get("common"):
            lines += ["### The main story", "", nar["common"]]
            if nar.get("common_links"):
                lines.append("Sources: " + ", ".join(f"[{l['outlet']}]({l['url']})" for l in nar["common_links"]))
            lines.append("")
        distinct = [g for g in nar["groups"] if g.get("distinct")]
        similar = [g for g in nar["groups"] if not g.get("distinct")]
        if distinct:
            lines += ["### How each side differs", ""]
            for g in distinct:
                lines.append(f"**{g['group']}** ({g['n_items']} items; {', '.join(g['outlets'])})  ")
                lines.append(g["distinct"])
                if g.get("languages"):
                    lines.append("Translated from: " + ", ".join(g["languages"]))
                if g.get("outlet_notes"):
                    lines.append("Outlet leanings: " + "; ".join(g["outlet_notes"]))
                if g["links"]:
                    lines.append("Sources: " + ", ".join(f"[{l['outlet']}]({l['url']})" for l in g["links"]))
                lines.append("")
        if similar:
            lines += ["Reported much the same as the main story: " + ", ".join(g["group"] for g in similar), ""]
        if nar.get("conflicts"):
            lines += ["### Points of disagreement", ""] + [f"- {c}" for c in nar["conflicts"]] + [""]
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


def _also_md(entry):
    lines = [f"### #{entry.get('rank', '?')} {entry['topic']}",
             f"_Trending on {', '.join(entry.get('platforms') or [])} "
             f"({_counts(entry.get('n_signals', 0), entry.get('n_outlets'))})_", ""]
    if entry.get("summary"):
        lines += [entry["summary"], ""]
    for sig in entry.get("signals") or []:
        url = sig.get("url") or ""
        lines.append(f"- [{sig['name']}]({url})" if url.startswith(("http://", "https://")) else f"- {sig['name']}")
    lines.append("")
    return "\n".join(lines)


def _ranked_titles(results, also):
    rows = [(r.get("rank") or 10 ** 6, r["topic"], "") for r in results]
    rows += [(a.get("rank") or 10 ** 6, a["topic"], " (headlines only)") for a in also]
    return sorted(rows, key=lambda row: row[0])


def render(day, results, also=(), focus=None):
    head = [f"# HameNews report {day}", "", f"_{NOTE}_", "", "## Trending now", ""]
    head += [f"{rank}. {title}{tag}" for rank, title, tag in _ranked_titles(results, also)] + [""]
    head += _focus_summary_md(focus)
    out = head + [render_topic(r) for r in results]
    if also:
        out += ["## Also trending (headlines only)", "",
                "_Not analysed in depth. Raise `discovery.topics_per_day` in config.yaml, or set it to 0, to "
                "analyse more of them._", ""] + [_also_md(a) for a in also]
    return "\n".join(out)


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


def _focus_html(focus):
    if not focus:
        return ""
    name = _e(focus["source"])
    if not focus["items"]:
        return f"<h3>What {name} reported</h3><p class='muted'>Nothing on this topic in the items fetched.</p>"
    rows = []
    for r in focus["items"]:
        marks = "".join(f"<div class='flag'>CHECK: {_e(f)}</div>" for f in r.get("flags", []))
        english = r["english"] or ("" if r["lang"] != "en" else r["original"])
        rows.append(f"<tr><td>{_e(r['lang_name'])}</td><td dir='auto' lang='{_e(r['lang'])}'>{_e(r['original'])}</td>"
                    f"<td>{_link(english or r['original'], r.get('url'))}</td><td>{marks}</td></tr>")
    return (f"<h3>What {name} reported</h3><div class='scroll'><table><tr><th>Language</th><th>Original</th>"
            f"<th>English</th><th>Checks</th></tr>{''.join(rows)}</table></div>")


def _topic_html(res):
    h = [f"<section class='topic'><h2><span class='rank'>#{_e(res.get('rank', '?'))}</span> "
         f"{_e(res['topic'])}</h2><p class='muted'>{_e(_trend_line(res))}</p>"]
    nar = res.get("narratives")
    if res.get("summary") and not (nar and nar.get("common")):  # the main story replaces the one-liner
        h.append(f"<p>{_e(res['summary'])}</p>")
    h.append(_focus_html(res.get("focus")))

    if nar and (nar["groups"] or nar.get("common")):
        if nar.get("common"):
            links = " · ".join(_link(l["outlet"], l["url"]) for l in nar.get("common_links", []))
            h.append("<h3>The main story</h3><div class='story'>"
                     f"<p>{_e(nar['common'])}</p>"
                     + (f"<p class='src'>Sources: {links}</p>" if links else "") + "</div>")
        distinct = [g for g in nar["groups"] if g.get("distinct")]
        similar = [g for g in nar["groups"] if not g.get("distinct")]
        if distinct:
            h.append("<h3>How each side differs</h3>")
        for g in distinct:
            links = " · ".join(_link(l["outlet"], l["url"]) for l in g["links"])
            h.append(
                f"<div class='side'><div class='side-name'>{_e(g['group'])} "
                f"<span class='muted'>({_e(g['n_items'])} items: {_e(', '.join(g['outlets']))})</span></div>"
                f"<p>{_e(g['distinct'])}</p>"
                + (f"<p class='src'>Translated from: {_e(', '.join(g['languages']))}</p>"
                   if g.get("languages") else "")
                + (f"<p class='src'>Outlet leanings: {_e('; '.join(g['outlet_notes']))}</p>"
                   if g.get("outlet_notes") else "")
                + (f"<p class='src'>Sources: {links}</p>" if links else "") + "</div>")
        if similar:
            h.append("<p class='muted'>Reported much the same as the main story: "
                     f"{_e(', '.join(g['group'] for g in similar))}</p>")
        if nar.get("conflicts"):
            h.append("<h3>Points of disagreement</h3><ul class='diff'>"
                     + "".join(f"<li>{_e(c)}</li>" for c in nar["conflicts"]) + "</ul>")
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
.diff{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px 12px 10px 30px}
.flag{color:#b45309}
.story{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:2px 14px}
a{color:var(--accent)}details{margin-top:16px}summary{cursor:pointer;font-weight:600}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:.92em}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
"""


def _also_html(entry):
    items = []
    for sig in entry.get("signals") or []:
        items.append(f"<li>{_link(sig['name'], sig.get('url'))}</li>")
    return (f"<section class='topic'><h3><span class='rank'>#{_e(entry.get('rank', '?'))}</span> "
            f"{_e(entry['topic'])}</h3><p class='muted'>Trending on {_e(', '.join(entry.get('platforms') or []))} "
            f"({_e(_counts(entry.get('n_signals', 0), entry.get('n_outlets')))})</p>"
            + (f"<p>{_e(entry['summary'])}</p>" if entry.get("summary") else "")
            + (f"<ul>{''.join(items)}</ul>" if items else "") + "</section>")


def _focus_summary_html(info):
    if not info:
        return ""
    langs = ", ".join(f"{k} {v}" for k, v in info["languages"].items())
    return (f"<h2>Focus source: {_e(info['name'])}</h2><p class='muted'>Found via: {_e(info['found_via'])}.</p>"
            f"<p>{_e(info['n_items'])} items fetched ({_e(langs)}); the translation checks flagged "
            f"{_e(info['flagged'])}; it appears in {_e(info['topics_covered'])} of {_e(info['topics_total'])} "
            "analysed topics.</p>")


def render_html(day, results, also=(), focus=None):
    toc = "".join(f"<li value='{_e(rank)}'>{_e(title)}<span class='muted'>{_e(tag)}</span></li>"
                  for rank, title, tag in _ranked_titles(results, also))
    more = ""
    if also:
        more = ("<h2>Also trending (headlines only)</h2><p class='muted'>Not analysed in depth. Raise "
                "<code>discovery.topics_per_day</code> in config.yaml, or set it to 0, to analyse more of them.</p>"
                + "".join(_also_html(a) for a in also))
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>HameNews {_e(day)}</title><style>{CSS}</style></head><body><main>"
            f"<h1>HameNews</h1><p class='muted'>{_e(day)}</p><p class='note'>{_e(NOTE)}</p>"
            f"<h3>Trending now</h3><ol class='toc'>{toc}</ol>"
            + _focus_summary_html(focus) + "".join(_topic_html(r) for r in results) + more + "</main></body></html>")


# --------------------------------------------------------------------- email body
# Email clients drop <style> blocks, CSS variables and <details>, so this version uses inline styles only and
# shows everything expanded. The full report is attached to the email.
_FONT = "font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif"
_MUTED = "color:#6b6b70"


def _a(label, url):
    u = _safe_url(url)
    return f'<a href="{_e(u)}" style="color:#0b5fff">{_e(label)}</a>' if u else _e(label)


def _links_email(links):
    return " &middot; ".join(_a(l["outlet"], l["url"]) for l in links)


def _topic_email(res):
    out = ['<div style="border:1px solid #d8d8dd;border-radius:10px;padding:14px 16px;margin:0 0 16px">',
           f'<h2 style="font-size:18px;margin:0 0 2px"><span style="color:#0b5fff">#{_e(res.get("rank", "?"))}</span> '
           f'{_e(res["topic"])}</h2>',
           f'<p style="{_MUTED};font-size:13px;margin:0 0 10px">{_e(_trend_line(res))}</p>']
    focus = res.get("focus")
    if focus:
        if focus["items"]:
            lines = "".join(
                f'<li style="margin:0 0 4px">{_a(r["english"] or r["original"], r.get("url"))}'
                + (f' <span style="{_MUTED}">({_e(r["lang_name"])}; original: {_e(r["original"])})</span>'
                   if r["lang"] != "en" else "") + "</li>" for r in focus["items"])
            out.append(f'<h3 style="font-size:15px;margin:10px 0 4px">What {_e(focus["source"])} reported</h3>'
                       f'<ul style="margin:0 0 8px;padding-left:20px">{lines}</ul>')
        else:
            out.append(f'<p style="{_MUTED}">Nothing from {_e(focus["source"])} on this topic.</p>')

    nar = res.get("narratives")
    if nar and (nar["groups"] or nar.get("common")):
        if nar.get("common"):
            out.append('<h3 style="font-size:15px;margin:10px 0 4px">The main story</h3>'
                       f'<p style="margin:0 0 6px;line-height:1.5">{_e(nar["common"])}</p>')
            if nar.get("common_links"):
                out.append(f'<p style="font-size:13px;margin:0 0 8px">Sources: {_links_email(nar["common_links"])}</p>')
        distinct = [g for g in nar["groups"] if g.get("distinct")]
        similar = [g for g in nar["groups"] if not g.get("distinct")]
        if distinct:
            out.append('<h3 style="font-size:15px;margin:10px 0 4px">How each side differs</h3>')
        for g in distinct:
            extra = []
            if g.get("languages"):
                extra.append("Translated from: " + ", ".join(g["languages"]))
            if g.get("outlet_notes"):
                extra.append("Outlet leanings: " + "; ".join(g["outlet_notes"]))
            if g["links"]:
                extra.append("Sources: " + _links_email(g["links"]))
            out.append('<div style="border-left:4px solid #0b5fff;padding:2px 0 2px 12px;margin:0 0 10px">'
                       f'<div style="font-weight:600">{_e(g["group"])} <span style="{_MUTED};font-weight:400">'
                       f'({_e(g["n_items"])} items)</span></div>'
                       f'<p style="margin:2px 0;line-height:1.5">{_e(g["distinct"])}</p>'
                       + "".join(f'<p style="{_MUTED};font-size:12px;margin:2px 0">{x}</p>'
                                 for x in ([_e(e) for e in extra if not e.startswith("Sources")]
                                           + [e for e in extra if e.startswith("Sources")])) + "</div>")
        if similar:
            out.append(f'<p style="{_MUTED};font-size:13px">Reported much the same as the main story: '
                       f'{_e(", ".join(g["group"] for g in similar))}</p>')
        if nar.get("conflicts"):
            out.append('<h3 style="font-size:15px;margin:10px 0 4px">Points of disagreement</h3>'
                       '<ul style="margin:0 0 8px;padding-left:20px">'
                       + "".join(f'<li style="margin:0 0 4px">{_e(c)}</li>' for c in nar["conflicts"]) + "</ul>")
    else:
        out.append(f'<p style="{_MUTED}">Not enough attributable coverage to summarise by source group '
                   f'({_e(res["n_items"])} items collected).</p>')
    d = res.get("divide")
    if d:
        out.append(f'<p style="{_MUTED};font-size:12px;margin:6px 0 0">Divide verdict: {_e(d["verdict"])}. '
                   'Full tables are in the attached report.</p>')
    out.append("</div>")
    return "".join(out)


def render_email_html(day, results, also=(), focus=None):
    toc = "".join(f'<li value="{_e(rank)}" style="margin:0 0 3px">{_e(title)}'
                  f'<span style="{_MUTED}">{_e(tag)}</span></li>' for rank, title, tag in _ranked_titles(results, also))
    parts = [f'<div style="{_FONT};max-width:680px;margin:0 auto;padding:16px;color:#1c1c1e;font-size:15px">',
             '<h1 style="font-size:22px;margin:0 0 2px">HameNews</h1>',
             f'<p style="{_MUTED};margin:0 0 10px">{_e(day)}</p>',
             f'<p style="{_MUTED};font-size:12px;margin:0 0 14px">{_e(NOTE)}</p>',
             '<h2 style="font-size:17px;margin:14px 0 6px">Trending now</h2>'
             f'<ol style="margin:0 0 16px;padding-left:24px">{toc}</ol>']
    if focus:
        langs = ", ".join(f"{k} {v}" for k, v in focus["languages"].items())
        parts.append(f'<p style="margin:0 0 14px"><strong>Focus source: {_e(focus["name"])}.</strong> '
                     f'{_e(focus["n_items"])} items fetched ({_e(langs)}); it appears in {_e(focus["topics_covered"])} '
                     f'of {_e(focus["topics_total"])} analysed topics.</p>')
    parts += [_topic_email(r) for r in results]
    if also:
        parts.append('<h2 style="font-size:17px;margin:18px 0 6px">Also trending (headlines only)</h2>')
        for a in also:
            heads = "".join(f'<li style="margin:0 0 2px">{_a(s["name"], s.get("url"))}</li>'
                            for s in (a.get("signals") or [])[:3])
            parts.append(f'<div style="margin:0 0 12px"><div style="font-weight:600"><span style="color:#0b5fff">'
                         f'#{_e(a.get("rank", "?"))}</span> {_e(a["topic"])} <span style="{_MUTED};font-weight:400;'
                         f'font-size:13px">({_e(_counts(a.get("n_signals", 0), a.get("n_outlets")))})</span></div>'
                         + (f'<ul style="margin:2px 0 0;padding-left:20px">{heads}</ul>' if heads else "") + "</div>")
    parts.append(f'<p style="{_MUTED};font-size:12px;margin-top:18px">The full report with tables is attached.</p></div>')
    return ('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, '
            f'initial-scale=1"><title>HameNews {_e(day)}</title></head><body style="margin:0;background:#ffffff">'
            + "".join(parts) + "</body></html>")
