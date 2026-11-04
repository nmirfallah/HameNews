import copy

DEFAULTS = {
    "llm": {
        "provider": "anthropic",
        "models": {"fast": "claude-haiku-5-5", "smart": "claude-sonnet-5-5"},
        "options": {},
    },
    "mastodon_instance": "mastodon.social",
    "news_feeds": [
        {"name": "BBC News", "url": "http://feeds.bbci.co.uk/news/world/rss.xml"},
        {"name": "The Guardian", "url": "https://www.theguardian.com/world/rss"},
        {"name": "NPR", "url": "https://feeds.npr.org/1001/rss.xml"},
        {"name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml"},
        {"name": "Fox News", "url": "https://moxie.foxnews.com/google-publisher/latest.xml"},
        {"name": "DW", "url": "https://rss.dw.com/rdf/rss-en-all"},
        {"name": "France 24", "url": "https://www.france24.com/en/rss"},
        {"name": "RT", "url": "https://rt-english.com/rss/"},
    ],
    # Outlets searched through Google News with a site: filter (no RSS URL needed).
    "news_sites": [
        {"name": "Tasnim News Agency", "site": "tasnimnews.ir"},
        {"name": "Fars News Agency", "site": "farsnews.ir"},
        {"name": "The Grayzone", "site": "thegrayzone.com"},
    ],
    # Force outlets into a named group, whatever the AI would have guessed.
    # Format: group name -> outlet names as they appear in results (case-insensitive).
    "outlet_groups": {
        "Qatar state-linked media": ["Al Jazeera", "Al Jazeera English"],
        "Russia state-linked media": ["RT", "RT News", "RT English", "Russia Today"],
        "Iran state-linked media": ["Tasnim News Agency", "Tasnim", "Fars News Agency",
                                    "FARS News Agency", "Fars News"],
        "The Grayzone": ["The Grayzone", "Grayzone", "thegrayzone.com"],
    },
    # National news agencies from trendwatch/agencies.py, grouped by country and ownership type.
    "agencies": {"enabled": True, "search": True, "site_chunk": 8},
    "discovery": {
        "enabled_sources": ["google_trends", "wikipedia", "hackernews", "mastodon",
                            "bluesky", "news_headlines"],
        "topics_per_day": 3,
        "candidate_topics": 10,
        "min_platforms": 2,
        "google_trends_geo": "US",
        "signals_per_platform": 40,
        "news_signal_cap": 120,
        "headlines_per_feed": 15,
    },
    "collection": {
        "sources": ["news", "bluesky", "mastodon", "hackernews"],
        "max_articles": 80,
        "max_posts": 80,
        "skip_replies": True,
        "google_news": True,
        # Google News editions to search. More editions = more national perspectives.
        "google_news_editions": ["US", "GB", "IL", "IN", "AU"],
    },
    "narratives": {
        "enabled": True,
        "min_total_items": 3,
        "min_group_items": 2,
        "max_items_per_group": 8,
        "max_groups": 8,
    },
    "analysis": {
        "min_items_to_analyze": 8,
        "batch_size": 10,
        "max_item_chars": 500,
        "min_kappa": 0.5,
        "min_framed_items": 10,
        "min_framed_share": 0.25,
        "min_framing_share": 0.15,
        "min_items_outlet": 10,
        "min_items_account": 15,
        "lean_threshold": 0.6,
    },
}


def deep_merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def build_config(user_cfg=None):
    cfg = deep_merge(DEFAULTS, user_cfg or {})
    cfg["domain_groups"] = {}
    if cfg["agencies"]["enabled"]:
        from . import agencies
        merged = {g: list(n) for g, n in agencies.outlet_groups().items()}
        for g, names in cfg["outlet_groups"].items():
            lst = merged.setdefault(g, [])
            lst += [n for n in names if n not in lst]
        cfg["outlet_groups"] = merged
        cfg["domain_groups"] = agencies.domain_groups()
    return cfg


def load_config(path):
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        return build_config(yaml.safe_load(f) or {})
