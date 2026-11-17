# What happens to revenue after exclusivity ends, and what the model assumes

Researched 2026-11-17. The competitor record is built, and so is the rule it was built
for: what it does and what it moved is the last section. The sections before it are the
research as it stood when the rule was chosen. Beside this file: `observations.csv`, the 75 products the
question touches with their reported revenue, their competitor status and what a rule
would move; and `launch_evidence.csv`, the filers' statements the record's launches rest
on, including the ones that settled nothing.

## The question

Symbicort lost US exclusivity in 2023 and the model holds it at about $2.9bn a year for
ever. A product whose loss of exclusivity is already behind it is treated as "in the
base": its reported revenue is taken to reflect the loss, its last reported growth rate
fades to nil over five or ten years, and its terminal value is a flat perpetuity. Is flat
right?

## The answer

It depends on whether a competitor is on the market, and until now the book could not
say. With the record built, of the 75 products past exclusivity:

| Status in the United States | Products | What the model's "flat" does |
|---|---|---|
| A generic or biosimilar is on the market | 23 | overstates: their revenue is still falling |
| No biosimilar is licensed against it | 26 | fits: their revenue is flat |
| A small molecule with no generic launch recorded | 21 | fits on the evidence, which is silence |
| Licensed, and not sold or not confirmed sold | 5 | fits for now |

A decline applied to every product past exclusivity would be wrong for 52 of the 75, and
they hold most of the value: $41.22 a share of Amgen, $30.76 of AbbVie, $29.58 of Biogen.

## The competitor record

`backend/competitors.py`, read at `GET /companies/{ticker}/competitors`. It keeps three
registers apart, because each says a different thing:

| Register | What it says | What it cannot say |
|---|---|---|
| FDA Paragraph IV list | the date the first generic began selling | anything about a biologic, or a market outside the US |
| FDA Purple Book (`biosimilar_licences`, 107 licences against 23 reference brands, October 2026) | which biosimilars are licensed against a product, and whether each is still listed | whether one has launched: aflibercept has six listed and most are held off the market by settlement; etanercept has three and none is sold |
| The filer's own report (`data/competitor_launches.csv`, 53 statements; and the dated rows of `data/disclosed_loe.csv`) | that a competitor is selling, in its words, with the filing | nothing, where the filer is silent |

Across the 1,398 marketed products in the book: 111 have a competitor on the US market,
354 biologics have no biosimilar licensed, 919 small molecules have no generic launch
recorded, and 14 are licensed without a confirmed launch.

What it corrected. Humira, Remicade and Lantus were dated by the lapse of the 12-year
exclusivity and read as uncopied; each owner's filing says biosimilars are selling.
Brilinta was dated by a patent expiry and Nexium by nothing live in the Orange Book;
AstraZeneca dates the generic entry of both. Simponi has a biosimilar licensed and
listed, and J&J says a US entrant is still ahead. Perjeta has one licensed too, and
Roche's Half-Year Report 2026 does not expect it on the US market before 2028.

One thing the reading turned up that is not the record's to fix: the book dates
Perjeta's US loss of exclusivity at 2026, from Roche's Finance Report 2025. The newer
report moves it to 2028 at the earliest, and Europe to 2027.

What it could not settle, and says so: Tysabri (a biosimilar is licensed; Biogen never
says it launched in the US), Aranesp, Nplate, Vectibix, Botox and Avonex (the owner's
report is silent, and no biosimilar is licensed against any of them), Xarelto and Saxenda
(the owner describes litigation, not a launch).

## What the book's own filings show

Reported product revenue, FY2023 to FY2025, each year against the one before, counted
from the competitor's launch where there is one.

| Group | Years after | Changes | Median a year | Revenue-weighted | Share falling |
|---|---|---|---|---|---|
| Competitor on the US market | 0 to 2 | 12 (6 products) | -37.0% | -33.8% | 75% |
| Competitor on the US market | 3 or more | 13 (7 products) | -8.3% | -7.1% | 69% |
| No competitor on the US market | 3 or more | 35 (18 products) | -0.3% | -3.9% | 51% |

## What the long histories show

`data/growth_analogues.csv` holds filed annual revenue for past and present blockbusters
back to the 2000s. 37 of them fell 20% or more in a year after their peak. Counting from
that year:

| Years after the cliff | Changes | Median a year | Share falling |
|---|---|---|---|
| 1 to 3 | 76 (31 products) | -21.0% | 95% |
| 4 to 6 | 35 (13 products) | -10.8% | 74% |
| 7 to 10 | 19 (8 products) | -5.7% | 74% |
| 11 to 20 | 8 (2 products) | -2.0% | 62% |

Ten years after its peak the median product keeps a quarter of its peak revenue
(interquartile 0.17 to 0.51, 14 products). The decline slows; it does not stop at year
five. The two sources agree: about -8% a year three or more years on.

`data/erosion_defaults.csv` already records the same for a cliff still ahead: US Part D
spending four to eight years past a loss of exclusivity falls a median 10.4% a year, and
that file tested a floor and rejected it. The engine declines for ever after a cliff it
forecasts and stops only for one that has already happened.

## What the model does today with the 23

The last reported change fades in a straight line to nil over five years (ten where the
product is growing), and the terminal value is flat. The terminal value is 21% to 59% of
each one's value.

