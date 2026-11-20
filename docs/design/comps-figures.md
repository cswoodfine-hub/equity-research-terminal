# Comps, Companies: the table as figures

Drafted 2026-11-17 and built the same day: what was built, and where it departs from the
plan, is the last section.

## What the table is asked

The Table view of Comps, Companies is the focal company and its peers, one row each,
against the nine measures of a preset: 18 rows by 9 columns on AstraZeneca, 162 numbers,
of which a laptop screen shows about a dozen rows and three columns before it scrolls
both ways. A reader brings four questions to it:

1. Where does the company sit against its peers, measure by measure?
2. Which peers are the cheapest and the dearest on a measure, and by how much?
3. Is a cheap peer cheap for a reason: does it also grow slower or earn less?
4. What is the exact figure?

A table answers the fourth and makes the reader do the other three by eye: sort a column
in the head, find the focal row among eighteen, hold one column in mind while reading the
next. The marks that would do that work exist (the View menu's "Premium or discount to
median" and "Percentile rank" modes) and are off by default.

## The plan in one line

Three figures, each answering one of the first three questions, drawn from the same
cells the table prints. The table stays, one press away, for the fourth.

```
+--------------------------------------------------------------------------------------+
| [Scorecard | Figures | Table]   Columns: [Core valuation v]         17 peers, median |
|                                                                                      |
| 1 WHERE AZN SITS                              | 2 THE PEERS ON  [P/E v]               |
|   each measure a strip: peers as ticks,       |   one bar a company, ranked            |
|   the middle half shaded, AZN marked          |                                        |
|                                               |   NVO   ████████████████████  24.1x    |
|  P/E          ·· ·▐█·█▌· ◆ ·  ·   16.2x  +5%  |   LLY   ███████████████████   23.0x    |
|  EV/EBITDA    · ··▐██◆█▌ ··  ·    12.1x  -2%  |   AZN   █████████████  ◀      16.2x    |
|  EV/Revenue   ·  ·▐█·█▌·◆   ·      5.3x +14%  |   ───── median 15.4x ─────             |
|  FCF yield    ◆ ·▐█·█▌ · ··        3.1%  low  |   MRK   ████████████          14.9x    |
|  P/B          ·· ▐█·█▌ ◆· ·        6.0x +31%  |   PFE   ███████                9.7x    |
|  Street target ··▐█◆█▌ ·  ·       +12%   mid  |   ...                                  |
|  Rev growth    · ▐█·█▌ · ◆ ·      +8.6% high  |   not plotted: 1 not meaningful        |
|                                               |                                        |
| 3 THE WHOLE SET   rows companies, columns measures, each cell shaded by where it      |
|   falls among the peers; a row that is pale everywhere is cheap on everything         |
+--------------------------------------------------------------------------------------+
```

## Figure 1: where the company sits

One row a measure, for the measures of the chosen preset, in the preset's order.

- **The strip.** Every peer a tick on one scale, the middle half of the peers shaded, the
  median a rule, the focal company a marked dot. The same drawing as the Peer position
  plot, one lane a measure and all of them at once.
- **Beside it.** The company's figure, its distance from the median ("+5%") and its rank
  among the peers ("6 of 17"). Three numbers a row, not eighteen.
- **Colour means direction only where there is one.** Growth and margins have a better
  end, so better than the median is green and worse is red. A multiple has no better
  end: a premium is drawn as a premium, in the neutral colour, and not as good or bad.
- **A peer across every measure.** Resting on a tick names the peer and marks the same
  peer on every strip, so one company's profile reads straight down the figure.
- **A measure with nothing to plot** (not meaningful, or no value) says so in its row and
  draws no dot. Never a dot at nil.

This is what the focal row and the median row of the table say, read at a glance.

## Figure 2: the peers on one measure

A press on a row of figure 1 puts that measure here.

- One bar a company, longest first, the focal company in the accent colour, the median
  and the two quartiles as rules across the bars, each bar's figure at its end.
- A peer left out of the statistics is drawn hatched, in its place, and marked.
- Companies with no figure are listed under the bars, with the reason, and not drawn.
- A press on a bar opens the company's side panel, as a table row does today.

This is one column of the table, sorted, with its summary rows drawn in.

## Figure 3: the whole set

Rows are companies, the focal one pinned first; columns are the preset's measures. Each
cell is shaded by where the company falls among the peers on that measure, with the
figure on it. It is the table with the marks turned on and the numbers turned down: the
shape of the page is the same, so nothing has to be relearned, and a pattern shows that
eighteen rows of numerals hide (a company cheap on every multiple; a measure where the
whole set is bunched and one name is not).

- Sorted by fit to the focal company, or by any column on a press of its head.
- Shading on the same rule as figure 1: direction where a measure has one, distance from
  the median where it does not.

## What stays and what goes

- **The view switch gains one place.** It reads Scorecard, Table today and becomes
  Scorecard, Figures, Table. Figures is what Table opens on now.
- **The table stays**, behind "Table" in that switch, with everything it does today:
  presets, sorting, filters, pins, the summary rows, the tick that takes a peer out of the
  statistics, export.
- **The preset selector is shared.** Core valuation, Growth and profitability, Balance
  sheet and risk, Pharma, Biotechnology, Cell and gene therapy choose the measures of all
  three figures, as they choose the table's columns.
- **The Position strip** folded above the table is figure 1 with one lane. In the Figures
  view it is not drawn, since figure 1 is every lane; the Table view keeps it.
- **Text and chip columns** (country, subsector, stage, lead phase, the 90-day line) are
  not measures and are not drawn in figures 1 and 2. Figure 3 prints them as they are.

## How it is built

- **No new data.** Every figure reads `view.table` from `core.js`: the cells the table
  prints, with their values, formats, flags and percentile ranks, and the summary rows.
  A figure that disagreed with the table would be a second derivation, and there is none.
- **One new module**, `figures.js`, beside `table.js` in the compsval frame, mounted in
  the table's place when the switch is on Figures. The switch is state like the preset,
  so it persists and can be driven from the command palette.
- **The frame's own rules hold**: tokens only, a description on every figure, keyboard
  reach (arrows along a strip, Enter to open the company), the shared tooltip.
- **The design contract** (`docs/design/comps-valuation.md`) gets a revision recording
  the switch and the three figures, as its earlier revisions do.

## How it is checked

- Each figure's numbers are the table's: for every preset, the focal company's figure,
  median, distance and rank in figure 1 equal the table's cells and summary rows.
- A cell the table prints as not meaningful or not available is never drawn as a value.
- Every preset draws for a big pharma, a biotech and a cell and gene company, at the wide,
  laptop and narrow layouts.
- Screenshots at 1440 by 810 and 1920 by 1080, checked by eye.

## Order of work

1. Figure 1 and the switch. The table one press away.
2. Figure 2, opened from a row of figure 1.
3. Figure 3.
4. The Position strip leaves the Figures view; the contract is revised.

The tab works after every step.

## Decisions to make first

1. **What opens.** The tab opens on Scorecard today and that stays. The question is what
   a press on the second view gives: Figures, with Table a press further (the plan), or
   Table as today with Figures beside it.
2. **Figure 3.** Wanted, or are figures 1 and 2 enough with the table behind them?
3. **The other table.** The Scorecard view has a ranked table of its own beside the
   company map. This plan is for the Table view. If the Scorecard's table is the one
   meant, the answer is different and shorter.

## What was built, 2026-11-17

Decision 1 was taken as "Figures, with the table a press further". The switch on Comps,
Companies now reads Scorecard, Figures, Table. The tab still opens on the Scorecard, as it
did; Figures is the first of the two comparables views and the table is the press after it.

- **`frontend/components/compsval/figures.js` and `figures.css`.** One module, mounted in
  the table's place. It reads `view.table` and nothing else: the columns of the preset,
  each cell's value, status, percentile and distance from the median, and the summary
  rows. The model of each figure is a pure function (`profileRows`, `rankedBars`,
  `gridModel`), tested against the table's own cells.
- **Figure 1, where the company sits.** One row a measure. Peers are ticks, the middle
  half a band, the median a rule, the company a dot; beside it the figure, the distance
  from the median and the rank. Green and red only on a measure with a better end. A
  measure with no figure says why in its row and draws no dot.
- **Figure 2, the peers on one measure.** A press on a row of figure 1 ranks the peers on
  it. Bars run from nil, so a negative reads as one; the median is a solid rule and the
  quartiles dotted. A peer out of the statistics is hatched. Companies with no figure are
  named under the bars with the reason.
- **Figure 3, the whole set.** The table's rows and columns, each cell shaded by its
  percentile among the peers: green and red where a measure has a better end, grey by
  size where it has none.
- **One company across all three.** Resting on a tick, a bar or a grid row marks that
  company on every figure. A press opens its panel, as a table row does. The bars and the
  grid rows are keyboard stops (Tab, then Enter or Space); the ticks are not, since every
  company they draw is also a bar and a row.
- **The measures control** is the table's preset, by the same action, so the two views
  never disagree about which columns are on the page.
- **Shared with the table:** the scope line, the peer drawer, the footer and the
  methodology drawer. The command palette has "Show the comparables as figures".

Where it departs from the plan:

- **The Peer position plot stays.** Step 4 had it leave the chart strip. The strip is not
  shown in the Figures view at all, so the page loses the block there, and the Table view
  keeps the strip as it was. Nothing was removed.
- **Figure 3 does not sort on a press of a column head.** It keeps the table's order, so
  a sort made in the Table view carries over. Figure 2 is the sorted reading of a column.
- **Arrows along a strip** were not built, for the reason given above.

Checked: the eight tests of `frontend/tests/compsval/figures.test.js` (every number equals
the table's cell or summary row, for every preset; a cell with no figure is never drawn),
the shell's test of the third view, and by eye on AstraZeneca at 1440 and 820 wide.
