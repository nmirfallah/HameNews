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
- 2026-11-10: the daily report is emailed through SMTP using only the standard library (no third-party action
  sees the credentials); recipients live in `emails.yaml`, credentials in repository secrets; the email step is
  last so a mail failure cannot lose results; one message per recipient.
- Keep `check_sources.py` as the first thing to run when something looks wrong.
- Offline test suite (unittest, no dependencies beyond the app's own) runs on every push via
  `.github/workflows/tests.yml`; the AI and all network access are faked in tests.

## Cost levers
Full analysis costs roughly 50-60 fast-model requests plus a few smart-model ones per topic (seen in the
first live run). `discovery.topics_per_day` is the main lever; "Also trending" costs nothing beyond the
single clustering call. Check the Console usage page and set `topics_per_day` to what you want to pay daily.

## Workflow facts (checked by tests/test_workflows.py)
Secret names match the code's environment variables; a preflight step fails early if the key is missing; 60
minute timeout; no overlapping runs; user inputs reach the shell only through environment variables; the commit
step runs last and only after success; the report is shown in the job summary and kept as an artifact.

## Email notes
Gmail is the default (`smtp.gmail.com`, port 587 STARTTLS, app password with 2-Step Verification). Ideas for later:
per-recipient options (topics of interest, language, only-when-something-changes), a plain "nothing new today"
mode, delivery to a team chat, an unsubscribe note when addresses beyond your own are added, and a provider with
an API (Resend, Brevo) if Gmail limits become a problem.

## Open questions
- Translation adds fast-model calls (20 items per call) and one keyword-translation call per topic; how much does it add per run? Both are cached.
- Actual cost per daily run on live data? Check the Anthropic Console usage page after the first runs.
- Does Google News rate-limit the roughly 40 requests per topic? If so, add backoff or lower
  `agencies.search`.
- Will the Actions bot's commits keep a scheduled workflow active in a public repo? (Repo is private, but
  confirm the behaviour.)

## Tasks
- First live Actions run still to be done: confirm runtime, cost and that Google News tolerates GitHub's IP ranges.
- Add a failure summary to the report (which sources returned nothing today).
- Alert on failed runs (GitHub emails the workflow owner on failure by default; confirm it reaches you).
- Cost cap: stop analysing further topics once an estimated token budget is exceeded.
- Add a small set of live smoke tests (opt-in, needs network and an API key) for the real sources and models.
- Pin dependency versions once the first live run succeeds.
