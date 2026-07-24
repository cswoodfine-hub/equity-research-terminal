# Research notes, overnight build

Read before implementation: TERMINAL_OVERVIEW.md, backend/main.py, db.py, schema.sql,
insights.py, whatchanged.py, diff.py, refresh.py, comps.py, frontend/streamlit_app.py,
theme.py. Facts below verified against the live database, not assumed.

## Current tab structure and chart inventory

Nine tabs: Key insights, Prices, Financials, Pipeline, LOE, Approvals, Catalysts,
Comps, News. One company selected at top drives everything; a horizon rail (hand SVG,
`rail.py`) sits in a right column on every tab.

Where charts render today:

| View | Renderer | Note |
|---|---|---|
| Intraday sparkline (Key insights) | Altair | line + session rules |
| Price chart (Prices) | Altair | interactive zoom, hover crosshair |
| Growth against margin (Financials) | hand SVG `trend.py` | dual axis, 4 quarters |
| Pipeline area bars (Pipeline) | Altair | stacked by phase, dim on select |
| LOE cliff (LOE) | Altair | per-company bar chart |
| Revenue mix donut (Approvals) | hand SVG `revenue_mix.py` | inside labels |
| Catalyst calendar (Catalysts) | hand HTML `calendar_view.py` | month grid |
| Phase matrix (Comps) | Altair | heatmap, sqrt colour ramp |
| Growth/margin scatter (Comps) | Altair | universe scatter |
| Horizon rail (all tabs) | hand SVG `rail.py` | three stacked windows |

Native Streamlit chart calls: none (`st.line_chart` etc. unused). All Altair goes
through one `chart()` helper. `st.dataframe` used for tables (stays; it is a table,
not a chart). `st.html` is available (Streamlit 1.50).

## Schema facts (from schema.sql, confirmed against the DB)

- `asset_revenue(asset_id, fiscal_year, value, unit, source, is_curated)` unique per
  asset-year. **15 of 18 tickers have rows** (missing: ABBV, ROG, BAYN; GSK and REGN
  partial). NVO is DKK, sums are in reporting currency.
- `exclusivities(asset_id, protection_type, expiry_date, source)`; orphan exclusivity
  excluded from cliffs via `loe.NOT_A_CLIFF`.
- Protected assets that also carry revenue, per ticker: BMY 16, MRK 14, NVS 13,
  AZN 12, JNJ 7, BIIB 7, AMGN 6, PFE 5, NVO 4, LLY 3, SNY 3, VRTX 3, GILD 1,
  ABBV/GSK/REGN/ROG/BAYN 0. The unpriced band is a real, large state, exactly as the
  brief expects.
- `changes` currently holds **10 rows, all new_approval**. `diff.py` does emit
  `date_slip` (later date, medium) and `date_change` (earlier date, low) plus
  status_change / phase_advance / phase_regress, but no date moves have been captured
  yet. The slippage view therefore ships against seeded tests and a designed empty
  state on live data; it fills as refreshes accumulate.
- `snapshots`: per-trial (2578), per-filing (960), per-approval (908), plus
  per-company payloads for prices/financials. `/as-of` can honestly reconstruct
  trial state at a date; other entities reconstruct at company granularity.
- `catalysts`: 218 rows, all derived data readouts, none curated, no PDUFA yet.
- `asset_indications` is **empty**. "Revenue per Phase 3 asset" would be a fiction;
  the screen column is computed and named per Phase 3 *trial* instead.
- Prices: 5 years daily for all 18 (2021-07 to 2026-07), 15m intraday for recents.
- No `annotations` table: added by migration 001 (additive).

## Decisions

1. **Component layer**: `frontend/components/` with `tokens.py`, `charts.py` (ten
   pure SVG builders), `render.py` (st.html wrapper with explicit dimensions).
   Hand SVG with fixed viewBox is what already defeats the hidden-tab collapse.
2. **Palette**: the six brief values plus the given phase ramp go into tokens as the
   single source. `theme.P` (dark) is re-pointed at the token values so every
   existing SVG module shifts palette in one move; light mode is retired from the
   default path (terminal is dark by design brief). Mapping: ground=#0C1417,
   panel/raised=#131E22, rule=#1F2E33, text/ink=#E8EDEA, muted/stale=#7E9098,
   up/data=#4C9A7A, down/oxblood=#C4553B, flag=#D9B26B. rule_strong derived one step
   lighter (#2E4249) for stronger hairlines; modality keeps its two labelled colours,
   retuned to sit in the palette (orange book #C98A4B, purple book #8B7FC7). No
   gradients anywhere.
3. **Interactivity**: st.html strips scripts, so drag-to-zoom on the price chart is
   replaced by the existing window buttons plus a pure-CSS hover crosshair per bar
   band (the pivot playbook's fallback). Recorded as a deviation.
4. **Slippage change basis**: computed from `changes` rows with
   `change_type IN ('date_slip','date_change')`, summing signed day moves per trial
   since first observation. diff.py already emits both; nothing new to add there.
5. **Materiality**: thresholds move to `backend/materiality.py`; diff.py and
   whatchanged.py import them. Phase 3 slips over 30 days upgrade to high (new), and
   the feed carries a `reason` naming the rule that flagged an item.
6. **Screen denominator**: Phase 3 trial count (in-development, lead sponsored), not
   assets, since asset mapping is empty. Column named "revenue per Phase 3 trial".
7. **API base**: frontend default becomes `ER_API_BASE` env var falling back to
   localhost:8000, so run.sh can wire the pair without editing code.
8. **Verification rig**: worktree API on port 8010 against the main DB
   (`ER_TOOL_DB`), worktree Streamlit on 8502. The user's own 8000/8501 instances
   stay untouched.
9. **Fonts**: Archivo, Archivo Narrow, IBM Plex Mono, Newsreader downloaded as woff2
   into `frontend/assets/fonts/`, served inline as base64 `@font-face` (Streamlit
   cannot serve arbitrary static files without config; base64 keeps it one file).
   If download fails: closest system stack, logged.

## Terminal density conventions studied

From Bloomberg-style terminals and the existing codebase's own conventions: fixed
right rail; tabular numerals everywhere; figures right-aligned; units in headers,
never cells; hairline rules over boxes; caps-and-tracking section labels; one accent
hue spent on data, never chrome; sub-row sparklines in screens; dashes for absent
values. The existing theme.py already does much of this; the rebuild keeps its rules
and moves the palette and type to the brief's tokens.
