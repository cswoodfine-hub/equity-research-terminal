# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

One analyst, who is also the operator and the builder. Confirmed 2026-11-17: nobody else
uses it, and the Streamlit Cloud deployment is the same person's remote access, not a
shared link.

The analyst runs independent biopharma equity research, knows the domain, and reads raw
filings without help. The job each morning is the sell-side one: what moved in my
universe, and does it change a view. They want speed and signal, not hand-holding, and
trust the tool only as long as it never fabricates a value.

No first-time visitor, no onboarding audience and no second role exists. Do not design
for one unless this section changes.

## Product Purpose

Novatalis Lens is an equity research terminal for biopharma. It is one loop, and neither
half is the product without the other (confirmed 2026-11-17):

1. Detect. A refresh pulls every source, writes a timestamped snapshot, and diffs it
   against the last one to produce a ranked change feed.
2. Reflow. A change moves the drug-level forecast: probability of success, launch and
   loss-of-exclusivity dates, the revenue curve.
3. Value. The forecast rolls up to risked NPV and a fair value per company, read against
   the price.

Success is a view the analyst can defend: every figure traceable to a source or to a
logged assumption, and every change in the view traceable to the event that caused it.

## Positioning

- Change detection and synthesis over free data, not raw data breadth. The paid tools
  that consolidate this data (Evaluate, Citeline, Visible Alpha, IQVIA) cost six figures;
  this watches a defined universe, flags what moved, and carries it through to value.
- Snapshots are the product. History is never overwritten, so the terminal accumulates a
  time series of how each pipeline, filing set and exclusivity position moved, which
  cannot be bought after the fact.
- Never a fabricated value. A gap is shown as a gap ("no free data"), never an estimate.

## Operating Context

- A daily, single-operator instrument. The scheduled refresh runs at 06:00 UTC, before
  any market opens; a second weekday pass at 10:00 UTC reads the daily pulse only.
- Runs locally as two processes (FastAPI on 8000, Streamlit on 8501) and as one process
  on Streamlit Cloud.
- A company selector drives every tab. The tab set depends on the company's engine:
  Universe, Key insights, Prices, Financials, Pipeline, Portfolio, Catalysts, Forecast,
  Themes, Runway, Comps, Holdings.
- The universe is partitioned once into three engines, and each asks only what its
  cohort can answer:
  - Big pharma: where the revenue comes from and when it stops.
  - Biotech: whether the next readout is funded and what reaches the market.
  - Cell and gene: which platform, who is furthest, and who runs out of money first.
- The seed file (`data/companies_seed.csv`) is the authority on the universe: 75
  companies on 2026-11-17, grown from the original 18 large caps.
- Analyst conventions the forecast follows come from a call with a sell-side biopharma
  research ED on 2026-08-06 and are recorded in `docs/ROADMAP.md`: everything is relative
  to consensus, PoS ramps by phase, FX is an explicit line, the DCF rolls into a 12-month
  forward price target.
- A one-page A4 company tearsheet (`exports/`) is the print artefact.

## Capabilities and Constraints

Terminology:

- The unit of analysis is the asset-indication pair, not the company.
- "The book" is the set of modelled assets and the valuations built on them.
- LOE is loss of exclusivity. LOE dates are US only (Orange Book, Purple Book).
- A dash means no free data, not zero.

Constraints that bind every surface:

- Null over estimate. If a source has no value the UI says so.
- Free sources only. No paid subscriptions. A source behind a login is allowed only
  under the conditions in `CLAUDE.md`, and any view built on one says so.
- The UI states its own caveats in place: US-only LOE, partial biologic coverage,
  "Medicare Part D only" with its year or release, "Medicaid only, before rebates",
  and the NLM attribution on any view built on RxNav.
- Payer access data (Part D, Medicaid) is display only. No forecast, rNPV, fair value,
  PoS or rating reads it, and a test enforces that.
- The daily pulse is an AI summary of the trade press. Every view labels it "Daily
  pulse (AI summary)", each item keeps its link, and it never becomes a value, a deal
  term or a catalyst.
- Generated notes are traceable to the change ids that produced them. The app works
  with no LLM key and falls back to a rules-only note.

Technical facts that shape the interface:

- The UI is Streamlit, not the React build `CLAUDE.md` first planned. Every chart is a
  hand-built SVG component inlined into the page (`frontend/components/charts.py`);
  there are no native Streamlit or Altair charts, because Streamlit collapses a chart
  rendered inside a hidden tab.
- Tab state is not URL-addressable, and a hydrating Streamlit page does not screenshot
  reliably headless.
- Colour, type and spacing come from one token set (`frontend/assets/tokens.css`,
  mirrored in `frontend/components/tokens.py`, kept in step by a test). No value is
  hardcoded outside those two files. Streamlit's own chrome reads
  `.streamlit/config.toml`, which mirrors the same tokens.

Open decisions:

- The in-app title still reads "Equity research terminal" and the cloud user agent
  reads "NovatalisTerminal". Both are expected to follow the name; no date is set.
- `README.md`, `TERMINAL_OVERVIEW.md` and `docs/PRD.md` still describe the 18-company,
  change-detection-only product. They are history, not the current record.

## Brand Commitments

- Name: Novatalis Lens. Novatalis is the house name and Lens is this product (confirmed
  2026-11-17).
- House style for generated text and UI copy, from `CLAUDE.md`: sentence-case headings,
  no em dashes, direct and unhedged, specific over abstract, lead with the number or the
  change. Banned words: additionally, highlight, underscore, pivotal, showcase,
  testament.
- A NOVATALIS wordmark exists on the front door (the engine picker), set in type. No
  logo mark or tagline exists. Do not invent one.

## Evidence on Hand

- A running interface of about 28,000 lines under `frontend/`, with its token set and
  locally shipped fonts in `frontend/assets/`. No DESIGN.md records it yet.
- Design plans per surface in `docs/design/` (Forecast tab, Comps, Key insights,
  company scorecard, strategy lab and others).
- Deterministic renders in `docs/screenshots/` (tearsheet, analyst views, chart
  primitives, spine and donut). They predate the three-engine split; check them against
  the running app before treating them as current.
- Model audits with measured figures: `docs/what_is_modelled.md`,
  `docs/where_the_gap_is.md`, `docs/ACTION_PLAN.md`.
- Live data in the SQLite database and the committed snapshot history.

Absent, and not to be fabricated: customers, testimonials, press, pricing, usage
figures, a track record of calls, and any claim that the tool beats a benchmark.

## Product Principles

1. A gap is information. Show what is missing and why, in the place it is missing.
2. Every figure answers "where did this come from": a source, a date, or a logged
   assumption the analyst can change.
3. Ask each company only what its engine can answer. A metric a cohort cannot fill is a
   question put to the wrong company, not a hole in the data.
4. Lead with the change and the number. The analyst opens it to learn what moved and
   what that does to value, not to browse.
5. Built for one expert. Density and speed outrank explanation; a caveat is stated once,
   where it applies.
