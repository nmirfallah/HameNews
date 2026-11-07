# Specs

Planning documents for HameNews, one file per subject. Code and the main README describe what exists today;
these describe what is planned, why, and what was decided.

| Spec | Subject | Status |
|---|---|---|
| [knowledge-base.md](knowledge-base.md) | Entities, claims, and storage (JSONL, DuckDB, graph) | Designed, not built |
| [sources.md](sources.md) | News feeds, agencies, social platforms and their gaps | In progress |
| [analysis.md](analysis.md) | Framing detection, labels, narratives, trend history | In progress |
| [scoring.md](scoring.md) | Scores linking sources to claimers (documented connection, narrative alignment, combined) | Draft |
| [operations.md](operations.md) | Scheduling, cost, testing, deployment | In progress |

## Conventions
- Each spec has: **Goal**, **Status**, **Decisions** (with dates), **Open questions**, **Tasks**.
- When a decision changes, add a dated line to its Decisions list instead of silently rewriting it.
- When a task ships, move it to the main README and delete it here, so specs never describe the past.
- Keep specs short. If one grows past a couple of pages, split it by subject.
