# Product requirements: pharma equity research terminal

## Summary

A single-user research terminal covering large-cap pharma. The analyst presses refresh, the app pulls live and near-live data from free sources, snapshots it, computes what changed since the last snapshot, and shows charts plus a short written note per company. It answers the question a sell-side analyst asks every morning: what moved in my universe, and does it change a view.

The differentiator is change detection and synthesis over free data, not raw data breadth. The paid tools that consolidate this data cost six figures. This tool watches a defined universe, flags changes, and writes them up.

## Problem

The data an analyst checks daily is scattered across price feeds, EDGAR, ClinicalTrials.gov, FDA databases, and IR pages. Evaluate, Citeline, Visible Alpha, and IQVIA consolidate it at prices that put them out of reach for independent research. No free tool watches a fixed universe, detects changes, and produces a note. This builds one.

## Goals

- Cover a fixed universe of large-cap pharma at the asset-indication level.
- One refresh brings every source up to date and reports per-source status.
- Detect and rank changes since the last refresh.
- Render the standard analyst views as charts.
- Produce a short written note per company from the detected changes.

## Non-goals (v1)

- Real-time streaming prices. On-demand refresh is enough.
- Small and mid-cap coverage. Fixed large-cap universe only.
- Paid data such as prescription volumes and product-level consensus. Gaps are labelled, not filled.
- Multi-user accounts, auth, and deployment. Runs locally for one analyst.

## User

One analyst running independent biotech research. Comfortable with the domain and with reading raw filings. Wants speed and signal, not hand-holding, and will trust the tool only if it never fabricates data.

## Company universe (v1)

LLY, NVO, MRK, PFE, ABBV, JNJ, AZN, GSK, NVS, ROG, SNY, BMY, AMGN, GILD, VRTX, REGN, BIIB, BAYN. Seeded from `data/companies_seed.csv`. Extending the universe is a config change, not a code change.

## Data sources and coverage

| Data | Source | Cost | Cadence |
|---|---|---|---|
| Prices, market cap | yfinance (or FMP) | free / cheap | on demand, 15-min TTL |
| Reported financials | EDGAR XBRL company-facts | free | daily |
| Filings (8-K, 6-K, 20-F) | EDGAR submissions | free | daily |
| Pipeline and trials | ClinicalTrials.gov v2 | free | daily |
| Approvals, labels, safety | openFDA | free | daily |
| LOE, patent expiry | Orange Book, Purple Book | free | weekly |
| Catalysts (PDUFA, readouts) | curated table + auto extraction | free | manual |
| News | IR RSS + EDGAR 8-K | free | daily |
| Consensus EPS / revenue | FMP paid tier | cheap | daily |

Two data-landscape facts to build around:

- Roche (ROG / RHHBY) and Bayer (BAYN / BAYRY) are not SEC registrants. Their US listings are OTC ADR programs, so EDGAR holds nothing for them. Financials for these two come from company IR, not EDGAR. The seed CSV marks them with `is_sec_filer = 0`.
- The European names that do file (NVO, AZN, GSK, NVS, SNY) submit 20-F annually and 6-K for interim and material events, not 10-K and 8-K. The filings fetcher handles both form families.

Not available free, and labelled as such in the UI: prescription and script data, product-level revenue consensus, aggregated analyst price targets.

## Core data model

The central table is `asset_indications`, one row per drug per indication with phase, status, region, and a derived next catalyst. Companies own assets, assets appear in indications, and catalysts and trials attach to the pair. Full schema in `db/schema.sql`.

The `snapshots` table captures the tracked fields of each entity on every refresh. The `changes` table stores the computed diffs. Snapshots are never overwritten, so the change history is continuous and, over months, becomes a time series of pipeline and estimate movement that no vendor sells. See `CLAUDE.md` for why this is the core of the product.

## Features

### Refresh

One button, one endpoint. Runs fetchers concurrently, respects per-source TTLs, and writes a `refresh_runs` row with per-source counts, errors, and timings. The UI shows last-updated per source and a running, complete, or partial state. A refresh inside a source's TTL is a no-op for that source and says so.

### Views

- Pipeline heatmap: companies down the side, phases across the top, asset counts in cells, colour by phase. Clicking a cell lists the asset-indications behind it.
- LOE cliff chart: revenue by asset over time, shaded by expiry year, so the patent cliff is visible per company and across the universe.
- Catalyst calendar: the next 90 days of PDUFA dates, data readouts, and regulatory decisions from the catalysts table.
- Comps table: EV/sales, P/E, and growth side by side, sortable.
- Price performance: each name and the universe against XLV, rebased.
- What changed: the feed described below.

### What changed feed

The core feature. Two layers.

1. Rules layer, always on. Flags trial status changes, primary completion date slips, new 8-K and 6-K filings, catalysts inside 60 days, and LOE exposure above a revenue threshold. Ranks by significance.
2. Note layer, optional. Passes the ranked changes for a company to the Anthropic API and returns a short morning-note paragraph. Falls back to a plain list of the flagged changes if no API key is set.

## Refresh and freshness policy

Per-source TTLs prevent redundant fetches: prices 15 minutes, clinical and regulatory daily, patent files weekly. Every refresh writes snapshots regardless of TTL, so the change history has no gaps even when a source is skipped.

## Build phases

Each phase is one Claude Code session in plan mode.

1. Scaffold: repo, `CLAUDE.md`, schema, seed CSV, empty FastAPI app.
2. Vertical slice: one company end to end, prices to chart to refresh button. Prove the plumbing before generalising.
3. EDGAR financials and the comps table.
4. ClinicalTrials.gov and the pipeline heatmap.
5. Orange Book and Purple Book, the LOE cliff chart, and openFDA approvals.
6. Catalysts table and calendar, news, and the snapshot diff engine.
7. Generated notes and polish.

Fast path: if the React frontend slows you down, build phases 2 to 6 in Streamlit and add the React frontend last. The backend and schema do not change.

## Success criteria

- Refresh completes for all sources with clear per-source status in one action.
- A real change (a trial moving to Active not recruiting, a completion-date slip, a new 8-K) appears in the what-changed feed within one refresh of it happening on the source.
- No fabricated values anywhere. Every gap is labelled.
- The five charts render for the full universe.

## Known limitations and honesty rules

- Trial-to-asset mapping is imperfect and relies on a manual override table.
- No free product-level consensus, so valuation views run on your own assumptions.
- yfinance can break without warning. Price failures are reported, not hidden.
- The tool informs a view. It does not produce investment advice or price targets on its own.

## Future

- rNPV module per asset-indication with editable WACC, PoS, peak sales, and launch year. The assumptions table is already stubbed in the schema.
- Alerting: email or push when a high-significance change lands, so pressing refresh is not required to catch it.
- Estimate-revision tracking once a consensus source is wired in.
