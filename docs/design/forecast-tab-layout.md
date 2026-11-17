# Forecast tab: one page, two parts, led by figures

Drafted 2026-11-17, second version. Built the same day; what shipped and where it differs
from the plan is in the last section.

## What the page is for

Two things, in this order, on one screen:

1. **Company forecast.** Where the whole company is going and what that is worth.
2. **Asset forecasts.** Which assets carry it, and how each one compares.

The page is charts, not prose. Each chart answers one question and has a small set of
choices above it, so the reader picks what is plotted: revenue, cash flow, profit, costs,
capex. Words appear only as titles, axis labels and one line under a chart saying what it
is built on. Everything else is a click away.

## The problem today, measured

Amgen's Forecast tab on a 1400 by 1000 screen: 3.8 screens tall, about 1,400 words, 28
charts, about 20 titled sections, 4 sliders and a tab set of 7 or 8 panels, all open at
once. The company is above and below one asset's workbench. No chart can be changed: each
shows one fixed measure.

## What each part has to answer

| Part | The question | The figure that answers it |
|---|---|---|
| Company | Is it worth more or less than the price? | the number strip |
| Company | Can the number be trusted? | the number strip: revenue covered, share resting on assumption |
| Company | Where is it going, and when does it fall? | chart 1, over time, to 2035 |
| Company | What is the value made of? | chart 2, the value split |
| Company | What does it depend on? | chart 3, how far each assumption can fall |
| Assets | Which assets matter? | chart 4, assets ranked |
| Assets | Is each growing or running off, and on track? | chart 5, assets over time |
| Assets | How do risk and reward line up? | chart 4's second view, two measures against each other |

## The page

```
+---------------------------------------------------------------------------------------+
| COMPANY FORECAST                                                                       |
| $467.84   $460.42   +2%     $492.65    99.3%      22%          14 Dec 2026             |
| value     price     gap     12 months  revenue    rests on     next catalyst           |
|                                        covered    assumption                           |
|                                                                                        |
| 1 THE COMPANY OVER TIME                         | 2 WHAT THE VALUE IS MADE OF          |
| [Revenue|Profit|Free cash flow|Costs|R&D|Capex] | [By source|By product|By area|       |
| [Marketed and pipeline|By product|By region]    |  By evidence]                        |
| [Each year|Cumulative] [Weighted|If all succeed]|  (bridge or bars, $ a share)         |
|                                                 |--------------------------------------|
|  reported ......| forecast ..............       | 3 WHAT IT DEPENDS ON                 |
|  ▇ ▇ ▇ ▇ ▇ ▇ ▇ ▇ ▇ ▇ ▆ ▅ ▄ ▃                    |  how far each can fall before the    |
|  2021 ......... 2026 ....... 2035               |  price is no longer supported        |
|  ◆ guidance   | exclusivity ends                |  (five bars)                         |
|                                                                                        |
| More: [Fair value range] [Peer multiples] [Cost to reach the gates] [Medicare]         |
+---------------------------------------------------------------------------------------+
| ASSET FORECASTS                                    25 valued · 4 not valued            |
|                                                                                        |
| 4 ASSETS COMPARED                               | 5 ASSETS OVER TIME                   |
| [Value|Peak revenue|Revenue in 2030|Cash flow|  | [Revenue|Free cash flow|             |
|  Chance|Exclusivity left|Return]                |  Cumulative cash|Patients]           |
| [All|Marketed|Pipeline]  [Ranked|Two measures]  | [Top five|Picked|Stacked]            |
|                                                 |                                      |
|  MariTide   ▇▇▇▇▇▇▇▇▇▇▇▇▇  $29.13               |   lines by year, reported as dots,   |
|  Prolia     ▇▇▇▇▇▇▇▇       $18.20               |   forecast as lines                  |
|  Repatha    ▇▇▇▇▇▇▇        $16.75               |                                      |
|  ...        (hatched = a judgement, not filed)  |                                      |
|                              click a bar for the asset's card · [see as a table]       |
+---------------------------------------------------------------------------------------+
```

## Part 1: company forecast

### The number strip

