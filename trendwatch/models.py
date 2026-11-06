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
    group: str = ""        # perspective group, e.g. "Israeli media" or "Bluesky posts"
    domain: str = ""       # website domain of the outlet when known (from Google News)
    leaning: str = ""      # left, center-left, center, center-right or right (outlets only); "" = unknown
    leaning_source: str = ""  # where the leaning came from: config, user, or AI estimate
    lang: str = ""         # ISO 639-1 language code of `text` ("" = unknown)
    text_en: str = ""      # English translation of `text` when it is not English

    @property
    def en(self):
        """The text to analyse: the English translation if there is one, else the original."""
        return self.text_en or self.text

    def to_dict(self):
        return asdict(self)
