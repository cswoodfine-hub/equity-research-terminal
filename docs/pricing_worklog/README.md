# Phase 3 pricing worklog

Working state of the pricing step for the assets the sort marked NEW
(`data/pipeline_sort.csv`), saved so a later session can continue it: the 75 at Phase 3,
all now seeded, held or refused, then the 121 at Phase 2 and 2/3, whose context files
`ctx.py` built from the book and the sort on 2026-09-25. Nothing here is read
by the app. A seed enters the book only after a second reader has reopened every source,
and only then is it assembled into `data/assumptions/`.

Progress per asset is in `status.md`.

## Method

0. `ctx.py` writes a context file per NEW asset at the phases asked (default Phase 2 and
   2/3): its indications and phases, its trials, the sort's evidence, and any row in the book
   whose name shares a word with it. The brief's "At Phase 2" section sets how the
   researcher treats an asset that has not reached Phase 3.
1. A researcher agent reads `BRIEF.md` and the asset's context file in `ctx/`, and writes
   `research/<TICKER>_<slug>.json`: price, gross to net, uptake, pool, each with a source.
2. A second agent, following the "second reader" section of the brief, reopens every source
   and writes `verified/<same file>` with a verdict per field.
3. `assemble.py verified/<file>.json` writes the seed into `data/assumptions/`, copying the
   company-level rows from the company's existing seed and any pool another asset already
   carries for the same disease. Then load the seeds, build the asset, and fix a price's
   currency where the company reports in euros, pounds or kroner (the seed shape test
   catches it).

## Running it again

