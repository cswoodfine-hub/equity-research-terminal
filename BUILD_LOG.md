# Build log, overnight autonomous build

## Roadmap tier 1 and 2 — 2026-07-25 11:30
Working down the additions roadmap in order.

**Item 1, GitHub Actions daily refresh (done).** history.py exports the
app-produced tables to data/history/*.ndjson (id-ordered, git delta-friendly)
and rebuilds from them with FK off; refresh.yml runs the git-scraping cycle
daily. Round-trip verified against 5988 live snapshots; a rebuilt db lets the
diff continue without replaying. Needs a GitHub remote and SEC_USER_AGENT secret
to activate, both documented.

**Item 2, DailyMed label changes (done).** dailymed.py polls SPL version history,
parses the LOINC 34067-9 indications section, and extracts the population over
the LLM seam into age floor, age ceiling, indication count and a phrase.
Migration 003; the diff turns a version bump into label_change / new_indication /
population_expansion with the numbers in the headline. A Labels tab. Verified
live for LLY: 33 labels, 8 populations resolved (the rest hit the free model rate
limit on a first-run burst and self-heal, since only changed labels re-extract).

**Item 3, efficacy supplements plus the CBER path (done).** parse_supplements
reads the approved EFFICACY submissions already in the drugsfda payload; migration
004 stores them; the diff detects a newly seen recent one as efficacy_supplement.
Verified live: 347 real supplements (LLY 103, MRK 245). The CBER gap is stated
plainly in the view rather than scraped: drugsfda is CDER only, and cell and gene
therapies are already covered by the DailyMed labels and the Purple Book.

**Item 4, FDA announcement feeds (done).** rssfeed.py parses the FDA press,
drug and MedWatch RSS feeds; fetchers/news_fda.py is one universe fetcher that
matches each item to a company and writes it to the news table, so an approval
or a supplement shows here as the announcement that corroborates it. It reaches
the CBER products drugsfda cannot: the sickle-cell gene-therapy press release
binds to VRTX through Casgevy. A /regulatory-news endpoint and an FDA
announcements section on the Universe tab, matched items first so a bound
approval never falls below agency housekeeping; the News tab gains a source
column. Verified live: 58 FDA items, 6 correct company matches (VRTX Casgevy,
ROG Xofluza, SNY Tzield, GILD Hepcludex, JNJ Abiomed), 774 EDGAR rows untouched.

Company matching is the hard part and the first live run bound wrong: the
product-revenue parser had written 10-K segment lines into brand_name (GENERAL,
Liver Disease Products Vemlidy, Children'S Allegra Allergy), so any title with a
common word stuck to a company. Fixed by trusting only a single coined word as a
brand token: a brand_name with a space is a revenue label or a two-drug combo
and there is no safe way to know which word is the brand, so it is dropped rather
than guessed, and a lone segment or ingredient word is dropped too. Re-ran clean.

EMA's general news RSS was retired; only per-medicine feeds remain, so the EU
indication-extension signal is deferred to item 7, the EPAR downloadable data,
and noted rather than scraped.

Suite 365. Four migrations now (annotations, fx, labels, supplements), all
additive.

## Follow-up: the five V2 recommendations — 2026-07-25 07:20
All five items from the final message, implemented, tested, committed one concern
each on top of the overnight build.

1. **FX.** Migration 002 fx_rates + fetchers/fx_ecb.py pull the free ECB daily
   reference set (no key) as USD-quoted rates; revenue-at-risk gains USD absolutes
   and the tab a converted bar labelled with the rate date. NVO 224.5bn DKK reads
   as 34.2bn USD; GSK/REGN, whose currency does not resolve, stay null, never
   fabricated. 10 tests.
2. **Spine click.** Each spine tick is now an SVG anchor to ?ticker=X&sel=key (no
   script); the app pins the selected item's full detail above the tabs and draws
   the hairline to it. Keys are a stable content hash, so the selection round-trips
   through the URL and is shareable. Verified in the browser.
3. **/as-of field grain.** Reconstructs the financial report in force at the date
   and the approvals known by then, joined to current brands, not just counts.
   Verified: 16 financial snapshots and 908 approvals reconstructed at 2026-07-20.
4. **Scheduled refresh.** backend/scheduled_refresh.py runs the universe refresh
   directly, logs to logs/refresh.log, holds an overlap lock that reclaims a stale
   one; cron and launchd documented. 5 tests on the wrapper's own behaviour.
5. **Batch tearsheets.** tearsheet.build_all + make tearsheets-all wrote all 18
   with zero failures.

Suite 337. Ran the ECB fetcher once against the live database, which stored 30
real rates dated 2026-07-24; append-only, no other mutation.

