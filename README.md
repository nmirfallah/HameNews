# HameNews

HameNews watches what is trending in the news and on social media, then answers a harder
question: **do different groups talk about it differently, and who is saying what?**

Once a day it finds the topics people are talking about (or takes a subject you choose),
collects articles and posts about each one, uses an AI model to work out the competing
framings, checks that the split is real and not imagined, and labels the news outlets and
accounts by how they frame the topic. The result is a Markdown report committed to this repo.

> **Keep this repository private.** It stores per-outlet and per-account labels in `data/`.
> It is built as a personal research tool.

## Contents
- [How it works](#how-it-works)
- [Quick start](#quick-start)
- [Run it daily with GitHub Actions](#run-it-daily-with-github-actions)
- [Configuration](#configuration)
- [Using a different AI model](#using-a-different-ai-model)
- [Adding a data source](#adding-a-data-source)
- [What you get](#what-you-get)
- [Project layout](#project-layout)
- [Reading the labels responsibly](#reading-the-labels-responsibly)
- [Known limits](#known-limits)
- [Plans and specs](#plans-and-specs)

## How it works

1. **Discover.** Trend signals come from Google Trends (public RSS), Wikipedia pageviews,
   Hacker News, Mastodon, Bluesky and news-feed headlines. The AI groups them into topics.
   A topic counts as trending only if it shows up on at least `min_platforms` different
   platforms (default 2). Skip this step with `--subject "..."`.
2. **Collect.** Articles come from Google News RSS plus your own feed list. Posts come from
   Bluesky, Mastodon and Hacker News comments.
3. **Find framings.** The AI proposes up to five ways different groups talk about the topic,
   describing what a post *does*, not who the author is. It may answer "no distinct framings".
   Framings are saved per topic and frozen so labels stay comparable from day to day.
   Edit the saved file and your version is kept.
4. **Test the divide.** Every item is labelled by two independent passes (different item order
   and framing order). An item keeps a label only if both passes agree. The agreement score
   (Cohen's kappa) and the share of items with a clear framing produce a verdict:

   | Verdict | Meaning |
   |---|---|
   | `strong` | Two or more framings are well represented and the labelling is reliable |
   | `one-sided` | One framing dominates |
   | `weak` | Most items are neutral or unlabelled |
   | `unreliable` | The two passes disagree too much; any split may be imagined |
   | `no distinct framings` | The sample showed one shared reaction |
   | `insufficient data` | Too few items were found |

5. **Profile sources.** Per-outlet and per-account counts accumulate across days. A label
   appears only after enough items (default 10 per outlet, 15 per account), and always shows
   its sample size, a confidence level and quoted evidence.
6. **Report.** A neutral AI-written summary of the computed numbers, plus tables.

**The report shows, for each trending topic (ranked by how much it is trending), what each group of
sources says:**

```
#1  Hamas attack on Israel          (trending on 5 platforms)
  According to Israeli media, ...   Sources: [Times of Israel] ...
  According to Iranian media, ...   Sources: [Tehran Times] ...
  According to US media, ...
  Where they differ: terminology, casualty figures, causes cited ...
```
Groups are the country an outlet is based in (for articles) or the platform (for posts).
Open it as a web page with `python run.py --open`, or `python run.py --open-latest`
to reopen the newest one without running anything.

The AI does the judgment work (grouping, framing, labelling, writing). Plain code does the
counting, thresholds and history, so the numbers are exact and cheap.

## Quick start (Windows PowerShell)

Requires [Python 3.10+](https://www.python.org/downloads/windows/) (tick "Add python.exe to PATH"
in the installer) and [Git for Windows](https://git-scm.com/download/win).

```powershell
git clone https://github.com/YOUR_USERNAME/HameNews.git
cd HameNews

python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

$env:ANTHROPIC_API_KEY = "your_key_here"      # lasts for this PowerShell window only

python run.py --subject "AI regulation"       # analyse one subject you choose
python run.py                                 # auto-discover today's trending topics
python run.py --topics 5                      # auto-discover, analyse 5 topics
python run.py --open                          # run, then open the HTML report in your browser
python run.py --open-latest                   # just reopen the newest report
```

Notes for Windows:
- If `Activate.ps1` is blocked, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`
  once in that window and activate again.
- If `python` is not found, use `py` instead (for example `py -m venv .venv`).
- To keep the API key permanently: `setx ANTHROPIC_API_KEY "your_key_here"`, then open a new window.
- Git may print "LF will be replaced by CRLF" warnings. They are harmless.

On macOS or Linux, use `python3`, `source .venv/bin/activate` and `export ANTHROPIC_API_KEY=...`.

Run the offline test (no network, no API key):

```powershell
python tests\test_pipeline.py
```

**Before your first real run,** check every source with `python check_sources.py`
(add `--llm` to also test your API key and model names).

**First run:** read the log. Every data source fails softly with a warning, so one broken
feed or endpoint never stops a run. Remove or fix any source that keeps warning.

## Run it daily with GitHub Actions

1. Push this project to a **private** repository.
2. Go to *Settings, Secrets and variables, Actions* and add:
   - `ANTHROPIC_API_KEY` (required)
   - `BSKY_HANDLE` and `BSKY_APP_PASSWORD` (optional; Bluesky search may need a free app password)
3. `.github/workflows/daily.yml` runs every day at 12:00 UTC and commits the new files in `data/`.
4. To test, open the *Actions* tab, choose **Daily trend report**, and click **Run workflow**.
   You can enter a subject there to analyse it instead of auto-discovering.

Cost: GitHub Actions is free for this usage (a daily run takes a few minutes). The AI
provider's API usage is billed separately; at this volume it is typically small, and
`discovery.topics_per_day`, `collection.max_articles` and `collection.max_posts` control it.

## Configuration

Everything is in `config.yaml`. Anything you leave out falls back to the defaults in
`trendwatch/config.py`.

| Setting | Purpose |
|---|---|
| `llm.provider`, `llm.models` | Which AI provider and which models (`fast` for bulk labelling, `smart` for clustering and writing) |
| `discovery.enabled_sources` | Which trend sources to use |
| `discovery.topics_per_day` | How many topics to analyse each day |
| `discovery.min_platforms` | Platforms a topic must trend on |
| `collection.sources` | Which sources to collect articles and posts from |
| `analysis.min_items_outlet` / `min_items_account` | Sample size before a source gets a label |
| `analysis.min_kappa` | Minimum agreement between the two labelling passes |
| `news_feeds` | The RSS feeds to read; add outlets with different perspectives for a fuller picture |

## Using a different AI model

The whole app talks to the AI through one small interface, `trendwatch/llm/base.py`.

- **Other models from the same provider:** change `llm.models` in `config.yaml`.
- **OpenAI, Ollama, vLLM, LM Studio, OpenRouter or any OpenAI-style server:**
  ```yaml
  llm:
    provider: openai_compat
    models: {fast: llama3.1, smart: llama3.1}
    options: {base_url: "http://localhost:11434/v1"}
  ```
  Also `pip install openai`.
- **A different SDK:** subclass `LLM`, implement `complete()`, and add one line to `PROVIDERS`
  in `trendwatch/llm/__init__.py`. No other file changes.

## Adding a data source

Each source is a small module in `trendwatch/sources/`:

- A discovery source exposes `signals(cfg)` and returns a list of `Signal`.
- A content source exposes `search(topic, cfg)` and returns a list of `Item`
  (`kind="article"` for outlets, `kind="post"` for individual accounts).

Register it in `trendwatch/sources/__init__.py`, then enable it in `config.yaml`.

## Why am I not seeing labels?

There are two kinds of output, and they fill in at different speeds:

- **"What each side says"** works from the first run. It needs at least `narratives.min_group_items`
  items from a source group. Outlets whose country the AI could not identify are left out.
- **Per-outlet and per-account labels** (in "Analysis details") need history: 10 articles per outlet
  and 15 posts per account on the same topic (`analysis.min_items_outlet` / `min_items_account`).
  Until then the table shows progress such as `building (3/10 items needed)`. They are also skipped
  when the verdict is `no distinct framings` or `insufficient data`.
  For testing, lower both numbers in `config.yaml`.
- No accounts at all? Bluesky search needs the app-password login (see Quick start).

## Getting more perspectives

Coverage is only as varied as your sources. Add more `google_news_editions` (country codes), and add
RSS feeds for outlets from the countries or camps you want represented, with an optional `group`
in `config.yaml`. Outlets not written in English are not covered unless they publish an English feed.
Outlet-to-country assignments are made by the AI and saved to `data/outlet_groups.json`; fix any
mistakes there and your edits are kept.

## Choosing which outlets are in which group

Settings in `config.yaml` (defaults live in `trendwatch/config.py`) control this:

- `news_feeds`: outlets read through their own RSS feed (BBC, Guardian, NPR, Al Jazeera, Fox, DW,
  France 24 and RT by default).
- `news_sites`: outlets searched through Google News with a `site:` filter (Tasnim, Fars and The Grayzone
  by default). Use it for outlets whose RSS address you do not have.
- `agencies`: about 60 national news agencies listed in `trendwatch/agencies.py`, each tagged with its
  country and ownership type. They are searched through Google News (several domains per query) and
  grouped as `<Country> state-linked media`, `<Country> public media` or `<Country> independent media`.
  Set `agencies.enabled: false` to turn this off, or `agencies.search: false` to keep the grouping
  but skip the extra searches. Edit the list to add or fix agencies.
- `outlet_groups`: forces outlets into a named group, overriding the AI and the agency list. The group
  name is exactly what appears in the report ("According to Qatar state-linked media, ...").

Grouping order for each article: its website domain, then its outlet name, then the AI's guess
(cached in `data/outlet_groups.json`, which you can edit).

Al Jazeera, RT, Tasnim and Fars are placed in their country's `state-linked` group (Qatar, Russia,
Iran). The Grayzone is its own group rather than being filed under a funder, because its funding is
disputed: the outlet says it takes no government money, while critics point to ties between its staff
and RT/Sputnik. Move it in `outlet_groups` if you disagree.

Limits: the agency names and domains were written from memory and not verified one by one. Many agencies
publish mainly in other languages and will only show up when they publish English content. Reported
as closed or unreachable: Argentina's Telam (reported closed in 2024) and KCNA (no searchable domain).
Run `python check_sources.py` to see which agencies actually return results.

## What you get

```
data/
  reports/2026-11-03.html    the daily report to read in a browser (plus .md and .json versions)
  outlet_groups.json         which country group each outlet belongs to (editable)
  topics/<topic>.json        frozen framings and divide history for each topic
  profiles/outlets.json      running per-outlet counts and evidence
  profiles/accounts.json     running per-account counts and evidence
  known_ratings.json         optional: your own reference ratings to show beside AI labels
```

`known_ratings.json` is a simple map such as `{"BBC News": "AllSides: Center"}`. If you use
ratings from AllSides, Media Bias/Fact Check or Ad Fontes, check each organization's licence first.

## Project layout

```
run.py                      command-line entry point
check_sources.py            smoke-tests every source and the AI model
config.yaml                 your settings
trendwatch/
  discovery.py              find and rank trending topics
  collect.py                gather articles and posts
  stance.py                 framings, two-pass labelling, divide verdict
  profiles.py               running outlet and account profiles
  groups.py, narratives.py  source groups and the "According to X..." summaries
  report.py, pipeline.py    report rendering (Markdown and HTML) and the daily flow
  prompts.py                every prompt in one place
  llm/                      model-independent AI layer and providers
  sources/                  one module per data source
tests/test_pipeline.py      offline end-to-end test
specs/                      planning documents, one file per subject
.github/workflows/daily.yml scheduled job
```

## Reading the labels responsibly

- A label describes how coverage of **one topic** is framed. It is not a verdict on a
  source in general. "Leans X on this topic" is a finding; "this outlet is X" is not.
- Labels come from an AI reading headlines and short snippets, so they can be wrong.
  Always check the quoted evidence and the sample size.
- A source reporting a claim is not endorsing it. The prompts try to separate the two,
  but sarcasm and missing context still cause errors.
- The AI has its own blind spots about what is neutral. Compare against a few outlets
  whose positions are well known, and edit the saved framings if they look off.
- Posts sampled from Bluesky, Mastodon and Hacker News are not the general public.
- Text collected from the web is treated as untrusted data and never as instructions to the AI.

## Known limits

- The code was tested offline with a fake AI and fake data. Live endpoints, feed URLs and
  the default model names should be confirmed on a first run.
- Google Trends access is an unofficial public feed and may change.
- Bluesky search may require the app-password login.
- Instagram and X/Twitter are not supported. X's API is paid and Instagram has no public trends API.
- Articles are judged from headlines and snippets, not full text.

## Plans and specs

Planned work and design decisions live in [`specs/`](specs/README.md), one file per subject:
the knowledge base of outlet and account connections, news sources, analysis quality, and operations.
