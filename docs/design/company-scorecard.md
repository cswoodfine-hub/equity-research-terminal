# Company scorecard: design specification

Revision 2, 2026-10-01. Written for the engineers who build it, in parallel. It replaces the
Valuation view of the Comps tab (docs/design/comps-valuation.md, revision 3 in section 12) as the
tab's first view, moves Drivers and risks to the Catalysts tab, and rebuilds Key insights as the
company's one-page summary. The valuation bridge on the Forecast tab (comps-valuation.md 12.5) is
not touched.

The user's request, in their words (the full text is in
`work-keep/company_scorecard_brief.md`): "in the comps tab i feel like theres too much words and
not enough clarity ... a similar scoring system that encapsulates all aspects of the company ...
like growth etc M&A activity ... in like a positive light ... as a score that can then be
visualized somehow against the other ones ... the main thing should be like a visual comparison
... if you like click on the specific company then it will give all the facts positives and
negatives ... click on like let's say three and then ... three column side-by-side but that will
only be if you press it ... the drivers of risks should be in the catalyst section and maybe we
could rethink the key insights".

"A similar scoring system" is the clinical scorecard on Comps > Indications
(`backend/landscape_score.py`, `charts.score_map`, `_landscape_scorecard`): two scores from 0 to
100 on one chart, the open company in green, a ranked table with a rank range beside it, words
only on demand.

Every number in this document was computed on a `.backup` of the live book taken 2026-10-01 08:06
and on `GET /comps/valuation` generated 07:05 UTC the same morning (prices to the 29 and 30 Sep
closes, section 2.8). The reference scripts are listed in Appendix A; they are throwaway code that
pins the method, not product code.

### What revision 2 changes

Revision 1 was reviewed on the day it was written. Every point of the review is answered in
Appendix C. The ones that changed the design:

1. **Business development and partnering are shown, not scored.** The deals the book holds for 24
   months still include stock ratings, ended collaborations, settlements, an insider share
   purchase, IT vendors and one deal under several names. Revision 1 counted 11 deals for GSK
   where a stricter read finds 7, and 5 of the 19 clinical companies credited with a partner owed
   it to an ending, a recital or a duplicate. A score built on that would rank companies on
   headline noise. Deals now sit in the company panel as facts, each with its headline and
   source, beside the firepower figure. They join the score once the deals reader is fixed
   (section 9, item 1).
2. **A measure is scored only when two thirds of the cohort have it**, a figure the payload flags
   as not like for like is not scored, and the product-revenue measures need product revenue on
   file for 60% to 110% of reported revenue. The commercial cohort loses its durability pillar to
   this rule (product revenue covers 7 of 22 companies).
3. **The rank range is a seeded interval**: where the rank falls in 90 of 100 random weightings of
   the pillars and of the measures inside them. Revision 1's best and worst rank with one pillar
   left out was narrower than the truth and let an unranked company into the variants.
4. **"Valuation" is now "Value"**, and the multiple itself is printed, never a score after a ratio's
   name. Exclusivity runway is now **Durability** (years of exclusivity left and reliance on the
   top product), so the bar no longer reads strong for a company losing a large product soon.
5. **Positives and negatives come from the business pillars only**, carry their period, and read
   "best" or "worst" in the cohort. Share price moves no longer lead the list.
6. **Key insights says each thing once**: the strip holds last close, model, the multiple against
   peers and the next exclusivity loss; Next is the first three rows of the Catalysts list.
7. **Comps shades the table** instead of printing about 125 pillar numbers; the number is on hover.
8. **Catalysts has one list.** Drivers are the events ahead, value-bearing first, Risks are
   exclusivity losses, slipped readouts and crowded patient pools. The calendar folds. Competition
   by indication stays on Comps > Indications. Drivers and risks is drawn in Python, so the
   compsval `drivers` mode of revision 1 is not built.

---

## 0. Decisions

1. **Three tabs, three questions.** Key insights: where does this company stand, and what changed.
   Comps: how does it compare with its peers. Catalysts: what could move it next. Each fact has one
   home (section 1.2).
2. **One scorecard, computed once, in Python.** `backend/company_score.py` scores all 70 companies
   and its output rides inside `GET /comps/valuation` as `scorecard`. Comps, Key insights and
   Catalysts draw the same numbers and print the same sentences. No score is computed in the
   browser.
3. **Fixed cohorts.** Big pharma (18), commercial-stage biotech and cell and gene (22),
   clinical-stage biotech and cell and gene (30). The peer set a reader edits changes the Table
   view, never a score.
4. **Business pillars.** Big pharma: growth, profitability, balance sheet, pipeline, durability.
   Commercial: growth, profitability, balance sheet, pipeline. Clinical: pipeline, funding. Value
   and momentum are scored the same way and drawn beside the business, never inside its score.
5. **Business development and partnering are facts in this build**: the deal list with its
   headlines and sources, and the firepower figure, in the company panel and in Compare. They join
   the score, as a pillar that can only lift a company, once the deals reader is fixed and
   reviewed (section 2.10).
6. **Ranks, not z-scores.** A metric becomes its mid-rank percentile in the cohort, turned so 100
   is always the better side. A metric is scored only when two thirds of the cohort have it. A
   pillar is the mean of its metrics, moved toward the cohort middle when some are missing. The
   company score is the mean of its business pillars, moved the same way. Equal weights.
7. **Uncertainty is a rank range:** where the rank falls in 90 of 100 random weightings of the
   pillars and of the measures inside them, seeded, so the same book gives the same range.
8. **One chart.** Company score across, value score up, bubble area for market cap, the open
   company in green, its rank inside each bubble, a ranked table with shaded cells beside it.
   Drawn by `charts.company_map`, which is `charts.score_map` with company captions, and shown
   inside the compsval frame so a bubble can be clicked.
9. **Detail only on demand.** Click a bubble or a row: the company panel, with every fact, its
   pillar scores, its positives and negatives, its deals. Tick up to three and press Compare:
   three columns side by side, opening on the scores and the lines, each pillar expanding to its
   measures.
10. **Positives and negatives come from the business pillars.** At most one of each per pillar,
    carried by the metric furthest past the quartile, number and period first ("8.6% revenue
    growth in FY2025, 4th best of 17 big pharma").
11. **Drivers and risks moves to Catalysts and becomes its one list.** Its metric half became the
    positives and negatives on Comps and Key insights. What moves is the event half, rebuilt in
    Python: events ranked as the Comps view ranked them, exclusivity losses, slipped readouts,
    crowded pools.
12. **Fewer words.** First screen, AZN at 1600 x 1000: Key insights 615 words today, at most 270;
    Comps 522, at most 260; Catalysts 628, at most 180 (section 8.7).

---

## 1. One design across the three tabs

### 1.1 What each tab says

| Tab | The question | First screen | No longer on it |
|---|---|---|---|
| Key insights | Where does this company stand, and what changed? | A strip of four figures (last close, model, multiple against peers, next exclusivity loss), one sentence, the pillar bars, up to three positives and three negatives, Next (the first three rows of the Catalysts list), the five newest high changes | the five-session sparkline, What happened, Dated ahead, the cells "12m value", "rating", "in development", "next loe" as a bare date, "N day", "flagged"; the morning note folds |
| Comps > Companies | How does it compare with its peers? | One chart of the cohort, the ranked table with shaded pillar cells beside it, one line on how to read it | the conclusion banner, "Why?", the KPI strip, Drivers and risks, the chart strip, the comparables table (one click away under Table) |
| Catalysts | What could move it next? | Drivers and risks: Drivers (events in 12 months, value-bearing first) beside Risks (exclusivity losses in 24 months, slipped readouts, crowded pools); At stake when a catalyst is priced | the calendar grid (folded under "Calendar, 24 months"), the six "unpriced" lines, Competition by indication (on Comps > Indications, where the comparison lives) |

The sub-tabs of Comps become **Companies**, Indications, Pipelines. Indications and Pipelines are
unchanged. (The "R&D against commercial performance" quadrant on Pipelines overlaps the new chart;
it stays, and section 9 lists it for a later decision.)

### 1.2 One home for every fact

| Fact | Its home | Shown elsewhere, as the same object | Said nowhere else |
|---|---|---|---|
| Company score, pillar scores, rank and range | Comps > Companies | Key insights sentence and bars; the company panel; Compare | |
| Positives and negatives | the scorecard (`scorecard.companies[T].positives`) | Key insights (up to three of each, within 75 words with the sentence), the company panel (all), Compare (first three) | Drivers and risks no longer states metric observations |
| The one sentence | the scorecard (`sentence`) | Key insights row 2; the company panel header | |
| The multiple against peers | the value pillar (`facts.multiple`) | Key insights strip cell "multiple"; the panel's Value row | the conclusion banner and KPI strip are gone |
| Value implied by peer multiples | Forecast, the bridge | | |
| Model fair value and rating | Forecast | Key insights strip cell "model" (same figures, labelled Model); panel Model values | |
| Events ahead | Catalysts, Drivers (12 months, one row per asset, ranked) | Key insights Next (the first three rows, the same list); panel Key catalysts; the folded calendar (24 months, by month) | |
| Exclusivity losses | Catalysts, Risks (24 months, share of revenue); Portfolio (the cliff) | Key insights strip "next exclusivity loss" (the first exclusivity row of Risks); the durability bar's note (years left) | |
| Deals and firepower | the company panel, Business development block (facts, not scored) | Compare, one row; Key insights What changed when a deal is new | not in the table, the chart or the score |
| Competition by indication | Comps > Indications | Catalysts Risks, one line per crowded pool | |
| Price | Prices | Key insights strip "last close"; the company panel | the Comps KPI strip is gone |
| The morning note | Key insights, folded | | the panel's "System-generated note" excerpt is gone |
| Snapshot changes | News (all) | Key insights What changed (five, high, no restatements) | the strip's "flagged" count is gone |

### 1.3 Key insights: the company on one page

Blocks, in order. Every number on the tab is a scorecard object, a figure the strip has always
read, or a catalyst or change row. Nothing is said twice: the strip holds what the bars and lines
do not, the sentence names pillars without their numbers (the bars carry those), and Next is the
head of the Catalysts list rather than a second ranking.

| # | Block | Content | Source | Words, AZN |
|---|---|---|---|---|
| 1 | Strip | four cells (below); Generate and Tearsheet at the right as today | as listed per cell | 26 |
| 2 | The sentence | `scorecard.companies[T].sentence`, Archivo 15 px, TEXT | scorecard | 18 |
| 3 | Company score | section head "Company score", basis "against {n} {cohort noun}"; `charts.pillar_bars`: the business pillars, a gap with the muted label "Price, not in the score", then value and momentum; the cohort median as a tick on each bar; durability carries the note "{y} years of exclusivity left" | scorecard pillars and cohort medians | 33 |
| 4 | Positives and negatives | section head "Positives and negatives"; up to three positives, then up to three negatives, one line each, "+" in UP or "−" in DOWN before each; where the sentence and the lines would pass 75 words (8.7) the longer side gives up its last line, never below two lines | scorecard lists | 55 |
| 5 | Next | section head "Next", basis "3 of {k} assets in 12 months, Catalysts has them all"; three lines, the value a share first where the event decides an unapproved asset's value, else the month: "$4.68  Elecoglipron · Phase 3 readout · obesity · est. Jun 2027", "est. Oct 2026  Truqap · Phase 3 readout · breast neoplasms" | `drivers.rank_events(context)[:3]`, the Catalysts list (section 5.4) | 30 |
| 6 | What changed | section head "What changed", basis "5 of {h} high in 30 days, News has them all"; five lines, newest first, the existing `change_row` markup without the leading ticker; rows of change type `revenue_restatement` and `rate_move` are left to News | the feed already read for the page, significance high | 62 |
| 7 | Morning note | an expander, folded: "Morning note · {layer} · {date}", the note and its byline inside, Generate beside it as today | `/companies/{t}/note` | 0 on the first screen |
| 8 | China-linked business development | last, in a folded expander "China-linked business development · {n} on file" (open, its rows put PFE over the budget at 1440) | `_china_bd` | 0 |

The strip, four cells, each `key / value / sub`, value first so a clipped sub never hides the
number:

| key | value | sub | Source |
|---|---|---|---|
| last close | 161.47 | −1.7% on the day | `prices` as today; the day move is `market.change_1d` of the company's `/comps/valuation` record |
| model | +19.5% | Buy, 193.03 in 12 months | `/fair-value` upside, rating and value as today; "·" and "not modelled" when not ok |
| multiple | 4.7× | EV to sales, median 4.8× | `scorecard.companies[T].facts.multiple`: the first of the value pillar's measures the company has, in list order, with the cohort median; "·" and "no multiple on file" |
| next exclusivity loss | Sep 2027 | 5.6% of FY2025 revenue, Lynparza | the first row of `scorecard.companies[T].exclusivity_losses` (24 months); "·" and "none in 24 months" |

AZN's P/E on the next 12 months is not shown because its FY1 estimates span 55% of their mean
(`estimate_range_wide`); EV to sales is the next measure in the list. LLY's cell reads "26.2×,
P/E NTM, median 15.1×".

**Drawing, AZN at 1600 x 1000.** The top bar and tab strip end at about y = 148; the tab content
is 1568 px wide.

```
y 150 ┌──────────────────────────────────────────────────────────────────────────────────────────┬───────────┐
      │ LAST CLOSE           MODEL                      MULTIPLE                  NEXT EXCLUSIVITY LOSS │ Generate  │
      │ 161.47               +19.5%                     4.7×                      Sep 2027             │ Tearsheet │
      │ −1.7% on the day     Buy, 193.03 in 12 months   EV to sales, median 4.8×  5.6% of FY2025       │           │
      │                                                                           revenue, Lynparza    │           │
y 218 ├──────────────────────────────────────────────────────────────────────────────────────────┴───────────┤
      │ AZN scores 58, 7th of 18 big pharma, range 2–11. Strongest on growth and pipeline, weakest on            │
      │ profitability.                                                                                          │
y 272 ├─ COMPANY SCORE  against 18 big pharma ────────────┬─ POSITIVES AND NEGATIVES ───────────────────────────┤
      │ Growth          ███████████████▍  |          77   │ + 23 late-stage compounds, 2nd best of 18 big pharma │
      │ Profitability   ██████▏    |                 31   │ + 8.6% revenue growth in FY2025, 4th best of 17 big  │
      │ Balance sheet   ██████████▉|                 55   │   pharma                                             │
      │ Pipeline        █████████████                65   │ − 23.4% operating margin in FY2025, 3rd worst of 12  │
      │ Durability      ████████████▌  4.6 years of       │   big pharma                                         │
      │                 exclusivity left             62   │ − 7% of FY2025 product revenue from drugs approved   │
      │ ─ ─ Price, not in the score ─ ─                   │   since 2021, 4th worst of 17 big pharma             │
      │ Value           █████████|                   46   │                                                      │
      │ Momentum        █▊        |                   9   │                                                      │
y 530 ├─ NEXT  3 of 25 assets in 12 months ───────────────┼─ WHAT CHANGED  5 of 10 high in 30 days ─────────────┤
      │ $4.68          Elecoglipron · Phase 3 readout ·    │ 28 Sep  AstraZeneca announces strategic equity      │
      │                obesity · est. Jun 2027             │         investment and clinical collaboration ...   │
      │ est. Oct 2026  Truqap · Phase 3 readout · breast   │ 25 Sep  Trial NCT06455449: primary completion slips │
      │ est. Nov 2026  Saphnelo · Phase 3 readout · lupus  │         2027-05-14 -> 2028-01-10                    │
      │                                                    │ 23 Sep  Truqap approved 2026-09-16                  │
      │                                                    │ 23 Sep  Tagrisso approved 2026-09-14                │
      │                                                    │ 23 Sep  Trixeo approved in the EU, asthma           │
y 770 ├────────────────────────────────────────────────────┴─────────────────────────────────────────────────────┤
      │ ▸ Morning note · gemini-flash-latest · 22 Sep 2026                                                         │
y 810 │ (China-linked business development, when present)                                                         │
```

Columns: 1.15 to 1 for blocks 3 and 4, the same split for 5 and 6. The bars are 300 px long at
this width; the tick on each bar is the cohort median. About 240 words on the first screen
(section 8.7). Streamlit cannot switch tabs from a Python link, so the tab carries
no "open in" links: each section's basis names the tab that holds the rest.

**Drawing, AZN at 1440 x 810.** The tab content is 1408 px wide and about 660 px tall.

```
y 150 ┌ LAST CLOSE        MODEL                     MULTIPLE                 NEXT EXCLUSIVITY LOSS  ┬ Generate ┐
      │ 161.47            +19.5%                    4.7×                     Sep 2027               │ Tearsheet│
      │ −1.7% on the day  Buy, 193.03 in 12 months  EV to sales, median 4.8× 5.6% of FY2025 rev…    │          │
y 214 ├ AZN scores 58, 7th of 18 big pharma, range 2–11. Strongest on growth and pipeline, weakest on ┘
      │ profitability.
y 262 ├─ COMPANY SCORE ─────────────────────────────┬─ POSITIVES AND NEGATIVES ───────────────────────┤
      │ seven bars, 24 px each, gap before price    │ four lines, wrapping to two at this width        │
y 500 ├─ NEXT ──────────────────────────────────────┼─ WHAT CHANGED ──────────────────────────────────┤
      │ three lines                                 │ five lines, the last cut at the fold             │
y 810 └─────────────────────────────────────────────┴──────────────────────────────────────────────────┘
```

At this size each strip sub is cut to one line (the CSS clamps it), and since every value comes
first the number always shows. Blocks 1 to 6 fit except the last line of What changed. About 190
words on the first screen.

**A clinical-stage company (CRSP).** Block 3 draws pipeline and funding, then value and momentum.
Block 4 prints the one positive it has; its pipeline lines are silenced because it shares a
marketed drug (section 2.12, rule 6). The multiple cell reads "2.3×, market cap to cash, median
2.1×". Next reads "No event dated in the next 12 months." (comps-context has none for CRSP; section
9, partnered catalysts). The exclusivity cell reads "·" and "none in 24 months".

