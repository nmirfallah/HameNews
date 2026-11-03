import hashlib
import html
import logging
import re

log = logging.getLogger("trendwatch")


def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:60] or "topic"


def short_hash(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:12]


def clip(s, n):
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


def term_in(term, text):
    """Whole-word, case-insensitive match (so 'AI' does not match 'said')."""
    return re.search(r"\b" + re.escape(term) + r"\b", text, re.IGNORECASE) is not None
