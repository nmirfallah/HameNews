from . import bluesky, google_trends, hackernews, mastodon, news, wikipedia

# Discovery: each takes cfg and returns list[Signal]
SIGNAL_SOURCES = {
    "google_trends": google_trends.signals,
    "wikipedia": wikipedia.signals,
    "hackernews": hackernews.signals,
    "mastodon": mastodon.signals,
    "bluesky": bluesky.signals,
    "news_headlines": news.signals,
}

# Collection: each takes (topic, cfg) and returns list[Item]
CONTENT_SOURCES = {
    "news": news.search,
    "bluesky": bluesky.search,
    "mastodon": mastodon.search,
    "hackernews": hackernews.search,
}
