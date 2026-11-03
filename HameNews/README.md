# HameNews

HameNews finds what is trending once a day (or analyses a subject you choose), measures whether
different groups **frame it differently**, and labels the outlets and accounts that share it.

**Keep this repo private.** It stores per-account labels in `data/`.

## Quick start
```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
python run.py --subject "AI regulation"     # one subject you choose
python run.py                               # auto-discover today's trending topics
python tests/test_pipeline.py               # offline test, no network or key needed
```
Output: `data/reports/YYYY-MM-DD.md` (+ `.json`), running profiles in `data/profiles/`,
frozen framings per topic in `data/topics/`.

## How it works
1. **Discover** (`discovery.py`): trend signals from Google Trends RSS, Wikipedia pageviews,
   Hacker News, Mastodon, Bluesky and news headlines. The LLM clusters them into topics;
   a topic counts as trending only if it shows on `min_platforms` different platforms.
   `--subject` skips this step.
2. **Collect** (`collect.py`): articles (Google News RSS + your feeds) and posts
   (Bluesky, Mastodon, HN comments) about each topic.
3. **Framings** (`stance.py`): the LLM proposes how groups talk about the topic, and is allowed
   to say "no distinct framings". They are saved to `data/topics/<topic>.json` and frozen;
   edit that file by hand and your version is kept.
4. **Divide detection**: every item is labelled by two independent passes (different item and
   framing order). Only items both passes agree on keep a label. The agreement score (Cohen's kappa)
   and the share of items with a clear framing give a verdict: `strong`, `one-sided`, `weak`,
   `unreliable` or `no distinct framings`.
5. **Profiles** (`profiles.py`): per-outlet and per-account counts accumulate across days.
   A label appears only after `min_items_outlet` / `min_items_account` items, and always shows
   its sample size, confidence and quoted evidence.
6. **Report** (`report.py`): a neutral AI-written summary of the numbers plus tables.

Optional: add `data/known_ratings.json` (`{"BBC News": "AllSides: Center"}`) to show reference
ratings from AllSides/MBFC/Ad Fontes next to the AI labels. Check each rater's licence first.

## Changing the AI model
Everything goes through the small `LLM` interface in `trendwatch/llm/base.py`.
- Other Anthropic models: change `llm.models` in `config.yaml`.
- OpenAI, Ollama, vLLM, OpenRouter or any OpenAI-style server: `provider: openai_compat`
  with `options.base_url` (see the commented example in `config.yaml`).
- A different SDK: subclass `LLM`, implement `complete()`, add one line to `PROVIDERS`
  in `trendwatch/llm/__init__.py`. No other file changes.

## GitHub Actions
1. Create a **private** repo and push this project.
2. Settings, Secrets and variables, Actions: add `ANTHROPIC_API_KEY`
   (optionally `BSKY_HANDLE` and `BSKY_APP_PASSWORD`).
3. `.github/workflows/daily.yml` runs daily at 12:00 UTC and commits `data/`.
   Use "Run workflow" to test it, with an optional subject.

## Known limits
- Written and tested offline only (fake LLM, fake sources). The live endpoints, feed URLs and
  default model names were not exercised, so run `python run.py --subject "something"` once and
  read the log: every source fails softly with a warning. Fix or remove any that do.
- Bluesky search may need the free app-password login. Instagram and X/Twitter are not supported.
- Outlets are judged from headlines and snippets, not full articles. Treat labels as leads to check.
- Social samples skew toward the platforms covered (Bluesky, Mastodon and HN are not the general public).
