# Build log, overnight autonomous build

## Phase 3: backend analytics — 2026-07-25 02:05
- materiality.py is now the single home of flagging thresholds; diff and
  whatchanged import it, every feed item carries a reason, P3 slips over 30d
  rank high, and revenue restatements over 5% are a new detected change type
  built on asset_revenue snapshots.
- Revenue at risk extends the existing build_exposure rather than duplicating
  it: shares of tagged product revenue, cumulative curve, unpriced band as
  counts. The universe endpoint reports shares only; stacking absolute values
  across DKK, EUR, GBP and USD without an FX source would fabricate a number,
  so the brief's universe stacked-bar-by-year becomes per-company share bars.
  Recorded as a deliberate deviation for honesty.
- Slippage, catalyst grid, screen (revenue per late trial, named for trials
  because asset mapping is empty), as-of reconstruction, annotations with an
  additive migration, /price-grid, /runs/latest. 20 new tests; suite 312.
- Hand checks: BMY 2031 share 0.258 = Eliquis 14.443bn / 56.015bn tagged,
  matches to the third decimal; LLY 5y share 0.0 verified as a true zero under
  the latest-protection convention; as-of 2026-07-01 correctly returns nothing,
  history begins 2026-07-18.
- Observed: refresh run 23 (scope=all) fired tonight from the user's own
  long-running instance on port 8000, not from this build; it pulled fresh
  registry state and the diff wrote 46 real trial changes, which gives the
  slippage view live rows. Append-only history, no conflict.
- Probe annotation created during endpoint verification was deleted; the live
  annotations table is empty.

## Phase 2: chart primitives — 2026-07-25 01:15
- All ten primitives in components/charts.py as pure data-to-SVG functions with
  explicit dimensions; 37 unit tests (validity, mark counts, null paths).
- The null rule surfaced a real defect during testing: a value islanded between
  two nulls was silently dropped because a one-point run cannot draw a polyline.
  Fixed across sparkline, line chart and small multiples: islanded points draw
  as dots. The test was corrected to demand this rather than relaxed.
- Visual smoke test via a headless-Chrome gallery caught three geometry issues
  (colliding series end labels, spine date/label crowding, flag dot on the date)
  and one robustness flaw: the hover CSS lived only in the page stylesheet, so
  an exported chart would paint every tooltip at once. Hover rules now ship
  inside the SVG itself.
- Decisions: drag-to-zoom is not carried by the SVG line chart (no scripts in
  st.html); the price view keeps its window buttons and gains CSS hover
  readouts per slot. Recorded as the pivot playbook's fallback.
- Suite 292 green.

## Phase 1: design system — 2026-07-25 00:45
- tokens.css and components/tokens.py written and mirrored, with a test that fails
  if they drift. Six palette values, phase ramp, spacing base 8, radius 0/2, three
  type roles.
- Ten woff2 files (Archivo 400-700, Archivo Narrow 600, IBM Plex Mono 400-600,
  Newsreader 400-500) downloaded from Fontsource and bundled in assets/fonts,
  162KB total, inlined as base64 @font-face with font-display swap. No CDN.
- theme.py rebuilt on the tokens; the legacy Palette field names stay as the
  compatibility layer so rail, trend, revenue_mix and calendar_view shift palette
  without edits. Light palette retained only for the ramp tests.
- Top bar: sticky strip with ticker select, identity, global search (Enter jumps
  to ticker or company-name match), last-refresh state from new GET /runs/latest,
  and a universe refresh button. All inputs squared; figures in mono.
- Decisions: fonts inline rather than static-served (no config dependency);
  widget styling global rather than wrapper-scoped, since Streamlit's sanitiser
  closes injected wrapper divs before widgets mount.
- Pivots: none. Suite 255 green. Shell verified in the browser on live data.
- Known issues: browser pane is 764px wide, so 1280/1920 layout checks move to
  headless-Chrome screenshots in phase 7.

## Phase 0: research — 2026-07-25 00:05
- Read every file named in the brief plus refresh.py, comps.py, theme.py in full.
- Verified schema and data coverage against the live database; findings and all
  decisions in RESEARCH_NOTES.md.
- Notable: changes table holds only new_approval rows so far, so the slippage view
  ships with a designed empty state on live data and seeded tests; asset_indications
  is empty, so the screen's per-asset column is computed per Phase 3 trial and named
  so; 15 of 18 tickers carry product revenue, so revenue-at-risk is real for most
  and the unpriced band carries ABBV, GSK, REGN, ROG, BAYN.
- Pivots taken: none yet.
- Known issues: none yet.
