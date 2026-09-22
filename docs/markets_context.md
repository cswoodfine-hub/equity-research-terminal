<!-- Build record. All ten builds are implemented, on main from 16b818b to c478cf8. -->

## What was built, and where the plan was wrong

All ten builds are done. The plan below is kept as written, because the reasoning in it
is what the work was argued from, but eight of its claims did not survive contact with
the data and the corrections matter more than the plan does:

- **The betas are not stale.** Recomputed against a now-current index, all nineteen
  came back within 0.01 of the stored value, mean absolute difference 0.004. The
  "windows as old as 2021-W34" the plan cites is the START of a conventional five-year
  window. Build 6 reports the measurement and adopts nothing.
- **AbbVie's debt weight is 0.123, not 0.433.** The most levered covered name is Pfizer
  at 0.280. Every per-share rate figure now comes from `backend/tools/rate_sensitivity.py`,
  which reruns the book rather than deriving from an elasticity.
- **Biogen's guidance basis is not null.** Its own note says "Growth on a reported basis
  ... assuming foreign exchange rates as of July 24, 2026", which is the stated-rate-date
  case exactly.
- **A deselection does not need the Remarks prose.** `negotiated_prices.update_kind`
  separates Deselect from the annual Inflation rebasing directly.
- **A full browser User-Agent does not work on the Yahoo endpoint.** Measured: the
  repo's own string 200 on 15 of 15, no string 429 on 13 of 13, a browser string 200 on
  only 4 of 16. The 429 is a classifier on the string, not a rate limit that decays.
- **The BIS lane needs a title gate too**, not just the CMS one. Agency plus term alone
  carries a Framework for Artificial Intelligence Diffusion into a pharmaceutical
  tariff lane.
- **China in-licensing cannot be identified as in-licensing.** A headline does not
  state direction reliably: Alnylam's agreement for commercialisation in China is
  Alnylam licensing out. Build 10 counts China-linked business development and refuses
  to claim the direction.
- **`ira.exposure` needed a company-level gate that did not exist**, and its output must
  never be called revenue at risk. It is Medicare gross spending at list against net
  revenue, which reads 47.7% on Bristol Myers.

Two defects on the revaluation path were found and fixed along the way, neither of them
in the plan: `breakpoints.Book.price_gap` never charged the rebuilt book for growth
capital, and the stub carry was frozen at the base cost of equity. Together they turned
Lilly's discount band from minus 5 and plus 138 a share into minus 59 and plus 75.

One assumption was restated and it is the largest single change in the sequence. The
equity risk premium moved from an undated 0.05 to the published 4.14% of 1 September
2026, which raised equity per share by a median 6.44% and moved the book's median gap
to the close from about -7% to +6.1%. That is one assumption changing, not new evidence
about any company.

---



# Markets context: how to go about it

Written 2026-09-22 from a four-way design pass over the codebase, live checks on every
endpoint proposed, three judges and a critic pass. Spot-checks below were re-run by hand
against the live database and the running API before the note was filed.

## Verification notes, added after the pass

Confirmed by hand on 2026-09-22:

- `forecast.wacc` (backend/forecast.py:332-343) computes `kd = cost_of_debt * (1 - tax)`,
  so the credit leg carries the tax shield and a spread move is worth
  `debt_weight * (1 - tax_rate)` of WACC, not `debt_weight`.
- `breakpoints.Book.price_gap` builds equity as
  `(new_book + future) * carry + net_cash + other_claims` and never subtracts the growth
  charge that `forecast_view.company_verdict` takes out of enterprise value
  (`ev = m_rnpv + p_rnpv + s_rnpv + f_value - g_value`). Lilly's charge is 54.37 a share
  today, 57.65 once carried, which is the size of the error in every revalued book.
- `rates_fred.py`, `negotiated_prices_cms.py` and `ndc_marketing.py` contain no
  `fetch_kind` at all, so their TTLs are inert.
- `risk_free` 0.0501 sits on 382 assumption rows, `cost_of_debt` 0.056 on 382, `erp` 0.05
  on 378 sourced "Damodaran US ERP estimate" with no date and no URL.
- `market_rates` holds 275 to 290 observations per series, 2025-08-14 to 2026-09-18.

Two claims in the pass are corrected here and the builds below should be read against
these, not against their own text:

- **Beta is not stale.** The stored windows end 2026-W35 and 2026-W36, two weeks old.
  "2021-W34" is the start of a conventional five-year window. Build 6b's value is the
  relative-performance half, not a beta refresh.
- **Benchmark prices already exist.** `benchmark_prices` holds 2,513 rows of ^GSPC from
  2016-09-02 to 2026-09-02, written by `beta.py` as a one-off. It is not registered in
  `refresh.py`, so it never updates. Build 6a is wiring and a symbol list, not a new
  table.

Also verified live: the Yahoo chart endpoint the price fetcher already calls serves
^GSPC, XLV, XBI, IBB, ^VIX, DX-Y.NYB, ^DRG and EURUSD=X. The `prices` table cannot hold
them, since `company_id` is `NOT NULL REFERENCES companies(id)`. Next free migration is
058.

---

# Global markets context for this terminal

## 1. The answer

Markets context here means the inputs that reprice this book, wired into the two funnels the book already has, plus one strip that says which of them moved today. The terminal already fetches almost all of it and reads almost none of it: 275 to 290 days of DGS10, DFII10, T10YIE and BAMLC0A3CAEY sit in `market_rates` with one consumer, 1170 rows of ECB history sit in `fx_rates` with one consumer, and every discount rate in the book runs off a risk-free rate of 0.0501 hand-read on 2026-09-16 into 440 rows whose own source string claims it is refreshed with the data.

