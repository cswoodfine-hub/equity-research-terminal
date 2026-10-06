# Key insights, revision 4: the note open, and one screen

Revision 4 (2 to 5 Oct 2026) keeps revision 3's call and price chart and replaces everything below them. The user asked for four things:
- The morning note open on arrival. It should cover the share price, recent trading and what may bear on it, then the 12-month value and the drivers and catalysts behind the rating.
- Everything below the top row organised so the figures fit on one screen without scrolling. The 24-month event track goes: it did not make clear when each driver, risk or catalyst falls. Dated lists of readouts and patent expiries replace it, and "What it rests on" becomes "Key assets", the top five marketed and top five pipeline assets.
- A second row of key figures in the top left, evenly spaced: the 24-hour move, annual revenue, products on sale, late-stage compounds and every compound in trials.
- A note that uses judgement and reasoning, so that one read gives the big picture.

Sections 1 to 11 below are revision 3. Where they describe bands 2 to 4, this section supersedes them. M1 (the call), M2 (price against the call), the bridge's arithmetic (M3), M8 and M9 stand.

### R4.1 Layout at 1440 x 900

```
y 134  ┌ THE CALL (5/12) ───────────────┐ ┌ PRICE AGAINST THE CALL (7/12) ──────────────────────────┐   unchanged
y 320  └────────────────────────────────┘ └──────────────────────────────────────────────────────────┘
y 345  ┌ MORNING NOTE (1.12fr) ──────┐ ┌ KEY ASSETS  $ a share (1fr) ──┐ ┌ WHERE 185.11 COMES FROM (1fr) ┐
       │ price and trading; the news │ │ MARKETED      value   LOE      │ │ waterfall 470 x 176            │
       │ that may bear on it         │ │ Tagrisso ██   10.29  Aug 2032  │ │                                │
       │ the 12-month value, the     │ │ … 5 rows, then "27 more 49.60" │ ├ AGAINST 18 BIG PHARMA  7th of 18 │
       │ rule that rates it, what it │ │ PIPELINE, AFTER POS value next │ │ FINANCIALS 58.7bn USD revenue  │
       │ rests on, what breaks it    │ │ Elecoglipron ▆ 4.66 Ph 3 · Apr │ │ Revenue growth ··●· 8.6% 4th…  │
       │ next readouts, first LOE,   │ │ … 5 rows, then "15 more 1.25"  │ │ … 8 measures in three groups,  │
       │ rank against the cohort     │ ├ PATENT EXPIRIES ───────────────┤ │ each value, place and strip    │
       ├ UPCOMING READOUTS ──────────┤ │ 8 Sep 2027 Lynparza 5.6% 2.43  │ │                                │
       │ ○ Oct 2026 Truqap Ph 3 · …  │ │ … 5 rows                       │ │                                │
y 860  └ 5 rows, "20 more" ──────────┘ └────────────────────────────────┘ └────────────────────────────────┘
       ├ WHAT CHANGED (7) ──────────────────────────────┤ ├ NOTE: [Rewrite note] [Tearsheet] (5) ─────────┤
```

- Band 2 is one `st.markdown` holding one grid, `.ki-band.c3e`, with columns `1.12fr 1fr 1fr` and a 32 px gap: about 470 | 420 | 420 px at 1440. The three columns end within about 60 px of each other for AZN, LLY and NVO.
- Every table row is 23 px with a hairline. Caps sub-heads are 10 px. Dates and values are mono, and so are the cohort places.
- A pipeline compound is purple wherever it is named, in Key assets and in the readouts.
- Measured on 2 Oct 2026: the tab panel is 850 px for AZN at 1440 x 900, so the whole of band 2 is above the fold. At 1600 x 1000 the foot is too. Below 1180 px the columns stack.

### R4.2 Modules

**The call's two figure rows** (`_ki_figures`, `_ki_business_figures`). There are two rows of five cells on one grid, `.ki-figs` with `repeat(5, 1fr)`.
- The market row: close, 24 hours, 1 year against XLV, street target, and the multiple against its median.
- The business row: market cap, the year's revenue with its growth, products on sale, late-stage compounds and compounds in trials.
- A figure carries its currency's sign ($ € £ ¥). Any other currency is named in the key.
- Products on sale is the model's count where the company is modelled. Otherwise it is the approved products on the exclusivity file, and the key says so.
- Late-stage counts Phase 3 and Phase 2/3. In trials counts every phase.
- The price chart grows to 196 px so band 1's halves stay level.

**Morning note** (`_ki_brief`, `_ki_brief_html`). Three short paragraphs, about 160 words, reasoned from the figures on the page and nothing else. The opening sentence is bold. The note model's rewrite (POST `/companies/{t}/brief`) is shown only while its facts hash matches today's figures. The click's answer is used as it comes back, because the GET is cached.
1. **The call, and what the price pays for.** "Buy, with a 12-month value of 185.11, 17.4% above the 157.70 close." The judgement then splits today's central value into two parts: the products on sale with net cash (or net of debt), and the pipeline plus future launches. It shows what the price implies for the second part. AZN's price "pays for the products on sale and net cash (80.39) and 82% of the 94.58 the model puts on the pipeline and future launches: the rest is the upside". LLY's "asks 889.82 for the pipeline and future launches, 3.3 times the model's 266.42". The other states each get their own wording: a rating or forecast read that failed, a modelled company with no 12-month value, and a company that is not modelled.
2. **The trading.** The month and the year against XLV. Then the month's news, set beside the move by its tone (`_ki_news_tone`): "despite" for good news in a falling month, "with" in a rising one, "alongside" for bad news in a fall. A move is never given a cause, and the timing is never placed within the month. With no news, the one-month relative says whether the move is the sector's. Late-stage slips are counted.
3. **What drives it and what to watch.** First, the three largest legs of the value, drawn from the top assets, launches past the pipeline and net cash, each with its protection or chance of approval. Then the levers that would break the call. Next, whether the next readouts test the pipeline or extend products already sold. Where the next test is the compound's next gate (the same kind of event, in the gate's month), its clause says what passing is worth: "The Phase 3 readout for Eloralintide (est. Jan 2028) is the next test of the pipeline, worth 8.23 a share if it passes and nil if it fails, against 5.02 now." Otherwise it keeps "..., 5.02 a share in the model". No sentence is added, and a gate already due is never said of a later study. Then the nearest loss of exclusivity, which is the first row of the list beside it, so the two cannot disagree. Last, the rank, with what growth and margin say together: "growth bought at the cost of margin", "a cash generator short of growth", "strong on both" or "weak on both". A clinical company gets its cash runway instead.

**Readouts and decisions** (`_ki_readouts`). This lists regulatory dates, Phase 3 and Phase 2/3 readouts, readouts of unapproved compounds worth at least 1% of the price (`DRIVER_MIN_PCT`), and Phase 2-or-later readouts of unapproved compounds the model does not value. They come from the comps-context catalysts, soonest first, five rows. Two trials of one compound in the same month count as one row. ○ marks every date the company has not stated or confirmed, which includes ClinicalTrials.gov dates given to the month. Quarter and half dates print as Q1 and H2. When the 12-month window holds fewer than five, the list is topped up with each compound's next registry readout past the window, so a clinical company still has a list.

**Key assets** (`_ki_key_assets`).
- Modelled: the top five counted marketed products and the top five counted pipeline compounds by value a share, on one bar scale.
  - Marketed rows show the LOE. It comes from `/exclusivities` as a month, or as the year alone where a 31 Dec date stands in for a year the filer gave. A product past its LOE shows "lapsed".
  - Pipeline rows show the next readout at the furthest phase the compound still has to read out, from `/programmes` (Elecoglipron: Phase 3, Apr 2028, not its Phase 1 in Nov 2026).
  - A compound with a next gate gets a whisker: a 1 px purple hairline from the bar's end to its value if the gate passes (the verdict line's `per_share_success`), with a 5 px end tick. It is drawn inside the bar's 8 px cell, so the row keeps its 21 px, and the bar scale takes the whiskers, so none is clipped (Amgen's scale is MariTide's 45.97 if it passes).
  - A compound whose model launch year falls before the earliest approval the registry and the FDA review clock allow has its value underlined: red before the floor, amber where its seed cites a filing or readout that is not on file. A part year carries nothing.
  - The row has one tooltip and no new word: the gate and what it is worth ("Phase 3 readout est. Jan 2028: 8.23 a share if it passes, nil if it fails, derived from published transition rates", or "on gate odds implied by the stated PoS"), a gate that costs more to reach than it is worth risked ("reaching the Phase 2 readout costs more than it is worth risked: it needs a 52% chance against the 27% on file, at published trial costs in 2018 prices"), and the launch floor's message. The cost fact has no mark of its own.
  - The "more" rows are the sum-of-the-parts total less the rows shown.
