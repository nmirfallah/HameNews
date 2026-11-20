"""A short plain-text summary of what the knowledge base says about an outlet or account, for the report."""
from .schema import STATUS_RANK
from .store import KBStore

LABELS = {"state_linked": "state-linked to", "publicly_funded_by": "publicly funded by", "owned_by": "owned by",
          "funded_by": "funded by", "affiliated_with": "affiliated with", "part_of": "part of"}


class Background:
    def __init__(self, root):
        self.kb = KBStore(root)

    def reference(self, name, kind="article"):
        """E.g. 'state-linked to Iran (reported); leaning: right (inferred)'. Empty when nothing is known."""
        found = self.kb.find_exact(name if kind == "article" else name, "outlet" if kind == "article" else "account")
        if len(found) != 1:
            return ""
        entity = found[0]
        claims = self.kb.claims_of(entity["id"], "out")
        denied = {(c["predicate"], c["object"]) for c in claims if c["status"] == "denied"}
        parts = []
        for c in sorted(claims, key=lambda c: (c["predicate"], STATUS_RANK[c["status"]])):
            if c["predicate"] in LABELS and c["status"] != "denied":
                other = self.kb.entities.get(c["object"], {}).get("name", c["object"])
                disputed = ", disputed" if (c["predicate"], c["object"]) in denied else ""
                parts.append(f"{LABELS[c['predicate']]} {other} ({c['status']}{disputed})")
        leanings = sorted((c for c in claims if c["predicate"] == "leaning"), key=lambda c: (STATUS_RANK[c["status"]], c["added"]))
        if leanings:
            parts.append(f"leaning: {leanings[0]['object']} ({leanings[0]['status']})")
        return "; ".join(parts)
