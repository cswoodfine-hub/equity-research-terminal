# Erosion after a generic launch, measured

Run 2026-10-29. Reproduce with
`ER_TOOL_DB=<copy> python3 work/patents/tools/erosion_study.py --download <dir>` then
`ER_TOOL_DB=<copy> python3 work/patents/tools/erosion_study.py <dir>`.

## Method

- **Events:** every reference drug on the FDA Paragraph IV list with a first commercial
  marketing date, earliest per brand name. 322 brands; 276 join to a Part D brand name.
- **Outcome:** the brand's national Medicare Part D gross drug cost and claims for each
  year, from the CMS series "Medicare Part D Prescribers - by Geography and Drug". There
  is one dataset a year from 2013, and the National rows are read.
- **Footing:** the forecast engine's own. The launch year L is left whole and the year-one
  drop lands in L+1. Each year is measured against L-1, the last full year before any
  generic.
- **Kept:** brands with over $10mm of Part D cost in L-1 and a launch from 2014 to 2023.
  That leaves 104 events: 86 oral, 18 not.

## Result

Median brand Part D cost retained, against the year before launch:

| years after the launch year | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| oral (n 86 to 50) | 0.245 | 0.098 | 0.061 | 0.043 | 0.030 | 0.024 |
| non-oral (n 18 to 12) | 0.412 | 0.285 | 0.172 | 0.137 | 0.110 | 0.069 |
| old small-molecule default | 0.40 | 0.26 | 0.17 | 0.15 | 0.14 | 0.12 |

Claims, which are volume alone, fall further: oral 0.20 in year one. The launch year
itself, which the engine leaves whole, lost a median 18% of cost.

Spread and features:
- Oral year-one cost drop: interquartile range 0.52 to 0.87.
- One Paragraph IV filer (the 180-day exclusivity) keeps 0.276 in year one. Two or more
  filers keep about 0.15.
- A brand already falling before its launch erodes the same as one that wasn't.

## Rows written to `data/erosion_defaults.csv`

| row | year-one drop | decay | late decay from year 4 | fit |
|---|---|---|---|---|
| small molecule | 0.77 | 0.50 | 0.26 | within 0.02 of each oral median |
| small molecule (non-oral) | 0.58 | 0.34 | 0.26 | within 0.01 of each non-oral median |

Each product's route comes from the Orange Book's "DF;Route" column, reduced per
application to oral or not. The asset's own application decides it (`dose_route.py`).

## Checks against filers' US lines

- **Sprycel:** generic 2024-09-03; BMS US sales 983mm in 2024, 299mm in 2025.
- **Tasigna:** generic 2025-05-23; Novartis US sales down 21% in the partial launch year.
- **Entresto:** generic 2025-07-23; down 26% in the partial launch year.
- **Brilinta:** generic 2025-05-01; down 48% in the partial launch year.
- **Symbicort (inhaled):** Part D brand cost kept 0.30 in its first full year. But
  AstraZeneca's US line, which includes its authorised generic, was still 1,193mm in 2025.
  Brand-only Part D overstates what a holder that sells its own generic loses. That is the
  reason a recorded launch with no fall since stays in the base (`forecast.build`).

## Caveats

- **Part D is gross of rebates.** For an oral brand losing to generics the rebates fall
  away, so gross cost understates net retention somewhat. Cost rather than claims is used
  for that reason.
- **Medicare only.** Commercial plans substitute oral generics as automatically, by state
  law. That is not measured here.
- **Non-oral rows are thin** (18 events, interquartile range 0.22 to 0.74) and mix routes:
  Copaxone kept 0.84 and Zyvox 0.05.
- **Biologics are untouched.** Their row rests on eight filers' US lines, and Part D
  carries few biologics.

## What it moved

On one database, the old curves against the measured ones: 149 products move and none
rises. The total is -94bn of 2,659bn (-3.5%).

| product | LOE | NPV old curve | NPV measured | change |
|---|---|---|---|---|
| Eliquis | 2028-12-31 | 27,251 | 19,192 | -8,060 (-30%) |
| Wegovy | 2031-12-05 | 195,653 | 187,733 | -7,920 (-4%) |
| Ozempic | 2031-12-05 | 200,947 | 194,267 | -6,679 (-3%) |
| Biktarvy | 2036-04-01 | 58,166 | 54,299 | -3,867 (-7%) |
| Rinvoq | 2036-10-17 | 59,010 | 55,261 | -3,749 (-6%) |
| Farxiga | 2026-04-04 | 8,647 | 5,490 | -3,157 (-37%) |
| Entresto | 2025-09-30 | 5,893 | 3,022 | -2,871 (-49%) |
| Kisqali | 2031-11-09 | 19,983 | 17,461 | -2,522 (-13%) |
| Mounjaro | 2036-05-13 | 133,301 | 130,825 | -2,476 (-2%) |
| Vraylar | 2029-09-17 | 10,959 | 8,831 | -2,128 (-19%) |
| Vyndaqel | 2026-12-31 | 4,651 | 2,525 | -2,126 (-46%) |
| Xarelto | 2025-10-31 | 2,096 | 630 | -1,466 (-70%) |

67 products move by more than 10%. All are small molecules with an LOE inside the window,
where the measured curve says the old one kept too much.