- Not modelled: products are ranked by share of the company's revenue and compounds by furthest phase, then the nearest readout. A modelled company with no modelled compound lists its programmes the same way.

**Loss of exclusivity** (`_ki_expiries`). The next five losses of exclusivity, soonest first, of products that matter: those the model values or those with revenue on file. A company with neither lists every one.
- The scorecard's own date wins for its products.
- A product the model already carries past its LOE is never listed.
- An orphan term is never taken for the product's loss: it guards one indication.
- Each row shows the date at its source's precision (a year where a filer gave a year), the product, its kind (patent, 12y biologic, settlement, model year), its share of revenue where known, and its value a share where modelled.
- A product the exclusivity file lacks (a CBER biologic) keeps the model's LOE year.

**Shares of revenue** (`_ki_product_mix`) are measured against the year's reported revenue. Bayer files a pharma-only product table, so Nubeqa is 5% of Bayer, not 30%, and the rest of revenue is one row. Product rows of another year than the revenue, or adding to more than it, give no shares at all.

**Bridge.** Unchanged in arithmetic, drawn at 470 x 176.

**Against the cohort** (`_ki_cohort_table`, `_ki_cohort_html`). One table in caps groups: Financials (with the revenue level beside the group label), Pipeline (with compounds in trials beside it) and Marketed. A clinical company gets Funding and Pipeline. Each row shows the measure, a 72 px peer strip where right is better, the value, and the place in tone. A group with no measure on file is one line giving the reason.

### R4.3 Reads

Revision 3 added no endpoint. Revision 4 reads two existing ones that the Pipeline and Portfolio tabs already use: `/companies/{t}/programmes` (compound stages and study due dates) and `/companies/{t}/exclusivities` (LOE dates and their basis). The next gates' costs come from `/companies/{t}/development`, the Forecast tab's company table, for the one tooltip fact above. Each read has its own try, so a failure empties one list or one fact and never the tab, and says it did not load.

### R4.4 What left the tab

- The event track, its key and the 12-month marker. Charts `event_track` and `share_bar` were removed with it.
- The rests table, and the breaks as rows (they are a sentence of the note now).
- The three cohort columns, with their revenue bars, phase bar and product-mix bar.
- The folded note expander.


### R4.5 What the 70-company review changed (2026-10-05)

A review of the note on all 70 companies found 27 faults, every one verified; a layout review at 1440, 1600 and 1180 found 21 more. The rules they set:

- **The call.** The price-implied split is not drawn for a company whose products on sale the model values at nothing (Moderna); the note says what the value is instead. Where the forecast covers under 90% of revenue the note says how much it leaves out (Roche, 72%). "The rest is the upside" is gone: the unpriced share of the pipeline is not the 12-month upside, which also carries the year's roll.
- **The trading.** "Despite the month's news" only where the shares also fell behind the sector. The year's relative is never set beside the month's move. A month with nothing rated high says its press releases and FDA news rated medium, and never says "no news on file" when lower-rated news exists. A deselection from Medicare negotiation is not good news; a release that hopes for an approval is not an approval (the press classifier refuses it too). Slips count one a trial, from its first date to its last, and a correction to a date already past is not a slip.
- **What comes next.** The next test of the pipeline is the furthest phase in the soonest month, a regulatory date first; never a regimen, a follow-up or extension study, an invitation-only study or a date more than eight years out. When the events read fails the readouts list says so and is not filled from the registry.
- **Loss of exclusivity.** The note names the first loss worth 5% of revenue, every product lost that day with it, and a larger one after it within five years (Merck: Keytruda, not Janumet). Dates print at their source's precision: a filing's or the statute's year is a year, never 31 December.
- **The cohort.** Growth and margin are judged by the scorecard's score in thirds, and a loss is never a good margin.
- **Length.** A note past 180 words says one piece of news, not two. Measured on the 70: 61 to 184 words, median 88.
- **Layout.** The cohort chip is the rank alone; "right is better" is said once in the table. The call's range sits on the lead's baseline, so the call stays level with the chart. A short note lets the readouts list run to seven rows, so the columns end together. The bridge is drawn at the column's width with no axis margin, and a price far above every bar is named in the chip rather than drawn. Columns stack below 1180, not at it.

# Key insights, revision 3: the highlights of every tab

Design only. This replaces company-scorecard.md 1.3 and 5.3 for this tab. Every field named below was checked on 2 Oct 2026 against the running API (AZN, LLY, BAYN and CRSP) and against the code in this worktree.

## 0. What the page answers, in eye order

| Band | Question | Distils | One picture |
|---|---|---|---|
| 1 | What is the call, and where is the price? | Prices, Forecast | price line with a 12-month gutter |
| 2 | Where does the 12-month value come from, and what does it rest on? | Forecast | the bridge, with ranked parts beside it |
| 3 | What could move it in the next two years? | Catalysts | one 24-month event track |
| 4 | How does the business compare with its cohort? | Financials, Pipeline, Portfolio, Comps | three columns, each with one picture and peer dot strips |
| foot | What changed; the note | News | none |

**Eye path.** The reader starts top left on the call: the coloured rating word, then the 192.49 figure. The eye moves right to the price line and its 12-month gutter, where the model dot sits above or below the dashed price rule. Bands 1 and 2 share one seam at 5/12, which gives two stacks:
- The left stack is the story in figures: the call, then what the value rests on, then what would break it.
- The right stack is the proof in pictures: price against the call, then the bridge. The bridge's last bar (12 months) sits directly under the gutter's model dot.

Below those, the track reads forward in time across the full width. The business band follows as three identical columns that the eye compares across. The foot comes last.

## 1. Layout at 1440 x 900

Tab content is 1408 px wide. The tab strip rule sits at about y 126.

