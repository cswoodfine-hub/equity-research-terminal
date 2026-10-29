# Step 3b: the four erosion caveats, measured

Run 2026-10-29 on a copy of the published book. **Decided the same day: option B, the
averages**, now in `data/erosion_defaults.csv`. On the copy the book is 2,606,574mm
against 2,659,091mm on main's rows (-52,517mm, -2.0%). Each row's note carries the
median fit as its bear case: oral 0.80 / 0.53 / 0.22, non-oral 0.56 / 0.60 / 0.07.
Those are recorded in the notes, not yet wired as a scenario.

## What was built (all under `work/patents/tools/`)

| tool | what it reads | what it gives |
|---|---|---|
| `filer_us_lines.py` | SEC Financial Statement Data Sets, Q1 and Q2 of 2010 to 2026 (34 files, about 3gb, each read and deleted) | 1,843 filer, product and year US revenue figures |
| `filer_erosion.py` | the above, beside Part D | erosion on the filers' own US lines, and the gap to Part D on the same launches |
| `erosion_study.py --wide` | Part D 2013 to 2024, the Orange Book, FDA's authorised generics list | launches the Paragraph IV list missed, and a route for each |
| `ag_list.py` | FDA Listing of Authorized Generics (issue of 2026-10-05, 98 pages) | 512 brands with a reported authorised generic |
| `partb_biosimilar_study.py` | Medicare Physician & Other Practitioners by Geography and Service, 2013 to 2024 | biologic erosion after a biosimilar, on Part B allowed amounts |

## Caveats 1 and 2: gross of rebates, Medicare only

**Measured, and the oral curve stands.** 26 launches have a filer US line in the year
before and the year after. That US line is net of rebates and covers every channel. Of
the 26, 15 are oral.

| oral | year 1 | year 2 | year 3 |
|---|---|---|---|
| filer US line kept, median (n 15, 11, 6) | 0.238 | 0.126 | 0.052 |
| the PR's oral row | 0.23 | 0.115 | 0.057 |
| filer US over Part D, same launches, median | 1.05 | 0.82 | 0.72 |

In year one the filers' net, all-channel lines and Part D gross cost agree to 5%. The PR's
oral row is within 0.02 of the filer medians in every year measured.

Limits:
- The SEC data tags US revenue by product only from the 2018 filings on (fiscal 2016 in
  their comparatives). The large filers did not tag product by country before.
- Pfizer, AbbVie and BMS do not tag it at all. Their 10-K tables print it, and reading
  those for past years is the remaining work.

## Authorised generics

**FDA's list is too incomplete to split on.** It names 512 brands. It does not carry
Lipitor, Crestor, Zytiga, Januvia, Sprycel or Plavix, and FDA says it is built from
annual reports and should be verified independently. None of the 15 oral filer-line
launches is on it. On Part D, brands on the list keep 0.254 in year one (n 40) against
0.200 (n 88) for those not on it. So an authorised generic is worth about five points of
year one, with "not on the list" mixing in brands that did have one. No separate row is
proposed. Symbicort, whose own authorised generic kept AstraZeneca's US line at 1,193mm,
is handled by the rule that a recorded launch with no fall since stays in the base.

## Caveat 3: non-oral rows thin

**More launches, and a correction.**
- **A Part D entry detector** names the generic entry year from Part D itself: the first
  year unbranded generics pass 5% of the molecule's claims after under 2%, for a brand
  holding at least half its molecule. Against 60 Paragraph IV launches it names the same
  year 70% of the time and within one 88%. It takes the measurable launches from 104 to
  163.
- **A bug fixed in the study.** The route reader matched "pen" inside "suspension", so oral
  suspensions (Exjade, Megace ES, CellCept, Zyvox) counted as injectable. The PR's
  non-oral row was fitted with them in it. The app's own route code reads the Orange Book
  route field and was never affected.
- **Corrected non-oral sample:** 28 launches (topical 10, eye 9, inhaled 3, nasal 3,
  injectable 3). No route reaches 15, so it stays one row.

| non-oral, Part D cost kept | year 1 | year 2 | year 3 | year 4 | years 1 to 4 together |
|---|---|---|---|---|---|
| median (n 28 to 17) | 0.403 | 0.202 | 0.086 | 0.046 | 1.05 (median per launch) |
| the PR's non-oral row | 0.42 | 0.277 | 0.183 | 0.135 | 1.02 |

The PR's row is right on year one and on the total over four years, which is what moves
value. It is too gentle on years 2 to 4 for the median launch.

**Part B cannot measure a small-molecule injectable.** An ANDA generic bills on the
brand's own code, so Part B shows the molecule's spending, not the brand's. That is an
upper bound, not a curve. This corrects the plan, which named Velcade and Alimta as
measurable.

## Caveat 4: biologics