| Product | Competitor since | Reported, FY2024 and FY2025 | Model | US share of revenue |
|---|---|---|---|---|
| Symbicort | 2023 | +22%, 0% | +0.2% fading to nil | 41% |
| Tecfidera | 2020 | -4%, -30% | -30% fading to nil over 5 years | 25% |
| Remicade | 2016 | -13%, +10% | fading to nil | 100% |
| Crestor | 2016 | +4%, +5% | +5.5% fading to nil | 4% |
| Humira | 2023 | one year on file | fading to nil | 67% |
| Stelara | 2025, by Amgen's report of its own launch | -5%, -41% | -41% fading to nil over 5 years | 63% |
| Nexium | 2015 | -8%, -6% | fading to nil | 8% |

Crestor, Nexium, Plavix and Zytiga earn almost nothing in the US any more. What is left
of them is outside it, where an off-patent brand holds, and they are not falling.

## What a rule would move

Through the what-if, saving nothing: the long-run rate of the 23 set to a decline in
place of nil.

| Company | The whole product at -6% | The US share only at -6% | The US share only at -10% |
|---|---|---|---|
| BioMarin | -2.1% | -2.1% | -2.6% |
| Bayer | -1.9% | -1.9% | -2.4% |
| Roche | -3.3% | -1.6% | -2.0% |
| Sanofi | -2.4% | -1.4% | -1.7% |
| Johnson & Johnson | -1.5% (-$3.30) | -1.2% (-$2.61) | -1.5% (-$3.31) |
| AstraZeneca | -2.7% (-$4.84) | -0.7% (-$1.22) | -0.9% (-$1.57) |
| AbbVie | -0.6% | -0.4% | -0.5% |
| Biogen | -1.1% | -0.3% | -0.3% |
| BMS, Novo Nordisk | under 0.3% | under 0.2% | under 0.2% |

Each product loses 35% to 50% of its value where the whole of it declines. The figures
are first-order: a smaller book leaves more room for the launches the model assumes,
which would give some of it back.

## The recommendation

Continue the decline for a product with a competitor on the market, on the share of its
revenue in the market where the competitor is, at the late rate its own erosion shape
already carries (10% a year for a non-oral small molecule, 23% for an oral one, 25% for a
biologic). Leave everything else flat.

- It adds no new number. The rates are measured and on file, and the engine already
  applies them to a cliff it forecasts. This makes a cliff behind a product behave like
  one ahead of it.
- It is narrow: 23 products, and one to two percent of the value of the six companies it
  touches most.
- It follows the evidence both ways. The 52 without a competitor stay flat because they
  are flat.
- It moves when the record does. A biosimilar's launch, stated in a filing, moves the
  product into the declining group on the next refresh.

Two things to settle before building it:

1. **The biologic rate.** 25% a year for ever is the rate of the first years. The one
   biologic the book can follow that far, Remicade, fell 13% and then rose 10% in years
   eight and nine. A biologic late rate of about 8%, the figure both sources give for
   three or more years on, would be the measured choice; it needs one row in
   `data/erosion_defaults.csv`, and that file held it open for want of evidence.
2. **Outside the United States.** The record carries what a filer says of Europe and
   elsewhere, and the engine's regional split could decline those shares too. The
   evidence there is thinner and mixed (an off-patent brand often holds in emerging
   markets), so the first version should decline the US share alone.

## What was built, 2026-11-17

The rule, as recommended, with the biologic rate at 8%. In `forecast.build`: a product
whose loss of exclusivity is in the base, with a competitor on the US market
(`competitors.selling`), has the US share of its revenue go on falling. Each year it
changes by what the reported trend gives or by the tail rate, whichever is the lower, so
a steep first fall runs its course and the tail takes over from it and stays. The
terminal value of that share is the falling stream. The rate is the late rate of the
product's own erosion shape (23% a year for an oral small molecule, 10% for a non-oral
one), and `tail_decay_pct` in `data/erosion_defaults.csv` for a biologic: 0.08. A biologic
cliff still ahead keeps its one rate; the tail is only for a cliff already past.

What it moved:

| Company | Value a share | Change | Of which products | Of which assumed launches |
|---|---|---|---|---|
| Roche | 29.95 to 29.09 | -2.9% | -0.52 | -0.27 |
| AstraZeneca | 176.17 to 172.74 | -1.9% | -2.24 | -1.10 |
| AbbVie | 218.96 to 217.77 | -0.5% | -0.89 | -0.23 |
| Johnson & Johnson | 219.87 to 218.85 | -0.5% | -0.72 | -0.25 |
| Biogen | 248.07 to 247.09 | -0.4% | -1.06 | +0.10 |
| BMS | 110.94 to 110.77 | -0.2% | -0.13 | -0.04 |
| Sanofi | 69.93 to 69.86 | -0.1% | -0.05 | -0.01 |
| Novo Nordisk | 47.94 to 47.93 | 0.0% | 0.00 | 0.00 |

The other 38 companies with a value did not move. Symbicort went from $7.47 to $5.52 a
share, Tecfidera from $7.29 to $6.23, Humira from $3.60 to $2.71, Stelara from $3.03 to
$2.34. The launches the model assumes fell with the products and did not give anything
back, as the research expected they might: a smaller book spends less on R&D, and the
launches are bought with R&D.

Four products have a competitor on the US market and were not made to fall, because no
regional split is on file for them and the rule is for the US share: Remicade (J&J),
Lantus Solostar (Sanofi), Kuvan (BioMarin) and Yaz (Bayer). Taking the whole of each as
American cut Yaz by 88% and Remicade by 68%; Yaz is sold round the world and grew 6% last
year. Each says so on its card, and each will fall once its split is on file
(`data/region_revenue.csv`).
