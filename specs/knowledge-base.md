# Knowledge base: who is connected to whom

**Status:** designed, not built.

## Goal
Remember, for every news agency and account, which states, owners, funders, governments and movements it is
connected to, with sources, so labels are checkable and corrections stick.

## Principles
- **Store claims, not verdicts.** An edge such as "Outlet X backed by State Y" is a claim: who asserted it,
  a source URL, a date and a status. Disputes sit side by side with denials. The tool never merges them
  into one "truth".
- **Facts and judgments are separate.** Ownership, country, registered company and official statements are
  facts. Political leaning and stance are judgments: per topic, dated, with evidence, never a permanent tag.
- **Never aggregate claims into a score.** Show them all in the report, grouped by status.
- **Time matters.** Ownership and funding change (shares transferred, outlets closed). Claims get
  valid_from and valid_to.
- **Individuals:** store only what a person states publicly (bio, verified organisation account). Anything
  inferred from their posts stays tied to a topic and a date.

## Data model (works in tables or a graph)
- **Entity** (id, type, name, aliases, country). Types: outlet, account, person, company, state,
  government body (e.g. IRGC), party or movement.
- **Claim** (subject, predicate, object, asserted_by, source_url, published_date, status, valid_from,
  valid_to, note).
  - predicates: based_in, owned_by, funded_by, affiliated_with, employs, regulated_by, sanctioned_by,
    rated_by (e.g. AllSides).
  - status: documented (filings, official statements), reported (credible outlet citing sources),
    alleged (made by an interested party), self_described, denied.
- **Observation** (entity, topic, framing, evidence, date): what the current per-topic labels already are.

Why the asserter matters: for one outlet, "reported by newspaper A, citing sources: funded by state S",
"denied by the outlet: no state funding" and "alleged by government G: backed by states T and U" are three
different claims, and all three belong in the database.

## Storage options
| Option | Pros | Cons |
|---|---|---|
| JSONL files as source of truth (entities.jsonl, claims.jsonl) | Plain text, easy to review in git, no lock-in; any engine below can load it | Needs a query engine on top |
| DuckDB (embedded, analytical) | Reads JSONL/CSV directly; strong for analytics over observations; graph pattern and path queries via the DuckPGQ community extension (SQL/PGQ) | DuckPGQ is a community extension still under active development; one writer at a time; pin the DuckDB version; check it installs on your Python version |
| SQLite (embedded, row-oriented) | In Python's standard library; mature; good for many small edits; every tool can open it | Graph traversal only through recursive queries; weaker for analytics (irrelevant at this scale) |
| Neo4j or similar graph database | Natural graph queries; good visual explorer | Needs a server or hosted instance; heavier to run on a schedule |

A multi-state link needs no graph database (tables handle many-to-many). A graph helps for multi-hop questions
such as outlet -> owner company -> shareholder -> state -> other outlets tied to that state.

## Decisions
- Model it as a graph of entities and claims, whatever the engine.
- Revised after comparing engines: claims live as JSONL files in the repo; DuckDB is the query layer, using
  plain SQL and recursive queries first and DuckPGQ only for graph-pattern queries. SQLite is the fallback
  if DuckDB gives trouble. Neo4j only if visually exploring the network becomes the main use.
- Do not commit the database file itself (binary, diffs badly); rebuild it from the JSONL each run.

## Open questions
- Does `pip install duckdb` work on the Python version in use (3.14)?
- Who curates claims: manual entry only, or AI-proposed claims reviewed by hand before they are stored?
- How are conflicting claims about the same fact displayed without implying a verdict?

## Tasks
1. Facts first: country, owner, funding with sources. Seed from `trendwatch/agencies.py` and
   `data/outlet_groups.json`.
2. Claims with status and asserter; reference ratings (AllSides, MBFC, Ad Fontes) stored as claims tagged by
   rater, after checking each rater's licence.
3. Link per-topic observations to entities.
4. Report: show "what each side says" next to the stored background claims for that outlet.
5. Only then: cross-topic summaries.
