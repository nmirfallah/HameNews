"""Check ONE source end to end: fetch its latest items, detect their language, translate them, and show
the original next to the English so translation quality can be judged (by eye and by automatic checks).

    python run.py -j irna.ir               # a domain, an outlet name, or a feed URL
    python run.py -j irna.ir --lang fa     # ask Google News for Persian pages of that site
"""
import html as _html
import re
import tempfile
from collections import Counter
from datetime import date
from urllib.parse import urljoin, urlparse

from . import agencies, languages, prompts
from .http import get, get_feed
from .models import Item
from .report import CSS, _e, _link
from .sources.news import google_items, google_url
from .models import Signal
from .store import Store
from .util import clip, log, slugify, strip_html, term_in

COMMON_FEED_PATHS = ("/rss", "/rss.xml", "/feed", "/feed/", "/atom.xml", "/rss/")
GENERIC_WORDS = {"news", "agency", "press", "media", "network", "service", "the", "and", "daily", "international"}


# ------------------------------------------------------------ finding the source
def parse_source(source):
    """Classify what the user typed: a URL, a domain, or an outlet name."""
    s = (source or "").strip()
    if re.match(r"https?://", s, re.I):
        return {"kind": "url", "url": s, "domain": urlparse(s).netloc.lower().removeprefix("www.")}
    if "." in s and " " not in s:
        return {"kind": "domain", "domain": s.split("/")[0].lower().removeprefix("www.")}
    return {"kind": "name", "name": s}


def domain_for_name(name, cfg):
    """Look an outlet name up in the agency list and the configured sites. An agency entry can hold several
    outlets and domains, so the domain is chosen by a word of the name appearing in it."""
    key = name.lower()
    for _, _, names, domains in agencies.AGENCIES:
        if key in (n.lower() for n in names) and domains:
            words = sorted((w for w in re.findall(r"[a-z0-9]{3,}", key) if w not in GENERIC_WORDS),
                           key=len, reverse=True)
            for word in words:
                for d in domains:
                    if word in d:
                        return d
            return domains[0]
    for site in cfg.get("news_sites", []):
        if site["name"].lower() == key:
            return site["site"]
    return ""


def display_name(domain, fallback=""):
    """A readable outlet name for a domain ('tasnimnews.ir' -> 'Tasnim News Agency'), from the agency list."""
    for _, _, names, domains in agencies.AGENCIES:
        if domain in domains:
            for n in names:
                tokens = [t for t in re.findall(r"[a-z0-9]{3,}", n.lower()) if t not in GENERIC_WORDS]
                if any(t in domain for t in tokens):
                    return n
            return names[0]
    return fallback or domain


def _stamp(items, domain):
    for it in items:
        it.domain = it.domain or domain
    return items


def _entry_text(e):
    title, summary = strip_html(e.get("title", "")), strip_html(e.get("summary", ""))
    return title if len(summary) < len(title) + 10 else f"{title}. {summary}"


def _items_from_feed(feed, outlet, lang_hint, limit):
    feed_lang = lang_hint or (getattr(feed, "feed", None) or {}).get("language", "")
    out = []
    for e in feed.entries:
        text = _entry_text(e)
        if text and e.get("link"):
            out.append(Item(id=e["link"], kind="article", platform="news", outlet=outlet, text=text,
                            url=e["link"], created_at=e.get("published", ""), lang=feed_lang))
        if len(out) >= limit:
            break
    return out


def find_feed(domain):
    """Look for an RSS/Atom feed: the links the homepage advertises first, then the usual paths."""
    base = f"https://{domain}/"
    candidates = []
    page = get(base)
    if page is not None:
        for tag in re.findall(r"<link\b[^>]*>", page.text, re.I):
            if (re.search(r'rel=["\']alternate["\']', tag, re.I)
                    and re.search(r'type=["\']application/(rss|atom)\+xml["\']', tag, re.I)):
                m = re.search(r'href=["\']([^"\']+)["\']', tag, re.I)
                if m:
                    candidates.append(urljoin(base, _html.unescape(m.group(1))))
    candidates += [urljoin(base, p) for p in COMMON_FEED_PATHS]
    seen = []
    for url in candidates:
        if url in seen or len(seen) >= 8:
            continue
        seen.append(url)
        feed = get_feed(url)
        if feed is not None and getattr(feed, "entries", None):
            return feed, url
    return None, ""


