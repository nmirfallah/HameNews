"""Running per-outlet and per-account profiles, accumulated across days (stored as JSON)."""
from .util import short_hash

FILES = {"article": "profiles/outlets.json", "post": "profiles/accounts.json"}


def key_for(item):
    return item.outlet if item.kind == "article" else f"{item.platform}:{item.outlet}"


def update(store, slug, items, labels):
    data = {k: store.read(f, {}) for k, f in FILES.items()}
    for it in items:
        lab = labels.get(it.id)
        if not lab or lab["label"] == "unclear":
            continue
        entry = data[it.kind].setdefault(key_for(it), {"topics": {}})
        t = entry["topics"].setdefault(slug, {"counts": {}, "seen": [], "evidence": []})
        h = short_hash(it.id)
        if h in t["seen"]:          # never double-count an item across days
            continue
        t["seen"].append(h)
        t["counts"][lab["label"]] = t["counts"].get(lab["label"], 0) + 1
        if lab["label"] != "none" and lab.get("evidence") and len(t["evidence"]) < 5:
            t["evidence"].append({"framing": lab["label"], "quote": lab["evidence"], "url": it.url})
    for k, f in FILES.items():
        store.write(f, data[k])


def summarize(counts, framings, min_items, lean_threshold):
    names = {f["id"]: f["label"] for f in framings}
    n = sum(counts.values())
    framed = {k: v for k, v in counts.items() if k != "none"}
    nf = sum(framed.values())
    if n < min_items:
        return {"n": n, "label": "insufficient data", "confidence": "-"}
    if nf < 3:
        return {"n": n, "label": "no clear framing (mostly neutral)", "confidence": "low"}
    ranked = sorted(framed.items(), key=lambda kv: -kv[1])
    top, cnt = ranked[0]
    share = cnt / nf
    if share >= lean_threshold:
        label = f"leans: {names.get(top, top)} ({share:.0%} of framed)"
    else:
        label = "mixed: " + " / ".join(names.get(k, k) for k, _ in ranked[:2])
    conf = "high" if n >= 4 * min_items and share >= 0.8 else "medium" if n >= 2 * min_items else "low"
    return {"n": n, "label": label, "confidence": conf}


def rows(store, slug, framings, cfg, limit=15):
    a = cfg["analysis"]
    refs = {k.lower(): v for k, v in (store.read("known_ratings.json", {}) or {}).items()}
    out = {}
    for kind, min_items in (("article", a["min_items_outlet"]), ("post", a["min_items_account"])):
        lst = []
        for name, entry in store.read(FILES[kind], {}).items():
            t = entry["topics"].get(slug)
            if not t:
                continue
            s = summarize(t["counts"], framings["framings"], min_items, a["lean_threshold"])
            s.update({"name": name, "reference": refs.get(name.lower(), ""),
                      "evidence": t["evidence"][:2]})
            lst.append(s)
        out["outlets" if kind == "article" else "accounts"] = sorted(lst, key=lambda r: -r["n"])[:limit]
    return out