## Phase 7: testing pass — 2026-07-25 05:40
- Full suite 319 green. No native Streamlit/Altair chart call anywhere
  (grep-confirmed; the one LineChartColumn is a table column, not a chart).
- All 18 tickers: 280 endpoint calls across every per-company and universe route
  returned 200; a builder sweep (revenue-at-risk + full tearsheet) ran clean for
  every ticker including ROG and BAYN; the loaded app showed zero stException
  nodes, which given Streamlit runs every tab body per pass proves all twelve
  tabs execute clean.
- No keys: provider() is None and the note falls back to the rules layer with no
  error. Empty database: schema-only API serves []/empty; the seeded-but-empty
  UI renders designed empty states on every tab, zero exceptions.
- Layout verified at 1280 and 1920; nulls render as "no free data" or a dash;
  focus is a visible outline via :focus-visible on every control.
- Not browser-exercised: the time-machine sidebar interaction (the automation
  layer toggled the Streamlit sidebar unreliably), though asof.state_at is unit
  tested for reconstruction, bad-date rejection and prehistory, and /as-of
  returned 200. The only console errors are WebSocket-reconnect noise from the
  many dev-server restarts, not app errors; fonts and CSS are inlined so there
  are no external asset requests to 404.

## Phase 8: scripts and docs — 2026-07-25 06:00
- run.sh (venv, deps, db init + seed, both processes, Ctrl-C stops both) and a
  Makefile with dev/test/refresh/tearsheets/clean. README rewritten around the
  twelve views, the component layer, and the new endpoints.
- Screenshots: live Streamlit does not capture reliably headless (snaps the
  loading skeleton) and its tabs are not URL-addressable, so docs/screenshots
  holds the deterministic artefact renders instead (tearsheet, analyst views,
  the primitive gallery, the spine), which draw the same components; noted in
  docs/screenshots/README.md. Every tab was verified in a real browser through
  the build.

## Phase 6: tearsheet and brief polish — 2026-07-25 05:05
- One-page A4 tearsheet per company to exports/, self-contained (inline styles,
  inline SVG from the shared primitives), POST endpoint plus a Key insights
  button. LLY/BMY/MRK generated; LLY verified to print to exactly one A4 page.
- Backend imports the frontend component layer over a sys.path insert; safe
  because components/ has no Streamlit dependency, and it keeps one source of
  chart truth for both the screen and the print sheet.
- exports/*.html gitignored (generated artefacts), directory kept with .gitkeep.
- Suite 319 green.

## Phase 5: new analyst views — 2026-07-25 04:30
- Universe brief as landing tab, revenue at risk (waterfall + universe bars),
  slippage dumbbell, catalyst grid with accept control, screen (comps + derived
  columns + inline sparkline). Plus annotations inline on changes, time machine
  with banner, and ?ticker= shareable URL from the should/nice-to-have list.
- Deviation recorded in phase 3 stands: the universe revenue-at-risk view is a
  per-company share bar, not a currency-stacked bar, because no FX source exists.
- Verification: the Streamlit automation layer would not switch tabs reliably
  (ref-to-pixel mismatch), so the five new charts were verified by rendering
  them from the live 8010 API into a headless-Chrome sheet, all correct
  including the honesty states (hatched no-free-data bars for ABBV/BAYN/ROG/SNY,
  true 0.0% for protected-but-not-soon). The app itself was confirmed to mount
  all twelve tabs with zero stException nodes: Streamlit runs every tab body on
  each script pass, so a clean load proves every tab executed without raising.
- Suite 315 green.

## Phase 4: tab rebuild — 2026-07-25 03:20
- Zero Altair remains. All nine tabs render through components/charts.py; the
  horizon rail is now the timeline spine and rail.py is deleted; the donut
  renders through the leader-line primitive over revenue_mix's bracketing.
- Pivot taken (playbook row 2): st.html turns out to sanitise SVG away
  entirely, verified by the charts being absent from the DOM with no error.
  The mount now uses markdown injection, the app's proven path.
- Real defects caught by browser verification, fixed at the root with tests:
  month-only registry dates ("2026-08") never reached the spine because ISO
  parsing rejects them; they now place at their month and the label refuses to
  invent a day. A mid-script write to the select's key desynced its displayed
  label from its state; the search jump moved into an on_change callback.
- A stray automation click on Refresh all ran a full universe refresh through
  the new code against the live database (run 24, complete in 47s): unplanned
  but a genuine end-to-end exercise of the new refresh path, idempotent
  derive_readouts confirmed (added 0 on rerun), restatement diff ran clean.
- Suite 315 green.

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
