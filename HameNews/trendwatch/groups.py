"""Assign every item to a perspective group.

Articles: by the country/region the outlet is based in (cached in data/outlet_groups.json,
which you can edit by hand; your edits are never overwritten). Posts: by platform.
"""
from . import prompts
from .util import log

FILE = "outlet_groups.json"
POST_GROUPS = {"bluesky": "Bluesky posts", "mastodon": "Mastodon posts",
               "hackernews": "Hacker News comments"}


def assign_groups(llm, items, store):
    cache = store.read(FILE, {}) or {}
    known = {k.lower() for k in cache}
    need = sorted({i.outlet for i in items
                   if i.kind == "article" and not i.group and i.outlet.lower() not in known})
    changed = False
    for start in range(0, len(need), 40):
        chunk = need[start:start + 40]
        try:
            data = llm.complete_json(prompts.SYSTEM, prompts.classify_outlets(chunk),
                                     tier="fast", max_tokens=2500)
        except Exception as e:      # do not cache "Unknown" when the call itself failed
            log.warning("outlet classification failed: %s", e)
            continue
        if isinstance(data, dict):
            data = data.get("outlets", [])
        for row in data:
            name, grp = row.get("outlet"), str(row.get("group") or "").strip()
            if name in chunk and grp:
                cache[name] = grp
        for name in chunk:
            cache.setdefault(name, "Unknown")
        changed = True
    if changed:
        store.write(FILE, dict(sorted(cache.items())))

    lower = {k.lower(): v for k, v in cache.items()}
    for it in items:
        if it.group:
            continue
        if it.kind == "article":
            it.group = lower.get(it.outlet.lower(), "Unknown")
        else:
            it.group = POST_GROUPS.get(it.platform, it.platform)