The principle that decides what gets in is measured size against the model's own noise, ranked on effect times breadth: an item earns a place only if it changes a number, a signal or a decision, and every item states its measured effect and how many names it reaches before it is built. By that test:

1. The risk-free rate. 25bp is a median -3.1% of equity per share across all 16 valued names, DGS10 has travelled 104bp inside the stored window, and scaling the 25bp measurement down to the median 3bp day is roughly -0.4% of equity per share across the whole book, every business day.
2. The equity risk premium. All 382 assumption rows and 58 line rows carry `erp` 0.05 sourced "Damodaran US ERP estimate" with no date and no URL, against his published 1 September 2026 figure of 4.14% quoted at a 4.75% risk-free. At beta 1 an 86bp premium error is 86bp of cost of equity on all 16 names, three and a half times the 25bp rate move build 3 exists to catch, and it is the only input in the discount-rate chain a reader cannot trace to a dated source.
3. Beta. 0.1 of beta is 50bp of cost of equity on all 16 names, twice a 25bp rate move, and the 19 stored betas quote windows as old as 2021-W34.
4. The cost of debt. `forecast.wacc` computes `kd = cost_of_debt x (1 - tax)`, so `d(wacc)/d(cost_of_debt)` is `debt_weight x (1 - tax_rate)`, not `debt_weight`. On ABBV that is 0.433 x (1 - 0.1081) = 0.386, so 100bp of spread is 39bp of WACC on the most levered name and nothing on an unlevered one. Six covered companies carry no debt weight at all.
5. FX for a foreign filer. 1:1 pass-through through the per-share divisor, so 1% of krone is 1% of Novo's dollar value, but it reaches only the valued non-USD filers, which is NVO, GSK and SNY: ROG, BAYN and LEGN carry no value against a price. Three of 16 names, at median daily moves of 0.18% to 0.28%.

The build order below is not this ranking. It is cheapest-high-value-first plus dependency: the read side and the two arithmetic defects come before any live input, because once the engine reads a live rate every published number moves between refreshes, and FX comes after the rate because the rate reaches five times as many names for the same day of work.

There is a second admission route, for dated context that carries no modelled number. The first route demands a measured per-share effect, and no policy fact can state one without an applied tariff or price assumption, which section 3 correctly forbids. So without a second route the whole class of pharma policy is excluded by the gate rather than judged. A context item qualifies when it carries a publication date and a stable document or docket id from a primary source, and it is rendered as a horizon-rail item or a cell labelled context. It gets no threshold, no forecast hook and no per-share sentence. What qualifies today: the Section 232 pharmaceutical tariff proceedings, the most-favoured-nation executive order of 2025-05-15, IRA negotiation rulemaking with a comment deadline, and CMS additions to the selected-drug list. Everything else below the first line stays context and is labelled as context.

## 2. The builds

Build 1 is two days of read-side work over data already on disk and no new source, and it gives the reader the standing level that every later change rule is read against. Build 2 is half a day that fixes a number already printed on the page and is the baseline every per-share consequence downstream is measured through. Only then does the engine start reading a live rate. The one new fetcher and the one unofficial source come sixth, after everything that depends only on FRED and the ECB.

### Build 1. The markets strip and the read side. 2 days

Adds the standing level: four rate cells, five FX crosses, each with its own observation date, plus the provenance sentences the app already composes and renders nowhere.

