# Analysis: framings, labels and narratives

**Status:** in progress. Pipeline works offline; quality on live data is unmeasured.

## Goal
For each trending topic, show what each group of sources says, whether the divide between groups is real,
and how outlets and accounts frame the topic, with evidence for every claim.

## Decisions
- Divide detection runs on every topic. Two independent labelling passes must agree before an item keeps a
  label; agreement is reported as Cohen's kappa.
- Labels describe what a post does (its framing), never the character of its author.
- Per-outlet and per-account labels need history (10 articles per outlet, 15 posts per account on a topic).
- Framings are frozen per topic in `data/topics/` so labels stay comparable; hand edits are kept.
- The AI never decides which framing is correct.
- The briefing is structured to avoid repetition: one shared main story, then per-group text limited to what
  the group adds or does differently, then a short list of real factual conflicts. Groups that add nothing
  are listed in one line.

## Multilingual notes
Labels and summaries are computed on English translations so groups are comparable across languages.
Translation quality is therefore part of label quality; the evaluation set should include translated items.

## Lessons from the first live run (2026-11-06)
- About a quarter of labelling batches returned unreadable JSON (unescaped quotes in the evidence field, or
  prose instead of JSON). Fixed with a quoting rule in the system prompt, a regex salvage for label rows, and
  splitting an unreadable batch in half. Track how often salvage and splitting fire; if frequent, consider a
  structured-output mode or dropping the model-written evidence in favour of code-extracted snippets.
- The model copied the style of the "already tracked topics" list. Pass readable names, never file-name slugs.

## Translation testing
`python run.py -j <source>` runs detection and translation on one source and saves a side-by-side page with
automatic checks and an optional model review (`--verify`). To go further: keep a small human-checked set of
headlines per language (Persian, Arabic, Russian, Hebrew, Turkish) and score translations against it, and
compare translations of the same story from different outlets for consistent handling of loaded terms.

## Open questions
- Does the model keep to the "say it once" rule on real topics, or does it still restate the main story in
  each group? If so, tighten the prompt or post-filter repeated sentences.
- Are the proposed framings sensible on real topics? Review the first live reports.
- Do the two-pass agreement thresholds (kappa 0.5, 25% framed) separate real divides from imagined ones?
- Do translated items label differently from native-English ones on the same story?
- Is headline-level text enough, or should full article text be fetched for the top few items?
- Should the same topic on different days share one history even if the AI names it differently?

## Tasks
- Review evidence quotes against their labels on the first real reports; tune prompts.
- Calibrate on outlets with well-known positions and fix framings that look off.
- Trend history: chart divide verdicts over days from `data/topics/*.json`.
- Topic matching across days (fuzzy match on names and keywords) to avoid duplicate topic files.
- Evaluation set: a small hand-labelled sample to measure labelling accuracy over time. Unit tests prove the
  code behaves; only this set shows whether the model's labels are any good.