```
x 16                        589  621                                                         1424
y 126 ──────────────────────────────── tab strip rule ───────────────────────────────────────────
y 134 ┌ THE CALL (5/12, 573) ─────────────┐ ┌ PRICE AGAINST THE CALL (7/12, 803), no rule ────────┐
      │ 12-MONTH VALUE · MODEL             │ │210┤         ╭╮                        ┆ IN 12 MONTHS │
      │ Buy  192.49  +22.1%                │ │   │  ╭╮ ╭──╯╰╮   ╭╮                   ┆   ┬          │
      │ against 157.70 · 163 to 231 in 12  │ │180┤╭─╯╰─╯     ╰╮╭╯╰╮                 ┆   ● model    │
      │ months                             │ │   │            ╰╯  ╰─╮ ╭╮            ┆   │  ○ street│
      │                                    │ │155┤                  ╰─╯╰●- - - - - -┆- -┴- - - - - │
      │ 157.70     −6.5%      211.63  4.6× │ │    Jan 26    Apr 26    Jul 26    Oct 26             │
      │ close ·    1 year ·   street· EV to│ │                                                      │
      │ −2.3% today −24 points 14 buy, sales│ │                                                     │
      │            vs XLV     2 hold  · med│ │                                                      │
y 302 └────────────────────────────────────┘ └──────────────────────────────────────────────────────┘
y 326 ├ WHAT IT RESTS ON  $ a share ───────┤ ├ WHERE 192.49 COMES FROM  $ a share · the price dashed, 157.70 ┤
      │ Launches past the pipeline ▒▒▒▒ 88.76 from R&D│ 89.61 ▕+12.32▕+88.76▕+10.58▕−19.44▕181.83▕+10.66▕192.49│
      │ Tagrisso         ██      10.29  LOE 2032 │ │ (waterfall 800 x 190, FLAG dashed rule at 157.70) │
      │ Imfinzi          █▊       8.89  LOE 2031 │ │                                                   │
      │ Ultomiris        █▌       7.63  LOE 2035 │ │                                                   │
      │ Symbicort        █▍       7.04  lapsed   │ │                                                   │
      │ 50 more                  68.07           │ │ marketed pipeline launches to today debt and costs│
      │ TODAY'S 181.83 MEETS THE 157.70 PRICE AT │ │ today  a year on  12 months                       │
      │ ▼ every discount rate    7.47% → 8.35%   │ │                                                   │
      │ ▼ launch productivity    0.364 → 0.312   │ │                                                   │
y 548 └────────────────────────────────────┘ └──────────────────────────────────────────────────────┘
y 572 ├ DRIVERS, RISKS AND CATALYSTS  next 24 months · Catalysts has them all ───────────────────────┤
      │      Truqap   Enhertu                                                                          │
      │   Phase 3 readout  Saphnelo  Fasenra                                                           │
      │ today ○─○○──○·─·─·──·──·─·───┊ 12 months ─────────────▼─────────────▼───▼────▼───────────────│
      │   Oct 26    Jan 27    Apr 27    Jul 27    Oct 27    Jan 28    Apr 28    Jul 28                 │
      │                                       ▼ Lynparza LOE     ▼ NCT06455449  ▼ Koselugo LOE ▼ NCT07775404│
      │                                         5.6% of revenue    slips 241 days 1.1% of revenue slips 307 days│
      │ 73% kept   Obesity: 2 candidates in a 19-drug pool (model)                                     │
y 758 └─────────────────────────────────────────────────────────────────────────────────────────────────┘
y 782 ├ AGAINST 18 BIG PHARMA  7th of 18 · score 58 · range 2–11 · right is better ──────────────────────┤
      │ FINANCIALS                     │ PIPELINE                        │ MARKETED PRODUCTS              │
      │ 58.7bn USD revenue, FY2025     │ 92 compounds in trials          │ 4.6 years of exclusivity left  │
      │ +8.6% · 4th of 17              │ 23 late-stage · 2nd of 18       │ 8th of 17                      │
      │ ▁▃▄▆█  FY21 to FY25            │ [P1 27|P1/2 28|P2 12|P3 23|·]   │ [Farxiga 14%|Tagrisso 12%|…|rest]│
y 900 ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ fold ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
      │ Operating margin  ··●·|··  23.4% 3rd worst of 12 │ Late-stage per $10bn ··|·●· 3.9 3rd of 18 │ Top product share ··|·●· 14% 6th of 17 │
      │ Net debt / cash flow ·|●·· 1.6× 8th of 17       │ 12.32 a share after PoS, 23.73 before    │ New-launch revenue ●·|··· 7% 4th worst of 17 │
y 990 ├ WHAT CHANGED  3 of 9 high in 30 days, News has them all ┤ ├ [Generate] [Tearsheet]              ┤
      │ 28 Sep  AstraZeneca announces strategic equity…         │ │ ▸ Morning note · gemini-flash-latest · 22 Sep 2026 │
      │ 23 Sep  Trixeo approved in the EU for the maint…        │ │                                    │
      ├ ▸ China-linked business development (folded, only when present) ───────────────────────────────┤
```

**Grid.** Each of bands 1 to 4 is a single `st.markdown` that holds a CSS grid (`.ki-band`). That makes the seams exact and paints each band as one element.
- Bands 1 and 2 use `grid-template-columns: 5fr 7fr; column-gap: 32px`. That gives 573 | 803 px at 1440 and 640 | 896 px at 1600.
- Band 3 is one cell.
- Band 4 uses `repeat(3, minmax(0, 1fr))` with a 32 px gap, so each column is 448 px at 1440.
- Bands sit 24 px apart (`.ki-band + .ki-band`).
- The foot uses `st.columns([5, 7], gap="medium")`, because it holds widgets.
- Below a 1180 px viewport, every band becomes one column.
- SVGs are built at their 1440 widths and mounted `chart-mount stretch`, so they scale ×1.115 at 1600. No chart text is smaller than 9 px.
- The builders emit no blank lines and no 4-space indents, so markdown cannot break the HTML.

**Type: six sizes.**

| Use | Face, size | Colour |
|---|---|---|
| Hero figure | Plex Mono 28px/600, tracking −0.02em | |
| Rating word | Archivo 24px/700 | |
| Module figures | Plex Mono 20px/600 | unit at 11px MUTED |
| Cell values | Plex Mono 15px/600 | |
| Section labels | the existing `.sec` caps (via `_ki_section_html`, the same markup as `section()`) | |
| Keys and captions | 10.5 to 11.5px | MUTED |
| Chart text | 9 to 10px | |

**Colour: tokens only.**
- UP and DOWN carry good and bad and the call's tone.
- FLAG marks the price rule and regulatory dates.
- PURPLE_BOOK marks the pipeline.
- PHASE_RAMP marks phases.
- MUTED marks peers and minor events.
- Product shades are `_blend(UP, GROUND, t)` in charts, or `_mix_hex` in the app, for t = 0, .25, .45, .6, .72. The rest of revenue is RULE_STRONG.
- No new hex values. No cards or panels: hairlines and whitespace separate.

**First screen.**
- At 1440 x 900: bands 1 to 3 in full, plus band 4's rule, its figure lines and its three pictures.
- At 1600 x 1000: bands 1 to 4, including the first peer row of each column.
- For BAYN, band 2 collapses to one line, so band 4 is whole at 1440 x 900.

## 2. Reads: no new endpoint

| Read | Function, cache | Already read in the same run by | Feeds |
|---|---|---|---|
| prices dict | page top, `/companies/{t}/prices` (in memory) | Prices | M1, M2 |
| feed | page top, `/changes?ticker=` | News, Catalysts | M6 (slips), M8 |
| comps payload | `_comps_valuation_payload(api_base)`, 60 s | Comps, Catalysts | M1, M7 (scorecard, record) |
| fair value | `api_get(api_base, f"/companies/{ticker}/fair-value")`, 30 s | Forecast (`_rating_tile`, `_fair_value_range`) | M1, M2, M3 check |
| verdict | `api_get(api_base, f"/companies/{ticker}/forecast-verdict")`, 30 s, the exact path string `_book` uses | Forecast, Pipeline, Portfolio | M3, M4, M5, M7 |
| breakpoints | `_breakpoints(api_base, ticker)`, 60 s, not api_get, so it shares Forecast's key | Forecast (`_what_breaks_it`) | M4 |
| context | `_comps_context(api_base, ticker)`, 60 s | Catalysts | M6 |
| note | `/companies/{t}/note`, as today | none | M9 |

- The tab does not read /cashflow, /statements, /approvals, /programmes or /street.
- The backend warmer (`response_cache.COMPANY_READS`) keeps verdict, fair-value, breakpoints and comps-context hot for every ticker. Key insights renders first, so it takes the first hit, which is a backend cache hit.
- Each object is read once at the top of its band and passed down as a dict. `st.cache_data` unpickles a copy per call, and the comps payload is 1.2 MB.
- Read order:
  1. Payload and fair value.
  2. Paint band 1.
  3. Verdict, then breakpoints.
  4. Paint band 2.
  5. Context.
  6. Paint band 3.
  7. Paint band 4 (no new read).
  8. Foot.
- Every read is in its own try. A failure costs one module, never the tab.

## 3. Modules

### M1. The call (band 1, left, 5/12)

**Content, AZN.**
- Key: `12-month value · model`.
- Lead on one baseline:
  - `Buy` in Archivo 24, UP;
  - `192.49` in mono 28;
  - `+22.1%` in mono 15, UP.
- Sub: `against 157.70 · 163 to 231 in 12 months`.
- Four figure cells, value over key:
  - `157.70` / `close · −2.3% today`
  - `−6.5%` (DOWN) / `1 year · −24 points vs XLV`
  - `211.63` / `street · 14 buy, 2 hold` (a zero count is left out)
  - `4.6×` / `EV to sales · median 4.7×`

