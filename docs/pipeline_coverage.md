# Pipeline coverage and correctness

What the pipeline book gets wrong and what it does not hold at all, measured on
2026-09-23 by ten agents with every number independently re-derived. Ordered by value at
stake, not by effort. Nothing here is a forecast; every figure is something the database
or a filing already says.

Done items are struck through with the commit that closed them. Everything else is open.

## The state, in four numbers

| | |
|---|---|
| Unmarketed assets modelled at all | 60 of 1,392 (4.3%) |
| Big pharma Phase 2, 2/3 and 3 modelled | 55 of 370 (14.9%) |
| Named pipeline share of enterprise value | 3.2% |
| Pipeline value resting on one shared anchor | 65.5% |

The depth where an asset is modelled is good: 54 of 59 run a full patient funnel, all 65
indication blocks carry all six pool factors, there is not one placeholder curve and not
one unsourced row. The problem is breadth, and the softness of the four assumptions that
actually set the revenue curve.

## Corrections, ranked by value at stake

**Closed**

1. ~~The Zepbound anchor derived once rather than restated seven times, the 4.5% rounding
   corrected to its own 4.3882%, and consistent grading.~~ 98e6067.
2. ~~Cagrilintide priced in USD inside a DKK book, carried at a sixth of itself.~~
   98e6067. Novo +$7.12 a share.
3. ~~The eight obesity lines each given the whole pool.~~ 0d9c4d4. One pool, counted
   once, stoppers returned to it, two denominators never mixed. VKTX -19.3%, NVO -4.0%,
   AZN -2.1%, LLY -1.9%, AMGN -1.4%, MRK -0.2%. It also found Merck and AstraZeneca
   competing on a breast cancer pool.
4. ~~The price path and the ex-US line.~~ a1ad602 and 473c005. They nearly cancel and
   were applied together. Two defects cleared on the way: the ex-US multiple was in the
   crowding key, so storing one would have dissolved item 3; and the price decline
   compounded past the cliff where the erosion curve already carries price.
5. ~~Lilly's 10% was a contribution, not a rate.~~ 473c005. Its table's three columns sum
   exactly to their printed totals, so the per-unit change is 1.43/1.53 - 1 = -6.54%. And
   a null price was never an abstention: the engine reads it as a flat real price for
   nineteen years. All four blanks now carry 0.05 at grade analogue.
6. ~~Indication tagging, and pooling on the asset-indication pair.~~ 7e062c4. No
   automatic rule shipped: four candidate signals measured at 5.7% to 42% precision over
   all 2,520 pairs, so the seven verified co-morbidities are recorded in
   `asset_indication_overrides` instead. Pooling now keys on the population through
   `indication_groups`, so Viking's Weight Loss asset competes with the seven on Obesity.
   The book did not move, which is correct: no mis-tagged row sat on a modelled asset.

**Open, largest first**

7. **The eight obesity lines still claim an implausible share of the population.** Even
   with one pool counted once, the model's peak has a large share of US obese adults on a
   branded incretin. No asset takes share from another on any clinical ground; the split
   is each analyst's multiple. The plan for fixing that is in
   `docs/pool_share_by_evidence.md`, and it opens with the finding that the evidence does
   not exist yet.
8. **The CagriSema overlap, opened by the currency fix and unquantified.** Cagrilintide is
   the largest line in Novo's book, above Ozempic and Wegovy, and its trials are CagriSema
   studies, which contain semaglutide. The book counts both at full value.
9. **The marketed incumbents are not deducted from the pool, which is 6.0% too large.**
   6.43mm US adults are already on branded obesity therapy, measured from filed regional
   splits, against a pool stated as 107.6mm untreated. Wegovy, Ozempic and Mounjaro run in
   marketed mode off reported revenue and never touch the pool identity. Now unblocked:
   the tagging fix landed, though Wegovy and Zepbound still carry no obesity indication
   row of their own, which is the remaining piece.
10. **United Therapeutics' "Oral Treprostinil" is nebulised Tyvaso's fibrosis filing.**
    $3,093mm, $64.58 a share, 24.2% of the company, with inhaled-treprostinil trials
    attached.