The scripts and brief use fixed paths under `/tmp/claude-0/price`. Recreate that layout:

    mkdir -p /tmp/claude-0/price/out
    cp -r docs/pricing_worklog/{BRIEF.md,*_TASK.md,*.py,index.json,ctx,verified} /tmp/claude-0/price/
    cp docs/pricing_worklog/research/*.json /tmp/claude-0/price/out/

The book has to be the current one. `data/er_tool.db.gz` is a July copy that lacks the
assumptions table and most pipeline rows, so take the published refresh instead (the
`data-latest` release asset; `github.com/<repo>/releases/download/data-latest/er_tool.db.gz`
downloads from this container), then migrate, fold aliases and load the seeds:

    gunzip -c er_tool.db.gz > backend/er_tool.db
    cd backend && python3 -c "import db, curated_register, programme_alias, asset_merge, \
        indication_mapping, assumptions; db.init(); p=str(db.DB_PATH); curated_register.apply(p); \
        c=db.get_connection(); programme_alias.load_curated(c); c.commit(); c.close(); \
        asset_merge.merge(p); indication_mapping.build(p); c=db.get_connection(); \
        assumptions.load_seeds(c); c.commit()"
    cp er_tool.db /tmp/claude-0/price/book.db     # read-only copy for lookup.py

## The loop

1. Researcher: an agent told to follow `RESEARCH_TASK.md` with `{F}` set to the context
   file name. Second reader: `SECOND_READER_TASK.md`, same substitution.
2. `show.py verified/<file>.json` prints every field with its verdict in one line.
3. Before assembling, check what the engine needs that a reader may not have added: a line
   of cancer therapy on a pool whose prevalence is above its incidence needs
   `untreated_carryover_pct` 0; a royalty is struck on the owner's margin, because the
   engine applies `economics_share` to rNPV; an approved product states `pos` 1.0. Add
   such a field to the verified file with verdict "added at assembly".
4. `assemble.py verified/<file>.json`, then `fx_seed.py data/assumptions/<seed>.csv` for a
   company reporting in pounds, euros, kroner or francs, then `build.py TICKER:Name` from
   `backend/` to load and build. Raise the seed count in `test_wacc_live_rate.py`. When the
   company already has a seed, assembly copies its block ("Company-level rows copied from");
   run `comparator_block.py` only when it reports the company keys missing, or the rows double.

## Holds, refusals and cost blocks

An asset is refused when its owner's share of the economics cannot be sourced from a filing
(a royalty filed without a rate: linerixibat, iza-bren, and Regeneron's fianlimab,
mibavademab and REGN-2Cat, each footnoted "(f) Sanofi is entitled to receive royalties"; RGX-121,
where REGENXBIO's royalty from Nippon Shinyaku is only "double-digit"), or
when it has no standalone path. It is held when its revenue would mostly come out of the
owner's own marketed product (ibuzatrelvir and Paxlovid, PG4 and Prevnar 20, nucresiran and
Amvuttra, PI-2620 and Tauklarify).

A company with no cost block gets one only when one of its assets survives the second read.
`block.py TICKER` drafts the filed-line rows (FY2025 cost ratios, the aggregate tax rate over
years with positive pre-tax income, beta from stored weekly prices, TotalDebt and market
cap); check each against the filings, since a stale or mis-scaled TotalDebt is common (Incyte
carried a 2018 scale error for years) and a first-profit year's tax line is often a deferred
tax credit (argenx, Alnylam), which needs a labelled judgement. Add the ticker's window to
`interest_addback.WINDOWS`, load the rows, and take `charge_floor.measure(conn, TICKER)` as
the other-costs charge (held at nil where it rebuilds below nil and no amortisation is on
file). Exelixis, argenx and Neurocrine were built this way; the xl092, empasiprubart and
nbi_1065845 seeds show the rows and their wording. A loss-making company takes a comparator's
ratios, as Viking takes Lilly's: `comparator_block.py SEED TICKER COMPARATOR DEBT_WEIGHT
"DEBT_SOURCE" "WHY"` writes the comparator's modal cost rows, the company's own beta and the
stated debt weight into an assembled seed. Register the pair in
`interest_addback.COMPARATORS`. Structure (aleniglipron) borrows Lilly's; Dyne, Capricor, Solid and
Intellia borrow Alnylam's, the book's rare-disease genetic medicine company with its own filed
lines; Vor borrows argenx's, the gMG incumbent telitacicept is priced against; Revolution Medicines
borrows Exelixis's; Ionis, whose own filed lines are a loss, borrows Alnylam's; Axsome, likewise, borrows Neurocrine's; Arrowhead, whose FY2025 revenue is mostly licence
income, borrows Alnylam's, as do Sarepta, whose FY2025 lines are a loss, and Taysha. A share netted
over a borrowed margin (Vor's royalty, Intellia's, Capricor's revenue share) says so and is
recomputed when the company files a cost of sales.

## What works in this container

WebSearch works; WebFetch is blocked for almost every host, ClinicalTrials.gov included.
The Amass connector ran out of quota in the second session, so trial dates come from the
context files and the book's trials table. The first session's search allowance ran out at
200; the second session ran thirteen second readers at five to ten searches each.

## Found on the way, not fixed here

- `backend/capture_anchor.py` hard-codes Zepbound as asset 13. In the current published
  database asset 13 is Camzyos and Zepbound is 139, so the default measurement returns 0.36%
  instead of 4.39%; its test passes only because the fixture stores Zepbound as 13. Resolve
  the asset by ticker and brand.
- `data/assumptions/azn_baxfendy.csv` (baxdrostat) cites an oncology source for its
  discontinuation and Enhertu's curve for its ramp, and prices off Leqvio's Part D figure
  although Leqvio is a Part B product; Baxfendy now has a WAC of $900 per 30 tablets.
- The osivelotor seed indexes Oxbryta's launch a year late when it solves its peak (2021 is
  Oxbryta's year one on a 2020 origin); the etavopivat seed carries the corrected 0.0602.
- The book's Lantheus SG&A line is general and administrative only; it leaves out $179mm of
  sales and marketing, which a Lantheus cost block must add.
- The povetacicept and sefaxersen seeds price IgA nephropathy off a CMS figure of $399,499;
  Voyxact now has a published list of $390,000 (the zigakibart seed uses it).
- Catalysts attached to the wrong asset: Structure's ACCOMPLISH readouts (catalysts 1142, 1143)
  point to a GSK asset (2076), Lilly's Foundayo catalyst 811 is a Merck HPV trial, and the
  telitacicept gMG readout points to Xofluza. The catalyst-to-asset link needs a check.
- Vor carries $653.9mm of warrant liabilities (the RemeGen and PIPE warrants) against a
  $1.15bn market capitalisation. They are not debt, but a per-share value on basic shares
  outstanding overstates what each share gets once they are exercised.
- Sjogren's carryover: telitacicept, ianalumab and dazodalibep share one pool (ESSDAI 5 or
  more, eligible 0.2) and all run at the engine's default of 1.0. The telitacicept reader
  withdrew a 0.9458 that would have applied to that seed alone; any change belongs to all three.
- Duchenne: deramiocel, DYNE-251 and SGT-003 share one pool (11,952 and 367); the first two
  set no carryover. Their Sarepta discounts differ by design and by rounding: DYNE-251 takes
  FY2023's 0.1849 (the PMO-heavy year), deramiocel FY2025's 0.2125 before the prior-year
  adjustment, SGT-003 and SRP-9003 FY2025's 0.2140 with it.
  DYNE-251's 0.78% discontinuation lets its treated stock reach about 82% of the exon 51 pool
  by 2039, and the ~650 patients already on Exondys are not netted from it.
- Obudanersen prices off Spinraza's 2020 Part D spend per beneficiary, the only year with a
  count (17). Spinraza is billed mainly under Part B, which the book does not carry; a Part B
  anchor would put net near 1.9 times this seed's.
- Zoldonrasib keeps the engine's 12-year LOE default (2043): Revolution's 10-K gives only a
  2031 to 2045 range across the tri-complex portfolio, with no date for the molecule.
- AXS-14 prices off Savella's 2024 Part D figure, a brand-only price before generic milnacipran
  launched in March 2026. The house method implies about $298mm of Savella sales against about
  $103mm reported nationally, so the fibromyalgia peak may be high by up to 2.9 times.
- The book's indication "Amyloidosis" (id 64) holds both AL amyloidosis (daratumumab,
  belantamab, etentamig, JNJ-79635322) and ATTR (vutrisiran, nucresiran, nex-z). The nex-z seed
  gives it the ATTR-CM pool (Alexander: 55,372 and 25,605), so an AL seed on that indication
  would inherit the wrong pool. The indication needs splitting before one is written.
- `tests/test_refresh.py::test_refresh_populates_then_skips_within_ttl` fails in this
  container because a fetcher reaches the network and the run goes partial; it failed before
  any change in this session.