- Sources, both already wired and verified live today, keyless: FRED CSV `https://fred.stlouisfed.org/graph/fredgraph.csv?id={DGS10|DFII10|T10YIE|BAMLC0A3CAEY}` and ECB `https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml` (29 currencies, all five reporting currencies present). Keep `HEADERS = {}` in `rates_fred.py` as the convention, but the real protection is the explicit timeout plus the soft error, since the hang reproduces intermittently and a 200 came back in 0.11s with a Connection header; and reject any body whose first line is not the expected header, because a bad series id returns an HTML shell.
- Licence decision, settled here rather than left open, because this build renders the credit cell. BAMLC0A3CAEY is read internally to set a discount rate, displayed with the ICE Data Indices copyright line on the cell, excluded from `data/history/*.ndjson`, and excluded from the payload any model sees. ICE prohibits reproduction without written permission and FRED cannot grant it, so internal display in a single-user terminal is the whole of the permitted use. If that reading is not acceptable, the credit cell and build 3's cost-of-debt override both come out, and Treasury plus a documented spread replaces them.
- TTL: 12 hours on both, unchanged. Three fixes are owed, one commit each. `rates_fred.py` writes no `fetch_kind` at all, so `base._last_live_fetch_at` finds no live snapshot and the 12-hour TTL is inert. `negotiated_prices_cms.py` and `ndc_marketing.py` have the same defect, and build 8 rests on the first of them, so all three are stamped here the way `adcomm_fedreg` does, before any build claims an existing TTL.
- Storage: none new, no migration. `market_rates(series, as_of, value, source)` and `fx_rates` as they stand.
- Code: `rates_fred.rates_on(db_path, on_date)` and `rates_fred.series(db_path, series, since)` beside `latest()`; `fx.series(db_path, base, since)` mirroring `fx.rates_on`, returning `[]` rather than a partial line when `since` predates 2026-07-24; `GET /markets?days=90` in `main.py` between `/screen` (917) and `/as-of` (929), with the rates half clamped at `rates_fred.KEEP_DAYS` (400) rather than the 1900 copied from `/price-grid`, since the table keeps 400 days and BAMLC0A3CAEY carries only three years on this endpoint.
- The cache, and why its key matters: `latest()` re-reads T10YIE 915 times per break-points call for one company, with a connection each, so it needs a process cache. Keyed on (series, day) it becomes a correctness fault the moment build 3 values the book off it, because a refresh that writes a newer observation mid-session stays invisible until the next day and the strip can print one `as_of` while the valuation uses another. Key it on `MAX(rowid)` of `market_rates` (one cheap read per call) or on the current refresh run id, and test that a write to `market_rates` invalidates it.
- Tests: extend `backend/tests/test_rates_fred.py` (inline CSV stays inline) to assert a suppressed day is a gap and not a carry-forward, that an empty second field parses as null and never as zero, and that `series()` returns the gap; extend `test_fx.py` for `series()` returning `[]` below the first stored date. New `test_markets_route.py` asserts the common-dates rule: intersect the `as_of` sets before any comparison and return None when the intersection is under two points, and never print one strip-level date over four series with three different last observations.
- UI: new `markets_strip(tape)` helper beside `metric_tiles` (`streamlit_app.py:1413`), returning `metric_tiles(items, one_row=True)`; called in the Universe tab between 3779 and 3781 under `section('Markets')` with `note()` beneath, where the rail CSS drops and the block gets full width. Ten cells is the ceiling and every later cell displaces one. That is a layout judgement about what reads on one row at the app's width, not a measurement. Each cell carries its series' own `as_of` in the sixth tuple element. `metric_tiles` already prints "no free data" for a None, which is the whole rendering path for a failed cell. Render the existing `long_run_basis` in the sum-of-the-parts byline (1750-1761), and fix `forecast_note.py:280-287`, which prints 2.34% as "2%" and calls a Treasury breakeven the book's own assumption. Surface the four `fx_as_of` fields already computed and thrown away, and add one to the comps payload, the only converting view that carries none.
- Change rule: none in this build. Licence conditions on the face of the page: cite FRED, carry the ICE BofA line on the credit cell, and cite the ECB with the note that the USD quoting is our own inversion.
- Forecast hook: none yet.

### Build 2. Fix the two defects on the revaluation path. 0.5 days

`breakpoints.Book.price_gap` (241-247) omits the growth-capital charge `company_verdict` subtracts, so every revalued book is high by `growth_investment x carry` per share: LLY +57.65, REGN +28.24, VRTX +23.92, AMGN +12.03. LLY's discount band therefore prints 442.77 / 447.95 / 585.56, which reads as -5.18/+137.61 a share for a point of WACC either way instead of the roughly -63/+80 a rerun produces. Separately it multiplies by a carry frozen at the base cost of equity (213), so a rate trial never re-derives it and understates by about 0.17% per 25bp.

- Subtract `forecast_view._growth_investment` (already computed at 1530-1534) inside `price_gap`, and recompute the carry inside a trial from the trial's own cost of equity. Two commits, one concern each.
- Test: a trial with no change reproduces `company_verdict`'s equity per share exactly.
- Add `backend/tools/rate_sensitivity.py`, a read-only calibration script that reruns `Book.equity_with` per company at `risk_free + 25bp`, at `cost_of_debt + 25bp` and at `erp + 25bp`, printing the per-share effect, the WACC delta and the tax rate and debt weight used. Every per-share figure any note in builds 3, 4 and 5 states is read out of this script at build time and cited to it in the commit message. No per-share consequence is asserted from arithmetic on an elasticity.

### Build 3. The discount-rate chain: live risk-free, live cost of debt, dated premium. 2.5 days

The largest effect that reaches all 16 valued names, and the one build that closes the untraceable term in the chain.

Measured: 25bp of risk-free moves equity per share by -2.61% (SNY) to -3.74% (AZN), median about -3.1%, split roughly evenly between the modelled book and the future pipeline (LLY book 328.6bn to 323.5bn, future pipeline 143.5bn to 134.9bn). The credit leg runs through the tax shield: `d(wacc)/d(cost_of_debt)` is `debt_weight x (1 - tax_rate)`, 0.386 on ABBV at a debt weight of 0.433 and a tax rate of 0.1081, so 25bp of spread is 9.7bp of WACC there and nothing on the six names with no debt weight.