Seven numbers, no sentences: value a share, price, the gap between them, value in twelve
months, revenue covered, the share of the value that rests on assumption, the next
catalyst's date. The rating sits on the gap as a colour and a word.

### Chart 1: the company over time

The main chart, about 60% of the width. Reported years on the left, drawn solid, from the
filings; forecast years on the right, to 2035, so the exclusivity losses are inside the
picture. Marks on the axis where the largest products lose exclusivity, and a diamond on
the guided year where the company gives guidance.

| Choice | Options |
|---|---|
| Measure | Revenue · Operating profit · Free cash flow · Costs · R&D · Capex |
| Split | Marketed and pipeline · By product (the largest eight and the rest) · By region · None |
| View | Each year · Cumulative |
| Basis | Weighted by chances · If everything succeeds |

"Costs" stacks cost of goods, SG&A, R&D, other and tax. "Free cash flow, cumulative" is
the company's cash profile.

### Chart 2: what the value is made of

Dollars a share. One choice:

| View | Shows |
|---|---|
| By source | the bridge: products on sale, the named pipeline, launches the model assumes, net debt |
| By product | each asset's share of the value |
| By area | by therapy area |
| By evidence | filed figures against judgements and placeholders |

### Chart 3: what it depends on

Five bars: the assumptions the price depends on most, each drawn as how far it can fall
before the price is no longer supported. Today this is a table of text behind a heading;
it becomes a figure on the page.

### One click away

Fair value range, peer multiples, the cost to reach the gates, Medicare negotiation, how
the sum is built. Each as a button that prints its own headline figure.

## Part 2: asset forecasts

### Chart 4: assets compared

Every valued asset as a bar, largest first. A hatched bar is one whose figure is a
judgement or a placeholder, not a filed number. Clicking a bar opens the asset's card.

| Choice | Options |
|---|---|
| Measure | Value a share · Peak revenue · Revenue in a chosen year · Free cash flow in a chosen year · Chance of approval · Years of exclusivity left · Return on the spend still ahead |
| Show | All · Marketed · Pipeline |
| View | Ranked · Two measures against each other |

"Two measures against each other" turns the bars into a scatter: pick what goes across
and what goes up (chance against value, years of exclusivity against revenue), each asset
a dot sized by its value. This is the benchmarking the earlier notes asked for, inside one
company.

### Chart 5: assets over time

The same assets by year. Reported years as dots, the forecast as a line, so an asset
running ahead of or behind its model shows at once.

| Choice | Options |
|---|---|
| Measure | Revenue · Free cash flow · Cumulative cash · Patients on therapy |
| Which | The five largest · The ones picked in chart 4 · All, stacked |

### One click away

- **The asset's card**, from a bar or a line: today's workbench whole, with the revenue
  path, the levers, and the Drivers, Next gate, Uptake, Cash and P&L, Sensitivity and
  Assumptions tabs. The sliders and panels leave the page.
- **See as a table**: every asset one row, for the reader who wants the numbers in
  columns. The table is the secondary view, not the page.

## What each measure can honestly show

| Measure | Reported history | Forecast | By asset |
|---|---|---|---|
| Revenue | yes, 2007 on | yes | yes |
| Operating profit | yes | yes | yes |
| Free cash flow | yes (operating cash flow less capex) | yes | yes |
| Cost of goods, SG&A, R&D, tax | yes | yes | yes, as the company's ratios on each asset's revenue |
| Capex | yes, 2007 on, 74 companies | **no** | no |
| Patients on therapy | no | yes, where the asset is built from patients | yes |
| Cumulative cash | from free cash flow | yes | yes |

Capex is the one gap. The model has no capex line: what keeps the plant running is inside
other costs, and what is spent to grow is its own line, growth investment. So the Capex
choice shows the reported years and stops, and says so on the chart. Forecasting it would
need a new assumption per company, which is a decision of its own (below).

A measure with no value for a year or an asset is drawn as a gap or left off, with the
reason on hover. It is never drawn as nil.

## How it behaves

- The choices sit directly above the chart they change, as a row of buttons, one pressed.
- A change redraws that chart only, at once, with no page reload: the page receives every
  series when it opens and switches between them in the browser, the way the Comps tab does.