11. **Twenty-four of sixty assets carry no `economics_share` and are valued at 100%.**
    They hold $125,242.7mm, 72.9% of the pipeline book. `asset_economics` is empty for all
    sixty.
12. **Four assets are priced on an indication with no `asset_indications` row**:
    Savolitinib, VX-147, Povetacicept and CD388.

## Coverage, and why the obvious way to close it makes the book worse

317 of 372 late-stage big pharma assets carry no assumption row. Sixteen of those are not
gaps: five are already-marketed products, two are lines the book values elsewhere, and
twelve are duplicate rows that fold into nine. `asset_merge` finds none of them, because
it matches on names and these differ by development code.

That leaves about 301 real gaps, and **29 of them are metabolic assets that would be
valued off the same Zepbound anchor that already carries 65.5% of pipeline value**.
Closing the gap in the obvious order concentrates the book further rather than
diversifying it, so items 3 to 7 come first.

Seven companies hold 161 late-stage assets and no pipeline model at all: Bayer, Gilead,
GSK, Novartis, Regeneron, Roche and Sanofi. Bayer and Roche have no valuation of any kind,
because neither files with the SEC and the book has no share count for them.

## The order to work in

Six of the twelve are closed. The remaining order, with the reason for each position.

1. **Item 8, the CagriSema overlap.** The largest single open number, and the currency
   fix made it visible rather than creating it.
2. **Item 9, deducting the incumbents.** Now unblocked by the tagging fix. What remains
   is that Wegovy and Zepbound carry no obesity indication row of their own, so the link
   from a marketed brand to the pool it occupies cannot yet be made automatically.
3. **Items 10, 11 and 12**, which are cheap, self-contained and each wrong in a way that
   is not arguable.
4. **Item 7, clinical share**, only as far as `docs/pool_share_by_evidence.md` says it
   can go: fix the data the registry already publishes and build the comparability gate.
   The score itself waits for readouts that have not happened.
5. **Only then add assets**, starting outside metabolic, and run a duplicate pass first.

## What the price and uptake pass added, 24 September 2026

Eleven seeds written, ten of which build, for $13,963mm of risk-adjusted value the book
was not carrying. SNY +5,660, AZN +3,230, GSK +2,692, BMY +882, NVS +766, REGN +733.

Four assets were researched to the same depth and deliberately not seeded, which is the
more important half of the result. Ziltivekimab: ZEUS missed at a hazard ratio of 0.99
(0.88 to 1.11). Pelacarsen: Lp(a)HORIZON missed in 8,323 patients and Novartis has stated
no filing intent, so it carries a price and no uptake curve and the engine refuses to
build it. Astegolimab: ARNASA missed and Roche has stated no submission, so a launch curve
has nothing to be measured from. Giredestrant: no pool, because SEER publishes no free
complete prevalence by hormone-receptor status.

Three things the pass found that were larger than the fourteen assets it was about.

**The price basis was right and is now measured rather than asserted.** Almost every
pipeline asset is priced off a comparator's CMS spending per Medicare beneficiary, cut by
a gross-to-net share, and both halves of that are wrong in opposite directions: CMS
spending is gross of rebates, while spending per beneficiary is not a year of therapy,
because the denominator is everyone who filled the drug at any point in the year. Coverage
measured against each drug's own schedule runs from 48% of a year on Verzenio and Xtandi
to 124% on Leqvio. Against CMS's own Maximum Fair Prices for the nine cycle-one IRA drugs
that carry a demand row, the convention lands at a median 96% of a real negotiated net
annual price, so the two errors cancel (`backend/gross_to_net.py`). The spread is 65% on
Imbruvica to 167% on Januvia, so it is sound for a book and loose for one asset. Three
verifiers independently recommended annualising every price, which would have put the book
50% above CMS's own negotiated prices. It was not done.