- Sources and TTL: as build 1 for the two live series, no new fetch. The premium is a hand-entered row, not a fetch: `pages.stern.nyu.edu/~adamodar/New_Home_Page/home.htm` is prose on a personal academic site with no stable structure, and no fetcher goes near it.
- Storage: none. Update the 440 seed source strings so they describe what the code now does, and add the ERP row's own dated source string.
- The ERP row carries four things or it does not ship: which of the five published variants it is, the author's own risk-free rate on that date (4.75% against our DGS10 level), whether the 0.22% US default spread is added back, and the publication date. Without them, pairing his premium with our live rate is a silent inconsistency in the same CAPM line.
- Code: `assumptions.load` overrides `risk_free` from DGS10 and `cost_of_debt` from BAMLC0A3CAEY, seed kept as the fallback so the engine still runs with an empty `market_rates`. `erp` stays a stored value and is never overridden from a market series. `forecast.wacc` (332-343) stays pure, taking the rates from the caller rather than importing the fetcher, and its basis extends from "CAPM from components" to name each leg with its own vintage: the series, level and `as_of` for the live legs, and the author, variant and date for the premium. The same override reaches `forecast_view._cost_of_equity` (1179-1192), the independent second funnel behind the fiscal-year-end to close carry. Resolve once per request and thread it like the existing `rates` dict.
- Evidence grades: `evidence.py:83-118` grades off the source text and regrades on refresh, and `breakpoints.CAPM_KEYS` groups the six CAPM rows behind the discount-rate lever, so rewriting 440 source strings moves a lever's grade. Assert the discount-rate lever's grade before and after the rewrite in the same commit, and state the intended grade in the commit message.
- Tests: `test_wacc_live_rate.py` injects a fixed rate through the override and asserts the basis string names series, level, date, and the premium's own vintage; asserts the seed fallback with an empty table. The sweep of every existing per-share assertion is not budgeted, because it is not needed: no test file reads `backend/er_tool.db`, the suite builds temp databases through `db.init(tmp_path)` where `market_rates` is empty, so the seed fallback holds and the figures stay green. One test states that explicitly: a temp database with no `market_rates` row reproduces today's per-share figure through the fallback. `test_forecast_tab_ui.py:99-116` already asserts this intent and passes today for the wrong reason.
- UI: the WACC tile caption (2951-2967, through `_short` at 2119-2125), the assumptions grid source column (2526-2533), the sensitivity grid x-axis basis (`forecast_view.py:272-296`), and a live-rate marker on the WACC slider track (2183-2190), which already steps in 25bp. The premium's cell says dated and names the date; the rate cells say live.
- Change rule: none in this build; the rules are build 4.
- Forecast hook: this is the hook. One change reprices 382 asset rows and 58 line rows.

### Build 4. The signal layer, anchored not delta, and rules only. 2 days

This is the app's stated differentiator and it is disconnected: three stored `market` snapshots have produced zero `changes` rows, and DGS10 went 4.94% to 5.01% between the last two while What Changed says nothing.

The threshold must be anchored to the level the last note was written against, not to the previous snapshot. Measured over the 275 stored DGS10 observations the median daily move is 3bp, p90 is 6bp and the largest is 14bp, and no five-observation window moved 25bp, so a delta rule writes zero rows over the whole 13-month history while the series travels 104bp.

- LLM confinement, decided before the text is written. CLAUDE.md limits the Anthropic API to the note step, and section 3 forbids any model step in the rate, FX or beta path. So no rate paragraph goes into `insights.SYSTEM_PROMPT`, and `_user_content` (called at `insights.py:262`) filters items of kind `market` and `fx` out of the payload the model sees. The macro sentences are composed by `build_rules_note` from the levels and the calibration figures, and appear verbatim in the note beside the model's company paragraphs. This is also what FRED's terms require, which restrict feeding the values into an artificial-intelligence process, and what ICE requires for the credit level, which may not be furnished to a third party.
- Storage: migration `058_market_signal_state.sql`, `market_signal_state(signal_key TEXT PRIMARY KEY, anchor_value REAL NOT NULL, anchor_as_of TEXT NOT NULL, armed INTEGER NOT NULL DEFAULT 1, flagged_at TEXT)`, with the comment block naming the fetcher that writes it and the units.
- Thresholds, in one module constant table with the measured firing rate in the comment so each can be argued with: DGS10 writes a row at 10bp (27 fires in 13 months, about 1.2% of book value) and a note at 25bp (8 fires, about 3.1%); T10YIE at 10bp (8 fires; 25bp fires zero times in 276 observations, so 25bp would be a rule that never runs); BAMLC0A3CAEY at 25bp (4 fires, against 21 at 10bp). Reset the anchor on fire.
- Diff: a `market` branch in `diff.detect_changes` (433-448) on the tracked-field shape, re-writing the snapshot only when a change was emitted, so a re-run is quiet and a first sighting baselines silently. Read the last snapshot that *differs*, not the last snapshot, because both fetchers snapshot on every refresh.
- Routing: an explicit branch in `whatchanged._recent_changes` (81-123) giving a universe-wide rate change the kind `market` with a null ticker, and both the per-company filter and the universe filter keep kind `market` regardless of ticker. Fan out to one row per company only where the consequence genuinely differs per name, which is the cost-of-debt rule. Add the change types to `materiality.change_reason` (57-89), which otherwise falls through to None and prints a change with no reason label.
- Volume and double counting: one macro note per company per refresh, ranked by measured per-share effect. DFII10 gets no rule of its own; when the DGS10 rule fires, decompose the move as the DFII10 delta plus the T10YIE delta over the two dates actually compared, state both dates, and suppress the clause when the components miss the nominal by more than 2bp, which happens when the publication dates do not line up (DGS10 and DFII10 to 2026-09-18, T10YIE to 2026-09-21).
- Note text, with every per-share figure read from `rate_sensitivity.py` and none of it asserted: "The 10-year Treasury is 5.01%, 25bp above the 4.76% this book last priced against. Carried into the risk-free rate, PFE equity per share falls 3.1%, from 31.40 to 30.42. 22bp of the move is the real rate and 3bp is breakeven inflation, so it is not an inflation story. Dates compared: 2026-08-27 and 2026-09-18." And for credit: "Single-A corporate yields are 5.84%, 25bp above the 5.59% the book's cost of debt assumes. At a debt weight of 0.433 and a tax rate of 10.8%, that is 9.7bp of ABBV's WACC and about 2.0% a share. Six covered companies carry no debt weight and do not move." The 2.0% replaces the 0.9% an earlier draft printed, which omitted the tax shield and was wrong by half.
- Tests: `test_market_signals.py` asserts the ratchet fires on a 25bp walk built from three 9bp days, fires once and not twice, writes nothing on a re-run, baselines silently on first sighting, and writes nothing from two snapshots that are not consecutive sessions for that series. A second test asserts no item of kind `market` or `fx` reaches `_user_content`.
- Forecast hook: none new.

