# Comps tab: valuation view, design specification

Status: agreed architecture, revision 3, ready to build. First draft 2026-09-29, revision 2 after
the design review 2026-09-30, revision 3 (section 12) 2026-09-30: a simpler page, the bridge on the
Forecast tab, catalysts and competition in Drivers and risks. Where section 12 and an earlier
section disagree, section 12 holds. Book used for every figure quoted: the 2026-09-29 22:33 backup
of the live book (prices to the 2026-09-28 close, refresh run 123, status partial). Appendix A
records the review points resolved differently from the reviewer's proposal, the review figures
corrected against the book, and what the check found beyond the review.

This document is the contract five engineers build against in parallel. Where it names a
value, a string, a threshold or a field, that is the value. Where the brief asks for
something the free data cannot support, the section says what the view shows instead.

Inputs: the user's brief (`scratchpad/comps_brief.md`), the data dictionary
(`scratchpad/understand_data.md`), the UI and Streamlit report (`scratchpad/understand_ui.md`)
the side panel report (`scratchpad/understand_detail.md`) and the design review's 51 points.

---

## 0. Decisions and what moves where

### 0.1 Fixed decisions

> Revision 3: decision 3 now counts three Python actions (12.9), and the bridge is drawn on the Forecast tab by the same component (12.5).

1. One bidirectional Streamlit custom component at `frontend/components/compsval/`, split into
   `index.html`, `styles.css`, `core.js`, `table.js`, `charts.js`, `panels.js`, `shell.js`, plus
   the Python wrapper `__init__.py`.
2. One new endpoint, `GET /comps/valuation`, built by `backend/comps_valuation.py`. It returns all
   70 companies. Streamlit passes all 70 to the component, so a peer from another subsector can
   be added without a rerun.
3. Every change of peer set, basis, currency, earnings basis, preset, filter, exclusion, bridge
   input or metric recomputes in `core.js` inside the iframe. Python sees two actions only: a
   change of focal company and a reload (section 7.5).
4. The Comps tab gets a new first and default sub-tab, **Valuation**. **Indications** (pharma only)
   and **Pipelines** stay. **Head to head** and **Screen** are removed; their measures move as
   listed in 0.2.
5. Real book data only. Where a metric has no free data the cell shows the null glyph `—`
   (U+2014) with a tooltip giving the reason. The glyph is a cell marker, not prose. All prose
   follows house style: sentence case, no em dashes, none of the banned words of CLAUDE.md
   (the list is `BANNED_WORDS` in 3.11), direct, number first.
6. The existing visual language stays (petrol-dark ground, radius 0 or 2px, IBM Plex Mono for
   figures, Archivo for UI). One new colour, `ACTIVE`, plus its derived wash, is added to both
   `tokens.py` and `tokens.css`.
7. Saved peer sets, table configuration and analyst notes live in the component's
   `localStorage`, wrapped in try/catch. The view works without storage. Every place that saves
   says "Saved in this browser only".

### 0.2 Measure migration from the removed sub-tabs

Nothing the removed sub-tabs showed is lost. Column ids are defined in section 4.

| Measure | Was in | Now in |
|---|---|---|
| Revenue, USD bn | Head to head, Screen | column `revenue`; side panel "Against the focal company" |
| Revenue growth | Head to head, Screen | column `revenue_growth`; side panel "Against the focal company" |
| Net margin | Head to head, Screen | column `net_margin`; side panel "Against the focal company" |
| R&D, share of sales | Head to head, Screen | column `rd_pct`; side panel "Against the focal company" |
| Market cap | Head to head, Screen | column `market_cap` (now 70 of 70, was 58); KPI strip |
| P/E (trailing) | Head to head, Screen | column `pe` at basis FY0 (GAAP or IFRS, tag A) |
| EV / sales | Head to head | column `ev_revenue` at basis FY0; EV now uses dated net debt, which corrects INCY (4.2x, not 7.9x) |
| Late-stage trials | Head to head, Screen | column `late_trials` |
| Revenue per late trial | Screen | column `revenue_per_late_trial` |
| Revenue losing exclusivity in 5 years | Head to head, Screen | column `loe_share_5y` |
| Unpriced exclusivity losses in 5 years | Screen | column `loe_unpriced_5y` |
| Catalysts in 12 months | Head to head, Screen | column `catalysts_12m` |
| Share price, 12 months | Head to head, Screen | column `ttm_price_change` |
| 90-day sparkline | Screen | column `spark_90d` |
| Filing currency | Screen | column `currency` |
| Better side marked per measure | Head to head | side panel "Against the focal company", with the better-is rules of `_H2H_ROWS` except catalysts in 12 months and the 12-month price change, which are unmarked (6.4) |
| Revenue growth and net margin, FY20 to FY25, two companies | Head to head "Compare over time" | side panel "Over time": the opened company against the focal company |
| Pick two companies | Head to head | open any row's side panel; the focal company is the other side; "Make focal" swaps |
| Focal row marked, sortable headings, heading definitions | Screen | focal row treatment, sorting, header tooltips |

`_head_to_head`, `_H2H_ROWS` and `_SCREEN_COLUMNS` in `streamlit_app.py`, and the `.h2h*` rules in
`theme.py`, are deleted once nothing references them (grep first). The `/comps`, `/comps/trend`,
`/screen` and `/price-grid` endpoints stay: other code and the new endpoint reuse them.

---

## 1. Component hierarchy and layouts

### 1.1 Tree

> Revision 3: the `#main` part of this tree is replaced by 12.1. The header band and the overlays stand.

Owners: **A** backend and wiring, **B** `core.js`, **C** `table.js`, **D** `charts.js` and
`panels.js`, **E** `shell.js`, `index.html`, the base of `styles.css` and the shared
`research.css`. Section 11 has the full ownership table.

```
Streamlit page (global navigation: top bar, main tabs)                       existing
  Comps tab
    st.tabs(["Valuation", "Indications" (pharma only), "Pipelines"], default="Valuation")
      Valuation                                                   streamlit_app.py (A)
        @st.fragment _comps_valuation_view()                     streamlit_app.py (A)
          compsval component iframe                               __init__.py (A)
            #app                                                   shell.js (E)
              header band (pinned, never scrolls, `panel` background)
                context bar             .sh-ctx                    shell.js (E)
                  identity: company selector (popover listbox), name, subsector, stage
                            and type chips, listing, reporting
                  controls: peer set, period, data state and currency, earnings,
                            "Data as of" chip, reload, export, help (carries the key state)
                conclusion banner       .sh-banner                 shell.js (E)
                  premium token, headline, support, meta line
                  meta line: system-generated label, confidence, warning chips,
                             "Look next" link, "Why?" button
                  "Why?" popover        .sh-why                    shell.js (E)
                KPI strip (6 cells, KPI 5 holds the position strip) .sh-kpis  shell.js (E)
                scope line              .sh-scope                  shell.js (E)
                  counts, exclusions, filters, statistics group, outlier mode,
                  warning chips, "+n" overflow menu, Edit peers, Reset filters
              #main (the one page-level scroll container)
                analysis band
                  peer position dot plot  .ch-dot                  charts.js (D)
                    metric switcher, "Primary" tag, "Use as primary"
                  valuation against fundamentals scatter .ch-sc    charts.js (D)
                    axis, size and colour selectors, trend toggle, interpretation line
                  comparable companies table .tb                   table.js (C)
                    toolbar: presets 1 to 7, layouts, statistics group, outliers,
                             conditional format, density, summary rows, column finder,
                             hidden-column chip, "Below the table" jump menu
                    table: group header, column header, focal row, peer rows (each
                           expandable), summary rows
                valuation bridge        .ch-br (chart) .pn-br (inputs)   charts.js + panels.js (D)
                drivers and risks       .pn-obs                    panels.js (D)
                peer selection          .pn-peers                  panels.js (D)
                  relevance table, candidates, saved sets, subgroups, cohort comparison, notes
                notes and data sources  .pn-notes                  panels.js (D)
                  sources and timestamps, storage notice, "Open methodology"
              detail side panel         .pn-detail                 panels.js (D)
              methodology drawer        .pn-method                 panels.js (D)
              overlays (fixed, inside the frame)
                command palette         .sh-pal                    shell.js (E)
                shortcut help           .sh-help                   shell.js (E)
                shared tooltip          .u-tip                     shell.js (E)
                shared menu             .u-menu                    shell.js (E)
                undo toast              .u-toast                   shell.js (E)
                live region (aria-live) .u-live                    shell.js (E)
```

The component never draws the Streamlit top bar or main tabs. The context bar is the first
thing inside the iframe.

### 1.2 Frame sizing

The frame fits the visible viewport and scrolls inside itself (UI report 6.3). `shell.js` owns
`fitFrame()`: height = `parent.innerHeight − frameTop − 12`, floor 560 px, fallback to the
`height` arg (900) when parent access throws, no update when the change is under 2 px. It runs on
every render (after `requestAnimationFrame`), on `window` resize, on parent resize (listener
registered once, removed on `pagehide`) and after `document.fonts.ready`.

Inside the frame: `html, body { height: 100% }`, `#app` is a grid with rows
`auto auto auto auto 1fr` (context bar, banner, KPI strip, scope line, `#main`). `#main` is the
page-level scroll container. A `ResizeObserver` in `shell.js` publishes two custom properties on
`#app`, rounded to whole pixels and written only when they change: `--band-h` (the header band's
height) and `--main-h` (`#main`'s client height).

The table box inside `#main` has `overflow: auto` and `max-height: var(--main-h)`. It keeps its
own scroll because horizontal scrolling with frozen columns needs one: an element whose
`overflow-x` is anything but `visible` becomes the sticky container for its descendants, so a
header that should stick to `#main` while the table scrolls sideways cannot exist in one table.
The box sets **no** `overscroll-behavior`, so a wheel or trackpad gesture that reaches the top or
bottom of the table carries on into `#main`, and the lower sections stay reachable by wheel. When
`#main` is scrolled until the table box's top meets the top of `#main`, the box fills the view
with its sticky header, focal row and summary rows. The toolbar's "Below the table ▾" menu and the
palette's "Go to section" entries scroll `#main` straight to the bridge, drivers and risks, peers
or notes.

### 1.3 Breakpoints and height modes

> Revision 3: the layout table below is replaced by 12.1 (one arrangement, the charts in a strip at every width, the side panel a drawer). The height modes stand.

Breakpoints read the frame's own `innerWidth` (the Streamlit main column with `no-rail`, about
60 px narrower than the screen). `shell.js` sets `data-layout` on `#app` to `ultrawide`, `wide`,
`laptop` or `narrow`, and `data-height` to `tall` or `short`.

| Layout | Frame width | Typical screen | Analysis band | Side panel | Lower sections |
|---|---|---|---|---|---|
| `ultrawide` | 2200 px and over | 2560 to 3440 px | Three columns: table `minmax(1100px, 2fr)`, chart rail `minmax(420px, 1fr)` capped at 600 px, side panel column 440 px. While no panel is open its column has width 0 and the table takes the space. Rail: dot plot, then scatter. | Its own column. The rail and the table stay in view. | Bridge full width. Then drivers and risks (2 fr) beside notes and data sources (1 fr). Then peer selection full width. |
| `wide` | 1700 to 2199 px | 1920 px | Table `minmax(960px, 2fr)` and rail `minmax(420px, 1fr)` capped at 600 px, side by side. Rail: dot plot, then scatter. | Docks into the rail column while open. The table does not reflow. The focal position stays in view in KPI 5's position strip. Esc or close restores the rail. | As `ultrawide`. |
| `laptop` | 1100 to 1699 px | 1280 to 1600 px | A chart strip above the table. The strip header holds a two-tab switch, "Position" (default) and "Valuation and growth", and a collapse chevron. Position: the dot plot, 120 px for one lane (plus 56 px per extra cohort lane). Valuation and growth: the scatter, 260 px. Collapsed: the 28 px header row only (state `chartStrip`, persisted per layout). Table full width below. | Right drawer, 440 px, fixed inside the frame from `--band-h` to the bottom, over the table's right side. The table keeps its scroll and focus. | All four stacked, full width. |
| `narrow` | under 1100 px | tablet, split screen | The same two-tab strip at 220 px. Table full width with frozen columns and horizontal scroll. | Full-width overlay over `#main`. | One tab strip: "Bridge", "Drivers and risks", "Peers", "Notes and sources". |

**Height modes.** `data-height="short"` when the frame is under 720 px tall, or when `#main` is
scrolled past 120 px. It returns to `tall` only when the frame is 720 px or taller and `#main` is
scrolled less than 40 px, so a scroll near the threshold does not make the band flicker. The
threshold comes from the measured chrome: at 1440 × 810 the Streamlit top bar, main tabs and Comps
sub-tabs put the frame's top about 200 to 215 px down, so the frame is about 585 px and opens
short; at 1920 × 1080 the frame is about 735 px and opens tall. A tall band (254 px typical) on a
735 px frame leaves 481 px for `#main`; a short band (194 px typical) on a 585 px frame leaves
391 px.

Header band heights, tall / short (px):

| Part | Tall | Short | Short keeps | Short drops |
|---|---|---|---|---|
| Context bar | 40 | 36 | every never-hidden item of 1.5 | nothing beyond the collapse steps of 1.5 (the same steps run at both heights) |
| Conclusion banner | 102 typical, 150 max | 82 typical, 104 max | the full headline (16 px, wrapped, never truncated), the premium token (18 px), a one-clause support (`supportShort`), the whole meta line with the label shortened to "System-generated" | the two-sentence support (it stays in "Why?") |
| Gap below the banner | 16 | 8 | | |
| KPI strip | 68 | 44 | label and value of all six cells; KPI 5's position strip | the period line and the compare line of every cell |
| Scope line | 28 | 24 | every item (overflow rules of 1.5) | nothing |
| Band total | 254 typical | 194 typical, 216 max | | |

Headlines are capped at 160 characters by the templates of 3.11 (a test checks every fixture
company). At 16 px that is two lines down to a 1,000 px frame and at most three lines in
`narrow`. The table is never converted to stacked cards. In `narrow` the KPI strip wraps into a
3 by 2 grid and the context bar into two rows (1.5).

### 1.4 Focal company and the Streamlit page

- The focal company is the app-wide `company_pick`. The component receives it as the `focal`
  arg. A focal change inside the component re-renders at once from client data, then posts
  `{action: "focus", ticker, nonce}`; Python applies it before the selectbox exists (section 7.5).
- The component receives the open engine as `engine`. The company selector lists that engine's
  companies first, then the rest. Default peers use the focal company's own engine, which differs
  from the open engine only when a shared link names no engine (`engine == ""`).

### 1.5 Header band contents (`shell.js`)

> Revision 3: the data state and currency select and the earnings control become one Basis menu (12.6); KPI 6 links to the Forecast tab (12.5); "Edit peers" opens a drawer (12.6).

The header band has a `panel` background, a 1 px `rule` bottom border and a 16 px side gutter.
The conclusion banner sits inside it on `ground`, so the conclusion is the darkest, most
contained block on the screen.

**Context bar.** One line (two rows in `narrow`), identity on the left, controls on the right,
8 px gaps. Price, the 1-day change and market cap are **not** here: the KPI strip owns them.

| Item | Content | Width, px (compact) | Collapse step |
|---|---|---|---|
| Company selector | button: ticker (mono 14 px 600) and `▾`; opens a listbox with a search box, the open engine's companies first under "In {engine label}", then "Other subsectors"; each row ticker, name, stage chip | 72 | never |
| Name | 15 px 600, ellipsis, full name in the tooltip | max 240 (120) | 5 |
| Subsector chip, stage chip | "Big pharma" / "Biotech" / "Cell and gene"; "Commercial" or "Clinical" (clinical tone) | 76 + 76 | never |
| Type chip | "Loss-making", "Revenue under $100m" or "Pre-revenue" (section 8); absent for a profitable company | up to 132 | never (when present) |
| Listing | US company: "{exchange}: {T}". Foreign: "US line {us_line}, home {home_exchange}", plus "1 ADR = {ratio} ordinary shares" when the ratio is not 1 | up to 180 | 1: moves into the selector's tooltip |
| Reporting | "Reports {row currency}, {standard}, {filer kind}", `⇄` when converted; "{standard}" is "standard not recorded" when `filer.standard` is null | up to 170 ("Files GBP", 64) | 2 |
| Peer set control | "Peers: {set label} ▾" (3.6), for example "Peers: Big pharma, commercial, 15 ▾"; the menu lists the system set, saved sets, "Custom (edited)" and "Save current set" | up to 260 (short form, up to 160) | 8: short form, never hidden |
| Period | segmented NTM, FY1, FY2, FY0, LTM; tooltips name the years | 200 (select "NTM ▾", 72) | 7: select, never hidden |
| Data state and currency | select reading "Standardised, USD ▾" (also EUR, GBP, CHF, DKK) or "As reported, filing currency ▾" | 172 | never |
| Earnings | segmented "GAAP/IFRS" and "Ex amort. and IPR&D"; tooltip `basis_text.adjusted` | 220 (single toggle "Ex amort.", 92) | 3 |
| Data as of | chip "Data as of 28 Sep" (the price date); tooltip lines: "Prices: close {date}, fetched {time} UTC", "Consensus: last checked {date}", "Financials: latest period {date}", "FX: ECB {date}", "Refresh run {id}: {status}, finished {time} UTC" | 124 ("28 Sep", 60) | 4 |
| Reload, Export | icon buttons; Export menu: CSV of this view, Copy as TSV, Copy summary | 60 ("⋯" menu, 26) | 6 |
| Help | `?` button followed by a 6 px key-state dot: filled `active` when the frame has focus, a hollow `muted` ring otherwise. Accessible name "Keyboard shortcuts, keys active" or "Keyboard shortcuts, click the view to use keys" (7.1) | 30 | never |

Collapse rule: after each render and on resize a `ResizeObserver` checks whether the bar
overflows. While it does, `shell.js` applies the next step in the order 1 to 8. When the bar
gains room for the most recent step plus 24 px, it reverses that step. Never-hidden items are the
company selector, the subsector, stage and type chips, the peer set control, the period, the data
state and currency control, and help. So the company, the peer set and the time basis are always
on screen. The same steps run in tall and short mode. In `narrow` the bar splits into an identity
row and a controls row (36 px each) and the steps run per row. Steps applied at rest for AZN:
none at `ultrawide`, 1 at a 1920 px screen, 1 to 6 at 1440 px, 1 to 8 at 1280 px (widths in
1.6).

The data state is set by one rule: `dataState = currency === "REPORTED" ? "As reported" :
"Standardised"`. It is the first word of the currency control's label, so it cannot disagree
with the currency. The "Data as of" chip is neutral unless a source this view reads (prices,
Nasdaq consensus, financials, FX) failed in the latest refresh run for the focal company, for an
included peer or for the whole universe (`as_of.run.failed_sources`, 2.2). Then it turns amber
with `!` and names the failure in its tooltip (section 8). Failures of other sources (press
releases, approvals, patents) are listed in the tooltip in neutral text.

**Conclusion banner.** `ground` background, 1 px `rule` border, a 3 px left bar, padding
12 px 16 px, 16 px of space below it (8 px short). A two-column grid, `112px 1fr`, gap 16 px.

- Column 1, the premium token: the premium or discount as its own figure, mono 24/28 600 in `text`
  (18/22 short), with `▲` for a premium or `▼` for a discount before it, for example "▲ +6%".
  Beneath it an 11 px `muted` caption: "premium to median", "discount to median" or "in line with
  median". The token is never coloured `up` or `down`: a discount is not favourable and a premium
  is not a warning. States with no stated premium (`low_confidence`, `too_few`, `no_multiple`,
  `no_peers`, `error`) show `—` with the caption "no premium stated".
- Column 2: the headline (21/28 600, figures in Plex Mono; 16/22 short), the support (14/20, at
  most two sentences; short mode shows `supportShort`, 13/18, one line), then the meta line (20 px
  high): the label "System-generated summary" (11 px `muted`; "System-generated" in short mode,
  the full label of 3.11 in its tooltip), the confidence chip "Confidence: high" with its
  three-segment bar (it opens the methodology drawer at "Confidence"), the warning chips
  ("Weak peer set", "Mixed business models", "Low confidence", section 8), the link "Look next:
  {text} →" in `active` text, and at the right the "Why?" button (`w`).
- Bar colour: `down` when `state === "error"`; `flag` when `confidence.level === "low"`, or
  `state` is `low_confidence` or `too_few`, or the peer set is weak (3.6); otherwise `active`.
- "Look next" (3.11) scrolls `#main` to its target and moves focus there: a table cell (focused
  and scrolled into view), a dot plot point, the scatter, or the peer panel. The live region says
  "Showing {target}".
- "Why?" opens a popover anchored to the button: 440 px wide (`narrow`: frame width less 32),
  `max-height: 50vh` with its own scroll, `role="dialog"`, labelled by its title "Why this
  summary". It overlays the page and never pushes the layout. Content in groups: "Primary
  metric" (the reason line), "Confidence", "Observations" (each a link to its column, model
  output labelled "Model output"), "Outliers", "Bases" (the mixed-standards and earnings-bases
  lines of section 8, when they apply). Last line: the link "Open drivers and risks". Focus moves
  to the popover's title on open; Esc, `w` or a click outside closes it and returns focus to the
  button.

**KPI strip.** Six cells on `panel`, 1 px `rule` dividers. Cells 1 to 4 and 6 share the width
equally; cell 5 is 1.5 times as wide and carries a 2 px `active` top border. A cell: label (12/16
Archivo 500 `muted`), value (17/22 IBM Plex Mono 500 `text`; cell 5 weight 600), period line
(11/14 mono `muted`, ending with the provenance word: "sourced", "calc." or "model"), compare
line (11/14 mono). Short mode drops the period and compare lines. Every cell is focusable and
shows its tooltip on focus. Arrows in the compare lines of cells 5 and 6 are `▲`/`▼` in `text`,
never `up` or `down`.

KPI 5 holds the **position strip** in both heights: an inline SVG, 120 × 20 px, to the right of
the value. It draws the peer interquartile range as a `rule-strong` band, the median as a 12 px
1 px `text` tick and the focal company as a 7 px `active` diamond with a 1 px `text` stroke; a
focal value beyond the plotted domain sits at the edge as `◂` or `▸`. The domain follows the dot
plot rule (5.1). The cell's accessible description reads "{T} at the {pct} percentile, {inside |
above | below} the interquartile range of {p25} to {p75}."

| Slot | Label | Value | Period line | Compare line | Tooltip |
|---|---|---|---|---|---|
| 1 | "Share price, USD" | 166.15 | "Close 28 Sep · sourced" | "▼ 0.26% on the day" | "Last close of the US-listed line, unadjusted. Per-share figures are in USD, the quote currency, whatever the display currency." |
| 2 | "Market cap, {cur} bn" | 260.0 | "Diluted shares · calc." when `market_cap_basis` is `diluted_weighted`; "Cover shares {date short} · calc." when `shares_outstanding` | "{ordinal} largest of {n} in the set", where n counts the focal company and the included peers (format: "5th largest of 16 in the set") | the `market_cap` column tooltip, then `market_cap_basis_text` |
| 3 | "EV, {cur} bn" | 283.9 | "Balance sheet {date} · calc." | "Net debt {x}" or "Net cash {x}" in the display currency bn | the `ev` column tooltip. When null: value `—`, period "No debt line on file", compare line empty, tooltip `NA_TEXT.no_debt_line` |
| 4 | "{primary header label}, {unit}", for example "P/E, ×" | 16.2 | "{basis chip} · calc.", for example "NTM street E · calc." | "Median {m}, n {k}" | the primary column's tooltip, then `primary.reasonText` (3.5), for example "P/E NTM is primary: AZN is profitable and 14 of 15 peers have a value." |
| 5 | "Against peer median" | "+5.6%" with `▲` | exactly one of "Premium", "Discount", "In line, within 5%", "Not stated: {k} peers" (`low_confidence`) or "Not stated" (`too_few`, `no_multiple`, `no_peers`) | "{ordinal} percentile" then the position strip | "The primary multiple over the peer median, less one. For FCF yield, the peer median over the yield, less one. A premium or discount is not a verdict; see drivers and risks." |
| 6 | "Implied value, USD" | 157.38 | "Median {primary label} × {operating metric} · calc.", for example "Median P/E NTM × NTM EPS · calc." | "▼ 5.3% against price" | "From the valuation bridge below, with its inputs. Per-share figures are in USD, the quote currency." |

- Slot 5 in `low_confidence` shows the number with an amber `!` in its marker slot.
- Slot 6 falls back to "Street target, USD" (value 211.07, period "12M, 16 analysts · sourced",
  compare "▲ 27.0% against price") when the bridge is disabled.
- For a clinical or sub-scale company the primary is market cap to cash (3.5), so the strip keeps
  its meaning: slot 4 "Market cap / cash, ×" (value 2.21, period "Balance sheet 30 Jun 2026 ·
  calc.", compare "Median 2.07, n 17"), slot 5 the premium, slot 6 the bridge at the peer median
  multiple of cash. Only `no_multiple` changes the slots: slot 4 becomes "Cash / market cap, %"
  (compare "Median {m}, n {k}"), slot 5 "Cash runway, months" (period `runway_basis`, compare
  "Median {m}") and slot 6 the street target.
- When the display currency is not USD, slots 1 and 6 show a `USD` unit chip after the value.

**Scope line.** One line, 28 px (24 short), on `panel`. It shows what shapes the statistics.
The peer set's name is in the context bar and is not repeated here. Items in priority order;
items 1 to 3 never leave the line:

1. Counts: "{n} peers, {k} in statistics" (opens the peer panel).
2. Exclusions: "Excluded: PFE ✕ BMY ✕", one removable chip per ticker. More than three become
   one chip "Excluded: {n} ▾" whose menu lists each with its remove button.
3. Filters: one removable chip per filter, for example "P/E, × ≥ 10 ✕"; the tooltip of every
   filter chip reads "Filters hide rows. Statistics still use every included peer." More than
   three become "Filters: {n} ▾".
4. "Statistics over: {group} ✕" when not all peers.
5. "Outliers excluded ✕" when the outlier mode is exclude (nothing is shown in the default
   include mode).
6. Warning chips of section 8 that belong here: "Non-December year ends: {n}", "Stale prices:
   {n}", "{n} extreme outliers", "Failed sources: {n}".
7. At the right, fixed: "Edit peers" and "Reset filters" (disabled with no filter).

When the line overflows, items are moved from the end of 6 back through 4 into a "+{n}" menu
button placed before the fixed actions. The menu lists each moved item with its own action.

### 1.6 Layout drawings

> Revision 3: `#main` in these drawings is replaced by 12.1. The header band stands.

Heights and widths in CSS pixels of the frame. `shell.js` implements these; integration checks
the running app against them with screenshots at 1440 × 810 and 1920 × 1080 (11.2).

**1440 × 810 screen: frame about 1380 × 585, `laptop`, `short`.** Band 194 px, `#main` 391 px.

```
x 0 ............................................................................... 1380
┌── context bar 36, one line, collapse steps 1–6 ───────────────────────────────────┐ y 0
│ AZN▾ AstraZeneca… [Big pharma][Commercial] Files USD ║ Peers: Big pharma, comm… ▾ … ?• │
├── banner 82 (ground) ─────────────────────────────────────────────────────────────┤ y 36
│ ▲ +6%       │ AZN trades at 16.2× P/E (NTM), a 6% premium to the median of 14 big   │
│ premium to  │ pharma peers, 15.4×.                             (16 px, wraps)       │
│ median  112 │ Alongside: revenue growth top quartile                  (13 px)       │
│             │ System-generated · Confidence: high ▮▮▮ · Look next: … →    Why?      │
├── 8 ──────────────────────────────────────────────────────────────────────────────┤ y 118
├── KPI strip 44 ───────────────────────────────────────────────────────────────────┤ y 126
│ Price 166.15 │ Mkt cap 260.0 │ EV 283.9 │ P/E 16.2 │ Against +5.6% ▭┼◆▭ │ Implied 157.38│
│   207          207            207        207        311                 207        │
├── scope line 24 ──────────────────────────────────────────────────────────────────┤ y 170
│ 15 peers, 15 in statistics │ Excluded … │ Filters … │ +2 ▾ │   Edit peers │ Reset     │
╞══ #main 391, scrolls ═════════════════════════════════════════════════════════════╡ y 194
│ chart strip 120: [Position | Valuation and growth] P/E NTM ▾ Primary   ⌃          │
│   dot plot, one lane 56, axis 24                                                  │
├── 8 ──────────────────────────────────────────────────────────────────────────────┤
│ toolbar 32 (outside the table box)                                                │
│ ┌ table box, max-height --main-h ───────────────────────────────────────────────┐ │
│ │ group header 22 · column header 40 (sticky)                                    │ │
│ │ frozen: ›20 ●28 Fit44 Company148 Ticker60 P/E84 = 384 │ scrolls sideways →    │ │
│ │ focal row 30 (sticky)                                                          │ │
│ │ peer rows 30 each                                                              │ │
│ │ tfoot: Median 26, n 26 (sticky; "Show mean and quartiles" adds three rows)     │ │
│ └────────────────────────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────────────────────┘
At rest: toolbar, headers, focal row, two peer rows, median and n. Collapsing the strip gives
five peer rows. Scrolling #main by 160 px gives the table box the whole 391 px: headers, focal
row, eight peer rows and the two summary rows.
```

Context bar at this width, 1,348 px inside the gutters, left to right with 8 px gaps: selector
72, name 120, subsector 76, stage 76, "Files USD" 64, then peer set 260, period segmented 200,
"Standardised, USD ▾" 172, "Ex amort." 92, "28 Sep" 60, "⋯" 26, help 30. Total 1,336 px. At a
1280 px screen (1,188 px inside) steps 7 and 8 also apply: period becomes "NTM ▾" (72) and the
peer set its short form (160), 1,108 px.

**1920 × 1080 screen: frame about 1860 × 735, `wide`, `tall`.** Band 254 px, `#main` 481 px.

```
x 0 ............................................................................... 1860
┌── context bar 40 (step 1: listing moved into the selector tooltip) ────────────────┐
├── banner 102 (ground) ──────────────────────────────────────────────────────────────┤
│ ▲ +6%  112 │ headline 21 px, one or two lines                                       │
│            │ support 14 px, at most two sentences                                   │
│            │ System-generated summary · Confidence: high ▮▮▮ · Look next: … →  Why? │
├── 16 ───────────────────────────────────────────────────────────────────────────────┤
├── KPI strip 68: five cells of 281 and KPI 5 at 422, with its position strip ────────┤
├── scope line 28 ────────────────────────────────────────────────────────────────────┤
╞══ #main 481 ════════════════════════════════════════════════════════════════════════╡
│ table 1212 (minmax(960, 2fr))                    │16│ rail 600 (capped)            │
│ toolbar 32                                          │ dot plot 176, one lane        │
│ table box: headers 62, focal 30, rows 30,           │ scatter controls 32           │
│ tfoot five rows 130 (all five shown at wide)        │ scatter 320                   │
│ frozen: ›20 ●28 Fit44 Company176 Ticker64 = 332     │ interpretation, two lines     │
└─────────────────────────────────────────────────────┴───────────────────────────────┘
```

**2560 × 1440 screen: frame about 2500 wide, `ultrawide`.** Table 1396, rail 600, side panel
440, two 16 px gaps and the 32 px gutter. With no panel open the table is 1852 px.

**Under 1100 px, `narrow`.** Context bar in two 36 px rows; banner as short mode; KPI strip in a
3 by 2 grid (88 px); scope line; then a 220 px two-tab chart strip; the table with frozen
`›`, `●`, Fit, Company (112), Ticker (56) and the primary column (80); the lower sections as one
tab strip.

---

## 2. Data contract: `GET /comps/valuation`

### 2.1 Conventions (stated once)

| Kind | Rule |
|---|---|
| Money | Millions of US dollars, suffix `_usd_m`, converted at the one ECB spot set in `fx.as_of`, using the unit on each filed row (`financials.unit`), never `companies.reporting_currency`. Full float precision; the client rounds. |
| Per share | US dollars per US-listed share (the quoted line), suffix none or `_per_share`. This covers `price`, `prev_close`, `range_52w`, `price_target` and its low and high, the model's `fair_value_per_share`, `range_today` and `forward_12m`, and street EPS. Filed EPS is the exception: `eps_diluted_rc` is in the row currency per ordinary share, for growth and the side panel only. |
| Ratios, rates, shares of a whole, growth | Decimals: 0.086 means 8.6 %. Guidance growth is stored in percent in the book (GSK 4.0) and is divided by 100 by the builder. |
| Share counts | Millions of US-listed shares, a plain count. `forecast_view._diluted_shares` returns a divisor with the reporting-currency rate folded in (shares / rate for a non-USD filer), so the builder multiplies that rate back out: `_diluted_shares(conn, id) × usd_per_unit[companies.reporting_currency] / 1e6`. |
| Dates | ISO `YYYY-MM-DD`. Timestamps ISO 8601 UTC with `Z`. |
| Nulls | A value with no free data, not filed, or not computable is `null`, never 0 and never estimated. Every `null` under `market`, `ev`, `periods`, `growth`, `street`, `risk`, `healthcare` and `model`, and a null `filer.standard` or `region`, has an entry in the record's `na` map giving a reason code (2.6). One entry on an object's path covers every null inside it when they share the reason (a null period object; guidance stated in words). `0` is a real zero (VRTX `loe_share_5y` is 0.0). |
| Multiples | Not precomputed. `core.js` computes every ratio from these components, so the currency, earnings-basis and period toggles cannot disagree with the backend. Growth rates are computed in the backend, because they are currency-internal and need rows the client does not receive; the backend also sends their bases in USD so the client can apply the n.m. floors of 4.2. |
| JSON | Strict: no NaN, no Infinity, no numpy scalars. The route serialises with `allow_nan=False` semantics (the builder passes every float through a `_finite()` guard). |
| Python | 3.9 compatible: `from __future__ import annotations`, no `match`, no runtime union syntax (`X \| Y`). |

### 2.2 Top level

```json
{
  "schema": 1,
  "generated_at": "2026-09-29T22:40:11Z",
  "complete": true,
  "incomplete_reason": null,
  "as_of": {
    "price_date": "2026-09-28",
    "price_trading_days_old": 0,
    "fx_date": "2026-09-28",
    "consensus_history_starts": "2026-09-17",
    "run": {"id": 123, "started_at": "2026-09-29T05:07:26Z", "finished_at": "2026-09-29T09:35:41Z",
            "status": "partial",
            "failed_sources": [
              {"source": "consensus_nasdaq", "ticker": "STOK", "message": "The read operation timed out"}
            ],
            "other_failures": ["approvals", "ndc_marketing", "paragraph_iv", "press_ir", "press_page"]}
  },
  "fx": {
    "as_of": "2026-09-28",
    "source": "ECB reference rates",
    "usd_per_unit": {"USD": 1.0, "EUR": 1.1378, "GBP": 1.326339, "CHF": 1.20224, "DKK": 0.15221}
  },
  "universe": {
    "n": 70,
    "engines": {"pharma": 18, "biotech": 26, "cellgene": 26},
    "engine_labels": {"pharma": "Big pharma", "biotech": "Biotech", "cellgene": "Cell and gene"},
    "absent_subsectors": ["Medtech", "Healthcare services"]
  },
  "basis_text": {
    "standardised": "{cur} at the ECB reference rate of 28 Sep 2026; per-share figures in USD per US-listed share; fiscal years as filed",
    "as_reported": "Each company's filing currency and standard, fiscal years as filed. Market cap and enterprise value are the USD market figures translated at the ECB rate of 28 Sep 2026; per-share figures stay in USD",
    "adjusted": "Operating income and EBITDA excluding tagged amortisation of intangibles and acquired IPR&D. Nothing is added back where operating income is derived",
    "street": "Nasdaq consensus, adjusted, per US-listed share, USD"
  },
  "companies": [],
  "errors": []
}
```

- `usd_per_unit` carries every currency that appears as a row unit in the universe, plus USD.
- `basis_text.standardised` is a template: `core.js` fills `{cur}` with the display currency, so
  the text never says USD while EUR is shown.
- `price_trading_days_old`: weekdays strictly between the newest `prices.as_of` in the universe
  and today (holidays not modelled).
- `as_of.run.status` is the stored `refresh_runs.status`: `"complete"`, `"partial"`,
  `"interrupted"`, `"failed"` or `"running"`. There is no `"ok"` value.
- `as_of.run.failed_sources`: parsed from `refresh_runs.detail` `$.sources[].errors` of the
  latest run, kept only for `VIEW_SOURCES = ("prices", "consensus_nasdaq", "financials", "fx")`.
  An error string that starts with a ticker and a colon (`"STOK: consensus_nasdaq: ..."`) gives
  that ticker; any other gives `ticker: null`, meaning the whole universe. `other_failures` lists
  the names of the other sources that reported errors, for the tooltip only.
- `complete` is false when any modelled company's cached fair-value or verdict read was missing
  (2.8). `incomplete_reason` is then `"model_not_computed"`.
- `errors`: one `{ticker, stage, message}` per company whose record builder raised. That company
  still appears in `companies` with `error` set and every value null.

### 2.3 Per-company record: fields

`field (type, unit)`: source to reuse. Defects from the data dictionary section 8 that must not
be copied are named.

**Identity**

| Field | Type | Source |
|---|---|---|
| `ticker`, `name` | str | `companies` |
| `engine` | `"pharma" \| "biotech" \| "cellgene"` | `engines.home(db_path)` (one call for all) |
| `stage` | `"commercial" \| "clinical"` | `runway.stage(conn, id)` |
| `country` | ISO2 str | `companies.country` as stored. It records the US listing, not the domicile, for several foreign-incorporated Nasdaq companies: CRSP, ARGX, QURE, AUTL, BNTX and LEGN are all stored as `US`. No free source in the book holds the domicile, so the view never calls this field the country of incorporation. |
| `region` | `"US" \| "Europe" \| "Other" \| null` | From `country`: Europe for GB, CH, DE, DK, FR, NL, BE, IE, SE, NO, ES, IT, AT, FI; US for `US`; Other otherwise. **Null** with `na` `domicile_unknown` when `country` is `US` but the company files a 20-F (BNTX, ARGX and LEGN today): a 20-F filer is by definition not a US company, and its real region is not stored. |
| `listing` | object | `{home_exchange, us_line, adr_ratio, otc}`. `home_exchange`: `companies.primary_exchange` normalised (`NASDAQ` and `Nasdaq` become `Nasdaq`, `NYSE` stays). `us_line`: `companies.us_adr_ticker` or null for a US company. `adr_ratio`: `adr_ratios.ordinary_per_adr` or null. `otc`: true when `primary_exchange` is `OTC` (SGMOQ) or when a US line exists for a company that is not an SEC registrant (`is_sec_filer = 0`: ROG's RHHBY and BAYN's BAYRY, which can only trade over the counter). The US line's venue is not otherwise stored, so the UI never names one. |
| `filer` | object | `{kind, annual_form, standard, standard_source, is_sec_filer, is_fpi_flag}`. `annual_form`: the latest of `10-K`, `20-F`, `40-F` in `filings.form_type` by `filed_date`, or null. `kind`: "10-K filer", "20-F filer" or "40-F filer" from `annual_form`; "not an SEC filer" when `is_sec_filer = 0`; null otherwise. `standard`, first rule that applies: (1) the `taxonomy` recorded in the newest `snapshots` row with `source='financials'` for this ticker (`$.taxonomy`: `us-gaap` gives "US GAAP", `ifrs-full` gives "IFRS"), `standard_source` "filed facts"; (2) "IFRS" for a non-SEC workbook filer (ROG, BAYN) or when `is_foreign_private_issuer = 1`, source "company record"; (3) "US GAAP" for a 10-K filer, source "form"; (4) otherwise null with `na` `standard_not_recorded` (a 20-F filer may report under either standard; BNTX, ARGX and LEGN until the next financials refresh). The FPI flag is not used for `kind`: BNTX, ARGX and LEGN carry `is_foreign_private_issuer = 0` yet file 20-F and 6-K. `is_fpi_flag` passes the stored flag through unchanged. |
| `reporting_currency` | str | `companies.reporting_currency` |
| `row_currency` | str | unit of the FY0 `Revenues` row, else of the FY0 cash-flow row. Differs from `reporting_currency` for BNTX (EUR). |
| `fiscal_year_end_month` | int 1 to 12 | month of the FY0 period end after `financials_view._nearest_month_end` (ARWR 9; JNJ and EXEL 12) |
| `themes` | str[] | `company_themes.theme`, sorted |
| `areas` | `{area: compounds}` | `notecontext._pipeline_areas(conn, id)`, top 5 by count, `"Healthy volunteers"` dropped |

Recording the taxonomy (owner A, part of this build): `fetchers/financials_edgar.py` and
`fetchers/financials_esef.py` add `"taxonomy": "us-gaap" | "ifrs-full"` to the snapshot payload
they already write, naming the taxonomy that supplied the `Revenues` fact. A fixture test covers
both. The field fills on the next financials refresh; until then rule (4) applies to the three
20-F filers without the FPI flag, and the UI says "standard not recorded".

**`market`**

| Field | Type, unit | Source and rule |
|---|---|---|
| `price` | float, USD per US-listed share | latest `prices` close, `interval='1d'` |
| `price_currency` | str | one pass over `snapshots` `source='prices'` `$.currency` (not the per-company `comps._price_currency` scan, which costs 0.9 s) |
| `price_as_of` | date | `prices.as_of` |
| `prev_close`, `change_1d` | float USD per US-listed share, decimal | second latest close; `price / prev_close − 1` |
| `quote_fetched_at` | timestamp | `MAX(snapshots.captured_at)` for `source='prices'`, `$.fetch_kind='live'` |
| `ttm_change` | decimal | `screen._ttm_change(conn, id)` |
| `range_52w` | `{low, high}`, USD per US-listed share | min low and max high of `prices` over the 365 days to `price_as_of` |
| `spark_90d` | float[], USD per US-listed share, at most 60 | a new helper `_spark(conn, company_id, today, days=90, max_points=60)` in `comps_valuation.py`: 1d closes with `as_of` after `today − days` and on or before `today`, downsampled evenly at indices `round(i × (n − 1) / (max_points − 1))`, which always keeps the first and the last close, so the line ends on `price_as_of`. `comps.price_grid` is not used: it reads `date('now')` rather than the builder's `today`, and its downsampling drops the latest close. |
| `shares_cover_m`, `shares_cover_as_of` | float, date | latest `SharesOutstanding` instant / (`adr_ratio` or 1) / 1e6, and its `period_end` (the cover-page date) |
| `shares_diluted_m`, `shares_basis` | float, str | `forecast_view._diluted_shares(conn, id) × usd_per_unit[companies.reporting_currency] / 1e6` (2.1), and "FY2025 weighted average diluted" or the fallback the helper used |
| `market_cap_usd_m` | float | **Basic route**, `price × shares_cover_m`, when a cover count exists, is dated within `COVER_COUNT_MAX_AGE_DAYS = 400` of `price_as_of`, and the ticker is not in `COVER_COUNT_EXCEPTIONS`. Otherwise the **diluted route**, `price × shares_diluted_m`. Never `comps._market_cap`, which is null for 12 names. |
| `market_cap_basis` | `"shares_outstanding" \| "diluted_weighted"` | which route |
| `market_cap_basis_text` | str | "Shares outstanding at the 2026-07-31 cover date", or "FY2025 weighted diluted shares, per US-listed share", followed by the reason when the diluted route was forced: "; the cover count is from 2012-07-13" or "; the cover count includes employee benefit trust shares" |
| `market_cap_shares_m` | float | `market_cap_usd_m / price`: the share count behind the market cap actually used. The bridge divides by it (3.9). |
| `market_cap_alt_usd_m` | float or null | the other route when both counts exist and are within a factor of `SHARE_SCALE_LIMIT = 5` of each other. Outside that factor the alternative is null with `na` `share_count_scale`: IOVA files its weighted diluted count in thousands (357,345 against a 453m cover count), which would read as a 99.9 % disagreement. |
| `market_cap_disagreement` | decimal or null | `abs(market_cap_usd_m / market_cap_alt_usd_m − 1)` when both exist |
| `beta`, `beta_basis` | float, str | `beta.compute(conn, ticker)` |
| `vol_1y` | decimal | annualised stdev of daily log returns over 365 days, needs over 200 returns: `stdev × sqrt(252)` (new helper in `comps_valuation.py`) |

`COVER_COUNT_EXCEPTIONS` is a dict in `comps_valuation.py`, each entry a ticker and the sentence
that justifies it. It starts with one entry: `"LLY": "The cover count includes about 50m shares
held by the employee benefit trust, which are not outstanding for EPS."` An entry is added only
with a cited reason. The cover count stays primary where it disagrees with the FY weighted
diluted count for an ordinary reason: issuance since the fiscal year end (VOR, EDIT, ALLO, IPSC)
or buybacks (EXEL, UTHR). There the cover count is the current one and the weighted count lags.

**`ev`**

| Field | Type, unit | Source and rule |
|---|---|---|
| `net_debt_usd_m` | float | `cashflow.build_cashflow(db, t)['net_debt_usd'] / 1e6`. Negative is net cash. Never the undated `comps._company_comps` debt. |
| `total_debt_usd_m`, `cash_usd_m` | float | `inputs.total_debt`, `inputs.cash`, converted at the row unit |
| `cash_lines` | str[] | `inputs.cash_lines` |
| `balance_sheet_as_of`, `debt_as_of`, `debt_basis` | date, date, str | `inputs.*` |
| `ev_usd_m` | float or null | `market_cap_usd_m + net_debt_usd_m`. Null with `na` `no_debt_line` when net debt is null. Debt is never assumed to be 0. |
| `other_claims_usd_m` | float or null | `other_claims.for_company(conn, t)['total']` (reporting-currency millions, signed like net cash: positive adds to equity) converted to USD. Null with `na` `none_on_file` when no lines. |
| `other_claims_lines` | object[] | `{label, value_usd_m (signed), as_of, basis}` |

**`periods`**: one object per basis; a missing basis is `null` with an `na` entry.

| Key | Tag | Fields |
|---|---|---|
| `FY0` | A | `label` ("FY2025"), `period_end`, `unit` (row currency), `revenue_usd_m`, `gross_profit_usd_m` (GrossProfit, else revenue less abs CostOfRevenue; `gross_basis` says which), `operating_income_usd_m`, `operating_income_basis` (`"reported" \| "derived"`, from `cashflow` `inputs.operating_income_basis`), `da_usd_m`, `ebitda_usd_m` (`cashflow` `ebitda_usd`), `amortisation_usd_m` (AmortisationOfIntangibles, null if untagged), `acquired_iprd_usd_m` (AcquiredIprd, null if untagged), `net_income_usd_m` and `net_income_basis` (below), `fcf_usd_m` (`cashflow` `fcf_usd`), `rd_usd_m`, `rd_ex_iprd_usd_m` (ResearchLessExpensedIprd), `tax_rate` (IncomeTaxExpense / IncomeBeforeTax clamped 0 to 0.5; null with `na` `no_tax_rate` when pre-tax income is not positive or not filed), `equity_usd_m`, `equity_as_of` and `equity_basis` (below), `eps_diluted_rc` |
| `FYm1` | A | the prior year: `label`, `period_end`, `revenue_usd_m`, `operating_income_usd_m`, `da_usd_m`, `ebitda_usd_m`, `amortisation_usd_m`, `acquired_iprd_usd_m`, `net_income_usd_m`, `eps_diluted_rc` |
| `FYm3` | A | three years before FY0: `label`, `revenue_usd_m` only, for the CAGR floor |
| `LTM` | A | `label` ("LTM Jun-26"), `period_end`, `revenue_usd_m`, `net_income_usd_m`. Built as FY + current cumulative YTD − prior-year same YTD, taking the cumulative row whose `fiscal_period` matches the months elapsed (not the discrete Q row on the same date). Null with `no_ltm_20f` when `filer.kind` is "20-F filer" or "not an SEC filer" (their 6-K interims carry no XBRL, and the workbooks publish no interims here), `no_ltm` otherwise. |
| `FY1`, `FY2`, `FY3` | E | `label` ("FY2026"), `eps`, `eps_low`, `eps_high`, `eps_n` (parsed from `note` "9 estimates"), `as_of`. Nasdaq rows, newest `as_of` per period (`consensus.latest`). FY1 is the first fiscal year whose end is on or after `price_as_of`, using `fiscal_year_end_month`. |
| `FY1.guidance` | G | See below. |
| `NTM` | E | `eps`, `weight_fy1`, `sign_change`, `basis_text`. `weight_fy1` = days from `price_as_of` to the FY1 end / 365, clamped 0 to 1; `eps = w × FY1.eps + (1 − w) × FY2.eps`. Uses the fiscal year end month, which fixes the December assumption in `fair_value._ntm_eps` (ARWR). `sign_change` is true when one of FY1 and FY2 EPS is at or below 0 and the other is above 0 (GILD −0.48 and 9.87; AXSM, ATRA, LEGN). Null with `na` `no_consensus` when FY1 is missing and `no_fy2_consensus` when only FY2 is missing: a twelve-month blend is never built from one year. |

Net income and equity, `net_income_basis` and `equity_basis`:

- `net_income_usd_m` is `NetIncomeAttributableToParent` where the book stores it (ROG and BAYN
  today, from their workbooks: ROG 12,880m CHF attributable against 13,799m total), with basis
  `"attributable to shareholders"`. Otherwise it is `NetIncomeLoss`, basis `"as filed"`.
- For a US GAAP filer `NetIncomeLoss` and `StockholdersEquity` are the parent's share already.
  For an IFRS filer, `statements.py` maps `NetIncomeLoss` to `ifrs-full:ProfitLoss` and
  `StockholdersEquity` to `ifrs-full:Equity`, both of which include non-controlling interests.
  When `filer.standard` is "IFRS" and no attributable row is stored, the builder adds a flag
  `includes_minorities` with `field` `periods.FY0.net_income_usd_m` or `periods.FY0.equity_usd_m`.
  Storing the attributable lines for 20-F and ESEF filers is a fetcher change outside this build
  (appendix A.3).

`FY1.guidance` (G) is `{value_usd_m, low_usd_m, high_usd_m, growth, growth_low, growth_high,
metric_scope, fx_basis, text, as_of}` or null with `no_guidance`:

- Rows: `consensus_estimates` with `source='guidance'`, the FY1 period label, metrics `Revenue`,
  `ProductSales` and `RevenueGrowth`. For each metric the newest `as_of` wins (LLY has three
  FY2026 Revenue rows; the 2026-08-05 row is used).
- `value_usd_m` and its low and high come from `Revenue`, else `ProductSales`, converted from the
  row's `currency` at the ECB rate. `value` is the midpoint the book stores.
- `growth` and its low and high come from `RevenueGrowth`, divided by 100 (the book stores 4.0
  for GSK's 3 % to 5 %, −3.0 for NVO, 10.0 for SNY).
- `metric_scope`, first rule that applies, over the note's "Scope:" clause when it has one (the
  text after "Scope:" up to the next full stop) and the whole note otherwise:
  `"product"` when the metric is `ProductSales` (GILD, INCY); `"product"` when the text matches
  `/not total revenues?/i`; `"total"` when it matches `/\btotal revenues?\b|\btop line\b/i`
  (AZN's scope line "Total Revenue (Product Revenue plus Collaboration Revenue)", AMGN, BMRN,
  VRTX, MRK); `"product"` when it matches `/\bproduct (revenue|sales)/i` (ALNY "combined net
  product revenue", SRPT "total net product revenue", AUTL "AUCATZYL net product revenue");
  otherwise `"total"` (IOVA "revenue guidance", LLY, PFE, BMY, JNJ, EXEL). Run over every FY2026
  guidance row in the book, these rules give the classes named here.
- `fx_basis` is the stored value: `"reported"`, `"reported_with_stated_rate_date"`, `"cer"` or
  null.
- `text` is the verbatim note. It is shown only as an attributed quotation (4.4), never as
  generated prose.
- A guide in words has the numbers null and `text` set, with `guidance_in_words` on the numbers.

**`growth`** (decimals, backend-computed, null with a reason when the base is not positive)

| Field | Rule |
|---|---|
| `revenue_fy` | FY0 / FYm1 − 1, in the row currency (NVO in DKK) |
| `revenue_cagr3` | (FY0 / FYm3)^(1/3) − 1, in the row currency |
| `ebitda_fy` | EBITDA FY0 / FYm1 − 1, same derivation both years; base must be positive |
| `ebitda_fy_adjusted` | as above with tagged acquired IPR&D added back in both years (amortisation is already inside D&A); equals `ebitda_fy` when nothing is tagged, **and when `operating_income_basis` is `"derived"`** (derived operating income never subtracted the separately presented IPR&D, so adding it back would count it twice: LLY's $3,008m) |
| `eps_fy_gaap` | filed diluted EPS FY0 / FYm1 − 1, row currency per ordinary share; base positive |
| `eps_street_fy2` | FY2.eps / FY1.eps − 1, FY1 positive |
| `eps_street_cagr` | (FY3.eps / FY1.eps)^(1/2) − 1, both positive |
| `revenue_guided_fy1` | Computed only when `metric_scope` is `"total"` and `fx_basis` is `"reported"`, `"reported_with_stated_rate_date"` or null: guided FY1 revenue / FY0 revenue − 1, or the guided growth figure (already a decimal). `fx_basis` null adds the flag `guidance_fx_unstated`. Product scope gives null with `guidance_product_scope` (SRPT's product guide of $1,250m over $2,198m of total revenue would read −43 %). Constant currency gives null with `guidance_cer` (NVO, SNY, AZN, NVS). FY26E / FY25A for EPS is never computed. |
| `bases` | `{revenue_fy: [fy0, fym1], revenue_cagr3: [fy0, fym3], ebitda_fy: [fy0, fym1], eps_fy_gaap: [fy0, fym1], eps_street_fy2: [fy1, fy2], eps_street_cagr: [fy1, fy3]}`: money in USD m, EPS per share, so `core.js` can apply the base floors and the magnitude cap of 4.2. |

**`street`**

| Field | Rule |
|---|---|
| `price_target` | `{value, low, high, as_of, ratings: {buy, hold, sell}}`, USD per US-listed share, from Nasdaq `PriceTarget 12M`, counts parsed from `note` |
| `consensus_checked_at` | `MAX(snapshots.captured_at)` for `source='consensus_nasdaq'`, this ticker |
| `eps_first` | `{FY1: {value, as_of}, FY2: {value, as_of}}` the oldest row per period, for revision arrows |

**`risk`**

| Field | Rule |
|---|---|
| `runway_months` | `runway._row(conn, company, today)['runway_months']`. Null for three different reasons, each with its own code: `not_burning` when the trailing burn is zero or positive (`burn_annual ≥ 0`); `no_cash_flow` when there is no burn figure at all (`burn_annual` null, ROG has no operating cash flow row); `no_cash` when the liquidity figure is missing. Months are a ratio of cash to burn in one currency, so BNTX's column defect does not change them. |
| `runway_basis`, `burn_flattered`, `cash_out` | same row |
| `est_dispersion` | (FY1 high − FY1 low) / abs(FY1 mean); null when the mean is null |
| `pt_dispersion` | (target high − low) / target mean |

**`healthcare`**

| Field | Rule |
|---|---|
| `lead_phase` | `engines._lead_stage(conn, tickers)` (one call): "Marketed", "Filed", "Phase 3", "Phase 2/3", "Phase 2", "Phase 1/2", "Phase 1", "Preclinical" |
| `major_products` | count of assets with latest-FY `asset_revenue` of at least USD 1bn (FX-converted); null with `no_product_revenue` |
| `top_product_share` | top product over tagged product revenue |
| `trial_concentration` | top asset's share of lead-sponsored active mapped trials; `active_mapped_trials` beside it |
| `late_trials`, `catalysts_12m`, `loe_share_5y`, `loe_unpriced_5y`, `revenue_per_late_trial_usd_m` | `screen.build_screen()` row (one call for all) |

**`model`** (section 2.8): `state` (`"modelled" \| "not_modelled" \| "not_computed" \| "failed"`),
`fair_value_per_share`, `rating`, `range_today` `[low, high]`, `forward_12m`, `upside_12m`
(from cached `/companies/{t}/fair-value` `equity_per_share` and `rating.*`), `pipeline_rnpv_usd_m`,
`pipeline_per_share`, `pipeline_per_share_unrisked`, `pipeline_assets` (from cached
`/companies/{t}/forecast-verdict` `sotp.pipeline.{rnpv, per_share, per_share_unrisked, n}`;
`rnpv` is reporting-currency millions and is converted), `price_date`.

**`flags`**: `[{code, field, severity, params}]`, codes in 2.5. **`na`**: `{path: code}`, codes in
2.6. **`lineage`**: `{price_as_of, quote_fetched_at, consensus_checked_at, balance_sheet_as_of,
fy_period_end, financials_source, fx_as_of}`. **`history`**: `{labels: ["FY20", ...], revenue_growth:
[...], net_margin: [...]}` from `comps.comps_trend()` (one call). **`screen_extras`**:
`{net_margin, rd_pct}` from `screen.build_screen()` (FY0 as filed). **`detail`**: section 2.7.
**`error`**: null or a message.

### 2.4 Example record: AZN (real values from the book)

`spark_90d` has at most 60 values; three are shown. `detail` is shown in 2.7.

```json
{
  "ticker": "AZN",
  "name": "AstraZeneca PLC",
  "engine": "pharma",
  "stage": "commercial",
  "country": "GB",
  "region": "Europe",
  "listing": {"home_exchange": "London", "us_line": "AZN", "adr_ratio": 1.0, "otc": false},
  "filer": {"kind": "20-F filer", "annual_form": "20-F", "standard": "IFRS",
            "standard_source": "company record", "is_sec_filer": true, "is_fpi_flag": true},
  "reporting_currency": "USD",
  "row_currency": "USD",
  "fiscal_year_end_month": 12,
  "themes": [],
  "areas": {"Oncology": 58, "Renal and hepatic": 10, "Metabolic": 8, "Cardiovascular": 6, "Respiratory": 6},
  "market": {
    "price": 166.15,
    "price_currency": "USD",
    "price_as_of": "2026-09-28",
    "prev_close": 166.58,
    "change_1d": -0.002581,
    "quote_fetched_at": "2026-09-29T05:46:07Z",
    "ttm_change": 0.126288,
    "range_52w": {"low": 147.38, "high": 212.71},
    "spark_90d": [164.56, 166.58, 166.15],
    "shares_cover_m": null,
    "shares_cover_as_of": null,
    "shares_diluted_m": 1564.679,
    "shares_basis": "FY2025 weighted average diluted",
    "market_cap_usd_m": 259971.4,
    "market_cap_basis": "diluted_weighted",
    "market_cap_basis_text": "FY2025 weighted diluted shares, per US-listed share",
    "market_cap_shares_m": 1564.679,
    "market_cap_alt_usd_m": null,
    "market_cap_disagreement": null,
    "beta": 0.56,
    "beta_basis": "computed from 261 weekly returns vs S&P 500, 2021-W39 to 2026-W40, Blume-adjusted (0.33 raw)",
    "vol_1y": 0.284471
  },
  "ev": {
    "net_debt_usd_m": 23903.0,
    "total_debt_usd_m": 29622.0,
    "cash_usd_m": 5719.0,
    "cash_lines": ["CashAndEquivalents", "ShortTermInvestments"],
    "balance_sheet_as_of": "2025-12-31",
    "debt_as_of": "2025-12-31",
    "debt_basis": "filed",
    "ev_usd_m": 283874.4,
    "other_claims_usd_m": -855.0,
    "other_claims_lines": [
      {"label": "equity-method investments", "value_usd_m": 302.0, "as_of": "2025-12-31", "basis": "filed"},
      {"label": "noncontrolling interests", "value_usd_m": -52.0, "as_of": "2025-12-31", "basis": "filed"},
      {"label": "pension and post-employment deficit", "value_usd_m": -1105.0, "as_of": "2025-12-31", "basis": "filed"}
    ]
  },
  "periods": {
    "FY0": {
      "label": "FY2025", "period_end": "2025-12-31", "unit": "USD",
      "revenue_usd_m": 58739.0, "gross_profit_usd_m": 48106.0, "gross_basis": "GrossProfit",
      "operating_income_usd_m": 13743.0, "operating_income_basis": "reported",
      "da_usd_m": 5086.0, "ebitda_usd_m": 18829.0,
      "amortisation_usd_m": 4207.0, "acquired_iprd_usd_m": null,
      "net_income_usd_m": 10233.0, "net_income_basis": "as filed", "fcf_usd_m": 11765.0,
      "rd_usd_m": 14232.0, "rd_ex_iprd_usd_m": 14232.0,
      "tax_rate": 0.174891, "equity_usd_m": 48719.0, "equity_as_of": "2025-12-31",
      "equity_basis": "as filed",
      "eps_diluted_rc": 6.54
    },
    "FYm1": {
      "label": "FY2024", "period_end": "2024-12-31",
      "revenue_usd_m": 54073.0, "operating_income_usd_m": 10003.0, "da_usd_m": 4722.0,
      "ebitda_usd_m": 14725.0, "amortisation_usd_m": 3923.0, "acquired_iprd_usd_m": null,
      "net_income_usd_m": 7041.0, "eps_diluted_rc": 4.5
    },
    "FYm3": {"label": "FY2022", "revenue_usd_m": 44351.0},
    "LTM": null,
    "FY1": {
      "label": "FY2026", "eps": 9.37, "eps_low": 5.18, "eps_high": 10.34, "eps_n": 6, "as_of": "2026-09-23",
      "guidance": {"value_usd_m": null, "low_usd_m": null, "high_usd_m": null,
                   "growth": null, "growth_low": null, "growth_high": null,
                   "metric_scope": "total", "fx_basis": "cer",
                   "text": "AstraZeneca reconfirms Total Revenue and Core EPS guidance for FY 2026 at CER, based on the average foreign exchange rates through 2025. Total Revenue is expected to increase by a mid-to-high single-digit percentage (accession 0001104659-26-086846, ...)",
                   "as_of": "2026-07-27"}
    },
    "FY2": {"label": "FY2027", "eps": 10.55, "eps_low": 5.75, "eps_high": 11.8, "eps_n": 7, "as_of": "2026-09-23"},
    "FY3": {"label": "FY2028", "eps": 12.09, "eps_low": 11.52, "eps_high": 12.41, "eps_n": 3, "as_of": "2026-09-20"},
    "NTM": {"eps": 10.246110, "weight_fy1": 0.257534, "sign_change": false,
            "basis_text": "FY2026 and FY2027 consensus EPS weighted by the days of each in the twelve months from 2026-09-28"}
  },
  "growth": {
    "revenue_fy": 0.086291, "revenue_cagr3": 0.098182,
    "ebitda_fy": 0.278710, "ebitda_fy_adjusted": 0.278710,
    "eps_fy_gaap": 0.453333, "eps_street_fy2": 0.125934, "eps_street_cagr": 0.135909,
    "revenue_guided_fy1": null,
    "bases": {"revenue_fy": [58739.0, 54073.0], "revenue_cagr3": [58739.0, 44351.0],
              "ebitda_fy": [18829.0, 14725.0], "eps_fy_gaap": [6.54, 4.5],
              "eps_street_fy2": [9.37, 10.55], "eps_street_cagr": [9.37, 12.09]}
  },
  "street": {
    "price_target": {"value": 211.066, "low": 155.015, "high": 267.633, "as_of": "2026-09-29",
                     "ratings": {"buy": 14, "hold": 2, "sell": 0}},
    "consensus_checked_at": "2026-09-29T05:47:36Z",
    "eps_first": {"FY1": {"value": 9.16, "as_of": "2026-09-17"}, "FY2": {"value": 10.44, "as_of": "2026-09-17"}}
  },
  "risk": {
    "runway_months": null, "runway_basis": "last full year", "burn_flattered": false, "cash_out": null,
    "est_dispersion": 0.550694, "pt_dispersion": 0.533578
  },
  "healthcare": {
    "lead_phase": "Marketed", "major_products": 15, "top_product_share": 0.147570,
    "trial_concentration": 0.057471, "active_mapped_trials": 174,
    "late_trials": 56, "catalysts_12m": 36, "loe_share_5y": 0.261990, "loe_unpriced_5y": 8,
    "revenue_per_late_trial_usd_m": 1048.911
  },
  "model": {
    "state": "modelled", "fair_value_per_share": 175.381, "rating": "Buy",
    "range_today": [149.970, 208.878], "forward_12m": 185.337, "upside_12m": 0.115479,
    "pipeline_rnpv_usd_m": 19547.97, "pipeline_per_share": 12.493, "pipeline_per_share_unrisked": 24.077,
    "pipeline_assets": 22, "price_date": "2026-09-28"
  },
  "flags": [
    {"code": "stale_balance_sheet", "field": "ev", "severity": "amber", "params": {"as_of": "2025-12-31", "days": 272}},
    {"code": "estimate_range_wide", "field": "periods.FY1", "severity": "amber", "params": {"low": 5.18, "high": 10.34, "mean": 9.37, "n": 6}},
    {"code": "market_cap_diluted_route", "field": "market.market_cap_usd_m", "severity": "info", "params": {}},
    {"code": "ifrs_filer", "field": "filer", "severity": "info", "params": {}},
    {"code": "includes_minorities", "field": "periods.FY0.net_income_usd_m", "severity": "amber", "params": {"line": "net income"}},
    {"code": "includes_minorities", "field": "periods.FY0.equity_usd_m", "severity": "amber", "params": {"line": "equity"}}
  ],
  "na": {
    "periods.LTM": "no_ltm_20f",
    "periods.FY0.acquired_iprd_usd_m": "not_tagged",
    "periods.FYm1.acquired_iprd_usd_m": "not_tagged",
    "periods.FY1.guidance": "guidance_in_words",
    "growth.revenue_guided_fy1": "guidance_in_words",
    "market.shares_cover_m": "no_shares",
    "market.shares_cover_as_of": "no_shares",
    "market.market_cap_alt_usd_m": "no_shares",
    "market.market_cap_disagreement": "no_shares",
    "risk.runway_months": "not_burning",
    "risk.cash_out": "not_burning"
  },
  "lineage": {
    "price_as_of": "2026-09-28", "quote_fetched_at": "2026-09-29T05:46:07Z",
    "consensus_checked_at": "2026-09-29T05:47:36Z", "balance_sheet_as_of": "2025-12-31",
    "fy_period_end": "2025-12-31", "financials_source": "edgar_companyfacts", "fx_as_of": "2026-09-28"
  },
  "history": {
    "labels": ["FY20", "FY21", "FY22", "FY23", "FY24", "FY25"],
    "revenue_growth": [0.091576, 0.405756, 0.185317, 0.032919, 0.180350, 0.086291],
    "net_margin": [0.118120, 0.003073, 0.074249, 0.130122, 0.130213, 0.174211]
  },
  "screen_extras": {"net_margin": 0.174211, "rd_pct": 0.242292},
  "detail": {},
  "error": null
}
```

What `core.js` derives from this record, as a check for B's tests (NTM basis, standardised USD,
reported earnings): P/E NTM 166.15 / 10.2461 = 16.22; P/E FY0 259971.4 / 10233 = 25.41; EV/Revenue
FY0 283874.4 / 58739 = 4.83; EV/EBITDA 283874.4 / 18829 = 15.08; FCF yield 11765 / 259971.4 = 4.53 %;
P/B 259971.4 / 48719 = 5.34; operating margin 13743 / 58739 = 23.40 %, adjusted
(13743 + 4207) / 58739 = 30.56 %; ROIC 13743 × (1 − 0.174891) / (48719 + 29622 − 5719) = 15.61 %;
net debt / EBITDA 23903 / 18829 = 1.27; PEG 16.22 / 13.59 = 1.19; market cap / revenue
259971.4 / 58739 = 4.43; market cap / cash 259971.4 / 5719 = 45.46. Company type profitable,
primary `pe`. At the illustrative focal-excluded pharma median of 15.36× (3.11) the bridge gives
15.36 × 10.2461 = 157.38 per share, −5.28 % against the price; at AZN's own 16.2159× it gives
166.15, the price.

Compact pre-revenue record, CRSP (only the fields that differ in kind are shown):

```json
{
  "ticker": "CRSP", "name": "CRISPR Therapeutics AG", "engine": "cellgene", "stage": "clinical",
  "country": "US", "region": "US",
  "listing": {"home_exchange": "Nasdaq", "us_line": null, "adr_ratio": null, "otc": false},
  "filer": {"kind": "10-K filer", "annual_form": "10-K", "standard": "US GAAP",
            "standard_source": "form", "is_sec_filer": true, "is_fpi_flag": false},
  "themes": ["CAR-T", "Cell therapy", "Gene editing", "Gene therapy", "RNA", "mRNA"],
  "market": {"price": 54.09, "price_as_of": "2026-09-28", "change_1d": -0.002582,
             "shares_cover_m": 96.693, "shares_cover_as_of": "2026-07-31",
             "market_cap_usd_m": 5230.1, "market_cap_basis": "shares_outstanding",
             "market_cap_basis_text": "Shares outstanding at the 2026-07-31 cover date",
             "market_cap_shares_m": 96.693,
             "market_cap_alt_usd_m": 4864.0, "market_cap_disagreement": 0.075,
             "shares_diluted_m": 89.925, "beta": 1.26, "vol_1y": 0.596504},
  "ev": {"net_debt_usd_m": -1778.154, "total_debt_usd_m": 586.198, "cash_usd_m": 2364.352,
         "cash_lines": ["CashAndEquivalents", "ShortTermInvestments", "MarketableSecuritiesNoncurrent"],
         "balance_sheet_as_of": "2026-06-30", "debt_basis": "filed", "ev_usd_m": 3451.95,
         "other_claims_usd_m": null, "other_claims_lines": []},
  "periods": {
    "FY0": {"label": "FY2025", "revenue_usd_m": 3.51, "operating_income_usd_m": -664.571,
            "ebitda_usd_m": -645.092, "net_income_usd_m": -581.599, "fcf_usd_m": -345.928,
            "equity_usd_m": 1746.551, "gross_profit_usd_m": null},
    "FYm1": {"label": "FY2024", "revenue_usd_m": 37.314, "operating_income_usd_m": -466.566, "net_income_usd_m": -366.252},
    "LTM": {"label": "LTM Jun-26", "period_end": "2026-06-30", "revenue_usd_m": 13.392},
    "FY1": {"label": "FY2026", "eps": -4.47, "eps_low": -5.63, "eps_high": -3.39, "eps_n": 11, "as_of": "2026-09-29"},
    "FY2": {"label": "FY2027", "eps": -3.61, "eps_low": -5.4, "eps_high": -1.18, "eps_n": 11, "as_of": "2026-09-29"},
    "NTM": {"eps": -3.831479, "weight_fy1": 0.257534}
  },
  "growth": {"revenue_fy": -0.905934, "revenue_cagr3": 0.430925, "ebitda_fy": null, "eps_street_fy2": null},
  "street": {"price_target": {"value": 73.58, "low": 45.0, "high": 110.0, "as_of": "2026-09-19",
                              "ratings": {"buy": 8, "hold": 5, "sell": 0}}},
  "risk": {"runway_months": 76.77, "runway_basis": "trailing twelve months to 2026-06-30",
           "burn_flattered": false, "cash_out": "2033-02-17", "est_dispersion": 0.501119},
  "healthcare": {"lead_phase": "Phase 1/2", "major_products": null, "loe_share_5y": null,
                 "trial_concentration": 0.666667, "active_mapped_trials": 6, "late_trials": 0, "catalysts_12m": 0},
  "model": {"state": "not_modelled", "fair_value_per_share": null, "pipeline_rnpv_usd_m": null},
  "flags": [{"code": "estimate_range_wide", "field": "periods.FY1", "severity": "amber",
             "params": {"low": -5.63, "high": -3.39, "mean": -4.47, "n": 11}}],
  "na": {"periods.FY0.gross_profit_usd_m": "not_filed", "growth.ebitda_fy": "non_positive_base",
         "growth.eps_street_fy2": "non_positive_base", "healthcare.major_products": "no_product_revenue",
         "healthcare.loe_share_5y": "no_product_revenue", "model.fair_value_per_share": "not_modelled",
         "model.pipeline_rnpv_usd_m": "not_modelled", "ev.other_claims_usd_m": "none_on_file"}
}
```

From this `core.js` must produce: company type `clinical`, not pre-revenue (revenue is on file);
P/E n.m. (EPS negative), EV/Revenue and market cap / revenue n.m. (revenue under USD 100m; the
raw EV/Revenue would be 983x), EV/EBITDA n.m. (EBITDA negative), FCF yield n.m. (negative), P/B
5230.1 / 1746.6 = 2.99, market cap / cash 5230.1 / 2364.4 = 2.21 (the primary metric), cash /
market cap 2364.4 / 5230.1 = 45.2 %, revenue growth and revenue CAGR n.m. (revenue under USD 10m
at one end), net debt / EBITDA n.m. (the tool today reads 2.76), runway 77 months. CRSP is
incorporated in Switzerland; the book stores `US` and, with a 10-K on file, the region stays US
(2.3 explains the limit).

### 2.5 Flag codes (backend emits, `core.js` words them)

| Code | Severity | Trigger | Params |
|---|---|---|---|
| `stale_price` | amber | weekdays strictly between `price_as_of` and today is 1 or more | `as_of, trading_days` |
| `stale_consensus` | amber | `consensus_checked_at` more than 3 days before today | `checked_at, days` |
| `stale_balance_sheet` | amber | `balance_sheet_as_of` more than 200 days before today | `as_of, days` |
| `stale_fiscal_year` | amber | FY0 `period_end` more than 456 days (15 months) before today | `label, period_end` |
| `source_failed` | amber | a `VIEW_SOURCES` source failed for this ticker, or for the universe, in the latest run | `source, run_id, message` |
| `fx_converted` | info | `row_currency` is not USD | `from, rate, as_of` |
| `currency_mismatch` | amber | any money row unit differs from `companies.reporting_currency` | `company_currency, row_units` |
| `fiscal_year_end` | amber | `fiscal_year_end_month` is not 12 | `month` |
| `ifrs_filer` | info | `filer.standard == "IFRS"` | none |
| `non_sec_filer` | info | not an SEC registrant (ROG, BAYN) | `source` (`financials_ir`) |
| `includes_minorities` | amber | IFRS filer with no stored attributable row, on net income or equity (2.3) | `line` (`"net income"` or `"equity"`) |
| `market_cap_diluted_route` | info | the diluted route is used because no cover count exists (AZN, NVO, ROG, BAYN) | none |
| `stale_shares` | amber | a cover count exists but is dated more than 400 days before `price_as_of`, the ticker is not in `COVER_COUNT_EXCEPTIONS`, and so the diluted route is used (REGN 2012-07-13; ADAPY 2025-08-11) | `as_of, days` |
| `cover_count_exception` | info | the ticker is in `COVER_COUNT_EXCEPTIONS`, so the diluted route is used whatever the cover count's date | `reason` |
| `market_cap_disagreement` | amber | both routes exist and `market_cap_disagreement` is over 0.10 | `primary, alt, pct, primary_basis, alt_basis, reason` |
| `derived_operating_income` | amber | `operating_income_basis == "derived"` (BMY, LLY, MRK and PFE in the current book) | none |
| `no_consensus` | amber | no Nasdaq EPS rows | `otc` (from `listing.otc`: true for BAYN, ROG and SGMOQ) |
| `thin_estimates` | amber | `eps_n` under 3 for FY1, FY2 or FY3; one flag per period (FY2028 has 1 or 2 estimates for BMRN, KRYS, REGN and VRTX) | `period, n` |
| `estimate_range_wide` | amber | `est_dispersion` over 0.5 with `eps_n` at least 3 | `low, high, mean, n` |
| `eps_sign_change` | amber | `periods.NTM.sign_change` | `fy1, fy2` |
| `guidance_fx_unstated` | amber | numeric guidance with `fx_basis` null is used for a guided cell | none |
| `burn_flattered` | amber | runway row says so | none |
| `calc_failed` | red | the record builder raised | `message` |

Flags touch cells through their `field` (2.3 paths) as listed in section 8. `thin_estimates`
for FY3 touches `peg` and `eps_cagr`; for FY2 it touches `eps_growth` on forward bases and P/E
FY2.

### 2.6 Null reason codes

`no_free_data`, `not_filed`, `not_tagged`, `no_debt_line`, `no_shares`, `share_count_scale`,
`no_consensus`, `no_consensus_otc`, `no_fy2_consensus`, `no_ltm_20f`, `no_ltm`, `no_guidance`,
`guidance_in_words`, `guidance_product_scope`, `guidance_cer`, `non_positive_base`,
`one_year_only`, `no_tax_rate`, `not_modelled`, `model_not_computed`, `model_failed`,
`no_prices`, `insufficient_history`, `not_burning`, `no_cash_flow`, `no_cash`,
`no_product_revenue`, `no_trials`, `no_rate`, `none_on_file`, `standard_not_recorded`,
`domicile_unknown`, `calc_failed`. Copy for each is in `core.NA_TEXT` (section 3.12).

### 2.7 Detail record (side panel)

Shape proven by `scratchpad/proto_detail.py`; median 5.2 KB, largest 8.2 KB (JNJ).

```json
{
  "spark": {"closes": [148.26, 170.62, 168.37], "change": 0.135640},
  "relative": {
    "1m": {"company_pct": 0.024795, "relative_pct": 0.016730, "covers_window": true},
    "3m": {"company_pct": -0.123774, "relative_pct": -0.207320, "covers_window": true},
    "1y": {"company_pct": 0.120666, "relative_pct": -0.160583, "covers_window": true}
  },
  "earnings": {
    "unit": "USD",
    "fy": [{"fy": 2024, "revenue_usd_m": 54073.0, "net_income_usd_m": 7041.0, "eps_rc": 4.5},
           {"fy": 2025, "revenue_usd_m": 58739.0, "net_income_usd_m": 10233.0, "eps_rc": 6.54}],
    "quarters": [{"label": "Q2-25", "period_end": "2025-06-30", "revenue_usd_m": 14457.0, "eps_rc": 1.57, "derived": false}]
  },
  "results": {"period_end": "2025-06-30", "revenue_usd_m": 14457.0, "yoy": 0.117406, "eps_rc": 1.57},
  "revisions": [
    {"metric": "EPS", "period": "FY2026", "value": 9.37, "first_value": 9.16, "first_as_of": "2026-09-17", "as_of": "2026-09-23", "revisions": 2, "n": 6, "low": 5.18, "high": 10.34},
    {"metric": "EPS", "period": "FY2027", "value": 10.55, "first_value": 10.44, "first_as_of": "2026-09-17", "as_of": "2026-09-23", "revisions": 2, "n": 7, "low": 5.75, "high": 11.8},
    {"metric": "PriceTarget", "period": "12M", "value": 211.066, "first_value": 213.026, "first_as_of": "2026-09-17", "as_of": "2026-09-29", "revisions": 9, "n": null, "low": 155.015, "high": 267.633}
  ],
  "catalysts": [
    {"type": "data readout", "expected_date": "2026-09-30", "date_confidence": "estimated", "title": "Phase 3, Imfinzi", "is_curated": false, "source_url": "https://clinicaltrials.gov/study/NCT05557838"}
  ],
  "pipeline": {"compounds": {"Phase 1": 27, "Phase 1/2": 28, "Phase 2": 12, "Phase 2/3": 0, "Phase 3": 23, "Phase 4": 2}, "unattributed": 1},
  "products": {"fiscal_year": 2025, "rows": [{"name": "Farxiga", "value_usd_m": 8400.0, "share": 0.1476}], "unattributed_usd_m": null},
  "filings": [{"form": "6-K", "filed_date": "2026-09-23", "title": "TRIXEO APPROVED IN EU FOR ASTHMA", "url": "https://www.sec.gov/Archives/edgar/data/901832/000165495426008520/a8652v.htm"}],
  "notes": {"system": {"generated_at": "2026-09-22T19:50:51Z", "model": "gemini-flash-latest", "excerpt": "Commercial execution remains robust, evidenced by FY2025 revenue reaching 58.7B USD, up 9% year-on-year"}},
  "lineage": {
    "sources": {"prices": {"live": "2026-09-29T05:46:07Z", "error": "2026-09-19T09:13:42Z"},
                "consensus_nasdaq": {"live": "2026-09-29T05:47:36Z", "error": "2026-09-19T09:32:15Z"}},
    "financials": {"latest_period_end": "2025-12-31", "sources": ["edgar_companyfacts"]},
    "fx_as_of": "2026-09-28",
    "refresh_run": {"id": 123, "finished_at": "2026-09-29T09:35:41Z", "status": "partial"}
  }
}
```

Rules: `spark.closes` at most 52, from `_spark(conn, id, today, days=365, max_points=52)` (2.3),
which keeps the latest close (not `comps.price_grid`);
`relative` from `comps.relative_performance`; `earnings.fy` at most 5; `earnings.quarters` at most
8 from `financials_view.build_statements(ticker, basis="quarterly", limit=8)` with `derived` kept
(Q4 is derived as FY less 9M; 7 names have no quarters and send `[]`); `revisions` only EPS FY1,
FY2 and the 12M target (guidance rows are in `periods.FY1.guidance`); `catalysts` the next 5
pending on or after today; `products.rows` at most 6; `filings` the latest 5; `notes.system` the
latest `insights` row, excerpt at most 400 characters, null for the 46 companies with none;
`lineage.sources` per source the newest live and newest error `captured_at` from one `GROUP BY`.
Never in the bundle: full price series, `consensus.street_view` (12 s), `catalyst_stakes` (5.5 s),
verdict `modelled` lists. Analyst notes are not in the payload; they live in `localStorage`.

### 2.8 Caching, cost and the model block

> Revision 3: `COMPANY_READS` gains the comps-context read, built the same cache-only way (12.2).

- `comps_valuation.build(db_path=None, today=None) -> dict`. `today` defaults to
  `dt.date.today()`; tests pass a fixed date. One connection, one pass per global helper
  (`engines.home`, `engines._lead_stage`, `screen.build_screen`, `comps.price_grid` twice,
  `comps.comps_trend`, `fx.latest_usd_rates`), then a per-company loop wrapped in try/except that
  sets `error` and `calc_failed` instead of failing the whole response.
- Budget: under 5 s cold for 70 on the live book, under 900 KB raw.
- Route in `main.py`: `@app.get("/comps/valuation")`. When `complete` is false it returns a
  `JSONResponse` with header `x-cache-skip: 1`.
- `response_cache.py`: add `LATE_GLOBAL_READS = ("/comps/valuation",)`, fetched in `warm_forever`
  after every `COMPANY_READS` url, so the fair-value and verdict entries it reads are warm. In
  `handle()`, return the response unstored when it carries `x-cache-skip: 1` (checked before the
  body is read). Together these stop an incomplete body being served as a hit.
- The model block reads only `response_cache.cached_json("/companies/{t}/fair-value")` and
  `cached_json("/companies/{t}/forecast-verdict")` for the companies with a modelled book (a join
  of `assets` to `assumptions`, as `response_cache._tickers` does). A missing entry gives
  `state: "not_computed"` and `complete: false`. `ok: false` gives `state: "failed"`. A company
  with no book gives `"not_modelled"`. The model block never drives the headline.

---

## 3. `core.js` API

Pure ES module: no DOM, no `window`, no storage, no `Date.now()` (callers pass time). Every
export below is used by at least one renderer or test. Numbers are plain JS numbers; `null` means
absent and is never coerced to 0.

### 3.1 Constants

```js
export const SCHEMA = 1;
export const STORAGE_KEY = "er.compsval.v1";          // localStorage
export const SESSION_KEY = "er.compsval.session.v1";  // sessionStorage
export const BASES = ["NTM", "FY1", "FY2", "FY0", "LTM"];
export const CURRENCIES = ["USD", "EUR", "GBP", "CHF", "DKK", "REPORTED"];
export const MIN_PEERS = 5;                 // fewer valid values: low confidence
export const MAX_DEFAULT_PEERS = 15;
export const MIN_DEFAULT_RELEVANCE = 40;    // also the floor for an "appropriate" peer
export const MIN_MEDIAN_RELEVANCE = 50;     // confidence penalty under this
export const MIN_REVENUE_USD_M = 100;       // revenue multiples, margins and R&D share below this are n.m.
export const MIN_GROWTH_BASE_USD_M = 10;    // revenue growth and CAGR n.m. when either end is below this
export const MIN_EBITDA_GROWTH_BASE_USD_M = 10;  // EBITDA growth n.m. when abs(base) is below this
export const MIN_EPS_GROWTH_BASE = 0.10;    // EPS growth and CAGR n.m. when abs(base EPS) is below this
export const MAX_ABS_GROWTH = 5.0;          // abs(growth) over 500 % is n.m., every growth column
export const MAX_REVENUE_MULTIPLE = 100;    // EV/Revenue and market cap / revenue over 100x are n.m.
export const MIN_MARGIN = -1.0;             // margins below -100 % are n.m.
export const MIN_EPS_FOR_DISPERSION = 0.10; // abs(mean EPS) below USD 0.10: dispersion n.m.
export const IN_LINE_PCT = 5;               // in line when the premium rounds to under 5 whole percent
export const NEAR_TREND_BAND = 0.10;        // abs(relative residual) under 10 %: near trend
export const MIN_SCATTER_PEERS = 3;         // fewer peers with both values: no scatter
export const TUKEY_K = 1.5, TUKEY_EXTREME_K = 3.0;
export const MAX_DISPERSION_RATIO = 0.6;    // iqr / median above this costs a confidence point
export const MAX_DERIVED_SHARE = 0.25;      // share of peer values on derived operating income
export const WIDE_RANGE_MIN_ESTIMATES = 5;  // estimate_range_wide counts for confidence under this n
export const WIDE_RANGE_MAX = 1.0;          // ... or above this dispersion
export const MAX_HEADLINE_CHARS = 160, MAX_SUPPORT_SHORT_CHARS = 90, MAX_LOOK_NEXT_CHARS = 60;
export const SHORT_FRAME_PX = 720, COLLAPSE_AT_PX = 120, EXPAND_BELOW_PX = 40;
export const FROZEN_MAX_SHARE = 0.40;       // frozen columns may cover at most this share of the table box
export const UNDO_MS = 5000;
export const RELEVANCE_WEIGHTS = {subsector: 0.25, model: 0.20, scale: 0.20,
                                  profitability: 0.15, growth: 0.15, geography: 0.05};
// Metrics a premium or discount can be stated on. Every other metric shows a position only.
export const PREMIUM_METRICS = ["pe", "ev_ebitda", "ev_revenue", "price_to_sales",
                                "price_to_book", "fcf_yield", "peg", "mcap_to_cash"];
export const BRIDGEABLE = ["pe", "ev_revenue", "ev_ebitda", "price_to_sales",
                           "price_to_book", "fcf_yield", "mcap_to_cash"];
export const BANNED_WORDS = [/* the six words CLAUDE.md's house style bans, lower case */];
```

`usesFiledFigures(colId, basis) -> boolean` is true for `pe` on FY0 or LTM, `ev_ebitda`,
`price_to_book`, `fcf_yield`, and the profitability columns. It decides whether a
mixed-standards penalty applies (3.11): street P/E on NTM, FY1 or FY2 is one adjusted basis for
every filer, and revenue, market cap and cash do not depend on the standard in a way this view can
measure.

### 3.2 Statistics

| Function | Semantics |
|---|---|
| `finite(values) -> number[]` | Keeps `typeof v === "number" && Number.isFinite(v)`. Drops null, undefined, NaN. |
| `quantile(values, p) -> number \| null` | Sort ascending a copy of `finite(values)`. Empty: null. Linear interpolation between closest ranks (R type 7, numpy default, Excel PERCENTILE.INC): `h = (n − 1) × p`, `lo = floor(h)`, result `x[lo] + (h − lo) × (x[lo + 1] − x[lo])`; `n = 1` returns that value. |
| `median(values)` | `quantile(values, 0.5)` |
| `mean(values)` | Arithmetic mean of `finite(values)`; empty: null. |
| `summarize(values) -> {n, mean, median, p25, p75, iqr, min, max} \| null` | Null when n is 0. `iqr = p75 − p25`. |
| `percentileRank(value, values) -> number \| null` | Mid-rank percent over `finite(values)` (the peer set, focal excluded): `(below + 0.5 × equal) / n × 100`. Null when value is null or n is 0. **Reported as a number only** ("62nd percentile"); it never decides a quartile. |
| `quartileSide(value, values) -> "top" \| "bottom" \| null` | `"top"` when `value ≥ quantile(values, 0.75)`, `"bottom"` when `value ≤ quantile(values, 0.25)`, else null; null when fewer than `MIN_PEERS` values. The same function and the same values the summary rows use, so a "top quartile" statement always agrees with the p75 row. Example: peers 1 to 8, focal 6.1: p75 is 6.25, so not top (the mid-rank percentile is 75). |
| `premium(value, reference, direction) -> number \| null` | `direction` from `multipleDirection`. `"richer_up"`: `value / reference − 1`. `"richer_down"` (yields): `reference / value − 1`. Null when the direction is null, when either input is null, or either is at or below 0. |
| `isInLine(p) -> boolean` | `Math.round(Math.abs(p) × 100) < IN_LINE_PCT`. The chip, the token and the headline all read the same rounded whole percent, so "in line" never sits beside "+5%". |
| `fences(values, k = TUKEY_K) -> {lo, hi} \| null` | Tukey: `p25 − k × iqr`, `p75 + k × iqr`. Null when n is under 5. |
| `outlierClass(value, values) -> "extreme" \| "mild" \| null` | Extreme outside the 3.0 fences, mild outside the 1.5 fences, else null; null when n is under 5. |
| `ols(points) -> {slope, intercept, r2, n} \| null` | Least squares y on x over points with both finite. Null when n is under 5 or the x variance is 0. `r2 = 1 − SSres / SStot` (0 when SStot is 0). |

Every statistic, percentile and quartile side for a column is computed over the same value set:
the included peers of the active statistics group, with outliers removed when the outlier mode is
`"exclude"` (3.7).

### 3.3 Classification

| Function | Semantics |
|---|---|
| `companyType(c) -> "profitable" \| "loss_making" \| "sub_scale" \| "clinical"` | `clinical` when `stage === "clinical"`. Else `sub_scale` when FY0 revenue is null or under `MIN_REVENUE_USD_M` (ABEO, AUTL and QURE today). Else `loss_making` when FY0 operating income is at or below 0 (or, when operating income is null, FY0 net income is at or below 0). Else `profitable`. Forward consensus does not decide the type: a company that made an operating profit last year is profitable even when one consensus year dips below zero (GILD, whose FY1 EPS is −0.48); that dip makes its P/E NTM not meaningful instead (4.2). |
| `isPreRevenue(c) -> boolean` | FY0 revenue is null or exactly 0 (12 companies today: CABA, DYN, GPCR, KYTX, PEPG, SANA, VOR with no revenue rows; ALLO, CAPR, RCKT, RVMD, VKTX with revenue filed as 0). Only these get the "Pre-revenue" chip. |
| `TYPE_LABEL` | `{profitable: "profitable", loss_making: "loss-making", sub_scale: "commercial with revenue under $100m", clinical: "clinical-stage"}` |
| `typeGroup(type)` | `profitable` → "profitable"; `loss_making` → "loss-making"; `sub_scale` and `clinical` → "pre-scale". Used by `mixedModels`. |
| `engineAffinity(a, b) -> number` | Same engine 1.0; biotech and cellgene 0.5; pharma and biotech 0.3; pharma and cellgene 0.1. |
| `phaseRank(phase) -> number \| null` | Preclinical 0, Phase 1 1, Phase 1/2 1.5, Phase 2 2, Phase 2/3 2.5, Phase 3 3, Filed 3.5, Marketed 4; any other value null (the component is then dropped). |

A clinical-stage company with real revenue (ARWR $829m, STOK $184m, BEAM $140m, IPSC $109m) is
`clinical`, and no copy ever says it has no revenue: the "Pre-revenue" chip and the words "no
revenue" appear only when `isPreRevenue` is true.

### 3.4 Cells and multiples

`cell(company, colId, ctx) -> Cell`, where `ctx = {basis, currency, earnings, fx, fy0Label}` and

```ts
Cell = {
  v: number | null,              // value in display units (money already in display currency m)
  status: "ok" | "na" | "nm" | "nb" | "err",   // nb: not burning
  text: string,                  // formatted, e.g. "16.2", "−1.6", "—", "n.m.", "no burn"
  reason: string | null,         // tooltip sentence for na, nm, nb, err
  tag: "A" | "E" | "G" | "M" | null,
  period: string | null,         // "FY2025", "LTM Jun-26", "NTM", "FY2026"
  tagDiffers: boolean,           // this cell's basis differs from its column's basis
  unit: string | null,           // only set in REPORTED currency mode for money columns
  flags: string[],               // flag codes that touch this cell (2.5) plus client flags below
}
```

Rules shared by every column (column-specific formulas are in section 4):

- Money: `usd_m` converts to the display currency as `usd_m / fx.usd_per_unit[cur]`. In
  `REPORTED` mode the currency is the record's `row_currency` and `unit` is set.
- Missing input: `status "na"`, `text "—"`, `reason` from `NA_TEXT[na code]` of the first null
  input, or `"No free data for this measure."` when the column itself has no source.
- Not meaningful: `status "nm"`, `text "n.m."`, `reason` from the column's n.m. rule.
- Basis: the column's supported bases are in section 4. When the global basis is unsupported the
  column uses its declared default for every row; that is the column's design, not a fallback, so
  nothing on the column turns amber. Only `LTM` falls back per cell: a company with no LTM gets
  its FY0 value with `tag "A"`, `period "FY2025"`, `tagDiffers true`.
- A cell whose company has `error` is `status "err"`, `text "—"`, reason
  `"Calculation failed for this company."`.
- Earnings basis `adjusted` ("Ex amort. and IPR&D") changes only: operating income (+ amortisation
  + acquired IPR&D where tagged), EBITDA (+ acquired IPR&D where tagged), and what depends on
  them. Two cases keep the reported value:
  - Neither line is tagged: client flag `no_tagged_addbacks`, reason `"No tagged amortisation or
    IPR&D, so the figure equals GAAP/IFRS."`.
  - `operating_income_basis === "derived"` (revenue less cost of sales, R&D and SG&A): client flag
    `derived_no_addback`, reason `"Operating income here is derived from revenue less cost of
    sales, R&D and SG&A, which already leaves out separately presented amortisation and IPR&D, so
    nothing is added back."`. Without this rule LLY's operating margin would move from 45.6 % to
    about 50.9 % by adding back an IPR&D charge that was never subtracted.
- Forward columns are always street adjusted whatever the toggle.

`multipleDirection(colId) -> "richer_up" | "richer_down" | null`: `richer_down` for `fcf_yield`;
`richer_up` for `pe`, `ev_ebitda`, `ev_revenue`, `price_to_sales`, `price_to_book`, `peg` and
`mcap_to_cash`; null for every other column, including `pt_upside` and `pipeline_to_ev` (a larger
upside or pipeline share means cheaper, not richer, and neither is a multiple) and `market_cap`,
`ev`, `cash_to_mcap` and `runway_months`. `premium()` returns null for a null direction.

### 3.5 Metric availability and the primary metric

`METRIC_CANDIDATES` (the dot plot switcher, in order): `["pe", "ev_ebitda", "ev_revenue",
"price_to_sales", "price_to_book", "fcf_yield", "peg", "mcap_to_cash", "market_cap", "ev",
"cash_to_mcap", "runway_months", "pt_upside", "ev_per_late_trial", "pipeline_to_ev"]`. Metrics in
`PREMIUM_METRICS` carry a premium or discount; the others plot a position and a percentile only
and are tagged "Position only" in the switcher.

`metricAvailability(focal, peers, colId, ctx) -> {enabled, n, premium, reason}`: enabled when the
focal cell is `ok` and at least 2 included peers are `ok`; `premium` is
`PREMIUM_METRICS.includes(colId)`. Reasons: `"Not meaningful for {T}: {cell reason}"`, `"Only {n}
peer has a value"`, `"No peer has a value"`.

`primaryMetric(focal, peers, ctx, override) -> {colId, basis, state, reasonText, fallbackFrom}`:

1. `override` (the analyst's choice, persisted per engine) wins when it is in `PREMIUM_METRICS`
   and enabled. An override outside `PREMIUM_METRICS` is ignored and cleared by `migrateState`.
2. Candidates by `companyType(focal)`:
   - `profitable`: `pe` (basis NTM, or the global basis when it is FY1, FY2, FY0 or LTM), then
     `ev_ebitda` (FY0), then `ev_revenue` (LTM with per-cell FY0 fallback), then
     `price_to_sales` (LTM with per-cell FY0 fallback).
   - `loss_making`: `ev_revenue`, then `price_to_sales`, then `mcap_to_cash`. P/B is not a
     candidate: on a cash-heavy balance sheet it measures the cash, and BNTX (null EV) would
     otherwise read as an 81 % discount on P/B.
   - `sub_scale` and `clinical`: `mcap_to_cash`. Market cap over cash and investments is the
     one scale-free valuation measure every one of the 70 companies has, and it has a peer median
     wherever a peer has cash on file.
3. Take the first candidate whose focal cell is `ok` and that has at least `MIN_PEERS` ok peer
   values: `state "ok"`.
4. Else the first candidate with the focal ok and 2 to 4 ok peers: `state "low_confidence"`.
5. Else, when the focal is ok on some candidate but no candidate has 2 ok peers:
   `state "too_few"`, `colId` the first candidate the focal is ok on. The focal value is shown;
   no premium is stated (KRYS: profitable with a P/E NTM of 38.6, one commercial cell and gene
   peer with a P/E and no peer with an EV).
6. Else (the focal is ok on no candidate): `state "no_multiple"`, `colId` null. The dot plot
   defaults to the first of `cash_to_mcap`, `runway_months`, `market_cap` with the focal ok.

`reasonText` (first line of "Why?" and the KPI 4 tooltip), exact templates:

- ok, first candidate: "{label} is primary: {T} is {type label} and {k} of {n} peers have a
  value." Example: "P/E NTM is primary: AZN is profitable and 14 of 15 peers have a value."
- ok, a later candidate: "{label} is primary: {earlier label} is not available ({reason of the
  earlier candidate}), and {k} of {n} peers have a value." Example: "EV/EBITDA is primary: P/E
  NTM is not available (not meaningful for GILD: consensus moves from a loss to a profit within
  the next twelve months), and 13 of 15 peers have a value."
- clinical or sub-scale: "Market cap / cash is primary: {T} is {type label}, so revenue and
  earnings multiples are not used, and {k} of {n} peers have a value."
- override: "{label} is primary: chosen by you. The dot plot's "Use as primary" sets it; "Reset
  primary" in its menu restores the default."
- `low_confidence`, `too_few`, `no_multiple`: the state's own line from 3.11.

The primary metric and the dot plot metric are separate (3.15 `dotMetric`): browsing metrics in
the dot plot never rewrites the conclusion.

### 3.6 Peer relevance and the default set

> Revision 3: step 2 of `defaultPeers` is replaced by 12.8 (a cohort of 20 or fewer is taken whole).

`relevance(focal, peer) -> {score, level, components, missing}`. Each component is 0 to 1; a
component whose input is null for either company is dropped and the weights renormalise over the
rest. `score = round(100 × Σ w·s / Σ w)`. `level`: high at 70 and over, medium 50 to 69, low
under 50.

| Component | Weight | Formula |
|---|---|---|
| `subsector` | 0.25 | `0.6 × engineAffinity + 0.4 × focus`, where `focus` is the mean of the cosine similarity of the `areas` vectors and the Jaccard index of `themes`, over whichever of the two exist for both. With neither, `subsector = engineAffinity`. |
| `model` (business model) | 0.20 | 1.0 same `typeGroup`; 0.5 same stage, different `typeGroup`; 0 different stage. |
| `scale` | 0.20 | `1 − min(1, abs(log10(mcap_a) − log10(mcap_b)) / 1.5)`: a 10x gap scores 0.33, 32x or more scores 0. |
| `profitability` (or clinical stage) | 0.15 | Both commercial: `1 − min(1, abs(m_a − m_b) / 0.40)` on FY0 operating margin clamped to −1 to 1. Both clinical: `1 − abs(phaseRank_a − phaseRank_b) / 4`. Mixed: 0. |
| `growth` | 0.15 | `1 − min(1, abs(g_a − g_b) / 0.30)` on `growth.revenue_fy` clamped to −0.5 to 1.0. |
| `geography` | 0.05 | Same country 1.0, same region 0.7, else 0.4. Dropped when either `region` is null (a 20-F filer stored as US), since the stored country is then known to be wrong. |

An **appropriate peer** is an included peer with a relevance score of at least
`MIN_DEFAULT_RELEVANCE`. The peer set is **weak** when fewer than 5 appropriate peers are
included, whatever the total count.

`defaultPeers(focal, universe) -> {tickers, reasons, pools, warning}`:

1. Candidates: every record except the focal and records with `error`.
2. Pool A: same engine and same stage. Rank by score desc, then market cap desc, then ticker.
   Keep scores of `MIN_DEFAULT_RELEVANCE` or more, at most `MAX_DEFAULT_PEERS`.
3. Under 5: add from pool B (same engine, other stage) by score until 5.
4. Still under 5: add from pool C (adjacent engine by `engineAffinity` of 0.5 or more, same stage).
5. `reasons[ticker]`: pool A `"Same subsector and stage, relevance {s}"`; pool B `"Added to reach
   five peers: same subsector, {stage} stage, relevance {s}"`; pool C `"Added to reach five peers:
   adjacent subsector, relevance {s}"`. `pools[ticker]` is `"A"`, `"B"` or `"C"`.
6. `warning`: `"too_few"` when still under 5 after pool C; else `"padded"` when any pool B or C
   peer scores under 40; else null. Both surface as states in section 8.

`setLabel(state, view) -> {full, short, noun}`, used by the peer set control, the peer panel, the
CSV header and the headline:

| Set | `full` | `short` | `noun` (headline) |
|---|---|---|---|
| System, one stage | "{engine label}, {stage}, {n}" ("Big pharma, commercial, 15") | "{engine label}, {n}" | "{engine label, lower case} peers", with "clinical" before it for a clinical set ("big pharma peers", "clinical cell and gene peers") |
| System, pools B or C used | "{engine label}, mixed stages, {n}" or "{engine label} and adjacent, {n}" | "{engine label}+, {n}" | "{engine label, lower case} and adjacent peers" |
| Saved | "'{name}', {n}" | the same, name cut at 16 characters with "…" | "peers in '{name}'" |
| Edited | "Custom, {n}" | "Custom, {n}" | "selected peers" |
| Subgroup active for statistics | set label, plus the scope chip "Statistics over: {subgroup}" | as set | "{subgroup} peers" |

`mixedModels(focal, included) -> null | {focalType, otherType, k, n}`: raised when the set,
focal counted, holds both a "profitable" and a "pre-scale" `typeGroup`, or when fewer than half
the included peers share the focal's `typeGroup`. `otherType` is the most common different type.

### 3.7 Peer statistics

`peerStats(view rows, colId, ctx, {outliers: "include" | "exclude", group}) -> Summary & {nm, na,
outliers: {mild: ticker[], extreme: ticker[]}, values}`. Over included peers only: the focal,
excluded rows and rows outside `group` never count. With `"exclude"`, mild and extreme outliers
(fences computed on the included values) are removed for that column only. Filters never change
statistics. `values` is the value set after these rules; `percentileRank`, `quartileSide`, the
premium, the observations and the confidence all read it, so every number on screen for a column
comes from one set.

### 3.8 Scatter regression and regions

`scatterModel(focal, rows, xCol, yCol, ctx, opts) -> {points, trend, reference, rel, region,
interpretation, description, domain, disabledReason}`. The fit uses included peers with both
values ok (outliers removed when the outlier mode is exclude); the focal is not in the fit.

- Disabled when the focal lacks x or y, or fewer than `MIN_SCATTER_PEERS` peers have both
  values (copy in section 8).
- With a trend (`ols` not null): `ŷ = intercept + slope × x_focal`. When `ŷ ≤ 0` or `ŷ` is under
  10 % of the peer median of y, the trend gives no usable reference at the focal's x, so
  `reference = "median"` and `rel = y_focal / median(y) − 1`. Otherwise `reference = "trend"` and
  `rel = (y_focal − ŷ) / ŷ`.
- Without a trend (n under 5): `reference = "median"` as above.
- `xSide`: `"better"` or `"worse"` than the peer median of x by the x column's direction (4.2:
  `+` higher is better, `−` lower is better); for a neutral x column (`n`), `"above"` or
  `"at or below"`.

| Region id | Condition | Label (neutral; x short name from the axis, for example "revenue growth") |
|---|---|---|
| `near` | `abs(rel) < NEAR_TREND_BAND` | "Near the peer trend" (or "Near the peer median" when `reference = "median"`) |
| `above_better` | `rel ≥ 0.10`, x better than the median | "Above trend, {x short} better than median" |
| `above_worse` | `rel ≥ 0.10`, x at or worse than the median | "Above trend, {x short} at or worse than median" |
| `below_better` | `rel ≤ −0.10`, x better than the median | "Below trend, {x short} better than median" |
| `below_worse` | `rel ≤ −0.10`, x at or worse than the median | "Below trend, {x short} at or worse than median" |

For a neutral x "better" and "worse" read "above median" and "at or below median". With
`reference = "median"`, "trend" in the labels reads "peer median". The labels describe position
only: a point below trend is not called cheap and a point above trend is not called expensive.

`domain` follows the dot plot rule (5.1): min to max of the plotted values, focal included,
excluding Tukey-extreme values (n ≥ 5), which are clamped to the edge. Interpretation copy is in
5.2.

### 3.9 Valuation bridge

`bridge(focal, rows, inputs, ctx) -> Bridge`. `inputs` (persisted per focal):
`{colId, stat: "median" | "mean" | "p25" | "p75" | "pct", pct, multipleOverride, metricOverride,
netDebtOverride, sharesSource: "market_cap" | "diluted" | "analyst", sharesOverride,
otherClaimsOn, otherClaimsOverride}`. Defaults: the primary metric when it is in `BRIDGEABLE`,
else the first `BRIDGEABLE` metric enabled for the focal; `median`; no overrides;
`sharesSource: "market_cap"`; `otherClaimsOn: false` (peer enterprise values exclude other
claims, so applying the focal company's alone is off by default; the row says so).

```
M  = multipleOverride ?? peerStat(colId, stat)              // applied multiple (or yield)
X  = metricOverride   ?? focal operating metric on the column's basis
EV multiples (ev_revenue, ev_ebitda):
   EVi = M × X                                              // display currency m
   ND  = netDebtOverride ?? ev.net_debt_usd_m (converted)
   OC  = otherClaimsOn ? (otherClaimsOverride ?? ev.other_claims_usd_m (converted, signed)) : 0
   Eq  = EVi − ND + OC
P/E on NTM, FY1, FY2:   V = M × EPS (USD per US-listed share); Eq = V × S
P/E on FY0 or LTM:       Eq = M × net income;  V = Eq / S
Market cap / revenue:    Eq = M × revenue;     V = Eq / S
P/B:                     Eq = M × equity;      V = Eq / S
Market cap / cash:       Eq = M × cash;        V = Eq / S
FCF yield:               Eq = FCF / M;         V = Eq / S
S  = sharesSource "market_cap": market.market_cap_shares_m (the count behind the market cap the
     peer multiples use); "diluted": market.shares_diluted_m; "analyst": sharesOverride
V  = Eq / S in USD per US-listed share (per-share figures are always USD, the quote currency;
     in a non-USD display currency Eq is converted back to USD before the division)
upside = V / price − 1
range  = the same with M at p25 and at p75, reported as [min, max] of the two values
```

The default S makes the bridge self-consistent: at the focal company's own multiple it returns
the current price exactly, on every route. With the FY weighted diluted count instead, LLY at its
own EV/Revenue would show a +5.2 % "upside" that is only the gap between 941m cover shares and
894.8m diluted shares. The diluted count stays available as a choice, with its basis text.

Guards, each giving `enabled: false` with a reason: column not bridgeable; focal X null
(`"{T} has no {metric} on this basis."`); X at or below 0; EV multiple with net debt null; S
null. `Eq ≤ 0` keeps the bridge but sets `V` null with reason `"Implied equity is negative: net
debt and claims exceed the implied enterprise value."`. The other-claims toggle is disabled when
`ev.other_claims_usd_m` is null, with the reason `NA_TEXT.none_on_file`.

`Bridge` carries `steps[]`, one per row in section 5.3, each
`{id, label, value, unit, source: "sourced" | "calculated" | "analyst", sourceText, editable}`,
and `description` (5.3).

### 3.10 Drivers and risks

> Revision 3: these rules stand and feed `view.insight.valuation`, which adds items from catalysts and competition (12.3).

`observations(focal, rows, ctx) -> {premium: Obs[], discount: Obs[], notAssessed: string[]}`,
`Obs = {id, side, colId, value, median, pct, strength, severity, provenance, short, tag, long}`.
A quartile rule fires only with at least `MIN_PEERS` ok peer values and uses `quartileSide`
(3.2), never `pct`. `strength = abs(pct − 50)` for quartile rules and 50 for absolute rules;
lists sort by strength desc and show 5 per side.

A rule does not fire when the focal's cell for its column carries `derived_operating_income`,
`derived_no_addback`, `includes_minorities`, `thin_estimates` or `estimate_range_wide`; the flag
is listed in "Why?" instead. So LLY's derived 45.6 % operating margin does not become a "top
quartile margin" observation.

| id | Side | Column | Fires when | `long` (panel) | `tag` (at most 40 characters) |
|---|---|---|---|---|---|
| `growth_top` | premium | `revenue_growth` | top quartile | "Revenue growth of {v} is in the top quartile of peers (median {m})." | "revenue growth top quartile" |
| `eps_growth_top` | premium | `eps_growth` (street) | top quartile | "Street EPS growth of {v} is in the top quartile of peers (median {m})." | "EPS growth top quartile" |
| `margin_top` | premium | `operating_margin` | top quartile | "Operating margin of {v} is in the top quartile of peers (median {m})." | "operating margin top quartile" |
| `roic_top` | premium | `roic` | top quartile | "Return on invested capital of {v} is in the top quartile of peers (median {m})." | "ROIC top quartile" |
| `pipeline_depth` | premium | `late_trials` | top quartile | "{v} late-stage trials against a peer median of {m}." | "late-stage trials top quartile" |
| `pipeline_value` | premium | `pipeline_to_ev` | top quartile | "Modelled pipeline value is {v} of enterprise value against a peer median of {m}. Model output." | "pipeline value top quartile (model)" |
| `leverage_low` | premium | `net_debt_ebitda` | bottom quartile, or focal net cash while the peer median is net debt | "Net debt of {v} EBITDA against a peer median of {m}." | "leverage bottom quartile" |
| `loe_low` | premium | `loe_share_5y` | bottom quartile | "{v} of product revenue loses US exclusivity within five years, against a peer median of {m}." | "patent exposure bottom quartile" |
| `visibility` | premium | `est_dispersion` | bottom quartile and FY1 estimates ≥ 5 | "Analyst EPS estimates span {v} of the mean, narrower than most peers (median {m})." | "narrow estimate range" |
| `runway_long` | premium | `runway_months` | clinical or sub-scale focal, runway ≥ 36 and top quartile | "Cash runway of {v} months against a peer median of {m}." | "runway top quartile" |
| `loss_making` | discount | `operating_margin` | `companyType` is `loss_making` | "Operating loss in {period}: operating margin of {v}." | "operating loss" |
| `runway_short` | discount | `runway_months` | runway under 24 (severity red under 12) | "Cash runway of {v} months on trailing burn." | "runway under 24 months" |
| `product_concentration` | discount | `top_product_share` | 0.50 or more | "{v} of product revenue comes from one product." | "one product over half of sales" |
| `trial_concentration` | discount | `trial_concentration` | 0.50 or more with 3 or more active trials | "{v} of active trials study one asset." | "trials concentrated on one asset" |
| `binary_catalysts` | discount | `catalysts_12m` | clinical or sub-scale focal with 1 or more | "{v} clinical catalysts due within 12 months, with little or no product revenue beside them. Dates are mostly estimated." | "binary catalysts in 12 months" |
| `patent_cliff` | discount | `loe_share_5y` | 0.30 or more, or top quartile | "{v} of product revenue loses US exclusivity within five years (peer median {m})." | "patent exposure top quartile" |
| `leverage_high` | discount | `net_debt_ebitda` | 3.0 or more, or top quartile, EBITDA over 0 | "Net debt of {v} EBITDA against a peer median of {m}." | "leverage top quartile" |
| `estimates_wide` | discount | `est_dispersion` | top quartile | "Analyst EPS estimates span {v} of the mean, wider than most peers (median {m})." | "wide estimate range" |
| `estimates_thin` | discount | `n_estimates` | FY1 estimates under 3 | "Only {n} analysts cover FY1 EPS." | "thin analyst coverage" |
| `growth_bottom` | discount | `revenue_growth` | bottom quartile | "Revenue growth of {v} is in the bottom quartile of peers (median {m})." | "revenue growth bottom quartile" |
| `margin_bottom` | discount | `operating_margin` | bottom quartile, commercial, `loss_making` not fired | "Operating margin of {v} is in the bottom quartile of peers (median {m})." | "operating margin bottom quartile" |

`short` (used in support sentences) is the `long` text reduced to its noun phrase, lower case,
without the final full stop, for example "revenue growth in the top quartile of peers (44.7 %
against a median of 6.0 %)". Each rule defines its own `short` beside its `long`. `provenance` is
`"M"` for `pipeline_value` and `"C"` otherwise: an M observation never enters `support`,
`supportShort` or `lookNext`, and is labelled "Model output" wherever it is listed.

`notAssessed` (always listed, muted): "Recurring revenue share: no comparable free data.",
"Reimbursement exposure: no comparable free measure. IRA Part D gross spending exists but is not
revenue at risk."

### 3.11 Conclusion banner and confidence

`conclusion(view) -> {state, headline, support, supportShort, token, label, labelShort,
confidence, bar, chips, lookNext, why, metric, value, median, premium, pct, n}`. `state`:
`"ok" | "low_confidence" | "too_few" | "no_multiple" | "no_peers" | "error"`.

Number rules in prose: multiples one decimal with `×` ("16.2×"); percentages one decimal with
`%` except premium, which is a whole percent; money `"$260.0bn"` for USD, `"EUR 228.5bn"` style
otherwise; ordinals "58th". `{metric}` is the prose label (`pe` "P/E", `ev_ebitda` "EV/EBITDA",
`ev_revenue` "EV/Revenue", `price_to_sales` "market cap to revenue", `price_to_book` "price to
book", `peg` "PEG", `mcap_to_cash` "market cap to cash"). `{period}` is the focal cell's own
period ("NTM", "FY2025", "LTM Jun-26", the balance sheet date for P/B and market cap to cash),
followed by ", peers mixed LTM and FY" when the column mixes periods. `{noun}` is
`setLabel().noun` (3.6). `{k}` counts peers with a value.

Headline (at most `MAX_HEADLINE_CHARS`; a test checks every fixture company):

| Case | Template |
|---|---|
| `ok`, not in line | "{T} trades at {v} {metric} ({period}), a {P}% {premium \| discount} to the median of {k} {noun}, {m}." |
| `ok`, in line (`isInLine`) | "{T} trades at {v} {metric} ({period}), in line with the median of {k} {noun}, {m} ({±P}%)." |
| `ok`, FCF yield | "{T}'s FCF yield of {v} ({period}) sits against a median of {m} for {k} {noun}: a {P}% {premium \| discount} on this measure." (in line: "…: in line on this measure ({±P}%).") |
| `low_confidence` | "{T} trades at {v} {metric} ({period}). Only {k} peers have a value, so no premium or discount is stated." |
| `too_few` | "{T} trades at {v} {metric} ({period}). {One peer has \| No peer has} a value, so there is no comparison." |
| `no_multiple` | "No valuation multiple has both a value for {T} and 2 or more peer values." |
| `no_peers` | "No peers are selected, so there is no comparison." |
| `error` | "The summary could not be computed." |

Example (illustrative; the numbers are from the 2026-09-28 book over the 14 other pharma names
with a meaningful P/E NTM, since GILD is n.m. under the sign-change rule of 4.2; the live default
set is capped at 15 by relevance and can differ): AZN at 16.22× against a focal-excluded median of
15.36× is +5.6 %, which rounds to 6, so the headline reads "AZN trades at 16.2× P/E (NTM), a 6%
premium to the median of 14 big pharma peers, 15.4×." The rounding rule keeps the token, the KPI
5 period line and the headline on the same whole percent.

Clinical example (book values): "CRSP trades at 2.2× market cap to cash (30 Jun 2026), a 7%
premium to the median of 17 clinical cell and gene peers, 2.1×."

Support (at most two sentences, built from non-M `observations`):

| Case | Template |
|---|---|
| premium, premium-side observations | "Alongside the premium, {T} has {d1}{ and {d2}}." Then, when a discount-side observation exists: "On the other side, it has {r1}." |
| discount, discount-side observations | "Alongside the discount, {T} has {r1}{ and {r2}}." Then, when a premium-side observation exists: "On the other side, it has {d1}." |
| tested association | Replaces the first sentence above only when `d1` (or `r1`) is on the scatter's current x column, the scatter has a trend with R² of at least 0.10, and the slope's sign puts the focal's side of the x median on the same side as the premium (or discount): "The {premium \| discount} is associated with {d1}: across these peers, {x label} and {metric} rise together (R² {r2})." ("fall together" for a negative slope). |
| premium or discount, no observation on its side | "No measure in this table sits in the direction of the {premium \| discount}. It may reflect factors outside the free data, such as deal expectations, litigation or pricing." |
| in line | "Measures furthest from peers: {o1}{; {o2}}." or, with no observation, "Its measures sit mostly within the peer interquartile range." |
| clinical or sub-scale, `ok` | "Enterprise value is {ev}{, and cash runway is {r} months on trailing burn}." then one observation sentence from the rows above when one exists. With EV null: "Enterprise value is not computed ({reason}){; cash runway is {r} months on trailing burn}." |
| `low_confidence` | "The {k} peer values run from {min} to {max}. A median of fewer than 5 is not a reliable reference." |
| `too_few` | "Widen the set to adjacent subsectors, or add peers with A." Action button: "Add adjacent-subsector peers" (adds pool C). |
| `no_multiple` | "{first candidate label}: {focal cell reason} Market cap is {mc}, the {pct} percentile of peers{; cash covers {c} of it}{; cash runway is {r} months on trailing burn}." |
| `no_peers` | "Add a peer with A or from the peer panel, or restore the system set." |
| `error` | "{message}. The table below is unaffected." |

`supportShort` (short mode, at most `MAX_SUPPORT_SHORT_CHARS`, one line): premium or discount
with observations "Alongside: {tag1}{; {tag2}}" (the second tag dropped when the line would pass
90 characters); tested association "Associated with {tag1} (R² {r2})"; none "No measure here
sits in its direction"; in line "Furthest from peers: {tag1}"; clinical or sub-scale "EV {ev}{;
runway {r} months}"; `low_confidence` "Only {k} peer values"; `too_few` "Too few peer values for a
comparison"; `no_multiple` "Market cap {mc}, {pct} percentile"; `no_peers` "No peers selected".

`token`: `{text, caption, dir}`, for example `{text: "+6%", caption: "premium to median", dir:
"up"}`, `{text: "−12%", caption: "discount to median", dir: "down"}`, `{text: "+3%", caption:
"in line with median", dir: null}`; `{text: "—", caption: "no premium stated"}` for the other
states. `dir` picks the `▲`/`▼` glyph only; the token is always `text` colour.

`label` (always shown): "System-generated summary from the table below. It states associations,
not causes." `labelShort`: "System-generated".

`lookNext -> {text, target: {kind: "cell" | "dotplot" | "scatter" | "peers", colId, ticker}}`,
at most `MAX_LOOK_NEXT_CHARS`, the first that applies:

1. The focal's primary cell carries a red flag, or an amber flag that costs confidence (the
   confidence table below): "Check {T}'s {metric} data: {flag chip}", target the cell.
2. The strongest non-M observation (either side): "{tag}", target the focal cell in its column.
3. An extreme outlier in the primary metric with outliers included: "{ticker}, an extreme
   {metric} value", target that point in the dot plot.
4. The scatter has a trend with R² under 0.10: "Valuation against growth: weak trend", target
   the scatter.
5. Otherwise: "The peer set: {n} peers", target the peer panel.

A data problem on the focal's own primary value comes first because it can change the headline
itself; the strongest observation is the usual answer.

`chips`: "Weak peer set" (flag) when the set is weak (3.6) or `defaultPeers.warning` is set;
"Mixed business models" (flag) when `mixedModels` is not null; "Low confidence" (flag) in state
`low_confidence`. Tooltips in section 8.

`bar`: `"down"` when `state === "error"`; `"flag"` when `confidence.level === "low"`, or
`state` is `low_confidence` or `too_few`, or the "Weak peer set" chip is on; else `"active"`.

`confidence(view) -> {level: "high" | "medium" | "low" | null, score, reasons[]}`. Null level (the
chip is hidden and the state chip speaks instead) for `too_few`, `no_multiple`, `no_peers` and
`error`.

| Input | Points | Reason text |
|---|---|---|
| ok peer values for the primary metric | 8 or more: +2; 5 to 7: +1; under 5: state `low_confidence` | "{k} peers have a value" |
| appropriate peers (3.6) | under 5 included: −1 | "Only {a} of {n} peers score 40 or more on relevance" |
| median relevance of the included peers | under `MIN_MEDIAN_RELEVANCE`: −1 | "The median peer relevance is {r} of 100" |
| mixed business models | −1 | "Peers mix {focal type} and {other type} companies" |
| mixed standards, only when `usesFiledFigures(primary, basis)` | −1 | "Peers mix IFRS and US GAAP filers, and {metric} uses filed figures" |
| primary column mixes periods (LTM with FY fallbacks) | −1 | "{k} peer values are fiscal-year figures in an LTM column" |
| more than `MAX_DERIVED_SHARE` of the peer values carry `derived_operating_income` | −1 | "{k} of {n} peer EBITDA figures are derived and may be overstated" |
| the focal's primary cell carries an amber flag; `estimate_range_wide` counts only when FY1 estimates are under `WIDE_RANGE_MIN_ESTIMATES` or dispersion is over `WIDE_RANGE_MAX` | −1 | the flag's text |
| peer dispersion: `iqr / median` over `MAX_DISPERSION_RATIO` | −1 | "Peer values are widely spread (interquartile range {x}% of the median)" |
| an extreme outlier in the primary metric, outliers included | −1 | "{k} extreme outlier(s) in the statistics" |

Level: high at 2 or more, medium at 1, low at 0 or below; forced low in `low_confidence`. Shown
as "Confidence: high" with a three-segment bar (filled segments = 3, 2, 1). Calibration on the
2026-09-28 book: AZN on P/E NTM has 14 peer values (+2), no standards penalty (street basis),
estimate range 0.55 on 6 estimates (not counted), IQR 54 % of the median (not counted), no
extreme outlier: score 2, high. A pharma focal on EV/EBITDA meets the standards and derived
penalties and scores lower, as it should.

`why` (the "Why?" popover, 1.5): `{groups: [{title, items: [{text, colId, provenance}]}]}` with
groups "Primary metric" (`reasonText`), "Confidence" (the reasons), "Observations" (every
observation, M ones labelled "Model output"), "Outliers" ("Without outliers the median is {m'}
and the {premium | discount} is {p'}%." when the outlier-excluded median differs by more than
5 %), and "Bases" (the mixed-standards and street-against-reported lines of section 8, when they
apply). When an item's column is not in the current preset, following its link runs
`SHOW_COLUMN` (3.15), which switches to a Custom copy with the column added, and the live region
says "Added {column} to a custom column set."

`lintCopy(text, kind) -> string[]`, `kind` `"sentence"` or `"label"`:

- Both kinds: `"em dash"` for U+2014 anywhere except a string that is exactly the null glyph;
  `"banned: {w}"` for each word of `BANNED_WORDS` (case-insensitive, whole word).
- `"label"` only (section titles, group and column header labels, KPI labels, chip texts, button
  and menu labels, `COMMANDS` labels, state titles): `"not sentence case"` when a word after the
  first starts with a capital and is not allowed. A word is allowed when it, or each part of it
  split on `/` and `-`, is on the allow list or matches `/^(FY\d{0,4}|Q[1-4]|\d+-[A-Z]|[A-Z])$/`
  (FY1, Q2, 20-F, 10-K, 6-K, one-letter keys such as A, R, U). Allow list: `["US", "GAAP",
  "IFRS", "EPS", "EV", "EBITDA", "FCF", "NTM", "LTM", "R&D", "IPR&D", "ECB", "USD", "EUR", "GBP",
  "CHF", "DKK", "IRA", "LOE", "OTC", "ADR", "CSV", "TSV", "P/E", "P/B", "PEG", "ROIC", "SG&A",
  "XLV", "S&P", "CAGR", "rNPV", "R²", "Phase", "Part", "Blume", "Nasdaq", "NYSE", "London",
  "FDA", "Forecast", "Financials", "Comps", "Pipelines", "Indications", "Valuation", "AZN"]` plus
  every ticker and company name in the payload.
- `"sentence"` strings (headlines, support, tooltips, state details, `NA_TEXT`, observation
  text) get the first two checks only: sentences start with capitals by design.
- Verbatim guidance notes and filing titles are quotations of the source, shown as
  "{company} guidance, {date}: “{text}”" with the text cut at the last word boundary before 240
  characters and "…" appended. They are never linted and never generated.

### 3.12 Copy tables

`NA_TEXT` (null reason to tooltip): `no_free_data` "No free data source carries this.";
`not_filed` "Not in the filings on file."; `not_tagged` "The filer does not tag this line.";
`no_debt_line` "No debt line filed within a year and no stated nil, so enterprise value is not
computed."; `no_shares` "No share count on file."; `share_count_scale` "The weighted diluted
share count on file is out of scale with the cover count (it looks filed in thousands), so it is
not used."; `no_consensus` "No consensus estimates on file."; `no_consensus_otc` "No consensus
on the free feed for this OTC listing."; `no_fy2_consensus` "No FY2 consensus, so a
twelve-month forward figure is not built."; `no_ltm_20f` "No LTM figure: 20-F filers' 6-K
interims carry no XBRL, and workbook filers publish no interims here."; `no_ltm` "No interim
filing after the fiscal year end."; `no_guidance` "No numeric guidance for this year.";
`guidance_in_words` "Guidance is stated in words, not a number."; `guidance_product_scope`
"Guidance covers product revenue only, not total revenue."; `guidance_cer` "Guidance is at
constant currency, so it is not set against reported revenue."; `non_positive_base` "The base is
zero or negative, so growth is not meaningful."; `one_year_only` "Only one fiscal year on file,
so no growth."; `no_tax_rate` "Pre-tax income is zero, negative or not filed, so there is no tax
rate and no ROIC."; `not_modelled` "No forecast model for this company."; `model_not_computed`
"Model values are still being computed. Reload in a minute."; `model_failed` "The model could
not value this company."; `no_prices` "No price history on file."; `insufficient_history` "Not
enough price history."; `not_burning` "Not burning cash on trailing operating cash flow.";
`no_cash_flow` "No operating cash flow on file, so burn and runway are not computed.";
`no_cash` "No cash or investments on file."; `no_product_revenue` "No product revenue on file.";
`no_trials` "No mapped trials."; `no_rate` "No ECB rate for this currency."; `none_on_file` "No
claims outside cash and debt on file."; `standard_not_recorded` "The accounting standard is not
recorded for this 20-F filer yet. It fills on the next financials refresh.";
`domicile_unknown` "This 20-F filer is stored with a US country code, so its region is not
known."; `calc_failed` "Calculation failed for this company."

`flagText(flag) -> {chip, text}` for every code in 2.5 and every client flag of 3.4; the copy is
in section 8.

### 3.13 Formatting

| Function | Output |
|---|---|
| `fmtNumber(v, decimals, {signed})` | Thousands separator `,`, fixed decimals, true minus U+2212, `+` only when `signed` and v over 0. Null: `"—"`. |
| `fmtCell(cell, col)` | Applies the column format (section 4.3) and returns `cell.text`. |
| `fmtMoneyProse(usdM, cur, fx)` | `"$260.0bn"`, `"$5.2bn"`, `"$950m"` under 1bn; non-USD `"EUR 228.5bn"`. |
| `fmtMultipleProse(v)` | `"16.2×"` |
| `fmtPctProse(v, d = 1)` | `"8.6%"` from 0.086 |
| `fmtDate(iso)` | `"28 Sep 2026"`; `fmtDateShort` `"28 Sep"` |
| `ordinal(n)` | `"1st"`, `"2nd"`, `"3rd"`, `"11th"`, `"58th"` |
| `compareCells(a, b, dir)` | Sort comparator: ok values by `v`, then `nm`, then `nb`, then `na`, then `err`, always last whatever `dir`; ties by ticker. |

### 3.14 Commands and keys

> Revision 3: commands added, changed and removed in 12.10.

`COMMANDS: {id, label, key, group, when, singleKey}[]` is the single list behind the help
overlay, the command palette and the key handler (section 7). `singleKey` is true for a binding
with no modifier outside a focused grid or chart.

`KEYMAP` maps a normalised key string to a command id. `normKey(event, isMac) -> string`:

- Prefix `mod+` when `metaKey` (macOS) or `ctrlKey` (elsewhere) is down; `alt+` when `altKey` is
  down.
- A printable key is taken from `event.key`. For a letter, the lower-case letter, prefixed
  `shift+` when `shiftKey` is down (`"x"`, `"shift+x"`). For any other printable character the
  character itself **without** a `shift+` prefix, because `event.key` already carries the
  shifted character on every layout: `"?"`, `"+"`, `"-"`, `"/"`, `"1"` to `"7"`.
- Named keys lower case with the same prefixes: `"enter"`, `"shift+enter"`, `"esc"` (from
  `"Escape"`), `"delete"`, `"up"`, `"down"`, `"left"`, `"right"` (from `"ArrowUp"` and so on),
  `"home"`, `"end"`, `"pageup"`, `"pagedown"`, `"tab"`.

`handleKey(state, keyString, focusZone) -> command id | null` returns null for a `singleKey`
command while `state.singleKeys` is false. `mod+k`, `esc`, `mod+z` and the keys a focused grid or
chart consumes (arrows, `home`, `end`, `pageup`, `pagedown`, `enter`, `shift+enter`, and `j`, `k`,
`o`, `s`, `x` inside a focused grid) stay active whatever the setting. That meets WCAG 2.1.4: a
single-key shortcut can be turned off, and the rest are active only while their component has
focus.

`matchCommands(query, commands, extra)`: fuzzy subsequence match, score prefix 3, word start 2,
other subsequence 1, ties by list order. Hint text for a single-key command is shown in the
palette and the tooltips only while `singleKeys` is true.

### 3.15 State, reducer and view

> Revision 3: additions and removals in 12.10. `deriveView` takes a third argument.

```js
export function defaultState(payload, {focal, engine}, persisted, session) -> State
export function migrateState(raw) -> PersistedState      // unknown version: default; drops unknown column ids, tickers and non-premium overrides
export function reduce(state, action, payload) -> State  // pure; returns the same object when nothing changed
export function persistable(state) -> {local: object, session: object}
export function deriveView(payload, state) -> View       // pure; each section try/catch into a section error state
export function toCSV(view) -> string
export function toTSV(view) -> string
export function summaryText(view) -> string              // conclusion, KPIs and bridge as plain text
```

`State`:

```ts
{
  version: 1,
  focal: string, engine: string,
  basis: "NTM" | "FY1" | "FY2" | "FY0" | "LTM",
  currency: "USD" | "EUR" | "GBP" | "CHF" | "DKK" | "REPORTED",
  earnings: "reported" | "adjusted",       // labels "GAAP/IFRS" and "Ex amort. and IPR&D"
  preset: "core" | "growth" | "balance" | "pharma" | "biotech" | "cellgene" | "custom",
  customColumns: string[], hidden: string[], pinned: string[], widths: {[colId]: number},
  sort: {colId: string, dir: "asc" | "desc"} | null,
  filters: {colId: string, op: ">=" | "<=" | "has" | "text", value: number | string}[],
  peerEdits: {[focal]: {added: string[], removed: string[], notes: {[ticker]: string}}},
  activeSet: "system" | `saved:${string}`,
  savedSets: {[name]: {tickers: string[], notes: {[ticker]: string}, created: string, engine: string}},
  subgroups: {[focal]: {[name]: string[]}},
  statsGroup: "all" | string,
  excluded: string[],                      // session only, per focal
  outliers: "include" | "exclude",
  primaryOverride: {[engine]: string | null},   // PREMIUM_METRICS only
  dotMetric: {[engine]: string | null},         // null follows the primary metric
  scatter: {x: string | null, y: string | null, size: "market_cap" | "ev" | "none",
            trend: boolean, colorBy: "none" | "stage", logY: boolean},
  cfMode: "off" | "premium" | "percentile" | "trend" | "quality" | "outliers",
  density: "compact" | "default" | "comfortable", textSize: 13 | 14 | 15,
  summaryRows: boolean, summaryExpanded: {[layout]: boolean},
  chartStrip: {[layout]: "open" | "collapsed"},
  layouts: {[name]: {preset, customColumns, hidden, pinned, widths, cfMode, density,
                     textSize, summaryRows, created: string}},
  singleKeys: boolean,                     // default true
  bridge: {[focal]: BridgeInputs},
  notes: {[ticker]: {text: string, updated: string}},   // analyst notes, side panel
  cohorts: string[],                        // up to 3 cohort ids for comparison
  ui: {detail: string | null, why: boolean, method: string | null,  // method: anchor id or null
       focus: {row: string, col: string} | null, expanded: string[],
       narrowTab: "position" | "scatter", laptopTab: "position" | "scatter",
       lowerTab: "bridge" | "obs" | "peers" | "notes",
       overlay: null | "palette" | "help" | "selector" | "peerpicker" | "columnfinder",
       undo: {label: string, before: object, at: number} | null}
}
```

Local (per `STORAGE_KEY`): everything except `focal`, `excluded` and `ui`; table settings and
`dotMetric` are kept per engine under `byEngine[engine]`; `layouts`, `savedSets`, `notes` and
`singleKeys` are global. Session (`SESSION_KEY`): `excluded` per focal, `ui.detail`,
`ui.expanded`, scroll offsets.

Actions (`{type, ...}`): `SET_FOCAL {ticker}`, `SET_BASIS {basis}`, `CYCLE_BASIS {dir}`,
`SET_CURRENCY {currency}`, `SET_EARNINGS {earnings}`, `SET_PRESET {preset}`,
`SET_CUSTOM_COLUMNS {ids}`, `HIDE_COLUMN {colId}`, `SHOW_COLUMN {colId}` (when the column is not
in the current preset, switches to a Custom copy of it with the column appended),
`PIN_COLUMN {colId}` (refused with a reason past the frozen budget of 4.1), `UNPIN_COLUMN {colId}`,
`MOVE_COLUMN {colId, dir}`, `RESIZE_COLUMN {colId, width}`, `RESET_LAYOUT`, `SORT {colId}` (cycles
desc, asc, none), `SET_FILTER {filter}`, `REMOVE_FILTER {colId}`, `CLEAR_FILTERS`,
`ADD_PEER {ticker}`, `ADD_POOL_C`, `REMOVE_PEER {ticker}`, `TOGGLE_EXCLUDE {ticker}`,
`SET_OUTLIERS {mode}`, `SET_PRIMARY {colId | null}`, `SET_DOT_METRIC {colId | null}`,
`SET_SCATTER {x?, y?, size?, trend?, colorBy?, logY?}`, `SET_CF_MODE {mode}`, `CYCLE_DENSITY`,
`SET_TEXT_SIZE {delta}`, `TOGGLE_SUMMARY_ROWS`, `TOGGLE_SUMMARY_EXPANDED {layout}`,
`SET_CHART_STRIP {layout, value}`, `SAVE_LAYOUT {name, now}`, `LOAD_LAYOUT {name}`,
`DELETE_LAYOUT {name}`, `SAVE_SET {name, now}`, `LOAD_SET {name}`, `DELETE_SET {name}`,
`RESTORE_SYSTEM`, `SET_SUBGROUP {name, tickers}`, `DELETE_SUBGROUP {name}`,
`SET_STATS_GROUP {group}`, `SET_COHORTS {ids}`, `SET_PEER_NOTE {ticker, text, now}`,
`SET_NOTE {ticker, text, now}`, `SET_BRIDGE {patch}`, `RESET_BRIDGE`, `SET_SINGLE_KEYS {on}`,
`OPEN_DETAIL {ticker}`, `CLOSE_DETAIL`, `FOCUS_CELL {row, col}`, `TOGGLE_ROW_EXPANDED {ticker}`,
`TOGGLE_WHY`, `OPEN_METHOD {anchor}`, `CLOSE_METHOD`, `SET_NARROW_TAB {tab}`,
`SET_LAPTOP_TAB {tab}`, `SET_LOWER_TAB {tab}`, `OPEN_OVERLAY {overlay}`, `CLOSE_OVERLAY`,
`UNDO`, `EXPIRE_UNDO {now}`.

Undo: `REMOVE_PEER`, `DELETE_SET`, `RESTORE_SYSTEM`, `RESET_LAYOUT`, `DELETE_LAYOUT`,
`DELETE_SUBGROUP` and `CLEAR_FILTERS` store the persisted slice they change in `ui.undo` with a
label ("Removed PFE from peers", "Deleted peer set 'Obesity'", "Restored system peers", "Reset
the column layout", "Deleted layout 'Mine'", "Deleted subgroup 'US large'", "Cleared 3
filters"). `UNDO` restores it; `EXPIRE_UNDO` clears it once `now − at ≥ UNDO_MS`. One level only:
a second destructive action replaces the first record.

`View` (what renderers consume; renderers never read the payload directly except
`payload.companies[i].detail` through `view.detail`):

```ts
{
  schema: 1, error: StateMsg | null,
  focal: {ticker, name, type, preRevenue, record},
  ctx: {basis, basisLabel, currency, currencyLabel, dataState: "Standardised" | "As reported",
        earnings, earningsLabel, fxText, basisText},
  header: {ticker, name, listingText, subsectorText, stageText, typeChip: Chip | null,
           reportingText, reportingShort, peerSet: {full, short}, dataAsOf: {text, short, tone,
           lines: string[]}, live: boolean},
  conclusion: (3.11),
  kpis: Kpi[6],        // Kpi = {id, label, value, unit, period, provenance: "sourced" | "calc." | "model",
                       //        compare, compareDir, tooltip, flag, strip: PositionStrip | null}
  primary: {colId, label, basisLabel, state, reasonText,
            candidates: {colId, label, enabled, premium, reason}[]},
  scope: {counts, items: {id, kind: "exclusion" | "filter" | "group" | "outliers" | "warning",
          text, tooltip, removable, priority}[]},
  table: {columns: ColView[], groups: {id, label, span}[], rows: RowView[],
          summary: {id: "mean" | "median" | "p25" | "p75" | "n", label, cells: {[colId]: SummaryCell}}[],
          summaryVisible: string[], sort, cfMode, density, textSize, preset, hiddenCount,
          frozenWidth, caption},
  dotplot: {colId, label, unit, isPrimary, premiumEligible, scale: "linear" | "log",
            domain: [number, number], lanes: {id, label, n, median, p25, p75, points: DotPoint[]}[],
            notPlotted: {nm, na}, target: {lo, hi} | null, description, disabledReason},
  scatter: (3.8) & {x, y, size, colorBy, logY, regions: {id, label, x, y}[]},
  bridge: Bridge, observations: (3.10),
  peers: {rows: PeerRow[], candidates: PeerRow[], savedSets, subgroups, cohorts: CohortRow[],
          mixed: StateMsg | null, weak: StateMsg | null},
  method: {sections: {id, title, body}[]},
  detail: DetailView | null,
  states: StateMsg[], lineage: {...}, undo: {label} | null
}
PositionStrip = {domain: [number, number], p25, median, p75, focal, clamped: "lo" | "hi" | null, description}
ColView  = {id, group, label, unitText, basisChip: {text, mixed: boolean} | null,
            provenance: "S" | "C" | "M", provenanceWord: "sourced" | "calc." | "model",
            tooltip, width, frozen: boolean, autoPinned: boolean, align: "left" | "right",
            sortDir: "asc" | "desc" | null, filter: object | null}
RowView  = {ticker, name, isFocal, excluded, expanded, outlier: null | "mild" | "extreme",
            source: "system" | "analyst" | "saved", pool: "A" | "B" | "C" | null, reason,
            relevance: {score, level, components}, note,
            cells: {[colId]: Cell & {pct, vsMedian, cf}}, error}
SummaryCell = {v, text, n, lowN: boolean, reason}
StateMsg = {id, severity: "info" | "amber" | "red", where: string[], title, detail,
            action: {label, command} | null}
Chip     = {id, text, tone: "neutral" | "active" | "flag" | "down" | "up" | "clinical", tooltip}
```

`caption` (table summary for screen readers): "Comparable companies for {T}: {n} peers, {k} in
statistics, preset {preset}, basis {basis}. Summary rows follow the company rows."

CSV (`toCSV`): first line `"# Comps for {T}, {set full}, basis {basis}, {currency}, generated
{ts}"`; then a header row `label (unit, basis, provenance)` per visible column; then the focal
row and peer rows in view order; a blank line; the summary rows; a blank line; `"# Prices {date};
FX {fx text}; {basis text}"`. Nulls are empty, n.m. is `n.m.`, numbers unformatted at full
precision. Filename `comps_{T}_{basis}_{YYYYMMDD}.csv`. TSV is the same without the comment
lines.

---

## 4. The table

### 4.1 Structure

> Revision 3: the `!` after a ticker follows `tickerFlags`, not every amber flag on the row (12.7).

A native `<table role="grid">` with `border-collapse: separate`, one sticky group-header row,
one sticky column-header row, the focal row pinned as the first body row (sticky under the
header, can be unpinned in the toolbar), peer rows, and a sticky `<tfoot>` holding the summary
rows. Frozen columns use sticky `left` offsets computed from widths. At most 71 rows, so no
virtualisation. The table re-renders `<tbody>` and `<tfoot>` in place and restores `scrollTop`,
`scrollLeft` and the active cell. The table box's sizing and scroll chaining are in 1.2.

Frozen, left to right (always, in every preset):

| id | Header | Width (wide / laptop / narrow) | Content |
|---|---|---|---|
| `exp` | (none; aria "Expand row") | 20 / 20 / 20 | a button with `›` (collapsed) or `⌄` (expanded), `aria-expanded`; `shift+Enter` on a focused row toggles it. Empty for the focal row. |
| `incl` | (none; aria "In statistics") | 28 / 28 / 24 | `●` included, `○` excluded (hatched cell), `◇` outlier excluded, `✕` (red) calculation failed, empty for the focal row. Click toggles exclusion. |
| `rel` | "Fit" | 44 / 44 / 36 | three 3 by 10 px bars, filled for level (high 3, medium 2, low 1), plus `+` in ACTIVE when the analyst added the peer. Tooltip: "Relevance {score} of 100. {reason}." and the six components. Empty for the focal row. |
| `company` | "Company" | 176 / 148 / 112 | name, ellipsis |
| `ticker` | "Ticker" | 64 / 60 / 56 | mono 600; a small amber `!` after the ticker when the row carries an amber flag (tooltip lists them) |
| primary column | its own header | at `laptop` and `narrow` only: auto-pinned, 84 / 80 | the primary metric column (3.5) follows the ticker, tagged "Primary" in its unit line; it moves when the primary changes. At `wide` and `ultrawide` it sits in its preset position, and is inserted after the ticker (unfrozen) when the preset lacks it. |

Frozen width budget: the base block is always frozen; manual pins may not take the frozen block
past `FROZEN_MAX_SHARE` (40 %) of the table box's width. Base blocks: 332 px at `wide` and `ultrawide`, 384 px at `laptop` (with the
auto-pinned primary), 328 px at `narrow`. Manual pins (header menu "Pin left") follow in pin order,
at most two at `wide` and `ultrawide`, one at `laptop`, none at `narrow`, and only within the
budget; a pin past it is refused with "Pinned columns would cover more than 40% of the table.
Unpin one first."

Row expansion: an expanded row adds a sub-row directly below it (the cell spans every column;
its content is sticky-left and as wide as the visible table box), 88 px, `panel` background.
Content: the relevance score and the six components as labelled 60 px bars with percents (a
dropped component reads "not scored: {reason}"), the source and inclusion reason, the pool (A, B
or C) when it came from the system set, the analyst's inclusion note as an inline text input
(saved on blur, "Saved in this browser only"), and buttons "Open details" and "Exclude from
statistics" or "Include". Expanded rows persist for the session (`ui.expanded`).

Group header labels are stored and shown in sentence case, 11 px 600 `muted`: "Company",
"Valuation", "Growth", "Profitability", "Balance sheet and risk", "Healthcare".

### 4.2 Column catalogue

Columns: `id` · header label and unit · format (4.3) · bases (default first; `-` means spot or
latest, no period) · direction (`+` higher is favourable, `−` lower is favourable, `n` neutral)
· provenance (S sourced, C calculated, M model) · formula and n.m. rule · tooltip definition.
The header unit line uses the display currency where it says `{cur}`. Tooltips are complete
definitions and follow house style.

**Company**

| id | Header | Fmt | Bases | Dir | Prov | Formula, n.m. | Tooltip |
|---|---|---|---|---|---|---|---|
| `country` | Country | text | - | n | S | `country` | "Country code as stored in the company record. For some foreign companies listed on Nasdaq it records the US listing, not the domicile." |
| `subsector` | Subsector | chip | - | n | C | engine label, stage chip (clinical in purple) | "Big pharma, Biotech or Cell and gene, from the terminal's engine rule, with commercial or clinical stage from inventory and cost of sales." |
| `currency` | Filed in | text | - | n | S | `row_currency`, `⇄` when converted | "The currency of the filed accounts. Amounts are converted at the ECB reference rate; ratios use the filed figures." |
| `price` | Price, USD | price2 | - | n | S | `market.price` | "Last close of the US-listed line, unadjusted. For foreign companies this is the ADR or US line, not the home listing." |
| `change_1d` | 1 day, % | pct1 signed | - | n | C | `change_1d` | "Change between the last two closes. Unadjusted, so an ex-dividend day reads as a fall." |
| `ttm_price_change` | 12 months, % | pct1 signed | - | n | C | `ttm_change` | "Share price change over the trailing twelve months." |
| `spark_90d` | 90 days | spark | - | n | S | `spark_90d` | "Daily closes over the last 90 days, ending on the last close." |
| `market_cap` | Market cap, {cur} bn | money1 | - | n | C | `market_cap_usd_m` | "Price times shares. Shares outstanding from the latest cover page when it is under 400 days old; otherwise FY weighted diluted shares, per US-listed share. The cell tooltip names the route." |
| `ev` | EV, {cur} bn | money1 | - | n | C | `ev_usd_m`; na `no_debt_line` | "Enterprise value: market cap plus net debt at the latest balance sheet. Excludes leases, pensions, minorities and other claims, which the bridge can apply separately." |
| `revenue` | Revenue, {cur} bn | money1 | FY0, LTM | n | S | FY0 or LTM `revenue_usd_m` | "Revenue for the last fiscal year, or the last twelve months where interim filings allow, converted at the ECB reference rate." |

**Valuation**

| id | Header | Fmt | Bases | Dir | Prov | Formula, n.m. | Tooltip |
|---|---|---|---|---|---|---|---|
| `ev_revenue` | EV/Revenue, × | mult1 | LTM, FY0, FY1 (G) | n | C | EV / revenue on the basis; FY1 uses guided revenue, only where `revenue_guided_fy1` is computable (2.3), else n.m. with `NA_TEXT.guidance_product_scope` or `.guidance_cer`. n.m. when revenue under 100 (USD m), EV at or below 0, or result over 100. | "Enterprise value over revenue. LTM where interim filings allow, else the last fiscal year; FY1 uses the company's own total revenue guidance at reported rates." |
| `price_to_sales` | Market cap / revenue, × | mult1 | LTM, FY0 | n | C | market cap / revenue, LTM with per-cell FY0 fallback. n.m. when revenue under 100 (USD m) or result over 100. | "Market cap over revenue. Needs no debt figure, so it covers companies whose enterprise value cannot be computed." |
| `ev_ebitda` | EV/EBITDA, × | mult1 | FY0 | n | C | EV / EBITDA FY0 (adjusted adds tagged IPR&D, except where operating income is derived). n.m. when EBITDA or EV is at or below 0. | "Enterprise value over EBITDA for the last fiscal year. EBITDA is operating income plus depreciation and amortisation as filed. Under IFRS 16 lease costs sit below EBITDA, which lifts IFRS filers' EBITDA against US GAAP peers. No free forward EBITDA exists." |
| `pe` | P/E, × | mult1 | NTM, FY1, FY2 (E), FY0, LTM (A) | n | C | Forward: price / EPS (street). NTM is n.m. when FY1 or FY2 EPS is at or below 0 (`eps_sign_change` or both negative); FY1 and FY2 are n.m. when their EPS is at or below 0. FY0 and LTM: market cap / net income (GAAP or IFRS, attributable where stored), n.m. at or below 0. No upper cap: very high values are handled by the outlier fences and the outlier mode. | "Price over earnings per share. Forward bases use Nasdaq street consensus, which is adjusted. FY0 and LTM use reported net income under GAAP or IFRS; IFRS profit can include minority interests where the attributable figure is not stored." |
| `fcf_yield` | FCF yield, % | pct1 | FY0 | n | C | FCF / market cap. n.m. when FCF is below 0. | "Free cash flow (operating cash flow less capital expenditure) for the last fiscal year over market cap. Under IFRS 16 lease payments sit in financing cash flow, which lifts IFRS filers' free cash flow against US GAAP peers." |
| `price_to_book` | P/B, × | mult1 | - | n | C | market cap / equity. n.m. when equity is at or below 0. | "Market cap over shareholders' equity at the latest balance sheet. IFRS equity can include minority interests." |
| `peg` | PEG, × | mult2 | NTM | n | C | P/E NTM / (street EPS CAGR FY1 to FY3 × 100). n.m. when either is at or below 0, or FY1 EPS is under 0.10. Carries `thin_estimates` for FY3. | "NTM P/E over the street EPS growth rate from FY1 to FY3, in percent. Both on the street basis. FY3 often rests on one to three estimates." |
| `mcap_to_cash` | Market cap / cash, × | mult1 | - | n | C | market cap / `cash_usd_m`; na when cash is null; n.m. when cash is 0. | "Market cap over cash, short-term and long-term investments at the latest balance sheet. Under 1× the market values the company below its cash." |
| `pt_upside` | Street target, % | pct1 signed | - | n | S | target / price − 1 | "Upside to the 12-month consensus price target from Nasdaq, per US-listed share." |
| `ev_per_late_trial` | EV per late trial, {cur} m | money0m | - | n | C | EV / `late_trials`. n.m. when trials are 0 or EV is at or below 0. | "Enterprise value per lead-sponsored Phase 3 or Phase 2/3 trial." |
| `pipeline_to_ev` | Pipeline / EV, % | pct1 | - | + | M | `pipeline_rnpv_usd_m` / EV. n.m. when EV is at or below 0. | "Risk-adjusted NPV of the modelled pipeline over enterprise value. Model output, for the 20 modelled companies." |

**Growth** (every column: n.m. when `abs(growth)` is over `MAX_ABS_GROWTH`, read from the bases
the backend sends)

| id | Header | Fmt | Bases | Dir | Prov | Formula, n.m. | Tooltip |
|---|---|---|---|---|---|---|---|
| `revenue_growth` | Revenue growth, % | pct1 signed | FY0, FY1 (G) | + | C | `growth.revenue_fy` or `revenue_guided_fy1`. n.m. when either year's revenue is under 10 (USD m). FY1 guided cells carry `guidance_fx_unstated` when the guide names no currency basis. | "Revenue growth over the prior fiscal year in the filing currency, or the company's guided total revenue growth for FY1 at reported rates." |
| `revenue_cagr3` | Revenue CAGR 3y, % | pct1 signed | FY0 | + | C | `revenue_cagr3`. n.m. when revenue at either end (FY0 or FY0 less three years) is under 10 (USD m). | "Compound annual revenue growth over three fiscal years to FY0, in the filing currency." |
| `ebitda_growth` | EBITDA growth, % | pct1 signed | FY0 | + | C | `ebitda_fy` or `ebitda_fy_adjusted`. n.m. when the prior year is at or below 0 or under 10 (USD m) in absolute terms. | "EBITDA growth over the prior fiscal year. Not meaningful when the prior year was small, zero or negative." |
| `eps_growth` | EPS growth, % | pct1 signed | NTM, FY1, FY2 (E), FY0 (A) | + | C | forward: `eps_street_fy2`; FY0: `eps_fy_gaap`. n.m. when the base EPS is at or below 0 or under 0.10 in absolute terms. Forward cells carry `thin_estimates` for FY2. | "Forward: street EPS FY2 over FY1. FY0: reported diluted EPS over the prior year. The two bases are never mixed in one figure." |
| `eps_cagr` | EPS CAGR FY1 to FY3, % | pct1 signed | NTM | + | C | `eps_street_cagr`. n.m. when FY1 EPS is under 0.10. Carries `thin_estimates` for FY3. | "Compound annual growth of street EPS from FY1 to FY3." |

**Profitability**

| id | Header | Fmt | Bases | Dir | Prov | Formula, n.m. | Tooltip |
|---|---|---|---|---|---|---|---|
| `gross_margin` | Gross margin, % | pct1 | FY0 | + | C | gross profit / revenue | "Gross profit over revenue, last fiscal year. Gross profit as tagged, or revenue less cost of sales." |
| `ebitda_margin` | EBITDA margin, % | pct1 | FY0 | + | C | EBITDA / revenue | "EBITDA over revenue, last fiscal year." |
| `operating_margin` | Operating margin, % | pct1 | FY0 | + | C | operating income / revenue; the "Ex amort. and IPR&D" basis adds tagged amortisation and IPR&D, except where operating income is derived | "Operating income over revenue, last fiscal year. The ex amortisation and IPR&D basis adds back those tagged lines, except where operating income is derived and never subtracted them." |
| `net_margin` | Net margin, % | pct1 | FY0 | + | C | net income / revenue | "Net income over revenue, last fiscal year, as filed." |
| `roic` | ROIC, % | pct1 | FY0 | + | C | operating income × (1 − tax rate) / (equity + debt − cash). n.m. when invested capital is at or below 0; na `no_tax_rate` when there is no tax rate. | "Operating income after tax at the effective rate (clamped 0 to 50 %) over equity plus debt less cash." |
| `rd_pct` | R&D / revenue, % | pct1 | FY0 | n | C | R&D / revenue (the ex IPR&D basis excludes acquired IPR&D) | "Research and development expense over revenue, last fiscal year." |

Margins, ROIC and R&D share are n.m. when revenue is under 100 (USD m) or the margin is below
−100 %.

**Balance sheet and risk**

| id | Header | Fmt | Bases | Dir | Prov | Formula, n.m. | Tooltip |
|---|---|---|---|---|---|---|---|
| `net_debt` | Net debt, {cur} bn | money1 signed | - | n | C | `net_debt_usd_m` (negative is net cash) | "Debt less cash and investments at the latest balance sheet. Negative means net cash." |
| `net_debt_ebitda` | Net debt / EBITDA, × | mult1 signed | FY0 | − | C | n.m. when EBITDA is at or below 0 | "Net debt over last fiscal year EBITDA. Negative means net cash." |
| `cash_to_mcap` | Cash / market cap, % | pct1 | - | n | C | `cash_usd_m` / market cap | "Cash, short-term and long-term investments at the latest balance sheet over market cap." |
| `runway_months` | Cash runway, months | int | - | + | C | `runway_months`; `nb` "no burn" only for `not_burning`; `—` with its reason for `no_cash_flow` and `no_cash` | "Cash and investments plus raises since the balance sheet, over trailing twelve-month operating cash burn." |
| `beta` | Beta | num2 | - | n | C | `beta` | "Five-year weekly beta against the S&P 500, Blume-adjusted." |
| `vol_1y` | Volatility 1y, % | pct0 | - | n | C | `vol_1y` | "Annualised standard deviation of daily log returns over one year." |
| `est_dispersion` | Estimate range, % of mean | pct0 | FY1 | − | C | `est_dispersion`; n.m. when abs(mean) is under 0.10 | "High less low FY1 EPS estimate over the mean. The range may mix GAAP and adjusted estimates." |
| `n_estimates` | Estimates, count | int | FY1 | + | S | `periods.FY1.eps_n` | "Number of analysts in the FY1 EPS consensus." |

**Healthcare**

| id | Header | Fmt | Bases | Dir | Prov | Formula, n.m. | Tooltip |
|---|---|---|---|---|---|---|---|
| `stage` | Stage | chip | - | n | C | Commercial, or Clinical (purple) | "Commercial when the company carries inventory and cost of sales, otherwise clinical." |
| `lead_phase` | Lead phase | chip | - | n | C | `lead_phase` (clinical tone unless Marketed) | "Marketed if any asset is marketed, otherwise the furthest trial phase." |
| `major_products` | Products over $1bn, count | int | FY0 | + | C | `major_products` | "Products with at least USD 1bn of revenue in the last fiscal year. Can include non-product lines a company reports beside products." |
| `loe_share_5y` | Losing exclusivity 5y, % | pct1 | - | − | C | `loe_share_5y` | "Share of tagged product revenue losing US exclusivity within five years." |
| `loe_unpriced_5y` | Unpriced losses 5y, count | int | - | − | C | `loe_unpriced_5y` | "Products losing exclusivity within five years whose revenue is not on file, so the share beside it cannot count them." |
| `top_product_share` | Top product, % | pct1 | FY0 | − | C | `top_product_share` | "The largest product's share of tagged product revenue. A proxy for concentration." |
| `trial_concentration` | Top asset trials, % | pct1 | - | − | C | `trial_concentration` | "The asset with the most active lead-sponsored trials, as a share of all of them. A proxy for pipeline concentration." |
| `late_trials` | Late-stage trials, count | int | - | + | C | `late_trials` | "Lead-sponsored Phase 3 and Phase 2/3 trials on file." |
| `revenue_per_late_trial` | Revenue per late trial, {cur} bn | money1 | FY0 | n | C | `revenue_per_late_trial_usd_m` | "Revenue over late-stage trials: how much of today's business each late-stage trial stands against." |
| `catalysts_12m` | Catalysts 12m, count | int | - | n | C | `catalysts_12m` | "Pending catalysts in the next twelve months. Almost all are derived from trial records with estimated dates." |
| `pipeline_ps` | Pipeline rNPV, USD/share | price2 | - | + | M | `pipeline_per_share` | "Risk-adjusted NPV of the modelled pipeline per US-listed share. Model output." |

**Column header.** Two lines: the label (Archivo Narrow 600, 12 px, `text`), then the unit line
(mono 10.5 px, `muted`): "{unit} · {basis chip} · {provenance word}", for example "× · NTM E ·
calc.", "USD bn · sourced", "% · FY25 A · calc.", "USD/share · model". For earnings columns the
basis chip adds "street" or "GAAP/IFRS". The auto-pinned primary adds "Primary".

- Basis chip text: `"NTM E"`, `"FY26 E"`, `"FY25 A"`, `"LTM A"`, `"FY26 G"`, `"M"`. It is
  **neutral** in every case, including a column whose basis is fixed by design (EV/EBITDA reads
  "FY25 A" in neutral while the global basis is NTM). A column whose cells mix periods adds `*`
  ("LTM A*") with the tooltip "{n} companies have no LTM figure, so their cells show the last
  fiscal year, marked A." Amber on the table is reserved for per-cell fallbacks and real flags
  (4.4).
- Provenance words map to the bridge's source chips: S "sourced" is "Sourced", C "calc." is
  "Calculated", M "model" is "Model output"; an analyst edit is "Analyst" (bridge only, 5.3).
  The KPI period lines use the same words (1.5).

### 4.3 Formats

| Format | Display | Decimals | Unit shown in header |
|---|---|---|---|
| `mult1`, `mult2` | ratio | 1, 2 | `×` |
| `pct1`, `pct0` | value × 100 | 1, 0 | `%` |
| `money1` | display currency bn (usd_m / rate / 1000) | 1 | `{cur} bn` |
| `money0m` | display currency m | 0 | `{cur} m` |
| `price2` | USD | 2 | `USD` |
| `num2` | plain | 2 | none |
| `int` | plain | 0 | `count` or `months` |
| `text`, `chip`, `spark` | as named | n/a | n/a |

`signed` adds `+` to positive values. All numbers are right-aligned in IBM Plex Mono with
`font-variant-numeric: tabular-nums lining-nums`; fixed decimals per column keep the decimal
points in line. Each numeric cell reserves a 12 px marker slot after the number so a marker never
shifts alignment.

### 4.4 Markers in cells

> Revision 3: a marker shows only where a flag bears on the cell's value (`flagMarks`, 12.7).

- Per-cell basis fallback: the tag letter (A, E, G) in the marker slot in **amber** when
  `tagDiffers` (an LTM column showing FY0 for this company); tooltip names the period. This is
  the only per-cell amber tag.
- Column-level period mixing is marked once, by `*` in the header chip, not in every cell.
- Model cells (M) always show `M` in `muted`.
- Data-quality mode shows every tag letter in `muted` (amber stays amber).
- Amber flag: 1 px dotted amber underline under the number plus the tooltip line; the marker slot
  shows `!` when there is no tag to show.
- `—` (null glyph, muted): tooltip "No value. {reason}".
- `n.m.` (muted): tooltip "Not meaningful. {reason}".
- `no burn` (muted, 11 px) for `nb`.
- Guided (G) cells carry the guidance quotation in their tooltip: "{company} guidance, {date}:
  “{text}”" (3.11 lint rules).
- The table holds no analyst-entered values. An analyst-added peer shows `+` in the Fit cell and
  "Added by you" in its tooltip and expanded row. Analyst inputs exist only in the bridge, where
  each carries the "Analyst" chip as well as the dashed underline (5.3).
- Filing currency mode (`REPORTED`): money cells show the currency code in a 28 px slot
  (`309.1 DKK`); the header unit reads "bn, filing currency". Market cap and EV in this mode are
  the USD market figures translated at the ECB rate, and their tooltips say "USD market value
  translated at the ECB rate of {date}". Money summary cells are computed when every included
  peer shares the focal company's row currency; otherwise they read `—` with the reason "Mixed
  currencies. Statistics need one currency: pick USD, EUR, GBP, CHF or DKK."

### 4.5 Presets

> Revision 3: each built-in preset holds nine columns (12.7), and "Layouts" sits in the toolbar's View menu.

Presets change only the non-frozen columns. Keys `1` to `7` select them in this order.

| # | id | Label | Columns |
|---|---|---|---|
| 1 | `core` | Core valuation | `market_cap`, `ev`, `pe`, `ev_ebitda`, `ev_revenue`, `price_to_sales`, `fcf_yield`, `price_to_book`, `peg`, `pt_upside`, `revenue_growth` |
| 2 | `growth` | Growth and profitability | `revenue`, `revenue_growth`, `revenue_cagr3`, `ebitda_growth`, `eps_growth`, `gross_margin`, `ebitda_margin`, `operating_margin`, `net_margin`, `roic` |
| 3 | `balance` | Balance sheet and risk | `market_cap`, `net_debt`, `net_debt_ebitda`, `cash_to_mcap`, `runway_months`, `beta`, `vol_1y`, `est_dispersion`, `n_estimates`, `ttm_price_change` |
| 4 | `pharma` | Pharma | `market_cap`, `pe`, `ev_ebitda`, `revenue_growth`, `operating_margin`, `major_products`, `loe_share_5y`, `loe_unpriced_5y`, `rd_pct`, `late_trials`, `revenue_per_late_trial`, `pipeline_ps` |
| 5 | `biotech` | Biotechnology | `market_cap`, `ev`, `ev_revenue`, `price_to_sales`, `mcap_to_cash`, `revenue_growth`, `gross_margin`, `operating_margin`, `runway_months`, `lead_phase`, `late_trials`, `catalysts_12m`, `pt_upside` |
| 6 | `cellgene` | Cell and gene therapy | `market_cap`, `ev`, `mcap_to_cash`, `runway_months`, `lead_phase`, `trial_concentration`, `late_trials`, `catalysts_12m`, `beta`, `vol_1y`, `pt_upside` |
| 7 | `custom` | Custom | the analyst's list; starts as a copy of the preset in use when first chosen |

The preset menu footnote reads: "No medtech or healthcare services companies are in the
70-company universe, so those presets are not offered. Cell and gene therapy takes their place."
The first open for an engine picks the preset matching the focal engine (`pharma`, `biotech`,
`cellgene`); afterwards the last used preset per engine is restored. Every column in the catalogue
is reachable through Custom and the column finder, including `country`, `subsector`, `currency`,
`price`, `change_1d`, `spark_90d`, `eps_cagr`, `stage`, `top_product_share`,
`ev_per_late_trial` and `pipeline_to_ev`.

**Saved layouts.** The toolbar's "Layouts ▾" menu (and the palette: "Save layout", "Load layout
{name}", "Delete layout {name}") saves the preset, custom columns, hidden, pinned and widths, the
conditional format mode, density, text size and summary rows under a name. Layouts are global,
not per engine, and live in `localStorage` ("Saved in this browser only"). Loading one replaces
those settings for the current engine; deleting one offers undo.

### 4.6 Summary rows

Rows in `<tfoot>`, sticky at the bottom, panel background, a 2 px `rule-strong` top border, 26 px
each: Mean, Median, 25th percentile, 75th percentile, Peers with a value (n). The label spans the
frozen columns and names the group: "Median, 14 peers" or "Median, US subgroup".

- At `wide` and `ultrawide` all five rows show. At `laptop` and `narrow` only Median and n show by
  default, to save height; the label cell carries "Show mean and quartiles" (a button, state
  `summaryExpanded` per layout, persisted), which adds the other three.
- Computed per column by `peerStats`: included peers only, never the focal, never excluded rows,
  outliers removed only in outlier-exclude mode, filters ignored.
- n 0: `—` "No peer has a value". n 1: `—` "One peer value, no statistic". n 2 to 4: the value
  with an amber dot and tooltip "{n} values, fewer than 5". n 5 and over: the value.
- Text, chip and spark columns: empty.
- The toolbar's "Summary rows" toggle hides the footer (persisted); the n row stays.

### 4.7 Row behaviour

- Focal row: pinned first, `active-wash` background, 2 px `active` inset bar on the left edge of
  `exp`, ticker weight 700, every text on the row in `text` colour (muted fails AA on the wash,
  section 9.6). Not counted in statistics; `incl` is empty with aria "Focal company, not in
  statistics".
- Keyboard-focused cell: 2 px `active` outline inset.
- Row with the side panel open: `aria-selected="true"` and a 2 px `active` bar on the right edge
  of the frozen block.
- Mouse: a single click on a **data cell** focuses that cell only, so the analyst can then press
  `s`, `x` or a filter without a drawer covering the table. A click on the **company or ticker
  cell**, a double click anywhere on the row, `Enter` or `o` opens the side panel. A click on
  `exp` expands the row; on `incl` it toggles exclusion.
- Excluded row (session only, per focal): numbers stay visible in `muted`, `incl` cell hatched,
  tooltip "Excluded from statistics. Still shown. X includes it again."
- Analyst-added row: `+` in the Fit cell. Saved-set row: source "saved" in the tooltip and the
  expanded row.
- Filtered-out rows are not rendered; the scope line's filter chips say so in their tooltip.

### 4.8 Sorting, filtering, resizing, hiding, pinning

- Sort: click a header or press `s` on a focused header or cell: desc, asc, none. Nulls, n.m.
  and errors are last in both directions (`compareCells`). The focal row stays pinned unless
  unpinned. `aria-sort` on the sorted header.
- Header menu (button `▾` on hover or focus, or `Enter` on a focused header): Sort descending,
  Sort ascending, Filter, Hide column, Pin left or Unpin, Move left, Move right, Definition
  (opens the methodology drawer at this column's definition).
- Filter: numeric columns take a minimum and a maximum or "Has a value"; text columns take a
  contains filter. Active filters appear as chips in the scope line ("P/E, × ≥ 10"), each
  removable; `r` clears all (with undo).
- Resize: drag the header's right edge (6 px hit area); min 56, max 320; double-click fits
  content; `widths` persist per column id.
- Hide: from the header menu or Custom; a toolbar chip "{n} hidden" lists hidden columns with
  "Show". Hiding a column in a preset other than Custom creates a Custom copy first, so presets
  stay as defined. The auto-pinned primary cannot be hidden at `laptop` and `narrow` ("The
  primary metric stays visible. Change the primary in the dot plot.").
- Pin: within the frozen budget of 4.1.
- Column finder (`f`): search box over labels and tooltips; Enter shows the column (switching to
  Custom when needed), scrolls to it and focuses the focal cell.

### 4.9 Conditional format modes

> Revision 3: the mode is chosen in the toolbar's View menu (12.7).

Toolbar select, `v` cycles, default Off. The focal row treatment applies in every mode. Colour is
never the only signal.

| Mode | Applies to | Mark |
|---|---|---|
| Off | none | none |
| Premium or discount to median | numeric columns | in-cell bar from a centre tick: length proportional to `abs(v / median − 1)`, clamped at 100 %; right of the tick above the median, left below; `cf-bar` fill for both sides (neutral: a low multiple is not treated as good). Tooltip "{x}% above the peer median". |
| Percentile rank | numeric columns | bar from the left edge, length = percentile rank, `cf-bar` fill; tooltip "{pct} percentile of peers" |
| Operating trend | growth and change columns only: `revenue_growth`, `revenue_cagr3`, `ebitda_growth`, `eps_growth`, `eps_cagr`, `change_1d`, `ttm_price_change` | `▲` in `up` and `up-wash` background when over 0; `▼` in `down` and `down-wash` when under 0. Levels such as margins are not trends and stay untouched, as do valuation columns. |
| Data quality | every cell | every tag letter shown; flagged cells get `flag-wash` and `!`; derived cells get `d` in the marker slot |
| Outliers | numeric columns | `◆` muted for mild, `◆` amber plus `hatch` background for extreme |

---

## 5. Charts

All charts are SVG built by `charts.js`, read their geometry from `view`, use tokens only, and
carry a `<title>` and a `<desc>` with `view.*.description`. Interactive charts are keyboard
reachable as described per chart; a visually hidden live element (`.u-live`) announces the
focused point.

### 5.1 Peer position dot plot

- Header row (HTML): title "Peer position", the metric switcher, a lane count chip, and a tag:
  "Primary" (`active` chip) when the plotted metric is the primary metric, "Position only"
  (neutral) when it is not in `PREMIUM_METRICS`. When the plotted metric differs from the primary
  and is in `PREMIUM_METRICS` and enabled, a button "Use as primary" dispatches `SET_PRIMARY`;
  its menu also has "Reset primary" (`SET_PRIMARY null`).
- Switcher: a segmented list of `METRIC_CANDIDATES` labels (P/E, EV/EBITDA, EV/Revenue, Market cap
  / revenue, P/B, FCF yield, PEG, Market cap / cash, Market cap, EV, Cash / market cap, Runway,
  Street target, EV per late trial, Pipeline / EV); the first five show inline, the rest in
  "More ▾". A disabled item is dimmed, not hidden, with its `metricAvailability` reason as
  tooltip. Choosing an item dispatches `SET_DOT_METRIC` and changes this chart only; the banner,
  the KPIs, the scatter's default Y and the bridge keep the primary. `dotMetric` null follows the
  primary. `m` focuses the switcher.
- Geometry: lane height 56 px, lane label column 112 px when there is more than one lane (cohort
  comparison, at most 3), axis 24 px, header row 28 px, padding 12 px: 120 px for one lane.
  Linear scale; log scale for `market_cap` and `ev` (ticks 1, 10, 100, 1,000 bn).
- Domain: from the minimum to the maximum of the plotted values, focal included, padded 8 %.
  With 5 or more peer values, Tukey-extreme values (outside the 3.0 fences) are left out of the
  domain and drawn at the edge with `◂` or `▸` and a label "{ticker} {value}". Values that are `nm` or `na` are never plotted; a line under the axis reads "Not
  plotted: {k} not meaningful, {j} with no value" and links to the table.
- Marks: IQR band `rule-strong` fill, 18 px tall, centred; median a 1 px `text` line spanning the
  lane plus 6 px with the label above "Median 15.4×"; peers `r = 4` `muted` fill; excluded peers
  `r = 4` dashed `muted` stroke, no fill; outliers labelled with the ticker (10.5 px muted);
  focal `r = 7` `active` fill with a 1.5 px `text` stroke, ticker label above (12 px 700) and the
  value beside. Collisions: points within 8 px stack in up to three rows, ±6 px.
- Analyst target range: when bridge inputs set a custom multiple or percentile, a dashed 1.5 px
  `flag` bracket below the axis from low to high labelled "Target range (analyst)".
- Interaction: hover a dot for "PFE 9.7× P/E NTM, 12th percentile"; click opens its side panel.
  The plot is one tab stop (`role="group"`, `aria-roledescription="dot plot"`, labelled by the
  description); left and right arrows move between points in x order, `Home` and `End` jump to
  the ends, Enter opens the detail, the focused point gets a 2 px `active` ring and its label,
  and the live element announces "{ticker}: {value}, {pct} percentile".
- Description: "{metric} for {n} peers. Median {m}, interquartile range {p25} to {p75}. {T} at {v},
  {pct} percentile." Prefixed "Primary metric. " when the plotted metric is the primary.
- Disabled state (no enabled metric): a `.u-state` block inside the card with the state copy from
  section 8.

### 5.2 Valuation against fundamentals scatter

- Controls (HTML above): X select (growth and profitability columns: `revenue_growth` default,
  `eps_growth`, `ebitda_growth`, `revenue_cagr3`, `operating_margin`, `ebitda_margin`, `roic`,
  `loe_share_5y`, `late_trials`), Y select (valuation columns; default the primary metric), size
  select (Market cap default, EV, None), "Colour: none | stage" (default none), "Trend line"
  toggle (default on), "Log scale" toggle for Y (offered for `ev_revenue`, `price_to_sales`,
  `mcap_to_cash`, `pe` and `price_to_book`, whose values are positive).
- Default X by Y: `pe` pairs with `eps_growth` (both street on forward bases), `ev_revenue` and
  `price_to_sales` with `revenue_growth`, `ev_ebitda` with `ebitda_growth`, others with
  `revenue_growth`.
- Geometry: 320 px tall (`laptop` tab 236, `narrow` 220), left axis 44 px, bottom axis 28 px.
  Area proportional to size: radius `4 + 14 × sqrt(size / maxSize)`. Domain per 3.8: min to max,
  Tukey-extreme values clamped to the edge with `◂`/`▸`/`▴`/`▾` and a label.
- Marks: subsector by **shape only**, in neutral tones: pharma circle, biotech square, cell and
  gene triangle. Commercial marks are filled `muted`; clinical marks are hollow with a 1.5 px
  `muted` stroke. Excluded peers: a dashed 1 px `muted` outline, no fill, full opacity. Focal: the
  mark filled `active` with a 2 px `text` ring outside it and the ticker label. With "Colour:
  stage", clinical marks use `clinical` for stroke (and fill when commercial marks are filled);
  nothing else changes colour. No other hue is used in the chart.
- Trend: OLS over included peers, dashed 1 px `text` line across the peers' x range, label
  "Peer trend, R² 0.41, n 16". A band of ±10 % around the trend (the near-trend band of 3.8) in
  `rule` fill, labelled "Near trend" at its right end. A vertical dashed `rule-strong` line at the
  median x, with "{x short} below median" and "above median" (or "worse" and "better" for a
  directional x) under the axis on either side.
- Region labels (10.5 px `muted`), at most four: "Above trend" and "Below trend" in each half of
  the plot either side of the median-x line. Each label is placed at the centre x of its half,
  at a y halfway between the band's edge and the plot's top (or bottom) at that x, so it always
  sits in its region whatever the slope. A label that would overlap a point within 8 px or leave
  the plot is not drawn. No corner labels. The focal company's region is named in the region
  chip below.
- Labels: focal, outliers and the five largest by size; others on hover or keyboard focus.
- Keyboard: the plot is one tab stop (`role="group"`, `aria-roledescription="scatter plot"`,
  labelled by the description). Left and right arrows move through points in x order (ties by
  y), `Home` and `End` jump to the ends, Enter opens the detail panel, Esc leaves the plot. The
  focused point shows its label and a 2 px `active` ring, and the live element announces
  "{ticker}: {x label} {x}, {y label} {y}, {region label}".
- Interpretation line (HTML under the chart, 13 px) from `scatterModel`, followed by the region
  chip (neutral):
  - near: "{T} sits close to the peer trend for its {x label} of {x}."
  - otherwise: "{T} sits {pct}% {above | below} the peer trend for its {x label} of {x}, with
    {x label} {better | worse} than the peer median." ("above | at or below the peer median" for a
    neutral x).
  - median reference (no trend, or the trend gives no usable value at the focal's x): "{T} sits
    {pct}% {above | below} the peer median of {y label}; {reason}." with the reason "too few
    peers with both values to fit a trend" or "the peer trend gives no usable value at {T}'s {x
    label}".
  - weak fit (R² under 0.10): append "The peer trend is weak (R² {r2}), so distance from it says
    little."
- Description: "{y label} against {x label} for {n} peers. Trend R² {r2}. {T}: {region label}."
  Without a trend: "{y label} against {x label} for {n} peers. Too few for a trend. {T}: {pct}%
  {above | below} the peer median."
- Disabled state: a `.u-state` block with the copy of section 8 ("No valuation against growth
  chart").
- Legend below: three shapes with labels, "hollow = clinical", "ring = {T}", and "dashed =
  excluded".

### 5.3 Valuation bridge

> Revision 3: the bridge is no longer a section of Comps. The same inputs and chart render on the Forecast tab in bridge mode (12.5).

Two columns inside the full-width section (stacked in `narrow`): inputs table on the left
(`panels.js`), chart on the right (`charts.js`).

Inputs table rows (label, value, source chip, control):

1. Valuation metric: select among `BRIDGEABLE` columns and bases; source "Calculated".
2. Peer statistic: select Median, Mean, 25th percentile, 75th percentile, Percentile (number
   input 0 to 100); shows "of 14 peers".
3. Applied multiple: number input; "Calculated" until edited, then "Analyst" with a reset link.
4. Operating metric: for example "NTM EPS, street, USD per share 10.25"; "Sourced: Nasdaq
   consensus, 23 Sep 2026"; editable (becomes "Analyst").
5. Implied enterprise value (EV metrics only): "Calculated".
6. Less net debt: "Sourced: balance sheet 31 Dec 2025"; editable.
7. Other claims: toggle, default off, with the text "Off: peer enterprise values exclude these
   claims. Turn on to apply {T}'s filed claims ({total})." Lines listed on hover. When on, a
   number input holds the total ("Sourced: {as_of}" until edited, then "Analyst"). Disabled when
   no claims are on file ("No claims outside cash and debt on file.").
8. Implied equity value: "Calculated".
9. Shares: select "Shares behind the market cap: {market_cap_basis_text}" (default), "FY diluted
   weighted average" or "Enter a count" (becomes "Analyst"); the value in millions of US-listed
   shares.
10. Implied value per share (USD): "Calculated", 17 px mono 600.
11. Current price: "Sourced: close 28 Sep 2026".
12. Upside or downside: signed percent with `▲`/`▼` in `text` colour.

Below: "Interquartile range: {low} to {high} per share", "Street target, 12M: {pt} ({upside})"
(sourced), "Model fair value: {fv} ({rating}), model output" when modelled. "Reset to sourced"
restores every input. Analyst inputs carry the "Analyst" chip and a dashed `flag` underline;
sourced figures carry a source tooltip; nothing distinguishes them by colour alone.

Chart: a horizontal waterfall (implied EV bar from 0, net debt as a floating negative step,
other claims step when on, equity total bar) in `text` at 60 % for totals and `muted` for steps,
values labelled at bar ends; then a per-share strip: axis in USD, the IQR range as a `cf-bar`
band, current price as a 1 px `text` line labelled "Price", implied value as an `active` diamond,
street target as a `muted` tick, model fair value as a hollow `muted` diamond labelled "Model"
(not `flag`: a model value is not uncertain data). Equity multiples skip the waterfall and show
only the strip. A disabled bridge shows the reason as a `.u-state` block.

Description (`bridge.description`, on the chart's `<desc>` and in a visually hidden paragraph):
"Implied value of {V} USD per share at the peer {stat} {metric} of {M}, against a price of
{price}: {upside} {upside | downside}. Interquartile range {lo} to {hi}. {Waterfall: implied
enterprise value {EVi}, less net debt {ND}{, plus claims {OC}}, gives equity of {Eq}.}"

### 5.4 Side panel minis

Shared builders exported by `charts.js`: `sparkline(values, {width, height, label})` (1 px `text`
line, last point dot), `barMini(series, {width, height, derivedIndex[]})` (derived bars hatched),
`lineMini(series[{name, values, tone}], labels, opts)` (peer `text`, focal `active` dashed),
`phaseBars(compounds, opts)` (phase ramp tokens from `phase-preclinical` to `phase-3`, and
`phase-approved` for Phase 4 or marketed; labels always shown). The view never uses the ramp's
`phase-filed` step, whose value is the `flag` colour. Each returns an `SVGElement` with
`role="img"` and a label.

---

## 6. Panels

### 6.1 Drivers and risks (`panels.js`, `mountObservations`)

> Revision 3: replaced by 12.4.

Section title "Drivers and risks" with the chip "Observations, not conclusions". Two columns:
"Potential premium drivers" (`▲` in `up`) and "Potential discount drivers" (`▼` in `down`). Each
item: glyph, the `long` sentence (13 px), and a link chip with the column label; an M item also
carries the chip "Model output". Clicking the chip (or Enter) scrolls the table to that column,
focuses the focal cell and sets `aria-live` "Showing {column}". When the column is not in the
current preset, the link runs `SHOW_COLUMN`, which switches to a Custom copy with the column
added, and the live region says "Added {column} to a custom column set." Up to 5 per side, then
"Show {n} more". Empty side: "No observation passes the quartile tests." `notAssessed` items sit
under a hairline in muted text. In `narrow` the columns stack.

### 6.2 Peer selection (`mountPeerPanel`)

> Revision 3: the same content, in a drawer (12.6).

Title "Peer selection" with chips "{n} peers", "{k} in statistics", and the set label.

1. Warnings at the top as amber `.u-state` blocks: mixed business models (`view.peers.mixed`),
   and the weak-set states of section 8 (`view.peers.weak`: "too_few", "padded", or fewer than 5
   appropriate peers).
2. Relevance table (one row per peer, sortable, keyboard grid like the main table): Select
   (checkbox, for subgroups and bulk actions; not the same as inclusion), In statistics
   (checkbox), Ticker, Company, Relevance (score and bars), Subsector, Business model, Scale,
   Geography, Growth, Profitability or stage (each component as a percent, `—` when dropped),
   Source (System, Analyst, Saved set), Pool (A, B, C), Reason (the `reasons` text), Note (inline
   text input, saved on blur), Remove. A header checkbox selects all visible rows.
3. Candidates: "Other companies by relevance", the top 20 non-peers from the whole universe with
   an "Add" button each, and a search box across all 70 (`a` opens it).
4. Saved sets: list with Load, Delete (with undo), and "Save current set" (name input). Each
   shows its company count and date. Line under the list: "Saved in this browser only."
5. Subgroups: "Make subgroup from selected" (enabled with 2 or more selected rows), rename,
   delete (with undo). System subgroups, always present: "US", "Europe", "IFRS filers",
   "US GAAP filers", "Commercial", "Clinical". "US" and "Europe" use `region` and leave out
   companies whose region is not known; "IFRS filers" and "US GAAP filers" use `filer.standard`
   and leave out those whose standard is not recorded; each subgroup's tooltip names who was left
   out. The table toolbar's "Statistics over" select uses them.
6. Cohort comparison: pick up to 3 of System set, All {engine}, Same stage across subsectors,
   saved sets and subgroups. A small table: cohort, n with a value, median, interquartile range,
   {T} premium or discount, {T} percentile, for the primary metric. The dot plot shows one lane
   per chosen cohort.
7. Outliers: "Statistics with outliers" or "without outliers" radio, mirrored by `u`.
8. "Restore system peers" button (with undo).

### 6.3 Notes and data sources (`mountNotesSources`) and the methodology drawer (`mountMethod`)

> Revision 3: notes and data sources become the footer and the first section of the methodology drawer (12.6).

Notes and data sources, in `#main`:

- Data sources and timestamps: prices (close date, fetch time), consensus (first record 17 Sep
  2026; last check), financials (latest periods and sources), FX (ECB date and the five rates),
  refresh run (id, finish time, status, the failed sources this view reads and the others in
  neutral text), model values (computed or not).
- Storage line: "Peer sets, layouts, table settings and notes are saved in this browser only.
  Another browser or port starts empty." When storage is unavailable, the section 8 copy instead.
- A button "Open methodology".

The methodology drawer (`.pn-method`) holds what used to be a closed disclosure at the bottom of
the page. It opens from the confidence chip (at "Confidence"), from "Definition" in any header
menu (at that column's definition), from the "Open methodology" button, and from the palette
("Show methodology"). It is a right-side drawer, 520 px (`narrow`: full width), fixed inside the
frame below the header band, `role="dialog"`; Esc or close returns focus to the control that
opened it. Sections, each with an anchor:

- "Peer statistics": statistics exclude the focal company; the quantile method; one value set per
  column for statistics, percentiles and quartiles (3.7).
- "Primary metric": the candidate order by company type and why (3.5).
- "Confidence": the points table of 3.11 in words, with this view's own reasons listed first.
- "Relevance": the six weights and the appropriate-peer floor.
- "Outliers": the Tukey fences.
- "Not meaningful": the thresholds of 3.1 in words.
- "Bases": what standardised and "Ex amort. and IPR&D" mean (`payload.basis_text`), street
  against reported earnings, mixed standards and IFRS 16.
- "Definitions": every column's tooltip, grouped as in the table.

### 6.4 Detail side panel (`mountDetail`)

> Revision 3: a right drawer at every width above `narrow` (12.1), with a "Data flags" list (12.7).

Opens on a click of the company or ticker cell, a double click on a row, `Enter` or `o` on a row,
a dot or scatter point click, or a palette command, with no rerun. The table keeps its scroll
position and focused cell; focus moves into the panel header and returns to the same cell on
close (Esc or the close button). Width 440 px (`laptop` drawer and `ultrawide` column), the rail
width (`wide`), full width (`narrow`). Up and down arrows with the panel open move to the previous
or next row and update the panel.

Contents, top to bottom:

1. Header: ticker (16 px 700), name, subsector and stage chips, relevance "{score} of 100" with
   the reason, source. Actions: "Make focal", "Exclude from statistics" or "Include", "Remove from
   peers" or "Add to peers", "Open in Forecast tab" (clicks the parent tab), close `✕`.
2. Price: 1-year weekly sparkline, 52-week range, 1m, 3m and 1y change and relative to XLV
   (`covers_window` false shows "listed for less than this window").
3. Against {focal}: the `_H2H_ROWS` measures (revenue, revenue growth, net margin, R&D share,
   market cap, P/E FY0, EV/Revenue FY0, late-stage trials, catalysts 12m, losing exclusivity 5y,
   price 12m) in two columns, peer and focal. `▲` marks the better side only for revenue, revenue
   growth, net margin and late-stage trials (higher) and losing exclusivity (lower). Catalysts in
   12 months and the 12-month price change are unmarked here, unlike `_H2H_ROWS`: more binary
   catalysts are a discount driver (3.10), and a past price move is not a better or worse
   business. R&D share, market cap, P/E and EV/Revenue stay unmarked as before. A row is unmarked
   when either side is missing. Hidden when the opened company is the focal.
4. Over time: revenue growth or net margin, FY20 to FY25, opened company against the focal
   (`lineMini`), with a two-option toggle.
5. Earnings trend: FY revenue and net income bars (5 years) and quarterly revenue (8 quarters,
   derived Q4 hatched, tooltip "Q4 derived as the fiscal year less nine months"). EPS labelled
   with its unit ("USD per ordinary share, as filed"). No quarters: "No quarterly filings for
   this company; fiscal years only."
6. Estimate revisions: EPS FY1, EPS FY2 and the 12-month target: latest, first ("since 17 Sep"),
   change with arrow, revision count, estimate count, low to high. Note: "The revision record
   starts on 17 Sep 2026."
7. Recent results: latest quarter end, revenue, year-on-year change, EPS, filing.
8. Key catalysts: next 5, date, type, title, source link. Auto-derived rows carry the amber chip
   "Derived, estimated date".
9. Product and pipeline mix: top products with share of product revenue (FY), compounds by phase
   (`phaseBars`), unattributed trials count.
10. Relevant filings: latest 5, form, date, title as a link (opens a new tab).
11. Notes: a textarea "Analyst note" saved on blur with "Saved in this browser only. Last saved
    {time}."; below it the system note excerpt labelled "System-generated note, {model},
    {date}". None: "No system note for this company."
12. Model values (modelled companies only): fair value, rating, range today, pipeline rNPV per
    share risked and unrisked, each marked M, and "Model output. It does not drive the summary."
13. Data lineage: a table of sources with last live fetch and last error; a source whose error
    is newer than its live fetch shows amber "Last fetch failed {date}". Then financials latest
    period and source, balance sheet date, FX date, refresh run.

---

## 7. Keyboard and mouse

### 7.1 Focus ownership

Streamlit binds `r`, `c`, `a` and `esc` on the parent document. Keys pressed while focus is
inside the iframe never reach those bindings, and the component registers **no** listener on the
parent. So every shortcut works only after the analyst clicks into the view or tabs into it
(`tab_index=0`). The key state shows on the help button in the context bar (1.5): a filled
`active` dot when `document.hasFocus()` inside the frame, a hollow `muted` ring otherwise, with
the accessible name and tooltip "Keyboard shortcuts, keys active" or "Keyboard shortcuts, click
the view to use keys", updated on `focus` and `blur`.

The key handler normalises every event with `normKey` (3.14) and ignores events whose target is
an `input`, `textarea`, `select` or `contenteditable`, except `esc` (closes or blurs) and, inside
the palette, arrow keys and `enter`. Modifier shortcuts use `mod` = Cmd on macOS, Ctrl elsewhere;
the handler calls `preventDefault()` only for keys it consumes.

### 7.2 Shortcuts

> Revision 3: `a` opens the peer drawer at its search box, and the `esc` order gains the drawer (12.6).

| Key | Command id | Action | Single key |
|---|---|---|---|
| `mod+k` | `palette.open` | Command palette | no |
| `/` | `palette.open` | Command palette | yes |
| `?` | `help.open` | Shortcut help overlay | yes |
| `c` | `company.open` | Company selector (type to filter, Enter picks) | yes |
| `1` to `7` | `preset.1` to `preset.7` | Table presets in the order of 4.5 | yes |
| `p` / `shift+p` | `basis.next` / `basis.prev` | Cycle NTM, FY1, FY2, FY0, LTM | yes |
| `y` | `currency.next` | Cycle USD, EUR, GBP, CHF, DKK, As reported | yes |
| `g` | `earnings.toggle` | GAAP/IFRS or ex amortisation and IPR&D | yes |
| `m` | `metric.open` | Focus the dot plot metric switcher | yes |
| `f` | `columns.find` | Search metrics and columns | yes |
| `a` | `peer.add` | Add a peer (picker over all 70) | yes |
| `x` | `peer.exclude` | Exclude or include the focused row in statistics | grid only |
| `shift+x` or `delete` | `peer.remove` | Remove the focused row from the peer set (with undo) | grid only |
| `enter` or `o` | `detail.open` | Open the focused row's side panel | grid only |
| `shift+enter` | `row.expand` | Expand or collapse the focused row | grid only |
| `e` | `export.csv` | Export CSV of the current view | yes |
| `shift+e` | `export.tsv` | Copy the current view as TSV | yes |
| `r` | `filters.reset` | Clear all filters (with undo) | yes |
| `shift+r` | `layout.reset` | Reset columns, widths and sort for this preset (with undo) | yes |
| `u` | `outliers.toggle` | Statistics with or without outliers | yes |
| `v` | `cf.next` | Cycle conditional format modes | yes |
| `s` | `sort.focused` | Sort by the focused column | grid only |
| `w` | `why.toggle` | Open or close "Why?" | yes |
| `d` | `density.next` | Compact, default, comfortable | yes |
| `+` / `-` | `text.bigger` / `text.smaller` | Text size 13, 14, 15 | yes |
| `mod+z` | `undo` | Undo the last destructive action while its toast shows | no |
| arrows, `j` / `k` | `grid.*` | Move between cells and rows in the focused grid | grid only |
| `home` / `end` | `grid.rowStart` / `grid.rowEnd` | First or last column | grid only |
| `pageup` / `pagedown` | `grid.page*` | Ten rows | grid only |
| `esc` | `overlay.close` | Close the top-most of: palette, help, menu, "Why?", selector, methodology drawer, side panel; else clear cell focus | no |

"Single key: yes" commands obey the help overlay's toggle **"Single-key shortcuts"** (on by
default, `SET_SINGLE_KEYS`, persisted in `localStorage`). With it off, only the "no" and "grid
only" keys work: modifier shortcuts and `esc` everywhere, the rest only while a grid or chart has
focus. The toggle is the first control in the help overlay, and the overlay says "Turn off single
keys if they clash with a screen reader or speech input." `j` and `k` are row movement only. No
normalised key is bound twice; `core.test.js` checks it.

### 7.3 Command palette

> Revision 3: entries changed in 12.10.

Opened by `mod+k` or `/`. An input and a list (at most 12 visible) of `COMMANDS` plus generated
entries: "Go to column {label}" for every column, "Go to section {name}" for the bridge, drivers
and risks, peers and notes, "Add peer {ticker} {name}", "Remove peer {ticker}", "Open {ticker}",
"Make {ticker} focal", "Set period {basis}", "Set currency {c}", "Load peer set {name}", "Save
peer set", "Save layout", "Load layout {name}", "Delete layout {name}", "Copy summary", "Export
CSV", "Reset bridge", "Show methodology", "Turn single-key shortcuts {on | off}". Each row shows
its shortcut on the right (single-key hints only while they are on). Up and down move, Enter
runs, Esc closes and returns focus to where it was. `role="dialog"` with `aria-modal="true"`,
list `role="listbox"`, `aria-activedescendant` on the input.

### 7.4 Focus order and style

> Revision 3: the order after the scope line is replaced by 12.1.

Tab order follows the visual order of the active layout. In every layout it starts: context bar
(company, peer set, period, data state and currency, earnings, data as of, reload, export or `⋯`,
help) → banner ("Look next", "Why?", the confidence chip) → KPI cells (each focusable for its
tooltip) → scope line chips and actions. Then:

| Layout | Order after the scope line |
|---|---|
| `ultrawide` | table toolbar → table (one stop; arrows inside) → rail: dot plot switcher, dot plot, scatter controls, scatter → side panel (when open) → bridge inputs → drivers and risks links → peer panel controls → notes and sources |
| `wide` | table toolbar → table → side panel (when open, it replaces the rail) or the rail: dot plot switcher, dot plot, scatter controls, scatter → bridge → drivers and risks → peers → notes |
| `laptop` | chart strip tabs and collapse → switcher and dot plot, or scatter controls and scatter → table toolbar → table → drawer (when open) → bridge → drivers and risks → peers → notes |
| `narrow` | chart tab strip → the visible chart → table toolbar → table → overlay panel (when open) → lower tab strip → the visible lower section |

Grids use a roving model: the grid element holds `tabindex="0"` and `aria-activedescendant`
names the active cell id `c-{ticker}-{colId}`. The dot plot and the scatter hold one tab stop each
(5.1, 5.2). Popovers and drawers move focus in on open and return it on close.

Visible focus everywhere: `outline: 2px solid var(--active)` with `outline-offset: 1px`
(`-2px` inside table cells). Never removed.

### 7.5 Mouse, tooltips and the Python round trip

> Revision 3: a third action, `indication`, and the link rules are in 12.9.

- Rows: 4.7. `incl` click toggles exclusion. Header click sorts; header `▾` opens its menu.
- Tooltips, one shared element positioned inside the frame:
  - Open after 300 ms of hover, or at once on keyboard focus.
  - Stay open while the pointer is over the anchor **or over the tooltip itself**, so their text
    can be selected and their links followed; close 300 ms after the pointer has left both.
  - Esc dismisses the tooltip without moving the pointer or the focus.
  - Content stays until dismissed, the pointer leaves, or focus moves (WCAG 1.4.13).
- Screen readers reach tooltip text without hovering:
  - Every focusable anchor with a tooltip (KPI cells, chips, header cells, buttons) sets
    `aria-describedby` to the id of a visually hidden element holding the same text.
  - The grid sets `aria-describedby="tb-active-desc"`, a visually hidden element that
    `table.js` rewrites whenever the active cell changes. It holds the cell's null or n.m.
    reason, its flag texts, its period and the column definition.
- Column edge drag resizes. There is no drag to reorder (menu Move left and Move right instead).
- Undo toast (`.u-toast`, `role="status"`): bottom-left inside the frame for `UNDO_MS` (5 s):
  "{label}. Undo", with the button and `mod+z`. Hovering or focusing the toast pauses its timer.
- Python round trips, the only ones:
  1. `{action: "focus", ticker, nonce}` from the company selector, "Make focal" or the palette.
     The fragment sees a new nonce, stores it and calls `st.rerun()` (app scope). A pre-selectbox
     hook copies it into `company_pick`, exactly like the `cov_nav` hook.
  2. `{action: "reload", nonce}` from the Reload button: the fragment clears
     `_comps_valuation_payload` and reruns the fragment. Tooltip: "Reload the comps from the API.
     Refresh all in the top bar fetches new data from the sources."
- "Open in Forecast tab" clicks the parent's `button[data-baseweb="tab"]` with that label (as
  `covnav` does) and, if the company differs, also sends the focus action.

---

## 8. State catalogue

> Revision 3: the states of the two evidence groups and their copy are in 12.3.

`where` names the surface; the copy is exact. Title and detail render in a `.u-state` block
(2 px left bar in the severity colour, title 13 px 600, detail 13 px) unless the surface is a
chip or a cell tooltip. Amber at rest is kept for real uncertainty: a clean default view (for
example AZN on the 2026-09-28 book) shows no amber anywhere except cells whose own data is
flagged.

| State | Trigger | Where | Copy |
|---|---|---|---|
| Loading (Python) | `api_get` running | Streamlit skeleton at the `height` arg | none (Streamlit skeleton) |
| Loading (component) | before the first render message | whole frame: context bar shows the `focal` arg ticker; body shows hatched skeleton rows | "Loading comps for {T}" / "Reading 70 companies from the book." |
| API error | `api_get` raises | Python `state(..., error=True)` in place of the component | "Comps did not load" / "The API at {api_base} did not answer /comps/valuation ({error}). Start the API, then reload the page." |
| Schema mismatch | `payload.schema !== SCHEMA` | whole frame, red | "This view is out of date" / "It reads data schema {expected} and the API sent {got}. Reload the page to load the matching view." |
| No peer set | 0 included peers | banner (`no_peers`), dot plot and scatter `.u-state`, table body note | "No peers selected" / "Add a peer with A or from the peer panel, or restore the system set." Action: "Restore system peers" |
| Low confidence | the primary metric has 2 to 4 ok peer values (`low_confidence`) | banner headline without a premium, amber bar, chip "Low confidence"; KPI 5 value with amber `!` and "Not stated: {k} peers"; dot plot subtitle; summary cells amber dots | chip tooltip: "Only {k} peers have a {metric}. A median of fewer than 5 is not a reliable reference, so no premium or discount is stated." |
| No comparison | the focal has a value on a candidate but no candidate has 2 ok peer values (`too_few`) | banner (`too_few`), amber bar; KPI 5 `—` "Not stated"; dot plot shows the focal alone | "No comparison for {T}" / "{T} has a {metric} of {v}, but {one peer has \| no peer has} a value. Widen the set to adjacent subsectors, or add peers with A." Action: "Add adjacent-subsector peers" |
| Default set short of five | `defaultPeers.warning === "too_few"` | banner chip "Weak peer set", amber bar; peer panel `.u-state` | "Only {n} companies qualify as peers" / "{T}'s subsector and stage, with adjacent subsectors, hold {n} companies with data. Add peers with A." |
| Padded set | `defaultPeers.warning === "padded"` | banner chip "Weak peer set", amber bar; peer panel `.u-state`; "Why?" | "{k} of {n} peers added below relevance 40" / "They were added to reach five peers. Their multiples may not be comparable; review them in the peer panel." |
| Weak peer set | fewer than 5 appropriate peers included (3.6) | banner chip "Weak peer set", amber bar; confidence −1; peer panel `.u-state` | chip tooltip: "Only {a} of {n} peers score 40 or more on relevance. The median rests on less comparable companies." |
| Mixed business models | `mixedModels` not null | banner meta chip "Mixed business models" (flag); peer panel `.u-state`; confidence −1; "Why?" | "Mixed business models" / "{k} of {n} peers are {other type} while {T} is {focal type}. Their multiples may not be comparable." |
| No appropriate valuation metric | `no_multiple` | banner (`no_multiple`); KPI slots 4 to 6 switch (1.5); dot plot on the first of cash / market cap, runway, market cap with a value | "No valuation multiple applies to {T}" / "{first candidate label}: {focal cell reason} The view shows {T}'s position on cash, runway and market cap instead." |
| Loss-making company | `companyType === "loss_making"` (focal) | context bar type chip "Loss-making" (`down` tone, `▼`); P/E and EV/EBITDA cells n.m. | chip tooltip: "Operating loss of {x} in {period}. P/E and EV/EBITDA are not meaningful, so the comparison uses {primary label}." |
| Sub-scale revenue | `companyType === "sub_scale"` (focal) | context bar type chip "Revenue under $100m" (neutral) | "Revenue of {x} in {period}, under the $100m floor for revenue multiples. The comparison uses {primary label}." |
| Pre-revenue company | `isPreRevenue` (focal) | context bar type chip "Pre-revenue" (`clinical` tone) | "No revenue on file for {period}. The comparison uses {primary label}." |
| Clinical stage | `stage === "clinical"` (focal) | the stage chip "Clinical" (`clinical` tone) | "Clinical stage: no inventory or cost of sales on file, so revenue and earnings multiples are not used by default{. Revenue of {x} in {period} is on file}." |
| Negative EBITDA | FY0 EBITDA at or below 0 in any displayed cell | EV/EBITDA, net debt / EBITDA, EBITDA growth cells n.m. | "Not meaningful. EBITDA was {x} in {period}." |
| EPS sign change | `eps_sign_change` | P/E NTM and the NTM EPS cell n.m.; the flag on the focal's FY1 and FY2 cells | "Consensus moves from a loss to a profit within the next twelve months (FY1 EPS {a}, FY2 EPS {b}), so P/E NTM is not meaningful." (For a profit to a loss: "from a profit to a loss".) |
| Missing estimates | `no_consensus` flag | forward cells `—`; for the focal, a banner support note and KPI 4 on the next candidate | cell: `NA_TEXT.no_consensus` or `.no_consensus_otc`; banner: "No consensus estimates for {T}, so the comparison uses reported {period} figures." |
| Thin estimates | `thin_estimates` | the cells of 2.5 amber; observation `estimates_thin` for FY1 | "Only {n} analysts cover {period} EPS." |
| Stale price | `stale_price` flag, or `as_of.price_trading_days_old ≥ 1` | price cell `!`; context bar "Data as of" chip amber for the focal; scope chip "Stale prices: {n}" for peers; universe-level amber `.u-state` under the banner | cell and chip: "Price is from {date}, {n} trading days old." Universe: "Prices are from {date}, {n} trading days old. Refresh all in the top bar fetches new closes." |
| Failed source | `source_failed` on the focal or an included peer, or a universe-wide failure of a `VIEW_SOURCES` source | "Data as of" chip amber with `!`; affected rows' ticker `!`; scope chip "Failed sources: {n}" | "Refresh run {id} ({status}, {date}): {source} failed for {tickers}. Their figures are from the previous successful fetch." |
| Partial run, other sources | `as_of.run.status` is not `"complete"` and no `VIEW_SOURCES` failure touches this view | "Data as of" chip tooltip only, neutral | "Refresh run {id} finished {date} with status {status}. The sources this view reads all succeeded." |
| Stale balance sheet | `stale_balance_sheet` | EV, net debt, P/B, cash / market cap, market cap / cash, ROIC cells amber | "Balance sheet from {date}, {days} days old. Enterprise value uses it as filed." |
| Stale consensus | `stale_consensus` | forward cells amber | "Consensus last checked {date}, {days} days ago." |
| Stale fiscal year | `stale_fiscal_year` | every FY0 cell amber | "Latest filed fiscal year is {label}, more than 15 months old." |
| Stale share count | `stale_shares` | market cap cell `!` and its dependants | "The cover-page share count on file is from {date}, so market cap uses FY{year} weighted diluted shares." |
| Share count exception | `cover_count_exception` | market cap tooltip | "{reason} Market cap uses FY{year} weighted diluted shares." |
| Data-source disagreement | `market_cap_disagreement` | market cap and dependent cells amber | "Market cap routes disagree by {pct}%: {a} from {primary basis} and {b} from {alt basis}. {Primary basis} is used: {reason}." Reasons: "it is the more recent count" (cover count primary), the exception's reason, or "the cover count is from {date}". |
| Includes minorities | `includes_minorities` | P/E FY0 and LTM, P/B, ROIC and net margin cells amber | "IFRS {line} here includes non-controlling interests; the share attributable to shareholders is not stored for this filer." |
| Currency converted | `fx_converted` | money cell tooltips; context bar reporting text | "Converted from {cur} at the ECB reference rate of {date}: 1 {cur} = {rate} USD." |
| Currency mismatch | `currency_mismatch` | ticker `!`; cell tooltips | "Filed figures are in {units} while the company record says {company}. Figures use the unit on each filed row." |
| Standard not recorded | `na` `standard_not_recorded` | context bar reporting text "standard not recorded"; left out of IFRS and US GAAP subgroups | `NA_TEXT.standard_not_recorded` |
| Fiscal-year mismatch | `fiscal_year_end` flag on the focal or an included peer | ticker `!`; FY cells amber; scope chip "Non-December year ends: {n}" | "Fiscal year ends in {month}. Fiscal years are not calendarised, so FY figures cover a different twelve months from December filers." |
| Extreme outliers | at least one extreme outlier in the primary metric (n ≥ 5) | dot plot edge markers and labels; scope chip "{n} extreme outliers"; "Why?"; confidence −1 | "Values more than three interquartile ranges beyond the quartiles. Statistics include them unless you exclude outliers (U)." |
| Mixed reporting standards | the included set holds IFRS and US GAAP filers | "Why?" group "Bases"; methodology drawer; confidence −1 only when the primary uses filed figures | "{i} IFRS and {g} US GAAP filers. Reported figures are not reconciled between standards. Under IFRS 16 lease costs sit below EBITDA and lease payments in financing cash flow, which lifts IFRS filers' EBITDA and free cash flow." |
| Street against reported EPS | basis NTM, FY1 or FY2 | earnings column chips "street" and "GAAP/IFRS"; "Why?" group "Bases"; methodology drawer | "Forward earnings are street adjusted. Reported earnings are GAAP or IFRS. The two are never divided into each other." |
| Mixed periods | LTM basis with any FY fallback in a visible column | header chip `*` ("LTM A*", neutral) and the per-cell amber A | "{n} companies have no LTM figure, so their cells show the last fiscal year, marked A." |
| Derived operating income | `derived_operating_income` | operating margin, EBITDA margin, EV/EBITDA, net debt / EBITDA, ROIC cells amber; left out of observations | "Operating income is derived as revenue less cost of sales, R&D and SG&A. It may leave out separately presented charges, so EBITDA and margins may be overstated." |
| No add-back on derived | client flag `derived_no_addback` | the same cells, basis "Ex amort. and IPR&D" | the reason of 3.4 |
| Guidance scope or currency | `guidance_product_scope`, `guidance_cer`, `guidance_fx_unstated` | FY1 G cells n.m. or amber | `NA_TEXT` copy; flag: "The guidance names no currency basis, so it is taken as reported." |
| Wide estimate range | `estimate_range_wide` | dispersion cell and forward P/E cells amber | "FY1 EPS estimates run from {low} to {high} around a mean of {mean}. The range may mix GAAP and adjusted estimates." |
| Scatter disabled | the focal lacks x or y, or fewer than 3 peers have both | scatter `.u-state` | "No valuation against growth chart" / "{T} has no {x label \| y label} value ({reason})." or "Only {k} peers have both {x label} and {y label}; at least 3 are needed." |
| Calculation failure (company) | `record.error` | row: every cell `—`, red `✕` in `incl` | "Calculation failed for {T}: {message}. Other rows are unaffected." |
| Calculation failure (section) | a `deriveView` section throws | that section, red `.u-state` | "This section could not be computed" / "{section} failed: {message}. The rest of the view is unaffected." |
| Model not computed | `complete === false` and a modelled company | model cells `—`; notes and sources line | `NA_TEXT.model_not_computed` |
| Time machine set | `live === false` arg | context bar chip (flag) | "Live data. The time machine does not apply to this view." |
| Storage unavailable | `localStorage` access throws | notes textarea, save-set and layout controls, notes and sources | "Notes, layouts and saved sets cannot be stored in this browser. They last until the page reloads." |
| Filters hide every row | filters leave 0 peer rows | table body | "No rows match the filters" / "Clear filters with R." |
| Bridge disabled | `bridge.enabled === false` | bridge section | Not bridgeable: "No bridge for {metric}. Pick P/E, EV/Revenue, EV/EBITDA, market cap / revenue, P/B, FCF yield or market cap / cash." Non-positive metric: "{metric} is zero or negative for {T}, so a multiple of it gives no value." No net debt: "Enterprise value needs net debt, and {T} files no debt line within a year." No shares: "No share count on file for {T}." |
| Negative implied equity | `Eq ≤ 0` | bridge per-share row | "Implied equity is negative: net debt and claims exceed the implied enterprise value." |
| Undo available | a destructive action (3.15) | undo toast | "{label}. Undo" |
| Single-key shortcuts off | `singleKeys === false` | help overlay line; palette hints hidden | "Single-key shortcuts are off. Use the palette (Cmd K or Ctrl K) or turn them on here." |
| Absent subsectors | always | preset menu footnote | "No medtech or healthcare services companies are in the 70-company universe, so those presets are not offered. Cell and gene therapy takes their place." |

---

## 9. Visual system (reusable by other research tabs)

### 9.1 Tokens

Existing, unchanged: `GROUND #0C1417`, `PANEL #131E22`, `RULE #1F2E33`, `RULE_STRONG #2E4249`,
`RULE_FAINT #162125`, `TEXT #E8EDEA`, `MUTED #7E9098`, `UP #4C9A7A`, `DOWN #C4553B`,
`FLAG #D9B26B`, `PHASE_RAMP`, `ORANGE_BOOK #C98A4B`, `PURPLE_BOOK #8B7FC7`, `SPACE 8`,
`RADIUS 0`, `RADIUS_SMALL 2`, the four font stacks.

New, added to `frontend/components/tokens.py` after `FLAG` and to `frontend/assets/tokens.css`
after `--flag`, with pairs appended to `PAIRS` in `backend/tests/test_tokens.py`:

```python
# Active state: focus rings, the focal row, the active control, neutral emphasis. Interaction
# only, never data direction. Always paired with a border, weight or glyph.
ACTIVE = "#62A8D4"
# ACTIVE mixed 14 % into PANEL (Oklab): the focal row and active cell background. Derived.
ACTIVE_WASH = "#1D2F37"
```

```css
  --active: #62A8D4;        /* focus, focal row, active control */
  --active-wash: #1D2F37;   /* focal row background, ACTIVE 14% into panel */
  --rule-faint: #162125;    /* closes the existing gap: in tokens.py, missing here */
```

`PAIRS` gains `("active", tokens.ACTIVE)`, `("active-wash", tokens.ACTIVE_WASH)`,
`("rule-faint", tokens.RULE_FAINT)`. `.streamlit/config.toml` stays as it is.

Python passes the component `COMPS_TOKENS` (defined next to `LANDING_TOKENS` in
`streamlit_app.py`, built only from `TK` constants): every `LANDING_TOKENS` entry plus
`rule-faint`, `active`, `active-wash`, `font-ui-narrow`, `phase-preclinical`, `phase-1`,
`phase-2`, `phase-3`, `phase-approved`, and `space` `"8px"`, `radius` `"0px"`, `radius-small`
`"2px"`. `phase-filed` is left out: its value is the `flag` colour, and this view keeps that
colour for uncertainty. `shell.js` sets each as a custom property on `document.documentElement`.

Derived properties, defined once at the top of `research.css` (9.8; no hex anywhere in component
CSS or JS):

```css
:root {
  --clinical: var(--purple-book);                                  /* clinical and pipeline only */
  --flag-wash: color-mix(in oklab, var(--panel) 88%, var(--flag));    /* #282E2B */
  --up-wash: color-mix(in oklab, var(--ground) 84%, var(--up));       /* #162725 */
  --down-wash: color-mix(in oklab, var(--ground) 84%, var(--down));   /* #271F1E */
  --cf-bar: color-mix(in oklab, var(--ground) 65%, var(--active));    /* #284252 */
  --hatch: repeating-linear-gradient(135deg, var(--rule) 0 1px, transparent 1px 5px);
}
```

(The hex values in the comments are the computed results, for the contrast table only.)

There are no categorical colours. Subsector is carried by shape (5.2) in neutral tones. An
earlier draft mapped biotech to `orange-book` and cell and gene to `phase-2`; those read as the
`flag` amber (contrast 1.46 between them, hues 30° and 39°) and the `up` green (1.07), so a
biotech bubble looked like a warning and a cell and gene bubble like a favourable value.

Semantic use: `active` interaction and the focal company; `up` favourable direction; `down`
unfavourable direction and errors; `flag` uncertainty, estimates flagged as such, stale or
incomplete data, failed sources, weak comparisons, analyst inputs; `clinical` clinical and
pipeline only. Never more than these five hues in one view. Red and green always travel with
`▲`/`▼`, a label or position, and never mark a premium or a discount (1.5).

Amber discipline: amber appears for a per-cell basis fallback, a flag on data the view shows, a
failed source this view reads, a weak or low-confidence comparison, and analyst inputs. Nothing
is amber by design in a clean default view: fixed-basis column chips, the mixed-standards note and
the earnings-bases note are neutral or live in "Why?" and the methodology drawer.

### 9.2 Type scale

| Role | Font | Size / line | Weight | Case |
|---|---|---|---|---|
| Premium token (banner) | IBM Plex Mono | 24 / 28 (short 18 / 22) | 600 | n/a |
| Conclusion headline | Archivo, figures Plex Mono | 21 / 28 (short 16 / 22) | 600 | sentence |
| Conclusion support | Archivo | 14 / 20 (short 13 / 18) | 400 | sentence |
| KPI value | IBM Plex Mono | 17 / 22 (short 15 / 20) | 500; KPI 5 600 | n/a |
| Bridge result (implied value) | IBM Plex Mono | 17 / 22 | 600 | n/a |
| Company title (context bar) | Archivo | 15 / 20 | 600 | as named |
| Section title | Archivo | 15 / 20 | 600 | sentence |
| Table text and figures | Archivo / IBM Plex Mono | 13 / 18 (14 and 15 with text size) | 400; focal ticker 700 | n/a |
| Column header label | Archivo Narrow | 12 / 16 | 600 | sentence |
| Label (KPI, form, chip) | Archivo | 12 / 16 | 500 | sentence |
| Column group header | Archivo | 11 / 14 | 600 | sentence |
| Metadata, units, timestamps, period lines | IBM Plex Mono | 11 / 14 | 400 | sentence |
| Markers (A, E, G, M, !) | IBM Plex Mono | 10 / 12 | 600 | uppercase letters |
| Tickers | IBM Plex Mono | context size | 600 | uppercase |

The ladder puts the conclusion first: token 24, headline 21, KPI values 17, section titles 15,
table 13. Labels and metadata differ by family as well as size (Archivo 500 against Plex Mono
400), so they never read as the same thing. Uppercase only for tickers and marker letters. All
figures use `font-variant-numeric: tabular-nums lining-nums`.

### 9.3 Spacing and density

Spacing steps 4, 8, 12, 16, 24, 32 px (`--space` multiples and a half step). Frame gutter 16 px.
Section gap 24 px; section title to content 8 px. Card padding 12 px. Space below the banner
16 px (8 short). Hairlines 1 px `rule`; structural rules 1 px `rule-strong`; summary separator
2 px `rule-strong`. Backgrounds: header band `panel`, banner `ground`, `#main` `ground`, cards
and the table box `panel`.

| Density | Body row | Summary row | Cell padding (x) |
|---|---|---|---|
| Compact | 26 px | 24 px | 6 px |
| Default | 30 px | 26 px | 8 px |
| Comfortable | 36 px | 30 px | 10 px |

Group header row 22 px, column header 40 px. Text size 13 (default), 14 or 15 scales the whole
frame, not only the table: `shell.js` sets `--ts` on `#app` (1, 14/13, 15/13) and every size in
9.2, every row height and the band heights of 1.3 are written as `calc(<px> * var(--ts))`. The
breakpoints do not move; `fitFrame` and the short-mode threshold read the real heights.

### 9.4 Numbers and markers

- Right-aligned, fixed decimals per column, U+2212 for minus, `+` only on signed columns, units in
  headers, never in cells (except the currency code in filing currency mode).
- `—` for no value, `n.m.` for not meaningful, `no burn` for runway, never `0` for either.
- Tag letters A (reported), E (street estimate), G (company guidance), M (model output). Amber
  only for a per-cell fallback (4.4).
- `*` after a header basis chip for a column that mixes periods.
- `!` amber for a flag; `◆` for outliers; `●` `○` `◇` `✕` for inclusion; `›` `⌄` for row
  expansion; `▲` `▼` for direction; `⇄` for a converted currency; `+` for an analyst-added peer.

### 9.5 Chips, buttons, inputs, overlays

- Chip: height 18 px, padding 0 6 px, 1 px border, radius 2 px, 12 px Archivo 500 (the label
  role of 9.2).
  - neutral: `rule-strong` border, `muted` text.
  - active: `active` border and text.
  - flag: `flag` border and text.
  - down: `down` border, `text` text, `▼` in `down`.
  - up: `up` border, `text` text, `▲` in `up`.
  - clinical: 2 px `clinical` left bar, `rule-strong` border, `text` text.
  - analyst: `flag` border, `text` text, label "Analyst".
  - basis chip: mono 10 px 600, neutral (with `*` for mixed periods).
- Buttons: height 26 px, radius 2 px, 1 px `rule-strong` border, `panel` background, `text`
  label 12.5 px 600; primary action `active` border; hover `rule-strong` background; disabled 50 %
  opacity with the reason as tooltip.
- Segmented controls: joined buttons, the selected one `active-wash` background, `active` border
  and `aria-pressed="true"`.
- Inputs: height 26 px, radius 0, 1 px `rule-strong` border, `ground` background; analyst-edited
  inputs get a dashed `flag` bottom border and the "Analyst" chip.
- `.u-state`: 2 px left bar (`muted` info, `flag` amber, `down` red), title 13 px 600, detail 13 px,
  optional action button.
- Popover (`.u-pop`, used by "Why?"): `panel` background, 1 px `rule-strong` border, 12 px
  padding, `max-height: 50vh`, own scroll, anchored below its button.
- Drawer (`.u-drawer`, used by the methodology and the `laptop` side panel): `panel` background,
  1 px `rule-strong` left border, full height below the header band.
- Toast (`.u-toast`): `panel` background, 1 px `rule-strong` border, 2 px `active` left bar,
  13 px text and one button.
- Focus: 2 px solid `active`, offset 1 px (−2 px inside table cells).

### 9.6 Contrast (WCAG 2.1, computed with `theme.contrast`)

Text needs 4.5:1 (AA body), graphics and focus rings 3:1.

| Foreground | on ground | on panel | on active-wash | on flag-wash | on up-wash | on down-wash | on cf-bar |
|---|---|---|---|---|---|---|---|
| text | 15.72 | 14.34 | 11.71 | 11.70 | 13.13 | 13.63 | 8.90 |
| muted | 5.61 | 5.12 | **4.18** | **4.18** | 4.69 | 4.87 | **3.18** |
| active | 7.15 | 6.53 | 5.33 | 5.32 | 5.97 | 6.20 | n/a |
| up | 5.51 | 5.02 | 4.10 (graphic) | 4.10 | 4.60 | 4.77 | n/a |
| down | **4.18** | **3.81** | 3.11 (graphic) | 3.11 | 3.49 | 3.62 | n/a |
| flag | 9.34 | 8.52 | 6.96 | 6.95 | 7.79 | 8.09 | 5.29 |
| clinical (purple-book) | 5.28 | 4.82 | 3.94 (graphic) | 3.93 | 4.41 | 4.58 | n/a |

Rules that follow from the bold failures:

- `muted` is never used for text on `active-wash`, `flag-wash` or over a `cf-bar`: the focal row
  and warning blocks use `text` for all text; bars sit behind `text` numbers only.
- `down` is never a text colour. Negative numbers are `text` with a true minus; `down` is used for
  glyphs, bars and the 2 px error rule, which need only 3:1 (4.18 on ground, 3.81 on panel).
- `up`, `down` and `clinical` on `active-wash` are graphics only (all above 3:1).
- `active` against `up` is 1.30:1, so they never distinguish two marks on their own.
- Scatter marks are `muted` on `panel` (5.12:1) at full opacity in every state; an excluded peer
  differs by its dashed outline, not by fading (40 % opacity would fall to 1.91:1).
- In-cell bars (`cf-bar` on ground) are supplementary to the printed number and are not required
  to meet 3:1.

### 9.7 Motion and preferences

No animation over 120 ms; transitions only on opacity and background; none under
`prefers-reduced-motion: reduce`. The frame follows the terminal's single dark theme; no light
theme is defined for this tab.

---

### 9.8 Shared stylesheet for the research tabs

The primitives live in one file, `frontend/assets/research.css` (owner E, created in the first
hour), so the other research tabs can use them:

- the derived properties of 9.1;
- the type-scale classes of 9.2: `.u-token`, `.u-headline`, `.u-support`, `.u-kpi-value`,
  `.u-section-title`, `.u-label`, `.u-meta`, `.u-num`, `.u-marker`, `.u-ticker`;
- `.u-chip` and its tones, `.u-btn`, `.u-seg`, `.u-input`, `.u-state`, `.u-pop`, `.u-drawer`,
  `.u-toast`, `.u-tip`, `.u-menu`, `.u-kpi-strip` and `.u-kpi`, `.u-focus`;
- the density and text-size variables of 9.3.

It reads only the custom properties of `tokens.css`. Two consumers load the same file:

- `theme.py` reads it next to `_TOKENS_CSS` (`_RESEARCH_CSS = (_ASSETS /
  "research.css").read_text()`) and injects it in `css()` after the tokens, so the Streamlit-native
  tabs can use the classes in their HTML.
- `compsval/__init__.py` reads it once at import and passes it as the `shared_css` arg;
  `shell.js` writes it into one `<style id="research-css">` before `styles.css` applies. The
  component's own `styles.css` holds only `.sh-`, `.tb-`, `.ch-` and `.pn-` rules.

Existing `theme.py` classes and their primitive. This build adds the primitives; moving each tab
onto them is later work, one tab per change.

| `theme.py` class | Primitive | Note |
|---|---|---|
| `.state`, `.state.err` | `.u-state`, `.u-state.red` | same 2 px bar idea; `.u-state` adds the amber tone and the action button |
| `.asof-banner` | `.u-state` (info) | |
| `.sec`, `.sec-label` | `.u-section-title` | sentence case replaces the tracked uppercase |
| `.sec-count`, `.sec-basis` | `.u-chip` (neutral), `.u-meta` | |
| `.stats`, `.stat`, `.pos`, `.metricbar` | `.u-kpi-strip`, `.u-kpi` | label, value, period and compare lines |
| `.stat .v.risk`, `.pos .v.down`, `.neg` | `.u-num` with a `▼` glyph | colour never alone |
| `.mono` | `.u-num` | tabular figures |
| `.fin-note`, `.note-d`, `.reg-tag`, `.pin-tag` | `.u-meta`, `.u-chip` | |
| `.subhead` | `.u-section-title` with `.u-meta` beside it | |

`backend/tests/test_research_css.py`: every `var(--x)` in `research.css` names a property defined
in `tokens.css` or in `research.css`'s own `:root`; the file holds no hex colour; `theme.css()`
contains the file's text; `compsval.__init__` passes the same text as `shared_css`.

---

## 10. Tests

> Revision 3: the tests each owner adds are in 12.11.

### 10.1 Backend: `backend/tests/test_comps_valuation.py`

Never the real book. Fixture `valuation_db(tmp_path, monkeypatch)`: `db.init(tmp)`,
`seed.load_companies(tmp)` (all 70 companies, most with no data), then seeds:

- LLY through `FinancialsEdgarFetcher` with `fixtures/companyfacts_lly.json` (as `test_comps.py`
  does), two `prices` rows, a prices snapshot with `currency` USD and `fetch_kind` live, Nasdaq
  `consensus_estimates` rows for EPS FY2026, FY2027, FY2028 with low, high and notes "9
  estimates, per US-listed share", and a `PriceTarget 12M` row with note "19 buy, 4 hold, 0 sell;
  per US-listed share"; three FY2026 `Revenue` guidance rows with different `as_of`.
- NVO through `fixtures/companyfacts_nvo.json` (DKK, no SharesOutstanding), a price, an
  `fx_rates` row for DKK, an `adr_ratios` row, and a `RevenueGrowth` guidance row of −3.0 with
  `fx_basis` `cer`.
- One clinical company with cash and short-term investment instants, negative operating cash flow
  rows, and no debt rows.
- One company with cash instants and no operating cash flow rows at all.
- One company whose latest price is five weekdays before the fixed `today`, with 80 daily closes.
- One company with money rows in EUR while `companies.reporting_currency` is USD, `country` US,
  `is_foreign_private_issuer` 0, `filings` rows of form 20-F and 6-K, and a financials snapshot
  whose payload carries `"taxonomy": "ifrs-full"` (BNTX-shaped); a second 20-F filer like it
  with no taxonomy in its snapshot.
- One company with a September fiscal year end and Nasdaq EPS rows.
- One company whose SharesOutstanding instant is 1.3 times its diluted share count.
- One company whose SharesOutstanding instant is dated 2012-07-13 (REGN-shaped).
- One company whose weighted diluted count is filed in thousands (IOVA-shaped: 357,345 against a
  453m cover count).
- One IR-workbook company (ROG-shaped) with `NetIncomeLoss` and `NetIncomeAttributableToParent`
  rows.
- One company with `ProductSales` guidance and one whose `Revenue` guidance note reads "net
  product revenue".
- FY EPS rows of −0.48 (FY2026) and 9.87 (FY2027) for one company (GILD-shaped).
- One `other_claims` row for LLY.
- A `refresh_runs` row with status `partial` whose `detail` carries a `consensus_nasdaq` error
  "STOK: consensus_nasdaq: The read operation timed out" and an `approvals` error.
- `today = dt.date(2026, 9, 29)` passed to `build`.

Assertions:

1. `out["schema"] == 1`; `len(out["companies"]) == 70`; tickers unique; every record has the
   keys of 2.3.
2. `json.dumps(out, allow_nan=False)` succeeds and no value is a numpy type.
3. LLY: `market_cap_basis == "diluted_weighted"` with a `cover_count_exception` flag and
   `market_cap_basis_text` ending with the exception reason; `market_cap_shares_m ==
   market_cap_usd_m / price`; `ev_usd_m == market_cap_usd_m +
   cashflow.build_cashflow(db, "LLY")["net_debt_usd"] / 1e6`; `periods.FY0.revenue_usd_m ==
   65179.0`; FY1 `eps_n == 9`; `street.price_target.ratings == {"buy": 19, "hold": 4, "sell":
   0}`; `NTM.weight_fy1 == (date(2026,12,31) − price_date).days / 365`; FY1 guidance is the
   newest of the three rows.
4. NVO: `market_cap_basis == "diluted_weighted"` and the value in USD (divisor × close × DKK
   rate); an `fx_converted` flag with the DKK rate; `growth.revenue_fy` equals the DKK ratio;
   guidance `growth == -0.03`, `growth.revenue_guided_fy1 is None` with `na` `guidance_cer`.
5. Clinical company: `ev.ev_usd_m is None` and `na["ev.ev_usd_m"] == "no_debt_line"`;
   `risk.runway_months > 0`; `ev.cash_usd_m` set. The company with no operating cash flow has
   `risk.runway_months is None` with `na` `no_cash_flow`, not `not_burning`.
6. Every `None` under `market`, `ev`, `periods`, `growth`, `street`, `risk`, `healthcare` and
   `model` in every record, and a null `filer.standard` or `region`, has an `na` entry (walk the
   tree). A null period object counts once.
7. Stale price company has `stale_price` with `trading_days == 4`; LLY (price the prior weekday)
   has none. Its `spark_90d` has at most 60 values, the last equals `market.price`, and changing
   the system clock (monkeypatch `datetime`) does not change it, since it reads `today`.
8. A negative EBITDA survives as a negative number (never nulled, never clamped).
9. BNTX-shaped company: `currency_mismatch` flag; amounts converted at the EUR rate, not treated
   as USD; `filer.kind == "20-F filer"`, `filer.standard == "IFRS"`, `standard_source ==
   "filed facts"`; `region is None` with `na` `domicile_unknown`; `na["periods.LTM"] ==
   "no_ltm_20f"`. The second 20-F filer has `filer.standard is None` with `na`
   `standard_not_recorded`.
10. September company: `fiscal_year_end_month == 9`, `fiscal_year_end` flag, NTM weight from the
    September year end.
11. The company whose cover count is 1.3 times its diluted count: `market_cap_basis ==
    "shares_outstanding"`, a `market_cap_disagreement` flag, and `market_cap_disagreement ==
    pytest.approx(0.30)` by the formula `abs(market_cap_usd_m / market_cap_alt_usd_m − 1)`.
12. REGN-shaped: `market_cap_basis == "diluted_weighted"` with `stale_shares`. IOVA-shaped:
    `market_cap_basis == "shares_outstanding"`, `market_cap_alt_usd_m is None` with `na`
    `share_count_scale`, no disagreement flag.
13. ROG-shaped: `net_income_usd_m` from `NetIncomeAttributableToParent`, `net_income_basis ==
    "attributable to shareholders"`. An EDGAR IFRS filer (NVO) has `includes_minorities` flags on
    net income and equity. LLY has none.
14. Guidance: the product-scope companies have `metric_scope == "product"` and
    `revenue_guided_fy1 is None` with `guidance_product_scope`; LLY has `metric_scope ==
    "total"` and a computed `revenue_guided_fy1`.
15. GILD-shaped: `periods.NTM.sign_change is True` and an `eps_sign_change` flag.
16. `as_of.run.failed_sources == [{"source": "consensus_nasdaq", "ticker": "STOK", ...}]`,
    `"approvals" in as_of.run.other_failures`, and STOK's record carries `source_failed`.
17. LLY `other_claims_usd_m` equals the signed row; a company without rows has null and
    `none_on_file`.
18. Model block with the response cache off: a modelled company has `state "not_computed"` and
    `out["complete"] is False`; with `response_cache.cached_json` monkeypatched to return saved
    `fv_*.json` and `fvd_*.json` shapes, `state "modelled"`, fields filled, `complete` true.
19. A company whose builder raises (monkeypatch a helper to raise for one ticker): that record
    has `error` set and `calc_failed`, the other 69 are built, `out["errors"]` names it.
20. Route: `TestClient(main.app).get("/comps/valuation")` returns 200 and the same shape; with
    `complete` false the response carries `x-cache-skip: 1`.
21. Cache: with the response cache enabled (`ER_TOOL_RESPONSE_CACHE=1` in the test) a response
    with `x-cache-skip: 1` is not stored (`response_cache._entries` has no key for it);
    `"/comps/valuation" in response_cache.LATE_GLOBAL_READS`.

`backend/tests/test_financials_taxonomy.py`: `financials_edgar` on `companyfacts_lly.json` writes
`"taxonomy": "us-gaap"` into its snapshot payload and on `companyfacts_nvo.json` writes
`"ifrs-full"`; `financials_esef` on its fixture writes `"ifrs-full"`.

`backend/tests/test_comps_valuation_book.py`, taking the `book` fixture (skipped where no book
is built): on the real book, read only, 70 records; market cap for all 70; EV for at least 36;
positive NTM P/E inputs for at least 29; `json.dumps` size under 900 KB; build under 10 s. Book
guards: REGN on the diluted route with `stale_shares`; LLY on the diluted route with
`cover_count_exception`; IOVA's alternative null with `share_count_scale`; BNTX, ARGX and LEGN
with `filer.kind == "20-F filer"` and `region is None`; GILD with `eps_sign_change`; SRPT and ALNY
with `metric_scope == "product"`. Run it against a `.backup` copy with `ER_TOOL_DB` pointed at
it.

`backend/tests/test_tokens.py`: the three new `PAIRS`, which fail until both files carry them.

`backend/tests/test_research_css.py`: 9.8.

### 10.2 JavaScript: `frontend/tests/compsval/core.test.js` (`node --test`)

Fixtures in `frontend/tests/compsval/`: `fixture_min.json` (hand-built by B from section 2.4:
AZN, CRSP plus four synthetic peers), and `fixture_payload.json` (A generates it from
`GET /comps/valuation` on the live API, trimmed to all 18 pharma records plus CRSP, NTLA, VKTX,
BNTX, ARWR, IOVA, KRYS, ATRA, AXSM, LEGN, ABEO, AUTL and QURE, `detail` kept for AZN and CRSP
only). Tests stay outside the served folder. A `package.json` with `{"type": "module",
"private": true}` sits beside them.

Assertions:

1. `quantile`: `[1,2,3,4]` p25 1.75, median 2.5, p75 3.25; odd `[1,2,3,4,5]` median 3; single
   value returns it; empty returns null; nulls and NaN ignored, never read as 0.
2. `percentileRank` mid-rank with ties; `premium` both directions, null for a non-positive
   reference and null for a null direction (`pt_upside`, `pipeline_to_ev`).
3. `quartileSide`: peers 1 to 8 with the focal at 6.1 is not `"top"` (p75 6.25) although its
   mid-rank percentile is 75; at 6.25 it is `"top"`.
4. `isInLine`: 0.044 true, 0.045 false, −0.049 false (rounds to 5).
5. `fences` and `outlierClass`: null under 5 values; a value at 3.1 IQR above p75 is extreme.
6. `ols`: exact line recovers slope and intercept, `r2` 1; under 5 points null.
7. AZN cells on the fixture: P/E NTM 16.22, P/E FY0 25.41, EV/Revenue FY0 4.83, market cap /
   revenue 4.43, EV/EBITDA 15.08, FCF yield 4.53 %, P/B 5.34, market cap / cash 45.46, operating
   margin 23.40 % and ex amortisation 30.56 %, ROIC 15.61 %, PEG 1.19 (each to 2 decimals).
8. LLY-shaped derived operating income: the "Ex amort. and IPR&D" operating margin equals the
   reported one and carries `derived_no_addback`; EV/EBITDA likewise.
9. CRSP cells: P/E, EV/Revenue, market cap / revenue, EV/EBITDA, FCF yield, revenue growth and
   net debt / EBITDA all `nm` with a reason; P/B 2.99; market cap / cash 2.21; cash / market cap
   45.2 %; runway 77; no cell ever shows `0` for a null input.
10. Growth guards: revenue CAGR n.m. when FY0 less three years is under 10 (USD m) (CRSP's +43.1 %
    on $1 to 4m of revenue); EBITDA growth n.m. on a base of 5 (USD m); EPS growth n.m. on a base
    of 0.05; any growth over 5.0 n.m.
11. `companyType`: AZN profitable; GILD profitable; CRSP clinical; ARWR clinical (and
    `isPreRevenue` false); ABEO, AUTL and QURE sub_scale; a synthetic commercial company with
    revenue 500 and an operating loss loss_making; `isPreRevenue` true only for revenue null or 0.
12. NTM sign change: GILD-shaped (−0.48, 9.87) and AXSM-shaped (−2.92, 3.76) P/E NTM are `nm`
    with the sign-change reason; their P/E FY2 is computed.
13. `primaryMetric`: AZN `pe` state ok; GILD `ev_ebitda` with the "P/E NTM is not available"
    reason; CRSP `mcap_to_cash` state ok; BNTX-shaped (loss-making, EV null) `price_to_sales`;
    KRYS-shaped (one peer on every candidate) state `too_few`; with 3 ok peers state
    `low_confidence`; an override of `runway_months` is ignored; an override of `ev_revenue`
    wins when enabled.
14. LTM basis: AZN (no LTM) cell falls back to FY0 with `tagDiffers` true; a company with LTM uses
    it; the column chip reads "LTM A*" and is not amber.
15. Currency: EUR display divides by 1.1378; `basis_text.standardised` renders with "EUR";
    `REPORTED` sets `unit`; summary money cells are `—` with the mixed-currency reason when row
    currencies differ and computed when every included peer shares the focal's row currency.
16. `relevance`: identical companies score 100; weights renormalise when growth is null (score
    unchanged by a missing component's weight); geography is dropped when either region is null;
    a pharma and a clinical cellgene company score under 40.
17. `defaultPeers`: at most 15; same engine and stage first; a focal with three same-pool
    candidates gets two from pool B with the "Added to reach five peers" reason; `warning` is
    `"padded"` when a pool B peer scores under 40 and `"too_few"` when pools A to C hold fewer
    than 5.
18. `mixedModels` fires for a profitable focal with two clinical peers in five.
19. `peerStats` excludes the focal, excluded rows and (in exclude mode) outliers; filters never
    change it; `percentileRank` and `quartileSide` read the same `values`.
20. `bridge`:
    - Self-consistency: for AZN, LLY and CRSP, with `multipleOverride` set to the focal's own
      multiple, V equals the price to within 1e-9 relative, on every enabled route (P/E NTM, P/E
      FY0, EV/Revenue, EV/EBITDA, market cap / revenue, P/B, market cap / cash).
    - P/E NTM on AZN with M 15.36 gives 15.36 × 10.2461 = 157.38 per share and upside −5.28 %.
    - The EV/EBITDA path subtracts net debt; other claims apply only when on;
      `otherClaimsOverride` replaces the filed total; the toggle is disabled when claims are null.
    - `sharesSource "diluted"` uses `shares_diluted_m`.
    - Negative X disables with the exact reason; negative equity keeps the steps and nulls the
      per-share value.
21. `scatterModel`: region ids for four constructed focal positions and `near` inside 10 %; a
    negative-slope fit with `ŷ ≤ 0` at the focal's x falls back to `reference "median"`; labels
    use "better" and "worse" from the x column's direction (`loe_share_5y` lower is better);
    disabled with fewer than 3 peers with both values.
22. Dot plot view: the domain is min to max of the plotted values; `nm` and `na` values are not
    in `points` and are counted in `notPlotted`; an extreme value is clamped with its label.
23. `observations`: rules fire only with 5 or more peer values and only by `quartileSide`;
    `runway_short` severity red under 12 months; `margin_top` does not fire for an LLY-shaped
    focal with `derived_operating_income`; `estimates_thin` and `estimates_wide` have their own
    copy; `notAssessed` always has two items.
24. `conclusion`:
    - The ok, in-line, FCF-yield, low-confidence, too-few, no-multiple, no-peers and clinical
      cases produce the exact templates of 3.11 with the fixture numbers.
    - The low-confidence headline contains no percentage.
    - Every headline for every fixture company is at most 160 characters and every
      `supportShort` at most 90.
    - A premium-side observation yields "Alongside the premium"; "associated with" appears only
      under the tested-association rule; an M observation never appears in `support`.
    - `label` is present; the token never carries an `up` or `down` tone.
25. `confidence`: AZN on `fixture_payload.json` (all 18 pharma) scores 2, level high, with no
    standards reason (P/E NTM is street) and no estimate-range reason (6 estimates, 0.55); a
    pharma focal on EV/EBITDA gets the standards reason and, with 4 of 13 peer values derived,
    the derived reason; a padded set gets the appropriate-peer reason; `bar` is `"flag"` for level
    low, for `low_confidence` and for a weak set.
26. `lookNext`: an amber flag that costs confidence on the focal's primary cell comes first; else
    the strongest non-M observation; the text is at most 60 characters.
27. House style: every string from `conclusion`, `observations`, `flagText`, `NA_TEXT`, the
    state catalogue (exported as `STATE_COPY`), column tooltips and `COMMANDS` labels passes
    `lintCopy` with its kind (3.11): labels get the case check, sentences do not. The allow list
    accepts "EV/Revenue", "FY2", "20-F", "R²", "Phase 3", "IRA Part D" and "Open in Forecast
    tab". Guidance quotations are not linted.
28. `reduce`: every action type returns a new state or the same object when nothing changes;
    `SORT` cycles desc, asc, none; `TOGGLE_EXCLUDE` is per focal; `SET_DOT_METRIC` never changes
    `primaryOverride`; `SHOW_COLUMN` for a column outside the preset switches to Custom with it
    appended; `REMOVE_PEER` then `UNDO` restores the peer; `EXPIRE_UNDO` clears the record after
    `UNDO_MS`; `persistable` leaves `excluded` and `ui` out of local storage.
29. `migrateState`: an unknown version returns defaults; unknown column ids and tickers are
    dropped; a `primaryOverride` outside `PREMIUM_METRICS` is cleared; a valid v1 object
    round-trips.
30. `toCSV`: header comment, units, basis and provenance in headers, empty for null, `n.m.` for
    not meaningful, summary block after a blank line.
31. `compareCells`: nulls, n.m. and errors last in both directions.
32. Keys: `normKey` gives `"?"` for `{key: "?", shiftKey: true}`, `"+"` for `{key: "+",
    shiftKey: true}`, `"shift+x"` for `{key: "X", shiftKey: true}`, `"mod+k"` for Cmd K on macOS
    and Ctrl K elsewhere, `"esc"` for Escape; `KEYMAP` has no key bound twice and no parent-level
    binding; every `COMMANDS` id with a key is reachable; with `singleKeys` false every
    `singleKey` command returns null from `handleKey` while `mod+k`, `esc` and grid keys still
    work.

`backend/tests/test_comps_js.py` runs `node --test "frontend/tests/compsval/*.test.js"` from the
repository root (glob string, not a bare directory) and is skipped when `node` is missing, so
`make verify` gates the JS.

### 10.3 Streamlit: `backend/tests/test_comps_tab_ui.py`

AppTest, skipped when the API is down, calling `_patch_button_group_serialisation()` like
`test_forecast_tab_ui.py`, module-scoped fixture:

1. The Comps sub-tabs are `["Valuation", "Indications", "Pipelines"]` for LLY and
   `["Valuation", "Pipelines"]` for a biotech; "Head to head" and "Screen" appear nowhere.
2. One `component_instance` named `components.compsval.compsval`; its `json_args` parse with
   `json.loads(s, parse_constant=fail)` (no NaN); `focal` equals the selected ticker;
   `payload.companies` has 70 records; `tokens` has `active` and `active-wash` and no
   `phase-filed`; `shared_css` equals the text of `frontend/assets/research.css`.
3. Setting `session_state["compsval"] = {"action": "focus", "ticker": "AZN", "nonce": 1}` and
   rerunning makes `company_pick == "AZN"`; the same nonce again changes nothing.

---

## 11. File ownership and build order

### 11.1 Ownership

> Revision 3: ownership for the revision is in 12.11, and the `ctx` additions in 12.10.

| File | Owner | Notes |
|---|---|---|
| `backend/comps_valuation.py` | A | builder, section 2; `COVER_COUNT_EXCEPTIONS`, `VIEW_SOURCES`, `_spark` |
| `backend/fetchers/financials_edgar.py`, `backend/fetchers/financials_esef.py` (snapshot payload only) | A | add `"taxonomy"` to the snapshot payload (2.3); nothing else in the fetchers changes |
| `backend/main.py` (route only) | A | `GET /comps/valuation`, `x-cache-skip` |
| `backend/response_cache.py` | A | `LATE_GLOBAL_READS`, skip header |
| `backend/tests/test_comps_valuation.py`, `test_comps_valuation_book.py`, `test_financials_taxonomy.py` | A | 10.1 |
| `frontend/components/tokens.py`, `frontend/assets/tokens.css`, `backend/tests/test_tokens.py` | A | 9.1, first commit |
| `frontend/components/compsval/__init__.py` | A | `comps_valuation(payload, *, focal, engine, tokens, live, height=900, key="compsval")`: `_jsonable`, `json.dumps(allow_nan=False)`, digest, `tab_index=0`, `default=None`; reads `assets/research.css` once and passes it as `shared_css` |
| `frontend/streamlit_app.py` | A | `COMPS_TOKENS`; sub-tabs; `@st.fragment` view; `_comps_valuation_payload` (`@st.cache_data(ttl=60)`); pre-selectbox focus hook; removal of Head to head and Screen and their dead helpers |
| `frontend/theme.py` | A | inject `research.css` after the tokens (9.8); delete `.h2h*` rules once unreferenced |
| `backend/tests/test_comps_js.py`, `backend/tests/test_comps_tab_ui.py`, `backend/tests/test_research_css.py` | A | 10.2 shim, 10.3, 9.8 |
| `frontend/tests/compsval/fixture_payload.json` | A | generated from the live API (GET only) |
| `frontend/components/compsval/core.js` | B | section 3 |
| `frontend/tests/compsval/core.test.js`, `fixture_min.json`, `package.json` | B | 10.2 |
| `frontend/components/compsval/table.js` | C | section 4; exports `mountTable(root, ctx) -> {update(view), focusCell(ticker, colId), scrollToColumn(colId), getViewport(), destroy()}`; owns `#tb-active-desc` |
| `styles.css` section `/* table */` (prefix `.tb-`) | C | |
| `frontend/components/compsval/charts.js` | D | section 5; exports `mountCharts(root, ctx) -> {update(view), focusDotPlot(), focusScatter(), focusPoint(ticker), destroy()}`, `mountBridgeChart(root, ctx)`, `positionStrip(strip, opts)` (for KPI 5), and the minis of 5.4 |
| `frontend/components/compsval/panels.js` | D | section 6; exports `mountBridgeInputs`, `mountObservations`, `mountPeerPanel`, `mountNotesSources`, `mountMethod`, `mountDetail`, each `(root, ctx) -> {update(view), destroy()}` |
| `styles.css` sections `/* charts */` (`.ch-`) and `/* panels */` (`.pn-`) | D | |
| `frontend/assets/research.css` | E | 9.8: the shared primitives and derived properties; first hour |
| `frontend/components/compsval/index.html` | E | `<link rel="stylesheet" href="./styles.css">`, `<div id="app">`, `<script type="module" src="./shell.js">` |
| `frontend/components/compsval/shell.js` | E | protocol shim, `installTokens`, `installSharedCss`, `copyFontFaces`, `fitFrame`, the `--band-h` and `--main-h` observer, storage wrapper (`try/catch`, `core.migrateState`), state and dispatch, layout, breakpoints and height modes, context bar with its collapse steps, banner with the token and "Why?" popover, KPI strip, scope line with its overflow menu, company selector, palette, help (with the single-key toggle), keyboard, shared tooltip, menu, undo toast and live region, CSV and clipboard actions |
| `styles.css` base and `/* shell */` (`.sh-`) | E | creates the file with the four section markers in the first hour; shared `.u-` rules live in `research.css` |

`ctx` (built by `shell.js`, used by every mount):
`{dispatch(action), getState(), getView(), openDetail(ticker), closeDetail(), openMethod(anchor),
announce(text), tooltip: {show(anchor, {title, body, lines}), hide(), describe(anchor)},
menu: {open(anchor, items), close()}, toast(label), storageOk, send(value),
clickParentTab(label), layout, height}`. Menu items are
`{id, label, shortcut, disabled, reason, checked, onSelect}`.

Class prefixes keep the stylesheets mergeable: `.u-` shared primitives in `research.css`, and in
`styles.css` `.sh-` shell, `.tb-` table, `.ch-` charts, `.pn-` panels. Nobody edits another
section.

### 11.2 Build order

1. **A, first hour**: tokens and `test_tokens` (unblocks the stylesheets). **E, first hour**:
   `research.css` with the derived properties of 9.1 and the primitives of 9.8, `index.html` and
   `styles.css` with the four empty section markers, pushed so C and D edit their own sections.
2. **In parallel**:
   - A: `comps_valuation.py`, the taxonomy field, route, cache changes, backend tests; then
     `fixture_payload.json` from the live API.
   - B: `core.js` against `fixture_min.json`, then against `fixture_payload.json` when it lands.
     Publishes the `View` shape of 3.15 unchanged; any change to it is a spec change.
   - C, D, E: build against a hand-written stub `View` that follows 3.15, then switch to
     `core.deriveView` when B lands.
3. **A**: `compsval/__init__.py`, `streamlit_app.py` wiring, `theme.py` injection, removal of the
   superseded sub-tabs, `test_comps_js.py`, `test_comps_tab_ui.py` and `test_research_css.py`
   (after B's tests exist).
4. **Integration** (E leads): real payload through `core.deriveView` into every mount. Checks:
   - `pytest tests/ --ignore=tests/test_refresh.py` green, `node --test` green.
   - Screenshots of the running app at 1440 × 810 and 1920 × 1080 compared with the drawings of
     1.6 (heights, widths, collapse steps, what the first screen shows), plus a pass at frame
     widths of about 1000 and 2500 px.
   - The five-second questions of the brief, on AZN, CRSP and GILD: which company (context bar),
     which peer group (peer set control and headline), which metric (headline and KPI 4),
     premium or discount (token and KPI 5), where it sits (KPI 5's position strip, then the dot
     plot), the likeliest data-supported explanation (support line and "Why?") and where to look
     next ("Look next"). All seven are answered from the header band.
   - A keyboard-only walk through every control in the tab order of 7.4, once with single-key
     shortcuts off; no horizontal page scroll outside the table; the table position kept when the
     side panel opens and closes; the wheel reaches the lower sections from over the table.
   - A JS edit needs a browser reload; a Streamlit rerun does not reload the iframe.

---

## 12. Revision 3: simplification

Status: agreed 2026-09-30, ready to build. It serves two requests made after the first build:
"I want to simplify it a bit i rlly like the drivers and risk section, i feel like the valuation
bridge bit shld be in the forecaasts tab", and "maybe linking the catalysts as well to the drivers
and risks bit and also indication competition and share of pool etc". The lead's decisions R3.1
to R3.7 (`scratchpad/comps_brief_followup.md`) are turned into contracts here. **Where this
section and sections 0 to 11 disagree, this section holds.** Superseded passages carry a one-line
pointer to the subsection that replaces them.

Figures quoted: the 2026-09-29 22:33 backup, with `today = 2026-09-29` (prices to the 2026-09-28
close). The context examples were produced by a reference prototype, not the implementation:
`scratchpad/arch3/ref_comps_context.py`, whose full outputs are `scratchpad/arch3/context_AZN.json`,
`context_LLY.json`, `context_NVO.json`, `context_AMGN.json`, `context_VRTX.json`,
`context_VKTX.json`, `context_BAYN.json` and `context_CRSP.json`. The peer set and flag counts
come from `core.js` run on a payload built from the same backup (`scratchpad/arch3/bk_val.json`,
`sim.mjs`, `sim2.mjs`). `scratchpad/` is the session scratchpad,
`/private/tmp/claude-501/-Users-charleswoodfine-Documents-WORK-Projects-ER-Tool--claude-worktrees-reverent-borg-5f3beb/6d18b4ba-ea38-4b11-8d77-43ead66a9954/scratchpad`.

### 12.0 What changes

| Decision | Change | Where |
|---|---|---|
| R3.1 | `#main` holds four things in one order at every width: Drivers and risks, the chart strip, the table, a one-line footer. The chart rail, the lower sections and the lower tab strip go. | 12.1 |
| R3.2 | Drivers and risks gains two evidence groups, "Catalysts ahead" and "Competition by indication", fed by a new per-company endpoint. | 12.2, 12.3, 12.4 |
| R3.3 | The valuation bridge leaves Comps. The Forecast tab draws it with the same component in `mode="bridge"`. KPI 6 stays and links there. | 12.5 |
| R3.4 | Peer selection is a drawer. Notes and data sources become the footer plus a first section of the methodology drawer. | 12.6 |
| R3.5 | One "Basis" menu replaces the data state and currency select and the earnings control. | 12.6 |
| R3.6 | Table toolbar: three controls. Presets hold nine columns. A `!` shows only where a flag bears on the value. | 12.7 |
| R3.7 | A cohort of 20 or fewer other companies is the default peer set, whole. | 12.8 |

New constants in `core.js`:

```js
export const CATALYST_MIN_PCT = 0.05;        // stake, or an unapproved asset's modelled value, as a share of price
export const POOL_KEEP_MAX = 0.90;           // a company keeping at most this share of its own forecasts is rationed
export const POOL_LEAD_MIN_SHARE = 0.25;     // largest share of the modelled starts, and at least this
export const POOL_LEAD_MIN_COMPANIES = 3;
export const COMPETITION_MIN_PCT = 0.02;     // the company's modelled value in the indication, share of price
export const INSIGHT_ROWS = 5;               // rows an evidence group shows before "Show {n} more"
export const WHOLE_COHORT_MAX = 20;          // R3.7
export const MAX_PRESET_COLUMNS = 9;         // R3.6
export const REGULATORY_KINDS = ["PDUFA", "regulatory decision", "AdCom", "EMA decision"];
export const LATE_PHASES = ["Phase 3", "Phase 2/3"];
export const CONTEXT_SCHEMA = 1;
export const GOTO_KEY = "er.compsval.goto";  // sessionStorage, 12.5
```

`LINT_ALLOW` gains `PoS`, `PDUFA`, `EMA` and `Catalysts`.

### 12.1 Page structure and layout (R3.1)

**Tree.** Replaces the `#main` part of 1.1.

```
#app                                                    shell.js
  header band (unchanged: context bar, banner, KPI strip, scope line)
  #main (the one page-level scroll container), children in this order at every width
    .sh-obs      Drivers and risks                      panels.js  mountObservations
    .sh-charts   chart strip: Position | Valuation and growth      charts.js  mountCharts
    .sh-table    toolbar and table box                  table.js   mountTable
    .sh-foot     Sources and method, one line           shell.js
  right-side surfaces, fixed inside the frame from --band-h to the bottom, one open at a time
    .sh-detail   company side panel, 440 px             panels.js  mountDetail
    .sh-peers    peer drawer                            panels.js  mountPeerPanel
    .sh-method   methodology drawer, 520 px             panels.js  mountMethod
  overlays (unchanged)
```

Gone from `#main`: `.sh-lower`, `.sh-lowertabs`, the bridge section and its two slots, the peer
section, the notes section, the chart rail of `wide` and the three-column grid of `ultrawide`.
`MOUNTS` in full mode is `table`, `charts`, `obs`, `peers`, `method`, `detail`. Gaps in `#main`:
8 px between blocks, 16 px side gutter.

`layoutFor(width)` keeps its four values. `ultrawide` arranges exactly as `wide`; only the table
widths of 4.1 still differ.

| Layout | Frame width | Drivers and risks | Chart strip | Table | Right-side surfaces |
|---|---|---|---|---|---|
| `wide`, `ultrawide` | 1700 px and over | Two rows, column gap 16, row gap 12. Row 1, `grid-template-columns: 1fr 1fr`: premium drivers, discount drivers. Row 2, `minmax(0, 0.85fr) minmax(0, 1.15fr)`: Catalysts ahead, Competition by indication. | Strip at every width (no rail). Header 28 px with the two tabs "Position" (default) and "Valuation and growth", the metric switcher, the "Primary" tag and the collapse chevron. Position: 120 px for one lane, plus 56 per extra cohort lane. Valuation and growth: 320 px. | Full width. Toolbar 32, table box `max-height: var(--main-h)`. All five summary rows. | Drawers: detail 440, peers `min(760px, 100% − 56px)`, method 520. |
| `laptop` | 1100 to 1699 px | The same two rows. | The same strip. Valuation and growth: 260 px. | Full width. Median and n rows by default (4.6). | The same widths. |
| `narrow` | under 1100 px, including the 800 px pane | One column: premium drivers, then discount drivers (side by side while the frame is 720 px or wider, stacked below that), then a two-tab strip "Catalysts ahead" and "Competition" (28 px) showing one group. | The same strip, 220 px. | Frozen columns and horizontal scroll (4.1). | Full-width overlays over `#main`. |

The tab state of the chart strip is `ui.narrowTab` at `narrow` and `ui.laptopTab` at every other
layout; `chartStrip[layout]` keeps the collapse state. `charts.js` drops `buildRail`.

**Heights of Drivers and risks** (`.pn-obs`, no inner scroll, no max-height):

| Part | Height, px |
|---|---|
| Title row: "Drivers and risks", the chip "Observations, not conclusions" | 32 |
| A side list: heading 24, then one item per observation. An item is one line (36) when its sentence fits, two lines (54) otherwise | 24 + 36 to 54 per item |
| Row gap | 12 |
| An evidence group: heading row 22 (title, count, column labels), 5 rows of 28, a link row 24 | 186 |
| Padding below | 12 |

At most five metric-linked items show per side, then "Show {n} more" (24 px); items drawn from
catalysts and competition always show (12.3).

**First screen at 1440 × 810** (frame about 1380 × 585, `laptop`, `short`: band 194, `#main`
391). Each column of row 1 is 666 px, so most sentences take two lines. AZN on this book has two
metric-linked premium items, plus the model's pipeline value once the model reads are warm, and
three discount items (two metric-linked and the obesity pool, 12.3): row 1 is 24 + 3 × 54 = 186.
The section is 32 + 186 + 12 + 186 + 12 = 428 px. The first screen therefore shows the
conclusion, the six key figures, the Drivers and risks title, both side lists whole, and the
heading and first four rows of both evidence groups. The chart strip starts 45 px below the
fold; the table starts at 428 + 8 + 148 + 8 = 592 px.

**1920 × 1080** (frame about 1860 × 735, `wide`, `tall`: band 254, `#main` 481). The columns of
row 1 are 906 px, sentences take one line: row 1 is 24 + 3 × 36 = 132, the section 374 px. The first
screen shows all of Drivers and risks and the chart strip's header and first 71 px.

**800 px pane** (`narrow`): band about 296 (two context rows 72, banner up to 104, gap 8, KPI
grid 88, scope line 24). With the 560 px floor `#main` has at least 264 px: the title, both side
headings and the first two items of each side.

The toolbar's "Below the table" menu goes (nothing is below the table but the footer). The
palette's "Go to section" entries become "Drivers and risks", "Peer position" and "Comparable
companies"; `scrollToSection` takes `"obs" | "charts" | "table"`. "Open drivers and risks" in the
"Why?" popover scrolls `#main` to the top and focuses the section title.

Tab order (replaces the table of 7.4) after the scope line, every layout: Drivers and risks
links (premium, discount, catalyst rows, competition rows, their "Show more" and tab links) →
chart strip tabs and collapse → switcher and dot plot, or scatter controls and scatter → table
toolbar → table → footer button → the open right-side surface.

### 12.2 Focal context endpoint: `GET /companies/{ticker}/comps-context`

Built by a new module, `backend/comps_context.py`. One company per call: the dated catalysts of
the next 12 months and the competition in the company's most valuable indications. The 2.1
conventions apply (strict JSON, decimals for shares, USD per US-listed share, ISO dates, every
null with a reason, Python 3.9).

```python
def build(ticker, db_path=None, today=None, verdict_for=None, stakes_for=None)   # -> dict or None
```

`None` for an unknown ticker (the route answers 404). `verdict_for(ticker)` and
`stakes_for(ticker)` default to `response_cache.cached_json("/companies/{t}/forecast-verdict")`
and `response_cache.cached_json("/companies/{t}/catalysts/stakes")`; tests inject them.

#### Top level (AZN, real values)

```json
{
  "schema": 1,
  "ticker": "AZN",
  "generated_at": "2026-09-29T22:41:07Z",
  "today": "2026-09-29",
  "window": {"from": "2026-09-29", "to": "2027-09-29"},
  "complete": true,
  "incomplete_reason": null,
  "price": {"close": 166.149994, "as_of": "2026-09-28"},
  "model": {"state": "modelled", "assets": 54},
  "catalysts": {
    "total": 36, "sent": 36,
    "counts": {"with_asset": 36, "with_indication": 28, "with_stake": 0, "with_asset_value": 27, "curated": 0},
    "items": []
  },
  "competition": {
    "covered": true, "reason": null, "ranked_by": "model_value",
    "total": 58, "valued": 19,
    "indications": []
  }
}
```

LLY on the same book: price 1184.78, 34 modelled assets, 33 catalysts (30 with an indication,
29 with an asset value, none with a stake), 74 indication groups of which 22 carry value.

- `price`: the latest `prices.close` with `interval = '1d'` dated on or before `today`, the rule
  behind `market.price` of 2.3. Null with no price (`na` reason `no_price` on every share of
  price).
- `model.state`: `"modelled"` (the cached verdict is ok and has lines), `"not_modelled"` (no
  asset the company owns or partners carries assumptions), `"not_computed"` (a book exists and
  the verdict is not in the response cache) or `"failed"` (the verdict is not ok). `assets` is
  the count of verdict `modelled` lines with a `per_share`.
- `complete` is false, with `incomplete_reason: "model_not_computed"`, only for `"not_computed"`.
  The route then answers with `x-cache-skip: 1`, exactly as `/comps/valuation` does.

#### Catalysts

Rows of `catalysts` with `company_id` the company, `status = 'pending'` and
`today ≤ expected_date ≤ today + 365 days`, compared as strings, ordered by `expected_date, id`.
This is the rule of `screen._catalysts_12m` with `today` injected, so `catalysts.total` equals
the table's `catalysts_12m` column on the same day. At most 60 are sent (`sent`).

```json
{
  "id": 1109,
  "date": "2027-06-04", "date_precision": "day", "date_confidence": "estimated",
  "kind": "data readout", "regulatory": false, "phase": "Phase 3",
  "asset": {"id": 1744, "name": "Elecoglipron", "is_marketed": false},
  "indication": {"id": 367, "name": "Obesity"},
  "title": "Phase 3, A Study to Investigate the Efficacy and Safety of Elecoglipron in Asian Participants With Obesity or Overweight With or Without Type 2 Diabetes Mellitus",
  "nct_id": "NCT07775404",
  "source_url": "https://clinicaltrials.gov/study/NCT07775404",
  "is_curated": false,
  "stake": null,
  "asset_value": {"per_share": 4.727080, "pct_of_price": 0.028451, "pos": 0.5537, "counted": true},
  "na": {"stake": "same_gate_later"}
}
```

| Field | Rule |
|---|---|
| `date`, `date_confidence` | `expected_date` and `date_confidence` as stored (`estimated`, `month`, `confirmed`, `stated`; the schema also allows `quarter` and `half`). |
| `date_precision` | `"quarter"` or `"half"` when the confidence says so; else `"month"` for a `YYYY-MM` date, `"day"` for a full date. |
| `kind`, `regulatory` | `catalyst_type` as stored; `regulatory` is true for PDUFA, regulatory decision, AdCom and EMA decision. |
| `nct_id` | The first `NCT` followed by eight digits in `source_url`, else null. |
| `asset` | For a registry readout (a `source_url` on clinicaltrials.gov) the `asset_id` of the `trials` row for `nct_id`, which the refresh keeps current, as the stake engine reads it; else `catalysts.asset_id`, else the trial's. Name is `COALESCE(brand_name, generic_name, internal_code)`. Null with `na.asset = "no_asset"`. |
| `phase` | The trial row's `phase`, else the leading "Phase n" of the title, else null. |
| `indication` | The indication of `asset_indication_id` when set; else the first descriptor of `indication_mapping.indications_for(conditions, parse_browse(mesh_terms))` for the trial that has an `indications` row by `mesh_id`. Null with `na.indication = "no_indication_link"`. |
| `stake` | Only from the `priced` list of `/companies/{t}/catalysts/stakes`, matched on catalyst id: `{per_share, pct_of_price, pos_now, pos_success, pos_failure, economics_share, basis, gate}`, `pct_of_price = abs(per_share) / price.close`. `basis` is `"stated"` (the asset's own `pos_success` and `pos_failure` rows, which always win) or `"derived"` (the legs pos_granular derives for a big pharma Phase 2 or 3 asset's next gate: the probability if it passes, nil if it fails, graded convention), and `gate` the gate's label ("Phase 3 readout", "Phase 2 readout", "FDA decision"; null for stated legs). A derived leg is priced only on the one catalyst that is the gate: the earliest pending readout of a study at the gate's phase, of this asset, in an indication the forecast values, or at the FDA decision a first-approval PDUFA in a modelled indication. Null with `na.stake` one of `no_asset`, `no_price`, `model_not_computed`, `not_modelled` (the asset has no modelled line), the engine's own reason for the catalyst (below), `no_gate` (a marketed product with no stated legs, where the engine returned nothing), or `not_in_stakes` (the engine returned nothing for this catalyst). |
| `asset_value` | The verdict's modelled line for the asset: `{per_share, pct_of_price, pos, counted}`. It is the risk-adjusted value of the whole asset, all indications, and is not a stake. Null with `na.asset_value` `no_asset`, `no_price` or `not_modelled` (`model_not_computed` while the verdict is missing). |

The shape of `stake`, with the one priced catalyst the book holds (CRSP, Casgevy, Phase 3 readout
estimated 2027-11-14, which falls outside the window today, so no company has a stake inside 12
months on this book):

```json
"stake": {"per_share": 4.204132, "pct_of_price": 0.077725, "pos_now": 0.8075,
          "pos_success": 0.95, "pos_failure": 0.4, "economics_share": 0.4}
```

LLY's first item: `{"id": 7, "date": "2026-10", "date_precision": "month", "date_confidence":
"month", "kind": "data readout", "phase": "Phase 3", "asset": {"id": 1492, "name":
"Retatrutide", "is_marketed": false}, "indication": {"id": 1, "name": "Diabetes Mellitus, Type
2"}, "stake": null, "asset_value": {"per_share": 33.777736, "pct_of_price": 0.028510, "pos":
0.875, "counted": true}, "na": {"stake": "no_gate"}}` as first built; with derived legs the
item's study (NCT06662383, TRIUMPH-1) is Retatrutide's gate and it carries a derived stake.
VKTX's VK2735 readout (estimated
2027-07-01) carries `asset_value` 24.090413 a share, 0.729349 of a 33.03 price, PoS 0.557. CRSP
has no catalyst in the window (`total: 0`).

#### Competition

Covered only where the landscape and the pool model reach: the company's id is in
`landscape._big_pharma_ids(conn)` (the pharma engine, 18 companies, VRTX among them). Otherwise

```json
"competition": {"covered": false, "reason": "not_big_pharma", "ranked_by": null,
                "total": 0, "valued": 0, "indications": []}
```

`reason` is `"no_indications"` for a big pharma company that appears in no entry of
`landscape.indications()`.

Steps for a covered company:

1. **The company's indications.** Entries of `landscape.indications(db_path)` whose `tickers`
   hold the company, grouped by `pool_crowding.group_of`, so one population written under
   several names is one row ("Obesity" stands for Obesity, Overweight, Weight Loss and Obesity,
   Morbid). The row's indication is the group's most contested entry (companies, then assets,
   then lowest id); its `members` are `landscape._members`. `total` counts groups.
2. **Value attribution.** The model values assets, not asset-indication pairs. A modelled
   asset is a verdict `modelled` line with a `per_share` and `counted` true (all of AZN's 54 and
   LLY's 34 are). Its `per_share` counts in every group the model sizes it in (an `assumptions` row with
   that `indication_id`); an asset the model sizes nowhere (a marketed product valued off
   reported revenue) counts in its lead indication: the `asset_indications` row with
   `is_lead = 1` of the asset, else of its `molecule_id`. An asset with neither counts nowhere.
   AZN: 35 of 54 lines land in a listed group, $70.71 of $102.89 a share. LLY: 31 of 34,
   $341.73 of $347.18.
3. **Ranking.** Groups by attributed value, largest first (`ranked_by: "model_value"`); ties by
   companies, assets, name. `valued` counts groups with value. With no modelled line
   (`not_modelled`, `not_computed`), `ranked_by` is `"contest"`: the landscape's own order, and
   every `value` is null with its reason. The first five groups are returned.
4. **Detail for the five.** `landscape.candidates`, `_pharmacology`, `on_label` and
   `compound_groups`, so one compound is one row and the counts are the landscape's own:
   `own.n + rivals.n` equals `coverage.candidates` of `GET /indications/{id}/landscape`. Stage
   buckets follow the landscape's stage text: `marketed` (marketed and on label here, or with no
   phase here), `phase3` (Phase 3 and Phase 2/3, including a drug sold for something else and
   trialled here), `phase2`, `other`.
5. **Pool.** `landscape._pool(conn, members)` and `pool_crowding.claimants`. Shares are stated
   only where a standing pool is shared:

   | Condition | Result |
   |---|---|
   | no claimant draws on the population | `pool: null`, `na.pool = "no_pool"` |
   | fewer than two pooled claimants | `crowding: null`, `na.crowding = "single_claimant"` |
   | pool size 0 (the model sizes the disease by each year's new patients, as for every cancer line) | `na.crowding = "flow_pool"` |
   | `uncrowded_share` over 1 (the claims exceed the stated population) | `na.crowding = "claims_exceed_pool"` |
   | `uncrowded_share` under 0.01 | `na.crowding = "share_under_1pct"` |
   | otherwise | `crowding = {uncrowded_share, crowded_share, kept, peak_year}`, `kept = crowded_share / uncrowded_share` |

   `company_pool` is stated with `crowding` when the company has a pooled claimant (else
   `na.company_pool = "no_claimant"`). Over pooled claimants only, each at its own peak year:
   `keeps` = the company's crowded peak starts over its uncrowded peak starts; `share_of_claims`
   = the company's crowded peak starts over all pooled claimants' (the shares of all companies
   sum to 1); `share_of_pool` = the company's crowded peak starts over `pool.patients`; `rank`
   among `of_companies` by `share_of_claims`; `leader`. Claimants are assets with a patient-based
   model, so marketed products valued off reported revenue are not in the pool figures.

AZN, row 4, in full:

```json
{
  "indication": {"id": 367, "name": "Obesity",
                 "members": ["Obesity", "Overweight", "Weight Loss", "Obesity, Morbid"]},
  "value": {"per_share": 8.522363, "pct_of_price": 0.051293, "assets": 2},
  "own": {"n": 3, "by_stage": {"marketed": 0, "phase3": 2, "phase2": 1, "other": 0},
          "candidates": [
            {"name": "Elecoglipron", "stage": "phase3", "phase_here": "Phase 3", "is_marketed": false,
             "asset_ids": [1744], "per_share": 4.727080, "attributed": true},
            {"name": "AZD6234", "stage": "phase3", "phase_here": "Phase 3", "is_marketed": false,
             "asset_ids": [1733], "per_share": 3.795283, "attributed": true},
            {"name": "Pramlintide", "stage": "phase2", "phase_here": "Phase 2", "is_marketed": true,
             "asset_ids": [524], "per_share": null, "attributed": false}],
          "more": 0},
  "rivals": {"n": 29, "companies": 8, "by_stage": {"marketed": 4, "phase3": 12, "phase2": 13, "other": 0}},
  "pool": {"patients": 107592242.0, "claimants": 19, "pooled_claimants": 19, "companies": 9},
  "crowding": {"uncrowded_share": 0.577292, "crowded_share": 0.420267, "kept": 0.727997, "peak_year": 2054},
  "company_pool": {"claimants": 2, "keeps": 0.726830, "share_of_claims": 0.119065, "share_of_pool": 0.050039,
                   "rank": 4, "of_companies": 9, "leader": {"ticker": "NVO", "share_of_claims": 0.257987}},
  "na": {}
}
```

`own.candidates` holds at most five, by attributed value then stage then name; `more` counts the
rest. A candidate's `per_share` sums its compound's attributed assets and is null, with
`attributed: false`, when none is attributed here.

The five rows, AZN and LLY:

| Company | Indication (id) | Value, $ a share | Of price | Own: marketed / Phase 3 / Phase 2 / other | Rivals (companies): same split | Pool | Company in the pool |
|---|---|---|---|---|---|---|---|
| AZN | Carcinoma, Non-Small-Cell Lung (20) | 21.33 | 12.8% | 13: 6 / 6 / 1 / 0 | 78 (14): 26 / 34 / 18 / 0 | 15 claimants, `flow_pool` | null |
| AZN | Breast Neoplasms (371) | 14.32 | 8.6% | 11: 8 / 2 / 0 / 1 | 60 (13): 21 / 21 / 16 / 2 | 48,000 patients, `claims_exceed_pool` | null |
| AZN | Asthma (75) | 9.84 | 5.9% | 10: 6 / 0 / 3 / 1 | 22 (8): 7 / 8 / 4 / 3 | 644,112 patients, 2 claimants, 4.7% claimed, 4.6% supplied, 2052 | `no_claimant` |
| AZN | Obesity (367) | 8.52 | 5.1% | 3: 0 / 2 / 1 / 0 | 29 (8): 4 / 12 / 13 / 0 | 107.6m patients, 19 claimants from 9 companies, 57.7% claimed, 42.0% supplied, 2054 | 2 claimants keep 72.7%; 11.9% of claims, 4th of 9; leader NVO 25.8% |
| AZN | Pulmonary Disease, Chronic Obstructive (122) | 6.83 | 4.1% | 9: 4 / 3 / 1 / 1 | 22 (8): 6 / 7 / 3 / 6 | 7 claimants, `flow_pool` | null |
| LLY | Obesity (367) | 294.31 | 24.8% | 9: 2 / 3 / 4 / 0 | 23 (8): 2 / 11 / 10 / 0 | as above | 4 claimants keep 73.3%; 23.2% of claims, 2nd of 9; leader NVO 25.8% |
| LLY | Breast Neoplasms (371) | 14.83 | 1.3% | 3: 2 / 1 / 0 / 0 | 68 (13): 27 / 22 / 16 / 3 | `claims_exceed_pool` | null |
| LLY | Alzheimer Disease (36) | 7.41 | 0.6% | 2: 1 / 1 / 0 / 0 | 16 (9): 1 / 4 / 11 / 0 | 2.2m patients, 8 claimants (7 pooled, 5 companies), 17.7% claimed, 16.8% supplied, 2057 | `no_claimant` |
| LLY | Arthritis, Juvenile (43) | 6.66 | 0.6% | 2: 0 / 2 / 0 / 0 | 15 (8): 9 / 6 / 0 / 0 | `no_pool` | null |
| LLY | Leukemia, Lymphocytic, Chronic, B-Cell (2) | 5.14 | 0.4% | 1: 1 / 0 / 0 / 0 | 9 (6): 2 / 4 / 2 / 1 | `single_claimant` | null |

The book's lead flags decide two of these rows and are shown as the book holds them: Mounjaro's
lead indication is Obesity, so tirzepatide's $218.63 (both brands) sits in LLY's obesity row, and
Taltz's is Arthritis, Juvenile. A company with no model (BAYN) is ranked by contest: Heart
Failure first, every `value` null with `na.value = "not_modelled"`.

Reason codes of this payload, worded by `core.CONTEXT_NA_TEXT` (12.3): `no_asset`, `no_price`,
`not_modelled`, `model_not_computed`, `not_in_stakes`, `no_indication_link`,
`no_attributed_asset`, `no_pool`, `single_claimant`, `flow_pool`, `claims_exceed_pool`,
`share_under_1pct`, `no_claimant`, `not_big_pharma`, `no_indications`, and the stake engine's
own (`forecast_view.STAKE_REASONS`), in the order it tests them:

| Code | When |
|---|---|
| `no_gate` | No stated legs and the asset is outside the gate model: marketed, outside Phase 2 or 3, or not a big pharma asset. Replaces `no_outcome_legs`. |
| `no_forecast` | The asset has a gate but its forecast cannot be built. |
| `stated_elsewhere` | Stated legs are priced once per asset, on the catalyst naming a study their sources cite, else the earliest whose own asset id is the asset. Any other catalyst of the asset, including a readout that reaches it only through its study (Casgevy's NCT05329649 in children with sickle cell disease and NCT05477563, beside the cited NCT05356195), carries this code, and a stated resolve on it is refused. |
| `nil` | The model already holds the asset at nil. |
| `regulatory_not_gate` | A regulatory date where the next gate is a readout, an AdCom or EMA opinion, or a supplemental application. |
| `not_a_gate` | A catalyst kind the gate model does not price (conference, other). |
| `no_trial_link` | A readout that names no registry study of this asset. |
| `past_gate` | A readout on an asset already at the FDA decision, including a stated PoS that implies a filing. |
| `not_gate_phase` | A readout at a phase that does not decide the gate (a Phase 2 study of a Phase 3 asset). |
| `phase_ahead_of_book` | A Phase 3 readout on an asset the book holds at Phase 2. |
| `other_indication` | A study, or a filing, in an indication the forecast does not value. |
| `same_gate_later` | A later catalyst of the gate an earlier one already prices. |

The stake engine runs (when no cached stakes read is present) only where an in-window catalyst
belongs to an asset carrying both stated legs, or to a modelled pipeline line. The stakes read
is warmed before this one (`response_cache.COMPANY_READS`).

#### Performance and cache

| Path | Budget | Measured (reference prototype, backup book) |
|---|---|---|
| Response cache hit | under 20 ms | not measured here (a stored body) |
| Built with the group memo warm | under 300 ms | AZN 9 ms, LLY 8 to 24 ms, VRTX 4 ms |
| Built cold | under 3 s | AZN 1.6 to 2.0 s, VRTX 1.0 s, LLY 0.6 s after AZN, CRSP under 10 ms |
| Body | under 60 KB | AZN 29.7 KB, LLY 26.9 KB, CRSP 0.6 KB |

What keeps it there:

- **No cold book.** The verdict comes only from `response_cache.cached_json`, as the model block
  of 2.8 does. The module never calls `forecast_view.company_verdict`,
  `landscape.landscape` or `landscape._model_lines`: the first costs 2.4 s for AZN alone and
  the landscape's own path costs 27 s for lung cancer's thirteen companies. Only the focal
  company's verdict is needed, because rivals are counted, not valued.
- **Stakes.** `cached_json` of the stakes read when present. Otherwise
  `forecast_view.catalyst_stakes` is called only when an in-window catalyst of the company
  names an asset carrying both `pos_success` and `pos_failure` (one SQL check; true for no big
  pharma company on this book), since that is the only case in which it prices anything.
- **Group memo.** The trial scan inside `landscape.candidates` is the cost: 0.17 to 0.55 s a
  group. Step 4 and step 5 are memoised per group in a module dict keyed
  `(response_cache.stamp(), group_key)`, at most 256 entries, cleared when the stamp moves,
  written under a lock.
  Obesity, lung and breast are shared by most of the 18, so warming them all costs far less than
  18 cold builds.
- **Ranking is cheap.** Steps 1 to 3 are one call to `landscape.indications` (5 ms once
  `_big_pharma_ids` is memoised, 0.13 s before), two queries and one `_members` query a group:
  under 40 ms for AZN's 58 groups.
- **Registration.** `response_cache.COMPANY_READS` gains `"/companies/{t}/comps-context"` as its
  **last** entry, so each company's verdict is warm before its context is built. The route sets
  `x-cache-skip: 1` on an incomplete body. Nothing else in the cache changes.

Route in `main.py`: `@app.get("/companies/{ticker}/comps-context")`, 404 for an unknown ticker,
`JSONResponse` with the skip header when `complete` is false.

### 12.3 The `context` arg and `view.insight`

**Python to frame.** The wrapper gains `context` and `mode` (12.5, 12.9). In full mode Python
reads `GET /companies/{ticker}/comps-context` for the app-wide company and passes the body; when
the read fails it passes `{"ticker": T, "error": "{message}"}`. The frame also receives
`context_digest` (twelve hex characters, as for the payload).

**Frame.** `shell.js` keeps the contexts it has received in a `Map` keyed by ticker (at most 12,
oldest dropped) and calls `core.deriveView(payload, state, {context, mode})` with the entry for
`state.focal`, or null. The view is rebuilt when the digest changes. A focal change made inside
the frame re-renders at once from client data: the conclusion, the key figures, the table and
the metric-linked observations are for the new company, the two evidence groups show the pending
state (or the cached context of a company seen before), and the context of the previous company
is never shown. The round trip of 7.5 then delivers the new one.

`insight.state`: `"pending"` when the context is null or `context.ticker !== state.focal`;
`"error"` when it carries `error` or `context.schema !== CONTEXT_SCHEMA`; else `"ok"`.

```ts
view.insight = {
  ticker: string, state: "ok" | "pending" | "error", message: StateMsg | null,
  valuation: {premium: InsightItem[], discount: InsightItem[], notAssessed: string[]},
  catalysts: {state: "ok" | "empty" | "pending" | "error",
              title: "Catalysts ahead", countText: string,      // "36 in 12 months, 24 assets"
              rows: CatalystRow[], note: string, empty: StateMsg | null,
              link: Link, linkLabel: "Open the Catalysts tab"},
  competition: {state: "ok" | "empty" | "not_covered" | "pending" | "error",
                title: "Competition by indication", countText: string,   // "5 of 19 valued indications"
                rows: CompetitionRow[], note: string, empty: StateMsg | null,
                link: Link | null, linkLabel: "Open Comps, Indications"}
}
InsightItem = {id: string, kind: "metric" | "catalyst" | "competition", side: "premium" | "discount",
               text: string, tag: string, strength: number, severity: "info" | "amber" | "red",
               provenance: "C" | "M", twoSided: boolean, chips: Chip[], link: Link, linkLabel: string}
Link = {kind: "column", colId: string}
     | {kind: "tab", tab: "Catalysts" | "Forecast"}
     | {kind: "indication", indicationId: number, name: string}
CatalystRow = {id: string,                       // "cat-{catalyst id of the event shown}"
               assetId: number | null, tier: 0 | 1 | 2 | 3 | 4,
               dateIso: string, dateShort: string, dateText: string, estimated: boolean,
               label: string, indicationText: string | null, moreText: string | null,
               modelText: string | null, modelKind: "stake" | "asset_value" | null, naText: string | null,
               side: "discount" | null, chips: Chip[], link: Link, sourceUrl: string | null,
               tooltip: string[]}
CompetitionRow = {id: string,                    // "ind-{indication id}"
                  indicationId: number, name: string, storedName: string,
                  valueText: string | null, valueNa: string | null,     // "$8.52 · 5.1%"
                  own: StageCounts, rivals: StageCounts & {companies: number},
                  ownText: string, rivalsText: string,
                  poolText: string | null, poolNa: string | null,       // "58% → 42%"
                  shareText: string | null, shareNa: string | null,     // "12%, 4th of 9"
                  side: "premium" | "discount" | "both" | null,
                  provenance: "M" | "S", link: Link, tooltip: string[]}
StageCounts = {n: number, marketed: number, phase3: number, phase2: number, other: number}
```

`view.observations` (3.10) is unchanged and still feeds the banner's support, "Look next" and
"Why?". `view.insight.valuation` is what the panel draws: the 3.10 observations as `InsightItem`
(`kind: "metric"`, `text` = `long`, `link = {kind: "column", colId}`, `linkLabel` = the column
label, chip "Model output" for provenance M), followed by the items the context supports. Items
from catalysts and competition never enter `support`, `supportShort` or `lookNext`.
`view.insight` is null in bridge mode.

**Order in a side list.** Metric items by strength, at most five shown; then the catalyst item;
then competition items in row order. Context items are always shown.

#### Rules that put a context fact on a side

A fact takes a side only under one of four rules. Everything else is evidence in its group with
no side. A catalyst is two-sided and says so.

| id | Side | Fires when | `tag` |
|---|---|---|---|
| `catalyst_stake` | discount, `twoSided` | the largest `stake.pct_of_price` among the items is `CATALYST_MIN_PCT` or more | "binary catalyst in 12 months (model)" |
| `catalyst_value` | discount, `twoSided` | `catalyst_stake` did not fire; among items that are regulatory or a readout in a late phase, on an asset that is not marketed and whose `asset_value.counted` is true, the largest `asset_value.pct_of_price` is `CATALYST_MIN_PCT` or more. The asset's earliest such event is the one named | "pipeline value on one event (model)" |
| `pool_rationed:{indicationId}` | discount | the row has `crowding` and `company_pool`, `company_pool.keeps ≤ POOL_KEEP_MAX` and `value.pct_of_price ≥ COMPETITION_MIN_PCT` | "shared patient pool (model)" |
| `pool_lead:{indicationId}` | premium | the row has `crowding` and `company_pool`, `rank === 1`, `of_companies ≥ POOL_LEAD_MIN_COMPANIES`, `share_of_claims ≥ POOL_LEAD_MIN_SHARE` and `value.pct_of_price ≥ COMPETITION_MIN_PCT` | "largest share of a shared pool (model)" |

All four carry provenance M, severity `amber` on the discount side and `info` on the premium
side, and strength 50. One row can yield both pool items (`side: "both"` on the row). When a
catalyst rule fires, the 3.10 observation `binary_catalysts` is left out of
`insight.valuation.discount` (it stays in `view.observations`): the specific statement replaces
the count.

Sentences (`text`). Share of price with one decimal, pool shares as whole percents, money as
`$` and two decimals, patients as "107.6m" from a million, "644k" from a thousand.

| id | Template | Real instance |
|---|---|---|
| `catalyst_stake` | "{pct} of the price, {ps} a share, separates success from failure at the {asset} {event} due {date}. The outcome can move the value either way. Model output." | none inside 12 months on this book. CRSP's Casgevy readout would read "7.8% of the price, $4.20 a share, separates success from failure at the Casgevy Phase 3 readout due around 14 Nov 2027. …" were it in the window |
| `catalyst_value` | "{pct} of the price, {ps} a share, is the risk-adjusted value the model carries for {asset}, whose {event} is due {date}. The outcome can move it either way. Model output." | VKTX: "72.9% of the price, $24.09 a share, is the risk-adjusted value the model carries for VK2735, whose Phase 3 readout is due around 1 Jul 2027. The outcome can move it either way. Model output." AMGN fires at 5.4% (Maridebart Cafraglutide, around 21 Jan 2027). AZN (Elecoglipron, 2.8%) and LLY (Retatrutide, 2.9%) do not |
| `pool_rationed` | "{keeps} of their own forecast is what {T}'s {k} modelled {indication} {candidate \| candidates} keep once {n} modelled drugs share one pool of {patients} patients. Model output." | AZN: "73% of their own forecast is what AZN's 2 modelled obesity candidates keep once 19 modelled drugs share one pool of 107.6m patients. Model output." LLY: the same with "LLY's 4" |
| `pool_lead` | "{share} of the patients the modelled drugs start in {indication} go to {T}'s {k} {candidate \| candidates}, the largest share of {c} companies. Model output." | NVO: "26% of the patients the modelled drugs start in obesity go to NVO's 4 candidates, the largest share of 9 companies. Model output." LLY holds 23%, second, so it does not fire |

Links, one per item. Metric items: the table column (`{kind: "column", colId}`). Catalyst
items and catalyst rows: the Catalysts tab (`{kind: "tab", tab: "Catalysts"}`, `linkLabel`
"Catalysts tab"). Pool items and competition rows: Comps, Indications with the indication
selected (`{kind: "indication", indicationId, name}`, `linkLabel` "{indication title},
landscape"). The Forecast tab is reached from KPI 6, the palette command `forecast.open` and the
side panel's "Open in Forecast tab" (12.5). Chips: "Model output" on all four context rules;
"Two-sided" on the two catalyst items.

`indicationTitle(name)`: the stored MeSH name with its comma-separated parts reversed, lower
case, first letter capital ("Carcinoma, Non-Small-Cell Lung" → "Non-small-cell lung carcinoma",
"Pulmonary Disease, Chronic Obstructive" → "Chronic obstructive pulmonary disease").
`indicationProse(name)` is the same without the capital ("obesity"). The stored name is in the
row tooltip.

#### Catalysts ahead: rows

One row per asset (events with no asset are their own rows). A row shows its asset's
best-ranked event; `moreText` counts the rest ("and 3 more for this asset").

| Tier | An event is in it when | Order inside |
|---|---|---|
| 0 | it has a `stake` | `stake.pct_of_price` descending |
| 1 | it is regulatory | date |
| 2 | a late-phase readout on an asset that is not marketed and has an `asset_value` | `asset_value.pct_of_price` descending |
| 3 | any other late-phase readout | date |
| 4 | the rest | date |

Rows sort by tier, then the order inside, then catalyst id. The panel shows `INSIGHT_ROWS`, then
"Show {n} more". `countText`: "{total} in 12 months, {rows} assets".

| Field | Text |
|---|---|
| `label` | "{asset}: {event}". Event: "{phase} readout" for a data readout with a phase, "data readout" without; "PDUFA date"; "advisory committee"; "regulatory decision"; "EMA decision"; otherwise the stored type in lower case. No asset: the title cut at 60 characters. |
| `dateShort` | "4 Jun 2027" for a day, "Oct 2026" for a month, "Q4 2026", "H1 2027". `estimated` is true unless the confidence is `confirmed` or `stated`; the cell then adds a muted "est." |
| `dateText` (prose) | "on 1 Feb 2027" (confirmed or stated), "around 4 Jun 2027" (any other day), "in Oct 2026", "in Q4 2026", "in H1 2027" |
| `indicationText` | `indicationTitle` of the indication, or null |
| `modelText` | stake: "at stake $4.20 a share, 7.8% of price". Asset value of an asset that is not marketed: "$4.73 a share, 2.8% of price, PoS 55%". Otherwise null |
| `naText` | for a marketed asset: "Marketed product. The model states no value for this readout." Otherwise `CONTEXT_NA_TEXT[na.stake]` |
| `chips` | "Two-sided" (neutral) on every row; "Model output" when `modelText` is set; "Derived, estimated date" (flag tone) when not curated and estimated; "Curated" (neutral) when curated |
| `link` | `{kind: "tab", tab: "Catalysts"}` |
| `tooltip` | the full title; "Source: {nct_id or the URL's host}"; for an estimated date "The date is the trial's estimated primary completion." |

AZN's first five rows: Elecoglipron: Phase 3 readout, 4 Jun 2027 est., Obesity, "$4.73 a share,
2.8% of price, PoS 55%"; AZD0780: Phase 3 readout, 4 Jan 2027 est., no indication, "$0.87 a
share, 0.5% of price, PoS 56%", and 1 more; Balcinrenone/dapagliflozin: Phase 3 readout, 16 Apr
2027 est., Heart failure; Imfinzi: Phase 3 readout, 30 Sep 2026 est., Hepatocellular carcinoma,
marketed, and 3 more; Datroway: Phase 3 readout, 30 Sep 2026 est., Non-small-cell lung
carcinoma, and 2 more. `countText`: "36 in 12 months, 24 assets". LLY: "33 in 12 months, 16
assets", first row Retatrutide: Phase 3 readout, Oct 2026, Type 2 diabetes mellitus, "$33.78 a
share, 2.9% of price, PoS 88%", and 3 more.

`note`: "Dates marked est. come from trial records. A catalyst is two-sided: it can raise or
lower the value. Value figures are model output."

#### Competition by indication: rows

One row per returned indication, in payload order.

| Field | Text | AZN, obesity |
|---|---|---|
| `name` | `indicationTitle` | "Obesity" |
| `valueText` | "${per_share} · {pct}", the company's attributed modelled value a share and its share of price; null with `valueNa` | "$8.52 · 5.1%" |
| `ownText` | "{n} own: {marketed} marketed, {phase3} Phase 3, {phase2} Phase 2, {other} earlier", zero parts left out | "3 own: 2 Phase 3, 1 Phase 2" |
| `rivalsText` | "{n} rivals from {companies} companies: …" in the same form | "29 rivals from 8 companies: 4 marketed, 12 Phase 3, 13 Phase 2" |
| `poolText` | "{uncrowded} → {crowded}": the pool claimed when each drug is modelled alone, then what one pool supplies. Null with `poolNa` = the reason | "58% → 42%" |
| `shareText` | "{share_of_claims}, {rank ordinal} of {of_companies}". Null with `shareNa` | "12%, 4th of 9" |
| `tooltip` | the stored name and members; "{n} modelled drugs from {c} companies claim {u} of {patients} patients at the {year} peak. Counted once, the pool supplies {c}."; "{T}'s {k} keep {keeps} of their own forecasts and {share_of_pool} of the pool."; the own candidates with stage and value | |
| `link` | `{kind: "indication", indicationId, name}` | id 367 |
| `provenance` | M when a value, pool or share text is set, else S | M |

`countText`: "{rows} of {valued} valued indications" ("5 of 19 valued indications" for AZN, "5 of
22" for LLY); ranked by contest: "{rows} of {total} indications, by contest". Column headings:
"Indication", "{T} value, $ a share · of price", "Own / rivals", "Pool claimed → supplied",
"{T} share". The `link` of the group is the first row's. `note`: "Rivals are big pharma
candidates that are marketed or in Phase 2 or later. Value counts each modelled asset in the
indication the model sizes it in, else in its lead indication. Pool figures are model output and
leave out marketed products valued off reported revenue."

#### States and copy

`core.CONTEXT_NA_TEXT`:

| Code | Copy |
|---|---|
| `no_asset` | "The event names no asset on file." |
| `no_price` | "No share price on file." |
| `not_modelled` | "No modelled value for this asset." |
| `model_not_computed` | "The model value has not been computed yet. Reload in a minute." |
| `no_gate` | "No gate is modelled for this asset, so no value at stake is stated." |
| `not_in_stakes` | "The stake engine has no figure for this event, so no value at stake is stated." |
| `no_forecast` | "The asset's forecast cannot be built yet, so no value at stake is stated." |
| `stated_elsewhere` | "The analyst's stated outcome is priced on another event of this asset." |
| `nil` | "The model holds this asset at nil, so nothing is left at stake." |
| `regulatory_not_gate` | "This regulatory event is not the gate the model prices." |
| `not_a_gate` | "This kind of event is not a gate the model prices." |
| `no_trial_link` | "The event names no study of this asset, so it cannot be tied to its gate." |
| `past_gate` | "The asset is already at the FDA decision, so this readout is past its gate." |
| `not_gate_phase` | "A readout at this phase does not decide the asset's next gate." |
| `phase_ahead_of_book` | "The model holds this asset at Phase 2, so a Phase 3 readout is ahead of its gate." |
| `other_indication` | "The study is in an indication the model does not value." |
| `same_gate_later` | "An earlier event decides the same gate, so this one is not priced twice." |
| `no_indication_link` | "No indication on file for this event." |
| `no_attributed_asset` | "No modelled asset is counted in this indication." |
| `no_pool` | "No modelled drug draws on a sized patient pool here." |
| `single_claimant` | "One modelled drug draws on this pool, so nothing is shared." |
| `flow_pool` | "The model sizes this disease by each year's new patients, so there is no standing pool to share." |
| `claims_exceed_pool` | "The modelled claims exceed the stated population, so no share of the pool is stated." |
| `share_under_1pct` | "The modelled drugs together claim under 1% of the pool." |
| `no_claimant` | "{T} has no modelled drug in the shared pool." |

State catalogue additions (section 8 form; `where` is the two evidence groups unless stated):

| State | Trigger | Copy |
|---|---|---|
| Context pending | `insight.state === "pending"` | "Loading catalysts and competition for {T}" / "They arrive with the page once the company changes." Severity info, skeleton rows under it |
| Context error | `insight.state === "error"` | "Catalysts and competition did not load" / "The API did not answer /companies/{T}/comps-context ({error}). Reload with the reload button." Severity amber. A schema mismatch uses the section 8 copy "This view is out of date" |
| No catalysts | `catalysts.total === 0` (CRSP) | "No dated catalysts in the next 12 months" / "No pending catalyst for {T} is dated between {from} and {to}. The Catalysts tab lists later events." |
| Competition not covered | `competition.covered === false`, `not_big_pharma` (CRSP, VKTX) | "Competition by indication is not covered for {T}" / "The indication landscape and the pool model cover the {n} big pharma companies. {T} is read on the {engine label} engine, so no rival counts or pool shares are stated." `{n}` is `payload.universe.engines.pharma` |
| No indications | `no_indications` | "No indication to compare for {T}" / "No {T} candidate that is marketed or in Phase 2 or later is linked to an indication in the landscape." |
| Ranked by contest | `ranked_by === "contest"` (BAYN) | line above the rows: "No modelled value for {T}, so indications are ordered by how many companies contest them." |
| Model not computed | `complete === false` | line above both groups: `CONTEXT_NA_TEXT.model_not_computed` |

### 12.4 Drivers and risks panel (`mountObservations`)

Replaces 6.1. Signature unchanged: `mountObservations(root, ctx) -> {update(view), destroy()}`.
It draws `view.insight`; with `view.insight` null it draws the section error state.

- Title row: "Drivers and risks", the chip "Observations, not conclusions".
- `.pn-obs-sides` and `.pn-obs-evidence`: the two rows of 12.1 (`.pn-obs-premium`,
  `.pn-obs-discount`; `.pn-obs-catalysts`, `.pn-obs-competition`). At `narrow` the two groups sit under one tab
  strip (`ui.insightTab`, action `SET_INSIGHT_TAB {tab: "catalysts" | "competition"}`).
- Side lists: headings "Potential premium drivers" (`▲` in `up`) and "Potential discount drivers"
  (`▼` in `down`). An item is a three-column grid: glyph, sentence (13/18), link chip at the
  right (`linkLabel` and `→`, accessible name "{linkLabel}: open"). Chips "Model output" and
  "Two-sided" follow the sentence. Empty side: "No observation passes the tests." The
  `notAssessed` lines stay under a hairline, muted, below the grid.
- Catalysts group: heading row (title, `countText`, and at the right the link button
  `linkLabel`). Rows are a grid `88px minmax(0, 1fr) 196px 20px`: `dateShort` (mono, "est."
  muted), `label` with `indicationText` after a middle dot in muted text and `moreText`, the
  model cell (mono, right aligned, `M` marker, or a muted `—` whose tooltip is `naText`), and a
  source button `↗` that opens `sourceUrl` in a new tab. The row is a button: click or Enter
  runs `ctx.openLink(row.link)`.
- Competition group: heading row with the five column headings of 12.3. Rows are a grid
  `minmax(120px, 1fr) 112px 100px 92px 92px`: name; `valueText`; "{own.n} / {rivals.n}" over a
  four-segment bar of the rivals by stage (marketed, Phase 3, Phase 2, earlier), with `ownText`
  and `rivalsText` as the cell's tooltip and accessible text; `poolText`; `shareText`. Text
  cells cut with an ellipsis; the row tooltip carries the full text. A null cell is the `—` glyph with its
  reason in the tooltip. A row whose `side` is set carries `▲`, `▼` or both before the name. The
  row is a button running `ctx.openLink(row.link)`.
- Both groups: `INSIGHT_ROWS` rows, then a link row "Show {n} more" (expands in place), and the
  `note` as the group's tooltip on an info button. State blocks of 12.3 replace the rows.
- Every link goes through `ctx.openLink(link)` (12.9). Nothing in the panel words a fact: all
  strings come from `view.insight`.

### 12.5 Bridge-only mode and the Forecast tab (R3.3)

**Wrapper.**

```python
def comps_valuation(payload, *, focal, engine, tokens, live,
                    context=None, mode="full", height=None, key=None)
```

`mode` is `"full"` or `"bridge"` (anything else raises `ValueError`). Defaults: `key`
`"compsval"` and `height` 900 in full mode, `"compsval_bridge"` and 360 in bridge mode. In
bridge mode the wrapper drops the `detail` record of every company before the digest (545 KB
against 926 KB on the live payload) and sends `context=None`. Args sent: `payload`, `digest`,
`focal`, `engine`, `tokens`, `live`, `shared_css`, `height`, `mode`, `context`,
`context_digest`. The bridge frame never calls `setComponentValue`.

**What the shell renders** with `mode === "bridge"` (`#app[data-mode="bridge"]`):

1. One context line, `view.bridgeLine = {text, linkLabel}`: "{T} against {set full}: peer {stat
   word} {metric label} of {M}, {k} of {n} peers with a value." AZN: "AZN against Big pharma,
   commercial, 17: peer median P/E (NTM) of 15.4×, 14 of 17 peers with a value." With the bridge
   disabled the line is "{T} against {set full}." and the reason of section 8 shows as a
   `.u-state` block in place of the chart.
2. The bridge chart (`mountBridgeChart`) and the inputs (`mountBridgeInputs`), the 5.3 content
   unchanged, in `.sh-bridge-body`: inputs `minmax(420px, 1fr)`, chart `minmax(360px, 1.1fr)`,
   gap 24; one column when the frame is under 900 px wide. `mountBridgeInputs` leaves out its
   own section title when `ctx.mode === "bridge"` (Streamlit draws the heading).
3. One closing line: the button "Change peers or metric in Comps" (`clickParentTab("Comps")`),
   then "Peer set and inputs are saved in this browser only."

Nothing else is built: no context bar, banner, KPI strip, scope line, table, charts, drivers,
drawers, palette, help or single-key handler. The shared tooltip, menu and live region stay.
`ctx` is the same object; `openDetail`, `openPeers` and `openMethod` are no-ops.

**Frame sizing.** The bridge is an ordinary block in the Forecast tab's flow, not fitted to the
viewport. `html, body { height: auto }`, `#app { display: block }`, no scroll container.
`fitFrame` is not used. A `ResizeObserver` on `#app` calls
`Streamlit.setFrameHeight(bridgeFrameHeight(contentHeight))` =
`max(200, ceil(contentHeight))`, only when it moves by 2 px or more. The first height is the
`height` arg.

**Storage.** Both frames are same-origin and use the same `STORAGE_KEY` and `SESSION_KEY`, so
the bridge reads the peer set, exclusions, period, basis and bridge inputs chosen in Comps.

- Each frame listens for `storage` events on either key, and re-reads on `visibilitychange`
  to visible. It then dispatches `ADOPT_PERSISTED {local, session}`: the reducer replaces every
  persisted slice with `migrateState(local)` and the focal's exclusions from `session`, and keeps
  `focal`, `engine`, `live` and `ui`. A frame ignores an event whose `newValue` is what it last
  wrote.
- The bridge frame writes only bridge inputs: `mergeBridge(storedLocal, focal, inputs)` reads
  the stored blob, replaces `bridge[focal]` and writes it back. It never writes its whole state,
  so a bridge frame left open cannot put back a peer set that Comps has since changed.

**Comps side.** KPI 6 keeps its label, value and compare line. Its tooltip becomes "From the
peer-multiple bridge on the Forecast tab, with its inputs. Click to open it. Per-share figures
are in USD, the quote currency." The cell is a button with `kpis[5].link = {kind: "tab", tab:
"Forecast"}`: `ctx.openForecastBridge()` writes `sessionStorage[GOTO_KEY] = JSON.stringify({target:
"bridge", at: Date.now()})` and clicks the parent's "Forecast" tab. The bridge frame, on that
`storage` event (or on finding a flag under 5 s old when it renders), removes the flag and,
once its `innerWidth` is over 0, calls `window.frameElement.scrollIntoView({block: "center"})`
inside try/catch. The `bridge.reset` command leaves `COMMANDS`; "Reset to sourced" in the inputs
does that job.

**Placement on the Forecast tab.** A new helper in `streamlit_app.py`:

```python
def _peer_value_section(api_base: str, ticker: str) -> None:
    section("Value implied by peer multiples", basis="peer set and metric from Comps · $ a share")
    # payload from _comps_valuation_payload(api_base); on failure:
    # state("Peer multiples unavailable", "The API did not answer on /comps/valuation: {error}.", error=True)
    compsval.comps_valuation(payload, focal=ticker, engine=st.session_state.get("engine") or "",
                             tokens=COMPS_TOKENS, live=<as the Comps view>, mode="bridge")
```

It is called exactly once per render of the tab:

1. in `_book`, directly after `_fair_value_range(api_base, ticker)` and before `_ira_strip`: the
   peer-multiple value sits under the lenses it is one more of;
2. in `_book`'s early return for a company with no model, after the "No model for {ticker} yet"
   state and before `return v, None`;
3. in `_render_forecast_tab`'s `if not options:` branch, after the "No forecastable products"
   state and before `return`.

So every company has it, modelled or not. It is not drawn when the forecast or verdict read
itself failed.

### 12.6 Peer drawer, footer and the Basis menu (R3.4, R3.5)

**Peer drawer.** `mountPeerPanel(root, ctx)` keeps its signature and its content (6.2: warnings,
relevance table, candidates, saved sets, subgroups, cohort comparison, outliers, restore). It now
mounts in `.sh-peers` and renders nothing while `view.peers.open` is false.

- `aside.u-drawer.pn-peers`, `role="dialog"`, `aria-modal="false"`, labelled by its title "Edit
  peers", with the set label chip and a close button `✕` in its header.
- Width `min(760px, 100% − 56px)`; `narrow`: full width. Fixed from `--band-h` to the bottom of
  the frame, its body scrolls. The relevance table scrolls sideways inside its own box.
- State `ui.peers: boolean`. Actions `OPEN_PEERS {search?: boolean}` and `CLOSE_PEERS`.
  `ctx.openPeers({search})`, `ctx.closePeers()`.
- Focus: on open it moves to the title (`tabindex="-1"`), or to the search box when opened with
  `search: true`. Esc or close returns focus to the control that opened it (the pattern of
  `mountMethod`). Focus is not trapped; the table behind stays live, so excluding a peer in the
  drawer shows at once.
- Opened by: "Edit peers" and the counts item in the scope line; "Edit peers" in the peer set
  control's menu; `a` (`peer.add`, with `search: true`); the palette command `peers.edit`; the
  banner chips "Weak peer set" and "Mixed business models"; a "Look next" whose target is
  `peers`; the state action "Restore system peers" does not open it.
- One right-side surface at a time: `OPEN_PEERS` clears `ui.detail` and `ui.method`;
  `OPEN_DETAIL` and `OPEN_METHOD` clear `ui.peers`; `OPEN_METHOD` clears `ui.detail` and
  `OPEN_DETAIL` clears `ui.method`. Esc closes, in order: palette, help, menu, "Why?", selector,
  methodology drawer, peer drawer, side panel.

**Footer** (`.sh-foot`, shell, 28 px, 12/16 `muted`, one line, ellipsis). `view.footer = {text,
tone: "neutral" | "flag", buttonLabel: "Sources and method"}`. `text`: "Prices close {date} ·
consensus checked {date} · FX ECB {date} · refresh run {id}, {status} · saved in this browser
only", for example "Prices close 28 Sep 2026 · consensus checked 23 Sep 2026 · FX ECB 28 Sep
2026 · refresh run 123, partial · saved in this browser only". `tone` is `flag`, with `!`
before the text, under the rule that turns the "Data as of" chip amber (1.5). The button opens
the methodology drawer at the anchor `sources`.

**Methodology drawer.** Its first section is now "Sources" (anchor `sources`): the sources and
timestamps table, the analyst notes list and the storage line that `mountNotesSources` drew.
`mountNotesSources` is no longer mounted; `panels.js` keeps its builder as the body of that
section. The other sections of 6.3 follow unchanged.

**Basis menu.** The context bar's controls are, left to right: peer set, period, **Basis**,
"Data as of", reload, export, help. The data state and currency select and the earnings control
go.

- `view.header.basis = {text, nonDefault: boolean, tooltip}`. `text` is "Basis" when the
  currency is USD and earnings are GAAP/IFRS. Otherwise it names each choice that is not the
  default, comma separated: "Basis: EUR", "Basis: as reported", "Basis: ex amort.", "Basis: EUR,
  ex amort.". A chip that is not default has an `active` border. Width 64 px at the default, up
  to 172. `tooltip` is the basis text of 2.2 for the choices in force.
- The menu (shared menu, `kind: "head"` groups): "Currency and data state" with the six radio
  items of 1.5 ("Standardised, USD" to "As reported, filing currency"); "Earnings" with
  "GAAP/IFRS" and "Ex amort. and IPR&D"; when not default, "Reset to USD and GAAP/IFRS"; a note
  line with `basis_text.street` on forward bases.
- `y` and `g` keep working and announce the change. The collapse steps of 1.5 lose step 3; the
  Basis chip is never hidden. `view.ctx.dataState` and the rule of 1.5 for it are unchanged.

### 12.7 Table toolbar, presets and flag markers (R3.6)

**Toolbar** (32 px), left to right, nothing else:

1. "Columns: {preset} ▾": the preset menu of 4.5, keys `1` to `7`.
2. "Find column" with its `f` hint.
3. "View ▾": one shared menu, with `view.table.viewBadge = {count, lines}`. The button reads
   "View", or "View · {count}" when `count` is over 0; `lines` go in its tooltip.
4. The "{n} hidden ▾" chip, only while columns are hidden.

The View menu, in this order, each group under a `kind: "head"` item (`max-height: min(70vh,
560px)`, own scroll):

| Group | Items | Counts towards the badge when |
|---|---|---|
| "Statistics over" | "All included peers"; each subgroup with its count (radio) | not all peers ("Statistics over {group}") |
| "Outliers in statistics" | "Included", "Excluded" (radio, `u`) | excluded ("Outliers excluded") |
| "Conditional format" | the six modes of 4.9 (radio, `v`) | not off ("Format: {mode}") |
| "Density" | "Compact rows", "Default rows", "Comfortable rows" (radio, `d`) | not default |
| "Text size" | "Text 13 px", "Text 14 px", "Text 15 px" (radio, `+` and `-`) | not 13 |
| "Rows" | "Summary rows" (check); "Mean and quartiles in the summary" (check, `laptop` and `narrow`); "Pin the focal row" (check) | summary rows off |
| "Layouts" | "Save layout"; "Load {name}" and "Delete {name}" per saved layout; "Reset columns, widths and sort" (`shift+r`) | never |

Closing note: "Saved in this browser only." The "Layouts", "Statistics", "Outliers", "Format",
"Display" and "Below the table" buttons go; every action they held is in this menu, the palette
and its key.

**Presets.** Each built-in preset holds exactly `MAX_PRESET_COLUMNS` columns after the frozen
block. The primary column is still inserted when the preset lacks it (4.1), and every dropped
column stays reachable through Custom, the column finder and a Drivers and risks link.

| # | id | Columns kept | Dropped from 4.5 |
|---|---|---|---|
| 1 | `core` | `market_cap`, `ev`, `pe`, `ev_ebitda`, `ev_revenue`, `fcf_yield`, `price_to_book`, `pt_upside`, `revenue_growth` | `price_to_sales`, `peg` |
| 2 | `growth` | `revenue`, `revenue_growth`, `revenue_cagr3`, `ebitda_growth`, `eps_growth`, `gross_margin`, `operating_margin`, `net_margin`, `roic` | `ebitda_margin` |
| 3 | `balance` | `market_cap`, `net_debt`, `net_debt_ebitda`, `cash_to_mcap`, `runway_months`, `beta`, `vol_1y`, `est_dispersion`, `n_estimates` | `ttm_price_change` |
| 4 | `pharma` | `market_cap`, `pe`, `ev_ebitda`, `revenue_growth`, `operating_margin`, `loe_share_5y`, `rd_pct`, `late_trials`, `pipeline_ps` | `major_products`, `loe_unpriced_5y`, `revenue_per_late_trial` |
| 5 | `biotech` | `market_cap`, `ev_revenue`, `price_to_sales`, `mcap_to_cash`, `revenue_growth`, `runway_months`, `lead_phase`, `catalysts_12m`, `pt_upside` | `ev`, `gross_margin`, `operating_margin`, `late_trials` |
| 6 | `cellgene` | `market_cap`, `mcap_to_cash`, `runway_months`, `lead_phase`, `trial_concentration`, `late_trials`, `catalysts_12m`, `vol_1y`, `pt_upside` | `ev`, `beta` |
| 7 | `custom` | the analyst's list, uncapped | |

**Flag markers.** Two questions are now separate. `flagTouches` (3.4, unchanged) still says
which cells a flag reaches for the logic: the observation skip rule, the confidence points and
the n.m. rules read `cell.flags` as before. A new `flagMarks(flag, colId, key, rec)` says where
the flag bears on the printed value, and only that draws a marker.

- `Cell` gains `marks: string[]` (codes with `flagMarks` true). `cell.amber` and `cell.red` are
  computed from `marks`, and `cell.flagLines` holds the lines of `marks` only. So the `!`, the
  dotted underline and the cell tooltip appear only where the flag bears on that cell.
- `RowView` gains `tickerFlags: string[]` and `tickerLines: string[]`; `amberFlags` and the old
  row `flagLines` go. The `!` after a ticker shows only when `tickerFlags` is not empty.
- `DetailView` gains `flags: {code, severity, text, cells: string[]}[]`: every flag of the
  company with the column labels it marks. The side panel lists them under "Data flags", above
  "Data lineage". This is where everything else lives.

| Code | Cell marker on (`flagMarks`) | Was (`flagTouches`) | Ticker marker |
|---|---|---|---|
| `stale_price` | `price` | the same | no |
| `stale_consensus` | forward `pe`, `peg`, forward `eps_growth`, `eps_cagr`, `est_dispersion`, `n_estimates` | the same | costing |
| `stale_balance_sheet` | `ev`, `net_debt`, `price_to_book`, `cash_to_mcap`, `mcap_to_cash`, `roic` | the same | costing |
| `stale_fiscal_year` | none: it is a property of the row, shown in the detail panel | every FY0 cell | costing |
| `fiscal_year_end` | none, the same reason | every FY0, FY1 and FY2 cell | costing |
| `source_failed` | none | none | always |
| `fx_converted`, `ifrs_filer`, `non_sec_filer`, `market_cap_diluted_route`, `cover_count_exception`, `no_tagged_addbacks` | none (info; the market cap tooltip still names its route) | info | no |
| `currency_mismatch` | `revenue`, `net_debt`, `ev`, `revenue_per_late_trial`, `ev_per_late_trial` | the same | costing |
| `includes_minorities` | `pe` on FY0 and LTM, `net_margin`; or `price_to_book`, `roic` for the equity line | the same | costing |
| `stale_shares`, `market_cap_disagreement` | `market_cap` only | eleven market-cap dependants and `pe` on FY0 and LTM | costing |
| `derived_operating_income`, `derived_no_addback` | `operating_margin`, `ebitda_margin`, `ev_ebitda`, `net_debt_ebitda`, `roic` | the same | peer rule below |
| `no_consensus` | none: the forward cells read `—` with the reason | none | no |
| `thin_estimates` | FY3: `peg`, `eps_cagr`; FY2: forward `eps_growth`, `pe` on FY2; FY1: `pe` on FY1 | the same | costing |
| `estimate_range_wide` | `est_dispersion` only | also forward `pe` | costing, under the 3.11 condition (fewer than 5 estimates, or a range over 1.0) |
| `eps_sign_change` | none: the cells read n.m. with the reason | forward `pe`, `peg` | no |
| `guidance_fx_unstated` | `revenue_growth` and `ev_revenue` on FY1 | the same | costing |
| `burn_flattered` | `runway_months` | the same | no |
| `calc_failed` | every cell reads `—`; the row shows the red `✕` | the same | always (the `✕`, as now) |

A flag "costs confidence in the conclusion" when it took a point in `conclusion.confidence.points`
(3.11). So `tickerFlags` is:

- focal row: the codes `costingFlags` returns (amber flags reaching the focal's primary cell,
  marked "costing" above);
- peer row: `derived_operating_income` or `derived_no_addback` on the peer's primary cell while
  the derived-share penalty of 3.11 is in force; nothing else a peer carries costs a point;
- any row: `source_failed` for a `VIEW_SOURCES` source, and `calc_failed`.

Measured on the backup with the whole-cohort sets of 12.8 (18 rows each). AZN's view (pharma
preset, 216 numeric cells): 16 ticker markers become none, and 16 amber cells become 13, which
are the twelve EV/EBITDA and operating margin cells on derived operating income and one market
cap cell on a stale share count. CRSP's view (180 cells): 15 ticker markers become one (TSHA, a
failed consensus fetch), and 33 amber cells become 11, all in the market cap column where the
two share-count routes disagree.

### 12.8 Default peer set (R3.7)

Step 2 of `defaultPeers` (3.6) becomes:

> Pool A: same engine and same stage, ranked by score descending, then market cap, then ticker.
> When pool A holds `WHOLE_COHORT_MAX` (20) companies or fewer, all of it is the set: no
> relevance floor and no cap. Otherwise keep scores of `MIN_DEFAULT_RELEVANCE` or more, at most
> `MAX_DEFAULT_PEERS` (15).

Steps 3 to 6 are unchanged: a cohort under five is still padded from pools B and C and still
warns. `defaultPeers` also returns `whole: boolean`. The reason of a whole-cohort member under
the floor reads "Same subsector and stage, relevance {s}, under the usual floor of 40". The
peer set control's tooltip gains "Every {engine label} company at the {stage} stage. A cohort of
more than 20 is cut to the 15 most relevant." The weak-set and mixed-model states are unchanged
and still count appropriate peers at 40 or more.

Cohort sizes on this book, focal included: big pharma commercial 18, cell and gene clinical 18,
biotech commercial 14, biotech clinical 12, cell and gene commercial 8. Every cohort has 17 or
fewer other companies, so every one of the 70 companies now gets its whole cohort and the
15-company cut is dormant until a cohort holds more than 20 other companies.

| Focal | Before | After | Primary statistic | Premium | Implied value | Confidence |
|---|---|---|---|---|---|---|
| AZN | 15 (no BAYN at 64, no LLY at 59) | 17 | P/E NTM median 15.34× of 13 values → 15.36× of 14 (BAYN has no consensus) | +5.7% → +5.6% | $157.17 → $157.37 | high, unchanged |
| VRTX | 15 (no BAYN at 53, no LLY at 61) | 17 | 15.34× of 13 → 15.36× of 14 | +92.5% → +92.2% | $274.16 → $274.52 | high, unchanged |
| CRSP | 15 (no CRBU at 59, no KRRO at 58) | 17 | market cap / cash median 2.11× of 15 → 2.07× of 17 | +4.6% → +7.0% | $51.71 → $50.54 | medium → high |

The set label reads "Big pharma, commercial, 17" and the headline "the median of 14 big pharma
peers, 15.4×", which is the figure 1.6 and A.2 already quote. Stored `peerEdits` still apply on
top of the new system set; an `added` ticker that is now in the system set is dropped as a
duplicate.

### 12.9 Links and the Python round trips

`ctx.openLink(link) -> boolean` in `shell.js` is the one way a Drivers and risks item, a KPI or
a palette entry leaves the view.

| Link | What the frame does | Python |
|---|---|---|
| `{kind: "column", colId}` | `goToColumn(colId)`: scrolls `#main` to the table, shows the column (`SHOW_COLUMN` when the preset lacks it), focuses the focal cell, announces "Showing {column}" | none |
| `{kind: "tab", tab: "Catalysts"}` | clicks the parent's `button[data-baseweb="tab"]` whose label is "Catalysts" (`clickParentTab`, as `covnav` does). When the frame's focal differs from the `focal` arg it first sends the focus action of 7.5 | none beyond the focus action |
| `{kind: "tab", tab: "Forecast"}` | `openForecastBridge()` (12.5): the session flag, then the tab click | none |
| `{kind: "indication", indicationId, name}` | sends `{action: "indication", indication_id, ticker, nonce}` with `setComponentValue`, then clicks the parent's "Indications" tab. When that tab is absent (`clickParentTab` false: the company is not read on the big pharma engine) it announces "The Indications view opens for big pharma companies." and returns false | sets the landscape's picker |

Python hears three actions, the only ones: `focus` and `reload` (7.5), and `indication`.

- **Catalysts and Forecast** need no session state: the tabs exist for every engine and show
  the app-wide company, which is the focal company.
- **Indications.** The landscape's picker is the selectbox `key=f"land_pick_{ticker}"`, whose
  options are indication ids. A widget's key can be written only before the widget is created,
  so the write happens in a full run, ahead of the picker, as the focus hook does:
  - `_compsval_indication() -> int | None`: reads `st.session_state.get("compsval")`; when it is
    an `indication` action whose nonce is not `st.session_state["_compsval_ind_nonce"]`, returns
    the id.
  - In `_indication_landscape`, after `options` is built and before `st.selectbox`: when the id
    is in `options`, `st.session_state[f"land_pick_{ticker}"] = id`; the nonce is recorded
    either way, so an unknown id is dropped once. The `index=0` argument of the selectbox goes
    (it is the default, and a default beside a session value draws a warning).
  - In the `_comps_valuation_view` fragment: a new `indication` action calls `st.rerun()` (app
    scope), so the hook runs. The tab is already showing because the frame clicked it.
  - The action carries `ticker`, the frame's focal company. The frame sends one value at a
    time, so a link followed straight after a focal change made in the frame cannot send the
    focus action as well: `_compsval_focus()` therefore also returns the ticker of an unapplied
    `indication` action, and the page moves to that company before the picker is set.
- **Reload** clears `_comps_valuation_payload` and `_comps_context`.
- `_comps_context(api_base, ticker)`: `@st.cache_data(ttl=60, show_spinner=False)`, a direct
  read like the payload's, timeout 30 s. The fragment catches the failure and passes the error
  context of 12.3.

### 12.10 State, actions, commands and `View`: the diff

| Item | Change |
|---|---|
| `deriveView` | `deriveView(payload, state, extra = {})`, `extra = {context, mode}`. In bridge mode it builds `focal`, `ctx`, `bridge`, `bridgeLine`, `error` and leaves the rest null |
| `State.ui` | adds `peers: boolean` and `insightTab: "catalysts" \| "competition"`; drops `lowerTab`. `laptopTab` now serves `laptop`, `wide` and `ultrawide` |
| Actions added | `OPEN_PEERS {search?}`, `CLOSE_PEERS`, `SET_INSIGHT_TAB {tab}`, `ADOPT_PERSISTED {local, session}` |
| Actions removed | `SET_LOWER_TAB` |
| Reducer | the one-surface rule of 12.6 |
| `COMMANDS` added (palette only) | `peers.edit` "Edit peers", `sources.open` "Sources and method", `forecast.open` "Open the peer-multiple value on the Forecast tab", `catalysts.open` "Open the Catalysts tab" |
| `COMMANDS` changed | `peer.add` (`a`) opens the peer drawer at its search box |
| `COMMANDS` removed | `bridge.reset` |
| Palette entries | "Go to section" for the three sections of 12.1; "Open Comps, Indications: {name}" per competition row. "Reset bridge" and the old section entries go |
| `View` added | `insight` (12.3), `footer` (12.6), `bridgeLine` (12.5), `header.basis` (12.6), `table.viewBadge` (12.7), `peers.open`, `kpis[5].link`, `Cell.marks`, `RowView.tickerFlags` and `tickerLines`, `DetailView.flags`, `mode` |
| `View` removed | `RowView.amberFlags`, the row-level `flagLines` |
| Persisted state | version stays 1. No migration: new `ui` keys are session-only, preset ids are unchanged |
| `ctx` added | `openPeers(opts)`, `closePeers()`, `openLink(link)`, `openForecastBridge()`, `mode` |
| `PRESETS`, `defaultPeers`, `flagMarks`, `CONTEXT_NA_TEXT`, `indicationTitle`, `indicationProse`, `mergeBridge` | as 12.7, 12.8, 12.3, 12.5 |

### 12.11 File ownership and tests for this revision

Nobody edits another owner's files. Stub against this section where a dependency has not landed:
the context examples under `scratchpad/arch3/` have the exact shape of 12.2.

| Owner | Files | Builds |
|---|---|---|
| backend | `backend/comps_context.py`, the route in `backend/main.py`, `backend/response_cache.py`, `backend/tests/test_comps_context.py` | 12.2 |
| core | `frontend/components/compsval/core.js`, `frontend/tests/compsval/core.test.js`, `frontend/tests/compsval/fixture_*.json` (adds `fixture_context.json`: the AZN, LLY, NVO, VKTX, CRSP and BAYN bodies keyed by ticker, taken from `scratchpad/arch3/context_*.json` and regenerated from the endpoint once it answers) | 12.0 constants, 12.3, 12.7 presets and flag rules, 12.8, 12.10 |
| table | `table.js`, `table.css`, `frontend/tests/compsval/table.test.js` | 12.7 toolbar, View menu, markers |
| charts_panels | `charts.js`, `panels.js`, `charts.css`, `panels.css`, `frontend/tests/compsval/charts.test.js` | 12.1 strip at every width, 12.4, 12.5 mounts in bridge mode, 12.6 peer drawer and the Sources section |
| shell | `shell.js`, `shell.css`, `styles.css`, `index.html`, `frontend/tests/compsval/shell.test.js` | 12.1 layout, 12.5 bridge mode and storage, 12.6 footer and Basis, 12.9 `openLink`, the context map |
| wiring | `frontend/streamlit_app.py`, `frontend/components/compsval/__init__.py`, `backend/tests/test_comps_tab_ui.py` | 12.5 wrapper and placement, 12.9 |

Tests each owner adds. The existing suites stay green: `pytest tests/
--ignore=tests/test_refresh.py` and `node --test "frontend/tests/compsval/*.test.js"`.

**backend, `test_comps_context.py`** (logic tests build their own database; book guards take the
`book` fixture and are skipped without it):

1. Unknown ticker: `build` returns None; the route answers 404.
2. Window: rows dated `today` and `today + 365` are in, `today − 1` and `today + 366` are out,
   a `YYYY-MM` date inside the window is in; `total` equals the `screen._catalysts_12m` count on
   the same database when `today` is the real date.
3. Each field rule of 12.2: `date_precision`, `regulatory`, `nct_id`, the asset and phase from
   the trial row when `catalysts.asset_id` is null, the indication by `asset_indication_id` and
   by trial MeSH, and an `na` entry for every null.
4. Stake: an injected priced row gives `stake` with `pct_of_price = abs(per_share) / close`
   and its `basis` and `gate`; without it each of `no_asset`, `not_modelled`, `no_gate`,
   `not_in_stakes` and an injected engine reason is produced by its own case.
5. Never cold: with `verdict_for` returning None for a company with a book, `model.state` is
   `"not_computed"`, `complete` is false, and `forecast_view.company_verdict`,
   `landscape.landscape` and `landscape._model_lines` (patched to raise) are not called.
6. Not covered: a company outside the pharma engine gives `covered: false`, `not_big_pharma`,
   and `landscape.candidates` is not called.
7. Attribution: an asset with a model indication counts there; one without counts in its lead
   indication, its own then its molecule's; one with neither counts nowhere; rows rank by
   value; with no model `ranked_by` is `"contest"`.
8. Counts: `own.n + rivals.n` equals `len(landscape.landscape(...)["candidates"])` for the
   fixture indication, and the stage buckets follow the landscape's stage text.
9. Pool: each reason of the table in 12.2; `keeps`, `share_of_claims` (summing to 1 over
   companies), `share_of_pool` and `rank` on a two-company fixture.
10. Strict JSON (`json.dumps(allow_nan=False)`), and the module imports under Python 3.9.
11. Memo: a second build under the same stamp does not call `landscape.candidates`.
12. Route and cache: the skip header on an incomplete body; `COMPANY_READS[-1]` is the
    comps-context path.
13. Book guards: AZN and LLY are covered with five rows each and the obesity row has
    `0 < crowded_share ≤ uncrowded_share ≤ 1` and `0 < keeps ≤ 1`; CRSP is not covered; a second
    build of AZN takes under 300 ms.

**core, `core.test.js`:**

1. `defaultPeers`: a cohort of 17 is returned whole with `whole: true` (AZN includes LLY and
   BAYN); a synthetic cohort of 25 is cut to the 15 most relevant at or above the floor; a cohort of 3 still pads.
2. `PRESETS`: every built-in preset has exactly nine columns, and the lists equal 12.7.
3. `flagMarks`: one assertion per row of the table in 12.7. `cell.amber` follows `marks`.
   `stale_shares` marks `market_cap` and not `ev_revenue`. On the fixture AZN view no row has
   `tickerFlags`; a focal with a costing flag on its primary cell has it; a peer with derived
   operating income has it only while the derived-share penalty is in force.
4. `insight.state`: pending for a null context and for another ticker's; error for an `error`
   context and for a wrong schema; ok otherwise. The pending view still has the metric items.
5. Side rules on `fixture_context.json`: AZN discount holds `pool_rationed:367` with the exact
   sentence of 12.3 and no catalyst item; LLY the same and no `pool_lead`; NVO premium holds
   `pool_lead:367`; VKTX discount holds `catalyst_value` with the exact sentence and not
   `binary_catalysts`, while `view.observations.discount` still has it; a synthetic stake of 5%
   yields `catalyst_stake`, and one of 4.9% does not.
6. Catalyst rows: one row per asset, the tier order, AZN's first five labels as in 12.3, the
   three date forms, `modelText` null with the marketed `naText` for Imfinzi.
7. Competition rows: AZN obesity's `valueText`, `ownText`, `rivalsText`, `poolText`,
   `shareText`; each pool reason as `poolNa`; CRSP's group is `not_covered` and BAYN's carries
   the contest line, each with the copy of 12.3.
8. `indicationTitle` and `indicationProse` on the five AZN names.
9. Copy: every new string (side sentences, row texts, `CONTEXT_NA_TEXT`, state copy, footer,
   Basis chip, bridge line) passes `lintCopy`: no banned word, no em dash, sentence case.
10. Reducer: `OPEN_PEERS`, `OPEN_DETAIL` and `OPEN_METHOD` leave exactly one surface open;
    `ADOPT_PERSISTED` replaces the persisted slices and keeps `focal` and `ui`; `mergeBridge`
    changes only `bridge[focal]`.
11. `header.basis.text` for the four cases; `table.viewBadge`; `footer.text` and its tone;
    `bridgeLine.text` for AZN; `kpis[5].link`; `COMMANDS` has the four new ids, lacks
    `bridge.reset`, and no key is bound twice.
12. Bridge mode: `deriveView(payload, state, {mode: "bridge"})` returns `bridge` and
    `bridgeLine` and a null `insight` and `table`.

**table, `table.test.js`:** the toolbar holds exactly "Columns", "Find column" and "View" (and
the hidden chip only with hidden columns); no "Below the table"; the View menu's groups, order
and items, with the right item checked; the badge text; a `!` renders only for a cell with
`marks`, and after a ticker only with `tickerFlags`; the cell tooltip lists only the marking
flags.

**charts_panels, `charts.test.js`:** the strip renders at `wide` with the two tabs and a 320 px
scatter; `mountObservations` draws the four blocks, five rows and "Show {n} more", the pending,
error, empty and not covered blocks with the exact copy, and calls `ctx.openLink` with the row's
link; at `narrow` one group shows under the tab strip; `mountPeerPanel` renders nothing when
closed and a `role="dialog"` titled "Edit peers" when open, focusing the search box for
`search: true`; the methodology drawer's first section is "Sources"; `mountBridgeInputs` leaves
out its title when `ctx.mode === "bridge"`.

**shell, `shell.test.js`:** the block order of `#main` for each layout; `bridgeFrameHeight`;
the pure `contextFor(map, ticker)` and its 12-entry bound; `basisChip`; `openLink` against a
fake parent for the four link kinds, including the absent Indications tab; `mergeBridge` round
trip through a fake storage; the Esc order with the peer drawer in it.

**wiring, `test_comps_tab_ui.py`:** two component instances, `compsval` (mode `"full"`, a
`context` whose `ticker` is the focal, 70 companies with `detail`) and `compsval_bridge` (mode
`"bridge"`, `context` None, no `detail`); the Forecast tab carries the heading "Value implied by
peer multiples" for a modelled company and for one with no model; an `indication` action sets
`land_pick_{ticker}` once, and an unknown id or a repeated nonce changes nothing; a failed
context read gives the error context, not an exception; the wrapper rejects an unknown mode and
passes `mode`, `context` and `context_digest`.

**Integration** (shell leads), on the live app at 1440 × 810 and 1920 × 1080: the first-screen
claims of 12.1; AZN's obesity row opens Comps, Indications on Obesity; a catalyst row opens the
Catalysts tab; KPI 6 opens the Forecast tab at the bridge; a peer excluded in Comps changes the
bridge on the Forecast tab without a reload; the peer drawer opens from all five entry points
and returns focus; a company picked inside the frame shows the pending groups, then its own.

### 12.12 Decisions changed or sharpened from R3.1 to R3.7

| Decision | What this section does instead, and why |
|---|---|
| R3.2, "the value at stake where the model has one" | The book prices one catalyst in all (Casgevy, 2027-11-14), outside every holder's 12-month window, because only one asset carries both outcome legs. Nothing was derived for the rest then; a big pharma pipeline asset's next gate now derives its legs (12.2, `stake.basis`), and Drivers ranks a derived stake in tier 0 just below the stated ones. So a row also shows the model's risk-adjusted value of an unapproved asset, labelled as that and never as a stake, and the side rule has two forms (`catalyst_stake`, `catalyst_value`) at one 5% threshold. On this book that fires for AMGN, NVO, UTHR and VKTX and not for AZN or LLY. |
| R3.2, "most valuable indications" | The model values assets, not asset-indication pairs, so value is attributed by a stated rule: the indication the model sizes the asset in, else the book's lead indication. Counting an asset in every indication it touches ranked Lilly's fatty liver trial at $146 a share. |
| R3.2, "share of the modelled pool" | Stated as the company's share of the modelled claims among pooled claimants, and only for a standing pool with between 1% and 100% claimed. Cancer lines are sized by yearly new patients and have no pool to share, so their rows say so rather than show 0%. |
| R3.2, direction | Two pool rules and two catalyst rules take a side; rival counts by stage never do. A count of big pharma rivals cannot show that a field is empty, since biotech rivals are outside the landscape. |
| R3.1 | The charts are a strip at every width, and the side panel a drawer at every width: the fixed order leaves no rail to dock into. `wide` and `laptop` share one arrangement. |
| R3.3 | The bridge is drawn on the Forecast tab for every company, including those with no model, and KPI 6 scrolls to it. |
| R3.4 | Notes and data sources become the first section of the methodology drawer, not a drawer of their own: one drawer fewer. |
| R3.6, "about nine" | Exactly nine. The ticker marker is tied to the confidence points, so a peer's flag marks its ticker only when it feeds a penalty. |
| R3.7 | No relevance floor inside a whole cohort. Every cohort in the universe is under the limit today, so the 15-company cut is dormant. |
| 7.5 | Python now hears three actions, not two: `indication` joins `focus` and `reload`. |

Known limits, left as they are: the lead indication is the book's flag, right or wrong
(Mounjaro, Taltz); 8 of AZN's 36 catalysts and 3 of LLY's 33 have no indication on file. (A
catalyst row with no asset id was once not read by the stake engine; the engine now reads a
registry readout through its study's asset, as this payload does.)

---

### 12.13 As built: where the code departs from 12.1 to 12.6

- **Colour (supersedes 9.1's `ACTIVE`).** The view carries no colour of its own. The user asked
  for the Comps tab to match the rest of the terminal, so the blue `ACTIVE` token and its wash
  are gone from `tokens.py` and `tokens.css`. `research.css` derives `--active: var(--up)` (the
  terminal's tab underline and chosen pill), `--active-wash` as `--up` mixed 14 % into the panel,
  and `--focus: var(--text)` (the terminal's focus outline). `--up` also reads as a positive
  delta, so selection is always paired with a border, weight or glyph.

- **Narrow layout.** The two evidence groups stack under the side lists at every width; there is
  no "Catalysts ahead | Competition" tab strip, and `ui.insightTab` is unused. One scroll reads the
  whole section, and the 800 px pane shows both groups without a control to find.
- **Skeleton.** `shell.js` builds its skeleton on the first render message rather than at load,
  because that message names the mode. Nothing could paint before it anyway: the tokens arrive
  with it.
- **Detail panel.** The company panel is a fixed right-side drawer at every layout, as the peer
  and methodology drawers are; the docked rail column of `wide` went with the chart rail.
- **Sources.** `panels.js` prepends the "Sources" section to the methodology drawer itself
  (core's `view.method.sections` does not list it); `mountNotesSources` stays exported and is not
  mounted.
- **Bridge frame height.** The frame takes the height of `#app` plus 4 px, floored at 200.

---

## Appendix A. Resolved review points

The design review raised 51 points. Each was checked against the brief, the data dictionary and
the book (read only, the 2026-09-29 backup). Most were right and are built into the sections
above. This appendix records the points that were wrong in part, were resolved differently from
the reviewer's proposal, or found something the review did not.

### A.1 Points changed from the reviewer's proposal

| Point | Proposal | Resolution and reason |
|---|---|---|
| Pre-revenue primary (33 of 70 had no premium) | EV against the peer median EV first, then cash / market cap, then P/B | **Market cap / cash**, richer up, for clinical and sub-scale companies (3.5). EV against a peer-median EV measures size: the clinical cell and gene set spans $0.1bn (CRBU) to $5.2bn (CRSP) of market cap and scale is only 20 % of relevance, so a "premium" would mostly report size, which is the generic comparison the brief rules out. EV also exists for only 8 of 26 cell and gene names. Market cap / cash exists for all 70 and is scale-free: CRSP is 2.21× against a median of 2.07× over 17 clinical cell and gene peers, a 7 % premium. P/B adds nothing for a clinical company, whose equity is mostly its cash, and is dropped for loss-makers too (the BNTX 81 % "discount"). |
| Company type from consensus | Profitable only when FY1 and FY2 EPS are both positive | Type follows **FY0 operating income** (3.3). GILD made an operating profit in FY2025; one negative consensus year (−0.48) would have labelled it "loss-making" with a false chip. The sign-change rule on P/E NTM (4.2) removes the misleading 21.1× multiple, and GILD's primary moves to EV/EBITDA. AXSM, ATRA and LEGN get the same n.m. |
| Market cap share guard | Use the cover count only when within 400 days **and within 10 % of the diluted count**; otherwise diluted | The 400-day guard is adopted (REGN's 2012 count; ADAPY at 413 days). The 10 % rule is not: it would put 20 or more companies on a stale count. The cover count is the current one wherever the gap comes from issuance after the fiscal year (VOR +499 %, IPSC +109 %, EDIT +73 %, ALLO +57 %) or buybacks (EXEL −12 %, UTHR −10 %), and the diluted count is itself wrong for IOVA (filed in thousands). LLY moves to the diluted route through a named exception with its cited reason, and IOVA's alternative is dropped by a scale check (2.3). |
| Laptop table scrolling | Drop the table's inner scroll box; `#main` scrolls with the header and footer sticky to it | Not possible with frozen columns in one table: any `overflow-x` other than `visible` makes the table box the sticky container, so a header cannot stick to `#main` while the table scrolls sideways. The trap came from `overscroll-behavior: contain`, which is removed, so the wheel carries on into `#main` at the table's ends. The box is sized to `--main-h`, the laptop chart strip is 120 px and collapsible, the footer shows median and n by default at laptop, and a "Below the table" menu jumps to the lower sections (1.2, 1.3, 4.6). |
| Scatter clamp | Apply the dot plot's 5th to 95th percentile clamp | The dot plot's clamp itself changed (the review's point on the dot plot domain was right: with R-7 the minimum and maximum peers always fell outside it). Both charts now use min to max with only Tukey-extreme values clamped (5.1, 3.8). |
| Headline band edge | Consider hysteresis | Not adopted: a conclusion must be a function of the data, and hysteresis would make the same inputs read differently depending on the last view. The rounding rule is adopted instead (`isInLine`), so the token, KPI 5 and the headline always agree on the whole percent, and the in-line headline shows its percentage. |
| Row click | A single click only focuses the cell | Adopted for data cells. The brief asks that clicking a company row opens the side panel, so a click on the **company or ticker cell** still opens it, as do a double click, Enter and `o` (4.7). |
| System-generated label in short mode | An info icon with a tooltip | Kept as text, shortened to "System-generated", because the brief asks for a clear label; the full sentence is in its tooltip. |
| Earnings option names | "GAAP/IFRS" and "Adjusted" (one point); "Excl. amortisation and IPR&D" (another) | "GAAP/IFRS" and "Ex amort. and IPR&D". "Adjusted" would clash with the street "adjusted" EPS in the same view. |
| "Look next" order | Strongest observation, outlier, focal flag, weak fit | A flag that costs confidence on the focal's own primary value comes first, because it can change the headline; the strongest observation is the usual answer (3.11). |
| Standard and filer kind from filed facts | Read the taxonomy of the filed facts | The book does not store it: `financials` has no taxonomy column and the financials snapshot payload has no such key. The fetchers now write it into the payload (a one-key change in this build), and until the next financials refresh a 20-F filer without the FPI flag shows "standard not recorded" rather than a guess (2.3). Filer kind comes from `filings` now. |
| IFRS attributable profit and equity | Use the attributable tags for ESEF and 20-F filers | Only ROG and BAYN have `NetIncomeAttributableToParent` in the book. For the EDGAR and ESEF IFRS filers, `statements.py` maps net income to `ifrs-full:ProfitLoss` and equity to `ifrs-full:Equity` and stores no attributable line, so those cells carry the amber `includes_minorities` flag instead (2.3, 2.5). Storing the attributable lines is a fetcher mapping change that needs a financials refresh, outside this build. |
| Thin FY3 estimates on `eps_growth_top` | Attach the FY3 flag to the EPS growth observation | `eps_growth` is FY2 over FY1, so the FY3 flag goes on `peg` and `eps_cagr`, and a thin FY2 flag goes on forward `eps_growth`; the observation skips a flagged cell (2.5, 3.10). |

### A.2 Review figures corrected against the book

- Derived operating income: 4 of the 14 pharma EV/EBITDA values rest on it in the current book
  (BMY, LLY, MRK, PFE), not 6; BIIB and JNJ read reported operating income. 4 of 14 is still
  over 25 %, so the confidence penalty stands.
- IOVA's stored guidance note reads "revenue guidance of $350 million to $370 million", not
  product revenue, so the scope rule classes it total. AZN's note mentions "Product Revenue plus
  Collaboration Revenue" inside a total-revenue scope line; the rule reads the "Scope:" line
  first and checks "total revenue" before "product revenue", so AZN stays total (2.3). The rule
  was run over every FY2026 guidance row in the book.
- AZN's confidence: with GILD's P/E NTM now n.m., the focal-excluded pharma set has 14 values,
  median 15.36×, IQR 54 % of the median. AZN scores 2 (high), not medium: no standards penalty
  on a street metric, no estimate-range penalty at 6 estimates and 0.55.

### A.3 Found while checking, not raised by the review

- `refresh_runs.status` takes `complete`, `partial`, `interrupted`, `failed` or `running`; the
  earlier draft tested for `"ok"`, which never occurs, so the partial-run state would have fired
  on every run. Fixed in 2.2 and section 8.
- `comps.price_grid` reads `date('now')` and drops the latest close when downsampling; it also
  feeds the side panel's weekly sparkline. The builder uses its own `_spark` (2.3); the shared
  function's behaviour is left for its own fix.
- The seed carries `is_foreign_private_issuer = 0` and `country = US` for BNTX, ARGX and LEGN,
  which file 20-F, and `country = US` for CRSP, QURE and AUTL, which are incorporated outside the
  US. The view no longer relies on either field for filer kind or region, but other tabs read
  them.
- `COVER_COUNT_EXCEPTIONS` holds a sentence per ticker so every forced route is explained on
  screen; it is the only hand-kept list in the builder.
