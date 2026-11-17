# What happens to revenue after exclusivity ends, and what the model assumes

Researched 2026-11-17. Nothing is implemented. `observations.csv` beside this file is
every product the question touches, with its reported revenue, what the model assumes
for it and what a different rule would do to its value.

## The question

Symbicort lost US exclusivity in 2023 and the model holds it at about $2.9bn a year for
ever. A product whose loss of exclusivity is already behind it is treated as "in the
base": its reported revenue is taken to reflect the loss, its last reported growth rate
fades to nil over five or ten years, and its terminal value is a flat perpetuity. Is flat
right?

## The short answer

It depends on whether a competitor is on the market, and the model does not ask.

- **57 of the 75 products** past exclusivity have no competitor recorded. Their revenue
  three or more years on is flat: median 0.0% a year. The rule fits them.
- **18 have a generic or biosimilar on the market.** Their revenue three or more years on
  is still falling a median 19% a year, and the long filed histories say that goes on for
  a decade. The model fades their decline to nil in five years. The rule does not fit
  them.

So the fix is narrower than the one first proposed. A decline applied to every product
past exclusivity would be wrong for most of them, and they hold most of the value.

## The population

75 marketed products across 15 companies are "in the base". The date they are judged by
is one of two different things:

| What the date is | Products | Examples |
|---|---|---|
| A competitor is on the market: a generic launch on the FDA Paragraph IV list, or a filer naming generic or biosimilar entry | 18 | Symbicort, Crestor, Tecfidera, Stelara, Zytiga, Rituxan, Sprycel |
| Exclusivity has lapsed and no competitor is recorded: the 12-year biologic exclusivity has run out, or nothing live is listed in the Orange Book | 57 | Botox, Nplate, Vectibix, Aranesp, Orencia, Tysabri, the vaccines |

The second group is mostly biologics and vaccines nobody has copied.

## What the book's own filings show

Reported product revenue, FY2023 to FY2025, each year against the one before. 46 products
have two years or more on file; 88 changes in all.

| Group | Years past the date | Changes | Median a year | Revenue-weighted | Share falling |
|---|---|---|---|---|---|
| Competitor on the market | 0 to 2 | 9 | -36.7% | -30.3% | 78% |
| Competitor on the market | 3 or more | 10 (6 products) | -19.1% | -13.5% | 70% |
| No competitor recorded | 0 to 2 | 5 | -32.6% | -37.2% | 80% |
| No competitor recorded | 3 or more | 36 (18 products) | 0.0% | -3.2% | 50% |

The three no-competitor products that fall in their first two years are Brilinta,
Xarelto and Saxenda. Each is dated by a patent expiry, which a generic follows without
the date saying so, so they are in the wrong group (below).

By market, for the products whose filers print a regional split:

| Group | Market | Changes | Median a year |
|---|---|---|---|
| Competitor on the market | US | 14 (7 products) | -29.9% |
| Competitor on the market | Outside the US | 14 (7 products) | -22.4% |
| No competitor recorded | US | 33 (17 products) | -4.3% |
| No competitor recorded | Outside the US | 42 (21 products) | -1.2% |

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
five.

This agrees with what `data/erosion_defaults.csv` already records for a product whose
cliff is still ahead: US Part D spending four to eight years past a loss of exclusivity
falls a median 10.4% a year, and that file tested a floor and rejected it. The engine
already declines for ever after a cliff it forecasts. It stops only for a cliff that has
already happened.

## What the model does today

For the 18 with a competitor, the last reported change fades in a straight line to nil
over five years (ten where the product is growing), and the terminal value is flat. The
terminal value is 21% to 59% of each one's value.

| Product | Reported, FY2024 and FY2025 | Model | Terminal share of value |
|---|---|---|---|
| Symbicort | +22%, 0% | +0.2% fading to nil over 10 years | 51% |
| Crestor | +4%, +5% | +5.5% fading to nil over 10 years | 53% |
| Tecfidera | -4%, -30% | -30% fading to nil over 5 years | 32% |
| Stelara | -5%, -41% | -41% fading to nil over 5 years | 45% |
| Zytiga | -29%, -20% | -20% fading to nil over 5 years | 50% |
| Kuvan | -33%, -18% | -7% fading to nil over 5 years | 50% |

Symbicort and Crestor are the two that are not falling. Symbicort is 59% outside the US
and Crestor 96%, which is where an off-patent brand holds.

## What a narrow rule would move

Asset by asset, through the what-if and without saving anything: the long-run rate set
to a decline in place of nil, for the 18 with a competitor only.

| Company | At -6% a year | At -10% a year |
|---|---|---|
| Roche | -$1.00 a share (-3.3%) | -$1.28 (-4.3%) |
| AstraZeneca | -$4.07 (-2.3%) | -$5.23 (-3.0%) |
| BioMarin | -$0.44 (-2.1%) | -$0.56 (-2.6%) |
| Bayer | -$0.26 (-1.9%) | -$0.32 (-2.4%) |
| Biogen | -$2.69 (-1.1%) | -$3.45 (-1.4%) |
| Sanofi | -$0.73 (-1.0%) | -$0.93 (-1.3%) |
| Johnson & Johnson | -$1.42 (-0.6%) | -$1.80 (-0.8%) |
| BMS, Novartis, Novo Nordisk | under 0.3% each | under 0.3% each |

-6% is the median for years 7 to 10 after a cliff and -10% for years 4 to 6. Each product
loses 35% to 50% of its value. The figures are first-order: they leave out that a
smaller book leaves more room for the launches the model assumes, which would give some
of it back.

For scale only, the blanket rule first proposed, -3% a year on the 57 with no competitor:
AbbVie -4.0%, Biogen -3.1%, Amgen -2.3% ($10.80 a share), J&J -2.0%. The data does not
support it: those products are flat.

## What stands in the way

1. **The book cannot always tell which group a product is in.** Humira and Remicade
   sit in the no-competitor group because their date is the lapse of the 12-year
   exclusivity, while `data/erosion_defaults.csv` records both losing revenue to
   biosimilars. Brilinta, Xarelto and Saxenda are dated by a patent expiry. A rule keyed
   on competition needs a record of who has launched against what, which the Purple
   Book, the Paragraph IV list and the filers' own risk sections carry and the book
   reads only in part.
2. **Three years of product revenue.** The book's own product series run FY2023 to
   FY2025, so each product gives two changes. The long histories carry the weight for
   anything past year three, and they are on each filer's own basis, mostly worldwide.
3. **The US and the rest of the world differ.** The engine erodes the US share on a US
   date and holds the rest. A tail rule should do the same: decline the share where the
   competitor is, not the whole product.

## Options

1. **Leave it.** Defensible for the 57. Overstates the 18 by about a third to a half
   each, which is 1% to 3% of five companies' value.
2. **Continue the decline for products with a competitor on the market.** In place of
   fading to nil, run the product on the late rate its own erosion shape already carries
   (10% a year for a non-oral small molecule, 23% for an oral one, 25% for a biologic),
   on the share of revenue in the market where the competitor is. This uses rates already
   measured and on file, and makes a cliff behind a product behave like a cliff ahead of
   it. Needs the biosimilar launch record first.
3. **A measured tail of its own**: -11% a year in years 4 to 6, -6% in years 7 to 10, -2%
   after, from the long histories. Closer to the data than one rate, and a new shape to
   maintain.

Option 2 is the one I would build: it adds no new number, only stops the model treating
the same event two ways.