**A drug CMS names only by its container had no demand series at all.** There is no
"Repatha" row in the CMS Part D file, only Sureclick, Syringe and Pushtronex, so the whole
molecule was dropped for Repatha, Dupixent, Praluent, Kesimpta and Taltz and half of it
for Fasenra and Adbry. Repatha has 459,932 Medicare beneficiaries and $1,962mm of 2024
Part D spending and carried nothing. 83 rows recovered, 15 assets that had no series now
have one, 97 existing 2024 rows corrected, and underneath it a silent defect where any
asset CMS listed twice carried whichever row the payload happened to end with: Cellcept
Part B held 24 beneficiaries against the molecule's 42,875.

**An asset drew its success rate from the wrong disease.** The therapeutic area that picks
the precedent transition rate was resolved by classifying every trial an asset had ever
run as one blob, so tozorakimab was an infectious disease on its SARS-CoV-2 trials while
the line in the book is COPD, and REGN7508 was oncology on a cancer-associated thrombosis
trial while the line is atrial fibrillation. Nine of 393 modelled assets change area and
every one is a correction.

**Open, added to the list above**

13. **Roche and Bayer can hold no valuation at all, and Roche has 25 late-stage assets.**
    Neither files with the SEC, so EDGAR has no financials for either: Roche has 101 assets,
    3,915 price rows and zero financial rows, so a beta is derivable and a cost structure
    is not. Trontinemab is the concrete loss. Its research survived verification in full,
    with a price corroborated within 2.7% by an announced list and an uptake anchor
    measured in Leqembi and Kisunla patient-years rather than beneficiary counts, and it
    cannot be seeded because there is no company block to put it on. This is the single
    largest unvaluable block in the book and it is one fetcher, not one asset.

    **Bayer's half is now a route rather than a gap, pending its first live run.** Bayer
    files XBRL, just not with the SEC: its annual report is filed in the European Single
    Electronic Format, tagged in the same `ifrs-full` taxonomy Novo, GSK and Sanofi use in
    their 20-F. The equivalent of EDGAR's company-facts file is filings.xbrl.org, which
    serves every ESEF report as xBRL-JSON and is keyed by LEI.
    `fetchers/financials_esef.py` reads it and hands the facts to the same parser EDGAR
    data goes through (now `companyfacts.py`). Bayer's LEI, 549300J4U55H3WP1XT59, is on
    the seed and check-digit validated. Built in a session whose network reached neither
    filings.xbrl.org nor bayer.com, so the converter is tested on genuine Arelle output
    for a synthetic filer, not on Bayer's own report. Three things to confirm on the
    first refresh that reaches the index: that it holds Bayer at all (its German coverage
    could not be checked), that `Revenues`, `NetIncomeLoss` and `CashAndEquivalents`
    resolve, and that `TotalDebt` does, since Bayer may tag its financial liabilities
    under a concept of its own rather than `ifrs-full:Borrowings`. A miss is reported
    either way, never filled. Depth is FY2019 to FY2025 and annual only, because ESEF
    covers annual reports alone.

    The ADR ratio under it was wrong too. Four BAYRY make one ordinary share, not one
    (migration 067). It cost nothing while Bayer had no share count, and would have put
    every per-share figure at four times the price once it did.

    **Financials are necessary for a Bayer valuation, not sufficient.** Run on these rows,
    `fair_value.company` still refuses, because the sum of the parts is empty. Bayer has
    56 marketed assets with no product revenue on file, no company lines for Crop Science
    or Consumer Health, and not one modelled asset. Product sales sit in the management
    report, which ESEF does not tag, so they are curated rows in
    `data/product_revenue.csv` read from the annual report, the same route as any other
    untagged product table. After that come the three unmodelled late-stage assets, which
    are small. BAY3723113 is aficamten in a 36-patient Japanese Phase 3 (Bayer licensed
    Japan). BAY 3670549 is a Phase 2 in atrial fibrillation, primary completion 2030.
    AB-1005 is AskBio's GDNF gene therapy in an 8-patient Japanese Phase 2 in Parkinson's,
    not yet recruiting.

    Roche's half was closed separately and by a different route. Switzerland is outside
    the EU, so ESEF does not apply, but Roche publishes its own workbook (see "Roche
    unblocked" below).
14. **Amlitelimab and tozorakimab carry a 0.94 probability on one positive readout.**
    `pos_granular` places an asset at its own gate, and a single positive Phase 3 filing
    moves it to the NDA/BLA transition. Amlitelimab's Phase 3 programme has five trials
    reading out into 2026, so one positive result is not the whole programme at the filing
    gate. The behaviour is consistent across the book and is not obviously right.
15. **`data/assumptions/vk2735.csv` has a 14-column row** where every other row has 12,
    on `economics_share`. Pre-existing and tolerated by the loader, which reads by index.
16. **The Part D gross-to-net convention is loose per asset by design.** 65% to 167% of a
    negotiated price across nine drugs. An asset whose comparator has a published annual
    list price should use it: admilparant, AZD0780 and efimosfermin now do, and the rest
    of the book does not.

**The gap that remains**

208 late-stage assets at companies holding five or more still carry nothing, of 397. The
five largest gaps are NVS 43, GSK 32, ROG 25, LLY 20 and SNY 18. ROG's 25 are blocked on
item 13 rather than on research. Bayer's three were blocked the same way and now wait on
its first ESEF refresh and its product revenue.

## Roche unblocked, and half the late-stage gap is not a new medicine, 24 September 2026

**Item 13 is closed.** Roche publishes its own group financial data as a workbook for
investors to model from, free and without a login, at the Finance Information Tool. It
holds the IFRS income statement, the consolidated balance sheet and per-product sales split
by region, and `backend/roche.py` with `backend/fetchers/financials_ir.py` now reads it.
Roche has 34 group metrics, 23 product revenue rows and 92 regional rows where it had none.

**22 marketed Roche lines now build, worth CHF 101,022mm risk-adjusted, $19.11 an ADR
against an RHHBY close of $55.06.** That is 35% of the price, the right shape for a company
whose diagnostics division and pipeline are still unmodelled. The pipeline was always the
smaller half of the Roche loss: 46 marketed assets earning CHF 47.7bn a year were carried at
nil.

The parser refuses rather than guesses. Every subtotal in the sheet is the sum of the lines
above it and the 26 named products sum to the Pharmaceuticals Division's 47,669 exactly, so
nothing is written for a statement that does not tie. Three traps in the sheet each have a
test: a label is not unique, so reading the wrong "Amortisation of intangible assets" takes
core R&D for the IFRS charge; a year appears twice in the header, once over francs and once
over growth percentages, so the last match reads group sales as 1; and the product sheet
repeats all 26 products below with quarterly figures, so reading both blocks double counted
the division by 25%.

**A defect only Roche could have found.** `forecast_view._diluted_shares` falls back to group
net income over earnings per share where no share count is stored, and Roche's per-share
figure is struck on earnings attributable to shareholders, so the fallback gave 860.3mm
against the true 803.0mm. Roche is the only filer in this universe with a material minority
interest. Writing the count under the name the book already reads moves the per-ADR figure
from $17.84 to $19.11.

**Bayer is now the whole of item 13.** It reports under EU rules whose electronic format is
inline XBRL rather than a workbook, which is a different parser. The equivalent file is
filings.xbrl.org's xBRL-JSON, and the route to it is described under item 13. It has 3
unmodelled late-stage assets, so the cost of leaving its pipeline is small; its marketed
book is the larger half, as it was for Roche.

**HALF THE LATE-STAGE GAP IS NOT A NEW MEDICINE.** This is the finding that matters most for
the remaining work, and it inverts the obvious plan. Of the first 87 of 353 non-Roche assets
classified: 42 NEW, 29 DUPLICATE, 6 LINE_EXTENSION, 8 DEAD, 2 REGIMEN. Researching a price
and an uptake curve for all 353 would have valued Leqvio, Arexvy, Shingrix, Gardasil 9,
Cabometyx, Cobenfy, Nurtec and Vyvgart Hytrulo a second time, under a development code or a
formulation name, and added revenue the book already holds. Of the 42 genuinely new, 6 are
material.

`backend/stale_pipeline.py` makes the check standing rather than manual. An asset stays at
`is_marketed = 0` until `approvals_openfda` matches it, and that fetcher matches on the
company's own sponsor name, so an approval under a licensee, an acquired subsidiary or a
generic applicant is invisible. Of the 133 unmodelled late-stage assets whose name is shaped
like an ingredient, 15 already carry an FDA approval: mirvetuximab twice under ImmunoGen,
cabozantinib under Exelixis, encorafenib under Array, avelumab under EMD Serono, ravulizumab
under Alexion, ocrelizumab under Genentech, ritlecitinib under Pfizer's own name, linerixibat
under Intercept, and eltrombopag and decitabine as generics. It reports and changes nothing,
because whose value it is cannot be read off an approval record: Zydus' eltrombopag is a loss
of exclusivity for Novartis' Promacta, not an approval Novartis won.

**Three disease pools consolidated, one deliberately not.** Obesity, the largest cluster in
the book, had no row in `data/epidemiology.csv`: seven assets each carried 107,592,242 and all
seven agreed, so there was copying to stop rather than drift to repair. Non-small-cell lung
carcinoma was the same across eight assets and IgA nephropathy across one. Breast Neoplasms
is left alone because four assets use it for the metastatic HR-positive pool while an
adjuvant asset needs the early-stage one, so a single row would hand the wrong pool to
whichever did not write its own. Six aliases were also added, because the lookup was an exact
string match and the registry names one disease several ways: 18 multiple sclerosis assets
sat on "Relapsing-Remitting" and "Chronic Progressive" while the file filled only "Multiple
Sclerosis".

**Open, from the Roche build**

17. **Roche's other-costs charge was solved to operating profit, not by the house free-cash
    rebuild.** `charge_floor.measure` solves every other company's charge so its book
    reproduces free cash flow restated before interest, at replacement capex and without
    working-capital build, floored at minus the intangible amortisation inside its cost
    lines. Worked by hand on Roche's own workbook figures, that rebuild falls well below the
    floor and binds at it: minus CHF 665mm of amortisation in cost of sales and R&D, -1.08%
    of sales. Roche reports CHF 1,840mm of other revenue beside sales, so under the treatment
    Sanofi and Novartis get its ratios would be scaled onto total revenue, and the house
    margin comes to 29.8% against the 30.0% the operating-profit plug gives. Under 1% of
    value, so it was recorded rather than rebuilt. Doing it properly needs a window in
    `interest_addback.WINDOWS`, a row in `data/other_revenues.csv`, a row in
    `data/amortisation_in_cost_lines.csv`, and the cash-flow lines the modules read written
    from the workbook's own free-cash bridge. The workbook carries one year only.
18. **Eight companies whose late-stage assets are now being researched have no cost block
    at all:** argenx, Moderna, Alnylam, Intellia, Exelixis, Revolution Medicines, Neurocrine
    and Structure. Four are profitable on their own filed lines and can carry their own
    ratios with a house charge rebuild; Moderna, Intellia, Revolution and Structure are loss
    making or pre-revenue and take a scaled comparator's ratios with a comparator charge, as
    Viking does from Lilly. Each block is built only where one of its assets survives
    verification.

## The late-stage gap sorted, 24 September 2026

Every unmodelled late-stage row is now sorted by what it is, in `data/pipeline_sort.csv`,
before any of it is priced. Nothing was priced. The population is defined in
`backend/pipeline_sort.py`: not marketed, no assumptions, an indication at Phase 2, 2/3 or
3, Roche excluded. That is 345 rows on the 2026-09-24 database. The earlier count of 353
was taken on a database that was never published and cannot be reproduced; the
classification of its first 87 was never committed, so the sort was redone from nothing.

| Class | Rows | |
|---|---|---|
| NEW | 196 | a medicine the book does not hold in any form |
| DUPLICATE | 67 | a code, misspelling or second row for something the book carries |
| LINE_EXTENSION | 41 | a new indication, population, market or formulation of a marketed molecule |
| DEAD | 19 | discontinued, returned, or failed with no path, each on a company statement or filing |
| NOT_A_PROGRAMME | 16 | a comparator, background therapy, supportive care or follow-up study |
| REGIMEN | 6 | a combination of molecules each valued elsewhere |

149 of the 345, 43%, are not new medicines. The earlier sample put it at half. Of the
196 that are, 75 lead in Phase 3 and 115 in Phase 2. By company the new ones are
concentrated where the gap always was: Lilly 20, Novartis 20, GSK 13, Pfizer 12, AbbVie 10,
Sanofi 10. The largest Phase 3 new medicines by enrolment are zilebesiran (11,000),
ziltivekimab (10,000, though Novo halted two of its trials after ZEUS), PG4 (4,670),
mRNA-1018 (4,050), balcinrenone with dapagliflozin (3,850) and aleniglipron (3,600).

**How it was sorted.** A dossier per row from the database: names and aliases,
indications, trials with status, dates and enrolment, other rows sharing the molecule, and
matching EMA authorisations. Eight classifiers worked from the dossiers, Amass and web
search to one set of rules, and every row carries a one-sentence sourced reason. On review:
every approval date a classifier recalled rather than looked up, 24 of them, was checked
against the FDA's letter or the company's announcement, and all were right except Kymriah's
EMA date, which now takes the register's 2018-08-23. Every DEAD call rests on a company
statement, a filing or a registry termination, except gandotinib, which has had no trial
since 2015 and is marked low confidence because no discontinuation was ever announced.
Three consistency rules were applied across batches the classifiers had read differently:
an out-licensed molecule with economics retained is NEW, since `economics_share` can price
a royalty (naporafenib, linerixibat, zilurgisertib); a marketed fixed-dose product is a
DUPLICATE of that product, not a regimen of its parts (Trikafta, Alyftrek); and a new
indication or population is a LINE_EXTENSION, not a DUPLICATE, which moved 23 rows,
Vyvgart Hytrulo in Graves' disease and myositis and Datroway in new lung and breast
settings among them.

13 rows are low confidence and want a second reader: four development codes with no
published identity (LY3457263, LY4005130, PF-08049820, YMI024) and two J&J codes with
no named target, sasanlimab (positive Phase 3, EU filing withdrawn, no discontinuation on
record), linerixibat (approved, licensed to Alfasigma), cetrelimab, miransertib,
ALN-AGT01, the PF-07104091 dose-expansion row, and gandotinib.

**What the sort found that is wrong in the book itself.** These are not pipeline questions
and nothing here was changed; each is a follow-up.

- Approved products the book does not carry as marketed: Aucatzyl (Autolus), Zevaskyn
  (Abeona), Elahere (AbbVie), Enerzair and Atectura Breezhaler (Novartis, EU), Mosquirix
  (GSK), and tolebrutinib, authorised in the EU as Cenrifki on 2026-06-19. Emblaveo is
  carried under AbbVie while Pfizer holds its EU authorisation.
- Beqvez is still a marketed Pfizer product in the book. Pfizer discontinued it in all
  markets in February 2025.
- Tavneos (avacopan) is not in Amgen's marketed book, and the FDA proposed withdrawing its
  approval on 2026-04-27.
- mRNA-4157 is Merck's intismeran autogene, which the book models under Merck. Moderna and
  Merck share its cost and profit equally, so Moderna's half is unvalued unless the Merck
  model carries it.
- The registry lags the companies. REGN7999, JNJ-81201887 and nivisnebart are discontinued
  in filings or company statements while a trial still reads active or recruiting, so a
  trial status alone would have called all three alive.
- Rows outside the population that duplicate ones inside it: a separate unmodelled Lilly
  "Tersolisib" row, an "Olomorasib test" row, a second pz-cel row, and Roche's "Autogene
  Cevumeran" row with no indications.

**Sources ran short.** The Amass account reached its monthly usage limit on the first few
calls and resets on 2026-10-24, and the web search budget ran out for three of the eight
classifiers, which is why the review above checked by hand what they recalled. With
clinicaltrials.gov, api.fda.gov and ema.europa.eu reachable from the container, each of
those checks would read the registry or the regulator directly.

**Next.** Price only NEW, and begin with the Phase 3 rows. `pipeline_sort.unsorted()` lists
any row a later trials refresh adds that the file does not cover.
