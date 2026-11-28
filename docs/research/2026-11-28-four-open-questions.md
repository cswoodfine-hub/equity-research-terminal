# Four open questions from the stale-anchor pass, 2026-11-28

The re-strike of 2026-11-27 left four things to look at. Each was read against the filing
or the code on 2026-11-28, on the published book of that day with this branch's registers
applied. Fair values are the sum of the parts, mid, in dollars a share.

## What moved

| Company | Before | After | What moved it |
|---|---|---|---|
| Amgen | 510.76 | 447.10 | ceilings on Uplizna and Imdelltra; Krystexxa's fade 10 years to 5 |
| AbbVie | 224.70 | 212.80 | Elahere counted once (5.28); Botox's fade 10 years to 5 |
| Biogen | 256.44 | 249.25 | the anti-CD20 line's fade 10 years to 5 |
| Gilead | 147.29 | 144.94 | Livdelzi counted once |
| Merck | 190.35 | 189.60 | Bridion's erosion; Zerbaxa and Delstrigo fades |
| Bristol Myers | 103.30 | 103.42 | Zeposia's fade 5 years to 10 |
| Pfizer | 26.56 | 26.57 | Cresemba and Elrexfio fades, which net out |
| Axsome | 176.11 | 176.11 | nothing: see section 1 |
| Krystal | 125.29 | 125.29 | Vyjuvek's fade is 5 years in either band |
| Vertex | 514.05 | 491.87 | Journavx's ceiling |
| Roche | 29.03 | 29.75 | ten fades from 5 years to 10 (the US line, against a close of 60.64) |

Amgen is now below the 454.66 it stood at before the re-strike.

## 1. The growth convention behind Amgen and Axsome

**What was wrong.** A product anchored on reported revenue grows at a filed rate that
fades to nought over `growth_fade_years`. That length is not a judgement: it is the
median measured for one band of growth in `data/growth_analogues.csv` (0% to 10%, 10% to
25%, 25% to 50%, 50% to 100%). The re-strike moved 136 rates and left every fade where
it was. Fifteen rates had crossed a band edge, so each faded over a length measured on
different drugs.

Two had crossed 100% a year: Uplizna (+93% to +129%) and Imdelltra (+79% to +117%).
Above 100% the file holds 24 drugs, 13 of them censored, and no median can be read, so
no fade is measured there at all. On the 5 years carried over from the band below, the
second year still grows at 103%, and the two products reached $10,288mm and $8,066mm by
2030. That was the $51 a share.

**The book's own rule.** A launch rate is bounded by a published peak. Seven of the
ten products growing faster than 100% already carried `revenue_ceiling_musd`, and
three seed files (`gild_yeztugo.csv` among them) are refused outright until a published
peak can be found.

**What was done.**

- Uplizna: ceiling $3,000mm. TD Cowen analysts "see peak sales of $2 billion to $3
  billion for the Uplizna franchise" (BioSpace, 2025-09-10). The top of the range is a
  judgement: the estimate predates the myasthenia gravis approval of 2025-12-11, and
  the third quarter of 2026 alone annualises to $1,804mm.
- Imdelltra: ceiling $3,000mm. "GlobalData analysts forecast peak sales of more than
  $10bn and $3bn for Imfinzi and Imdelltra, respectively, within the 2026-2032 forecast
  period" (Clinical Trials Arena, 2026-09-09).
- Both are press-reported figures, not filings, and each row says so. Amgen's filings
  name no peak for either.
- Fifteen fades re-read for the band the rate now sits in. Eight lengths change; seven
  change their source text only.

**Axsome stands.** Auvelity's rate moved from +36.8% to +47.5%, inside one band, and
it already carries the company's own $8bn ceiling, which does not bind: the model peaks
at $1,730mm. The $44 a share is what a filed quarter does to a company with one growing
product. Nothing in the convention is broken there.

**Roche and Journavx, done the same day.**