**Hovers.**
- Word: `rating.basis`.
- Figure: `rolled a year at the 7.6% cost of equity, less the 3.18 dividend`.
- 1-year cell: `3rd worst of 18 big pharma against XLV`.
- Street cell: `155.14 to 267.85, 2 Oct 2026, 14 buy, 2 hold, 0 sell`.
- Multiple cell: `9th of 18` (the value-pillar metric whose id is `facts.multiple.metric`).

**Sources.**
- fair-value:
  - `ok` and `reason` (top level; BAYN carries no `rating` key);
  - `rating.{ok, rating, reason, forward_12m, forward_low, forward_high, upside_12m, cost_of_equity, dps, basis}`.
- Close: `prices["latest"]["close"]`, shown only when `prices["points"]` is non-empty, as today.
- Day move: `points[-1].close / points[-2].close − 1` (AZN 161.47 to 157.70 is −2.3%).
- 1-year move: from the year series that M2 draws, last over first, minus 1 (AZN −6.53%, which equals `market.ttm_change`). It is printed only when the first point is 358 days or more before the last.
- `scorecard.companies[T].pillars.momentum.metrics[id=rel_1y].{text, place, n}`.
- `record.street.price_target.{value, low, high, as_of, ratings.{buy, hold, sell}}`.
- `scorecard.companies[T].facts.multiple.{metric, text, label, median_text}`.

**Rules.**
- **Model lead:** when `rating.ok` and `forward_12m` is not None.
  - Word tone: Strong buy and Buy in UP, Hold in TEXT, Sell in DOWN.
  - If `rating.rating` is None, the word is `·` with `rating.reason` on hover, and the figure still shows.
- **Street lead:** when there is no model value and `price_target.value` exists.
  - Key: `12-month street target`. No word.
  - Figure: the target. The move is target over close.
  - A muted `not modelled` follows, with the fair-value reason on hover.
  - The street cell becomes `52 weeks` with the closes' low and high, matching the chart.
- **Neither:** the key is `12-month value`, the figure is a muted `·`, and the hover reads `{fv reason}; no consensus on file`.
- Money is 2 dp with separators. The range is 0 dp when the close is 100 or more, else 2 dp (the `_fair_value_range` rule). The move is 1 dp, signed.
- The block keeps the `.pos` class (`<div class="pos ki-call">`), which the screenshot driver waits for.

**Builders:** `_ki_year_series`, `_ki_call`, `_ki_figures`, `_ki_call_html`.

**Words:** 40 or fewer.

**Empty states.** Each cell is a muted `·` with its reason on hover:
- `no price on file`
- `less than a year of prices on file`
- the scorecard reason for `rel_1y`
- `no consensus on file`
- `no multiple on file`

### M2. Price against the call (band 1, right, 7/12)

**Content.** The last 365 days of daily closes (AZN has 252 points). They are thinned with `_downsample(…, cap=160)`, which keeps the last close.
- The line is TEXT at 1.4 px. Today's close is a dot.
- A FLAG dashed rule runs at the close from the last point across the gutter.
- The gutter is 96 px wide, headed `in 12 months`:
  - The model range is a 6 px vertical bar from `forward_low` to `forward_high`, coloured the tone blended 45% toward GROUND.
  - The model dot sits at `forward_12m` (r 4.5, in the tone) and is labelled `model`.
  - The street target is a hollow MUTED ring (r 4) labelled `street`.
- Three y ticks and quarter x ticks (`Jan 26`).
- No line joins today to either mark.

**Domain.** Closes, the close, the model low and high, and the street value, padded 8%. The street's low and high appear on hover only, because LLY's 940 to 1,600 would flatten the year.

**Hovers.**
- Model: `Model in 12 months 192.49, 163.44 to 230.99: the discount rate a point either way and the growth fade at the analogue quartiles, rolled a year`.
- Street: `Street target 211.63, 155.14 to 267.85, 14 buy, 2 hold, 0 sell, 2 Oct 2026`.
- Line end: `157.70, 1 Oct 2026`.

**Sources.** `prices.points[].{as_of, close}`; `fv.rating.forward_12m`, `forward_low` and `forward_high`; `record.street.price_target`.

**Builder:** `CH.price_call` (new), at 800 x 168.

**Words:** about 11.

**Empty states.**
- No points: the cell is a muted `·` with `no price on file; Refresh on Prices`.
- No model: no bar and no dot.
- No street target: no ring.
- Neither: no gutter, and the line takes the width.

### M3. Where {forward_12m} comes from (band 2, right, 7/12)

**Section.** `Where 192.49 comes from`, with the chip `$ a share · the price dashed, 157.70`.

**Steps.**
- AZN, 8 slots: marketed 89.61 (start) · pipeline +12.32 · launches +88.76 · to today +10.58 · debt and costs −19.44 · today 181.83 (end) · a year on +10.66 · 12 months 192.49 (end).
- LLY, 9 slots: 291.17 · +53.34 · lines +34.53 · +209.12 · +32.26 · −106.16 · 514.26 · +35.91 · 550.16. The price rule at 1,149.85 sits above every bar.

**Merges.** Each merged step's hover lists its parts through the new waterfall `tip`.
- `to today` = `carry_per_share`. Hover: `valued at 2025-12-31, carried 0.75y to the 2026-10-01 close` (from `valuation_anchor`, `years_to_price` and `price_date`).
- `debt and costs` = `growth_investment.per_share` + `net_cash_per_share` + `other_claims_per_share`. Each part is included only when truthy, the `_sotp_bridge` rule. Hover: `growth capital −3.62, net debt −15.28, other claims −0.55`.
- `a year on` = `equity_per_share × cost_of_equity − dps`. Hover: `7.6% cost of equity +13.83, less the 3.18 dividend`.

**Rules.**
- The pipeline step appears when `pipeline.n`, and the lines step when `lines.n`.
- `launches` is a hatched null step when `future.per_share` is None.
- `to today` is omitted when carry is falsy.
- When `net_cash_per_share` is None, `debt and costs` is a hatched null, the end bar reads `EV today`, and there is no `a year on` or 12 months.
- When `forward_12m` is None, the bridge stops at today.

**Reconcile, or draw nothing.** All three must hold to within 0.01:
- the `today` end equals `equity_per_share`;
- the 12-month end equals `sotp.forward_12m`;
- that value equals `fv.rating.forward_12m`.

Otherwise the chart is not drawn and one muted line reads `_KI_NO_BRIDGE`.

**Sources.** `verdict.sotp`:
- `marketed.{n, per_share}`, `pipeline.{n, per_share}`, `lines.{n, per_share}`, `future.per_share`, `growth_investment.per_share`;
- `carry_per_share`, `net_cash_per_share`, `other_claims_per_share`, `equity_per_share`;
- `cost_of_equity`, `dps`, `forward_12m`, `close`, `valuation_anchor`, `years_to_price`, `price_date`.

**Builder.** `_ki_bridge(sotp, forward_check)`, then `CH.waterfall(steps, 800, 190, value_fmt=2dp, reference={"label": None, "value": sotp["close"]})`.

**Gate (modelled).** The verdict is ok, and (`verdict.per_share` or `streams` or `placeholders`) is truthy, and `sotp.marketed.per_share` is not None. This is `_book`'s own gate. BAYN has `marketed.per_share` 0.0 and `per_share` 0.0, so it fails the gate and draws no zero bridge.

**Words:** about 30.

### M4. What it rests on, and what would break it (band 2, left, 5/12)

**Section.** `What it rests on`, with the chip `$ a share`.

**Rows.** Five rows ranked by $ a share across counted modelled assets, revenue lines and launches past the pipeline.

| Row | Bar | Value | Meta |
|---|---|---|---|
| Launches past the pipeline | MUTED hatch | 88.76 | `from R&D` (hover: `valued at 0.364 of revenue per R&D dollar, first launch 2026`, from `future.rate_used` and `first_launch_year`) |
| Tagrisso | UP | 10.29 | `LOE 2032` |
| Imfinzi | UP | 8.89 | `LOE 2031` |
| Ultomiris | UP | 7.63 | `LOE 2035` |
| Symbicort | UP | 7.04 | `lapsed` |
| tail | | `50 more · 68.07` | |

