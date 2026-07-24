# Build log, overnight autonomous build

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