- Roche: 20 products carried one fade text, written for the 10% to 25% band, whatever
  the rate. Ten grow at under 10% a year and now fade over the 10 years measured for
  that band, not 5 (Alecensa, Erivedge, Evrysdi, Gazyva, Hemlibra, Kadcyla, Ocrevus,
  Pulmozyme, Vabysmo). Three sit in a faster band whose length is also 5 and change
  their text only. Eight have a negative rate, for which no fade is measured: their
  rows now say they are a convention, and the length is unchanged.
- Journavx: ceiling $2,600mm. An analyst report from Visible Alpha, as Managed
  Healthcare Executive reported it on 2025-03-25, gives "peak global sales of $2.6
  billion by 2032" for acute pain, and $3.4 billion with the neuropathic indications,
  which the file's layers add for themselves. It is a consensus reported second hand
  from before the launch, and it had $105.8mm for 2025 against the $59.6mm Vertex
  reported. It binds in 2029; the guided rate of +233% reached $3,870mm in 2030
  without it.

**Left alone, and listed in `data/growth_convention_exceptions.txt`:**

- Farxiga, Lynparza, Bridion: negative rates under a fade text written for a growing
  product. The length is a convention either way.
- Tyvaso DPI: a fade text from another band, from before the re-strike.

## 2. Gilead's Yeztugo, and two double counts that were real

Yeztugo is not counted twice. Its line carries $150mm of 2025 revenue to the 2026 run
rate of $1,007mm and holds it. Its seed file has no growth rate on purpose, so the
engine refuses it and it adds nothing.

It would have been counted twice the day someone released that seed, because nothing
stopped a line and a product of the same name both being valued. Two already were:

| Company | Product | Base revenue | Counted as |
|---|---|---|---|
| AbbVie | Elahere | $690mm | a product model and a company line |
| Gilead | Livdelzi | $706mm | a product model and a company line |

The roll-up now leaves out a line whose name is a product it has valued, and names it
with the reason. The line rows are still in `data/company_lines/abbv.csv` and
`gild.csv`: the line loader corrects rows and does not remove them, so trimming the
files would not have reached the book.

## 3. Merck's Bridion

The nine-month rate was never the problem. The engine already held the loss of US
exclusivity on 2026-07-27, from Merck's 10-K. What it lacked was the right erosion: it
took the default for an injectable small molecule, 52% lost in year one, and kept a US
tail for ten years.

Merck's 10-Q for the third quarter (0000310158-26-000248) gives both figures:

- US sales of $108mm in the quarter against $392mm a year earlier, 72.4% lost in the
  first quarter of generics.
- "The Company expects the U.S. Bridion sales decline to continue and anticipates the
  discontinuation of U.S. sales of Bridion in 2027 as generic market supply stabilizes."

Year one now takes 72.4% and year two takes the rest of the US. Revenue after erosion:

| | 2026 | 2027 | 2028 | 2029 |
|---|---|---|---|---|
| Before | 1,528 | 698 | 441 | 294 |
| After | 1,528 | 463 | 127 | 112 |

The 2028 figure is sales outside the US only, 11% of the product, against a
third-quarter run rate of $144mm a year there. 2026 still reads high: the model has
$1,528mm and the filed nine months plus a fourth quarter at the third's pace is
$1,257mm, because the engine erodes nothing in the year of the cliff.

## 4. The lung cancer guard

The loosened guard is kept. The old one asked for osimertinib and pembrolizumab both in
the top three of 28 scored drugs. On the books of 2026-11-27 and 2026-11-28 the order
is osimertinib 80.8, nivolumab 75.1, alectinib 71.9, pembrolizumab 71.5, and the
scorecard's own rank range for each of the last two runs from 1 to 12. The test was
asserting an order the scorecard itself says it cannot tell apart.

The guard now holds osimertinib in the top three, pembrolizumab in the top five, and a
pembrolizumab rank range that reaches the top three. It still fails if pembrolizumab
falls out of the leading group, which is what it was written to catch.

## So it does not reopen

`backend/tests/test_growth_convention.py` reads the seed files and fails when a fade
names another band than its rate sits in, or a rate above 100% has no ceiling. A
re-strike that crosses a band edge now breaks the suite until the fade is re-read.
