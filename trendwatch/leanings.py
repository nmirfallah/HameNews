"""Political leaning of news outlets.

Order of precedence: your ratings in config.yaml (outlet_leanings), then data/outlet_leanings.json
(hand-editable; values may be plain strings), then an AI estimate that is cached there and always
labelled "AI estimate". The estimate is the outlet's usual editorial line, not a judgment on any story.
"""
from . import prompts
from .util import log

FILE = "outlet_leanings.json"
LEANINGS = ("left", "center-left", "center", "center-right", "right")
BUCKET = {"left": "left-leaning", "center-left": "left-leaning", "center": "centrist",
          "center-right": "right-leaning", "right": "right-leaning"}
_ALIASES = {"lean-left": "center-left", "lean-right": "center-right", "centre": "center",
            "centre-left": "center-left", "centre-right": "center-right", "centrist": "center"}


def clean(value):
    v = str(value or "").strip().lower().replace(" ", "-").replace("_", "-")
    v = _ALIASES.get(v, v)
    return v if v in LEANINGS else ""


def _entry(value, default_source):
    if isinstance(value, dict):
        return clean(value.get("leaning")), value.get("source") or default_source
    return clean(value), default_source


def assign_leanings(llm, items, store, cfg):
    lc = cfg.get("leanings", {})
    if not lc.get("enabled", True):
        return
    overrides = {str(k).lower(): _entry(v, "config") for k, v in (cfg.get("outlet_leanings") or {}).items()}
    cache = store.read(FILE, {}) or {}
    known = {k.lower() for k in cache} | set(overrides)
    need = sorted({i.outlet for i in items if i.kind == "article" and i.outlet.lower() not in known})

    changed = False
    for start in range(0, len(need), 40):
        chunk = need[start:start + 40]
        try:
            data = llm.complete_json(prompts.SYSTEM, prompts.classify_leanings(chunk),
                                     tier="fast", max_tokens=2500)
        except Exception as e:      # a failed call is not cached, so it is retried next run
            log.warning("leaning classification failed: %s", e)
            continue
        if isinstance(data, dict):
            data = data.get("outlets", [])
        answers = {}
        for row in data:
            if isinstance(row, dict) and row.get("outlet") in chunk:
                answers[row["outlet"]] = clean(row.get("leaning")) or "unknown"
        for name in chunk:
            cache[name] = {"leaning": answers.get(name, "unknown"), "source": "AI estimate"}
        changed = True
    if changed:
        store.write(FILE, dict(sorted(cache.items())))

    lookup = {k.lower(): _entry(v, "user") for k, v in cache.items()}
    lookup.update(overrides)                       # config beats the cache
    for it in items:
        if it.kind != "article":
            continue
        leaning, source = lookup.get(it.outlet.lower(), ("", ""))
        it.leaning, it.leaning_source = (leaning, source) if leaning else ("", "")
