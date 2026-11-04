"""'According to X, ... According to Y, ...': one neutral narrative per source group."""
from collections import OrderedDict, defaultdict

from . import prompts
from .util import clip, log


def _sample(items, limit):
    """Pick up to `limit` items, rotating through outlets so one outlet cannot dominate."""
    by_outlet = OrderedDict()
    for it in items:
        by_outlet.setdefault(it.outlet, []).append(it)
    out = []
    while len(out) < limit and any(by_outlet.values()):
        for k in list(by_outlet):
            if by_outlet[k]:
                out.append(by_outlet[k].pop(0))
                if len(out) >= limit:
                    break
    return out


def build(llm, topic_name, items, cfg):
    n = cfg["narratives"]
    if not n["enabled"] or len(items) < n["min_total_items"]:
        return None
    groups = defaultdict(list)
    for it in items:
        groups[it.group or "Unknown"].append(it)
    unclassified = len(groups.pop("Unknown", []))
    eligible = sorted(((g, its) for g, its in groups.items() if len(its) >= n["min_group_items"]),
                      key=lambda kv: -len(kv[1]))[: n["max_groups"]]
    if not eligible:
        return {"groups": [], "differences": "", "unclassified": unclassified}

    refs, blocks = [], []
    for g, its in eligible:
        sample = _sample(its, n["max_items_per_group"])
        outlets = ", ".join(sorted({i.outlet for i in its}))
        lines = [f'<group name="{g}" items="{len(its)}" outlets="{clip(outlets, 200)}">']
        for it in sample:
            text = it.text.replace("\n", " ").replace("<", "‹").replace(">", "›")
            lines.append(f'<item i="{len(refs)}" outlet="{it.outlet}">{clip(text, 300)}</item>')
            refs.append(it)
        lines.append("</group>")
        blocks.append("\n".join(lines))

    try:
        data = llm.complete_json(prompts.SYSTEM,
                                 prompts.group_narratives(topic_name, "\n".join(blocks)),
                                 tier="smart", max_tokens=3000)
    except Exception as e:
        log.warning("narratives failed: %s", e)
        return None

    sizes = {g: len(its) for g, its in eligible}
    outlet_lists = {g: sorted({i.outlet for i in its}) for g, its in eligible}
    out = []
    for row in (data.get("groups", []) if isinstance(data, dict) else []):
        g = row.get("group")
        if g not in sizes or not row.get("narrative"):
            continue
        links, seen = [], set()
        for idx in row.get("item_ids", []):
            if isinstance(idx, int) and 0 <= idx < len(refs) and refs[idx].url and idx not in seen:
                seen.add(idx)
                links.append({"outlet": refs[idx].outlet, "url": refs[idx].url})
        out.append({"group": g, "n_items": sizes[g], "outlets": outlet_lists[g][:8],
                    "narrative": str(row["narrative"]).strip(), "links": links[:3]})
    out.sort(key=lambda r: -r["n_items"])
    return {"groups": out, "unclassified": unclassified,
            "differences": str(data.get("differences", "")).strip() if isinstance(data, dict) else ""}
