"""Stage 3: find framings, label items twice independently, and measure whether the divide is real."""
import random
from datetime import date

from . import prompts
from .util import clip, log


def _block(items, max_chars):
    lines = []
    for idx, it in enumerate(items):
        text = it.text.replace("\n", " ").replace("<", "‹").replace(">", "›")
        lines.append(f'<item i="{idx}" type="{it.kind}">{clip(text, max_chars)}</item>')
    return "\n".join(lines)


def get_framings(llm, topic, items, store, cfg):
    """Framings are frozen per topic so labels stay comparable across days. Edit the saved
    file by hand and your version is kept."""
    rel = f"topics/{topic['slug']}.json"
    saved = store.read(rel)
    if saved and len(saved.get("framings", [])) >= 2:
        return saved
    a = cfg["analysis"]
    sample = items[:40]
    data = llm.complete_json(prompts.SYSTEM,
                             prompts.propose_framings(topic["topic"], _block(sample, a["max_item_chars"])),
                             tier="smart", max_tokens=1500)
    framings = []
    for n, f in enumerate(data.get("framings", [])[:5], 1):
        if f.get("label"):
            framings.append({"id": f"f{n}", "label": f["label"], "description": f.get("description", "")})
    result = {
        "topic": topic["topic"],
        "has_distinct_framings": bool(data.get("has_distinct_framings")) and len(framings) >= 2,
        "framings": framings,
        "created": date.today().isoformat(),
        "history": (saved or {}).get("history", []),
    }
    store.write(rel, result)
    return result


def _label_pass(llm, topic_name, framings, items, a, seed, reverse):
    order = list(range(len(items)))
    if seed is not None:
        random.Random(seed).shuffle(order)
    shown = list(reversed(framings)) if reverse else framings
    allowed = {f["id"] for f in framings} | {"none", "unclear"}
    out = {}
    bs = a["batch_size"]
    for start in range(0, len(order), bs):
        batch = [items[i] for i in order[start:start + bs]]
        try:
            data = llm.complete_json(prompts.SYSTEM,
                                     prompts.label(topic_name, shown, _block(batch, a["max_item_chars"])),
                                     tier="fast", max_tokens=1500)
        except Exception as e:
            log.warning("labelling batch failed: %s", e)
            continue
        if isinstance(data, dict):
            data = data.get("labels", [])
        for row in data:
            try:
                j, lab = int(row["i"]), str(row["label"]).strip()
                if not 0 <= j < len(batch) or lab not in allowed:
                    continue
                try:
                    conf = float(row.get("confidence", 0.5))
                except (TypeError, ValueError):
                    conf = 0.5
                out[batch[j].id] = {"label": lab, "confidence": conf,
                                    "evidence": clip(str(row.get("evidence", "")), 160)}
            except (KeyError, ValueError, TypeError):
                continue
    for it in items:
        out.setdefault(it.id, {"label": "unclear", "confidence": 0.0, "evidence": ""})
    return out


def cohens_kappa(xs, ys):
    n = len(xs)
    if n == 0:
        return 0.0
    po = sum(x == y for x, y in zip(xs, ys)) / n
    cats = set(xs) | set(ys)
    pe = sum((xs.count(c) / n) * (ys.count(c) / n) for c in cats)
    if pe >= 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1 - pe)


def label_with_consensus(llm, topic_name, framings, items, cfg):
    """Two independent passes (different item order and framing order). An item keeps a label only
    if both passes agree; otherwise it is 'unclear'. Agreement is reported as Cohen's kappa."""
    a = cfg["analysis"]
    fr = framings["framings"]
    p1 = _label_pass(llm, topic_name, fr, items, a, seed=None, reverse=False)
    p2 = _label_pass(llm, topic_name, fr, items, a, seed=7, reverse=True)
    labels = {}
    for it in items:
        x, y = p1[it.id], p2[it.id]
        labels[it.id] = dict(x) if x["label"] == y["label"] else \
            {"label": "unclear", "confidence": 0.0, "evidence": ""}
    kappa = cohens_kappa([p1[i.id]["label"] for i in items], [p2[i.id]["label"] for i in items])
    return labels, kappa


def divide_report(labels, framings, kappa, cfg):
    a = cfg["analysis"]
    n = len(labels)
    ids = {f["id"] for f in framings["framings"]}
    counts = {f["id"]: 0 for f in framings["framings"]}
    for lab in labels.values():
        if lab["label"] in ids:
            counts[lab["label"]] += 1
    framed = sum(counts.values())
    framed_share = framed / n if n else 0.0
    shares = {k: (v / framed if framed else 0.0) for k, v in counts.items()}
    significant = [k for k, s in shares.items() if s >= a["min_framing_share"]]

    if kappa < a["min_kappa"]:
        verdict = "unreliable"      # the two passes disagree: any split may be imagined
    elif framed < a["min_framed_items"] or framed_share < a["min_framed_share"]:
        verdict = "weak"            # most items are neutral or unlabelled
    elif len(significant) >= 2:
        verdict = "strong"
    else:
        verdict = "one-sided"
    return {"verdict": verdict, "kappa": round(kappa, 2), "n_items": n, "n_framed": framed,
            "framed_share": round(framed_share, 2), "counts": counts,
            "shares": {k: round(v, 2) for k, v in shares.items()}}