### Build 5. FX authority, the FX signal and the currency lens. 1.5 days

The largest per-unit sensitivity in the app and it is silent, though it reaches three valued names rather than sixteen. `forecast_view._to_price_units` (397-423) returns `shares / rate`, so a 5% stronger krone is 5% more dollars of Novo value against an unchanged dollar ADS price. It reaches NVO, GSK, SNY, ROG and BAYN, of which the first three carry a value against a price, takes the newest row by raw SQL bypassing `fx.py`, and reports no date to any caller.

- Source and TTL: ECB daily XML, 12 hours, unchanged.
- Storage: no migration. Widen the `fx_ecb` snapshot payload from `{as_of, currencies, fetch_kind}` to carry the five universe crosses by value, because as written a diff can see only that the file moved to a new date.
- Code: route `_to_price_units` through `fx.latest_usd_rates` and return the rate and its `as_of` alongside the divisor, so one module owns every rate the app uses and every per-share rNPV states the day it used. Give `runway.liquidity` a `rates` argument so the cash-sized treemap is as currency-safe as the revenue-sized one. Add a currency lens to `fair_value.py` for non-USD filers only: the translation rate 5% either way, basis "the reference rate 5% stronger and weaker, the business unchanged".
- Change rule: an anchored 2% ratchet per cross (EUR, CHF, DKK, GBP, JPY), fanned out to the filers that report in it, because the consequence is company-specific. 2% is chosen against the measured daily moves (median absolute 0.18% EUR, 0.21% GBP, 0.25% CHF, 0.28% JPY) and against the roughly one percentage point of currency effect five of six 2026 guidance rows state, so a firing move is larger than the effect the company itself called out.
- Note text, rules-composed like build 4: "The krone is 2.1% stronger against the dollar since 2026-08-12, at 0.1537 USD per krone. NVO converts 2.1% higher everywhere this terminal ranks companies in dollars, and its dollar value per share moves with it. The forecast itself is unchanged: it runs in kroner."
- Tests: extend `test_fx.py` for the widened payload and the 2% ratchet; assert the three missing business days (2026-08-12, 2026-08-27, 2026-09-02) are drawn and compared as gaps, never interpolated.
- UI: the sum-of-the-parts byline (1750-1761) and the football field caption (1870-1921).
- Forecast hook: the divisor only. The book is single-currency by construction and stays so.

### Build 6a. Benchmark closes as a real fetcher. 1.5 days

`benchmark_prices` holds 2513 ^GSPC rows ending 2026-09-02 against company prices at 2026-09-21, and has no fetcher, so the index series goes stale while company prices move and quietly biases every beta.

- Source: Yahoo v8 chart, `https://query1.finance.yahoo.com/v8/finance/chart/{%5EGSPC|XLV}?range=10y&interval=1d`. Stay on query1, which `prices.py` and `beta.py` already point at, and send `Mozilla/5.0 (compatible; NovatalisResearch/0.1)`. The 429s are a header artefact: bare and full-browser User-Agents drew 429 repeatedly, the repo string returned 200 on every attempt. `beta.py:31` already sends exactly that string, the same value as `prices._USER_AGENT` at `prices.py:31`, so there is no header to fix there. `benchmarks.py` defines its own copy of the constant rather than importing either, because a fetcher-to-fetcher import is not allowed. Treat 429 as a soft reported error.
- TTL: 24 hours. The book is valued on closes.
- Storage: migration `059_benchmark_prices_adjclose.sql` adds `adjclose REAL` to `benchmark_prices`. XLV's 2016 close of 73.34 against an adjclose of 62.04 is an 18% ten-year gap, so any close-based relative figure charges the sector's whole dividend stream to the sector as underperformance. Store both and compare like with like. Never put an index or ETF in `prices`: `company_id` is NOT NULL and migration 048 states the consequence for the treemap, the comps table and the coverage counts.
- Fetcher: `backend/fetchers/benchmarks.py` on `BaseFetcher`, source `benchmark`, fixed `entity_key`, entity_type `market`, its own `_snapshot_cache` reading stored state, `fetch_kind` stamped, registered in `refresh._universe_fetchers` beside `RatesFredFetcher`.
- Test and fixture: `tests/fixtures/yahoo_chart_xlv.json` (trimmed), `test_benchmarks.py` asserts a null bar is dropped rather than carried, that `adjclose` and `close` land in their own columns, and an idempotent upsert on (symbol, as_of).
- Licence position: Yahoo's terms do not permit automated collection, so the series stays an internal input to a computed beta and a relative figure, is never exported, and a stored beta stays in use when the endpoint breaks. Store null rather than a stale or assumed beta.

### Build 6b. Beta measured and relative performance. 2 days

`beta.compute` derives a Blume-adjusted five-year weekly beta correctly and has no production caller, so 19 betas live as frozen assumption values quoting windows as old as 2021-W34.