Three sources:
- **Part B, 8 biosimilar launches.** Biosimilars bill on their own Q5 codes, so the
  reference product's code is the brand alone: Neupogen 2015, Remicade 2017, Neulasta
  2018, Avastin, Herceptin and Epogen/Procrit 2019, Rituxan 2020, Lucentis 2023. The
  reference product kept a median 0.525 in year one, and later years fell a median 31% a
  year (n 30, Lucentis left out because Vabysmo and Eylea took its patients too).
- **Filer US lines.** The eight on file, plus Epogen from the SEC data (21% in year one).
  Year one fell a median 26.5% (n 9). Later years fell a median 25.2% a year (n 10: Humira,
  Neulasta, Remicade).
- **Part D, dates only.** Medicare Part D claims for Humira were about 660,000 in 2022 and
  650,000 in 2024 while AbbVie's US line collapsed through net price. Part D gross cost
  cannot see a biologic's fall.

Insulins (Humalog, Basaglar, Lantus) are left out. Their US lines fell through the 2023
list price cuts, not biosimilars.

The filer lines are net and all-channel, which is what the model values, so they set the
row. Part B, the Medicare physician-office channel, erodes faster (year one 0.475 against
0.265) and is the cross-check. **Proposed: biologic year one stays 0.25, the decay rises
from 0.20 to 0.25.**

## The decision this stops on: median or average

Every row so far is fitted to the median launch, the typical product. Value is linear in
revenue, so the input that leaves the book's total unbiased is the average kept across
launches. The spread is skewed (most brands collapse, a few hold), so the average sits
well above the median. Each launch is capped at 1.0, so a brand that rose cannot count as
gaining.

| kept after launch | year 1 | year 2 | year 3 | year 4 |
|---|---|---|---|---|
| oral median (n 134 to 99) | 0.214 | 0.083 | 0.046 | 0.037 |
| oral average | 0.299 | 0.192 | 0.138 | 0.115 |
| oral filer US average (n 15 to 5) | 0.349 | 0.263 | 0.130 | 0.038 |
| non-oral median (n 28 to 17) | 0.403 | 0.202 | 0.086 | 0.046 |
| non-oral average | 0.463 | 0.334 | 0.207 | 0.177 |

Hold-out test, fitting on 80% of launches and scoring the other 20% over 100 splits (median
absolute error in years one and three):
- **Oral:** the PR's row 0.082, the old literature row 0.157.
- **Non-oral:** the PR's row 0.182, the old literature row 0.170. The median-error test
  favours a steep curve on a skewed spread, which is why it cannot settle this choice.

**Value on one database:**

| curve set | oral | non-oral | biologic | total NPV | against main |
|---|---|---|---|---|---|
| main (literature) | 0.60 / 0.35 / 0.10 | same | 0.25 / 0.20 | 2,659bn | |
| PR as it stands | 0.77 / 0.50 / 0.26 | 0.58 / 0.34 / 0.26 | 0.25 / 0.20 | 2,565bn | -94bn (-3.5%) |
| **A: medians** | 0.77 / 0.50 / 0.26 | 0.58 / 0.34 / 0.26 | 0.25 / 0.25 | 2,535bn | -124bn (-4.7%) |
| **B: averages** | 0.71 / 0.31 / 0.23 | 0.52 / 0.34 / 0.10 | 0.25 / 0.25 | 2,607bn | -53bn (-2.0%) |

Rows read year-one drop / yearly decay / late decay from year four.

| product | main | PR | A | B |
|---|---|---|---|---|
| Ozempic | 200,947 | 194,267 | 194,267 | 207,933 |
| Wegovy | 195,653 | 187,733 | 187,733 | 203,740 |
| Mounjaro | 133,301 | 130,825 | 130,825 | 135,752 |
| Skyrizi | 78,867 | 78,867 | 75,931 | 75,931 |
| Rinvoq | 59,010 | 55,261 | 55,261 | 56,685 |
| Keytruda | 47,011 | 47,011 | 43,195 | 43,195 |
| Darzalex | 44,450 | 44,450 | 41,795 | 41,795 |
| Eliquis (BMS) | 27,251 | 19,192 | 19,192 | 22,211 |
| Kisqali | 19,983 | 17,461 | 17,461 | 18,425 |
| Farxiga | 8,647 | 5,490 | 5,490 | 6,654 |
| Entresto | 5,893 | 3,022 | 3,022 | 4,120 |
| Xarelto | 2,096 | 630 | 630 | 1,176 |

**Recommendation: B, the averages.** The book adds every product's value into company and
universe totals, and only the average leaves those totals unbiased. The median is the
better guess for a single product with nothing else known, and it stays on the page as
the bear case. Either way the PR's non-oral row note needs rewriting, since it was
measured with the route bug in it.
