# Forecast tab: one page, two parts

Drafted 2026-11-17. Not built. This is the plan to agree before any code.

## The problem, measured

Amgen's Forecast tab on a 1400 by 1000 screen, as it stands:

| | Today |
|---|---|
| Height | 3.8 screens |
| Words | about 1,400 |
| Charts | 28 |
| Tables | 3 |
| Sliders | 4 |
| Titled sections | about 20 |
| Tab sets inside the tab | 1, with 7 or 8 panels |

The order is the second problem. The company comes first (figures, sum of the parts, fair
value range, summary, revenue by year, revenue build), then one asset's workbench in the
middle (path, bridge, levers, eight panels), then the company again (what breaks it, risks
that move together, development cost, peer multiples, Medicare negotiation). A reader
looking for "the company" finds it in two places with an asset between them.

Nothing is wrong with any one block. There is no order of importance: every block is
open, at full size, at once.

## The rule

The page presents two things, in this order, and nothing else at the top level:

1. **Company forecast.** What the whole company is worth and what it is forecast to sell.
2. **Asset forecasts.** Every asset on one row, the ones that carry the value first.

Both fit on one screen. Everything else is one click away and says, before the click, what
the click will show. Nothing is deleted: every block on the page today keeps a home.

## The page

```
+--------------------------------------------------------------------------------------+
| COMPANY FORECAST                                                                      |
| Amgen's equity is worth $467.84 a share on the model, 2% above the $460.42 price.     |
|                                                                                       |
| $467.84        $492.65          Buy +7%        99.3%            14 Dec 2026           |
| a share today  in 12 months     rating         revenue covered  next catalyst         |
|                                                                                       |
| +-- Revenue, reported and forecast --+  +-- Where the value comes from --------+      |
| | FY25A  FY26E  FY27E  FY28E         |  | marketed  pipeline  launches  debt   |      |
| | (stacked: marketed, pipeline)      |  | (the sum of the parts as a bridge)   |      |
| +------------------------------------+  +--------------------------------------+      |
|                                                                                       |
| More on the company:                                                                  |
| [Fair value range  $396 to $542] [What breaks it  3 levers] [Revenue by product]      |
| [Peer multiples] [Cost to reach the gates] [Medicare negotiation  2 drugs] [...]      |
+--------------------------------------------------------------------------------------+
| ASSET FORECASTS                    25 assets · $ a share · click a row for its card   |
|                                                                                       |
| MARKETED                 value   of price  peak revenue    exclusivity  path          |
| Prolia                   $18.20   4.0%     $4.1bn  2025    2025         ▂▃▅▇▆▃▁       |
| Repatha                  $16.75   3.6%     $3.9bn  2029    2029         ▂▄▆▇▇▅▂       |
| ...                                                                                   |
| PIPELINE, AFTER ITS CHANCES   value   of price  chance  peak revenue  next readout    |
| MariTide                 $29.13   6.3%     55%     $16.6bn 2034   21 Jan 2027         |
| Olpasiran                 $4.06   0.9%     58%     ...            31 Mar 2028         |
| ...                                              [show all 25]                        |
+--------------------------------------------------------------------------------------+
```

### Part 1: company forecast

Always on screen:

- **One sentence.** The first sentence of today's forecast summary. The rest of that
  paragraph moves behind "How the sum is built".
- **Five figures.** Value a share, value in twelve months, rating, revenue covered, next
  catalyst. Today's six, less the share price, which the sentence already states.
- **Two charts, half a screen wide each.** Revenue by year (reported, then three forecast
  years, marketed and pipeline stacked) and the sum of the parts as a bridge. These are
  the two the question "what is the forecast" needs: what it sells and what that is worth.

One click away, as a row of labelled buttons. Each prints its own headline figure, so the
row itself is a summary, the pattern the Catalysts tab's "More detail" rail already uses:

| Button | Shows | What moves there |
|---|---|---|
| How the sum is built | the rest of the summary paragraph and the sum's workings | "Forecast summary", "How the sum is built" |
| Fair value range | low to high across the lenses | "Fair value range", "How each lens is built" |
| Revenue by product | the stacked build by product and year | "Revenue build" |
| What breaks it | how far each assumption can fall before the price | "What breaks it", "Risks that move together" |
| Peer multiples | value implied by peers | "Value implied by peer multiples" |
| Cost to reach the gates | development cost across the pipeline | the company development table |
| Medicare negotiation | drugs selected and the price cut | "Medicare price negotiation" |

Each opens as a card over the page, the way a Catalysts row opens its card, and closes
back to where the reader was.

### Part 2: asset forecasts

Always on screen: one table, every asset one row, marketed first then pipeline, each
group sorted by value a share. It replaces today's "Value by asset" list, which shows the
same assets with fewer facts and no way to compare them.

- Marketed columns: value a share, share of the price (as a bar), peak revenue and its
  year, exclusivity year, and the revenue path as a small line.
- Pipeline columns: value a share after its chances, share of the price, chance of
  approval, peak revenue and its year, the next readout's date.
- The first rows carry the value. The table shows as many as fit the screen and a "show
  all" for the rest; the count is always stated.

One click away: a row opens that asset's card. The card is today's workbench, whole:

- on top, the asset's figures, its revenue path and where its value sits;
- under that, the tabs that exist today: Drivers, Next gate, Uptake, Cash and P&L,
  Sensitivity, Assumptions;
- the levers (volume, price, chance, discount rate) sit inside the card, under the path
  they move.

So the four sliders and the eight panels leave the page and appear only for the asset
the reader chose.

## What changes for the reader

| | Today | After |
|---|---|---|
| Height on a 1400 by 1000 screen | 3.8 screens | 1 |
| Charts on first view | 28 | 2, plus one small line a row |
| Sections open at once | about 20 | 2 |
| Where the company is | above and below the asset | the top half |
| Where an asset's detail is | in the middle of the page, always open | its card, on a click |

## What it rests on

- The page already reads everything it needs from two calls: the company verdict and the
  asset's forecast. No new figure is computed. The asset table needs three fields per row
  the verdict already carries (`peak_revenue`, `peak_year`, `loe_year`, `pos`) and a
  revenue path it also carries (`revenue_share`).
- The asset's detail is fetched when its card opens, not for the first asset on load, so
  the tab opens faster than today.
- The cards use the dialog the Catalysts tab uses.

## How it is checked

- The existing app tests that open the Forecast tab are moved to the new structure, not
  deleted: each one that reads a panel now opens the card first.
- New tests: the page shows exactly two sections; every block on today's page is
  reachable (a list of today's section titles, each found behind a button or in a card);
  the asset table has one row per modelled asset and its values sum to the company's.
- House style and "a null is never a zero" tests on every visible string.
- A screenshot at 1400 by 1000 and at 900 wide for Amgen (large), Vertex (mid) and a
  one-asset biotech, checked by eye before it ships.

## Order of work

1. The company part: the sentence, the five figures, the two charts, the button row with
   the cards behind it. The asset workbench stays where it is for now, under it.
2. The asset table, replacing "Value by asset".
3. The asset card: the workbench moves into it and leaves the page.
4. Tests moved and added; the narrow layout.

Each step leaves the tab working, so it can ship step by step.

## Decisions to make before step 1

1. **How an asset's detail opens.** A card over the page (the plan, as Catalysts does), or
   the row opening in place beneath itself, or a panel sliding in from the right. A card
   keeps the page still; opening in place keeps the table in view but pushes the page down.
2. **The second company chart.** The plan uses the sum of the parts as a bridge. The fair
   value range is the alternative, if "what is it worth against the price" matters more
   than "where the value comes from".
3. **The levers.** Inside the asset card only (the plan), or also a company-level lever on
   the main page.
4. **How many asset rows.** As many as fit with "show all" (the plan), or always all of
   them and let the page scroll.
