"""SQLite query index, built in memory from the JSONL files. Nothing is stored here: it is rebuilt on demand, so
the JSONL files stay the single source of truth (and DuckDB or another engine could replace this module)."""
import json
import re
import sqlite3
from collections import Counter, defaultdict

from .schema import DEFAULT_INCLUDE, STATUS_RANK, TIE_PREDICATES, KBError

SCHEMA = """
CREATE TABLE entities (id TEXT PRIMARY KEY, type TEXT, name TEXT, country TEXT, notes TEXT, added TEXT);
CREATE TABLE aliases (alias TEXT, entity TEXT);
CREATE TABLE claims (id TEXT PRIMARY KEY, subject TEXT, predicate TEXT, object TEXT, object_kind TEXT,
                     status TEXT, asserted_by TEXT, source_url TEXT, published TEXT, valid_from TEXT,
                     valid_to TEXT, note TEXT, added TEXT, added_by TEXT);
CREATE TABLE observations (entity TEXT, topic TEXT, topic_name TEXT, date TEXT, n_items INTEGER,
                           counts TEXT, evidence TEXT);
CREATE INDEX claims_subject ON claims(subject);
CREATE INDEX claims_object ON claims(object);
CREATE INDEX obs_entity ON observations(entity);
CREATE VIEW v_claims AS
  SELECT c.*, s.name AS subject_name, s.type AS subject_type,
         CASE WHEN c.object_kind = 'entity' THEN o.name ELSE c.object END AS object_name
  FROM claims c JOIN entities s ON s.id = c.subject
  LEFT JOIN entities o ON o.id = c.object AND c.object_kind = 'entity';
"""
_FORBIDDEN = re.compile(r"\b(attach|detach|pragma|load_extension|insert|update|delete|drop|alter|create|replace)\b", re.I)


