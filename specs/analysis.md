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

## Multilingual notes
Labels and summaries are computed on English translations so groups are comparable across languages.
Translation quality is therefore part of label quality; the evaluation set should include translated items.

## Open questions
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
