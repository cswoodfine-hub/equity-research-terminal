# What is modelled, what is not, and what should be

Measured 2026-09-23 against the live book. Every figure here is computed, not estimated.

## The short answer

The book values 60 pipeline assets. It could value about 294 more. Of the 294, roughly
half are Phase 3 and half Phase 2, and on the modelled cohort's own lower quartile they
are worth on the order of $27bn, on its median about $126bn. Both numbers are upper
bounds for a reason given below.

## What is modelled

| | |
|---|---|
| Pipeline assets with assumptions | 60 |
| Of those, building cleanly | 59 |
| Their risked value | $166bn |
| Median asset | $868mm |
| Assets under $500mm | 25 of 59, and 2.6% of the value |

Nearly all of it is Phase 3: 54 assets carrying $158bn. There is exactly one modelled
Phase 2 asset, Vertex's povetacicept, and three at Phase 2/3 worth $75mm between them.

The depth is good where it exists. Every patient-built asset carries all six pool
factors, there is no placeholder curve anywhere, and not one assumption row is unsourced.
The weakness is not depth, it is that the four assumptions setting the revenue curve are
analogue or convention rather than measured, and that 65% of pipeline value still rests
on one shared obesity anchor.

## What is not modelled

Start from 1,392 unmarketed assets. Most of that number is noise: 420 big pharma rows
carry no indication at all, 274 are Phase 1 or Phase 1/2, and 312 belong to companies
outside the covered universe.

The population that matters is **315 big pharma assets at Phase 2 or later with no
assumptions**. Culling it:

| | |
|---|---|
| Same molecule already marketed | 13 |
| Duplicate of an asset already modelled | 2 |
| No usable name | 6 |
| **Genuine gaps** | **294** |

The cull matters. Inclisiran sodium is Leqvio, olaparib monotherapy is Lynparza,
nivolumab with hyaluronidase is Opdivo, and litifilimab appears twice under its code.
Counting those as missing value would be double counting.

**By company**: Novartis 45, GSK 34, Lilly 30, Sanofi 26, Pfizer 24, Roche 23, AbbVie 18,
Regeneron 15, Bristol 15, AstraZeneca 13, Merck 11, J&J 10, Novo 9, Vertex 7, Gilead 6,
Amgen 3, Bayer 3, Biogen 2.

The concentration is the finding. Novartis, GSK, Sanofi and Roche account for 128 of the
294 and have no modelled pipeline asset at all between them, so the gap is not spread
evenly: four companies are simply absent from the pipeline book.

**The largest by trial size**: GSK's mRNA seasonal flu vaccine at 54,000 enrolled,
Regeneron's REGN7508 at 15,364 across eight Phase 3 trials, AstraZeneca's AZD0780 at
15,100, GSK's RSVPreF3 at 10,212, Novo's ziltivekimab at 10,000, Merck's MK-1406 at
10,000.

## What it would take

Of the top 40 gaps, the blocker splits almost evenly:

- **21 have a pool already.** Their disease has a prevalence row somewhere in the book,
  so what they need is a price and an uptake curve. That is a day's work each.
- **19 have no prevalence for their disease anywhere.** Those need epidemiology first,
  and that is the thing one piece of work unlocks in bulk, because assets cluster on
  diseases.

Neither blocker is a data source problem. Both are seeding work.

## What should not be modelled, and why

- **Phase 1 and Phase 1/2, 274 assets.** At an all-indication likelihood of approval near
  8%, and with no pool, no price and usually no disease on file, the line cannot move a
  price and the effort is better spent on the Phase 3 gaps.
- **The 420 big pharma rows with no indication at all.** Nothing can be built on them
  until the registry gives them a disease. They are a data gap, not a modelling gap.
- **Assets outside the covered universe, 312.** Modelling them values companies the
  terminal does not cover.
- **The 21 modelled assets already worth under $0.10 per share of their owner.** They are
  0.35% of pipeline value between them. Adding more of that kind adds work, not value.

## The bound, and why it is an upper bound

On the modelled Phase 3 median of $927mm, the 136 Phase 3 gaps are about $126bn. On the
lower quartile of $196mm they are about $27bn.

**Both are upper bounds, and the reason is selection.** The modelled set is not a random
sample of the pipeline. It is the set somebody already judged worth modelling, so its
median asset is far better than a typical unmodelled one. The lower quartile is the more
honest anchor and even it is probably generous.

**Phase 2 cannot be bounded at all.** The modelled book holds one Phase 2 asset, so there
is no distribution to draw from. Any figure put on the 148 Phase 2 gaps would be
invented, which is why none appears here.

## The order to work in

1. **Epidemiology for the clustered diseases**, because it unblocks 19 of the top 40 at
   once and every one after them.
2. **The four absent companies**, Novartis, GSK, Sanofi and Roche, because a company with
   no pipeline line at all is understated in a way no per-asset work fixes.
3. **Phase 3 before Phase 2**, by an order of magnitude in expected value.
4. **Never the long tail.** Of the assets already modelled, 25 of 59 are worth less than
   $500mm and together they are 2.6% of the value. The book does not need more of them.