def collect_journal(source, cfg, subject="", lang="", limit=10):
    """Return (items, how_found). Tries configured feeds, a given feed URL, a discovered feed, then Google News."""
    spec = parse_source(source)
    domain = spec.get("domain") or (domain_for_name(spec["name"], cfg) if spec["kind"] == "name" else "")
    lang = languages.norm(lang)

    for f in cfg.get("news_feeds", []):          # 1) a feed you already configured
        host = urlparse(f["url"]).netloc.lower().removeprefix("www.")
        if spec.get("name", "").lower() == f["name"].lower() or (domain and (host == domain or host.endswith("." + domain))):
            feed = get_feed(f["url"])
            if feed is not None and feed.entries:
                return (_stamp(_items_from_feed(feed, f["name"], f.get("lang") or lang, limit), host),
                        f"your configured feed '{f['name']}'")

    if spec["kind"] == "url":                    # 2) the URL itself may be a feed
        feed = get_feed(spec["url"])
        if feed is not None and getattr(feed, "entries", None):
            return (_stamp(_items_from_feed(feed, display_name(domain), lang, limit), domain),
                    f"the feed at {spec['url']}")

    if domain:
        feed, url = find_feed(domain)            # 3) a feed discovered on the site
        if feed is not None:
            return (_stamp(_items_from_feed(feed, display_name(domain), lang, limit), domain),
                    f"a feed found at {url}")
        query = f"{subject} site:{domain}".strip()   # 4) Google News restricted to the site
        url = google_url(query, "US", lang or "en")
        items = _stamp(google_items(get_feed(url), limit, outlet=display_name(domain), lang=lang or ""), domain)
        if items:
            return items, f"a Google News search restricted to {domain}" + (f" in {languages.name(lang)}" if lang else "")
    return [], "nothing (no feed was found and Google News returned no results for this source)"


# ------------------------------------------------------------- checking quality
def _letters(text):
    return [c for c in text if c.isalpha()]


def check_row(row):
    """Cheap automatic checks on one row; returns a list of short flags."""
    flags = []
    if row.get("meta_lang") and row["lang"] and row["meta_lang"] != row["lang"]:
        flags.append(f"the source said {languages.name(row['meta_lang'])} but the model says {languages.name(row['lang'])}")
    if row["lang"] == "en":
        return flags
    orig, eng = row["original"], row["english"]
    if not eng:
        return flags + ["no translation returned"]
    if eng.strip().lower() == orig.strip().lower():
        flags.append("translation identical to the original")
    letters = _letters(eng)
    if letters and sum(ord(c) >= 0x250 for c in letters) / len(letters) > 0.2:
        flags.append("English text still contains non-Latin script")
    ow, ew = len(orig.split()), len(eng.split())
    if ow >= 4 and (ew / ow < 0.3 or ew / ow > 3.5):
        flags.append("translation length looks off")
    return flags


def _safe(text):
    return text[:400].replace("<", "‹").replace(">", "›")


def verify(llm, rows, batch=10):
    """Optional independent check: a stronger model grades each translation against its original."""
    todo = [r for r in rows if r["english"]]
    for start in range(0, len(todo), batch):
        chunk = todo[start:start + batch]
        block = "\n".join(
            f'<item i="{i}" lang="{r["lang"]}"><original>{_safe(r["original"])}</original>'
            f'<english>{_safe(r["english"])}</english></item>' for i, r in enumerate(chunk))
        try:
            data = llm.complete_json(prompts.SYSTEM, prompts.verify_translations(block), tier="smart", max_tokens=2000)
        except Exception as e:
            log.warning("translation verification failed: %s", e)
            continue
        for row in data if isinstance(data, list) else data.get("items", []) if isinstance(data, dict) else []:
            try:
                j, verdict = int(row["i"]), str(row["verdict"]).strip().lower()
            except (KeyError, ValueError, TypeError, AttributeError):
                continue
            if 0 <= j < len(chunk) and verdict in ("good", "minor", "wrong"):
                chunk[j]["verdict"], chunk[j]["note"] = verdict, clip(str(row.get("note", "")), 160)


