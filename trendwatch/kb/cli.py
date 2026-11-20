"""The `python kb.py` command: look things up, add sourced claims, and check the data."""
import argparse
import os
import sys

from ..config import build_config
from .index import KBIndex
from .schema import DEFAULT_INCLUDE, ENTITY_TYPES, PREDICATES, STATUSES, KBError
from .seed import seed_all
from .store import KBStore


def _name(kb, eid):
    e = kb.entities.get(eid)
    return e["name"] if e else str(eid)


def fmt_claim(kb, c, perspective=None):
    """One readable line for a claim. `perspective` is the entity being shown, so claims about it read naturally."""
    obj = _name(kb, c["object"]) if c.get("object_kind") == "entity" else c["object"]
    if perspective and c["subject"] != perspective:
        text = f"{_name(kb, c['subject'])} {c['predicate']} {_name(kb, perspective)}"
    else:
        text = f"{c['predicate']} {obj}"
    text += f"  [{c['status']}]  said by {c['asserted_by']}"
    if c.get("published"):
        text += f", {c['published']}"
    if c.get("valid_from") or c.get("valid_to"):
        text += f"  (valid {c.get('valid_from') or '...'} to {c.get('valid_to') or 'now'})"
    if c.get("source_url"):
        text += f"\n      source: {c['source_url']}"
    if c.get("note"):
        text += f"\n      note: {c['note']}"
    return text


def fmt_path(kb, path):
    parts = []
    for s in path:
        parts.append(f"{_name(kb, s['subject'])} --{s['predicate']}--> {_name(kb, s['object'])} [{s['status']}]")
    return "  |  ".join(parts)


def _include(args):
    inc = list(DEFAULT_INCLUDE)
    if getattr(args, "include_alleged", False):
        inc.append("alleged")
    if getattr(args, "include_inferred", False):
        inc.append("inferred")
    return tuple(inc)


def cmd_show(kb, ix, args):
    e = kb.one(args.name)
    p = ix.profile(e["id"])
    lines = [f"{e['name']}  ({e['type']}, id {e['id']})"]
    if e["aliases"]:
        lines.append(f"Also known as: {', '.join(e['aliases'])}")
    if e.get("country"):
        lines.append(f"Country: {e['country']}")
    if e.get("notes"):
        lines.append(f"Notes: {e['notes']}")
    lines += ["", "Claims about it:"] + ([f"  - {fmt_claim(kb, c)}" for c in p["out"]] or ["  (none)"])
    if p["in"]:
        lines += ["", "Claims that point to it:"] + [f"  - {fmt_claim(kb, c, e['id'])}" for c in p["in"]]
    if p["disputes"]:
        lines += ["", "Disputed (a denial exists next to another claim; neither is treated as the truth):"]
        for d in p["disputes"]:
            lines.append(f"  - {_name(kb, d['subject'])} {d['predicate']} {_name(kb, d['object'])}: "
                         + ", ".join(f"{c['status']} (by {c['asserted_by']})" for c in d["claims"]))
    o = p["observations"]
    if o["items"]:
        lines += ["", f"Observed on {o['topics']} topic(s) over {o['days']} day(s), {o['items']} labelled items. "
                      "Framings seen: " + ", ".join(f"{k} {v}" for k, v in o["framings"].items())]
    return "\n".join(lines)


def cmd_connections(kb, ix, args):
    e = kb.one(args.name)
    rows = ix.connections(e["id"], args.hops, _include(args))
    if not rows:
        return f"No connections found for {e['name']} (statuses followed: {', '.join(_include(args))})."
    out = [f"Connections of {e['name']} within {args.hops} hop(s), following: {', '.join(_include(args))}", ""]
    for r in rows:
        out.append(f"{r['name']} ({r['type']})  {r['hops']} hop(s), weakest link: {r['weakest']}\n    {fmt_path(kb, r['path'])}")
    return "\n".join(out)


def cmd_tied_to(kb, ix, args):
    e = kb.one(args.name)
    rows = ix.tied_to(e["id"], args.hops, _include(args))
    if not rows:
        return f"Nothing is tied to {e['name']} by the claims followed ({', '.join(_include(args))})."
    out = [f"Outlets and accounts tied to {e['name']} within {args.hops} hop(s), following: {', '.join(_include(args))}", ""]
    for r in rows:
        out.append(f"{r['name']} ({r['type']})  {r['hops']} hop(s), weakest link: {r['weakest']}\n    {fmt_path(kb, r['path'])}")
    return "\n".join(out)


def cmd_disputed(kb, ix, args):
    rows = ix.disputed()
    if not rows:
        return "No disputed claims."
    out = []
    for d in rows:
        out.append(f"{_name(kb, d['subject'])} {d['predicate']} {_name(kb, d['object'])}")
        out += [f"  - [{c['status']}] said by {c['asserted_by']}" + (f"  {c['source_url']}" if c["source_url"] else "")
                for c in d["claims"]]
    return "\n".join(out)


def cmd_search(kb, ix, args):
    found = kb.resolve(args.text)
    return "\n".join(f"{e['id']}  {e['name']}  ({e['type']})" for e in found) or f"Nothing matches {args.text!r}."


