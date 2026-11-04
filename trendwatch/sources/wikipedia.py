"""Wikipedia most-viewed articles: a spike here usually means something happened in the world."""
from datetime import datetime, timedelta, timezone

from ..http import get_json
from ..models import Signal

SKIP_PREFIXES = ("Main_Page", "Special:", "Wikipedia:", "Portal:", "Help:", "File:",
                 "Category:", "Talk:", "Template:", "Deaths_in_", "-")


def signals(cfg):
    day = datetime.now(timezone.utc) - timedelta(days=2)  # newest day may not be published yet
    url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/all-access/"
           f"{day:%Y/%m/%d}")
    data = get_json(url)
    try:
        articles = data["items"][0]["articles"]
    except (TypeError, KeyError, IndexError):
        return []
    out = []
    for a in articles:
        name = a.get("article", "")
        if name.startswith(SKIP_PREFIXES):
            continue
        out.append(Signal(name=name.replace("_", " "), platform="wikipedia",
                          score=float(a.get("views", 0)),
                          url=f"https://en.wikipedia.org/wiki/{name}"))
    return out[:60]