- A pipeline row has a PURPLE_BOOK bar and the meta `PoS 88%` in purple.
- A line row has a bar in `_mix(MUTED, GROUND, .5)` and the meta `line`.
- The tail value is the operating sum (marketed + pipeline + lines + future, per share) less the shown rows. It equals the rest's sum: AZN 68.07, LLY 97.23.

**Breaks sub-block.**
- Caps sub-label:
  - direction down: `Today's 181.83 meets the 157.70 price at`;
  - direction up: `The 1,149.85 price needs`.
- Then the two nearest reachable levers:
  - AZN: `▼ every discount rate 7.47% → 8.35%`, `▼ launch productivity 0.364 → 0.312`.
  - LLY: `▲ uncapped growth fade 5.7y → 8.7y`, `▲ every discount rate 7.99% → 4.05%`.
- The lever name is `lever` for company scope and `{name}'s {lever}` for asset scope.
- Hover on the sub-label: the whole of `sentence.body`, including the joint-failure sentence (AZN: worth $173.98 if its obesity agents fail together).
- Hover on each row: `{evidence} · {evidence_class}`.

**Sources.**
- `verdict.modelled[].{name, per_share, counted, is_marketed, pos, loe_year, loe_in_base}`.
- `verdict.streams[].{line, per_share}`.
- `verdict.sotp.future.{per_share, rate_used, rate, first_launch_year}`.
- `_breakpoints`:
  - top level: `{ok, direction, equity_per_share, close, sentence.body}`;
  - `levers[].{name, lever, scope, kind, key, model, break, reachable, distance, evidence, evidence_class, shown}`.
- Levers are sorted by `distance`.
- Formatting is `_ki_lever_text`, a copy of `_lever_value` under the `_ki_` prefix:
  - launch_rate prints as `0.364`;
  - a scale lever with a single `shown` asset prints its percentages, as `_what_breaks_it` does.

**Builders:** `_ki_rests_on`, `_ki_rests_html`, `_ki_breaks`, `_ki_breaks_html`, `_ki_lever_text`.

**Words:** about 40.

**Empty states.**
- No counted asset: `No modelled asset is counted yet.`
- Breakpoints not ok, or no reachable lever: the sub-block is left out. There is no placeholder; Forecast holds the reason.
- A lever whose break is None is never shown.

### M5. Not modelled (band 2, when the gate fails)

One row across both columns holds a muted line, `_KI_NOT_MODELLED`: `Nothing is modelled for {T} yet, so there is no 12-month value. Forecast starts one.`

When `record.periods.FY1.eps` and `FY2.eps` exist, a figure row `What the street expects` follows:
- `9.37` / `FY2026 EPS, 6 estimates`
- `10.55` / `FY2027 EPS, 7 estimates`
- growth `+12.6%`

These are street figures only, never chained to reported EPS. BAYN has neither, so it gets the line alone.

**Builder:** `_ki_street_expects(record)`.

**Words:** 25 or fewer.

### M6. Drivers, risks and catalysts (band 3, full width)

**Section.** `Drivers, risks and catalysts`, with the chip `next 24 months · Catalysts has them all`.

**Axis.** The track is 1400 x 136 and runs from today (`board["today"]`, the same as Catalysts) to 24 months ahead.
- A TEXT dashed rule marks today.
- A RULE_STRONG dashed rule marks 12 months, labelled `12 months`.
- Quarter ticks are labelled `Jan 27`.

**Above the axis: drivers.** The first four rows of `DRV.rank_events(context)`, the head of the Catalysts Drivers list.
- Label: `row.asset`.
- Sub: `row.lead · Phase 3` when `row.model`, else `row.event`.
- Marks:
  - value: an UP disc, r = 3 + 4·sqrt(pct / max pct);
  - regulatory (tier 1): a FLAG diamond, 7 px;
  - readout: a TEXT ring when estimated, a TEXT disc when dated.
- Every other ranked event in the next 12 months is a 2 px MUTED dot on the axis. These dots are unlabelled; the hover is the row's `line`.
- AZN shows 4 labelled marks plus 20 dots. LLY's first label is Retatrutide, with an UP value mark and the sub `$33.42 · Phase 3`.

**Below the axis: risks.** The dated rows of `DRV.risk_parts(company, context, feed, today)[0]`, up to four.
- Exclusivity: a filled DOWN triangle at `row.date`. Label `{asset} LOE`, sub `{share_text} of revenue`.
- Slip: a hollow DOWN triangle at `row.new`. Label `nct_id`, sub `slips {days} days`.
- AZN: Lynparza LOE 5.6% (8 Sep 2027), NCT06455449 slips 241 days (Jan 2028), Koselugo LOE 1.1% (13 Mar 2028), NCT07775404 slips 307 days (Apr 2028).

**Under the track.** At most one undated (pool) risk, as an existing `.ki-ev` row: `73% kept  Obesity: 2 candidates in a 19-drug pool (model)`.

**Placement.**
- A day-precision date sits on its day.
- A month, quarter or half sits mid-period.
- Every hover says `est.` where the date is estimated (`row.date_text`).
- A date past 24 months pins to the right end with `→ Mon YY`.
- Labels use two tiers per side, shifted right greedily as in `approvals_timeline`.

**Sources.**
- The context, through `DRV.rank_events` rows: `{asset, event, lead, model, tier, date, precision, estimated, date_text, pct_of_price, line}`.
- `DRV.risk_parts` rows: `{kind, lead, line, date, new, asset, share_text, nct_id, days}`.
- These draw on `scorecard.companies[T].exclusivity_losses` and on the feed's high `date_slip` rows.

**Builders:** `_ki_track_items(events, risks, today, labelled=4)` returns (items, undated); `CH.event_track` (new).

**Words:** about 55.

**Empty states.**
- Context failed: the track draws risks only, plus the muted `DRV.CONTEXT_FAILED`.
- No event and no risk: one muted `DRV.EMPTY` line and no track.
- Only undated risks: no track, just the rows.
- `context.complete is False`: the muted line `Model values are still being computed. Reload in a minute.`

### M7. Against {n} {noun} (band 4)

**Section.** `Against 18 big pharma`, with the chip `7th of 18 · score 58 · range 2–11 · right is better`. The chip is built from `rank`, `ranked_of`, `score` and `range_text`. For an unscored company, the chip is `reason_text`, or the sentence.

**Column anatomy.** Three columns, one anatomy:
- a caps sub-label;
- a figure line (mono 20 figure, unit, an inline delta and a muted place);
- a 48 px picture;
- two peer rows.

**Peer row.** It has three parts:
- the short label, with the full `method.metrics[id].label` on hover (130 px);
- a dot strip (150 px), from `CH.peer_dots`;
- the value in mono TEXT and the place in mono, toned like the focal dot (`3rd worst of 12`).

**Dot strip.**
- Dots: every cohort member whose `pillars[pid].metrics[id].value` is not None (`scorecard.companies[*]` where `cohort` matches).
- Domain: min to max, padded 6%. It is reversed when `method.metrics[id].better == "lower"`, so right is always better.
- Median tick: `cohort.metric_medians[id]`.
- Focal dot: UP when `metric.score` is 75 or more, DOWN at 25 or less, else TEXT.
- Each dot carries `<title>{ticker} {text}`.

**Financials.** Cohorts with growth, profitability and balance sheet.
- Figure: `58.7` with the unit `bn USD revenue, FY2025`, the delta `+8.6%` (UP), and the place `4th of 17`.
  - Level and delta come from `verdict.reported_revenue[-1]` and `[-2]` (mm, in the reporting currency). The delta is printed only for consecutive years.
  - Currency is `record.reporting_currency`: BAYN EUR, NVO DKK.
  - Place is from `growth.rev_growth.{place, n}`.
- Picture: `CH.bar_chart` (vertical, reused) of the last five fiscal years.
  - A missing year inside the range is None, so it draws hatched.
  - Earlier years are `_mix(MUTED, GROUND, .45)`; the latest is UP and shows its value.
- Rows:
  - profitability: the first metric with a value of `op_margin`, `pretax_margin`, `fcf_margin` (LLY: `Pre-tax margin 39.5% 2nd of 17`, because op_margin is null);
  - balance sheet: `nd_ocf`, else `net_cash_rev`. The commercial cohort uses `runway`.
