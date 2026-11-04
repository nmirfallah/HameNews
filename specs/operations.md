# Operations: running, cost and testing

**Status:** in progress.

## Goal
Run once a day unattended, cheaply, with failures that are visible and never silent.

## Decisions
- Python, GitHub Actions on a daily cron in a private repo (free at this usage); data committed back to
  `data/`.
- The AI model sits behind a small interface (`trendwatch/llm/`): Anthropic by default, OpenAI-compatible
  servers supported, new providers need one class and one registry line.
- Every data source fails softly with a warning; one broken feed never stops a run.
- Console output is forced to UTF-8 for Windows.
- Keep `check_sources.py` as the first thing to run when something looks wrong.

## Open questions
- Actual cost per daily run on live data? Check the Anthropic Console usage page after the first runs.
- Does Google News rate-limit the roughly 40 requests per topic? If so, add backoff or lower
  `agencies.search`.
- Will the Actions bot's commits keep a scheduled workflow active in a public repo? (Repo is private, but
  confirm the behaviour.)

## Tasks
- Add a failure summary to the report (which sources returned nothing today).
- Alert on failed runs (e.g. GitHub notifications on the workflow).
- Cost cap: stop analysing further topics once an estimated token budget is exceeded.
- CI: run `python tests/test_pipeline.py` on every push.
- Pin dependency versions once the first live run succeeds.
