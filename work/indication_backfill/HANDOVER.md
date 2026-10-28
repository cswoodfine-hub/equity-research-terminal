# Handover — pick up here

Written 2026-10-27 at the point a session rate limit stopped Phase 1b. Everything
below is on `main` and pushed. Read `PROGRESS.md` and `PLAN_GATE_SURFACE.md` in this
directory first; this file says only what to do next and what to be careful of.

## State, measured not remembered

| | |
|---|---|
| catalysts priced | **142** (from 133) |
| catalysts at `no_gate` | 314 |
| layers `indication_layer` prices | **60** (from 10) |
| assumption rows | 13,030 |
| tests | 4,262 passing, 118 skipped |
| draft files awaiting nothing | 55, all loaded |

Reproduce any of it:

```bash
cd "ER Tool"
python3 work/indication_backfill/nogate.py /tmp/now.json          # the gate surface
python3 work/indication_backfill/steps_to_priced.py /tmp/now.json  # what each one lacks
python3 work/indication_backfill/worklist.py                       # resumable unit state
```

## Phase 1b result, 2026-10-28

Rerun with five agents, the same grouping. 9 of the 25 marketed assets have a product
revenue figure in a filing; for the other 16 the filing names none, and they stay
unmodelled rather than estimated.

- Loaded: Lumakras, Exdensur, Rhapsido, Vanrafia, Qfitlia, Wayrilz.
- Committed, not loaded on the published copy (no Ayvakit asset there): Ayvakit. Should
  load against the book.
- Held: Datroway (growth runs uncapped at 167% a year to $2.2bn by 2030) and Sunosi (no
  Axsome company half). See `held/HELD.md`.
- Anchored but blocked the same way as Sunosi: Ionis Dawnzera ($95.55mm) and Tryngolza
  ($107.526mm). An Ionis and an Axsome company half, built from the 10-K, releases
  all three.
- Exclusivity to check against the substance patent: Lumakras 2040 vs 2038, Vanrafia 2043
  (method of use) vs 2034, Wayrilz 2041 vs 2033.

Measured on the published release copy, not the book (its IDs differ, so it reads
130/55 where the book reads 142/60): priced 130 to 130, layers 55 to 55.

**The plan was wrong about Phase 1b.** It called 75 catalysts "an asset model, nothing
else". For a marketed product that is not true: a readout on a selling product prices
through an indication layer, and a layer needs a price per patient and a
discontinuation rate. Steps to priced on the copy, before and after:

| | before | after |
|---|---|---|
| asset model | 74 | 65 |
| link + asset model | 86 | 83 |
| asset price/disc + layer seeds | 18 | 27 |
| link + asset price/disc + layer seeds | 32 | 35 |

12 catalysts went from two missing pieces of one kind to the Phase 3 shape. Real work,
not yet a priced gate. The clinical-stage half of the 65 is the expensive build the plan
already said to do last.

## The job that was running when this stopped (2026-10-27)

**Phase 1b: 25 marketed assets the book does not model.** Five agents were launched and
all five died on a session rate limit before writing a single file. Nothing of theirs is
on disk, so this starts clean.

Everything they needed is committed:

- `work/indication_backfill/BRIEF_ASSET_MODEL.md` — the standing brief
- `work/indication_backfill/asset_dossiers/*.md` — one per company, 15 of them
- `data/assumptions/lly_jaypirca.csv` — the exemplar to imitate

The grouping that was launched, five agents:

1. ABBV (2), AMGN (1), ARGX (1), ARWR (1)
2. AXSM (1), AZN (2), BMY (2)
3. GSK (2), IONS (2), JNJ (1)
4. NVS (4), LLY (1)
5. PFE (1), REGN (1), SNY (3)

Each agent prompt said: read the brief, read your dossiers, read the exemplar, never
fabricate, copy the company half verbatim from the sibling seed, the anchor is the work,
and watch the reporting currency — GBP for GSK, EUR for Sanofi, and check the rest
against the `companies` table rather than assuming.

## Then

**Phase 2 — 46 catalysts** needing a link and then layer seeds. The 170 link refusals
split: 77 the registry never indexed, 51 paediatric with no paediatric row on the asset,
39 ambiguous between the asset's own indications. The paediatric block is the most
tractable — 46 curated rows on one existing mechanism, and it is a correctness fix as
well as coverage.

**Phase 3 — 54 catalysts** needing an asset price and then layer seeds.

## Things that will bite you

**The verifier is a floor, not a verdict.** `verify_seeds.py` has eight rules and every
one was written because something got through it. Run it, then read a sample by hand.
The two things it still cannot catch are a real citation misread, and a number that is
sourced but that its own author does not believe.

**`integrate.py` appends; never make it copy.** It used `shutil.copy2` and destroyed 52
existing seed files, because a draft is named after its asset and lands on the seed the
book already had. The database survived because `load_seeds` is insert-only; the files
did not. Restored from git. Do not reintroduce a copy.

**Currency is read from the company, not the label.** The engine models a company in its
reporting currency and converts once at the end, so a dollar figure on a sterling filer
reads as pounds. Ten prices did this. There is now a verifier rule, but write them right.

**`held/` is not a reject pile.** Two pieces of sound research are there, each one
sourced number from loading. `held/HELD.md` says exactly what would release them.

**Do not research more layers across the whole book.** Waves 1 and 2 produced 37 layers
and 9 priced gates, because a layer only becomes a gate if its indication carries a
dated catalyst, and only 33 of 154 open units did. Work the steps-to-priced list, not
the unit list.

**Check a unit is not already answered before researching it.** Of 28 Phase 1a
candidates, 12 were already answered deliberately — `base_pool_overlap_pct` 1.0 or
`pos` 0, written by the research and correctly unpriced.

## Open, not started

- 51 assets carry no model at all (the clinical-stage half of the no-model block)
- 7 seed files name a brand the book has no asset for, so `load_seeds` skips every row
  in them silently: Be One, Symtuza Revenue Share, Abiomed, SURGICAL, Promacta Revolade,
  Tafinlar Mekinist, Pfizer Centre One
- 3 products carry no label because DailyMed has none for the plain name (Ventolin,
  Glucotrol, Prevnar); their stablemates' labels were correctly refused
- `llm.provider()` is None, so `extract_population` writes nulls rather than inventing
  them, and label population fields are empty on the twelve refetched labels
