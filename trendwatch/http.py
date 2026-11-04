import requests

from .util import log

UA = "trendwatch/0.1 (personal research tool)"


def get(url, params=None, headers=None, timeout=20):
    h = {"User-Agent": UA}
    h.update(headers or {})
    try:
        r = requests.get(url, params=params, headers=h, timeout=timeout)
        r.raise_for_status()
        return r
    except requests.RequestException as e:
        log.warning("GET %s failed: %s", url, e)
        return None


def get_json(url, params=None, headers=None, timeout=20):
    r = get(url, params, headers, timeout)
    if r is None:
        return None
    try:
        return r.json()
    except ValueError:
        log.warning("GET %s did not return JSON", url)
        return None


def get_feed(url):
    import feedparser  # imported lazily so other code paths work without it
    r = get(url)
    return feedparser.parse(r.content) if r is not None else None