- The choices are kept in the address bar, so a view can be bookmarked or sent.
- Hover gives the exact figure and its source. The words are in the hover, not on the page.
- A company with one asset opens that asset's card in place of charts 4 and 5.

## What it takes to build

- One new read, `GET /companies/{ticker}/forecast/board`: the company's reported series,
  each asset's yearly revenue, costs, profit and cash flow at the company's share (the
  verdict already carries these per asset as `pnl_share` and `revenue_share`), each
  asset's scalars, and the five break-points. No new figure is computed; the board adds
  assets up and joins reported years to forecast years.
- One browser component for the two parts, built on the chart code the Comps tab uses.
- The asset card reuses the workbench as it is, inside a dialog.

## How it is checked

- The board's company series equal the sum of its assets, year by year, for every
  measure, and its value equals the sum of the parts.
- Every block on today's page is still reachable: a list of today's section titles, each
  found on the page, behind a button or in a card.
- Every choice of every chart draws for a large company, a mid-sized one and a one-asset
  biotech, and a missing value is a gap, not a nil.
- The word count of the first view is under 150, against about 1,400 today.
- Screenshots at 1400 by 1000 and 900 wide, checked by eye before it ships.

## Order of work

1. The board read and its tests.
2. The company part: the strip, chart 1 with its four choices, charts 2 and 3. The old
   company blocks move behind buttons.
3. The asset part: charts 4 and 5, the table view.
4. The asset card; the workbench leaves the page.
5. Old tests moved, the narrow layout, the one-asset case.

The tab works after every step.

## Decisions to make before step 1

1. **What each chart opens on.** The plan: chart 1 on revenue, split marketed and
   pipeline, each year, weighted by chances; chart 4 on value a share, ranked.
2. **Forecast capex.** Reported only (the plan), or add a capex assumption per company so
   it can be forecast. The second needs a sourced rule, for example capex as its own
   five-year share of revenue from the filings.
3. **The measures list.** Is anything missing that you want to pick: net income, earnings
   a share, dividends and buybacks (all reported, none forecast today)?
4. **How an asset's detail opens.** A card over the page (the plan), or in place.

## What was built, 2026-11-17

The page as planned: the number strip, the company over time with its four choices, what
the value is made of, what it depends on, the More row, assets compared (ranked rows that
open the asset's card, and two measures against each other), assets over time, and the
table. Amgen went from 3.8 screens, about 1,400 words and 28 charts to 1.45 screens,
about 230 words and five figures, with no slider on the page.

Decisions taken while building:

- **Forecast capex is drawn, from the valuation's own rule.** The engine has no capex
  line but charges plant twice, and both charges are measured from filings: upkeep at the
  company's plant depreciation over its revenue, and new plant at the pooled capex above
  depreciation per dollar of revenue added. The chart stacks the two, so the line
  reconciles with the free cash flow beside it. A separate rule (a five-year share of
  revenue) would not. A filer with no plant lines on file gets no forecast and the reason.
- **The launches the model assumes are a group of their own** in every company chart,
  hatched. They are 42% of Amgen's value, and a path that left them out fell away from
  2030 while the value did not.
- **The asset card** is today's workbench, reordered: the figures (worth, size, odds,
  life, then the rate), one chart switched between revenue, free cash flow, cumulative
  cash, costs and patients with the value bridge beside it, the levers under the chart,
  then the layers. The picker inside moves between assets without closing the card.
- **A choice redraws through the server**, not in the browser: the tab is one fragment
  and the board is cached, so a press is a redraw of that tab alone.

Not in this version:

- **By region** as a split. The verdict carries each product's regional shares, not a
  path per region after each region's own loss of exclusivity.
- **Return** as a measure in assets compared. It is one cash-profile read per asset, too
  slow for the page; it is on the asset's card.
- **Patients** in assets over time, for the same reason; it is on the card.
- **The guidance diamond** on the company chart. Guidance is read for one year by the
  fair value view and is not on the board.
- **Choices in the address bar**, and a headline figure on each More button.