# ------------------------------------------------------------------- the run
def translate_rows(llm, cfg, store, items, use_cache=True):
    """Detect each item's language and translate to English (mutating the items); return one row per item."""
    meta = {it.id: languages.norm(it.lang) for it in items}
    languages.annotate(items)
    detected = {it.id: it.lang for it in items}
    cfg = dict(cfg, languages=dict(cfg.get("languages", {}), translate=True))   # these sources are always translated
    tstore = store if use_cache else Store(tempfile.mkdtemp(prefix="hamenews-nocache-"))
    languages.translate_items(llm, items, tstore, cfg)

    rows = []
    for i, it in enumerate(items, 1):
        if meta[it.id]:
            how_lang = "source metadata"
        elif it.lang == detected[it.id] and languages.guess(it.text):
            how_lang = "script/word guess"
        elif it.lang == "en" and it.text.isascii():
            how_lang = "assumed English"
        else:
            how_lang = "model"
        if it.lang != detected[it.id]:
            how_lang = "corrected by the model"
        row = {"n": i, "original": it.text, "english": it.text_en, "lang": it.lang, "lang_name": languages.name(it.lang),
               "lang_how": how_lang, "meta_lang": meta[it.id], "url": it.url, "verdict": "", "note": ""}
        row["flags"] = check_row(row)
        rows.append(row)
    return rows


def run_journal(llm, cfg, store, source, subject="", lang="", limit=10, use_cache=True, do_verify=False):
    """The translation test: show one source's items next to their English translations."""
    items, how = collect_journal(source, cfg, subject, lang, limit)
    result = {"source": source, "found_via": how, "date": date.today().isoformat(), "rows": [], "summary": {}}
    if not items:
        return result
    result["rows"] = rows = translate_rows(llm, cfg, store, items, use_cache)
    if do_verify:
        verify(llm, rows)
    translated = [r for r in rows if r["lang"] != "en"]
    result["summary"] = {
        "items": len(rows), "translated": len([r for r in translated if r["english"]]),
        "english": len(rows) - len(translated), "flagged": len([r for r in rows if r["flags"]]),
        "languages": dict(Counter(r["lang_name"] for r in rows)),
        "verdicts": dict(Counter(r["verdict"] for r in rows if r["verdict"])),
    }
    name = f"journal/{slugify(source)}-{result['date']}"
    store.write_text(name + ".html", render_html(result))
    store.write_text(name + ".md", render_md(result))
    store.write(name + ".json", result)
    result["path"] = name + ".html"
    return result


# ------------------------------------------------------- focus on one source in the real analysis
def prepare_focus(llm, cfg, store, source, lang="", limit=40, use_cache=True):
    """Fetch and translate one source's latest items so the normal analysis can include them."""
    items, how = collect_journal(source, cfg, "", lang, limit)
    focus = {"source": source, "name": items[0].outlet if items else source, "found_via": how,
             "items": items, "rows": []}
    if items:
        focus["rows"] = translate_rows(llm, cfg, store, items, use_cache)
    return focus


def focus_signals(focus):
    """The source's headlines as trend signals (in English), so topics it covers rise in the ranking."""
    return [Signal(name=f"{it.en} [{it.outlet}]", platform="news", score=1.0, url=it.url, source=it.outlet)
            for it in focus["items"]]


def focus_items_for_topic(focus, topic):
    """The source's items that belong to a topic: members of its cluster, plus keyword matches in English."""
    urls = set(topic.get("focus_urls", []))
    terms = [t for t in [topic["topic"]] + list(topic.get("keywords", [])) if t]
    return [it for it in focus["items"] if it.url in urls or any(term_in(t, it.en) for t in terms)]


def row_for(item):
    row = {"original": item.text, "english": item.text_en, "lang": item.lang, "lang_name": languages.name(item.lang),
           "url": item.url, "meta_lang": ""}
    row["flags"] = check_row(row)
    return row