- Clinical cohort: the title is `Funding`. The figure is runway text and place (CRSP `77 months · 2nd of 28`), there is no picture, and the row is `share_change`.

**Pipeline.**
- Figure: `92` with the unit `compounds in trials` and the place `23 late-stage · 2nd of 18`.
  - The count is from `record.detail.pipeline.compounds`. It equals the Pipeline tab's /programmes count: AZN 92, LLY 85, BAYN 19, all checked.
  - The place is from `late_compounds`; the clinical cohort uses `mid_late_compounds`.
- Picture: `CH.share_bar` (new) by furthest phase: Phase 1, Phase 1/2, Phase 2, Phase 3 (Phase 2/3 folded in), and Phase 4 in MUTED.
  - Colours: PHASE_RAMP. Phase 1/2 is `_blend(Phase 1, Phase 2, .5)`.
  - Labels `P1 27`, `P1/2 28`, `P2 12` and `P3 23` appear where a segment is 40 px or wider.
- Rows:
  - `late_per_rev`, shown as `Late-stage per $10bn 3.9 3rd of 18`;
  - when modelled with `pipeline.n` > 0, a text row from `sotp.pipeline.per_share` and `per_share_unrisked`: `12.32 a share after PoS, 23.73 before`.
  - The clinical cohort uses `trial_conc`.

**Marketed products.**
- Figure: `4.6` with the unit `years of exclusivity left` and the place `8th of 17` (`durability.loe_years`).
- Picture: `CH.share_bar` of `record.detail.products.rows`, the top five by `value_usd_m`, plus `rest` = `periods.FY0.revenue_usd_m` less those five.
  - This applies only when `products.fiscal_year` matches FY0's year; otherwise the label reads `of product revenue on file`.
  - AZN: Farxiga 14.3%, Tagrisso 12.3%, Imfinzi 10.3%, Ultomiris 8.0%, Calquence 6.0%, rest 49.0%. This matches the Portfolio donut.
  - Shades: `_blend(UP, GROUND, t)`. The rest is RULE_STRONG.
- Rows:
  - `top_product`, shown as `Top product share 14% 6th of 17`;
  - `fresh_share`, shown as `New-launch revenue 7% 4th worst of 17`.
- Commercial cohort (no durability pillar): the figure is the top product's share (`41% of revenue from {name}`), and there are no rows.
- Clinical cohort: the title is `Lead asset`. The figure is `facts.lead_phase.text`, and the row is `facts.partner_on.text`.

**Short labels.** Kept in `_KI_SHORT`:

| Metric id | Short label |
|---|---|
| op_margin | Operating margin |
| pretax_margin | Pre-tax margin |
| fcf_margin | FCF margin |
| nd_ocf | Net debt / cash flow |
| net_cash_rev | Net cash / revenue |
| runway | Cash runway |
| late_per_rev | Late-stage per $10bn |
| fresh_share | New-launch revenue |
| top_product | Top product share |
| trial_conc | Trial concentration |
| share_change | Share count change |

**Builders.**
- `_ki_columns(board, ticker, record, verdict)` uses `_ki_metric`, `_ki_peer_row`, `_ki_rev_bars`, `_ki_phase_segments` and `_ki_mix_segments`.
- Then `_ki_column_html`.
- Charts: `CH.bar_chart` (reused), `CH.share_bar` (new), `CH.peer_dots` (new).

**Words:** about 55 visible at 1440 x 900; about 85 for the whole band.

**Empty states.**
- A metric with a None value prints its label and a muted `·`, with the reason on hover (`method.reasons[reason]`, or `reason`), and no strip.
- No product rows: the picture is a muted `·` with `no product revenue on file`.
- Scorecard failed: band 4 is one muted line, `_KI_FAILED`.

### M8. What changed (foot, left 5/12)

The tab keeps `_ki_changes`, `_ki_change_row` and `_ki_changes_basis`, and shows three rows. One change: `_ki_changes` gains `skip_ncts=()`. A row whose headline names an NCT id already drawn on the track is skipped, so a slip is not said twice. The basis counts the filtered list.

**Empty state:** `_KI_NO_CHANGES`.

### M9. Note, Generate, Tearsheet (foot, right 7/12), then China BD

**Content.**
- A row of two tertiary buttons, `Generate` and `Tearsheet`, sits above the folded expander `_ki_note_label(written)`.
- The buttons are created before the expander in script order, so `regenerate` is known when the note is read. Generate still opens the expander on the run that wrote the note.
- The tearsheet byline sits under the buttons.
- Inside the expander, the prose is held to 68ch.
- `_china_bd` stays folded, last, at full width.

**States and words.** Unchanged from today. About 8 words while folded.

## 4. Builders

### 4.1 `frontend/components/charts.py`

All are pure. Each returns `""` when there is nothing to draw. Colours come from TK, or from `_blend` of TK colours. A null is never drawn as zero, and every mark has a `<title>`.

```python
def price_call(closes: Sequence[Optional[float]], dates: Sequence[str], close: Optional[float],
               model: Optional[dict] = None,    # {mid, low, high, tone: "up"|"down"|"neutral", tip}
               street: Optional[dict] = None,   # {value, tip}
               width: int = 800, height: int = 168,
               value_fmt: Callable[[float], str] = None) -> str: ...

def event_track(items: Sequence[dict], today, months: int = 24, width: int = 1400,
                height: int = 136, mark_months: int = 12) -> str: ...
# item: {date, side: "above"|"below", kind: "value"|"regulatory"|"readout"|"minor"|"loss"|"slip",
#        estimated: bool, precision: "day"|"month"|"quarter"|"half", label, sub, tip, weight}

def peer_dots(peers: Sequence[dict], focal: dict, better: str = "higher", width: int = 150,
              height: int = 18, median: Optional[float] = None,
              tone: Optional[str] = None, label: str = "") -> str: ...
# peers/focal: {ticker, value, text}; right is better; ties offset ±4px

def share_bar(segments: Sequence[dict], width: int = 440, height: int = 34, bar_h: int = 10,
              min_label_px: float = 40, label: str = "") -> str: ...
# segment: {value >= 0, colour, label, sub, tip}; 1px GROUND gaps; labels cut to fit

def waterfall(...)   # unchanged signature; a step may carry "tip", drawn as <title> in its rect
                     # (a null step keeps "no free data" and appends the tip)
```

Reused unchanged: `bar_chart` (vertical, for the revenue columns), `_downsample`, `DRV.rank_events`, `DRV.risk_parts`, `change_row`, `note_html`, `state` and `_china_bd`.

### 4.2 `frontend/streamlit_app.py`: pure builders

These use the `_ki_` prefix and only `html`, `re`, `dt` and other `_ki_` names, so the AST harness runs them. They emit CSS classes, and colour keys for SVG segments. The renderer maps keys to TK.

```python
_ki_money(v, decimals=2) -> str                          # "1,149.85", "−19.44", "·" for None
_ki_year_series(points: list, days: int = 365) -> dict   # {closes, dates, close, as_of, day_move, year_move, low, high}
_ki_call(rated: dict, fv_reason, series: dict, street: dict | None) -> dict
        # {source: "model"|"street"|None, key, word, word_tone, value, move, move_tone, sub, tip, note}
_ki_figures(series, call, momentum: dict | None, street: dict | None,
            multiple: dict | None, multiple_place: dict | None) -> list   # [(value, key, tone, tip)] x4
_ki_call_html(call: dict, figures: list) -> str          # <div class="pos ki-call">…<div class="ki-figs">
_ki_bridge(sotp: dict, forward_check: float | None = None) -> dict   # {ok, steps, reason}
_ki_rests_on(verdict: dict, shown: int = 5) -> dict      # {rows:[{name,value,kind,meta,tip}], more_n, more_value, top}
_ki_rests_html(rests: dict) -> str
_ki_lever_text(kind: str, value, key: str = "") -> str
_ki_breaks(bp: dict | None, shown: int = 2) -> dict      # {head, rows:[{glyph,name,model,brk,tip}], tip} or {}
_ki_breaks_html(breaks: dict) -> str
_ki_street_expects(record: dict) -> list
_ki_track_items(events: list, risks: list, today, labelled: int = 4) -> tuple   # (items, undated)
_ki_metric(company: dict, pillar_id: str, ids: tuple = ()) -> dict | None
_ki_peer_row(board: dict, ticker: str, pillar_id: str, metric: dict) -> dict
        # {id, label, full_label, text, place_text, value, better, median, tone, peers, reason}
_ki_rev_bars(reported: list, n: int = 5) -> list         # [{label "FY25", value | None, latest}]
_ki_phase_segments(compounds: dict) -> list              # [{value, key, label, sub, tip}]
_ki_mix_segments(products: dict, fy0: dict, shown: int = 5) -> list
_ki_columns(board: dict, ticker: str, record: dict, verdict: dict | None) -> list   # 3 column dicts
_ki_column_html(col: dict, picture_svg: str, strip_svgs: list) -> str
_ki_section_html(label: str, basis: str = "") -> str     # the same markup section() writes
_ki_band_html(cells: list, layout: str = "2col") -> str
_ki_changes(feed, ticker, today, skip_ncts=()) -> list   # extended
```