class KBIndex:
    def __init__(self, kb):
        self.kb = kb
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        for e in kb.entities.values():
            self.conn.execute("INSERT INTO entities VALUES (?,?,?,?,?,?)",
                              (e["id"], e["type"], e["name"], e.get("country", ""), e.get("notes", ""), e.get("added", "")))
            for alias in [e["name"], *e["aliases"]]:
                self.conn.execute("INSERT INTO aliases VALUES (?,?)", (alias, e["id"]))
        for c in kb.claims.values():
            self.conn.execute("INSERT INTO claims VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", tuple(
                c.get(k, "") for k in ("id", "subject", "predicate", "object", "object_kind", "status", "asserted_by",
                                        "source_url", "published", "valid_from", "valid_to", "note", "added", "added_by")))
        for o in kb.observations.values():
            self.conn.execute("INSERT INTO observations VALUES (?,?,?,?,?,?,?)",
                              (o["entity"], o["topic"], o.get("topic_name", ""), o["date"], o["n_items"],
                               json.dumps(o["counts"], ensure_ascii=False), json.dumps(o.get("evidence", []), ensure_ascii=False)))
        self.conn.commit()
        self.conn.execute("PRAGMA query_only = ON")

    # ---------------------------------------------------------------- helpers
    def _name(self, eid):
        e = self.kb.entities.get(eid)
        return e["name"] if e else eid

    def _step(self, claim, walk_from, walk_to, direction):
        return {"claim_id": claim["id"], "subject": claim["subject"], "object": claim["object"],
                "predicate": claim["predicate"], "status": claim["status"], "asserted_by": claim["asserted_by"],
                "source_url": claim["source_url"], "walk_from": walk_from, "walk_to": walk_to, "direction": direction}

    def _edges(self, include, predicates=None):
        rows = self.conn.execute(
            "SELECT * FROM claims WHERE object_kind = 'entity' ORDER BY id").fetchall()
        # a denial is a counter-claim, never a link: it is excluded even if the caller lists it
        return [dict(r) for r in rows if r["status"] in include and r["status"] != "denied"
                and (predicates is None or r["predicate"] in predicates)]

    @staticmethod
    def _search(start, adjacency, hops):
        """Level-by-level search keeping, for each reachable entity, a shortest path and, among equally short
        paths, the one whose weakest link is strongest."""
        best = {start: {"hops": 0, "path": [], "rank": -1}}
        frontier = [start]
        for depth in range(1, hops + 1):
            candidates = {}
            for node in sorted(frontier):
                for nxt, step in adjacency.get(node, ()):
                    if nxt in best:
                        continue
                    rank = max(best[node]["rank"], STATUS_RANK[step["status"]])
                    current = candidates.get(nxt)
                    if current is None or rank < current["rank"]:
                        candidates[nxt] = {"hops": depth, "path": best[node]["path"] + [step], "rank": rank}
            best.update(candidates)
            frontier = list(candidates)
            if not frontier:
                break
        best.pop(start)
        return best

    def _results(self, found, types=None):
        out = []
        for eid, info in found.items():
            e = self.kb.entities[eid]
            if types and e["type"] not in types:
                continue
            weakest = max((s["status"] for s in info["path"]), key=lambda s: STATUS_RANK[s])
            out.append({"entity": eid, "name": e["name"], "type": e["type"], "hops": info["hops"],
                        "weakest": weakest, "path": info["path"]})
        return sorted(out, key=lambda r: (r["hops"], STATUS_RANK[r["weakest"]], r["name"].casefold()))

    # ---------------------------------------------------------------- queries
    def claims_about(self, entity_id, direction="both"):
        """Claims where the entity is the subject ('out') or the object ('in'), strongest first."""
        rows = []
        for c in self.kb.claims_of(entity_id, direction):
            rows.append(dict(c, direction="out" if c["subject"] == entity_id else "in"))
        return sorted(rows, key=lambda c: (c["direction"], c["predicate"], STATUS_RANK[c["status"]], c["id"]))

    def connections(self, entity_id, hops=1, include=DEFAULT_INCLUDE, direction="both", predicates=None):
        """Entities reachable within `hops` links, each with its path and the weakest status along it."""
        if entity_id not in self.kb.entities:
            raise KBError(f"Unknown entity {entity_id!r}.")
        adjacency = defaultdict(list)
        for c in self._edges(include, predicates):
            if direction in ("both", "out"):
                adjacency[c["subject"]].append((c["object"], self._step(c, c["subject"], c["object"], "out")))
            if direction in ("both", "in"):
                adjacency[c["object"]].append((c["subject"], self._step(c, c["object"], c["subject"], "in")))
        return self._results(self._search(entity_id, adjacency, hops))

    def tied_to(self, target_id, hops=2, include=DEFAULT_INCLUDE, predicates=TIE_PREDICATES, types=("outlet", "account")):
        """Everything with a chain of tie claims leading to the target (an outlet owned by a company that is
        owned by a state is tied to that state at two hops). Each result's path runs entity -> ... -> target."""
        if target_id not in self.kb.entities:
            raise KBError(f"Unknown entity {target_id!r}.")
        adjacency = defaultdict(list)
        for c in self._edges(include, predicates):
            adjacency[c["object"]].append((c["subject"], self._step(c, c["object"], c["subject"], "in")))
        results = self._results(self._search(target_id, adjacency, hops), types)
        for r in results:
            r["path"] = list(reversed(r["path"]))      # present as entity -> ... -> target
        return results

    def disputed(self):
        """Triples (subject, predicate, object) that have a denial next to at least one other claim."""
        groups = defaultdict(list)
        for c in self.kb.claims.values():
            groups[(c["subject"], c["predicate"], c["object"])].append(c)
        out = []
        for key, claims in sorted(groups.items()):
            statuses = {c["status"] for c in claims}
            if "denied" in statuses and statuses - {"denied"}:
                out.append({"subject": key[0], "predicate": key[1], "object": key[2],
                            "claims": sorted(claims, key=lambda c: (STATUS_RANK[c["status"]], c["id"]))})
        return out

    def observations_for(self, entity_id):
        rows = self.conn.execute("SELECT * FROM observations WHERE entity = ? ORDER BY date, topic", (entity_id,)).fetchall()
        return [dict(r, counts=json.loads(r["counts"]), evidence=json.loads(r["evidence"])) for r in rows]

    def profile(self, entity_id):
        """Everything known about one entity, grouped for display."""
        e = self.kb.entities[entity_id]
        claims = self.claims_about(entity_id)
        obs = self.observations_for(entity_id)
        framings = Counter()
        for o in obs:
            framings.update(o["counts"])
        disputes = [d for d in self.disputed() if entity_id in (d["subject"], d["object"])]
        return {"entity": e, "out": [c for c in claims if c["direction"] == "out"],
                "in": [c for c in claims if c["direction"] == "in"], "disputes": disputes,
                "observations": {"days": len({o["date"] for o in obs}), "topics": len({o["topic"] for o in obs}),
                                 "items": sum(o["n_items"] for o in obs), "framings": dict(framings.most_common(8))}}

    def stats(self):
        q = self.conn.execute
        return {"entities": dict(q("SELECT type, COUNT(*) FROM entities GROUP BY type ORDER BY 2 DESC").fetchall()),
                "claims_by_status": dict(q("SELECT status, COUNT(*) FROM claims GROUP BY status ORDER BY 2 DESC").fetchall()),
                "claims_by_predicate": dict(q("SELECT predicate, COUNT(*) FROM claims GROUP BY predicate ORDER BY 2 DESC").fetchall()),
                "observations": q("SELECT COUNT(*) FROM observations").fetchone()[0]}

    def sql(self, query, limit=200):
        """A read-only SELECT over the tables (entities, aliases, claims, observations) and the v_claims view."""
        text = query.strip().rstrip(";").strip()
        if ";" in text or not re.match(r"(?is)^(select|with)\b", text) or _FORBIDDEN.search(text):
            raise KBError("Only a single read-only SELECT query is allowed.")
        try:
            cursor = self.conn.execute(text)
            rows = cursor.fetchmany(limit)
        except sqlite3.Error as e:
            raise KBError(f"SQL error: {e}")
        return [d[0] for d in cursor.description], [tuple(r) for r in rows]