- Beta: call `beta.compute` at load, report the computed value beside each of the 19 frozen ones, and adopt nothing without a decision, following this branch's own precedent of a measured rate reported and not adopted. Guard it: keep the stored beta unless the fresh series covers the full 261-week window, since a partial series would quietly move a discount rate. `breakpoints.CAPM_KEYS` and `_lever_evidence` already treat the six CAPM rows as one evidence group, so a live input inherits the grading.
- Relative performance: `comps.relative_performance(conn, ticker, symbol, windows)` beside `comps.price_grid` (240-269), returning per window `{company_pct, benchmark_pct, relative_pct, first_as_of, last_as_of}` or None, on intersected dates and never stored. UI: one `{span} vs XLV` stat in the existing `.stats stats-tight` f-string in the Prices tab (4261-4275) beside the window that defines it, using `.v.risk` for a negative and a muted dash when the benchmark does not cover the window; and the relative figure folded into the `.pos` move cell's `sub` (3967-3983) rather than added as a seventh cell, which would wrap and eat the sparkline. A rebased overlay goes to `CH.line_chart` with two `_pct_from_start` series, never the drawchart component, which builds one series and calls `priceToCoordinate` on it.
- Change rule: none. A relative move is a reading, not an event.
- Forecast hook: beta through the same override as build 3, gated on the decision in section 4.

### Build 7. Guidance currency basis as a hand-entered enumerated field. 1 day

`fair_value.guidance` (60-96) detects a constant-currency guide by grepping the note for "constant" or " cer" and then applies the guided growth to the prior year's reported revenue either way (86-91), so a company guiding 10% at CER is modelled as guiding 10% reported.

- Source: the filers' own releases, already seeded verbatim in `data/consensus/guidance_2026.csv`. No new endpoint, no new fetcher.
- Who fills the field, which decides whether the build is safe: a person, by hand, in the seed CSV, beside the verbatim sentence already there. `guidance.py` is the model-extraction path, and routing a filer's varied prose through it into a field a fair value lens reads is exactly where a fabricated value creeps in, which CLAUDE.md does not allow. There are 13 rows. The enumeration is transcription, not extraction.
- Storage: migration `060_guidance_fx_basis.sql` adds `consensus_estimates.fx_basis TEXT` enumerated `cer` / `reported` / `reported_with_stated_rate_date`, null when the release states none. The seed loader reads the new CSV column in the same commit as the migration. The basis is stated in varied prose across filers ("at CER, based on the average foreign exchange rates through 2025", "assuming foreign exchange rates as of July 24, 2026"), and BIIB states explicitly that no constant-currency basis is given, so the null case is real.
- Rule: no feed. Where `fx_basis` is `cer`, the guidance lens is suppressed rather than captioned: applying a CER growth rate to reported revenue produces a number on the wrong basis, and a caption confirming that leaves a reader-facing fair value lens wrong. Where it is null the view says no stated currency basis, never an assumed one. Only `reported` and `reported_with_stated_rate_date` draw a lens.
- Test: `test_guidance_fx_basis.py` asserts the stored value is one of the three enum members or null, that BIIB stays null, that a `cer` row draws no lens, and that NVS's basis-date FX level is null rather than substituted, because `fx_rates` history starts 2026-07-24 and the NVS row is `as_of` 2026-07-21.
- UI: the guidance lens caption on the football field (1870-1921).
- Forecast hook: none. See section 3 for why the stated percentage does not become an applied number.

### Build 8. IRA selected drugs, read out of what is already stored. 1 day

The one place a policy fact reaches a named asset exactly, because CMS names the brand. `negotiated_prices` holds 293 rows across IPAY 2026 to 2028, `negotiated_prices_cms.py` already fetches the file weekly, and `ira.py` already has `brands`, `selected`, `exposure` and `ceiling_cut` with no caller. It depends on build 1's `fetch_kind` stamp: without it the 7-day `cms_mfp` TTL never skips.

- Source and TTL: none new, the existing 7-day `cms_mfp` TTL.
- Storage: no migration. Dedupe to drug-year first: rows are per NDC-9 per price period and the drug column holds several brands in one string. `ira.selected` currently takes the first matching `ipay` per drug through `next(...)`, so a drug appearing in a new cycle cannot be read off it; change it to carry every IPAY year per drug, or to return one row per (drug, ipay).
- The company-level gate, which does not exist yet and is named here: `ira.exposure(conn, asset_id)` returns Part D spending, claims and gross spending per claim for one asset, or a reason where no Part D row exists. It returns no revenue share and no company total. So build 8 adds `ira.company_exposure(conn, ticker)`: Part D gross spending summed over the linked assets, over latest reported revenue converted through `fx`, with the count of linked assets carrying no Part D row stated beside it. The note gate is 1% on that figure. The 4.1% in the note text below is illustrative until that function runs.
- Deselection, one source of truth: the curated CSV `loe.cms_deselections` (129-160) already owns it, and `loe.for_assets` (260-275) lets a deselection pull an LOE date earlier, which changes the erosion clock and so changes modelled revenue. The curated CSV wins. A `negotiated_prices` row gaining `effective_to` writes an `ira_deselected` change row for review and never feeds `loe.py`, because `effective_to` is also set by the annual inflation adjustment and the file's own Remarks field is the only place the two are distinguished. Where a reviewer promotes it into the curated CSV, that edit is an LOE input change: snapshot the LOE inputs before it lands, and the build then does move a modelled number, which the review step is there to gate.
- Rules: a drug appearing for a new IPAY year writes `ira_selected` on the linked company. The row is always written; the note is gated on `company_exposure` reaching 1% of latest reported revenue.
- Note text: "CMS lists 3 ABBV drugs for IPAY 2028, about 4.1% of latest reported revenue. The ceiling cut is an upper bound and not the realised cut, because the rebates the maximum fair price replaces are confidential."
- Test: `test_ira_signal.py` asserts the multi-brand string splits, the drug-year dedupe, that every IPAY year per drug survives, the deselection rule writing a review row and not an LOE date, and that the note stays quiet under the 1% gate.
- UI: `metric_tiles(one_row=True)` per-company strip (drugs selected, earliest IPAY, MFP per 30-day supply, exposure bound), and the item in the existing change feed.
- Forecast hook: none applied on the selection side. The bound is shown with the revenue behind it and nothing is multiplied.