**Kept:** `_ki_attr`, `_ki_signed_pct`, `_ki_month`, `_ki_day`, `_ki_product`, `_ki_words`, `_ki_headline`, `_ki_change_row`, `_ki_changes_basis`, `_ki_note_label`, `_KI_FAILED`, `_KI_NO_CHANGES`, `_KI_EMPTY` and `_KI_MINUS`.

**Removed:** `_ki_strip_cells`, `_ki_strip_html`, `_ki_pillar_rows`, `_ki_lines_pick`, `_ki_lines_html`, `_ki_next_basis`, `_ki_next_html`, `_KI_LINES_SHOWN`, `_KI_PROSE_WORDS`, `_KI_SEPARATOR`, `_KI_NO_LINES`, `_KI_NEXT_SHOWN` and `_KI_NO_NEXT`.

**New constants:**
- `_KI_SHORT`
- `_KI_RESTS_SHOWN = 5`
- `_KI_BREAKS_SHOWN = 2`
- `_KI_TRACK_LABELLED = 4`
- `_KI_RISKS_LABELLED = 4`
- `_KI_TRACK_MONTHS = 24`
- `_KI_NOT_MODELLED`
- `_KI_NO_BRIDGE = "The bridge does not add up here; Forecast has it in full."`
- `_KI_NO_ASSET = "No modelled asset is counted yet."`

### 4.3 Renderer outline, `_key_insights_tab(api_base, ticker, feed, prices)`

1. Load DRV as today. Read the payload once, and from it the record, board, company and cohort (as today).
2. Read fair value. Build series, call and figures, then `CH.price_call`. Emit band 1.
3. Read the verdict and apply the gate. If modelled: `_ki_bridge`, then `CH.waterfall`; `_breakpoints`, then `_ki_breaks`; and `_ki_rests_on`. Otherwise use `_ki_street_expects`. Emit band 2.
4. Read the context. Build events, risks and items, then `CH.event_track`. Emit band 3, plus the undated row and any notes.
5. Build `_ki_columns`. The pictures come from `CH.bar_chart` and `CH.share_bar`, and the strips from `CH.peer_dots`, with colour keys mapped by a local dict. Emit band 4.
6. Foot: `st.columns([5, 7])`. What changed goes left. The buttons, the tearsheet byline and the note expander go right.
7. `_china_bd`.

The renderer must not read or set `_BOOK_UNIT`.

## 5. CSS (frontend/assets/research.css, all `.ki-`)

- `.ki-band`: grid, 32 px column gap. `.ki-band.c2` is `5fr 7fr`; `.ki-band.c3` is `repeat(3, minmax(0, 1fr))`. `.ki-band + .ki-band` adds 24 px. Below 1180 px, `@media` sets one column.
- `.pos.ki-call { display: block }`. `.ki-k` is a 10px caps key. `.ki-lead` is a flex baseline with a 12 px gap. `.ki-word` is 24/700, with `.up`, `.down` and `.neutral`. `.ki-fig` is 28 px mono. `.ki-move` is 15 px mono. `.ki-sub` is 11.5 px MUTED.
- `.ki-figs`: `repeat(4, minmax(0, 1fr))`, gap 16. `.ki-f .v` is 15 px mono; `.ki-f .k` is 10.5 px MUTED, two lines at most.
- `.ki-bk`: grid `minmax(0, 1fr) 120px 56px 64px`, 22 px rows, a RULE hairline, and 8 px bars with the modifiers `.m` UP, `.p` var(--purple-book), `.l` and `.f` hatch. `.ki-bk-more` is the tail.
- `.ki-brk-h` is a caps sub-label. `.ki-brk` is a grid of `12px minmax(0, 1fr) auto` with mono values.
- `.ki-col`. `.ki-col-h` is the caps sub-label. `.ki-col-fig` is 20 px mono with a unit and a muted place. `.ki-peer` is a grid of `130px 150px minmax(0, 1fr)` in 22 px rows.
- `.ki-note .byline, .ki-note p { max-width: 68ch }`.
- Retire `.ki-strip`, `.ki-sentence`, `.ki-bars`, `.ki-lines`, `.ki-line` and `.ki-next`.

## 6. States by company

| State | Band 1 | Band 2 | Bands 3 and 4 |
|---|---|---|---|
| Modelled (21 of 70: 17 of 18 big pharma, CRSP, INCY, MRNA, UTHR) | model lead, gutter | bridge, rests, breaks | full |
| Street target, no model (most of the other 49; 66 of 70 have a target) | street lead, `not modelled` | M5 line, plus street EPS when on file | full |
| Neither (BAYN, ADAPY, SGMOQ; ROG is modelled with no target) | `·` lead | M5 line | full |
| Clinical cohort | as the model state | as the model state | Funding / Pipeline / Lead asset columns |

## 7. Acceptance checks

### General

- **G1.** No new endpoint. In AppTest with `api_get`, `_breakpoints`, `_comps_context` and `_comps_valuation_payload` wrapped, the tab makes these reads and no others: the payload, fair-value, forecast-verdict (the exact path string `_book` uses), `_breakpoints`, comps-context and the note.
- **G2.** Band 1's markdown is emitted before the verdict read, checked by element order.
- **G3.** Every figure traces to a field named in its module. Fixtures with nulls draw `·` with a reason in `title`, never a 0. That covers net cash None, future None, op_margin None, no target and no points.
- **G4.** No em dash and no banned word, in every string the builders emit for the AZN, LLY, BAYN and CRSP fixtures. Labels are sentence case.
- **G5.** Every fill and stroke in the new SVGs is a TK colour or a `_blend` of two.
- **G6.** `.pos` is present on the page.
- **G7.** The bridge reconciles for every modelled company: the today end matches `equity_per_share`, and the 12-month end matches `fv.rating.forward_12m`, each to within 0.01. Otherwise the tab shows `_KI_NO_BRIDGE`.
- **G8.** The track's labelled drivers are `DRV.rank_events(context)[:4]` in order. Its labelled risks are the dated rows of `DRV.risk_parts(...)[0]`. So Key insights and Catalysts never disagree. Tests compare against the function, not against names, because the AZN head moved from Elecoglipron to Truqap between 1 and 2 Oct.
- **G9.** Word budget, by the E5 counter:
  - first screen at most 250 at 1440 x 900, and at most 290 at 1600 x 1000, for AZN, LLY and CRSP;
  - whole tab at most 340, folded content excluded.
- **G10.** The tab's own Python, with warm caches and the network excluded, runs under 300 ms. Full-page time on a warm backend stays within 10% of today's.
- **G11.** At a 1280 px viewport there is no horizontal scroll. At 1180 px every band is one column.

### AZN, first screen at 1440 x 900

- **Call:** `Buy` in UP, `192.49`, `+22.1%`, and `against 157.70 · 163 to 231 in 12 months`.
- **Cells:**
  - `157.70` / `close · −2.3% today`
  - `−6.5%` / `1 year · −24 points vs XLV`
  - `211.63` / `street · 14 buy, 2 hold`
  - `4.6×` / `EV to sales · median 4.7×`
