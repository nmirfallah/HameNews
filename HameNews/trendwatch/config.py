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
    ],
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
        "max_articles": 60,
        "max_posts": 80,
        "skip_replies": True,
        "google_news": True,
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
    return deep_merge(DEFAULTS, user_cfg or {})


def load_config(path):
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        return build_config(yaml.safe_load(f) or {})
