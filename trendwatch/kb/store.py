"""JSONL storage: one file per kind, sorted and written atomically so git diffs stay small and readable."""
import hashlib
import json
import os
from datetime import date

from .schema import (CLAIMER_TYPES, ENTITY_TYPES, PREDICATES, STATUSES, KBError, check_choice, check_date,
                     check_leaning, entity_id, norm)


def _hash(*parts):
    return hashlib.sha1("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:12]


class KBStore:
    def __init__(self, root):
        """`root` is the data directory (the one the rest of the app uses); files live in <root>/kb/."""
        self.dir = os.path.join(root, "kb")
        self.entities, self.claims, self.observations = {}, {}, {}
        self._dirty = set()
        self.load()

    # ------------------------------------------------------------------ files
    def path(self, kind):
        return os.path.join(self.dir, f"{kind}.jsonl")

    def _read(self, kind):
        try:
            with open(self.path(kind), encoding="utf-8") as f:
                for n, line in enumerate(f, 1):
                    line = line.strip()
                    if line:
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError as e:
                            raise KBError(f"{self.path(kind)} line {n} is not valid JSON ({e}). Fix or remove that line.")
        except FileNotFoundError:
            return

    def load(self):
        self.entities = {e["id"]: e for e in self._read("entities")}
        self.claims = {c["id"]: c for c in self._read("claims")}
        self.observations = {self._obs_key(o): o for o in self._read("observations")}
        self._dirty = set()

    @staticmethod
    def _obs_key(o):
        return (o["entity"], o["topic"], o["date"])

    @property
    def dirty(self):
        return bool(self._dirty)

    def save(self):
        """Write only the files that changed, sorted, via a temporary file so a crash cannot corrupt them."""
        if not self._dirty:
            return
        os.makedirs(self.dir, exist_ok=True)
        data = {
            "entities": sorted(self.entities.values(), key=lambda e: e["id"]),
            "claims": sorted(self.claims.values(), key=lambda c: (c["subject"], c["predicate"], c["id"])),
            "observations": sorted(self.observations.values(), key=lambda o: (o["date"], o["entity"], o["topic"])),
        }
        for kind in sorted(self._dirty):
            tmp = self.path(kind) + ".tmp"
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                for row in data[kind]:
                    f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            os.replace(tmp, self.path(kind))
        self._dirty = set()

    # --------------------------------------------------------------- entities
    def upsert_entity(self, type_, name, aliases=(), country="", notes="", id_=None):
        """Create the entity, or enrich the existing one: aliases are added and blank fields filled, but values
        already there are never overwritten, so hand edits survive re-seeding. Returns (entity, created)."""
        check_choice(type_, ENTITY_TYPES, "entity type")
        name = str(name or "").strip()
        if not name:
            raise KBError("An entity needs a name.")
        eid = id_ or entity_id(type_, name)
        existing = self.entities.get(eid)
        clean = [a.strip() for a in aliases if a and a.strip() and norm(a) != norm(name)]
        if existing is None:
            entity = {"id": eid, "type": type_, "name": name, "aliases": sorted(set(clean), key=str.casefold),
                      "country": str(country or "").strip(), "notes": str(notes or "").strip(),
                      "added": date.today().isoformat()}
            self.entities[eid] = entity
            self._dirty.add("entities")
            return entity, True
        changed = False
        known = {norm(a) for a in existing["aliases"]} | {norm(existing["name"])}
        for alias in clean:
            if norm(alias) not in known:
                existing["aliases"].append(alias)
                known.add(norm(alias))
                changed = True
        for field, value in (("country", country), ("notes", notes)):
            if value and not existing.get(field):
                existing[field] = str(value).strip()
                changed = True
        if changed:
            existing["aliases"] = sorted(set(existing["aliases"]), key=str.casefold)
            self._dirty.add("entities")
        return existing, False

    def find_exact(self, text, type_=None):
        """Entities whose id, name or alias equals `text` (ignoring case, accents and punctuation)."""
        wanted = str(text or "").strip()
        if not wanted:
            return []
        if wanted.lower() in self.entities:
            hits = [self.entities[wanted.lower()]]
        else:
            key = norm(wanted)
            hits = [e for e in self.entities.values()
                    if key in {norm(e["name"]), *(norm(a) for a in e["aliases"])}]
        if type_:
            hits = [e for e in hits if e["type"] == type_]
        return sorted(hits, key=lambda e: e["id"])

    def resolve(self, text):
        """Exact matches first; otherwise entities where the text is part of a name or alias."""
        exact = self.find_exact(text)
        if exact:
            return exact
        key = norm(text)
        if len(key) < 3:
            return []
        part = [e for e in self.entities.values() if any(key in norm(n) for n in (e["name"], *e["aliases"]))]
        return sorted(part, key=lambda e: e["id"])

    def one(self, text, expect_type=None):
        """Resolve to exactly one entity, or explain why that is not possible."""
        found = self.resolve(text)
        if expect_type and any(e["type"] == expect_type for e in found):
            found = [e for e in found if e["type"] == expect_type]
        if not found:
            raise KBError(f"No entity matches {text!r}. Add it with: python kb.py add-entity <type> <name>")
        if len(found) > 1:
            options = ", ".join(f"{e['id']} ({e['name']})" for e in found[:8])
            raise KBError(f"{text!r} matches several entities: {options}. Use the exact id.")
        return found[0]

    # ----------------------------------------------------------------- claims
    def claims_of(self, entity_id_, direction="both"):
        out = []
        for c in self.claims.values():
            if direction in ("both", "out") and c["subject"] == entity_id_:
                out.append(c)
            elif direction in ("both", "in") and c.get("object_kind") == "entity" and c["object"] == entity_id_:
                out.append(c)
        return out

    def add_claim(self, subject, predicate, object_, *, status, asserted_by, source_url="", published="",
                  valid_from="", valid_to="", note="", added_by="user"):
        """Add a claim (subject and, for entity predicates, object are entity ids). Adding the same claim twice
        does nothing. Returns (claim, created)."""
        check_choice(predicate, tuple(PREDICATES), "predicate")
        check_choice(status, STATUSES, "status")
        asserted_by = " ".join(str(asserted_by or "").split())
        if not asserted_by:
            raise KBError("Every claim needs asserted_by: who says it (an outlet, a government, 'user', ...).")
        if subject not in self.entities:
            raise KBError(f"Unknown subject {subject!r}.")
        if PREDICATES[predicate] == "entity":
            if object_ not in self.entities:
                raise KBError(f"Unknown object {object_!r}; the predicate {predicate!r} links two entities.")
            kind = "entity"
        else:
            if not str(object_).strip():
                raise KBError(f"The predicate {predicate!r} needs a value.")
            if predicate == "leaning":
                check_leaning(object_)
            kind = "value"
        if subject == object_:
            raise KBError("A claim cannot link an entity to itself.")
        source_url = str(source_url or "").strip()
        if source_url and not source_url.startswith(("http://", "https://")):
            raise KBError(f"source_url must start with http:// or https:// (got {source_url!r}).")
        published, valid_from, valid_to = (check_date(published, "published"), check_date(valid_from, "valid_from"),
                                           check_date(valid_to, "valid_to"))
        if valid_from and valid_to and valid_to < valid_from:
            raise KBError("valid_to is before valid_from.")
        cid = "c_" + _hash(subject, predicate, object_, status, asserted_by.casefold(), source_url, valid_from)
        if cid in self.claims:
            return self.claims[cid], False
        claim = {"id": cid, "subject": subject, "predicate": predicate, "object": object_, "object_kind": kind,
                 "status": status, "asserted_by": asserted_by, "source_url": source_url, "published": published,
                 "valid_from": valid_from, "valid_to": valid_to, "note": str(note or "").strip(),
                 "added": date.today().isoformat(), "added_by": added_by}
        self.claims[cid] = claim
        self._dirty.add("claims")
        return claim, True

    def remove_claim(self, claim_id):
        if claim_id not in self.claims:
            raise KBError(f"No claim with id {claim_id!r}.")
        del self.claims[claim_id]
        self._dirty.add("claims")

    # ------------------------------------------------------------ observations
    def set_observation(self, entity, topic, topic_name, day, counts, evidence=()):
        """What an outlet or account said on a topic that day (counts per framing). Replaces the same day's
        entry, so re-running a day never double counts."""
        if entity not in self.entities:
            raise KBError(f"Unknown entity {entity!r}.")
        row = {"entity": entity, "topic": topic, "topic_name": topic_name, "date": check_date(day, "date"),
               "n_items": int(sum(counts.values())), "counts": dict(sorted(counts.items())),
               "evidence": list(evidence)[:2]}
        self.observations[self._obs_key(row)] = row
        self._dirty.add("observations")
        return row

    # --------------------------------------------------------------- integrity
    def check(self):
        """Problems worth fixing, as readable strings (an empty list means healthy)."""
        problems = []
        for e in self.entities.values():
            if e["type"] not in ENTITY_TYPES:
                problems.append(f"entity {e['id']}: unknown type {e['type']!r}")
        for c in self.claims.values():
            where = f"claim {c['id']}"
            if c["predicate"] not in PREDICATES:
                problems.append(f"{where}: unknown predicate {c['predicate']!r}")
            if c["status"] not in STATUSES:
                problems.append(f"{where}: unknown status {c['status']!r}")
            if c["subject"] not in self.entities:
                problems.append(f"{where}: subject {c['subject']!r} does not exist")
            if c.get("object_kind") == "entity" and c["object"] not in self.entities:
                problems.append(f"{where}: object {c['object']!r} does not exist")
            if not c.get("asserted_by"):
                problems.append(f"{where}: no asserted_by")
            if c.get("valid_from") and c.get("valid_to") and c["valid_to"] < c["valid_from"]:
                problems.append(f"{where}: valid_to is before valid_from")
        for o in self.observations.values():
            if o["entity"] not in self.entities:
                problems.append(f"observation {o['entity']}/{o['topic']}/{o['date']}: entity does not exist")
        return problems

    def claimer_ids(self):
        return [e["id"] for e in self.entities.values() if e["type"] in CLAIMER_TYPES]
