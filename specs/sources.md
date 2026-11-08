# Sources: where the news and posts come from

**Status:** in progress. Core sources work; agency coverage is unverified.

## Goal
Cover enough different national, state-linked, public and independent outlets that the "what each side says"
section reflects real differences, and know which sources actually work.

## Decisions
- Google News RSS (several national editions) is the main article source, plus configured RSS feeds.
- Outlets without a known RSS address are searched through Google News with a `site:` filter.
- About 60 national agencies live in `trendwatch/agencies.py`, tagged by country and ownership type, and are
  grouped as `<Country> state-linked | public | independent media`.
- The Grayzone is its own group, not filed under a funder, because its funding is disputed.
- X/Twitter and Instagram are excluded (no free API access).
- 2026-11-07: discovery ranks by a trend score (platform breadth plus distinct news outlets) and no longer
  requires two platforms, because a story covered by many outlets but not spiking on search or social was
  being dropped (suspected for the Iran war). Topics beyond `topics_per_day` are listed, not hidden. A
  `watchlist` guarantees standing stories are analysed. Each run saves a discovery log for `--why`.
- Other languages: non-English items are translated to English for analysis (originals kept and cached);
  topics are also searched in configured languages through Google News editions, using model-written
  search terms. Language comes from source metadata first, with a script/stopword guess as fallback.

## Open questions
- Google News top-story feed URLs (`/rss`, `/rss/headlines/section/topic/WORLD`) and the five editions are
  from memory; confirm with `python check_sources.py` that they return headlines.
- Is 400 headlines and 30 candidate topics enough for a busy news day, or do we need a pre-filter by outlet?
- Which agency domains in `agencies.py` are wrong or return nothing? (Written from memory.)
- Do Tasnim, Fars and others have working English RSS feeds to add under `news_feeds`?
- Which Google News country/language pairs actually return results? (Written from memory, unverified;
  there is no Iran edition.)
- Is translating headlines enough, or do key stories need full-text translation?
- Should agency searches also use native-language terms (each agency would need a `lang` field)?

## Tasks
- Run `python check_sources.py` and fix or remove failing domains and feeds.
- Add confirmed RSS feeds for outlets that currently rely on the site-search fallback.
- Add a `lang` field to agencies in `trendwatch/agencies.py` and search them with translated terms.
- Persian, Arabic, Hebrew and Russian outlets: add feeds in the original language with `lang` set.
- Bluesky: set up the app-password login so account-level data is available.
- Prune old `data/discovery/*.json` logs (about 100 KB a day) after N days.
- Topic relevance filter: broad keywords such as 'shooting' pull in unrelated stories (seen in the Krakow report).
- Hacker News: filter out comments that only contain the keyword in passing.
- Mastodon: consider a second instance if one server's trends are too narrow.
- Télam is reported closed (2024) and KCNA has no searchable domain; decide whether to keep them.
