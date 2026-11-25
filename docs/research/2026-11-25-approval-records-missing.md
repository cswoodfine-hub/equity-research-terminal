# Approval records missing: the 14 fixed and a plan for the 44

Date: 2026-11-25. Book: the published database, refreshed 2026-11-25 06:42 UTC.

## What the warning means

The Portfolio tab prints "Approval record missing for X" when an asset is marked
marketed and no row in `approvals` points at it (`main.company_approvals`,
`approval_status = "missing_record"`). 59 of the book's 1,419 products were in that
state, in 17 of 75 companies.

They are two populations, told apart by the note each asset carries:

- 14 were created by the FDA registers. Each holds an FDA application number, so an
  approval exists and the book failed to attach it.
- 45 were created from a revenue line in a filing or an annual report. Most are not one
  US product under that name.

## The 14: every date is in the Purple Book

Source for every row below: FDA Purple Book, October 2026 release
(https://www.accessdata.fda.gov/drugsatfda_docs/PurpleBook/2026/purplebook-search-October-data-download.csv),
columns "Approval Date", "Marketing Status" and "Licensure".

| Ticker | Product | Application | Approval date | Listed as | Licence |
|---|---|---|---|---|---|
| LLY | Humalog | BLA020563 | 1996-06-14 | Rx | Licensed |
| MRK | Antivenin (Latrodectus mactans) | BLA101062 | 1936-02-13 | Rx | Licensed |
| MRK | Normal Horse Serum | BLA101084 | 1959-01-02 | Rx | Licensed |
| MRK | PegIntron/ Rebetol Combo Pack | BLA125196 | 2008-06-13 | Disc | Voluntarily revoked |
| PFE | Antivenin (Crotalidae) Polyvalent | BLA101098 | 1954-02-08 | Disc | Voluntarily revoked |
| PFE | Antivenin (Micrurus fulvius) | BLA101099 | 1967-08-28 | Rx | Licensed |
| SNY | Tetanus Toxoid Adsorbed | BLA103913 | 1999-12-09 | Rx | Voluntarily revoked |
| SNY | Diphtheria & Tetanus Toxoids Adsorbed | BLA103919 | 1999-12-09 | Rx | Voluntarily revoked |
| SNY | Tetanus and Diphtheria Toxoids Adsorbed | BLA103921 | 1999-12-09 | Rx | Voluntarily revoked |
| SNY | Menomune-A | BLA103924 | 1999-12-09 | Disc | Voluntarily revoked |
| SNY | Menomune-A/C | BLA103925 | 1999-12-09 | Disc | Voluntarily revoked |
| SNY | Botulism Antitoxin Bivalent (Equine) Types A and B | BLA103937 | 2000-02-24 | Rx | Voluntarily revoked |
| SNY | Diphtheria & Tetanus Toxoids Adsorbed | BLA103944 | 2000-02-24 | Disc | Voluntarily revoked |
| SNY | Influenza Virus Vaccine, H5N1 | BLA125244 | 2007-04-17 | Disc | Licensed |

### Why the book missed them

`attach_licensures` matched a marketed asset to the Purple Book on its brand alone.
Three things defeated that, and the application number each asset already carries
settles all three:

- Ten have no proprietary name. The file prints "N/A" or nothing, `parse_licensures`
  dropped any row without a brand, and the gap query skipped any asset without one.
- Three share a brand key. `_brand_key` cuts a name at the first slash, so Menomune-A/C
  became MENOMUNE-A and "PegIntron/ Rebetol Combo Pack" became PEGINTRON, each colliding
  with another licence. All three were refused as ambiguous.
- Humalog is printed under two BLAs: 020563, and 205747 for the U-200 pen. The brand was
  refused as ambiguous. openFDA's row for BLA020563 sits on the Humalog Kwikpen asset.

### What changed

`backend/fetchers/exclusivity_purplebook.py`:

- `parse_licensures` keeps a licence with no proprietary name and reduces each licence's
  status to the words `approvals.marketing_status` already holds.
- `attach_licensures` matches on the BLA the asset carries before the brand. Where one
  BLA holds two products (BLA125326 is Arzerra and Kesimpta) the brand picks the row, and
  an asset whose name the file does not print under that BLA is refused.
- The row written says whether the licence is still sold. A revoked licence is
  Discontinued whatever its presentations say: twelve rows of the release read "Rx"
  beside "Voluntarily Revoked".

Run against a copy of the 2026-11-25 book: 15 written, none ambiguous, 44 unmatched. All
14 are dated. The fifteenth is Novo's revenue-line copy of Xultophy, which carries
BLA208583 and takes its 2016-11-21 date.

Ten of the 14 come out Discontinued. Before this they read as marketed products with a
missing record. None of the ten carries revenue, so no valuation moves.

### Two things to know about these dates

- The date is the licence's date in the register. Five Sanofi licences share 1999-12-09
  and two share 2000-02-24, under licence numbers 1725 and 1726. That reads as the day
  the licence was issued to that holder, since tetanus toxoid was in use decades
  earlier. The register prints no earlier date, so none is stored.
- The rows reach the book at the next Purple Book fetch on `main`, which runs weekly. A
  run started with `force_all` writes them at once.

## The 44: what each one is

Evidence for each was read from the book's own tables, the EMA register the book holds
(`eu_medicines`) and openFDA's drugsfda on 2026-11-25. The grouping is a reading of that
evidence. Each row needs its filing checked before a curated row is written.

Why this matters beyond the warning: these lines carry the latest-year revenue of
$30.9bn, DKK 42.7bn and EUR 1.3bn, 35 of them have forecast assumptions, and 43 of the 44
hold no exclusivity record. Where the same product also exists as a registry asset, the
revenue sits on one row and the approval and exclusivity on the other.

### A. Not a product: 8

| Ticker | Line | What it is |
|---|---|---|
| ALNY | Collaborations | collaboration revenue |
| ALNY | Rare | a category, the sum of products reported beside it |
| ALNY | C 5 Co Co Obligation | a performance obligation under a collaboration |
| ALNY | C 5 Monotherapy Obligation | a performance obligation under a collaboration |
| ARWR | Madrigal | revenue from a partner, named for the partner |
| BAYN | CT Fluid Delivery | a radiology device business |
| BMRN | Products Excluding ALDURAZYME | a subtotal of the company's own products |
| IONS | Salanersen | collaboration revenue against a compound still in trials |

Resolution: one row each in `data/not_a_product.csv`, with the filing cited. The revenue
stays in the company total and leaves the product list. Check BioMarin and Alnylam first:
a subtotal stored beside its own members counts that revenue twice.

### B. A product the company already holds, under another spelling: 12

| Ticker | Line | Asset that holds the approval |
|---|---|---|
| JNJ | CONCERTAMethylphenidate | Concerta, NDA21121, 2000-08-01 |
| JNJ | EDURANTrilpivirine | Edurant, NDA202022, 2011-05-20 |
| NVS | Gleevec Glivec | Gleevec, NDA21588, 2001-05-10 |
| NVO | Novo Seven | Novoseven, BLA103665, 1999-03-25 |
| NVO | Ryzodeg | Ryzodeg 70/30, BLA203313, 2015-09-25 |
| NVO | Novo Rapid And Novo Log | Novolog, BLA020986, 2000-06-07 |
| NVO | Novo Mix And Novo Log Mix | Novolog Mix 70/30, BLA021172, 2001-11-01 |
| PFE | Zithromax Zmax | Zithromax, NDA50710, 1991-11-01 |
| PFE | FSME-IMMUN / TicoVac | Ticovac, 2021-08-13 |
| MRK | Isentress / Isentress HD | Isentress HD, NDA205786, 2007-10-12 |
| INCY | Minjuvi / Monjuvi | Monjuvi, 2020-07-31 |
| GILD | Sofosbuvir Velpatasvir | Epclusa, NDA208341, 2016-06-28 |

Resolution: a row in `data/product_display_names.csv` so the line resolves to the asset
that already exists, then a one-off move of the revenue, regions and assumptions from the
copy to that asset, and the copy retired. Novo's Xultophy copy belongs here too: it is
dated now and is still a second row for one product.

### C. One line covering several products: 8

| Ticker | Line | Members |
|---|---|---|
| JNJ | Invega Sustenna / Xeplion / Trinza / Trevicta | Invega Sustenna, Invega Hafyera; Xeplion and Trevicta in the EU |
| JNJ | Prezista / Prezcobix / Rezolsta / Symtuza | Prezista, Prezcobix, Symtuza; Rezolsta in the EU |
| NVO | Haemophilia A | the factor VIII products |
| NVO | Haemophilia B | the factor IX products |
| NVO | Human Insulin | the human insulin products |
| BIIB | FUMADERM And ADUHELM | Aduhelm, BLA761178; Fumaderm, in neither register |
| MRK | Adempas / Verquvo | Verquvo; Adempas, licensed to Bayer |
| PFE | Braftovi / Mektovi | NDA210496 and NDA210498, both 2018-06-27, held by Array BioPharma |

Resolution: rows in `data/franchise_map.csv` naming the members, and the page shows the
members' approvals under the line. The filing reports one number, so the line stays the
revenue carrier and nothing is split. Braftovi and Mektovi are not in the book at all:
Array BioPharma is a Pfizer subsidiary and needs adding to Pfizer's sponsor names in
`approvals_openfda.py`.

### D. Licensed in the US to another applicant: 4

| Ticker | Line | Where the licence is |
|---|---|---|
| PFE | Eliquis | Bristol Myers Squibb, 2012-12-28 |
| MRK | Lynparza | AstraZeneca, 2014-12-19 |
| INCY | Tabrecta | Novartis, 2020-05-06 |
| LNTH | Techne Lite | NDA017771, 1976-11-16, listed by openFDA under SHINE |

Resolution: a row each in `data/marketed_additions.csv`, the register for a product
whose licence sits under another applicant's name. The approval stays the applicant's
and the date is what is taken, as the Purple Book step already does for Bayer's Eylea.

### E. Sold outside the US, in the EMA register: 7

| Ticker | Line | EMA record |
|---|---|---|
| BIIB | BENEPALI | 2016-01-13, Samsung Bioepis |
| BIIB | FLIXABI | 2016-05-26, Samsung Bioepis |
| BIIB | IMRALDI | 2017-08-24, Samsung Bioepis |
| BIIB | FAMPYRA | 2011-07-20, Merz Therapeutics |
| INCY | JAKAVI | 2012-08-23, Novartis Europharm |
| NVS | Jakavi | 2012-08-23, Novartis Europharm |
| PFE | Zavicefta | 2016-06-23, Pfizer Ireland |

Resolution: write an approval with region EU and agency EMA from `eu_medicines`, on an
exact and unique name. `approvals` has the two columns and every row today is US and
FDA, so each view that reads the table needs checking for an assumption that a row is
American before this is switched on.

### F. Sold outside the US, in no register the book can read: 5

| Ticker | Line | Evidence |
|---|---|---|
| AZN | Seloken | not in drugsfda; not in the EMA register |
| AZN | Roxadustat | not in drugsfda; the EMA register holds it as Evrenzo, under Astellas |
| BAYN | Aspirin Cardio | not in drugsfda; not in the EMA register |
| BAYN | Glucobay | not in drugsfda; not in the EMA register |
| PFE | Sulperazon | not in drugsfda; not in the EMA register |

Being in neither register is what a national authorisation looks like from here, and it
is not proof of one. Resolution: a small curated register, one row a product with the
annual report page that says where it is sold, and a page line that says "sold outside
the US; no approval record in a free register". No date is inferred.

## The plan, in order

1. Not a product (A). Curation only. Removes 8 and any double count. Smallest risk,
   largest effect on the totals, so it goes first.
2. Same product, other spelling (B). Curation plus one migration that moves revenue and
   assumptions to the surviving asset. Removes 12 and joins the revenue to its
   exclusivity date. This is the step that can move a valuation, so each company's fair
   value is compared before and after.
3. Other applicants (D), with Array BioPharma added to Pfizer's sponsors. Curation and
   one line of code. Removes 4 and brings Braftovi and Mektovi into the book.
4. Lines covering several products (C). Curation, and a change to the Portfolio page so a
   franchise line shows its members' approvals. Removes 8.
5. EMA approvals (E). Code, after the audit of views that assume a US row. Removes 7.
6. Outside every register (F), and the wording. Curation and copy. The message stops
   calling these missing. Removes the last 5.
7. A count by cause in the run's health summary, so a new one is seen the day it
   appears.

## Found on the way, not fixed here

- The 366 approvals the Purple Book step wrote before today carry no marketing status.
  The step only fills gaps, so they stay blank until backfilled.
- openFDA's approval for BLA020563 is attached to Humalog Kwikpen, whose own application
  is BLA205747. Humalog now has its own row from the Purple Book; the misplaced one
  remains.
- Not checked: whether a forecast for any of the 44 already carries a curated
  exclusivity year in its assumptions.
