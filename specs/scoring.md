# Source scoring: connections between sources and claimers

**Status:** draft for review, not built. Depends on `knowledge-base.md` for documented connections.

## Goal
For every news source (and, later, social account), show how strongly it is connected to each **claimer**
(a state, group, bloc or party that promotes a narrative), by two independent measures and a combined view:

- **Documented connection** (structural): ownership, funding, control or official affiliation, from sourced claims.
- **Narrative alignment** (behavioural): how closely its coverage echoes the claimer's stated position over time.
- **Combined view**: one number per claimer that says plainly which of the two it rests on.

Unknown connections are not assumed to be zero; they are estimated from coverage as evidence accumulates.

## Terms
- **Claimer:** an actor with a publicly stated position on topics. Types: state or government, armed group or
  movement, bloc or institution, party or politician.
- **Stated position:** what the claimer says publicly about a topic. It is never "what they want" or intent.
- **Position card:** a short reviewed record of a claimer's stated position on one topic, with source links.
- **Echo:** a source's item adopts the framing that matches a claimer's stated position (not merely reports it).

## Decisions
- 2026-11-06: two separate scores plus a combined view (not a single merged number).
- 2026-11-06: all four claimer types are in scope: states and governments, armed groups and movements,
  blocs and institutions, parties and politicians.
- 2026-11-06: scores are used for the daily report, sorting and filtering, shift alerts, and as new claims
  in the knowledge base.
- 2026-11-06: scores for different claimers are independent (an outlet can be high for several); they do not sum to 100.

## Principles
- **Say what is measured.** Wording is "documented connection" and "aligns with". Never "proxy", "agent",
  "bot" or "controlled by" unless a documented claim says so. Precedent: Hamilton 68, which inferred ties from
  content overlap and was accused of mislabelling ordinary accounts while its authors said it never claimed bots;
  its account list was also not public. Lesson: state the meaning, show the evidence, publish the method.
- **Evidence on every score.** Each number links to its claims, items and sample size, or it is not shown.
- **Unknown is not zero.** No data gives "unknown" or "not enough data".
- **Alignment is not coordination.** Echoing a position proves similarity, not funding or control.
- **No circular proof.** Alignment never feeds back into the documented score (see Knowledge base feed).
- **Versioned.** Every stored score records the method version, so changes can be traced and compared.

## Score 1: documented connection (structural), 0-100 or unknown
Computed from knowledge-base claims between a source and a claimer.

| Claim type (example) | Base strength |
|---|---|
| owned by, or funded mainly from the budget of, the claimer | 100 |
| official organ of a party or movement (self-described or documented) | 90 |
| leadership appointed or removed by the claimer | 80 |
| partial funding, grants, contracts | 60 |
| former officials in senior roles, sponsored content | 20-30 |

Multiply by status: documented 1.0, self-described 1.0, reported 0.7, alleged 0.3. Take the **maximum** over
claims (never add, to avoid double counting). Add `disputed: true` when the best claim is reported or alleged
and a denial exists. A denial is stored and shown beside the allegation; it does not lower the number silently.
All values live in config because they are judgments, not facts.

Interim seed until the knowledge base exists: outlets in `trendwatch/agencies.py` with kind `state` get a
structural value for their country as a **reported** claim (0.7 x base), flagged "from ownership type, verify".

## Score 2: narrative alignment (behavioural), 0-100 with an interval
Starting formulation, to be tuned by the validation below.

1. **Position cards.** For each topic and claimer with a stated position, build a card. The AI drafts it from
   the claimer's own channels (config list per claimer, e.g. foreign ministry, state news agency, official
   press releases) or from reputable reporting that quotes them (for groups whose channels should not be
   scraped directly); a person reviews it. Unreviewed cards are used with lower weight and marked "AI-drafted".
2. **Framing match.** For each topic's framings, the AI maps which framings match each claimer's card
   (`TASK:map_framings_to_claimers`), with a quoted justification. Mappings are stored and editable.
3. **Observations.** After labelling, for each (source, topic, claimer) record: framed items, items matching,
   and the topic baseline (share of all other sources matching).
4. **Distinctiveness.** Only topics where the claimer's framing is neither universal nor absent count
   (baseline echo rate between 10% and 90%); agreeing with what everyone says carries no signal.
5. **Score.** Exponentially decayed counts (half-life 90 days, configurable):
   `A = 100 * (sum(d*matches) + k*b) / (sum(d*framed) + k)`, where `d` is the decay weight, `b` the population
   mean echo rate for that claimer, and `k` a shrinkage strength (about 10 items). With little data, A stays near
   typical. Report the interval from the effective sample size, and also "vs typical outlet" (A minus b).