**States.** No scorecard in the payload (the API's builder failed): blocks 2 to 4 are one state,
"The scorecard did not load: {error}.", and the strip's first two cells, Next and What changed draw
as usual. A company with no company score (ADAPY today): the sentence reads "ADAPY is not scored:
2 of 4 pillars have data, and a score needs 3." and the bars draw the pillars that exist.

What leaves the tab, and where it went: the sparkline (Prices owns price); What happened (deals to
the company panel and What changed, readouts to What changed); Dated ahead (Next, and Catalysts in
full); "12m value" and "rating" (one "model" cell); "in development" (the pipeline pillar's
panel); the five-year move (Prices); the "flagged" cell (What changed's basis).

### 1.4 Comps > Companies: the company against its peers

The sub-tab opens on the **Scorecard** view. A two-way switch at the right of the context bar,
"Scorecard | Table", opens the **Table** view, which is the current comparables table with its
toolbar, scope line, peer drawer and (folded) chart strip, unchanged in behaviour. The switch is
remembered in the browser like the other view settings.

In the Scorecard view the context bar shows the ticker, the name, the engine and stage chips, the
cohort ("Scored against 18 big pharma"), "Data as of 30 Sep", Compare, reload and help. The peer
set control, the period buttons and the Basis menu belong to the Table view and hide here, since
nothing in the Scorecard view reads them.

**Drawing, AZN at 1600 x 1000.** The compsval frame starts at about y = 210 and is fitted to the
viewport, about 780 px. Table cells are shaded, not numbered: in the drawing ▓▓ is a score of 75
or more and ▓ 60 to 74 (UP), ▒ 26 to 40 and ▒▒ 25 or less (DOWN), blank is 41 to 59 and "·" a
missing pillar; on screen the opacity grows continuously with the distance from 50 (3.2).

```
┌ AZN AstraZeneca PLC [Big pharma][Commercial]   Scored against 18 big pharma   [Scorecard|Table] [Compare 1] Data as of 30 Sep ⟳ ? ┐
├──────────────────────────── chart, 60% ────────────────────────────────────────┬──────────── ranked table, 40% ──────────────────┤
│ weaker, lower multiples                       stronger, lower multiples │       #  range co.   score      grow prof bal. pipe dur. value│
│ 100 ┬──────────────────────────────┬──────────────────────────────┐     │ ☐  1  1–10 VRTX ▇▇▇▇ 72   ▓▓   ▓▓   ▓▓             ▒▒  │
│     │                 ⑰BMY  ⑪SNY   │                              │     │ ☐  2  1–6  NVS  ▇▇▇▇ 69   ▓    ▓▓   ▓▓   ▓             │
│     │ ⑱BAYN                       ⑨GSK                            │     │ ☐  3  1–11 REGN ▇▇▇  65   ▒    ▓    ▓▓   ▓             │
│  75 ┤                    ⑬PFE      │                              │     │ ☐  4  2–11 NVO  ▇▇▇  65   ▓▓   ▓▓   ▓▓             ▓   │
│     │                  ⑮BIIB       │        ④NVO  ②NVS            │     │ ☐  5  1–12 LLY  ▇▇▇  63   ▓▓        ▒    ▓    ▓    ▒▒  │
│  50 ┼ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┼ ─ ─ ●⑦AZN ⑥ROG ③REGN─ ─ ─ ─ ┤     │ ☐  6  1–11 ROG  ▇▇▇  61   ·         ▓                  │
│     │                   ⑫GILD     │                              │     │ ☑  7  2–11 AZN  ▇▇▇  58   ▓▓   ▒         ▓    ▓        │
│  25 ┤              ⑯MRK ⑭ABBV ⑩AMGN│                              │     │ ☐  8  5–13 JNJ  ▇▇▇  54        ▓    ▓    ▒         ▒▒  │
│     │                              │  ⑧JNJ                        │     │ ...                                                    │
│   0 ┴──────────────────────────────┴───────────⑤LLY ①VRTX────────┘     │ ☐ 17 10–17 BMY  ▇▇   35   ▒▒                  ▒▒   ▓▓  │
│     0              25              50              75            100    │ ☐ 18 17–18 BAYN ▇    11   ▒▒   ▒▒   ▒▒   ▒▒   ·    ▓▓  │
│ weaker, higher multiples  company score → stronger  stronger, higher multiples │                                                │
│ ● every pillar scored  ○ some pillars missing  ◯ bigger: larger market cap  ● AZN    │                                          │
│ How to read it: right is a stronger business than its cohort, up is lower multiples. The number is the rank in the table.   │
│ Click a company for its facts; tick up to three to compare.                                                                   │
└───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

The chart is 760 x 480 in its own units and scales to its column (about 930 px wide at 1600, so
about 590 px tall). The table rows are 26 px; 18 rows fit with the header. A cohort of 22 or 30
scrolls inside the table, with the open company's row scrolled into view on first paint. With the
business development column gone and the cells unnumbered, the table needs about 40% of the frame
rather than 42%, and each shaded cell is about 65 px at 1600 and 55 px at 1440: wide enough
for the short headers of 3.2, with the full name in each header's tooltip.

**Drawing, AZN at 1440 x 810.** The frame is about 590 px tall. The context bar takes 44 px; the
chart (about 845 px wide, 535 px tall) and the table (about 560 px wide) share the rest. The
how-to-read line moves into the chart's key row as a "How to read it" tooltip at this height, so
nothing below the chart is cut.

```
┌ AZN AstraZeneca PLC [Big pharma][Commercial]  Scored against 18 big pharma  [Scorecard|Table] [Compare 1] ⟳ ? ┐
├──────────────── chart ────────────────────────────────────────┬──────────── ranked table ──────────────────┤
│ the chart, as above, 845 x 535                                 │ 18 rows of 24 px, the same columns         │
│ key row: ● every pillar ○ some missing ◯ market cap ● AZN  ⓘ   │                                             │
└────────────────────────────────────────────────────────────────┴─────────────────────────────────────────────┘
```

**On a click.** A bubble or a row opens the company panel over the table column; the chart stays,
the clicked bubble gains a TEXT ring. Esc or the close button returns. Section 4.1.

**Compare.** Each row has a box; the open company's is ticked when the view opens. "Compare {k}"
in the context bar is enabled from two ticks, and a fourth tick is refused with "Compare takes up
to three. Untick one first." Pressing it lays the three columns over the chart and the table until
closed. Section 4.2.

**Below the chart, when it applies:** "Not ranked: ADAPY (2 of 4 pillars, a score needs 3)." and
"Not on the chart: {T} (no value measure on file)." as one muted line each. ABEO, AUTL and QURE
are ranked but have no value measure (revenue under $100m), so they are listed on the second line.

**States.** The payload has no `scorecard` or it carries `error`: the view shows "The scorecard did
not load: {error}. The Table view still works." with a button to the Table view. The open company
not ranked: the chart and table draw its cohort, the company has no bubble, and its line under
the chart says why.

### 1.5 Catalysts: what could move it next

In order:

1. **Drivers and risks**, section head with basis "events in 12 months, exclusivity losses in 24 ·
   model output marked", drawn in Python (`_drivers_and_risks`, section 5.4). Two columns:
   - **Drivers**: the events of the next 12 months from comps-context, one row per asset, in the
     order the Catalysts ahead list of the Comps view used (ported to Python, 5.4): a priced stake
     first, then regulatory dates, then late-stage readouts that decide an unapproved asset's
     value, largest first, then the other late-stage readouts by date, then the rest by date. One
     change: a valued readout under 1% of the price falls to the dated group, so a $0.05 asset no
     longer outranks Enhertu's breast cancer readout. Five rows, "Show {n} more" opening the rest
     in place. A valued row leads with its value a share ("$4.68  Elecoglipron · Phase 3 readout ·
     obesity · est. Jun 2027"); a readout for a marketed drug leads with its month ("est. Oct 2026
     Truqap · Phase 3 readout · breast neoplasms"), because the drug's whole value is not at stake
     on one new indication. "est." marks every registry date; a month the registry gives without a
     day prints as the month.
   - **Risks**, in this order: exclusivity losses in the next 24 months with their share of FY0
     revenue ("5.6% of revenue  Lynparza exclusivity ends 8 Sep 2027"); readouts that slipped by
     90 days or more in the last 90 days, at most two ("241 days  NCT06455449 readout slips to Jan
     2028"); crowded patient pools from the comps-context competition rows, the rule of
     comps-valuation.md 12.3 ported ("73% kept  Obesity: 2 candidates in a 19-drug pool (model)").
     At most five rows, each under 15 words and number first. Exclusivity keeps at least three rows
     (more where slips and pools leave room): the next loss, which the Key insights strip names,
     then the largest by share of revenue, all printed by date, so PFE shows Eliquis (12.7%) over
     its fifth small loss. Rows left out fold under "Show {n} more", as Drivers do.
   - A column with no row is not drawn and the other takes the width. With both empty the section
     is one muted line: "No dated event or exclusivity loss on file for {T}."
2. **At stake**, only when a catalyst is priced: the priced rows with their met and missed buttons,
   unchanged. The unpriced lines ("unpriced: add pos_success, pos_failure on the Forecast tab") go.
3. **Calendar, 24 months**: an expander, folded, labelled "Calendar, 24 months · {n} dated events",
   holding the grid with its caption corrected (section 8.5) and then the rows behind it. Folded,
   it never shows the same events twice on one screen.

Competition by indication does not move here: it compares the company's indications with its
rivals', which is the Comps > Indications question. Its risk half arrives as the crowded-pool rows,
and each names the indication so the reader can open it there.

**Drawing, AZN at 1600 x 1000.**

```
y 150 ┌─ DRIVERS AND RISKS  events in 12 months, exclusivity losses in 24 · model output marked ───────────────┐
      │ DRIVERS  25 assets in 12 months                         │ RISKS                                       │
      │ $4.68          Elecoglipron · Phase 3 readout · obesity │ 5.6% of revenue  Lynparza exclusivity ends   │
      │                · est. Jun 2027                          │                  8 Sep 2027                  │
      │ est. Oct 2026  Truqap · Phase 3 readout · breast        │ 1.1% of revenue  Koselugo exclusivity ends   │
      │ est. Nov 2026  Saphnelo · Phase 3 readout · lupus       │                  13 Mar 2028                 │
      │ est. Nov 2026  Enhertu · Phase 3 readout · breast       │ 241 days  NCT06455449 readout slips to       │
      │ est. Dec 2026  Fasenra · Phase 3 readout · asthma       │           Jan 2028                           │
      │                                                         │ 364 days  NCT06921785 readout slips to       │
      │ Show 20 more                                            │           Mar 2030                           │
      │                                                         │ 73% kept  Obesity: 2 candidates in a 19-drug │
      │                                                         │           pool (model)                       │
y 440 ├─ AT STAKE (only when a catalyst is priced; none for AZN) ────────────────────────────────────────────┤
y 450 ├─ ▸ Calendar, 24 months · 72 dated events ───────────────────────────────────────────────────────────┤
```

About 125 words on the first screen for AZN, against 628 today. LLY's Drivers lead with Retatrutide
("$33.51  Retatrutide · Phase 3 readout · obesity · Nov 2026", a month the registry gives without
a day, so no "est."), then Zepbound and Foundayo, also Nov 2026; its Risks hold Trulicity (6.6% of
revenue, 31 Dec 2027). CRSP has no event, exclusivity loss or
crowded pool on file, so the section is the one muted line, and its At stake row (Casgevy, priced
through VRTX's model) and the folded calendar follow.

---
## 2. The method

### 2.1 Cohorts

A score says "against these companies", so the cohort is the first decision and it is fixed: the
same for every reader on every day, never the peer set a reader edits.

| Cohort id | Label (chip) | Noun (in sentences) | Rule | n today |
|---|---|---|---|---|
| `big_pharma` | Big pharma | big pharma | `engine == "pharma"` and `stage == "commercial"` | 18 |
| `commercial` | Commercial biotech and cell and gene | commercial-stage biotechs | `engine in ("biotech", "cellgene")` and `stage == "commercial"` | 22 |
| `clinical` | Clinical-stage biotech and cell and gene | clinical-stage biotechs | `stage == "clinical"`, any engine | 30 |

`stage` is the record's own field (`runway.stage()`: commercial once product revenue is filed). A
company whose first approval has not yet reached a filing stays clinical until it does (ARWR,
approved Nov 2025 with a September year end; RVMD, approved Aug 2026); section 2.9 says how the
approval shows. Collaboration revenue alone does not move a company: BEAM, IPSC and STOK book over
$100m of it and have no product.

Why not the comps view's default peers (same engine and stage, five cells)? Cell and gene
commercial is 8 companies: one place is 14 points, one peer moves a score by that much. Folding it
into commercial biotech gives 22. The two clinical cells score on pipeline and funding, neither of
which depends on modality, so they are one cohort of 30. And a score that moved when someone
toggled a peer could not be shown on Key insights as the same number, or snapshotted.

Members today. Big pharma: ABBV, AMGN, AZN, BAYN, BIIB, BMY, GILD, GSK, JNJ, LLY, MRK, NVO, NVS,
PFE, REGN, ROG, SNY, VRTX. Commercial: ABEO, ADAPY, ALNY, ARGX, ATRA, AUTL, AXSM, BMRN, BNTX, EXEL,
INCY, IONS, IOVA, KRYS, LEGN, LNTH, MRNA, NBIX, QURE, RGNX, SRPT, UTHR. Clinical: ALLO, ALT, ARCT,
ARWR, BEAM, CABA, CAPR, CRBU, CRSP, DYN, EDIT, FATE, GPCR, IPSC, KRRO, KYTX, NTLA, PEPG, PRME, RCKT,
RVMD, SANA, SGMOQ, SLDB, STOK, TSHA, VKTX, VOR, VYGR, WVE. Membership is computed on every build,
never listed in code.

### 2.2 Pillars and their metrics

Every pillar is named for the good outcome, and every metric is turned so that 100 is the better
side: this is the "positive light" of the request. Business pillars make the company score. Price
measures are scored the same way and drawn beside it.

**The coverage rule.** A metric is scored in a cohort only when at least two thirds of its members
have a value (12 of 18, 15 of 22, 20 of 30) and the values take at least 3 distinct levels. Below
that the gaps are not random (the 20-F filers file no quarters; the companies with no consensus are
the small ones), so ranking the half that has a value would compare a chosen few. A metric that
fails is shown in the panel as a fact with "Not scored: {k} of {n} in the cohort have it". A
pillar left with no scored metric leaves the cohort's list.

Coverage today, companies with a value (the ones that fail the rule in brackets):

| Pillar (id) | Metric (id) | Better | Big pharma, of 18 | Commercial, of 22 |
|---|---|---|---|---|
| Growth (`growth`) | Revenue growth (`rev_growth`) | higher | 17 | 16 |
| | Revenue growth, 3-year CAGR (`rev_cagr3`) | higher | 16 | (14) |
| | Street EPS growth, FY1 to FY3 (`eps_cagr`) | higher | (11) | (4) |
| Profitability (`profitability`) | Operating margin (`op_margin`) | higher | 12 | 21 |
| | Pre-tax margin (`pretax_margin`) | higher | 17 | 20 |
| | Free cash flow margin (`fcf_margin`) | higher | 17 | 19 |
| Balance sheet (`balance_sheet`) | Net debt to operating cash flow (`nd_ocf`) | lower | 17 | not in this cohort's list |
| | Net cash to revenue (`net_cash_rev`) | higher | 18 | not in this cohort's list |
| | Cash runway (`runway`) | longer; not burning is best | not in this cohort's list | 19 (11 not burning) |
| | Share count change, 1 year (`share_change`) | lower | not in this cohort's list | (12) |
| Pipeline (`pipeline`) | Late-stage compounds (`late_compounds`) | more | 18 | 22 |
| | Late-stage compounds per $10bn revenue (`late_per_rev`) | more | 18 | not in this cohort's list |
| | Revenue from launches of the last 5 years (`fresh_share`) | higher | 17 | (7) |
| Durability (`durability`) | Exclusivity left, revenue-weighted (`loe_years`) | longer | 17 | (7) |
| | Revenue from the top product (`top_product`) | lower | 17 | (7) |

So big pharma scores on five pillars and fourteen metrics, and the commercial cohort on four
pillars: growth (revenue growth), profitability (three margins), balance sheet (runway) and
pipeline (late-stage compounds). Durability is absent from the commercial list, not zero: 15 of
22 have no usable product revenue on file. The panel shows those figures where they exist.

The balance sheet lists differ by cohort on purpose. Every big pharma company files debt and none
burns cash, so runway ties all 18 and share counts move by buybacks. In the commercial cohort half
the companies file no debt line and half burn cash, so runway is what separates them. Neither list
holds a market-cap ratio: the business score must not move with the share price (2.6).

**Clinical cohort** (of 30):

| Pillar (id) | Metric (id) | Better | Coverage |
|---|---|---|---|
| Pipeline (`pipeline`) | Compounds in Phase 2 or later (`mid_late_compounds`) | more | 30 |
| | Trials on the lead asset (`trial_conc`) | lower | 30 |
| Funding (`funding`) | Cash runway (`runway`) | longer | 28 |
| | Share count change, 1 year (`share_change`) | lower | 28 |

Growth, profitability and durability do not apply before product revenue. They are absent from
the clinical pillar set, not zero, and the panel says so once. Lead phase is a fact, not a metric
(2.9).

**Price, all cohorts, never in the company score:**

| Measure (id) | Metric (id) | Better | Big pharma | Commercial | Clinical |
|---|---|---|---|---|---|
| Value (`value`) | P/E, next 12 months (`pe_ntm`) | lower | 14 | (7) | not in list |
| | EV to sales, FY0 (`ev_sales`) | lower | 18 | not in list | not in list |
| | Market cap to sales, FY0 (`mcap_sales`) | lower | not in list | 18 | not in list |
| | Free cash flow yield, positive only (`fcf_yield`) | higher | 17 | (8) | not in list |
| | Market cap to cash (`mcap_cash`) | lower | not in list | not in list | 30 |
| Momentum (`momentum`) | Against XLV, 1 year (`rel_1y`) | higher | 18 | 22 | 30 |
| | Against XLV, 3 months (`rel_3m`) | higher | 18 | 22 | 30 |

Commercial biotech uses market cap to sales because EV is null for 34 of 52 non-pharma companies
(no debt line filed). A negative free cash flow yield is not meaningful, as core.js already
treats it: in the commercial cohort it measured cash burn, not price, and made the two axes of the
chart read the same thing (2.6).

Measures considered and left out of the score, each shown as a fact where it has a home:

| Left out | Why | Where it shows |
|---|---|---|
| Business development (deals in 24 months) and partnering (clinical) | the deal rows are not yet reliable enough to rank on (2.10) | the company panel and Compare, as facts |
| Net margin | one-offs and minority interests (7 of 70 records carry `includes_minorities`); pre-tax margin is filed on one basis by every company but EXEL and SNY | panel |
| Lead phase (clinical) | correlates +0.76 with compounds in Phase 2 or later, and "Marketed" came from a junk asset row for WVE (2.9) | panel fact |
| Late-stage compounds per $10bn revenue, commercial | rewards small revenue (RGNX 117 per $10bn) and correlates +0.73 with the count | Table view |
| Net cash to market cap | puts the share price into the business score; at year-ago prices NVO's balance sheet score moved 65 to 82 with no filing changed | Table view |
| Model fair value, upside, pipeline rNPV | model output, 20 of 70 modelled; scoring it marks down every company without a model | Forecast; Key insights "model" cell; panel Model values |
| Street target upside, buy share | the consensus' opinion; target upside rank-correlates −0.50 with the 12-month move in big pharma (targets trail the price) | panel |
| Guided revenue growth | 11 of 70, partly in words or at constant currency | panel |
| Estimate revisions | 14 days of consensus history (from 17 Sep 2026) | panel; scored from about 16 Dec 2026, section 9 |
| Five-year LOE share (`loe_share_5y`) | window ends 2030 on this date and leaves already-generic revenue out | Table view column, until fixed (section 9) |
| Clinical scorecard of the company's drugs | big pharma only, scores the marketed portfolio far more than the pipeline | Comps > Indications |
| Deal values | headline values unreliable (14 of the valued 24-month deals wrong) | the deal list quotes each headline verbatim |
| Catalyst count | a count of events has no good direction | Catalysts |
| R&D intensity, return on equity | no good direction; negative equity (ABBV) | Table view |

### 2.3 Metric definitions

Every input is a field of the `GET /comps/valuation` record (`rec`) already built for the Comps
view, or one of six reads of tables the book already has (5.1). Paths are into `rec`. "FY0
revenue" is `rec.periods.FY0.revenue_usd_m`. A null value carries a reason code (texts in 8.4).

| Metric | Value | Null, with reason |
|---|---|---|
| `rev_growth` | `rec.growth.revenue_fy` | FY0 revenue under $100m (`below_revenue_floor`); either base under $10m or growth beyond ±500% (`growth_not_meaningful`); the payload's own na code (`one_year_only`, `insufficient_history`); a flag of 2.8 |
| `rev_cagr3` | `rec.growth.revenue_cagr3` | as `rev_growth` |
| `eps_cagr` | `rec.growth.eps_street_cagr` | base EPS under 0.10 in absolute value (`eps_base`); FY1 consensus under half of FY2 (`eps_base_depressed`: MRK's FY2026 consensus of 2.76 against 9.61 for FY2027, from a one-off charge, gave 99.7% a year); the payload's na (`non_positive_base`, `no_consensus`, `no_consensus_otc`); a flag of 2.8 |
| `op_margin` | `periods.FY0.operating_income_usd_m / FY0 revenue` | `derived_operating_income` (2.8); revenue zero or not filed (`no_revenue`) |
| `pretax_margin` | FY0 `IncomeBeforeTax` from `financials` (period end equal to `periods.FY0.period_end`, period type FY), converted at `payload.fx.usd_per_unit[row unit]`, over FY0 revenue | not filed (`not_filed`: EXEL and SNY today); `no_revenue` |
| `fcf_margin` | `periods.FY0.fcf_usd_m / FY0 revenue` | not filed; `no_revenue` |
| `nd_ocf` | `ev.net_debt_usd_m / OCF`, OCF = FY0 `CashFlowOperating` from `financials` for the FY0 fiscal year, converted as above | no debt line filed (`no_debt_line`); OCF at or under zero (`burning_cash`); OCF not filed (`not_filed`) |
| `net_cash_rev` | `(ev.cash_usd_m − ev.total_debt_usd_m) / FY0 revenue` | `no_debt_line` (the debt is unknown, never read as nil); FY0 revenue under $100m |
| `runway` | `risk.runway_months`; where `na["risk.runway_months"] == "not_burning"` the text is "not burning cash" and it ranks above every burner, tied with the other non-burners | the payload's na code; `burn_flattered` |
| `share_change` | `WeightedAverageDilutedShares` for the latest quarter over the same quarter a year before (period ends 345 to 385 days apart), less 1; else the last two fiscal years | net income of the two periods on opposite sides of zero (`dilution_basis_changed`: a diluted count adds options and convertibles only in a profitable period, so ABEO read −14.4% while its basic count rose 15%; ABEO, ALNY and IONS today); ratio under 0.5 (`share_split`) or over 20 (`share_scale`); no quarters filed (`not_filed`: the 20-F filers) |
| `late_compounds` | `detail.pipeline.compounds["Phase 3"] + ["Phase 2/3"]` | no pipeline record (`no_pipeline`) |
| `late_per_rev` | `late_compounds / (FY0 revenue / 10,000)` | FY0 revenue under $100m |
| `fresh_share` | `productivity.portfolio_freshness(conn, company_id, rates, today=FY0 period end)`, so the five years run back from the end of the revenue year, not from today (NVO's Wegovy, approved 4 Jun 2021, counts on FY2025 revenue); exact duplicate product rows counted once (below) | the product gate (`no_product_revenue`, `partial_product_revenue`); any of it dated by the whole-register inference rather than the drug's own approval (`inferred_dates`: LNTH, whose Pylarify carries no approval row); the function's reason |
| `loe_years` | over the company's owned product rows of the FY0 year (the product gate's rows), each with an effective date from `loe.for_assets(conn, exclude_orphan=True)`: revenue-weighted mean of `max(0, (date − today) / 365.25)` | the product gate; under half of that revenue has a date (`under_half_dated`) |
| `top_product` | the largest product row of the FY0 year, converted to USD, over FY0 revenue | the product gate |
| `mid_late_compounds` | `detail.pipeline.compounds` Phase 2 + Phase 2/3 + Phase 3 | `no_pipeline` |
| `trial_conc` | `healthcare.trial_concentration` | the payload's na code (`no_trials`) |
| `pe_ntm` | `market.price / periods.NTM.eps` | the rules of core.js `peCompute` for basis NTM: FY1 or FY2 consensus at or under zero, NTM EPS at or under zero (`eps_not_positive`); no consensus (`no_consensus`); a flag of 2.8 |
| `ev_sales` | `ev.ev_usd_m / FY0 revenue` | revenue under $100m; EV null (`no_debt_line`); a flag |
| `mcap_sales` | `market.market_cap_usd_m / FY0 revenue` | revenue under $100m; a flag |
| `fcf_yield` | `periods.FY0.fcf_usd_m / market.market_cap_usd_m`, where FCF is above zero | FCF at or under zero (`fcf_negative`); not filed |
| `mcap_cash` | `market.market_cap_usd_m / ev.cash_usd_m` | cash at or under zero (`no_cash`) |
| `rel_1y`, `rel_3m` | `detail.relative["1y"].relative_pct`, `["3m"]` | `covers_window` false (`short_history`) |

Every revenue ratio reads FY0 revenue, for every company. Revision 1 used LTM to June 2026 where
it existed and FY0 elsewhere, which put 11 US filers and 7 foreign filers on different bases in one
rank (LLY's LTM is 22% above its FY0).

**The product gate.** `fresh_share`, `loe_years` and `top_product` read one fiscal year of product
revenue, FY0, from `asset_revenue` (period FY) over the company's owned assets. Rows of the same
value in the same year count once: they are one line filed twice, as VRTX's Trikafta is (assets
102 and 6972, $10.31bn each). The rows, converted at the payload's rates, must sum to between 60%
and 110% of FY0 revenue, or the three metrics are null with `partial_product_revenue` (no rows at
all: `no_product_revenue`). The floor is 60% rather than 70% because product rows hold drugs only,
and JNJ's MedTech is about a third of its revenue (JNJ 64%, SNY 67%); BAYN, at 17% with its crop
science outside, fails. Today 17 of 18 big pharma pass and 7 of 22 commercial companies. Revision
1 read each product's latest year, which mixed EXEL's junk FY2024 "Product Gross" line with its
FY2026 rows, and divided by a VRTX total that held Trikafta twice: its top product share read 48%
where the true figure is 86% of revenue.

**Floors.** The comps view's own (comps-valuation.md 3.1): $100m of FY0 revenue for growth and
for ratios on revenue other than margins, $10m at either end for growth, 0.10 for an EPS base,
±500% for growth, consensus crossing zero for P/E. Margins are the exception (2.4).

Three measures are computed both here and by core.js for the Table view (P/E NTM, EV to sales on
FY0, revenue growth); a parity test holds them equal wherever both have a value (7.2). Free cash
flow yield is checked for the same rule on negative values.

### 2.4 From a metric to a score of 0 to 100

For a company with value `v` in a cohort where the other members with a value are `others`:

```
percentile = 100 × (count(o < v) + 0.5 × count(o == v)) / len(others)
metric score = percentile            if higher is better
             = 100 − percentile      if lower is better
```

This is the mid-rank formula of core.js `percentileRank`, the company excluded from its own
reference set. It reads "beats 12 of 17", which a reader can repeat.

- **Ties** share the mid-rank: every non-burning commercial company scores the same on runway.
- **Margins on small revenue rank last.** A margin on FY0 revenue under $100m is kept, shown with
  its revenue ("$5.8m of revenue in FY2025, too little to compare margins") and ranked below every
  other value, tied with any other such margin. Dropping it would leave ABEO, AUTL and QURE with no
  profitability pillar, so 2 of 4 pillars and no rank: the three weakest commercial businesses
  would vanish from the chart. Keeping the ratio as it stands would rank ABEO's pre-tax margin of
  1,225% (a voucher sale on $5.8m of revenue) first.
- **Winsorising** is not applied, because a rank already bounds every outlier.
- **Direction** is fixed per metric (2.2).

### 2.5 Pillar score

For a pillar whose cohort list has `K` scored metrics, of which the company has `k`:

```
raw    = mean of the company's metric scores in the pillar
w      = (k / (k + 1)) × ((K + 1) / K)
pillar = 50 + (raw − 50) × w
```

With every metric present, `w = 1` and the pillar is the plain mean. One of two keeps three
quarters of its distance from 50, one of three keeps two thirds. This is shrinkage toward the
cohort middle: a pillar that rests on fewer measures is trusted less, the idea behind the clinical
scorecard's shrinkage of a drug resting on one trial. In arithmetic it is the same as filling the
gap with the middle score at weight `1 − w`, and the method says so rather than claiming nothing is
filled. The coverage rule (2.2) keeps that to the few companies that miss a measure most of their
cohort has. A pillar with no metric present is null with the reason "No free data for any of its
measures" (or the single reason when all share one).

ROG, big pharma, balance sheet: net debt to operating cash flow is null (operating cash flow not
filed), net cash to revenue scores 82.4. `k = 1, K = 2, w = 0.75`, pillar = 50 + 32.4 × 0.75 =
74.3, shown 74.

### 2.6 Company score and rank

```
company score = 50 + (mean of the business pillars present − 50) × w(k, K)
```

with `k` the business pillars present and `K` those in the cohort's list (5 big pharma, 4
commercial, 2 clinical), the same pull as 2.5. A company score needs two thirds of the cohort's
business pillars, rounded up: 4 of 5, 3 of 4, 2 of 2. Below that it is null and the company is
listed beside the chart with "{k} of {K} pillars, a score needs {m}". ADAPY has 2 of 4 today.

ROG: four business pillars (growth is null: one fiscal year of revenue on file and no consensus),
mean 61.3, `w = (4/5)(6/5) = 0.96`, company score 60.9, shown 61, 6th of 18.

Rank: by the unrounded company score, descending, within the cohort; equal scores break by ticker
so the order is stable. The rank is over the ranked companies only ("7th of 18").

**Value and momentum** are pillars in form (2.5 applies) and never inside the company score. Value
is what the market charges for the business, not the business; momentum moves every close. Kept
apart, they are the chart's two axes, and no business measure divides by market cap, so a falling
share price moves a bubble up, never sideways. The company score and the value score
rank-correlate −0.35 across big pharma (quality is priced), −0.05 in the commercial cohort and
−0.29 in the clinical cohort; revision 1's commercial figure of +0.45 came from scoring cash burn
on both axes.

### 2.7 Weights

Equal across business pillars and across metrics within a pillar. There is no history of these
scores against returns to fit weights on, weights fitted on 18 companies would be noise, and equal
weights are the easiest to explain. The rank range (2.11) shows how much the order depends on that
choice. There is no weight slider: it lets a reader reach any ranking they came for.

### 2.8 Missing data and flags

A value is in one of five states, each with its text (8.4):

| State | Meaning | Example |
|---|---|---|
| value | a number, scored | AZN operating margin 23.4% |
| not meaningful | a number exists but is not comparable | revenue growth on revenue under $100m; P/E with consensus crossing zero |
| not like for like | the payload flags the figure | LLY's operating margin, derived rather than filed |
| not applicable | the measure does not exist for this kind of company | growth for a clinical-stage company |
| no free data | the book has no source for it | ROG growth (one fiscal year, no consensus) |

A pillar rests on what exists and says how much ("Growth 62, on 1 of 3 measures"). A pillar with
nothing is left out of the company score and named in the panel ("Not in the score: growth, no free
data"). A company below the pillar minimum is not ranked and says why.

**A flagged figure is not scored.** Revision 1 scored figures it would not print; 41 of them sat in
a cohort's top or bottom quarter. Now a flag that makes a figure not like for like nulls it, with
the flag as its reason, and the panel shows the figure beside the reason:

| Amber flag | Metrics it nulls | Why |
|---|---|---|
| `derived_operating_income` | `op_margin` | operating income derived as revenue less cost of sales, R&D and SG&A leaves out separately presented charges: PFE's derived margin is 35.6% against a filed pre-tax margin of 12.0% (6 big pharma) |
| `estimate_range_wide`, `thin_estimates` on FY1, FY2 or NTM | `eps_cagr`, `pe_ntm` | the consensus is too thin or too spread to rank |
| `thin_estimates` on FY3 | `eps_cagr` | |
| `burn_flattered` | `runway` | the burn rate is understated (5 companies) |
| `stale_fiscal_year` | `rev_growth`, `rev_cagr3`, the three margins, `late_per_rev`, `net_cash_rev`, `ev_sales`, `mcap_sales`, `fcf_yield` | FY0 is a year behind the cohort (ADAPY) |
| `currency_mismatch` | `rev_growth`, `rev_cagr3` | the years compared are filed in different currencies (ARGX, BNTX) |
| `stale_shares`, where `market.market_cap_basis` is the stale cover count | `ev_sales`, `mcap_sales`, `fcf_yield`, `mcap_cash` | the share count is over a year old (ADAPY; REGN's market cap already uses its FY2025 diluted count, so nothing of REGN is nulled) |

Shown, not withheld:

| Amber flag | Why it does not null | Where it shows |
|---|---|---|
| `market_cap_disagreement` | the market cap uses the latest cover count; the alternative is the FY2025 weighted diluted count, which lags issuance (IPSC: 181m shares on 3 Aug 2026 against 87m weighted over 2025). The primary is the right basis, so 22 of 23 flags point the same way | the panel's Value row, with both figures |
| `stale_price` | 22 companies last closed on 29 Sep and the rest on 30 Sep: one trading day | the bubble tooltip and the panel's data line carry the date |
| `stale_balance_sheet` | it is the latest filed balance sheet (the 20-F and IR filers at a FY2025 year end) | the date beside every balance figure in the panel |
| `includes_minorities` | net margin is not a measure (2.2) | panel |
| `eps_sign_change`, `no_consensus` | the P/E and EPS rules already return null | |
| `guidance_fx_unstated`, `fiscal_year_end` | the scorecard reads neither guidance nor a fiscal-year comparison | panel |

Every amber code the payload emits sits in one of the two tables; a test fails on a code in
neither (7.2).

### 2.9 Clinical-stage companies

Two business pillars: pipeline (how far and how wide: compounds in Phase 2 or later, and how much
of the trial book rests on the lead asset) and funding (how long the cash lasts and how much it has
cost holders). The value axis is market cap to cash: how much the market pays beyond the cash for
the pipeline, the only honest multiple for a company with no earnings or sales. It is kept off the
funding pillar so the chart's axes stay independent.

**Lead phase is a fact.** The panel prints the highest phase in `detail.pipeline.compounds`, and
"marketed" only when an owned asset has an `approvals` row: ARWR "Lead asset marketed: Redemplo,
approved Nov 2025", RVMD "Lead asset marketed: Rasonque, approved Aug 2026", WVE "Lead asset in
Phase 2" (its "Marketed" came from an asset row named "Category One Programs" with no approval).
It is not scored: it rank-correlates +0.76 with compounds in Phase 2 or later, so it counted the
same thing twice, and a marketed lead in a clinical cohort was a free top score.

**A partner on a marketed drug.** Where the company is the `partner_ticker` of a marketed asset in
`assumptions` (CRSP on Casgevy, VRTX's asset), the panel says "Shares Casgevy, VRTX's marketed
drug" and the pipeline pillar's lines are silenced (2.12, rule 6): its "0 compounds in Phase 2 or
later" is true of what CRSP owns and misleading about the company.

### 2.10 Business development and partnering: shown, not scored

The user asked for M&A to count, read in a positive light. The question behind it: can the company
buy or license its way to its next products, and can it afford to? This build answers it with
facts, not a score, because the book cannot yet count deals well enough to rank on:

- Revision 1's gate kept stock ratings ("Incyte: Buy For The Turnaround"), ended collaborations
  ("Century Therapeutics ends collaboration with Bristol-Myers Squibb"), patent settlements, a
  cancelled property purchase, an insider's share purchase ("GSK president acquires ADS in savings
  plan"), contract recitals, AI and IT vendors, crop science and animal health, and one deal under
  a place name ("Massachusetts", "Waltham", "U.S"). It counted 11 deals for GSK; a stricter read
  finds 7.
- The counts have holes as well as noise: the November 2024 licence between SRPT and Arrowhead is
  not on file for either company, so SRPT would score as if it had made no deal.
- Removing only the rows that are plainly not deals moved 22 of 30 clinical ranks, and 5 of the
  19 clinical companies credited with a partner owed it to an ending, a recital or a duplicate.

**What shows.** In the company panel, a Business development block: "{n} deals on file in 24
months", the list (date, type, the headline or filing sentence verbatim, source link, "filing" or
"news"), newest first, at most eight, with the chip "From headlines and filings, not reviewed";
and for commercial companies the firepower line "Could fund about ${x}bn of deals before net debt
reaches three times operating cash flow", from `3 × OCF − net debt`, only where both are filed
(AZN $19.8bn). Compare carries one row with the count and the newest deal. Key insights' What
changed shows a deal when it is new. The table, the chart and the score do not.

**The gate for the list** (on both routes, filing and news):

1. rows with `deal_type` in acquisition, licensing, collaboration, `counterparty` not null,
   `event_date` within 730 days of today;
2. dropped when the quote is not a deal: a rating ("a buy", "buy thesis"), an ending
   ("terminat", "ends its collaboration", "discontinu", "wind down"), a settlement, a
   cancellation, a recital ("WHEREAS"), or a share purchase by an officer ("savings plan",
   "president acquires");
3. dropped when the counterparty is not a party: a place or a generic noun (a curated list:
   "Biz", "Firm", "Drug", "RNA", "CAR-T", "PET", "U.S", "US-based", "Massachusetts", "Waltham"
   and the like, extended on review), or a technology, sales-channel, manufacturing, crop, animal
   health, device, university or public-body counterparty (a curated list, starting with
   Microsoft, NVIDIA, Anthropic, OpenAI, Google, Amazon, Veeva, Viz.ai, Hims, Pocketpills,
   Fujifilm, Resilience, TARGAN, RAGT, Camelina, Benchmark Genetics, universities, clinics, the
   WHO, development boards and West Pharmaceutical Services);
4. news rows only: not commentary (`deals_news.COMMENTARY`), not another company's deal
   (`deals.NOT_OUR_DEAL`), a counterparty `deals.is_party()` accepts, and the company named as the
   subject: its name, ticker or a distinctive word of its name, not followed by "Holdings",
   "owner", "president" or "director", with a deal verb (`deals_news.DEAL_VERBS`) within four
   words;
5. one row per deal event: a news row within 3 days of a kept row is the same event, and rows
   sharing a distinctive counterparty word within 180 days are the same event (a 10-Q repeats a
   deal it announced in an 8-K); a filing row wins over a news row. Two filing rows never merge on
   the date alone, and two deals with one counterparty a year apart stay two (AZN's CSPC deals of
   June 2025 and July 2026).

On the book this keeps 6 deal events for AZN, 7 for GSK, 15 for LLY, 2 for VRTX, 1 for CRSP and 0
for SRPT. The list reads "on file" because a deal announced in a press release the deals table
has not read yet (AZN and Summit Therapeutics, 28 Sep) appears in What changed first.

**When it joins the score.** Once the deals reader is fixed (section 9, item 1) and a reviewed
fixture of the 24-month deals of the 18 big pharma matches the gate within one deal per company,
business development becomes a pillar for the two commercial cohorts and partnering a pillar for
the clinical cohort, each scored only upward: `max(50, percentile of deal events)`. A company that
grows its own drugs then sits at the middle, never below it, which is the positive light the user
asked for. Deal values are never summed: 14 of the valued 24-month deals carry a wrong headline
value.

### 2.11 Uncertainty: the rank range

The inputs are filed figures and street estimates, not estimates with standard errors, so a score
has no sampling interval. What does move a rank is the method's main judgement, the equal weights.
So the range asks: under how many reasonable weightings does the company keep this place?

```
seed = 20261001; draws = 2000
the ranked set is the companies ranked on the full score, fixed for every draw
for each draw:
    give each business pillar a weight from a flat Dirichlet (every weighting equally likely),
    and each metric inside a pillar likewise; the same weights for every company
    pillar  = the pull of 2.5 on the weighted mean of the company's metric scores present
    score   = the pull of 2.6 on the weighted mean of its pillars present
    rank the fixed set
range = the 5th and 95th percentiles of the company's ranks over the draws
```

It reads "7th of 18, range 2–11": in 90 of 100 weightings AZN sits between 2nd and 11th. It is
deterministic for the seed, so the same book gives the same range and a test can pin it. It is the
analogue of the clinical scorecard's range ("where it falls in 95 of 100 redraws"), with the
weights redrawn instead of the trial results, at 90 because a weighting is a judgement rather than
a sampling error. Holding the ranked set fixed removes revision 1's bug, where an unranked company
entered the variants and pushed others to a 22nd place of 21.

The ranges are wide, and that is the finding: across big pharma the median range spans 9 places of
18, across the clinical cohort 12.5 of 30. NVS (1 to 6) and BAYN (17 to 18) are settled; most of
the middle is not. The rank stays in each bubble because it is how the chart and the table find
each other, and the range is printed beside every rank: in the table, the sentence, the panel and
the tooltip. A tier (top, middle, bottom third) was considered and not used: most ranges cross a
tier boundary, so a tier would be as uncertain as the rank and add a second vocabulary.

### 2.12 Positives and negatives

Generated from the business pillars, never written separately, and read by every surface from one
list. Value and momentum make no line: a share price move is not a fact about the company, and
leading the list with one (revision 1 put "−21 points against XLV over 3 months" first for AZN)
made the summary change with every close. The panel shows them in their own rows.

**Rules, per company:**

1. For each business pillar, the candidates are the company's scored metrics in it, less a runway
   of "not burning cash" (a tie at the top, not a distinction).
2. The candidate with the highest metric score makes a **positive** when that score is 75 or more;
   the one with the lowest makes a **negative** when its score is 25 or less. So a pillar gives at
   most one of each.
3. A positive on a metric with a natural zero also needs the right side of zero: growth, margins
   and net cash to revenue above zero, share count change below zero. "4.4% of market cap in net
   debt" and "+3.1% change in share count" no longer read as positives.
4. Absolute rules, each added only when its pillar has no negative yet and its metric carries no
   positive, tested on the value as displayed: cash runway under 24 months ("{m} months of cash
   runway, under two years"; STOK's 23.9 months displays as 24 and makes no line); top product
   over half of revenue ("{p}% of FY2025 revenue from {product}, over half"); net debt over three
   times operating cash flow ("Net debt of {x}× operating cash flow, above 3×").
5. Order each list by strength, `|metric score − 50|`, highest first. The absolute lines take
   strengths 49 (runway), 48 (top product) and 47 (leverage).
6. A company that is the partner on a marketed drug (2.9) makes no pipeline line.
7. Key insights and Compare show the first three of each; the panel shows all.

**The line:** `{phrase with the value and its period}, {place} of {n} {cohort noun}`, number first.
The phrase per metric is in 8.2; it names the fiscal year ("8.6% revenue growth in FY2025") or the
span ("−14.8% a year revenue growth, FY2022 to FY2025"), and names the product where there is one
("86% of FY2025 revenue from Trikafta"). `place` counts from the nearer end in the metric's better
direction: "best", "2nd best", "worst", "3rd worst", with "joint " where tied, so "lowest" never
has to be read as good or bad. `n` counts the cohort members with a value. Counts are pluralised
("1 late-stage compound"). Net debt and net cash read on their own side of zero ("Net debt of
4.7× operating cash flow", "Net cash of 1.1× revenue"). Each line carries its source (`source`:
the filing and its period, "consensus of 30 Sep", "pipeline record" or "product revenue on file"),
shown on hover on Key insights and Compare and as a link on the panel's metric row.

Across the book these rules give 70 positives and 100 negatives, 0 to 7 lines a company (IONS and
SRPT have none: no measure past a quartile), 2.4 on average.

### 2.13 The one sentence

Built from the scores, at most 30 words, in house style. Template:

```
{T} scores {S}, {rank ordinal} of {n} {cohort noun}, range {lo}–{hi}.
[ Strongest on {p1}[ and {p2}] | Weakest on ... | both, joined by ", weakest on " | "No pillar above 60 or below 40." ]
```

- strongest: the business pillars scoring 60 or more, best first, at most two; weakest: those at
  40 or less, worst first, at most two. Pillar names in lower case, without their numbers (the
  bars beside it carry them).
- If the sentence runs over 30 words, the second strongest and then the second weakest are
  dropped. The longest today is 21 words (PFE).
- not ranked: "{T} is not scored: {k} of {K} pillars have data, and a score needs {m}."
- The multiple is not in the sentence: it is the strip's "multiple" cell, printed as a multiple.

### 2.14 Worked examples

Each from the 2026-10-01 book, computed by the reference script (Appendix A). Metric score is
already turned so 100 is better; place and n are as the line would print them.

**AZN**, big pharma: score 58, 7th of 18, range 2 to 11; value 46, momentum 9.

| Pillar | Score | Metric | Value | Metric score | Place | n |
|---|---|---|---|---|---|---|
| Growth | 77 | Revenue growth | 8.6% | 81.2 | 4th best | 17 |
|  |  | Revenue growth, 3-year CAGR | 9.8% | 73.3 | 5th best | 16 |
|  |  | Street EPS growth, FY1 to FY3 | null: `estimate_range_wide` |  | (not scored in cohort) |  |
| Profitability | 31 | Operating margin | 23.4% | 18.2 | 3rd worst | 12 |
|  |  | Pre-tax margin | 21.1% | 31.2 | 6th worst | 17 |
|  |  | Free cash flow margin | 20.0% | 43.8 | 8th worst | 17 |
| Balance sheet | 55 | Net debt to operating cash flow | 1.6× | 56.2 | 8th best | 17 |
|  |  | Net cash to revenue | −0.4× | 52.9 | 9th best | 18 |
| Pipeline | 65 | Late-stage compounds | 23 | 94.1 | 2nd best | 18 |
|  |  | Late-stage compounds per $10bn revenue | 3.9 | 82.4 | 4th best | 18 |
|  |  | Revenue from launches of the last 5 years | 7% | 18.8 | 4th worst | 17 |
| Durability | 62 | Exclusivity left, revenue-weighted | 4.6 years | 56.2 | 8th best | 17 |
|  |  | Revenue from the top product | 14% | 68.8 | 6th best | 17 |
| Value | 46 | P/E, next 12 months | null: `estimate_range_wide` |  |  |  |
|  |  | EV to sales | 4.7× | 52.9 | 9th best | 18 |
|  |  | Free cash flow yield | 4.7% | 37.5 | 7th worst | 17 |
| Momentum | 9 | Against XLV, 1 year | −18 points | 11.8 | 3rd worst | 18 |
|  |  | Against XLV, 3 months | −21 points | 5.9 | 2nd worst | 18 |

Sentence: "AZN scores 58, 7th of 18 big pharma, range 2–11. Strongest on growth and pipeline, weakest on profitability."

Positives: "23 late-stage compounds, 2nd best of 18 big pharma"; "8.6% revenue growth in FY2025, 4th best of 17 big pharma".
Negatives: "23.4% operating margin in FY2025, 3rd worst of 12 big pharma"; "7% of FY2025 product revenue from drugs approved since 2021, 4th worst of 17 big pharma".

AZN's P/E and street EPS growth are null (`estimate_range_wide`: its FY1 EPS estimates run from 5.18 to 10.34 around a mean of 9.37), so its value score rests on EV to sales and free cash flow yield and the strip's multiple cell shows EV to sales. Its next exclusivity loss is Lynparza, 8 Sep 2027, 5.6% of FY2025 revenue.

**LLY**, big pharma: score 63, 5th of 18, range 1 to 12; value 3, momentum 59.

| Pillar | Score | Metric | Value | Metric score | Place | n |
|---|---|---|---|---|---|---|
| Growth | 100 | Revenue growth | 44.7% | 100.0 | best | 17 |
|  |  | Revenue growth, 3-year CAGR | 31.7% | 100.0 | best | 16 |
|  |  | Street EPS growth, FY1 to FY3 | 23.3% |  | best (not scored in cohort) | 11 |
| Profitability | 50 | Operating margin | null: `derived_operating_income` |  |  |  |
|  |  | Pre-tax margin | 39.5% | 93.8 | 2nd best | 17 |
|  |  | Free cash flow margin | 13.8% | 6.2 | 2nd worst | 17 |
| Balance sheet | 31 | Net debt to operating cash flow | 2.7× | 37.5 | 7th worst | 17 |
|  |  | Net cash to revenue | −0.7× | 23.5 | 5th worst | 18 |
| Pipeline | 71 | Late-stage compounds | 13 | 70.6 | 6th best | 18 |
|  |  | Late-stage compounds per $10bn revenue | 2.0 | 41.2 | 8th worst | 18 |
|  |  | Revenue from launches of the last 5 years | 68% | 100.0 | best | 17 |
| Durability | 62 | Exclusivity left, revenue-weighted | 7.7 years | 87.5 | 3rd best | 17 |
|  |  | Revenue from the top product | 35% | 37.5 | 7th worst | 17 |
| Value | 3 | P/E, next 12 months | 26.2× | 7.7 | 2nd worst | 14 |
|  |  | EV to sales | 16.7× | 0.0 | worst | 18 |
|  |  | Free cash flow yield | 0.9% | 0.0 | worst | 17 |
| Momentum | 59 | Against XLV, 1 year | +29 points | 82.4 | 4th best | 18 |
|  |  | Against XLV, 3 months | −8 points | 35.3 | 7th worst | 18 |

Sentence: "LLY scores 63, 5th of 18 big pharma, range 1–12. Strongest on growth and pipeline, weakest on balance sheet."

Positives: "44.7% revenue growth in FY2025, best of 17 big pharma"; "68% of FY2025 product revenue from drugs approved since 2021, best of 17 big pharma"; "39.5% pre-tax margin in FY2025, 2nd best of 17 big pharma"; "7.7 years of exclusivity left on FY2025 product revenue, 3rd best of 17 big pharma".
Negatives: "13.8% free cash flow margin in FY2025, 2nd worst of 17 big pharma"; "Net debt of 0.7× revenue, 5th worst of 18 big pharma".

LLY's 45.6% operating margin is derived rather than filed and is not scored; its 39.5% pre-tax margin and its 13.8% free cash flow margin (a manufacturing build-out) carry profitability to the middle. It is the chart's bottom right: the fastest grower at the highest multiples. Revision 1 put it 1st; without the deal count and the derived margin it is 5th, range 1 to 12.

**PFE**, big pharma: score 40, 13th of 18, range 4 to 17; value 72, momentum 68.

| Pillar | Score | Metric | Value | Metric score | Place | n |
|---|---|---|---|---|---|---|
| Growth | 3 | Revenue growth | −1.6% | 6.2 | 2nd worst | 17 |
|  |  | Revenue growth, 3-year CAGR | −14.8% | 0.0 | worst | 16 |
|  |  | Street EPS growth, FY1 to FY3 | −6.6% |  | 2nd worst (not scored in cohort) | 11 |
| Profitability | 17 | Operating margin | null: `derived_operating_income` |  |  |  |
|  |  | Pre-tax margin | 12.0% | 12.5 | 3rd worst | 17 |
|  |  | Free cash flow margin | 14.5% | 12.5 | 3rd worst | 17 |
| Balance sheet | 9 | Net debt to operating cash flow | 4.7× | 6.2 | 2nd worst | 17 |
|  |  | Net cash to revenue | −0.9× | 11.8 | 3rd worst | 18 |
| Pipeline | 94 | Late-stage compounds | 27 | 100.0 | best | 18 |
|  |  | Late-stage compounds per $10bn revenue | 4.3 | 94.1 | 2nd best | 18 |
|  |  | Revenue from launches of the last 5 years | 21% | 87.5 | 3rd best | 17 |
| Durability | 75 | Exclusivity left, revenue-weighted | 5.3 years | 68.8 | 6th best | 17 |
|  |  | Revenue from the top product | 13% | 81.2 | 4th best | 17 |
| Value | 72 | P/E, next 12 months | 9.7× | 76.9 | 4th best | 14 |
|  |  | EV to sales | 3.5× | 76.5 | 5th best | 18 |
|  |  | Free cash flow yield | 5.5% | 62.5 | 7th best | 17 |
| Momentum | 68 | Against XLV, 1 year | −7 points | 35.3 | 7th worst | 18 |
|  |  | Against XLV, 3 months | +13 points | 100.0 | best | 18 |

Sentence: "PFE scores 40, 13th of 18 big pharma, range 4–17. Strongest on pipeline and durability, weakest on growth and balance sheet."

Positives: "27 late-stage compounds, best of 18 big pharma"; "13% of FY2025 revenue from Eliquis, 4th best of 17 big pharma".
Negatives: "−14.8% a year revenue growth, FY2022 to FY2025, worst of 16 big pharma"; "Net debt of 4.7× operating cash flow, 2nd worst of 17 big pharma"; "14.5% free cash flow margin in FY2025, 3rd worst of 17 big pharma".

PFE is best on pipeline and near worst on growth and the balance sheet, so its place turns on the weights: range 4th to 17th. The leverage rule (4.7× is above 3×) adds nothing because the balance sheet pillar already has its negative.

**VRTX**, big pharma: score 72, 1st of 18, range 1 to 10; value 4, momentum 53.

| Pillar | Score | Metric | Value | Metric score | Place | n |
|---|---|---|---|---|---|---|
| Growth | 84 | Revenue growth | 8.9% | 87.5 | 3rd best | 17 |
|  |  | Revenue growth, 3-year CAGR | 10.4% | 80.0 | 4th best | 16 |
|  |  | Street EPS growth, FY1 to FY3 | null: `thin_estimates` |  | (not scored in cohort) |  |
| Profitability | 82 | Operating margin | 34.8% | 90.9 | 2nd best | 12 |
|  |  | Pre-tax margin | 38.7% | 87.5 | 3rd best | 17 |
|  |  | Free cash flow margin | 26.6% | 68.8 | 6th best | 17 |
| Balance sheet | 100 | Net debt to operating cash flow | −3.8× | 100.0 | best | 17 |
|  |  | Net cash to revenue | 1.1× | 100.0 | best | 18 |
| Pipeline | 43 | Late-stage compounds | 4 | 8.8 | joint 2nd worst | 18 |
|  |  | Late-stage compounds per $10bn revenue | 3.3 | 76.5 | 5th best | 18 |
|  |  | Revenue from launches of the last 5 years | 9% | 43.8 | 8th worst | 17 |
| Durability | 50 | Exclusivity left, revenue-weighted | 11.4 years | 100.0 | best | 17 |
|  |  | Revenue from the top product | 86% | 0.0 | worst | 17 |
| Value | 4 | P/E, next 12 months | 29.4× | 0.0 | worst | 14 |
|  |  | EV to sales | 10.0× | 5.9 | 2nd worst | 18 |
|  |  | Free cash flow yield | 2.4% | 6.2 | 2nd worst | 17 |
| Momentum | 53 | Against XLV, 1 year | +6 points | 47.1 | 9th worst | 18 |
|  |  | Against XLV, 3 months | −2 points | 58.8 | 8th best | 18 |

Sentence: "VRTX scores 72, 1st of 18 big pharma, range 1–10. Strongest on balance sheet and growth."

Positives: "Net cash of 1.1× revenue, best of 18 big pharma"; "11.4 years of exclusivity left on FY2025 product revenue, best of 17 big pharma"; "34.8% operating margin in FY2025, 2nd best of 12 big pharma"; "8.9% revenue growth in FY2025, 3rd best of 17 big pharma"; "3.3 late-stage compounds per $10bn of revenue, 5th best of 18 big pharma".
Negatives: "86% of FY2025 revenue from Trikafta, worst of 17 big pharma"; "4 late-stage compounds, joint 2nd worst of 18 big pharma".

Trikafta is counted once, so 86% of FY2025 revenue comes from it, the worst of 17; revision 1 read 48%. Its two deals in 24 months (WuXi Biologics, Crinetics, both from filings) show in the panel and are not scored. Its value score of 4 sits it at the bottom of the chart with LLY.

**CRSP**, clinical-stage biotechs: score 59, 10th of 30, range 2 to 23; value 45, momentum 67.

| Pillar | Score | Metric | Value | Metric score | Place | n |
|---|---|---|---|---|---|---|
| Pipeline | 33 | Compounds in Phase 2 or later | 0 | 15.5 | joint worst | 30 |
|  |  | Trials on the lead asset | 67% | 50.0 | joint 15th best | 30 |
| Funding | 85 | Cash runway | 77 months | 96.3 | 2nd best | 28 |
|  |  | Share count change, 1 year | +10.8% | 74.1 | 8th best | 28 |
| Value | 45 | Market cap to cash | 2.3× | 44.8 | 14th worst | 30 |
| Momentum | 67 | Against XLV, 1 year | −38 points | 51.7 | 15th best | 30 |
|  |  | Against XLV, 3 months | −11 points | 82.8 | 6th best | 30 |

Sentence: "CRSP scores 59, 10th of 30 clinical-stage biotechs, range 2–23. Strongest on funding, weakest on pipeline."

Positives: "77 months of cash runway, 2nd best of 28 clinical-stage biotechs".
Negatives: none.

CRSP's pipeline pillar reads what it owns (Phase 1/2 at most); its pipeline lines are silenced and the panel says it shares Casgevy, VRTX's marketed drug (2.9). Its Eli Lilly collaboration (Jan 2026, from its filing) is in the panel's deal list. At stake on Catalysts prices its Casgevy readout at $4.18 a share.

### 2.15 The big pharma cohort today

| # | Range | Company | Score | Growth | Profit | Balance | Pipeline | Durability | Value | Momentum |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 to 10 | VRTX | 72 | 84 | 82 | 100 | 43 | 50 | 4 | 53 |
| 2 | 1 to 6 | NVS | 69 | 68 | 76 | 76 | 69 | 56 | 59 | 18 |
| 3 | 1 to 11 | REGN | 65 | 39 | 72 | 94 | 68 | 50 | 50 | 74 |
| 4 | 2 to 11 | NVO | 65 | 78 | 77 | 76 | 52 | 41 | 65 | 0 |
| 5 | 1 to 12 | LLY | 63 | 100 | 50 | 31 | 71 | 62 | 3 | 59 |
| 6 | 1 to 11 | ROG | 61 | · | 56 | 74 | 59 | 56 | 48 | 41 |
| 7 | 2 to 11 | AZN | 58 | 77 | 31 | 55 | 65 | 62 | 46 | 9 |
| 8 | 5 to 13 | JNJ | 54 | 52 | 64 | 73 | 28 | 53 | 17 | 62 |
| 9 | 4 to 13 | GSK | 50 | 42 | 34 | 61 | 53 | 62 | 87 | 24 |
| 10 | 3 to 16 | AMGN | 47 | 90 | 51 | 6 | 47 | 44 | 24 | 79 |
| 11 | 6 to 16 | SNY | 46 | 51 | 18 | 82 | 40 | 41 | 96 | 18 |
| 12 | 5 to 17 | GILD | 42 | 32 | 81 | 31 | 16 | 50 | 41 | 74 |
| 13 | 4 to 17 | PFE | 40 | 3 | 17 | 9 | 94 | 75 | 72 | 68 |
| 14 | 7 to 17 | ABBV | 39 | 48 | 43 | 15 | 21 | 66 | 27 | 38 |
| 15 | 9 to 17 | BIIB | 37 | 19 | 36 | 27 | 57 | 44 | 62 | 76 |
| 16 | 10 to 17 | MRK | 36 | 29 | 44 | 30 | 61 | 12 | 26 | 88 |
| 17 | 10 to 17 | BMY | 35 | 13 | 50 | 49 | 41 | 25 | 92 | 68 |
| 18 | 17 to 18 | BAYN | 11 | 12 | 0 | 21 | 6 | · | 86 | 53 |

Ranges are where the rank falls in 90 of 100 random weightings (2.11); "·" is a pillar with no
data. All four corners of the chart hold companies: stronger at higher multiples (VRTX, REGN, LLY,
ROG, AZN, JNJ), stronger at lower multiples (NVS, NVO, GSK), weaker at lower multiples (SNY, PFE,
BIIB, BMY, BAYN), weaker at higher multiples (AMGN, GILD, ABBV, MRK). REGN sits on the line (64.8,
49.6). The commercial and clinical cohorts are in Appendix B.

### 2.16 What the score does not claim

It does not say a company is a buy or a sell (the model rating on Forecast does that, on a
different basis). It does not say a deal was good, and in this build it does not count deals at
all. It does not compare across cohorts: a 60 in big pharma and a 60 among clinical-stage biotechs
are places in different races, and Compare says so when it puts them side by side. It does not
move with the peer set a reader edits, or with the share price.

---

## 3. The visual

### 3.1 The chart

**Axes.** Company score across (0 to 100, "company score → stronger"), value score up (0 to 100,
"value score → lower multiples"). Why these two:

1. They are a portfolio manager's two questions: what am I buying, and what am I paying for it.
   Quality at a reasonable price is the most common large-cap screen, and in healthcare the market
   prices patent cliffs and pipelines into the multiple, so the two belong on separate axes.
2. They separate the companies. The two scores rank-correlate −0.35 across big pharma, −0.05 in
   the commercial cohort and −0.29 in the clinical cohort, and all four quadrants of big pharma
   hold companies (2.15). Growth against value would not: P/E and EPS growth rank-correlate 0.67
   across big pharma, so that chart redraws the market's own pricing line.
3. They move the way a reader expects: the company score changes when a filing, a consensus update
   or a pipeline change lands; value changes every close. No business measure divides by market
   cap, so day to day the bubbles drift up and down and move across only on news.
4. It is the clinical scorecard's chart: two scores from 0 to 100, the better corner at top right,
   tinted. Nothing new to learn.

**Marks.**

| Element | Rule |
|---|---|
| Bubble | one per company with both scores, at (company score, value score), never moved to avoid another |
| Area | market cap: `size = 100 × sqrt(market cap / largest market cap in the cohort)`, radius `6 + 9 × size / 100` px (6 to 15, score_map's range); drawn largest first, so a small bubble sits on top of a large one (LNTH over INCY) |
| Fill | solid (0.9) when every business pillar is scored; hollow when one or more is missing. Colour is never the only signal: a hollow bubble's tooltip says "on {k} of {K} pillars" |
| Colour | the open company in UP with a GROUND gap ring (score_map's treatment); every other company MUTED |
| Number in the bubble | its rank in the table, so chart and table read together without a label |
| Ring | a TEXT ring, 1.4 px, on a company picked for Compare or open in the panel; drawn by the frame (3.4) |
| Labels | tickers, placed by score_map's label routine with a leader line where a label sits away from its bubble. `max_labels` defaults to the number of points when there are 20 or fewer, so every big pharma company is labelled; in a larger cohort the top five, the open company, then peers best first while room lasts, at most 12. A bubble left unlabelled still carries its rank, which finds it in the table |
| Grid | 0, 25, 50, 75, 100 on both axes, 50 dashed in RULE_STRONG, the top right quarter tinted PANEL |
| Corner captions | top right "stronger, lower multiples"; top left "weaker, lower multiples"; bottom right "stronger, higher multiples"; bottom left "weaker, higher multiples". No point is called cheap or expensive |
| Key, one line | "● every pillar scored", "○ some pillars missing", "bigger: larger market cap", "● {T}" in UP |
| Tooltip | `<title>` per bubble (section 8.1), with the price date when it is not the cohort's latest |
| Not drawn | no trend line, no error bars (the range is a rank, not a score interval), no momentum |

**At a glance.** Top right is a stronger business at lower multiples than the cohort, bottom left
the reverse; the green bubble is the open company and its number is its rank. On big pharma today
AZN sits right of the middle and just under it (58, 46): a stronger business than most of the
cohort at about its middle multiples. VRTX (72, 4) and LLY (63, 3) are the bottom right corner,
the strongest businesses at the highest multiples; BAYN is the top left (11, 86); NVS, NVO and GSK
are the stronger businesses at lower multiples. A reader who wants the number reads the table
beside it; one who wants the reason clicks the bubble.

Size in its own units: 760 x 480, scaled to its column by `viewBox` (about 845 x 535 at 1440 wide,
930 x 590 at 1600). Colours come from `components/tokens.py` only: TEXT, MUTED, UP, PANEL, RULE,
RULE_STRONG, GROUND. No blue, no red on the chart.

### 3.2 Beside it: the ranked table

Like the clinical scorecard's table, narrower, and shaded rather than numbered so the comparison is
seen before it is read:

| Column | Content |
|---|---|
| box | ticks the company for Compare (4.2) |
| # | rank, mono |
| range | "2–11", mono, muted; one number when the range is one place |
| company | ticker, the open company in bold with the UP bar at the row's left (the clinical table's `sc-mine`); the name in the tooltip |
| score | a 40 px bar and the number, mono |
| one cell per business pillar, then value | no number: a fill of UP above 50 or DOWN below it, at opacity `0.85 × |score − 50| / 50`, so 50 is the panel colour and 0 or 100 is nearly solid; "·" in MUTED when the pillar is missing. The tooltip carries the number and its basis ("Growth 77, on 2 of 2 measures; cohort median 48") |

Value is shaded like the pillars: up the chart (lower multiples than the cohort) is the buyer's
better side, the same reading as the positives and negatives.

Headers, lower case and short, each with the pillar's full name and its measures in the tooltip:
big pharma "grow", "prof", "bal.", "pipe", "dur.", "value"; commercial the same less "dur.";
clinical "pipe", "fund", "value". Rows in rank order, then the companies not ranked, muted, with
"·" for rank and the reason in the tooltip. Hovering a row rings its bubble and hovering a bubble
marks its row.

Shading takes about 100 figures off the first screen (18 rows of 6 cells) and lets the eye find a
column of weakness or a row of strength at once; the panel and Compare print every number.

### 3.3 The words on the first screen

Only these: the context bar, the axis and corner captions, the key, the table headers and its rank,
range, ticker and score columns, and one line under the chart: "How to read it: right is a
stronger business than its cohort, up is lower multiples. The number is the rank in the table.
Click a company for its facts; tick up to three to compare." (36 words). Where the frame is under
600 px tall the line moves into the key row's "How to read it" tooltip. The not-ranked and
not-on-chart lines (1.4) appear only when they apply.

### 3.4 How the chart gets into the frame

The SVG is built in Python by `charts.company_map` (section 5.2) and passed to the compsval frame
as an argument. Each bubble is a group the frame can find and style:

```html
<g class="cm-pt" data-ticker="AZN" tabindex="0" role="button" aria-label="AZN, rank 7, range 2 to 11, company score 58, value 46">
  <circle class="cm-ring" r="…" fill="none" stroke="#E8EDEA" stroke-width="1.4" opacity="0"/>
  <circle class="cm-dot" r="…" …><title>…</title></circle>
  <text class="cm-rank" …>7</text>
</g>
```

The frame binds click and Enter on `.cm-pt` to open the panel, Space to toggle Compare, and sets
the classes `is-picked` and `is-open` on the group; `scorecard.css` shows `.cm-ring` at opacity 1
for either. The SVG is never rebuilt in the browser.

---

## 4. Detail on demand

### 4.1 The company panel

Opens on a bubble or a row (click, or Enter on a focused one), over the table column; the chart
stays and the company's bubble is ringed. Esc or × closes it and returns focus to what opened it.
It is the existing `mountDetail` panel with new blocks at the top and two sections removed.

In order:

1. **Header**, as today: ticker, name, the cohort chip and the stage chip; actions "Make focal",
   "Compare" (a toggle, pressed when the company is picked), "Open in Forecast", ×.
2. **Score**: "58 · 7th of 18 big pharma · 2nd to 11th in 90 of 100 weightings", then the sentence
   (2.13).
3. **Positives and negatives**: two lists, all lines, each with its pillar's name as a small muted
   chip at the right.
4. **Pillars**: one row per business pillar, then the muted rule "Price, not in the score", then
   value and momentum. A row is the pillar's name, a bar from 0 to 100 with the cohort median as a
   tick, the score, and "on {k} of {K} measures" when `k < K`. A missing pillar reads its reason in
   place of the bar. Each row opens (click or Enter) to its metrics: label, value with its period,
   "4th best of 17", and for a gap its reason; a metric not scored in the cohort shows its value
   with "Not scored: {k} of {n} in the cohort have it". Three rows carry more:
   - Durability: "{y} years of exclusivity left", "Product revenue on file: {c}% of FY2025
     revenue", and the exclusivity losses of the next 24 months.
   - Value: each multiple beside the cohort median ("4.7× EV to sales, median 4.8×"), and where
     `market_cap_disagreement` is set, the alternative market cap and its basis.
   - Momentum: the 1-month, 3-month and 1-year moves against XLV (the existing Price section,
     moved here).
5. **Business development** (facts, not scored): "{n} deals on file in 24 months", the list of
   2.10, newest first, at most eight, with the chip "From headlines and filings, not reviewed"; the
   firepower line where it applies. Clinical companies add "Lead asset: {phase}" or "Lead asset
   marketed: {brand}, approved {Mon YYYY}", and "Shares {brand}, {owner}'s marketed drug" where it
   applies.
6. **Weights**: one muted line, "Equal weights. Under 90 of 100 random weightings the rank stays
   between 2nd and 11th." This is where the range comes from.
7. **The existing sections**, in their order: Over time, Earnings trend, Estimate revisions,
   Recent results, Key catalysts, Product and pipeline mix, Relevant filings, Notes (the reader's
   own), Model values, Data lineage (with the price date, FY0 label, balance sheet date and every
   amber flag by name).

Removed from the panel: "Against {focal}" (Compare does this for up to three) and the
"System-generated note" excerpt (Key insights holds the note). Fixed while here: Key catalysts
prints a month-only date as "Nov 2026" rather than a dash, and shows one row per asset and month.

### 4.2 Compare

Never shown until asked for.

**Picking.** The box on each table row, the panel's Compare toggle, or Space on a focused bubble.
At most three; a fourth is refused with "Compare takes up to three. Untick one first." The open
company is ticked when the view first opens for it, so ticking two more makes three. Picks last for
the session and are not saved.

**Opening.** "Compare {k}" in the context bar, enabled from two picks (tooltip "Tick two or three
companies" before that). The sheet covers the chart and the table; "Close" and Esc return to the
chart with the picks kept.

**Columns:** one per pick, equal widths, the open company first if picked, then in rank order.

**Rows on opening**, about a dozen:

| Row | Content | Marked |
|---|---|---|
| Company | ticker, name, cohort chip; market cap ($bn) | no |
| Company score | the score, "7th of 18, range 2–11" under it | yes, higher |
| One row per business pillar, in cohort order | the pillar score as a shaded cell with its number; the row opens to one row per metric: value with period and place ("8.6% in FY2025, 4th best of 17") | pillar: higher; metric: by its direction |
| Value, Momentum | the score, opening to the multiples and moves | as above |
| Positives | the first three | no |
| Negatives | the first three | no |
| Business development | "{n} deals on file, newest {Mon YYYY}"; firepower where filed | no |
| Data (folded) | pillars scored ("5 of 5"), amber flags by name, price date, FY0 label, balance sheet date | no |

**The better value.** In a marked row the best cell gets a small "▲" in UP before it and weight
600; every tied best cell is marked; nothing is marked when fewer than two cells have a value. The
others stay neutral: there is no red for the weakest, since a low figure is not always bad (a high
multiple for a fast grower, a short runway for a company about to be paid). "Best" is the higher
score for score rows and the metric's own direction for metric rows.

**Companies from different cohorts.** Their metric rows are the union of the cohorts' lists, a
cell outside its cohort's list reading "not scored for {cohort noun}". Score rows are not marked,
and one muted line sits under the header: "Scored against different peers. Compare the measures,
not the scores."

A blank cell is "·" with its reason on hover. The sheet scrolls inside itself; the column headers
stay pinned.

---

## 5. Where it is built

### 5.1 Backend: `backend/company_score.py`, inside `GET /comps/valuation`

A new module, no new table, no new fetcher.

```python
SCHEMA = 2

def build(payload: dict, db_path=None, today=None) -> dict:
    """The scorecard for every company in a built /comps/valuation payload. Reads tables the
    book already has, then scores. Never raises: a failure returns
    {"schema", "error", "companies": {}} so the Comps view still opens."""

def book_inputs(conn, records: list[dict], rates: dict, today) -> dict[str, dict]:
    """Per ticker: FY0 operating cash flow and pre-tax income (USD m), share count change with
    its basis, product rows of FY0 (de-duplicated) with their exclusivity dates, freshness on
    those rows, owned approvals, partner-on-marketed-asset, gated deal events, firepower."""

def score(records: list[dict], inputs: dict[str, dict], today, seed: int = 20261001,
          draws: int = 2000) -> dict:
    """Pure. Cohorts, metric values with reasons, coverage, metric scores, pillars, company score,
    rank, rank range, value, momentum, positives, negatives, sentence, facts, chart point."""

def product_rows(rows: list[dict], fy: int) -> list[dict]:          # pure, 2.3, exact duplicates once
def gate_deals(rows: list[dict], company: dict) -> list[dict]:      # pure, 2.10
def share_change(quarters, years, net_income) -> tuple:             # pure, 2.3
def loe_years(rows: list[dict], loe: dict, today) -> tuple:         # pure, 2.3
def percentile(value, others) -> float                              # pure, 2.4
def pull(raw: float, k: int, K: int) -> float                       # pure, 2.5
def rank_range(metric_scores, spec, ranked, seed, draws) -> dict    # pure, 2.11
```

`main.py`, the existing route:

```python
@app.get("/comps/valuation")
def comps_valuation_view():
    payload = comps_valuation_module.build()
    payload["scorecard"] = company_score_module.build(payload)
    ok = payload["complete"] and not payload["scorecard"].get("error")
    headers = {} if ok else {response_cache.SKIP: "1"}
    return JSONResponse(payload, headers=headers)
```

A scorecard that failed is never cached as a complete answer.

The reads, all of tables the book already has: from `financials`, `CashFlowOperating` and
`IncomeBeforeTax` for the FY0 year, and `WeightedAverageDilutedShares` and `NetIncomeLoss` by
quarter and by year; the `deals` rows of 730 days; `asset_revenue` rows of the FY0 year for owned
assets; `loe.for_assets(conn, exclude_orphan=True)`; `approvals` for owned assets;
`productivity.portfolio_freshness(conn, id, rates, today=FY0 period end)`; and `assumptions` rows
with key `partner_ticker`. On the book they add about 0.6 s to the 6.8 s build. The scorecard block
stays under 350 KB (deal lists capped at 8 rows a company and quotes at 160 characters).

Two small changes outside the module, both owned by E1:

- `fetchers/deals_news.py` gains two public names, `DEAL_VERBS = _DEAL_VERBS` and `COMMENTARY =
  _COMMENTARY`, so the scorecard does not reach into the fetcher's private names.
- `asset_revenue.fy_product_rows(conn, company_id, fiscal_year)` returns one fiscal year's product
  rows with exact duplicates counted once, and `productivity.portfolio_freshness` reads its rows
  through it, so the Pipelines tab's freshness stops counting VRTX's Trikafta twice too (VRTX:
  4.7% before, 8.9% after).

Why inside the existing payload rather than a new endpoint: the Comps view and Key insights both
need it, and both already read this payload through one Streamlit cache, so one read gives both
tabs the same numbers by construction. A separate endpoint would build `comps_valuation` a second
time (7 s cold) or depend on another cache's timing, and the two tabs could show different scores
for a minute, which is what happened to the share price during refresh run 125.

### 5.2 Frontend, Comps: compsval revision 4

The scorecard is drawn inside the compsval frame, from the server's objects, with the chart built
in Python.

- **Why the frame.** A bubble must be clickable, and the frame already has what a click opens: the
  company panel with every fact, the peer drawer, the table, keyboard handling, focus return. A
  chart drawn by Streamlit cannot be clicked; rebuilding the panel in Python would give the page two
  panels.
- **Why Python draws the chart.** `charts.company_map` reuses `score_map`'s drawing, the look the
  user liked, rather than porting it to JavaScript. The frame only shows the SVG and binds clicks.
- **Why no scoring in the browser.** core.js only arranges `payload.scorecard` into rows, columns
  and cells; a second implementation would give each reader different scores and leave Key
  insights unable to show the same numbers.
- **Testable at each layer:** the method in pytest, the arrangement in node tests, the wiring in
  AppTest, the look in the headless driver.

**Files.**

| File | Change |
|---|---|
| `components/charts.py` | `company_map(points, width=760, height=480, open_ticker=None, max_labels=None)`, `max_labels` defaulting to the number of points up to 20 and to 12 above; bubbles drawn largest first; the shared drawing moves into a private `_bubble_map` that `score_map` also calls, with `score_map`'s output unchanged byte for byte |
| `components/compsval/__init__.py` | `REVISION = 4`; `MODES = ("full", "bridge")` unchanged; `comps_valuation(..., chart_svg=None)`; bridge strips `scorecard` and `detail` |
| `components/compsval/core.js` | `buildScorecard(A)` into `view.scorecard` (rows with shaded cells: `fill`, `alpha`, `title`); `buildCompare(A)` into `view.compare` (groups with `open` state); `buildDetail` gains `scorecard` and loses `against`; state `ui.view`, `ui.compare`, `ui.compareOpen`, `ui.comparePrimed`, `ui.compareRowsOpen`; actions `SET_VIEW`, `TOGGLE_COMPARE`, `OPEN_COMPARE`, `CLOSE_COMPARE`, `TOGGLE_COMPARE_ROW`; full mode stops deriving `conclusion`, `kpis`, `observations`, `insight`, `scatter` |
| `components/compsval/scorecard.js` (new) | `mountScorecard` (chart host, ranked table, the lines under it) and `mountCompare` (the sheet) |
| `components/compsval/panels.js` | the detail panel's Score, Positives and negatives, Pillars, Business development and Weights blocks; drop Against and the system note; month-only dates in Key catalysts |
| `components/compsval/shell.js` | Scorecard view mounts `scorecard`, `compare`, `detail`, `method`; Table view mounts `scope`, `table`, `charts` (folded by default), `detail`, `peers`, `method`; the view switch and Compare button in the context bar; the peer control, period buttons and Basis menu only in Table view; no banner, no KPI strip; inject `chart_svg` when its digest changes |
| `components/compsval/scorecard.css` (new), `index.html` | styles for the above, tokens only |
| `streamlit_app.py`, Comps section | sub-tab "Valuation" renamed "Companies"; `_company_map_points(scorecard, ticker)` and the `company_map` call in `_comps_valuation_view`, passing `chart_svg` |

**What of the current Valuation view.** Removed from the page in this build (not mounted, not
derived): the conclusion banner with its confidence chip and "Look next", "Why?", the KPI strip,
the Drivers and risks section (its metric observations became the positives and negatives; its
catalyst and competition evidence is rebuilt on Catalysts and Comps > Indications), the "Valuation
and growth" scatter tab, the panel's "Against {focal}" and system-note excerpt, the palette
commands `catalysts.open` and `forecast.open`. Kept: the context bar (less of it in Scorecard
view), the scope line, the comparables table with its toolbar, presets and filters (Table view),
the Position dot plot (Table view, folded), the peer drawer, the methodology drawer (it shows the
scorecard's method in Scorecard view, 8.6), the company panel (extended), the footer, bridge mode.
The removed parts' code and tests are deleted in build step 6, after the new view has shipped.

### 5.3 Frontend, Key insights: Python

`streamlit_app.py`, the `with insights_tab:` block, rewritten to section 1.3. It reads:

- `_comps_valuation_payload(api_base)["scorecard"]["companies"][ticker]` and the cohort's
  `medians`, the same cached object the Comps tab reads;
- `_comps_context(api_base, ticker)` for Next, through `drivers.rank_events` (5.4), the first three
  rows;
- the feed already read at the top of the page for What changed, rows of significance high, less
  `revenue_restatement` and `rate_move`, the leading "{T} " removed from each headline;
- `/companies/{t}/fair-value` for the model cell, as today.

This adds no read: the page runs every tab on each rerun, so the Comps payload and the focal
context are already fetched and cached for the minute.

`charts.pillar_bars(rows, width=520)` draws block 3: rows `{label, score, median, note}` and one
`{separator: "Price, not in the score"}`; label in TEXT, a track in RULE, the bar in MUTED, the
cohort median as a 1 px TEXT tick, the number at the right in TEXT, UP at 75 or more, DOWN at 25 or
less; a missing pillar prints its reason in MUTED where the bar would be; a note prints in MUTED
under its label.

The calls that only fed removed blocks go: `/companies/{t}/intraday` (sparkline),
`/companies/{t}/deals` and `/companies/{t}/readouts` (What happened). The `/pipeline` read stays
only if another tab still uses it on the same run.

### 5.4 Frontend, Catalysts: Python

Drivers and risks is drawn by Streamlit, not by a compsval mode. Its rows need no click into the
frame, and Key insights needs the same ranked list, so one Python function serves both.

`frontend/drivers.py` (new, pure, no Streamlit import):

```python
DRIVER_MIN_PCT = 0.01   # a valued readout under this share of the price is ranked by date
SLIP_MIN_DAYS = 90      # a readout slip this long or longer, detected in the last 90 days

def rank_events(context: dict) -> list[dict]:
    """comps-context catalysts, one row per asset, in the order of core.js compareCatalysts:
    tier 0 a priced stake (largest share of price first), 1 regulatory, 2 a late-stage readout
    of an unapproved asset valued at DRIVER_MIN_PCT of the price or more (largest first),
    3 other late-stage readouts, 4 the rest; inside tiers 1, 3 and 4 by date, then id.
    Each row: {lead, asset, event, indication, date_text, estimated, per_share, source}."""

def risks(company: dict, context: dict, feed: list[dict], today) -> list[dict]:
    """Exclusivity losses of the next 24 months from scorecard.companies[T].exclusivity_losses,
    then readout slips from the feed (change type date_slip, SLIP_MIN_DAYS or more, detected in
    the last 90 days, at most two, newest first, longer first on a shared day), then crowded pools
    from context.competition (company_pool.keeps at or under 0.90 and the indication worth 2% of
    the price or more, the core.js pool rule). At most five rows, each under 15 words."""
```

`streamlit_app.py`, the `with catalysts_tab:` block: `_drivers_and_risks(api_base, ticker)` first
(section head, two columns, "Show {n} more" as a `st.expander` holding the rest of the Drivers),
then At stake without its unpriced lines, then the calendar and its rows inside one folded
`st.expander`, the caption from the corrected `calendar_view.caption` (8.5).

---

## 6. Data contracts

### 6.1 `payload.scorecard`

Added to the `GET /comps/valuation` body. Every figure a frontend prints is in it, formatted
(`text`, `place`, `sentence`, line `text`), so Python and JavaScript print the same characters.
Scores are whole numbers; `raw` and `score_raw` keep the unrounded values for tests and for
ranking. Nulls carry a reason code.

```jsonc
"scorecard": {
  "schema": 2,
  "generated_at": "2026-10-01T07:05:20Z",
  "today": "2026-10-01",
  "error": null,                        // or "TypeError: …"; then cohorts and companies are {}
  "method": {
    "rules": {"coverage": 0.6667, "min_distinct": 3, "positive_at": 75, "negative_at": 25,
              "revenue_floor_usd_m": 100, "product_coverage": [0.60, 1.10], "loe_dated_floor": 0.5,
              "deal_window_days": 730, "deal_list_max": 8, "range": {"seed": 20261001,
              "draws": 2000, "level": 90}},
    "pillars": {                        // id -> label, table header, kind
      "growth": {"label": "Growth", "column": "grow", "kind": "business"},
      "profitability": {"label": "Profitability", "column": "prof", "kind": "business"},
      "balance_sheet": {"label": "Balance sheet", "column": "bal.", "kind": "business"},
      "pipeline": {"label": "Pipeline", "column": "pipe", "kind": "business"},
      "durability": {"label": "Durability", "column": "dur.", "kind": "business"},
      "funding": {"label": "Funding", "column": "fund", "kind": "business"},
      "value": {"label": "Value", "column": "value", "kind": "price"},
      "momentum": {"label": "Momentum", "column": "mom.", "kind": "price"}
    },
    "metrics": {                        // id -> label, better side, unit of `text`
      "rev_growth": {"label": "Revenue growth", "better": "higher", "unit": "pct1"},
      "nd_ocf": {"label": "Net debt to operating cash flow", "better": "lower", "unit": "mult1"}
      // … every metric of 2.2, labels as in 8.2
    },
    "text": {"how_to_read": "…", "method": ["…"]}   // section 8
  },
  "cohorts": {
    "big_pharma": {
      "label": "Big pharma", "noun": "big pharma", "n": 18,
      "pillars": [                      // this cohort's scored list, in display order
        {"id": "growth", "metrics": ["rev_growth", "rev_cagr3"]},
        {"id": "profitability", "metrics": ["op_margin", "pretax_margin", "fcf_margin"]},
        {"id": "balance_sheet", "metrics": ["nd_ocf", "net_cash_rev"]},
        {"id": "pipeline", "metrics": ["late_compounds", "late_per_rev", "fresh_share"]},
        {"id": "durability", "metrics": ["loe_years", "top_product"]},
        {"id": "value", "metrics": ["pe_ntm", "ev_sales", "fcf_yield"]},
        {"id": "momentum", "metrics": ["rel_1y", "rel_3m"]}
      ],
      "not_scored": [{"metric": "eps_cagr", "have": 11, "of": 18}],
      "ranked": ["VRTX", "NVS", "REGN", "NVO", "LLY", "ROG", "AZN", "JNJ", "GSK", "AMGN",
                 "SNY", "GILD", "PFE", "ABBV", "BIIB", "MRK", "BMY", "BAYN"],
      "not_ranked": [],                 // [{"ticker": "ADAPY", "reason": "2 of 4 pillars, a score needs 3"}]
      "not_on_chart": [],               // [{"ticker", "reason": "no value measure on file"}]
      "medians": {"score": 49, "growth": 48, "profitability": 50, "balance_sheet": 52,
                  "pipeline": 52, "durability": 50, "value": 49, "momentum": 56},
      "metric_medians": {"pe_ntm": 15.11, "ev_sales": 4.76, "fcf_yield": 0.0512}
    }
    // "commercial", "clinical"
  },
  "companies": {
    "AZN": {
      "ticker": "AZN", "cohort": "big_pharma",
      "score": 58, "score_raw": 58.10, "rank": 7, "ranked_of": 18, "rank_range": [2, 11],
      "pillars_scored": 5, "pillars_of": 5, "reason": null,
      "value": 46, "momentum": 9,
      "sentence": "AZN scores 58, 7th of 18 big pharma, range 2–11. Strongest on growth and pipeline, weakest on profitability.",
      "pillars": {
        "growth": {"score": 77, "raw": 77.3, "k": 2, "of": 2, "reason": null, "metrics": [
          {"id": "rev_growth", "value": 0.0863, "text": "8.6%", "period": "FY2025", "score": 81.2,
           "place": "4th best", "n": 17, "reason": null, "scored": true},
          {"id": "rev_cagr3", "value": 0.0982, "text": "9.8%", "period": "FY2022 to FY2025", "score": 73.3,
           "place": "5th best", "n": 16, "reason": null, "scored": true},
          {"id": "eps_cagr", "value": null, "text": null, "score": null, "place": null, "n": null,
           "reason": "estimate_range_wide", "scored": false}]},
        "durability": {"score": 62, "raw": 62.5, "k": 2, "of": 2, "reason": null, "metrics": ["…"]}
        // … every pillar of the cohort's list, value and momentum included
      },
      "positives": [
        {"pillar": "pipeline", "metric": "late_compounds", "strength": 44.1,
         "text": "23 late-stage compounds, 2nd best of 18 big pharma", "source": "pipeline record"},
        {"pillar": "growth", "metric": "rev_growth", "strength": 31.2,
         "text": "8.6% revenue growth in FY2025, 4th best of 17 big pharma", "source": "FY2025 20-F"}],
      "negatives": [
        {"pillar": "profitability", "metric": "op_margin", "strength": 31.8,
         "text": "23.4% operating margin in FY2025, 3rd worst of 12 big pharma", "source": "FY2025 20-F"},
        {"pillar": "pipeline", "metric": "fresh_share", "strength": 31.2,
         "text": "7% of FY2025 product revenue from drugs approved since 2021, 4th worst of 17 big pharma",
         "source": "product revenue on file"}],
      "facts": {
        "multiple": {"metric": "ev_sales", "text": "4.7×", "label": "EV to sales", "median_text": "4.8×"},
        "loe_years_text": "4.6 years of exclusivity left",
        "product_coverage": 0.969,
        "lead_phase": null,                       // clinical only: {"text", "brand", "approved"}
        "partner_on": null,                       // clinical only: {"brand", "owner"}
        "deals": {"n": 6, "rows": [{"date": "2026-09-01", "type": "acquisition", "route": "news",
                  "quote": "AstraZeneca acquires ZEGFROVY rights for $600 million", "url": "https://…"}],
                  "chip": "From headlines and filings, not reviewed"},
        "firepower_usd_m": 19822
      },
      "exclusivity_losses": [
        {"asset": "Lynparza", "date": "2027-09-08", "share_of_revenue": 0.056, "basis": "drug substance patent"},
        {"asset": "Koselugo", "date": "2028-03-13", "share_of_revenue": 0.011, "basis": "drug substance patent"}],
      "chart": {"x": 58.10, "y": 45.75, "size": 49.3, "complete": true}
    }
  }
}
```

A metric outside the company's cohort list is absent, not null. A metric in the list with no value
has `value`, `text`, `score`, `place` null and `reason` set (8.4); a metric not scored in the
cohort has `scored: false` and keeps its value. A company not burning cash has runway `value` null,
`text` "not burning cash", a `score` (the non-burners' shared mid-rank) and no `reason`. A pillar
with no metric has `score` null and `reason` set. `chart` is null when the company has no score or
no value score. `firepower_usd_m` (`3 × OCF − net debt`) is present only where both are filed;
AZN's is `3 × 14,575 − 23,903 = 19,822`. `exclusivity_losses` holds the next 24 months, any cohort.

### 6.2 compsval arguments (revision 4)

| Arg | full | bridge |
|---|---|---|
| `payload` | the whole body, `scorecard` included | without `detail` and `scorecard` |
| `digest` | of `payload` | as now |
| `focal`, `engine`, `tokens`, `live`, `shared_css`, `height`, `mode` | as now | as now |
| `context`, `context_digest` | not sent (full mode no longer draws the evidence; removed in build step 6) | not sent |
| `chart_svg` | `charts.company_map(...)` for the focal's cohort, or "" when the focal has no cohort chart | absent |
| `chart_digest` | 12 hex of `chart_svg` | |

### 6.3 Frame state and view

New state, all in `state.ui` (core.js `defaultState`), and only `view` persisted to browser
storage:

| Key | Values | Default |
|---|---|---|
| `view` | "scorecard", "table" | "scorecard" |
| `compare` | up to three tickers | the focal is added once per focal, when fewer than three are picked (`comparePrimed` records it) |
| `compareOpen` | boolean | false |
| `compareRowsOpen` | pillar ids opened in Compare | none |

Actions: `SET_VIEW {value}`, `TOGGLE_COMPARE {ticker}` (a fourth is refused and announced),
`OPEN_COMPARE` (needs two), `CLOSE_COMPARE`, `TOGGLE_COMPARE_ROW {pillar}`. `OPEN_DETAIL` and
`CLOSE_DETAIL` are reused.

`view.scorecard` (core.js `buildScorecard`):

```js
{
  state: "ok" | "error",
  errorText: null,
  cohort: {id: "big_pharma", label: "Big pharma", noun: "big pharma", n: 18},
  contextText: "Scored against 18 big pharma",
  columns: [{id: "growth", header: "grow", title: "Growth: revenue growth, revenue growth 3-year CAGR"}, …, {id: "value", …}],
  rows: [{ticker: "VRTX", name: "Vertex Pharmaceuticals Incorporated", rank: 1, rangeText: "1–10", score: 72,
          cells: [{id: "growth", fill: "up" | "down" | null, alpha: 0.58, title: "Growth 84, on 2 of 2 measures; cohort median 48"}, …],
          focal: false, picked: false, ranked: true, reason: null}, …],
  notRankedText: null,              // "Not ranked: ADAPY (2 of 4 pillars, a score needs 3)."
  notOnChartText: null,
  howToRead: "How to read it: …",
  compareLabel: "Compare 1", compareEnabled: false
}
```

`view.compare` (core.js `buildCompare`, null unless `compareOpen`):

```js
{
  columns: [{ticker: "AZN", name: "AstraZeneca PLC", cohortLabel: "Big pharma"}, …],
  mixed: false,                     // true when the columns span cohorts
  groups: [{id: "score", label: "Company score", open: true,
            rows: [{id: "score", kind: "score",
                    cells: [{text: "58", sub: "7th of 18, range 2–11", best: false, reason: null}, …]}]},
           {id: "growth", label: "Growth", open: false, rows: [{kind: "score", …}, {kind: "metric", id: "rev_growth", …}]},
           …, {id: "data", label: "Data", open: false, rows: […]}]
}
```

`view.detail.scorecard` (in `buildDetail`): `{scoreLine, sentence, positives: [{text, pillarLabel}],
negatives, pillars: [{id, label, score, median, onText, reason, note, metrics: [{label, text,
period, place, reason, scored}]}], deals: {countText, rows, chip}, firepowerText, leadPhaseText,
partnerText, exclusivityRows, weightsText}`.

### 6.4 What the frames send to Python

Unchanged: `{"action": "focus", "ticker", "nonce"}` (Make focal), `{"action": "reload", "nonce"}`.
The full frame no longer sends `indication` (its evidence moved). Compare, the view switch and the
panel never leave the frame.

---

## 7. Who builds what, the tests, the order

### 7.1 Ownership

Five engineers. Each file has one owner; where two touch `streamlit_app.py` or `charts.py` they
edit different blocks, named here, so the merges are clean.

| Owner | Files |
|---|---|
| E1, backend scoring | `backend/company_score.py` (new); `backend/main.py` (the one route); `backend/fetchers/deals_news.py` (two public aliases); `backend/asset_revenue.py` (`fy_product_rows`) and `backend/productivity.py` (read through it); `backend/tests/test_company_score.py` (new); `backend/tests/fixtures/company_score/` (new) |
| E2, frontend Comps | `frontend/components/compsval/*`; `frontend/components/charts.py`: `_bubble_map` and `company_map`, placed directly after `score_map`; `streamlit_app.py`: the Comps block (`with comps_tab:`), `_comps_valuation_view`, `_company_map_points`; `frontend/tests/compsval/*.test.js`; `backend/tests/test_comps_tab_ui.py` |
| E3, frontend Key insights | `streamlit_app.py`: the `with insights_tab:` block and any helper it alone uses; `frontend/components/charts.py`: `pillar_bars`, appended at the end of the file; `frontend/assets/research.css`: the `.ki-` rules, appended at the end; `backend/tests/test_insights_tab_ui.py` (new) |
| E4, frontend Catalysts | `frontend/drivers.py` (new); `streamlit_app.py`: the `with catalysts_tab:` block, `_drivers_and_risks` (new); `frontend/calendar_view.py` (`caption`); `backend/tests/test_drivers.py` (new); `backend/tests/test_catalysts_tab_ui.py` (new) |
| E5, tests and review | `backend/tests/test_scorecard_consistency.py` (new); `backend/tests/test_scorecard_copy.py` (new); the screenshot pass with the headless driver; the cleanup of step 6 with E2 |

### 7.2 Tests

**E1, `test_company_score.py`** (pure functions on fixtures, no API):

- `percentile`: mid-rank with ties; the company excluded from its own reference set; flipped for
  lower-is-better.
- `pull`: `w = 1` with every metric; 0.75 for one of two; 2/3 for one of three; null with none.
- the coverage rule: a metric held by 11 of 18, or with 2 distinct levels, is not scored and is
  listed in `not_scored`; a pillar with no scored metric leaves the cohort's list.
- the floors give null with the right reason; a margin on revenue under $100m ranks last, tied,
  and prints its revenue; `no_debt_line` never reads as nil debt; "not burning" ranks above every
  burner and ties the rest; a negative free cash flow yield is null.
- flags: every amber code in the fixture payload is in the null table or the shown table of 2.8,
  and a new code fails the test; `derived_operating_income` nulls the operating margin and leaves
  pre-tax margin; `market_cap_disagreement` nulls nothing.
- `share_change`: ABEO and IONS null with `dilution_basis_changed`; a ratio under 0.5 or over 20
  null.
- `product_rows` and the product gate: VRTX's two Trikafta rows count once (top product 86%);
  BAYN at 17% gives `partial_product_revenue`; JNJ at 64% passes.
- `eps_cagr`: MRK null with `eps_base_depressed`.
- `fresh_share`: NVO counts Wegovy with today set to FY0's end; LNTH null with `inferred_dates`.
- company score null below the pillar minimum, with the reason; rank over ranked companies only;
  ties broken by ticker.
- `rank_range`: deterministic for the seed; the ranked set held fixed (a company with no score
  never enters a draw); on a six-company synthetic cohort where one company leads every metric,
  its range is [1, 1].
- positives and negatives: business pillars only; one of each per pillar at most; the 75 and 25
  thresholds; the natural-zero rule for growth, margins, net cash and share change; the absolute
  rules only fill a pillar with no negative, never on a metric with a positive, and test the
  displayed value (23.9 months makes no runway line); the partner rule silences CRSP's pipeline
  lines; "best" and "worst" counted in the metric's direction; pluralisation.
- `gate_deals`: on saved rows from the book (fixture `deals_rows.json`, the 24-month rows of AZN,
  LLY, VRTX, CRSP, GPCR, JNJ, IOVA, GSK, NVS, ROG, MRK, BIIB, BMY, NVO and BEAM): GSK keeps 7,
  drops "Massachusetts" and "US-based" as non-names, merges "SBP Group" into the filing of the same
  day and drops the savings-plan row; NVS drops "U.S", ROG "Biz", MRK "Firm", BIIB "Waltham" and LLY
  "CAR-T"; MRK, BIIB and LLY count a deal its 10-Qs repeat once (Verona, Terns, Apellis, Orna);
  BMY drops Microsoft, NVIDIA and Anthropic; NVO drops Pocketpills, Hims, OpenAI, Amazon and
  Anthropic; AZN keeps both CSPC deals; BEAM drops its Bio Palette termination; CRSP keeps Eli
  Lilly only; IOVA keeps none.
- `loe_years`: past dates count 0; revenue-weighted on the FY0 rows; null under half dated.
- the sentence: the AZN, LLY and CRSP sentences of 2.14 from their fixture scores; 30 words or
  fewer for every company in the fixture.
- the worked examples: with `fixtures/company_score/book_2026-10-01.json` (the 70 records trimmed
  to the fields `score()` reads, plus the captured book inputs), `score()` gives the big pharma
  table of 2.15 exactly, Appendix B exactly, and the AZN, LLY, PFE, VRTX and CRSP rows of 2.14 to
  one decimal.
- `build()` returns `{"error": …}` rather than raising when a read fails; the route then sets the
  cache-skip header; the block is under 350 KB.

**E1, the book guard** (marked like the other book guards, runs against a `.backup` copy, never the
live file): every company is in exactly one cohort; every metric listed for a cohort is scored in
it or appears in `not_scored`; at least 15 of 18 big pharma are ranked.

**E2, `core.test.js`**: `buildScorecard` rows, fills, alphas and the not-ranked line from
`fixture_payload.json` with a `scorecard` block added; `TOGGLE_COMPARE` refuses a fourth;
`buildCompare` opens with pillar groups closed and the data group folded, marks the best cell by
direction, marks ties, marks nothing with one value, does not mark score rows across cohorts and
adds the mixed line; `buildDetail().scorecard` carries the weights text and the deals block; full
mode derives no `conclusion`, `kpis`, `observations` or `insight`. **`shell.test.js`**: the
Scorecard view mounts four slots and the Table view six; the peer control is hidden in Scorecard
view. **`scorecard.test.js`**: clicking `.cm-pt` opens the panel; Space toggles `is-picked`.

**E2, Python:** `company_map` draws one `.cm-pt` group a company with `data-ticker`, labels all 18
big pharma tickers by default, draws the largest bubble first, the open company in UP, a hollow
bubble for a company missing a pillar, the four corner captions, and no line beyond the grid's ten;
`score_map`'s existing test in `test_landscape_score.py` passes unchanged. `test_comps_tab_ui.py`:
the sub-tabs read Companies, Indications, Pipelines; the component receives `chart_svg` and a
payload with `scorecard`; the arguments parse as strict JSON.

**E3, `test_insights_tab_ui.py`** (AppTest, skipped without the API like the other tab tests): the
strip has four cells in order, each value before its sub; the multiple cell equals
`facts.multiple`; the exclusivity cell equals the first `exclusivity_losses` row; the sentence
equals `scorecard.companies[T].sentence`; the lines equal the first three positives and negatives;
Next equals `drivers.rank_events(context)[:3]`; What changed holds no `revenue_restatement` or
`rate_move` row and no leading ticker; no sparkline, What happened or Dated ahead block is drawn;
the morning note is folded. `pillar_bars` unit test: one bar a scored pillar, the separator, a
reason in place of a missing bar, a note under its label, colours from tokens only.

**E4, `test_drivers.py`**: `rank_events` on `ctx_AZN.json` and `ctx_LLY.json` (saved to
fixtures) gives Elecoglipron then Truqap, Saphnelo, Enhertu for AZN and Retatrutide then Zepbound,
Foundayo for LLY; one row per asset; a valued readout under 1% of the price ranks by date; a
marketed drug's row leads with its month; "est." on estimated dates and none on a month-only date.
`risks`: AZN gives Lynparza, Koselugo, two slips and the obesity pool; CRSP gives none; every row
is under 15 words and starts with a number. **`test_catalysts_tab_ui.py`**: Drivers and risks is
first on the tab; At stake prints no "unpriced" line; the calendar sits in a folded expander and
its caption names Phase 1/2, Phase 2 and Phase 3.

**E5:**

- `test_scorecard_consistency.py`: for AZN, LLY, PFE, VRTX and CRSP the Key insights strip, the
  Comps rows and the Compare cells show the same score, rank, range, pillar scores and line texts
  as the payload (Python reads the AppTest tree; the JavaScript side through a node script over the
  same payload); Key insights Next equals the first three Drivers on Catalysts; and the parity of
  the measures computed both by `company_score` and core.js (P/E NTM, EV to sales on FY0, revenue
  growth), equal to 1e-9 for every company where both have a value, plus free cash flow yield's
  null on negative free cash flow in both.
- `test_scorecard_copy.py`: every fixed string of section 8 and every generated sentence and line
  of the fixture pass the house-style lint (sentence case, no em dash, none of the six banned
  words), the same rules as core.js `lintCopy`; every reason code the payload emits maps to a text
  in 8.4.
- the screenshot pass: Key insights, Comps > Companies (closed, panel open, Compare of three) and
  Catalysts for AZN, LLY, CRSP at 1440 x 810 and 1600 x 1000 with the driver in
  `work-keep/driver/`; the first-screen word counts of 8.7 measured the way `understand_tabs.md`
  counted them. The spec is signed off on these measurements, not on the drawings' estimates.

### 7.3 Build order

```
1. E1  company_score.py, the route, the two small changes, fixtures, tests ──┐  first; freezes 6.1
   E1  writes fixtures/company_score/sample_scorecard.json                    │  (the whole block)
2. E4  drivers.py and its tests (needs only comps-context fixtures)          ──┤  in parallel with 1
3. E2  company_map, Scorecard view, panel blocks, Compare                    ──┤  against the sample payload, then the live API
   E3  Key insights                                                            │  against the sample payload and drivers.py
   E4  the Catalysts tab                                                       │  after 1 for exclusivity_losses
4. E5  consistency, copy and parity tests; screenshot pass                   ──┤  as 3 lands
5. All  one review pass at 1440 x 810 and 1600 x 1000                        ──┤  word budgets of 8.7 measured
6. E2+E5 delete the code and tests of what 5.2 removed                       ──┘  a separate commit, after 5
```

Commits stay one concern each, conventional messages, as CLAUDE.md asks.

---

## 8. Copy

House style throughout: sentence case, no em dashes, none of the words additionally, highlight,
underscore, pivotal, showcase, testament; number first; specific. Negative numbers use the minus
sign (U+2212), multiples the times sign (U+00D7), as the Comps view already does.

### 8.1 Fixed labels

| Where | Text |
|---|---|
| Comps sub-tab | Companies |
| View switch | Scorecard · Table |
| Context bar, cohort | Scored against {n} {cohort noun} |
| Compare button | Compare {k} (tooltip before two picks: "Tick two or three companies") |
| Fourth pick | Compare takes up to three. Untick one first. |
| Chart axis, across | company score  →  stronger |
| Chart axis, up | value score  →  lower multiples |
| Corner captions | stronger, lower multiples · weaker, lower multiples · stronger, higher multiples · weaker, higher multiples |
| Key | every pillar scored · some pillars missing · bigger: larger market cap · {T} |
| How to read it | How to read it: right is a stronger business than its cohort, up is lower multiples. The number is the rank in the table. Click a company for its facts; tick up to three to compare. |
| Bubble tooltip | {T} {name}. Company score {S}, {rank} of {n}, range {lo}–{hi}. Value {v}. {Pillar} {s}, … (on {k} of {K} pillars, when fewer) [Price of {d}, when not the cohort's latest.] |
| Not ranked | Not ranked: {T} ({k} of {K} pillars, a score needs {m}). |
| Not on the chart | Not on the chart: {T} (no value measure on file). |
| Scorecard failed | The scorecard did not load: {error}. The Table view still works. |
| Table headers | grow · prof · bal. · pipe · dur. · value; clinical: pipe · fund · value |
| Table cell tooltip | {Pillar} {s}, on {k} of {K} measures; cohort median {m} |
| Panel score line | {S} · {rank} of {n} {cohort noun} · {lo} to {hi} in 90 of 100 weightings |
| Panel headings | Positives · Negatives · Pillars · Price, not in the score · Business development · Weights |
| Pillar row, partial | on {k} of {K} measures |
| Metric not scored | Not scored: {k} of {n} in the cohort have it |
| Weights | Equal weights. Under 90 of 100 random weightings the rank stays between {lo} and {hi}. |
| Deals count | {n} deals on file in 24 months (1 deal; none: "No deal on file in 24 months.", never a scored zero) |
| Deal list chip | From headlines and filings, not reviewed |
| Firepower | Could fund about ${x}bn of deals before net debt reaches three times operating cash flow. |
| Product coverage | Product revenue on file: {c}% of {FY} revenue |
| Lead phase | Lead asset in {phase} · Lead asset marketed: {brand}, approved {Mon YYYY} |
| Partner fact | Shares {brand}, {owner}'s marketed drug |
| Panel action | Compare (a toggle) |
| Compare title, close | Compare · Close |
| Compare groups | Company · Company score · {pillar labels} · Value · Momentum · Positives · Negatives · Business development · Data |
| Mixed cohorts | Scored against different peers. Compare the measures, not the scores. |
| Cell outside a cohort's list | not scored for {cohort noun} |
| Key insights strip keys | last close · model · multiple · next exclusivity loss |
| Key insights strip subs | {x}% on the day · {rating}, {price} in 12 months · {label}, median {m} · {p}% of {FY} revenue, {asset} |
| Key insights strip, empty | · and "not modelled" (model); · and "no multiple on file" (multiple); · and "none in 24 months" (exclusivity) |
| Key insights sections | Company score (basis "against {n} {cohort noun}") · Positives and negatives · Next (basis "3 of {k} assets in 12 months, Catalysts has them all") · What changed (basis "5 of {h} high in 30 days, News has them all") · Morning note |
| Key insights bars separator | Price, not in the score |
| Durability bar note | {y} years of exclusivity left |
| Next, empty | No event dated in the next 12 months. |
| What changed, empty | Nothing rated high in 30 days. |
| Catalysts section | Drivers and risks (basis "events in 12 months, exclusivity losses in 24 · model output marked") |
| Catalysts lists | Drivers ({k} assets in 12 months) · Risks |
| Drivers more | Show {n} more |
| Risks more | Show {n} more |
| Driver row, valued | {$x}  {asset} · {event} · {indication} · {date} |
| Driver row, other | {date}  {asset} · {event} · {indication} |
| Risk rows | {p}% of revenue  {asset} exclusivity ends {d Mon YYYY} · {n} days  {NCT} readout slips to {Mon YYYY} · {k}% kept  {indication}: {c} candidates in a {n}-drug pool (model) |
| Drivers and risks, empty | No dated event or exclusivity loss on file for {T}. |
| Calendar expander | Calendar, 24 months · {n} dated events |

### 8.2 Metric labels and line phrases

`{v}` is the formatted value, `{FY}` the FY0 label, `{FYm3}` the label three years before.

| Metric | Label (panel, Compare) | Line phrase |
|---|---|---|
| `rev_growth` | Revenue growth | {v} revenue growth in {FY} |
| `rev_cagr3` | Revenue growth, 3-year CAGR | {v} a year revenue growth, {FYm3} to {FY} |
| `eps_cagr` | Street EPS growth, FY1 to FY3 | {v} a year street EPS growth, {FY1} to {FY3} |
| `op_margin` | Operating margin | {v} operating margin in {FY} |
| `pretax_margin` | Pre-tax margin | {v} pre-tax margin in {FY} |
| `fcf_margin` | Free cash flow margin | {v} free cash flow margin in {FY} |
| any margin, revenue under $100m | as above | ${r}m of revenue in {FY}, too little to compare margins |
| `nd_ocf` | Net debt to operating cash flow | Net debt of {v} operating cash flow; below zero: Net cash of {v} operating cash flow |
| `net_cash_rev` | Net cash to revenue | Net cash of {v} revenue; below zero: Net debt of {v} revenue |
| `runway` | Cash runway | {v} of cash runway |
| `share_change` | Share count change, 1 year | {v} change in share count over a year (a plus sign on a rise) |
| `late_compounds` | Late-stage compounds | {v} late-stage compound(s) |
| `late_per_rev` | Late-stage compounds per $10bn revenue | {v} late-stage compounds per $10bn of revenue |
| `fresh_share` | Revenue from launches of the last 5 years | {v} of {FY} product revenue from drugs approved since {FY − 4} |
| `loe_years` | Exclusivity left, revenue-weighted | {v} of exclusivity left on {FY} product revenue |
| `top_product` | Revenue from the top product | {v} of {FY} revenue from {product} |
| `mid_late_compounds` | Compounds in Phase 2 or later | {v} compound(s) in Phase 2 or later |
| `trial_conc` | Trials on the lead asset | {v} of trials on the lead asset |
| `pe_ntm` | P/E, next 12 months | {v} P/E on the next 12 months |
| `ev_sales` | EV to sales, FY0 | {v} EV to {FY} sales |
| `mcap_sales` | Market cap to sales, FY0 | {v} market cap to {FY} sales |
| `fcf_yield` | Free cash flow yield | {v} free cash flow yield |
| `mcap_cash` | Market cap to cash | {v} market cap to cash |
| `rel_1y` | Against XLV, 1 year | {v} against XLV over 1 year |
| `rel_3m` | Against XLV, 3 months | {v} against XLV over 3 months |

Every ranked line ends ", {place} of {n} {cohort noun}", with place "best", "{k}th best", "worst",
"{k}th worst", "joint " before it on a tie. Absolute lines: "{m} months of cash runway, under two
years"; "{p}% of {FY} revenue from {product}, over half"; "Net debt of {x}× operating cash flow,
above 3×". The product name drops anything in brackets ("Trikafta (Copackaged)" prints
"Trikafta").

Value formats (`unit`): `pct1` "8.6%", and whole percent at 100% or more ("767%"); `pct1s`
"+10.8%" (signed); `pct0` "68%"; `mult1` "15.7×"; `num1` "3.9"; `num0` "23"; `months` "77 months"
or "not burning cash"; `years` "4.6 years"; `points` "+29 points" (the relative return in
percentage points, signed); `phase` "Phase 1/2" or "marketed".

### 8.3 Bands

| Score | Table cell and bar tone |
|---|---|
| 75 or more | bar UP; cell UP at opacity 0.85 × (s − 50) / 50 |
| 51 to 74 | bar MUTED; cell UP, fainter |
| 50 | no fill |
| 26 to 49 | bar MUTED; cell DOWN, fainter |
| 25 or less | bar DOWN; cell DOWN |

The sentence's strongest and weakest clauses read the rounded score: 60 or more, 40 or less.

### 8.4 Reasons for a gap

Every reason code the payload emits has a text; the copy test fails on one without.

| Code | Text |
|---|---|
| `below_revenue_floor` | Revenue under $100m, so ratios on it are not meaningful |
| `growth_not_meaningful` | Growth on a base under $10m, or beyond 500%, is not meaningful |
| `one_year_only` | One fiscal year on file, so no growth |
| `insufficient_history` | Under four fiscal years on file, so no 3-year growth |
| `eps_base` | Base EPS under 0.10, so EPS growth is not meaningful |
| `eps_base_depressed` | Next year's consensus is under half of the year after, so growth from it is not meaningful |
| `non_positive_base` | Base EPS at or below zero, so EPS growth is not meaningful |
| `eps_not_positive` | Consensus EPS at or below zero in the next 12 months |
| `no_consensus` | No street estimates on file |
| `no_consensus_otc` | No street estimates on file for this over-the-counter listing |
| `no_revenue` | No revenue filed for FY0 |
| `no_debt_line` | No debt line filed, so net debt is not known |
| `burning_cash` | Operating cash flow is negative |
| `not_filed` | Not filed |
| `no_cash_flow` | No cash flow statement on file |
| `dilution_basis_changed` | Net income changed sign between the two periods, so diluted share counts are not comparable |
| `share_split` | Share count fell by more than half in a year: a reverse split the book cannot see |
| `share_scale` | Share counts more than twentyfold apart: a scale error |
| `no_pipeline` | No mapped pipeline on file |
| `no_trials` | No trials on file |
| `no_product_revenue` | No product revenue on file |
| `partial_product_revenue` | Product revenue on file covers {c}% of revenue, outside 60% to 110% |
| `under_half_dated` | Under half of product revenue has a dated exclusivity |
| `no_dated_approvals` | No approval dates for the products on file |
| `inferred_dates` | Some product revenue has no approval date of its own |
| `fcf_negative` | Free cash flow is negative, so a yield is not meaningful |
| `no_cash` | No cash on file |
| `short_history` | Under a full window of prices |
| `not_scored_in_cohort` | Not scored: {k} of {n} in the cohort have it |
| `not_applicable` | Does not apply before product revenue |
| `no_free_data` | No free data for any of its measures |
| `too_few_pillars` | {k} of {K} pillars, a score needs {m} |
| `derived_operating_income` | Operating income is derived, not filed, so it may leave out charges |
| `estimate_range_wide` | Estimates spread too wide to rank |
| `thin_estimates` | Too few analysts to rank |
| `burn_flattered` | The burn rate on file is understated |
| `stale_fiscal_year` | The latest filed year is more than 15 months old |
| `currency_mismatch` | The years compared are filed in different currencies |
| `stale_shares` | The share count on file is over a year old |

### 8.5 Calendar caption (Catalysts)

"{n} ahead in the next 24 months. [{m} carry a month and no day, which is all the registry gives,
so they sit in the month rather than on a date in it.] Readouts come from the primary completion
dates of Phase 1/2, Phase 2 and Phase 3 trials, regulatory dates from filings announcing an FDA
acceptance, and both are rebuilt on every refresh."

### 8.6 How it is scored (methodology drawer, Scorecard view)

"How it is scored, each from 0 to 100."

- "Cohort: {cohort label}, {n} companies, the same for every reader. Editing peers changes the
  Table view, not the scores."
- "Each measure: the share of the cohort it beats, ties counted half, turned so 100 is the better
  side. A measure counts once two thirds of the cohort have it."
- "Each pillar: the average of its measures, moved toward the cohort middle when some are
  missing."
- "Company score: the average of the business pillars, moved the same way. It needs {m} of {K}."
- "Value and momentum are scored the same way and kept out of the company score: they are the
  price, not the business."
- "Range: where the rank falls in 90 of 100 random weightings of the pillars and their measures."
- "Positives and negatives: a business measure in the cohort's top or bottom quarter, at most one
  of each a pillar. A few fixed tests add others: runway under two years, one product over half of
  revenue, net debt over three times operating cash flow."
- "Deals are listed, not scored, until the deal records are reviewed."
- "A figure the data flags as not like for like is not scored. A gap says why."

### 8.7 Word budgets, first screen

Counted as `understand_tabs.md` counted them: visible text inside the viewport below the tab strip
after drawing, a figure one word. The estimates count the drawings of section 1; the budgets are
checked on the built pages (7.2, E5).

| Tab | AZN today | Estimate from the drawing, 1600 x 1000 | Budget 1600 x 1000 | Budget 1440 x 810 | Of which prose |
|---|---|---|---|---|---|
| Key insights | 615 | 240 | 270 | 220 | sentence and lines only, 75 |
| Comps > Companies | 522 | 220 | 260 | 230 | 36 |
| Catalysts | 628 | 125 | 180 | 160 | 0 |

LLY and CRSP must also come in under the same budgets. A budget missed is a bug, not a tweak.

---

## 9. Gaps and follow-ups

Found on the way, not built here, each with its owner's file.

1. **Deals reader** (`fetchers/deals_news.py` `parse_deal`, `deals.py`): stores headlines that do
   not name the company, ratings, endings, settlements, insider purchases and vendor contracts as
   deals, and misses some real ones (the SRPT and Arrowhead licence of November 2024). The
   scorecard's gate (2.10) cleans the list it shows; the fix belongs in the reader. Scoring
   business development and partnering waits on it and on a reviewed fixture of the 18 big
   pharma's 24-month deals.
2. **Deal values** (`deals.py` `recent_rows`): the stated structure overrides the headline value
   when they differ (LLY's Kelonia, Centessa, Orna, AtaiBeckley at $250m; MRK's Terns at $132m and
   Verona at $500m; ABBV's Capstan at $15.78bn). The scorecard quotes headlines, never values.
3. **Five-year LOE share** (`asset_revenue.build_revenue_at_risk`): the window ends at
   `years[4]` = 2030 and already-generic revenue never reaches the numerator. The scorecard uses
   revenue-weighted years and dated exclusivity losses instead; the Table view still shows the
   share.
4. **Partnered assets and catalysts**: CRSP's Casgevy is VRTX's asset, so CRSP's pipeline reads
   Phase 1/2 and comps-context gives it no catalyst. The partner economics sit in `assumptions`
   (`partner_ticker`, `economics_share`); the `asset_economics` table is empty. Reading them would
   attach a partner's share to its pipeline and catalysts.
5. **Model state disagreements**: CRSP fair value ok while the comps payload says `not_modelled`;
   MRNA's −90% upside on 0% model coverage. Neither feeds the scorecard; both show on Key insights'
   model cell.
6. **Estimate revisions**: score them as a measure under momentum once three months of consensus
   history exist (from about 16 Dec 2026); the payload already carries `eps_first`.
7. **Scorecard snapshots**: writing the company and pillar scores to `snapshots` on each refresh
   would let What changed say "Growth 62 to 48 after the Q2 10-Q". It needs a materiality rule (a
   pillar move of 10 or more, a rank move of three or more) so value and momentum, which move
   daily, never reach the feed.
8. **Comps > Pipelines quadrant** ("R&D against commercial performance"): it is a two-score company
   chart beside the new one. Keep or fold, for the user to decide once both are on screen.
9. **Product revenue rows**: VRTX's Trikafta is on file twice (assets 102 and 6972, one should
   fold into the other through `asset_merge`); EXEL has no FY2025 product rows and a junk FY2024
   "Product Gross" line; SRPT holds only Elevidys and IONS 12% of its revenue; LNTH's Pylarify has
   no approval row, so its freshness is inferred. Filling the commercial cohort's product revenue
   to two thirds would bring durability into its score.
10. **Restatement significance** (`diff.py`): a product revenue restatement over 5% is rated high,
    so ten AZN restatements of 5 Sep outnumbered every other high change. Key insights now leaves
    them to News; rating them medium, or printing them as "$2m to $79m", belongs in the diff
    engine and would change News and the snapshots, so it is not done here.
11. **One horizon for events**: comps-context reads 12 months (`WINDOW_DAYS = 365`), so Drivers
    hold 12 months while the folded calendar holds 24. A `days` argument on the comps-context
    route would let Drivers run to 24 months if the user wants one horizon on the tab.

---

## Appendix A. The reference scripts

All in `work-keep/proto/r2/`, run on the `.backup` of the book (`work-keep/proto/book.db`) and the
saved payload (`work-keep/proto/comps_valuation.json`). Throwaway code that fixes the method's
numbers; `company_score.py` re-implements it. Run in this order:

| Script | What it does | Run |
|---|---|---|
| `prodrev.py` | FY0 product rows per commercial-stage company, exact duplicates once, coverage against FY0 revenue; writes `prodrev.json` | any python 3 |
| `pretax.py` | FY0 `IncomeBeforeTax` in USD m; writes `pretax.json` | any python 3 |
| `inputs.py` | the book reads of 5.1 that need the backend: share count change with its basis, freshness anchored on FY0's end and de-duplicated, exclusivity dates on the FY0 rows, owned approvals, partner-on-marketed-asset, and the deal gate of 2.10; writes `inputs.json` | from `backend/` with the venv python |
| `score.py` | the method of section 2 end to end, the rank range included; writes `scores.json`, prints the cohorts and the examples named on the command line | `python3 r2/score.py AZN LLY PFE VRTX CRSP` |
| `tables.py` | the tables of 2.14, 2.15 and Appendix B; writes them as markdown | `python3 r2/tables.py > r2/tables.md` |

FY0 operating cash flow comes from `understand_analyst_bd.json` (field `cfo`), carried over from
the research reports. Revision 1's scripts (`spec_scores.py`, `spec_deal_gate.py`, `spec_loe.py`)
stay in `work-keep/proto/` for the record; the share count change it read
(`metrics_all.json` `b_share_growth_yoy`) came from a step no script records, and revision 2 no
longer uses it.

E1 assembles `backend/tests/fixtures/company_score/book_2026-10-01.json` from these files: the 70
records of `comps_valuation.json` trimmed to the fields of 2.3, and per ticker the captured inputs
(`inputs.json`, `prodrev.json`, `pretax.json`, the operating cash flow). `score()` on that fixture
must reproduce 2.14, 2.15 and Appendix B, which pins the port to the reference.

## Appendix B. The other two cohorts today

Commercial biotech and cell and gene (22; ADAPY not ranked):

| # | Range | Company | Score | Growth | Profit | Balance | Pipeline | Value | Momentum |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 to 9 | INCY | 75 | 47 | 81 | 72 | 100 | 71 | 79 |
| 2 | 2 to 7 | NBIX | 73 | 53 | 76 | 72 | 90 | 65 | 40 |
| 3 | 1 to 8 | ALNY | 72 | 87 | 62 | 72 | 67 | 29 | 19 |
| 4 | 2 to 6 | ARGX | 71 | · | 77 | 72 | 67 | 24 | 71 |
| 5 | 1 to 12 | BNTX | 69 | · | 43 | 72 | 95 | 41 | 55 |
| 6 | 1 to 13 | UTHR | 65 | 27 | 96 | 72 | 67 | 53 | 48 |
| 7 | 1 to 15 | KRYS | 63 | 67 | 97 | 72 | 17 | 12 | 67 |
| 8 | 3 to 15 | EXEL | 62 | 20 | 88 | 72 | 67 | 59 | 79 |
| 9 | 7 to 13 | BMRN | 59 | 33 | 65 | 72 | 67 | 82 | 64 |
| 10 | 1 to 14 | AXSM | 59 | 93 | 46 | · | 40 | 18 | 52 |
| 11 | 8 to 16 | LNTH | 54 | 13 | 65 | 72 | 67 | 76 | 71 |
| 12 | 3 to 17 | RGNX | 51 | 100 | 26 | 11 | 67 | 88 | 17 |
| 13 | 8 to 15 | IONS | 50 | 60 | 35 | 39 | 67 | 35 | 17 |
| 14 | 5 to 16 | LEGN | 50 | 80 | 53 | · | 17 | 47 | 17 |
| 15 | 11 to 15 | SRPT | 49 | 40 | 44 | 72 | 40 | 94 | 48 |
| 16 | 11 to 19 | IOVA | 32 | 73 | 17 | 22 | 17 | 6 | 98 |
| 17 | 12 to 21 | MRNA | 30 | 0 | 19 | · | 67 | 0 | 98 |
| 18 | 13 to 21 | ATRA | 24 | 7 | 66 | 6 | 17 | 100 | 17 |
| 19 | 16 to 19 | QURE | 20 | · | 5 | 33 | 17 | · | 2 |
| 20 | 18 to 20 | ABEO | 19 | · | 5 | 28 | 17 | · | 38 |
| 21 | 19 to 21 | AUTL | 15 | · | 5 | 17 | 17 | · | 76 |
| · | · | ADAPY | · | · | · | 0 | 17 | · | 29 |

Clinical-stage biotech and cell and gene (30):

| # | Range | Company | Score | Pipeline | Funding | Value | Momentum |
|---|---|---|---|---|---|---|---|
| 1 | 1 to 3 | ARWR | 87 | 91 | 82 | 10 | 81 |
| 2 | 2 to 8 | ARCT | 79 | 82 | 76 | 62 | 67 |
| 3 | 3 to 10 | DYN | 75 | 82 | 68 | 28 | 53 |
| 4 | 1 to 21 | BEAM | 72 | 58 | 87 | 48 | 47 |
| 5 | 2 to 18 | ALLO | 68 | 77 | 59 | 83 | 71 |
| 6 | 5 to 12 | RVMD | 67 | 59 | 76 | 0 | 95 |
| 7 | 2 to 19 | FATE | 67 | 71 | 63 | 72 | 83 |
| 8 | 3 to 14 | GPCR | 65 | 57 | 72 | 17 | 34 |
| 9 | 4 to 18 | NTLA | 62 | 82 | 43 | 31 | 22 |
| 10 | 2 to 23 | CRSP | 59 | 33 | 85 | 45 | 67 |
| 11 | 6 to 17 | VKTX | 58 | 52 | 65 | 3 | 72 |
| 12 | 10 to 15 | WVE | 58 | 65 | 52 | 66 | 7 |
| 13 | 6 to 21 | SLDB | 58 | 72 | 43 | 59 | 41 |
| 14 | 6 to 20 | TSHA | 56 | 38 | 74 | 24 | 67 |
| 15 | 4 to 20 | RCKT | 56 | 77 | 35 | 100 | 29 |
| 16 | 11 to 22 | STOK | 49 | 38 | 59 | 21 | 53 |
| 17 | 11 to 22 | CAPR | 48 | 38 | 57 | 41 | 41 |
| 18 | 6 to 25 | VYGR | 47 | 43 | 52 | 90 | 17 |
| 19 | 5 to 24 | KYTX | 47 | 66 | 28 | 52 | 62 |
| 20 | 4 to 25 | ALT | 47 | 38 | 56 | 93 | 60 |
| 21 | 16 to 27 | SANA | 34 | 33 | 35 | 14 | 55 |
| 22 | 14 to 29 | PRME | 33 | 43 | 22 | 7 | 38 |
| 23 | 16 to 30 | CABA | 31 | 49 | 13 | 76 | 29 |
| 24 | 19 to 27 | PEPG | 31 | 38 | 24 | 79 | 55 |
| 25 | 13 to 29 | CRBU | 29 | 16 | 43 | 86 | 26 |
| 26 | 18 to 28 | KRRO | 27 | 16 | 37 | 97 | 24 |
| 27 | 21 to 28 | EDIT | 26 | 16 | 35 | 69 | 36 |
| 28 | 16 to 30 | IPSC | 26 | 16 | 35 | 34 | 67 |
| 29 | 20 to 29 | VOR | 25 | 38 | 12 | 38 | 47 |
| 30 | 27 to 30 | SGMOQ | 14 | 16 | 11 | 55 | 50 |

Commercial notes. Durability is not in this cohort's list (product revenue usable for 7 of 22),
so four pillars make the score and a company needs three. The balance sheet column reads 72 for
the 11 companies not burning cash: runway is its only scored measure, and they tie at the top.
ABEO, AUTL and QURE have under $100m of revenue: their margins rank last (2.4) and they have no
value score, so they are ranked but not on the chart. ADAPY's FY0 is FY2024 (`stale_fiscal_year`),
which nulls its growth and margins and leaves 2 of 4 pillars: not ranked. The ranges run from 2–6
(ARGX) to 1–15 (KRYS, strong on margins and weak on pipeline).

Clinical notes. ARWR leads, range 1 to 3: 2 compounds in Phase 2 or later (the most any of the 30
has), 38% of its trials on the lead asset, and a 3.1% share count rise over the year; its runway is
not scored (`burn_flattered`). Its approved Redemplo shows in the panel as a fact. With two pillars
the ranges are wide (median 12.5 places of 30): a company strong on one and weak on the other moves
across most of the cohort as the weights move (BEAM 1 to 21, CRSP 2 to 23).

## Appendix C. Resolved review points

Revision 1 was reviewed on 2026-10-01 in 35 points. Each was checked against the brief and the
book before it was acted on; the checks are in `work-keep/proto/r2/` and the scratchpad scripts
`critic1.py` to `critic6.py`. "Accepted" means the spec now does what the point asked or more;
"in part" and "kept" say what was not done and why.

1. **Catalysts missed its word budget and listed the catalysts twice** (blocker). Accepted.
   Drivers is the tab's one list; the calendar folds into "Calendar, 24 months"; the drawing
   estimate is about 125 words against a budget of 180, and sign-off waits for the measured count
   at 1600 x 1000 and 1440 x 810 (7.2, E5). Drivers keep comps-context's 12 months rather than 24:
   that is the window the event values are computed for, and a longer one is a backend change
   listed in section 9, item 11.
2. **The business development pillar scored duplicates and non-deals; GSK's line was false**
   (blocker). Accepted, further than asked: business development is not scored at all in this
   build (2.10). The gate for the panel's list now drops non-names and places, merges a news row
   into the filing of the same deal, and drops vendors, crop and animal health. GSK, NVS, ROG, MRK
   and BIIB are in the gate fixture (7.2).
3. **Drivers and risks arrived nearly empty, its one sentence moved unedited**. Accepted. The spec
   now says plainly that the metric half became the positives and negatives (0.11, 5.2). Drivers
   hold the ranked events, Risks the exclusivity losses, slipped readouts and crowded pools, each
   number first and under 15 words ("73% kept  Obesity: 2 candidates in a 19-drug pool (model)").
   With nothing to show, the section is one muted line.
4. **Exclusivity losses disappeared from Key insights and Catalysts**. Accepted. They are Risks
   rows with their share of FY0 revenue, the strip's fourth cell ("Sep 2027 · 5.6% of FY2025
   revenue, Lynparza"), and a block in the panel's durability row (`exclusivity_losses`, 6.1).
5. **Key insights said several things twice**. Accepted. The strip is last close, model, the
   multiple against the cohort median and the next exclusivity loss; none repeats a block below.
   The sentence names pillars without numbers; the bars carry them. The basis texts no longer
   repeat the cohort, and "since the last refresh" became "in 30 days", which is what the feed
   spans. Market cap was not added to the strip: the multiple is the figure a reader compares, and
   market cap is in the panel and Compare.
6. **"Valuation 44" read backwards**. Accepted. The pillar and the axis are "Value" ("value score →
   lower multiples"); the strip and the panel print the multiple itself beside the cohort median;
   no score follows a ratio's name anywhere, and the sentence has no valuation clause.
7. **Share-price moves led the negatives**. Accepted. Positives and negatives come from the
   business pillars only (2.12); value and momentum have their own rows in the panel and Compare.
8. **Business development broke its positive-only rule and missed a deal on the same screen**.
   Accepted by not scoring it: no "weakest on business development", no red cell. The list says
   "on file", counts deal events rather than counterparties (AZN's two CSPC deals stay two), and
   the firepower line sits beside it. The Summit deal reached What changed through a press
   release before the deals table read it; "on file" is the honest label until the reader does.
9. **Next showed estimated dates as firm and ranked by date, not value**. Accepted in part. Next is
   now the first three rows of the Drivers list, the same object; every registry date carries
   "est." and a month-only date prints as the month. Not taken: leading every line with a value a
   share, and the point's account of the current ranking. The live Catalysts ahead list does not
   put Tagrisso and Imfinzi first: it puts readouts that decide an unapproved asset's value first
   (Elecoglipron, $4.68, tops AZN's list on `driver/shots/comps_AZN_text.json`) and gives a
   marketed drug's readout no value, because one new indication does not put Tagrisso's whole
   $10.31 at stake. That rule is kept, with a 1% of price floor so a $0.05 asset no longer
   outranks Enhertu's breast cancer readout.
10. **"Exclusivity runway" was half product concentration**. Accepted. The pillar is
    "Durability" (years of exclusivity left and reliance on the top product), and its bar carries
    the years left as a note.
11. **The Comps comparison was a grid of about 125 numbers**. Accepted. Pillar and value cells are
    shaded, the number on hover (3.2). With the deals column gone the table needs 40% of the frame.
12. **Lines built on known book errors**. Accepted in part. CRSP's pipeline lines are silenced
    because it is the partner on a marketed drug; that fact is in `assumptions` (`partner_ticker`),
    not in `asset_economics`, which is empty. Lead phase is no longer scored, prints "marketed" only
    with an approvals row, and reads "Lead asset marketed: Redemplo, approved Nov 2025". Not taken:
    moving a company with FY0 revenue of $100m or more into the commercial cohort. BEAM, IPSC and
    STOK pass that test on collaboration revenue with no product, and ranking licence income
    against product sales on margins would be the error. A company moves when it files product
    revenue, which is the record's own stage rule.
13. **Compare opened as a sheet of about 40 rows**. Accepted. It opens on about a dozen rows, each
    pillar expanding to its measures and the data rows folded (4.2).
14. **Lines carried no period or source, some read the wrong way, and two partnering lines**.
    Accepted. Each phrase carries its year or span, each line its source (2.12); places read
    "best" or "worst" in the measure's own direction; partnering makes no line now.
15. **The rank range was worded three ways**. Accepted. "range 2–11" everywhere, and in the panel
    "2nd to 11th in 90 of 100 weightings". "Could sit" is gone.
16. **At 1440 px the strip cut off the key number**. Accepted. Every cell puts its number first
    ("+19.5%", then "Buy, 193.03 in 12 months").
17. **The balance sheet pillar used market cap**. Accepted. Net cash to revenue replaces net cash
    to market cap; no business measure divides by market cap (2.2).
18. **What changed carried raw restatements rated high**. Accepted in part. Key insights leaves
    `revenue_restatement` and `rate_move` rows to News and drops the leading ticker. Re-rating
    restatements belongs in the diff engine and would change News and the snapshots, so it is
    listed in section 9, item 10.
19. **The labelling rule contradicted the signature; headers were tight at 1440 px**. Accepted in
    part. `max_labels` defaults to the cohort size up to 20; headers are short with full names in
    the tooltip; bubbles draw largest first, so LNTH sits on top of INCY. Not taken: moving
    overlapping bubbles apart. A bubble's position is its two scores, and moving it would draw a
    false one.
20. **Competition by indication answered a Comps question on Catalysts**. Accepted. It stays on
    Comps > Indications; its risk half reaches Catalysts as one crowded-pool row per indication.
    This departs from the brief's reading (decision 3 listed it with Drivers and risks); the
    user's own words named drivers and risks, and the one comparison stays where comparisons live.
21. **The deal gate kept ratings, endings, settlements, recitals and duplicates; two pillars ranked
    on them** (blocker). Accepted: neither business development nor partnering is scored, the gate
    excludes that language on both routes, and a company with no deal shows "No deal on file in 24
    months", never a scored zero. Re-checked on the book: the stricter gate keeps 7 for GSK, 2 for
    ROG and none for BEAM, SANA or IPSC.
22. **Share count change took the wrong sign when net income changed sign** (blocker). Accepted.
    Verified: ABEO and IONS compare a profitable quarter with a loss quarter. The book holds no
    basic weighted count and its cover-page counts do not reach back a year, so the rule nulls
    the figure (`dilution_basis_changed`: ABEO, ALNY, IONS) rather than switch basis. The script
    that computes it is `r2/inputs.py`, recorded in Appendix A. Share count change is now scored
    only in the clinical cohort (28 of 30); in the commercial cohort it fails the coverage rule.
23. **Product revenue summed to 22% to 200% of reported revenue**. Accepted with a different band.
    Product rows are one fiscal year, exact duplicates once, and must cover 60% to 110% of FY0
    revenue. The floor is 60%, not 70%: JNJ's drugs are 64% of its revenue because MedTech is a
    third of it, and its product rows are complete. VRTX's top product share is now 86% of revenue,
    the old section 9.9 is corrected (it was a duplicate, not a Trikafta and Kaftrio split), and
    the worked example follows.
24. **Lead phase read "Marketed" from a junk asset; marketed companies sat in the clinical
    cohort**. Accepted in part, as point 12: lead phase is a fact, not a metric, so a marketed lead
    no longer buys a top score; the cohort follows filed product revenue.
25. **The commercial valuation axis measured cash burn**. Accepted. A negative free cash flow yield
    is not meaningful, as core.js treats it; the commercial value score is market cap to sales;
    the per-cohort correlation of the two axes is reported (−0.35, −0.05, −0.29) and the parity
    test covers the free cash flow yield rule.
26. **The rank range was buggy and understated how far a rank can move**. Accepted. The ranked set
    is held fixed; the range is the 90% interval of 2,000 seeded random weightings of pillars and
    of the measures inside them, so metric-level sensitivity is in it too (2.11). Not taken: a tier
    in place of the rank. Most ranges cross a tier boundary, so a tier is no more certain than the
    rank; the rank stays as the chart's key to the table and the range is printed beside it.
27. **The pull toward 50 imputed the cohort middle; the gaps were not random**. Accepted. The
    method text says what the pull is (2.5); the two-thirds coverage rule stops ranking a chosen
    half; margins under the revenue floor are kept and rank last, so QURE is now ranked (19th of
    21) rather than hidden.
28. **Figures too unreliable to print still moved the score; some flags were ignored**. Accepted in
    part. A flag that makes a figure not like for like now nulls it (2.8), and every amber code
    sits in one of the two tables. Not taken: nulling on `market_cap_disagreement`. The payload's
    market cap uses the latest cover count, and the alternative is the FY2025 weighted diluted
    count, which lags share issuance (IPSC: 181m shares on 3 Aug against 87m weighted over 2025).
    Scoring IPSC on the alternative would value it on half its shares. The panel shows both.
    `stale_price` is one trading day for 22 companies; the date is shown, not withheld.
29. **Business development was not read in a positive light and the balance sheet did not offset
    it**. Accepted. It is not scored, so it is never a weakest pillar or a red cell; the claim
    about the balance sheet offset is dropped; when it is scored it can only lift a company
    (`max(50, percentile)`, 2.10).
30. **The fresh-share window was anchored on today**. Accepted. The five years run back from the
    end of the revenue year: NVO reads 27% (Wegovy counts), GILD 4.8%. The point's second rule
    (null when the newest approvals have no revenue row) did not fit the cases: GILD's newest drugs
    have rows and now count, and LNTH's problem was the reverse, a product row with no approval
    date, which is now null (`inferred_dates`). VRTX's figure also lost its duplicate Trikafta
    row (4.7% to 8.9%).
31. **EPS growth from a depressed FY1 became MRK's strongest positive**. Accepted. FY1 under half
    of FY2 is not meaningful (`eps_base_depressed`), with MRK in the fixtures. After the flag
    rules, street EPS growth is held by 11 of 18 big pharma and is not scored in any cohort.
32. **Price leaked into the business score through net cash to market cap**. Accepted, as point 17.
33. **Double counting inside the pipeline pillars**. Accepted. Late-stage compounds per $10bn of
    revenue left the commercial list; lead phase left the clinical list.
34. **Generated lines contradicted themselves or read on the wrong side of zero**. Accepted. The
    natural-zero rule covers net cash and share count change; an absolute rule never fires on a
    metric that already carries a positive; thresholds read the displayed value; counts are
    pluralised; a sentence over 30 words drops its second strongest, then second weakest pillar
    (the longest today is 21 words).
35. **Data contract gaps**. Accepted. Every reason code the payload emits has a text in 8.4 and a
    test enforces it; `no_estimates` is `no_consensus`; the gate's word lists are written out in
    2.10 from the reference script; every revenue ratio reads FY0, stated in 2.3; the route skips
    the cache when the scorecard carries an error (5.1); the deal list prints the verbatim headline
    rather than a counterparty column, so a brand in the counterparty field (ZEGFROVY) is never
    printed as a company; "marketed" has its own phrase.
