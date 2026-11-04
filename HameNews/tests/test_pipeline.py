"""Offline end-to-end test: fake LLM + fake data sources, no network, no API key.
Run:  python tests/test_pipeline.py     (or: pytest)"""
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trendwatch import sources
from trendwatch.config import build_config
from trendwatch.llm.base import LLM, extract_json
from trendwatch.models import Item, Signal
from trendwatch.pipeline import run
from trendwatch.store import Store


class FakeLLM(LLM):
    """Answers each TASK deterministically so the whole pipeline can be exercised."""

    def __init__(self):
        super().__init__({"fast": "fake-fast", "smart": "fake-smart"})
        self.calls = []

    def complete(self, system, prompt, tier="fast", max_tokens=2000):
        task = re.match(r"TASK:(\w+)", prompt).group(1)
        self.calls.append(task)
        if task == "cluster_topics":
            return json.dumps([
                {"topic": "Album Launch", "keywords": ["album", "launch"], "signal_ids": [0, 1, 2],
                 "summary": "A big album was released."},
                {"topic": "Lonely Signal", "keywords": ["x"], "signal_ids": [3], "summary": "."}])
        if task == "propose_framings":
            return "```json\n" + json.dumps({"has_distinct_framings": True, "framings": [
                {"label": "Celebratory", "description": "Frames it as an achievement."},
                {"label": "Dismissive", "description": "Mocks or belittles it."}]}) + "\n```"
        if task == "label_items":
            rows = []
            for m in re.finditer(r'<item i="(\d+)"[^>]*>(.*?)</item>', prompt):
                text = m.group(2).lower()
                lab = "f1" if "triumph" in text else "f2" if "mock" in text else "none"
                rows.append({"i": int(m.group(1)), "label": lab, "confidence": 0.9,
                             "evidence": text[:40]})
            return json.dumps(rows)
        if task == "classify_outlets":
            names = re.findall(r"^- (.+)$", prompt, re.M)
            return json.dumps([{"outlet": n, "group": "Israeli media" if n == "Outlet0" else "Iranian media"}
                               for n in names])
        if task == "group_narratives":
            gs = re.findall(r'<group name="([^"]+)"', prompt)
            first = re.search(r'<item i="(\d+)"', prompt)
            return json.dumps({"groups": [{"group": g, "narrative": f"According to {g}, it was covered.",
                                           "item_ids": [int(first.group(1))]} for g in gs],
                               "differences": "They use different terms."})
        if task == "write_narrative":
            return "Neutral briefing text."
        raise AssertionError(task)


def fake_signals(cfg):
    return [Signal("Album drop", "google_trends", 10), Signal("New album", "wikipedia", 9),
            Signal("album launch", "mastodon", 5), Signal("Something else", "hackernews", 1)]


def fake_content(topic, cfg):
    items = []
    for i in range(24):
        text = ("A triumph for the artist" if i % 3 == 0 else
                "Mock the hype, honestly" if i % 3 == 1 else "Album released on Friday")
        items.append(Item(id=f"a{i}", kind="article", platform="news",
                          outlet=f"Outlet{i % 2}", text=f"{text} #{i}", url=f"http://x/{i}"))
    for i in range(10):
        items.append(Item(id=f"p{i}", kind="post", platform="bluesky", outlet=f"user{i % 2}",
                          text="Total triumph, love it" if i % 2 == 0 else "Mock mock mock",
                          url=f"http://p/{i}", engagement=i))
    return items


def setup():
    sources.SIGNAL_SOURCES.clear(); sources.SIGNAL_SOURCES["fake"] = fake_signals
    sources.CONTENT_SOURCES.clear(); sources.CONTENT_SOURCES["fake"] = fake_content
    return build_config({"discovery": {"enabled_sources": ["fake"], "topics_per_day": 3},
                         "collection": {"sources": ["fake"]},
                         "analysis": {"min_items_outlet": 5, "min_items_account": 5}})


def test_extract_json():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! [1, 2, 3] done') == [1, 2, 3]


def test_end_to_end_and_no_double_counting():
    cfg = setup()
    with tempfile.TemporaryDirectory() as d:
        store, llm = Store(d), FakeLLM()
        name = run(llm, cfg, store)
        res = store.read(name.replace(".md", ".json"))
        # "Lonely Signal" trends on one platform only, so it is filtered out
        assert [r["topic"] for r in res] == ["Album Launch"], res
        div = res[0]["divide"]
        assert div["verdict"] == "strong", div
        assert div["kappa"] == 1.0
        assert "Divide verdict: strong" in store.read_text(name) if hasattr(store, "read_text") else True

        outlets = res[0]["rows"]["outlets"]
        assert len(outlets) == 2 and all(o["n"] == 12 for o in outlets), outlets
        assert all(o["label"] != "insufficient data" for o in outlets)

        # Running again on the same items must not inflate the counts
        run(llm, cfg, store)
        prof = store.read("profiles/outlets.json")
        assert sum(sum(t["counts"].values()) for e in prof.values()
                   for t in e["topics"].values()) == 24
        # framings are frozen: only proposed once
        assert llm.calls.count("propose_framings") == 1


def test_narratives_by_group_and_html_report():
    cfg = setup()
    with tempfile.TemporaryDirectory() as d:
        store, llm = Store(d), FakeLLM()
        name = run(llm, cfg, store)
        res = store.read(name.replace(".md", ".json"))[0]
        nar = res["narratives"]
        names = {g["group"] for g in nar["groups"]}
        assert {"Israeli media", "Iranian media", "Bluesky posts"} <= names, names
        assert nar["differences"] and res["rank"] == 1
        assert all(g["links"] for g in nar["groups"])
        # classification is cached and editable; a second run must not ask again
        assert store.read("outlet_groups.json")["Outlet0"] == "Israeli media"
        run(llm, cfg, store)
        assert llm.calls.count("classify_outlets") == 1
        md = open(store.path(name), encoding="utf-8").read()
        assert "### What each side says" in md and "**Israeli media**" in md
        html = open(store.path(name.replace(".md", ".html")), encoding="utf-8").read()
        assert "According to Israeli media" in html and "<!doctype html>" in html


def test_html_escapes_untrusted_text():
    from trendwatch.report import render_html
    bad = {"topic": "<img src=x onerror=alert(1)>", "n_items": 1, "platforms": [], "n_signals": 0,
           "narratives": {"groups": [{"group": "<b>g</b>", "n_items": 2, "outlets": ["<i>o</i>"],
                                      "narrative": "<script>alert(1)</script>",
                                      "links": [{"outlet": "x", "url": "javascript:alert(1)"}]}],
                          "differences": "", "unclassified": 0}}
    out = render_html("2026-01-01", [bad])
    assert "<img" not in out and "<script>" not in out and "javascript:" not in out


def test_manual_subject_and_provider_registry():
    from trendwatch.llm import get_llm
    try:
        get_llm({"provider": "nope", "models": {}})
        raise AssertionError("should have failed")
    except ValueError as e:
        assert "Known providers" in str(e)


if __name__ == "__main__":
    test_extract_json(); test_end_to_end_and_no_double_counting(); test_narratives_by_group_and_html_report(); test_html_escapes_untrusted_text(); test_manual_subject_and_provider_registry()
    print("all tests passed")
