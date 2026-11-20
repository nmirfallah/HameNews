"""Seed the knowledge base from what the project already knows. Seeding is idempotent and additive: it never
overwrites an edit, and everything it writes is marked with where it came from (added_by "seed:...") and a
status that says how much to trust it. The agency list was written from memory and a table you supplied, so
its claims are "reported" and should be verified against a primary source before being relied on."""
import json
import os

from .. import agencies
from ..leanings import _entry, clean
from ..util import log
from .schema import norm
from .store import KBStore

SEED_AGENCY = "HameNews agency list"
STATE_ALIASES = {
    "United States": ["USA", "US", "United States of America"], "United Kingdom": ["UK", "Britain", "Great Britain"],
    "Russia": ["Russian Federation"], "Iran": ["Islamic Republic of Iran"], "South Korea": ["Republic of Korea"],
    "North Korea": ["DPRK"], "Czech Republic": ["Czechia"], "United Arab Emirates": ["UAE"],
    "China": ["PRC", "People's Republic of China"], "Turkey": ["Türkiye", "Turkiye"],
}
KIND_NOTE = {
    "state": "Described as state-run, state-owned or state-affiliated in the agency list; the exact relation is not "
             "specified. Verify against a primary source.",
    "public": "Described as a public or publicly funded agency in the agency list. Verify against a primary source.",
}
# Agency entries that hold several distinct outlets: outlet -> words that identify its names and domains.
SPLITS = {
    "Iran": {"IRNA": ["irna", "islamic republic news"], "Tasnim News Agency": ["tasnim"], "Fars News Agency": ["fars"]},
    "Qatar": {"Qatar News Agency": ["qatar news", "qna"], "Al Jazeera": ["jazeera", "الجزيرة"]},
    "Russia": {"TASS": ["tass"], "RT": ["rt", "russia today"]},
    "United Kingdom": {"Reuters": ["reuters"], "PA Media": ["pa media", "press association", "pa.media"]},
}


def _name_has(keyword, name):
    return f" {norm(keyword)} " in f" {norm(name)} "


def outlets_for(entry):
    """The outlets inside one agency-list entry: name, aliases (including domains) and domains."""
    country, _, names, domains = entry
    spec = SPLITS.get(country)
    if not spec:
        return [{"name": names[0], "aliases": list(names[1:]) + list(domains), "domains": list(domains)}]
    outlets = {name: {"name": name, "aliases": [], "domains": []} for name in spec}
    first = next(iter(spec))
    for n in names:
        owner = next((o for o, words in spec.items() if any(_name_has(w, n) for w in words)), first)
        outlets[owner]["aliases"].append(n)
    for d in domains:
        owner = next((o for o, words in spec.items()
                      if any(w in d or norm(w).replace(" ", "") in d for w in words)), first)
        outlets[owner]["domains"].append(d)
        outlets[owner]["aliases"].append(d)
    return list(outlets.values())


def seed_agencies(kb):
    for entry in agencies.AGENCIES:
        country, kind = entry[0], entry[1]
        state, _ = kb.upsert_entity("state", country, STATE_ALIASES.get(country, []), country=country)
        for o in outlets_for(entry):
            outlet, _ = kb.upsert_entity("outlet", o["name"], o["aliases"], country=country)
            kb.add_claim(outlet["id"], "based_in", state["id"], status="reported", asserted_by=SEED_AGENCY,
                         added_by="seed:agencies")
            predicate = {"state": "state_linked", "public": "publicly_funded_by"}.get(kind)
            if predicate:
                kb.add_claim(outlet["id"], predicate, state["id"], status="reported", asserted_by=SEED_AGENCY,
                             note=KIND_NOTE[kind], added_by="seed:agencies")


def seed_config(kb, cfg):
    """Single outlets named in the config's outlet_groups (a group named after its first name, such as The Grayzone)."""
    derived = set(agencies.outlet_groups())
    for group, names in (cfg.get("outlet_groups") or {}).items():
        if group not in derived and names and norm(group) == norm(names[0]):
            kb.upsert_entity("outlet", names[0], names[1:])


def _leaning_sources(root, cfg):
    path = os.path.join(root, "outlet_leanings.json")
    cache = {}
    try:
        with open(path, encoding="utf-8") as f:
            cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    found = {name: _entry(value, "user") for name, value in cache.items()}
    found.update({str(k): _entry(v, "config") for k, v in (cfg.get("outlet_leanings") or {}).items()})
    return found


def seed_leanings(kb, root, cfg):
    asserted = {"AI estimate": "HameNews AI estimate", "config": "user (config.yaml)"}
    for name, (leaning, source) in _leaning_sources(root, cfg).items():
        if not leaning:
            continue
        hits = kb.find_exact(name, "outlet")
        if len(hits) > 1:
            log.warning("leaning for %r skipped: it matches several outlets", name)
            continue
        outlet = hits[0] if hits else kb.upsert_entity("outlet", name)[0]
        kb.add_claim(outlet["id"], "leaning", leaning, status="inferred" if source == "AI estimate" else "reported",
                     asserted_by=asserted.get(source, "user (outlet_leanings.json)"), added_by="seed:leanings")


def seed_all(root, cfg):
    """Run every seed and save if anything changed. Returns how many entities and claims were added."""
    kb = KBStore(root)
    before = (len(kb.entities), len(kb.claims))
    seed_agencies(kb)
    seed_config(kb, cfg)
    seed_leanings(kb, root, cfg)
    if kb.dirty:
        kb.save()
    return {"entities_added": len(kb.entities) - before[0], "claims_added": len(kb.claims) - before[1]}
