from dataclasses import asdict, dataclass


@dataclass
class Signal:
    """One 'this is trending' data point from a discovery source."""
    name: str
    platform: str          # google_trends, wikipedia, hackernews, mastodon, bluesky, news
    score: float = 0.0
    url: str = ""


@dataclass
class Item:
    """One article or post about a topic."""
    id: str                # globally unique (url or platform id)
    kind: str              # "article" (outlet) or "post" (individual account)
    platform: str
    outlet: str            # outlet name for articles, handle for posts
    text: str
    url: str = ""
    created_at: str = ""
    engagement: int = 0

    def to_dict(self):
        return asdict(self)
