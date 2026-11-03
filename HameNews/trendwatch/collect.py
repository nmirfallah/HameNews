"""Stage 2: gather articles and posts about a topic from the enabled content sources."""
from .sources import CONTENT_SOURCES
from .util import log


def collect(topic, cfg):
    items, seen = [], set()
    for name in cfg["collection"]["sources"]:
        fn = CONTENT_SOURCES.get(name)
        if fn is None:
            log.warning("unknown content source %r", name)
            continue
        try:
            found = fn(topic, cfg)
        except Exception as e:
            log.warning("content source %s failed: %s", name, e)
            continue
        for it in found:
            if it.id and it.id not in seen and it.text.strip():
                seen.add(it.id)
                items.append(it)

    c = cfg["collection"]
    articles = [i for i in items if i.kind == "article"][: c["max_articles"]]
    posts = sorted((i for i in items if i.kind == "post"), key=lambda i: -i.engagement)[: c["max_posts"]]
    return articles + posts
