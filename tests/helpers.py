"""Shared test helpers: a scriptable fake LLM, builders, and fixtures. No network, no API keys."""
import json
import logging
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

logging.getLogger("trendwatch").setLevel(logging.CRITICAL)  # keep expected warnings out of test output

from trendwatch.config import build_config  # noqa: E402
from trendwatch.llm.base import LLM  # noqa: E402
from trendwatch.models import Item  # noqa: E402


class ScriptedLLM(LLM):
    """Returns queued replies in order, or asks `handler(prompt, tier)`. Records every call.

    A reply may be a string (returned as is), any other JSON-able value (dumped to JSON),
    or an Exception (raised)."""

    def __init__(self, replies=(), handler=None):
        super().__init__({"fast": "fast-model", "smart": "smart-model"})
        self.replies = list(replies)
        self.handler = handler
        self.calls = []

    def complete(self, system, prompt, tier="fast", max_tokens=2000):
        self.calls.append({"system": system, "prompt": prompt, "tier": tier, "max_tokens": max_tokens})
        reply = self.handler(prompt, tier) if self.handler else self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, str) else json.dumps(reply)

    def tasks(self):
        return [re.match(r"TASK:(\w+)", c["prompt"]).group(1) for c in self.calls]


class EchoLLM(LLM):
    """Registered under a fake provider name to test get_llm()."""

    def __init__(self, models, flag=None):
        super().__init__(models)
        self.flag = flag

    def complete(self, system, prompt, tier="fast", max_tokens=2000):
        return "echo"


ITEM_RE = re.compile(r'<item i="(\d+)"[^>]*>(.*?)</item>', re.S)


def keyword_labels(prompt):
    """Label items by keyword: 'triumph' -> f1, 'mock' -> f2, else none."""
    rows = []
    for m in ITEM_RE.finditer(prompt):
        text = m.group(2).lower()
        label = "f1" if "triumph" in text else "f2" if "mock" in text else "none"
        rows.append({"i": int(m.group(1)), "label": label, "confidence": 0.9, "evidence": text[:30]})
    return rows


def leaning_reply(prompt, mapping=None):
    """Answer a classify_leanings prompt from a name -> leaning mapping (default: unknown)."""
    mapping = mapping or {}
    return [{"outlet": n, "leaning": mapping.get(n, "unknown")} for n in re.findall(r"^- (.+)$", prompt, re.M)]


def task_handler(**responses):
    """Answer by TASK tag. Values are data, or callables taking the prompt. An unexpected task fails the test."""
    def handle(prompt, tier):
        task = re.match(r"TASK:(\w+)", prompt).group(1)
        reply = responses[task]
        return reply(prompt) if callable(reply) else reply
    return handle


FRAMINGS_REPLY = {"has_distinct_framings": True, "framings": [
    {"label": "Celebratory", "description": "Frames it as an achievement."},
    {"label": "Dismissive", "description": "Mocks or belittles it."}]}

FRAMINGS = {"topic": "T", "has_distinct_framings": True, "framings": [
    {"id": "f1", "label": "Celebratory", "description": "d1"},
    {"id": "f2", "label": "Dismissive", "description": "d2"}]}


def cfg(**overrides):
    return build_config(overrides)


def item(i, kind="article", outlet="Outlet", text=None, **kw):
    platform = kw.pop("platform", "news" if kind == "article" else "bluesky")
    return Item(id=str(i), kind=kind, platform=platform, outlet=outlet,
                text=text if text is not None else f"text {i}", **kw)


def mixed_items(n_articles=12, n_posts=6):
    """Articles alternate triumph/mock/neutral; posts alternate triumph/mock."""
    out = []
    for i in range(n_articles):
        text = ("A triumph for the artist" if i % 3 == 0 else
                "Mock the hype, honestly" if i % 3 == 1 else "Album released on Friday")
        out.append(item(f"a{i}", "article", f"Outlet{i % 2}", f"{text} #{i}", url=f"http://x/{i}"))
    for i in range(n_posts):
        out.append(item(f"p{i}", "post", f"user{i % 2}",
                        "Total triumph, love it" if i % 2 == 0 else "Mock mock mock",
                        url=f"http://p/{i}", engagement=i))
    return out