6. **Eligibility.** Minimum effective items (outlets 20, accounts 40) across a minimum number of topics (5).
   Below that: "not enough data".
7. **Overlapping claimers.** Count a framing for a claimer only if it differs from at least one other claimer's
   position on that topic, so shared positions (for example two allies) are not double counted.

## Combined view (proposed rule)
Always shown with a **basis tag** and an interval.

| Situation | Combined value | Basis tag |
|---|---|---|
| Documented claim exists | the structural value | `documented` (alignment shown beside it as a consistency check) |
| Only reported or alleged claims | blend: `w*structural + (1-w)*alignment`, w = 0.6 reported, 0.3 alleged | `reported + behaviour` or `alleged + behaviour` |
| No claims | the alignment score | `inferred only` |
| Neither | unknown | none |

**Divergence flag:** documented connection high but alignment low (or the reverse) is shown as a finding
("funded by X but does not echo its line"), not averaged away.

## Outputs
- **Report:** a source card per outlet or account: documented connection, alignment with interval and sample
  size, combined view with basis, and links to the evidence. Sorting and filtering by claimer and score.
- **Shift alerts:** when a source's alignment changes by 20 or more points between 30-day windows with
  non-overlapping intervals, when its top-aligned claimer changes, or when a new documented claim is added.
  Debounced, listed in a "Shifts" section of the daily report; extra channel (GitHub issue, email) is open.
- **Knowledge base feed:** alignment results are written as claims with predicate `narrative_aligned_with`,
  status `inferred`, asserted by "HameNews scoring vN", with pointers to the observations. They are
  excluded from the structural score and from position cards, so they can never prove themselves. A person can
  promote a claim only by attaching an independent source.

## Data model additions
- `claimers.jsonl`: id, name, type, aliases, official_channels.
- `position_cards.jsonl`: claimer, topic, summary, key_claims, source_urls, drafted_by, reviewed, valid_from.
- `framing_matches.jsonl`: topic, framing_id, claimer, matches (bool), justification, reviewed.
- `alignment_observations.jsonl`: source, topic, claimer, date, framed, matched, baseline.
- `scores.jsonl`: source, claimer, date, version, structural {value, claims, disputed},
  alignment {value, low, high, n_eff, topics}, combined {value, basis, divergence}.

## Config sketch
```yaml
scoring:
  enabled: false                 # experimental until validation passes
  half_life_days: 90
  shrinkage_k: 10
  min_items: {outlet: 20, account: 40}
  min_topics: 5
  structural_weights: {owned: 100, organ: 90, appointed: 80, partial: 60, former_staff: 25}
  status_multiplier: {documented: 1.0, self_described: 1.0, reported: 0.7, alleged: 0.3}
  alert_delta: 20
claimers:
  - {id: israel, type: state}
  - {id: usa, type: state}
  - {id: iran, type: state}
```

## Validation (a gate before scores appear in reports)
- **Anchor set:** outlets with documented ties (the state-linked agencies) should rank high for their own
  claimer. Measure rank quality (AUC) of alignment against known pairs versus unrelated pairs.
- **Negative controls:** independent cooperatives (for example AP, dpa) should not outrank state-linked outlets
  for their own claimer's narrative.
- **Acceptance:** AUC of at least 0.75 on anchors across claimers, and stable ranks when the window is split
  in two. Until met, scores are behind `scoring.enabled: false` and labelled experimental.
- **Human spot checks:** review the top and bottom outlets per claimer each month; record disagreements.
- **Unit tests:** formulas (decay, shrinkage, intervals, distinctiveness), combined-view rule, no-circularity
  rule, eligibility, status multipliers, "unknown is not zero".

## Open questions
1. Is 0-100 alignment read as "echo rate" intuitive enough, or should it be centred (0 = typical outlet)?
2. Who reviews position cards, and how often? An unreviewed card should probably carry a visible penalty.
3. How are positions for armed groups gathered safely (reporting that quotes them versus their own channels)?
4. Parties and politicians overlap with the left/right leaning feature. Merge later (leaning derived from
   party alignment) or keep separate?
5. Individuals: minimum evidence and which accounts may be scored at all (public figures and organisations only?).
6. Alert channel beyond the report: GitHub issue, email, or none.
7. How should a claimer's position that changes over time be versioned on its card?

## Tasks
1. Claimers config and position cards (draft from channels, review flow).
2. Framing-to-claimer mapping step and storage.
3. Observation log from the existing labelling step.
4. Structural score from claims (interim seed from `agencies.py`).
5. Alignment score with decay, shrinkage and intervals.
6. Validation harness and the acceptance gate.
7. Combined view and divergence flag.
8. Report source cards, sorting and filtering, shifts section.
9. Knowledge-base feed with the no-circularity rule.
10. Alert channel.