- **Chart:** a gutter bar from 163.44 to 230.99, with the UP dot at 192.49 above the FLAG rule at 157.70, and the street ring at 211.63.
- **Bridge:** 89.61, +12.32, +88.76, +10.58, −19.44, 181.83, +10.66 and 192.49.
- **Rests:** Launches past the pipeline 88.76 · Tagrisso 10.29 LOE 2032 · Imfinzi 8.89 LOE 2031 · Ultomiris 7.63 LOE 2035 · Symbicort 7.04 lapsed · `50 more · 68.07`.
- **Breaks:** `Today's 181.83 meets the 157.70 price at`, then `every discount rate 7.47% → 8.35%` and `launch productivity 0.364 → 0.312`.
- **Track:** four labelled driver marks (rank_events[:4]) and the other events as dots. Below: Lynparza LOE 5.6% of revenue, NCT06455449 slips 241 days, Koselugo LOE 1.1% of revenue and NCT07775404 slips 307 days. The pool line sits under the track.
- **Band 4:** the rule and chip `7th of 18 · score 58 · range 2–11 · right is better`; the figures `58.7bn USD revenue, FY2025 +8.6% · 4th of 17`, `92 compounds in trials · 23 late-stage · 2nd of 18` and `4.6 years of exclusivity left · 8th of 17`; and three pictures.

### LLY

- **Call:** `Sell` in DOWN, `550.16`, `−52.2%`, and `against 1,149.85 · 469 to 656 in 12 months`.
- **Cells:** `1,149.85` / `close · −0.6% today`; `+39.3%` / `1 year · +22 points vs XLV`; `1,364.15` / `street · 20 buy, 2 hold, 1 sell`; `26.0×` / `P/E NTM · median 14.9×`.
- **Gutter:** the model bar and dot sit well below the price line.
- **Bridge:** includes `lines +34.53`, and ends at 550.16, under the rule at 1,149.85.
- **Rests:** Launches 209.12, Mounjaro 145.87, Zepbound 71.27, Retatrutide 33.42 `PoS 88%` in purple, Foundayo 31.25, and `35 more · 97.23`.
- **Breaks:** the head `The 1,149.85 price needs`, then `uncapped growth fade 5.7y → 8.7y` and `every discount rate 7.99% → 4.05%`.
- **Track:** the first label is Retatrutide, with an UP value mark. Trulicity LOE 6.6% sits below.
- **Band 4:** Financials row 1 reads `Pre-tax margin 39.5% 2nd of 17`. The mix starts Mounjaro 35.2%, Zepbound 20.8%.

### BAYN (nothing modelled, no target)

- **Call:** the key `12-month value` and a muted `·`. The hover reads `no value against a price: equity, shares or the close is not on file; no consensus on file`.
- **Cells:** `12.73` / `close · −5.7% today`; `+46.3%` / `1 year · +29 points vs XLV`; `·` / `street · no consensus on file`; `1.6×` / `EV to sales · median 4.7×`.
- **Chart:** the line only, with no gutter marks.
- **Band 2:** the one `_KI_NOT_MODELLED` line. No zero bridge is drawn: the gate catches marketed.per_share 0.0.
- **Track:** Kerendia (est. Apr 2027) and Nubeqa (est. Jul 2027) above. Kovaltry LOE 1.3% (16 Mar 2028) below.
- **Band 4:** fully on the first screen.
  - Chip: `18th of 18 · score 11 · range 17–18 · right is better`.
  - Financials: `45.6bn EUR revenue, FY2025 −2.2% · worst of 17`, with two columns (FY24 and FY25). Rows: `Operating margin −2.4% worst of 12` and `Net debt / cash flow 5.2× worst of 17`.
  - Pipeline: `19 compounds in trials · 1 late-stage · worst of 18`.
  - Marketed: the figure is a muted `·` with its partial-product-revenue reason. The mix shows Nubeqa 5.2% … rest 86.8%. Both rows are `·` with reasons.

### CRSP (clinical)

- **Call:** `Sell 35.18`, from fair-value; the comps record's `model.state` is not used.
- **Band 4:** the chip `10th of 30 clinical-stage biotechs`.
  - Funding: `77 months · 2nd of 28`.
  - Pipeline: `4 compounds in trials · 0 in Phase 2 or later · joint worst of 30`.
  - Lead asset: `Lead asset in Phase 1/2`, with `Shares Casgevy, VRTX's marketed drug`.

## 8. Word budget

Estimated for AZN at 1440 x 900: band 1 about 50, band 2 about 75, band 3 about 55, and the visible part of band 4 about 50. That makes about 230 on the first screen, against a budget of 250. The whole tab is about 310, against 340.

A missed budget is a bug. Cut in this order:
1. Drop the driver subs.
2. Drop the pool line.
3. Drop the street cell's ratings.

## 9. What leaves the tab, and where it lives

| Removed | Where it lives now |
|---|---|
| Four-cell strip | the call, and M1's cells |
| Sentence | band 4's chip and dots |
| Pillar bars | Comps > Companies; the evidence is in band 4's dot strips |
| Positives and negatives | the Comps company panel; the same facts are band 4's places |
| Next | the track's drivers |
| Generate and Tearsheet at the top right | the foot |

Value and momentum become M1's multiple cell and 1-year cell.

## 10. Tests, fixtures and docs

**Fixtures.** Capture slices for AZN, LLY, BAYN and CRSP into `backend/tests/fixtures/key_insights/`:
- fair-value;
- verdict, trimmed to `sotp`, `modelled`, `streams`, `reported_revenue`, `per_share`, `placeholders` and `ok`;
- breakpoints;
- comps record (`market`, `street`, `periods.FY0/FY1/FY2`, `detail.pipeline`, `detail.products` and `reporting_currency`);
- a scorecard slice with every cohort member's metric values;
- the last 400 price points;
- the feed.

Reuse `fixtures/drivers/ctx_*.json`.

**Tests to rewrite.**
- `backend/tests/test_insights_tab_ui.py`: the new builders; a `charts` section for `price_call`, `event_track`, `peer_dots`, `share_bar` and the waterfall tip; and the live AppTest checks from G1 to G9.
- Update the references to the strip, sentence, lines and Next in `test_scorecard_consistency.py`, `test_scorecard_copy.py` and `test_drivers.py`. The `test_drivers.py` check that Next is the head of the same list becomes: the track is `rank_events[:4]`.

**Docs.** Revise `docs/design/company-scorecard.md` sections 1.1 (the Key insights row), 1.2 (homes), 1.3, 5.3, 7.2 and 8.7 (the new budgets), and point them to this spec.

## 11. Risks

- **Two ranges on two tabs.** Forecast's rating tile prints today's range (155 to 218). The call prints the 12-month range (163 to 231). The sub must say `in 12 months`.
- **Breaks are against today, not the call.** Breakpoints solve against today's equity (181.83), not the 12-month 192.49. The head names `today's 181.83`, and its verb flips when the direction is up.
- **Launches past the pipeline are a model convention.** They make up 35 to 50% of value (AZN 88.76 of 190.69; LLY 209.12 of 588.16). They are labelled `from R&D`, with the rate on hover. Their breakpoint, launch productivity, is AZN's second lever.
- **Currencies.**
  - Per-share figures are USD. Foreign filers' figures are translated at `sotp.fx`.
  - Revenue levels are in the reporting currency, and the unit names it.
  - The mix and the dot strips are ratios, so unitless.
  - Never print the comps record's `*_usd_m` levels as Financials, or Key insights and the Financials tab will disagree.
- **Cold start.** The verdict, breakpoints and fair value pay their cold cost on this tab first, and `api_get` times out at 30 s. The backend warmer covers them, and each read sits behind its own try, with a muted dot when it fails.
- **Track crowding.** AZN has four estimated readouts between Oct and Dec 2026. The track needs two tiers, stems and hollow marks for estimates. Month- and quarter-precision dates sit mid-period, and the hover says `est.`.
- **Peer strips.** The axis reverses for lower-is-better measures, so the band chip says `right is better`. Tied values are offset 4 px.
- **Tests and spec change by design.** The tests assert the strip, the 75-word lines and Next. Rewrite them together with the build.