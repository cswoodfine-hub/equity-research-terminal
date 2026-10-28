# Closing the gate surface — the plan, and the measurement it rests on

Written 2026-10-27, after Waves 1 and 2 loaded. Reproduce every number here with
`work/indication_backfill/nogate.py` and the steps-to-priced query in this file's
sibling scripts.

## The measurement that should drive this

133 catalysts priced, 323 unpriced. Asking of each unpriced catalyst *what stands
between it and a price* — rather than which bucket it falls in — gives this:

| what is missing | catalysts | example |
|---|---|---|
| a link **and** an asset model | 87 | Amvuttra, NOA LIFT |
| **an asset model, and nothing else** | **75** | Emrelis, Mivelsiran |
| a link and layer seeds | 46 | Rinvoq, Ubrelvy, Venclexta |
| a link, an asset price, and layer seeds | 37 | Vraylar, Elahere, Krystexxa |
| **layer seeds, and nothing else** | **30** | Rinvoq, Venclexta, Ubrelvy |
| an asset price and layer seeds | 17 | Imdelltra |
| a phase correction and an asset model | 11 | ABBV-400, BEAM-201 |
| nothing — the Wave 1/2 load just fixed these | 16 | Imfinzi, Cobenfy |

Counting a blocker wherever it appears: **an asset model is missing on 173**, a link on
**170**, layer seeds on **130**, an asset price on **54**.

## What this corrects

I told Charles that linking was the multiplier. That was half right and the useful half
is the other half. Linking appears on 170 catalysts, but **87 of them also have no asset
model**, so linking them alone prices nothing — it moves the blocker rather than
removing it. Only 46 are link-plus-layer-seeds, and none is link-alone.

The honest reading is that the surface has **two** large blockers of near-equal size,
and the cheap work is where exactly one of them applies.

## The order to work in

**105 catalysts are one step from a price.** They are the whole of the first phase.

### Phase 1a — 30 catalysts: layer seeds, nothing else (days)

Already linked, on a selling product that already carries a price and a discontinuation
rate, at a gateable phase. This is Wave 3 of exactly the work Waves 1 and 2 did, and it
is the highest yield per hour left on the board. Rinvoq, Venclexta and Ubrelvy lead it.

### Phase 1b — 75 catalysts: an asset model, nothing else (weeks)

Already linked, at a gateable phase, on an asset that carries no forecast at all. This
is a different template from a layer: the marketed seed the book has 353 examples of —
revenue anchor, growth to a published peak, cost stack, discount rate.

Split it, because the two halves cost very different amounts:

- **the marketed ones** — Emrelis, Lumakras, Datroway, Augtyro, Balversa, Litfulo,
  Veopoz, Sunosi, Olumiant, Piqray, Rhapsido, Vanrafia. A product with reported revenue
  and a published peak is a day's work each and is worth having for its own sake, not
  only for the gate.
- **the clinical-stage ones** — BEAM, CRSP, QURE, ALLO and the rest. A full bottom-up
  build on an asset with no revenue. Expensive, and the valuation is mostly judgement.
  Do these last or not at all.

### Phase 2 — 46 catalysts: link, then layer seeds

Linking first, because a layer seeded against a catalyst that names no disease prices
nothing. The 170 that need a link split by *why* the link is refused:

| reason | catalysts | the fix |
|---|---|---|
| the registry indexed no MeSH descriptor | 77 | curated condition → descriptor rows, as `asset_indication_additions.csv` already does |
| paediatric, and the asset carries no paediatric row | 51 | create the rows; `Pediatric Crohn's disease` is the precedent, 42 assets and 46 pairs |
| ambiguous: several of the asset's own indications | 39 | read each protocol and say which, citing it, as `asset_indication_exclusions.csv` does |
| would link on the next rebuild | 2 | nothing |

The paediatric block is the most tractable: one mechanism, 46 curated rows, and it stops
a readout in children being read as deciding the adults' approved indication, which is a
correctness fix as well as a coverage one.

### Phase 3 — 54 catalysts: an asset price, then layer seeds

The price is the cheap half and the dossier now hands agents the CMS per-beneficiary
figure directly, which is why Wave 2's prices were measured rather than placeheld.

### Not a phase — the 11 needing a phase correction

The rollover rule already fixes these at the next rebuild. Nothing to do.

## What to stop doing

**Do not research more indication layers across the whole book.** Waves 1 and 2
produced 37 new layers and 9 new priced gates, because only 33 of 154 open units carry a
dated catalyst. Phase 1a is 30 catalysts' worth of layer work that *does* convert, and
after that the yield falls off sharply. Phase 2 and 3 are the ones that reopen it.

## How to know it worked

Re-run `nogate.py` and compare `priced` and the steps-to-priced split. The second is the
one that matters: a phase that moves catalysts from "two things missing" to "one thing
missing" has done real work even if `priced` has not moved yet.
