"""Observations: what each outlet or account said about a topic on a given day, from the labelling step."""
from collections import Counter


def record_observations(kb, day, slug, topic_name, items, labels, framings):
    """Aggregate the day's labels per outlet/account for one topic and store them (one row per entity, topic and
    day, replaced on re-runs). Returns how many observations were stored."""
    names = {f["id"]: f["label"] for f in framings["framings"]}
    per_entity = {}
    for it in items:
        lab = labels.get(it.id)
        if not lab or lab["label"] == "unclear":
            continue
        if it.kind == "article":
            type_, name, aliases = "outlet", it.outlet, ([it.domain] if it.domain else [])
        else:
            type_, name, aliases = "account", f"{it.platform}:{it.outlet}", []
        found = kb.find_exact(name, type_)
        entity = found[0] if found else kb.upsert_entity(type_, name, aliases)[0]
        slot = per_entity.setdefault(entity["id"], {"counts": Counter(), "evidence": []})
        label = names.get(lab["label"], lab["label"])
        slot["counts"][label] += 1
        if label != "none" and lab.get("evidence") and len(slot["evidence"]) < 2:
            slot["evidence"].append({"framing": label, "quote": lab["evidence"], "url": it.url})
    for entity_id, slot in per_entity.items():
        kb.set_observation(entity_id, slug, topic_name, day, dict(slot["counts"]), slot["evidence"])
    return len(per_entity)
