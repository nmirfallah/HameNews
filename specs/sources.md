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

## Open questions
- Which agency domains in `agencies.py` are wrong or return nothing? (Written from memory.)
- Do Tasnim, Fars and others have working English RSS feeds to add under `news_feeds`?
- How much non-English coverage is worth the cost of translating headlines first?

## Tasks
- Run `python check_sources.py` and fix or remove failing domains and feeds.
- Add confirmed RSS feeds for outlets that currently rely on the site-search fallback.
- Bluesky: set up the app-password login so account-level data is available.
- Hacker News: filter out comments that only contain the keyword in passing.
- Mastodon: consider a second instance if one server's trends are too narrow.
- Télam is reported closed (2024) and KCNA has no searchable domain; decide whether to keep them.