### Build 9. One narrow policy lane, on the context route. 1.5 days

The Federal Register API is sound once one field name is corrected: `fields[]=presidential_document_type` is not valid and 400s the whole request, and the field is `subtype`. With that change the spine returns 200 with every requested field typed. Two lanes earn a place on the context route of section 1, and no others.

- Lane one, BIS pharmaceuticals: agency slug `industry-and-security-bureau`, term `pharmaceuticals`. Measured 2 of 2 on topic, both with a docket id and one with an `effective_on`. This is the Section 232 tariff proceeding.
- Lane two, CMS negotiation rulemaking: agency slug `centers-for-medicare-medicaid-services`, gated on the `CMS-42xx` docket prefix rather than on the term alone. Measured precision on the term alone was 2 of 9, and two of the misses were the recurring "Agency Information Collection Activities" notice, which carries a real `comments_close_on` and would write a junk deadline onto the horizon rail. `comments_close_on` is populated on 5 of 9 rows and `docket_ids` on all of them, so a gated row maps to a dated context item with a stable dedupe key.
- Window: seed from an explicit start date, not the rolling window. The anchor documents sit outside 180 days: the Section 232 initiation is 2025-04-16 and the MFN order 2025-05-15. Backfill from 2025-01-01 with the same gates, then maintain on the rolling window. `count` saturates at 10000 with cursor paging, so the gates are what make the lane pageable at all.
- Rules: no modelled number, no per-share sentence, no threshold. Items carry their own source dates, never a fetch date, and an item whose company cannot be matched is kept with a null company the way `rssfeed` keeps an unmatched item. `rssfeed.match_company` returns one company and first match wins over an unordered dict, so a policy item naming several manufacturers needs a multi-match variant rather than reuse as is.
- Test: a fixture per lane, asserting an invalid agency slug fails loudly (the API returns `{"errors":{"agencies":"invalid value"}}`), that a `CMS-42xx` gate drops the information-collection notice, and that a null `effective_on` stores null.
- Forecast hook: none, by construction of the context route.

### Build 10. China in-licensing, off the deals tables. 1 day

The first pipeline-sourcing question an analyst asks of this universe today, and it needs no new source: `deals_news.py` and `deals.py` already parse and store these headlines, including the "acquire China rights" shape the party parsers explicitly step over (`deals.py:383-385`, `deals_news.py:255`).

- Source: the existing `deals` rows and their verbatim quotes. No new endpoint.
- Rule: count and value China-origin in-licensing per company from the stored rows, taking a deal only where the headline states the origin or the counterparty plainly, and reporting `announced_value` as announced consideration or null. Nothing inferred, no terms reconstructed, no share of pipeline computed.
- UI: one context cell per company on the deals view with the count and the summed announced value where every row carries one, and null where any does not.
- Test: a fixture of stored rows asserting a China-rights headline is counted once, a headline naming no origin is not counted, and a missing `announced_value` makes the sum null rather than partial.
- Forecast hook: none.

## 3. What not to build