def cmd_stats(kb, ix, args):
    s = ix.stats()
    fmt = lambda d: ", ".join(f"{k} {v}" for k, v in d.items()) or "none"
    return (f"Entities: {fmt(s['entities'])}\nClaims by status: {fmt(s['claims_by_status'])}\n"
            f"Claims by predicate: {fmt(s['claims_by_predicate'])}\nObservations: {s['observations']}")


def cmd_sql(kb, ix, args):
    columns, rows = ix.sql(args.query, args.limit)
    lines = [" | ".join(columns)] + [" | ".join("" if v is None else str(v) for v in r) for r in rows]
    return "\n".join(lines) + f"\n({len(rows)} row(s))"


def cmd_check(kb, ix, args):
    problems = kb.check()
    if problems:
        raise KBError("The knowledge base has problems:\n  - " + "\n  - ".join(problems))
    return f"Knowledge base is consistent: {len(kb.entities)} entities, {len(kb.claims)} claims, {len(kb.observations)} observations."


# ---- commands that change data (these save)
def cmd_add_entity(kb, ix, args):
    e, created = kb.upsert_entity(args.type, args.name, args.alias or [], args.country or "", args.notes or "")
    kb.save()
    return f"{'Added' if created else 'Updated'} {e['id']}."


def cmd_add_claim(kb, ix, args):
    subject = kb.one(args.subject)
    if PREDICATES.get(args.predicate) == "entity":
        object_ = kb.one(args.object)["id"]
    else:
        object_ = args.object
    claim, created = kb.add_claim(subject["id"], args.predicate, object_, status=args.status, asserted_by=args.by,
                                  source_url=args.source or "", published=args.published or "",
                                  valid_from=args.valid_from or "", valid_to=args.valid_to or "", note=args.note or "")
    kb.save()
    return f"{'Added' if created else 'Already present:'} claim {claim['id']}: {fmt_claim(kb, claim)}"


def cmd_remove_claim(kb, ix, args):
    kb.remove_claim(args.claim_id)
    kb.save()
    return f"Removed {args.claim_id}."


def cmd_seed(kb, ix, args):
    summary = seed_all(args.data_dir, build_config({}))
    return f"Seeded: {summary['entities_added']} entities and {summary['claims_added']} claims added."


def build_parser():
    ap = argparse.ArgumentParser(prog="kb.py", description="HameNews knowledge base: who is connected to whom, with sources.")
    ap.add_argument("--data-dir", default="data", help="the data folder (default: data)")
    sub = ap.add_subparsers(dest="command", required=True)

    def add(name, fn, help_):
        p = sub.add_parser(name, help=help_)
        p.set_defaults(fn=fn)
        return p

    add("seed", cmd_seed, "load the agency list, outlet leanings and config into the knowledge base (safe to repeat)")
    add("stats", cmd_stats, "how much is stored")
    add("check", cmd_check, "validate the data (dangling links, bad statuses, ...)")
    add("disputed", cmd_disputed, "claims that have a denial next to them")
    p = add("search", cmd_search, "find entities by name, alias or part of a name")
    p.add_argument("text")
    p = add("show", cmd_show, "everything about one entity")
    p.add_argument("name")
    for name, fn, help_ in (("connections", cmd_connections, "entities linked to this one, up to N hops"),
                            ("tied-to", cmd_tied_to, "outlets and accounts whose chain of ties leads to this entity")):
        p = add(name, fn, help_)
        p.add_argument("name")
        p.add_argument("--hops", type=int, default=2)
        p.add_argument("--include-alleged", action="store_true", help="also follow alleged claims")
        p.add_argument("--include-inferred", action="store_true", help="also follow inferred (behavioural) claims")
    p = add("sql", cmd_sql, "run a read-only SELECT (tables: entities, aliases, claims, observations, view v_claims)")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=200)
    p = add("add-entity", cmd_add_entity, "add or enrich an entity")
    p.add_argument("type", choices=ENTITY_TYPES)
    p.add_argument("name")
    p.add_argument("--alias", action="append")
    p.add_argument("--country")
    p.add_argument("--notes")
    p = add("add-claim", cmd_add_claim, "add a sourced claim: SUBJECT PREDICATE OBJECT")
    p.add_argument("subject")
    p.add_argument("predicate", choices=list(PREDICATES))
    p.add_argument("object", help="an entity (name or id), or a value for 'leaning'")
    p.add_argument("--status", required=True, choices=STATUSES)
    p.add_argument("--by", required=True, help="who asserts it (an outlet, a government, 'user', ...)")
    p.add_argument("--source", help="URL of the source")
    p.add_argument("--published", help="publication date, YYYY-MM-DD")
    p.add_argument("--valid-from", dest="valid_from")
    p.add_argument("--valid-to", dest="valid_to")
    p.add_argument("--note")
    p = add("remove-claim", cmd_remove_claim, "remove a claim by id")
    p.add_argument("claim_id")
    return ap


def execute(argv):
    args = build_parser().parse_args(argv)
    kb = KBStore(args.data_dir)
    return args.fn(kb, KBIndex(kb), args)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        print(execute(argv))
    except KBError as e:
        sys.exit(f"Error: {e}")