def focus_info(focus, results):
    flagged = sum(1 for r in focus["rows"] if r["flags"])
    covered = sum(1 for r in results if (r.get("focus") or {}).get("items"))
    return {"name": focus["name"], "source": focus["source"], "found_via": focus["found_via"],
            "n_items": len(focus["items"]), "languages": dict(Counter(r["lang_name"] for r in focus["rows"])),
            "flagged": flagged, "topics_covered": covered, "topics_total": len(results)}


# ------------------------------------------------------------------- output
def _summary_line(r):
    s = r["summary"]
    langs = ", ".join(f"{k} {v}" for k, v in s["languages"].items())
    line = f"{s['items']} items ({langs}); {s['translated']} translated, {s['flagged']} flagged by the automatic checks"
    if s.get("verdicts"):
        line += "; model review: " + ", ".join(f"{v} {k}" for k, v in s["verdicts"].items())
    return line


def render_text(result):
    if not result["rows"]:
        return (f"Source: {result['source']}\nFound via: {result['found_via']}\n\n"
                "Nothing to translate. Try a different spelling, a feed URL (-j https://site/rss), or "
                "--lang fa (any language code) to ask Google News for pages in that language.")
    out = [f"Source: {result['source']}", f"Found via: {result['found_via']}", _summary_line(result), ""]
    for r in result["rows"]:
        out.append(f"{r['n']}. [{r['lang_name']}, {r['lang_how']}]")
        out.append(f"   original: {clip(r['original'], 200)}")
        if r["lang"] != "en":
            out.append(f"   English:  {clip(r['english'], 200) or '(none)'}")
        for flag in r["flags"]:
            out.append(f"   CHECK: {flag}")
        if r["verdict"]:
            out.append(f"   model review: {r['verdict']}" + (f" - {r['note']}" if r["note"] else ""))
    out += ["", f"Saved: {result.get('path', '')}"]
    return "\n".join(out)


def render_md(result):
    lines = [f"# Translation check: {result['source']}", "", f"Found via: {result['found_via']}.", "",
             _summary_line(result) if result["rows"] else "Nothing found.", ""]
    for r in result["rows"]:
        lines += [f"### {r['n']}. {r['lang_name']} ({r['lang_how']})", f"- Original: {r['original']}",
                  f"- English: {r['english'] or ('(same as original)' if r['lang'] == 'en' else '(none)')}"]
        lines += [f"- CHECK: {f}" for f in r["flags"]]
        if r["verdict"]:
            lines.append(f"- Model review: {r['verdict']}" + (f" - {r['note']}" if r["note"] else ""))
        lines.append("")
    return "\n".join(lines)


def render_html(result):
    body = []
    for r in result["rows"]:
        eng = r["english"] or ("(already English)" if r["lang"] == "en" else "(none)")
        marks = "".join(f"<div class='flag'>CHECK: {_e(f)}</div>" for f in r["flags"])
        if r["verdict"]:
            marks += f"<div>Model review: <strong>{_e(r['verdict'])}</strong> {_e(r['note'])}</div>"
        body.append(
            f"<tr><td>{_e(r['n'])}</td><td>{_e(r['lang_name'])}<br><span class='muted'>{_e(r['lang_how'])}</span></td>"
            f"<td dir='auto' lang='{_e(r['lang'])}'>{_link(r['original'], r['url'])}</td>"
            f"<td>{_e(eng)}</td><td>{marks}</td></tr>")
    table = ("<div class='scroll'><table><tr><th>#</th><th>Language</th><th>Original</th><th>English</th>"
             f"<th>Checks</th></tr>{''.join(body)}</table></div>") if body else "<p>Nothing found.</p>"
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>Translation check: {_e(result['source'])}</title><style>{CSS}.flag{{color:#b45309}}"
            "td{font-size:1rem}</style></head><body><main>"
            f"<h1>Translation check</h1><p><strong>{_e(result['source'])}</strong> "
            f"<span class='muted'>via {_e(result['found_via'])}</span></p>"
            f"<p class='muted'>{_e(_summary_line(result)) if result['rows'] else ''}</p>{table}</main></body></html>")
