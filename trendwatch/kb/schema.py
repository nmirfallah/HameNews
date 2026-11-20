import re
import unicodedata
from datetime import date

from ..leanings import LEANINGS


class KBError(ValueError):
    """A problem with knowledge-base input; the message says what to fix."""


ENTITY_TYPES = ("outlet", "account", "person", "politician", "company", "state", "government_body",
                "movement", "party", "institution", "other")
CLAIMER_TYPES = ("state", "government_body", "movement", "institution", "party", "politician")

# Strongest to weakest. "denied" is a counter-claim, not weak evidence, and is never followed as a link.
STATUSES = ("documented", "self_described", "reported", "inferred", "alleged", "denied")
STATUS_RANK = {s: i for i, s in enumerate(STATUSES)}
DEFAULT_INCLUDE = ("documented", "self_described", "reported")

# predicate -> what its object is. Edges point from the dependent to the patron (outlet owned_by company).
PREDICATES = {
    "based_in": "entity",             # where an outlet or person is based
    "owned_by": "entity",
    "funded_by": "entity",
    "affiliated_with": "entity",
    "part_of": "entity",              # a body that belongs to another (a force that is part of a state)
    "state_linked": "entity",         # described as state-run / state-owned / state-affiliated; relation unspecified
    "publicly_funded_by": "entity",   # a public corporation funded by a state
    "employs": "entity",              # patron -> person; not a tie in the other direction
    "regulated_by": "entity",
    "sanctioned_by": "entity",
    "narrative_aligned_with": "entity",   # behavioural and inferred (scoring); never a documented tie
    "leaning": "value",               # the object is one of left .. right
}
TIE_PREDICATES = ("owned_by", "funded_by", "state_linked", "publicly_funded_by", "affiliated_with", "part_of")

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def norm(text):
    """Case-, accent- and punctuation-insensitive form used for matching names."""
    t = unicodedata.normalize("NFKD", str(text or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^\w]+", " ", t.casefold()).strip()


def entity_id(type_, name):
    return f"{type_}:{norm(name).replace(' ', '-')[:60] or 'x'}"


def _valid_date(value):
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def check_date(value, label):
    value = str(value or "").strip()
    if value and not (_DATE.match(value) and _valid_date(value)):
        raise KBError(f"{label} must be a date like 2026-11-15, not {value!r}.")
    return value


def check_choice(value, choices, label):
    if value not in choices:
        raise KBError(f"Unknown {label} {value!r}. Use one of: {', '.join(choices)}.")
    return value


def check_leaning(value):
    if value not in LEANINGS:
        raise KBError(f"A leaning must be one of: {', '.join(LEANINGS)} (got {value!r}).")
    return value