- DTWEXAFEGS as a currency proxy: it is a goods-and-services trade-weighted advanced-economy basket including Australia, Sweden and Korea, published on the weekly H.10 so it lags spot by up to a week, and `fx_rates` plus `asset_revenue_regions` already give a better-matched weighting from data on disk.
- An `fx_effect_pct` column that changes a modelled number: the stated basis is usually a period average rather than an ECB daily fix, five of six rows state about one percentage point which is inside the error of the comparison, and one guidance row predates the first stored FX date.
- ^VIX: its last bar is a day ahead of every equity series on a Chicago calendar with 94 null bars, so a snapshot would store a partial intraday print as a close and emit a spurious change row for a value that changes later the same day.
- ^DRG: an unadjusted price index read beside adjusted ETF closes, on a weaker licence claim than an ETF quote, for a cell XLV already carries.
- XBI over XLV as a risk-appetite regime: its threshold cannot be set until a backfill exists, the two legs carry unequal dividend drag that drifts the ratio about 16% over ten years, and its own note states no valuation consequence.
- T10Y2Y as a curve regime: a migration row, a five-session confirmation rule and a state machine to deliver a label whose consequence sentence is that nothing in the book moves, because the book reads one ten-year point. One sentence in `note()` says it instead.
- A 15-minute TTL on Yahoo benchmark symbols: the book is valued on closes, so it buys nothing and multiplies exposure to the one unofficial endpoint in the feature.
- Migrating the price and benchmark fetchers to query2: the premise is disproven, query1 returns 200 with the repo's own User-Agent and 429s only on a missing or browser header, and both hosts are one provider.
- The nineteen-row per-company fan-out for a universe-wide rate move: it writes about 500 rows a year from one series and frames a macro event as a company event, to avoid one branch in `whatchanged`.
- The 20pp XLV de-rating rule as specified: it is calibrated on stored ^GSPC closes and fired against XLV, where close and adjclose diverge 18% over ten years, so the calibration and the application use different bases.
- The five-lane Federal Register spine as specified: the field name 400s the whole request, quoted phrases in `conditions[term]` return zero, and the measured counts came in at 2, 1, 9, 50 and 590 against the claimed 5, 6, 27, 8 and 36. Two of the five lanes survive the correction and the gates, and they are build 9. The other three do not: the FDA user fee lane (590 hits on boilerplate authority text), the USTR 301 lane (50 hits, one on topic, `effective_on` null on every row), and the HHS and CMS RSS lanes (a 403 from an Akamai edge, and a feed serving HTML anchor fragments as titles).
- A 180-day rolling window as a lane's only window: the MFN order of 2025-05-15 and the Section 232 initiation of 2025-04-16 sit permanently outside it, so the tape's own anchor documents are the items it would never fetch. Build 9 backfills from a date and only then rolls.
- Agency-plus-term matching as the only policy gate: measured precision was 2 of 9 on CMS, with a recurring information-collection notice that carries a real `comments_close_on` and would write a junk deadline onto the horizon rail.
- The Google News policy lane: one query at the 100-item ceiling, recency uneven enough that one query's newest item is four months old, redirect links rather than publisher URLs, and a bare "MFN" term that pulls unrelated trade stories.
- WPU0638 and PCU325412325412: monthly list-price indexes on two different bases that net no rebates, bought for a footnote nothing applies.
- Payer and pharmacy benefit manager context generally, and named so it reads as a decision: the Medicare trustees report, PBM reform, the Part D redesign and 340B are out of scope for this feature. None of them reaches a named asset the way a CMS selected-drug row does, none has a free structured feed with dated rows, and the only modelled number any of them could touch is a net price the rebate data needed to compute is confidential. The IRA lane in build 8 is the one payer fact that survives those tests, and it survives because CMS publishes the brand and the price.
- Any applied tariff or MFN figure, and any inferred imported share of cost of goods: the imported share is not published free and the deal terms are undisclosed, so an applied number is invention with a citation attached.
- Exporting BAMLC0A3CAEY: ICE prohibits reproduction in any form without written permission and FRED cannot grant it, so the level stays internal, out of `data/history/*.ndjson`, and out of any model payload, and the endpoint returns only a rolling three years anyway.
- Per-currency risk-free curves, a term-structured discount rate, and translating the forecast year by year: the first two the app cannot evidence and the four fetched series cover none of those curves, and the third would require forecasting FX.
- An index level in `market_rates` or an index row in `prices`: `rates_fred.parse` divides by 100 and the column is declared a rate, so 113.15 would read as 113%, and migration 048 already states the consequence for the treemap, the comps table and the coverage counts.
- Any path from an index, a spread or a volatility level into a WACC, an ERP, a success rate, an uptake curve or a multiple, and any LLM step in the rate, FX or beta path, the note feed included: every number here is arithmetic on a published series, the model's only job is written company commentary, and the note must degrade to the rules text with no key.
- A scraped or implied equity risk premium, and a dedicated markets tab: the first has no licensed automated route and no stable page structure, which is why build 3 hand-enters a dated row instead, and the second invites the fifteen cells the ten-cell budget exists to refuse.

## 4. Open decisions

1. Which day's rate a valuation uses: the latest observation, or the rate on the valuation date. `market_rates` keeps 400 days, so the dated convention reaches back only that far, and every snapshot already in history was computed at the frozen 0.0501 regardless of its day. Do not retro-restate stored history to make the convention look older than it is.
2. Whether to adopt the recomputed beta into the assumptions at all, or report it beside the 19 frozen values and leave adoption to a later explicit decision. Adopting it moves every valuation in the book on a market series rather than on analysis.
3. Whether a mixed-vintage CAPM is acceptable. Build 3 makes `risk_free` live and daily while `erp` stays a dated row read once a month, so a rate rise lifts cost of equity one for one when an implied premium historically compresses against the rate. The size of the inconsistency is stated rather than hidden: the premium is 4.14% against his own 4.75% risk-free, our seed carries 5.00%, and at beta 1 the 86bp gap is three and a half times the 25bp rate move the signal layer exists to catch. The alternative is to hold the whole CAPM at one vintage and refresh it deliberately, which gives up the daily signal. Accepting the mix is the recommendation, on the ground that the basis string names each leg's vintage and the reader can see it, but it is a decision and it belongs here.
4. Whether the FRED and Yahoo terms are acceptable for this terminal as used. The ICE question is settled in build 1 and not left open: internal display with the copyright line, no export, no model payload. The two that remain are FRED's own terms, written for personal and non-commercial use and restricting the feeding of values into an artificial-intelligence process, which build 4 honours by keeping the macro sentences rules-only, and Yahoo's, which do not permit automated collection at all and which build 6a confines to a computed beta and a relative figure held internally. The engineering answer is in the builds; the risk appetite is yours.

## 5. Week one

1. `fix(rates): stamp fetch_kind on the FRED snapshots so the 12-hour TTL applies`
2. `fix(cms): stamp fetch_kind on the negotiated-prices and NDC fetchers`
3. `feat(rates): read market_rates by date and by series, cached per refresh run`
4. `feat(api): GET /markets serves rates, FX and benchmarks with a date per series`
5. `feat(ui): markets strip on the universe tab, one observation date per cell`
6. `fix(forecast): render the breakeven basis and print it to one decimal`