# Arm names and acquisition terms across the universe, 2026-11-27

The two checks built for Lilly earlier today (`docs/research/2026-11-27-lilly-coverage-gaps.md`,
Part B) gave their first universe-wide readings: 44 pipeline rows named for a study's arm,
and 147 acquisition rows with no terms. This note records what each turned out to be, what
closed it, and what stays open with the reason.

Branch `claude/lilly-coverage-gaps-stufah`, continuing the Lilly work. Nothing to `main`.

## 1. Arm names: 44 rows, 44 closed

A derived pipeline row takes the shortest intervention name a study used, and the registry
often names an arm rather than a molecule. The reading (`trial_mapping.arm_named_assets`)
caught four shapes: a route ("LY4057996 IV", "SC VK3019"), a dose ("GSK3772701 50 mg",
"VXB-241 240 mcg", "Dose 1 of BMN 331"), a tracer ("[14C]AZD4954 Oral Solution"), and a
part, cohort or arm label ("AZD1613 - Part A", "AZD2373-Arm 1", "Exl-111 (MAD)").

Each row was read against its ClinicalTrials.gov record on 2026-11-27 and fixed through the
registers, never the database:

- **35 named** through `data/programme_names.csv`, each row citing the study that gives the
  name. Where the registry gives an INN it is used: opemalirsen (AZD2373, from
  NCT07154901), autogene cevumeran (RO7198457, from NCT03289962 and two others),
  cilofexor (GS-9674), trevogrumab (REGN1033), adimanebart (ARGX-119), fepixnebart
  (LY3016859, from the Lilly slide the discontinued register already cites). Where it gives
  only a code, the code is the name (AZD9793, AZD8965, AZD4954, AZD1613, BEAM-301, BMN 331,
  GSK4425689A, GSK3772701, LY4057996, LY4152199, LY3839056, MER511, LNTH2403, V118C,
  NNC0662-3168, EDK060, Exl-111, RO7121932, VXB-241, SRP-1003, VK3019, VY1706,
  AAVAnc80-antiVEGF). Five GSK and Sanofi vaccine candidates with neither are named from
  their studies' official titles: "RSV/hMPV combination vaccine", "4-component Strep A
  vaccine", "UTI vaccine", "iNTS-TCV", "GVGH quadrivalent pan-Salmonella vaccine",
  "egg-based H5N8 pandemic influenza vaccine".
- **11 folded** through `data/asset_alias_map.csv` into the product they are an arm of:
  anifrolumab's SC and prefilled-syringe arms into Saphnelo, ADAURA's and TATTON's
  osimertinib arms into Tagrisso, subcutaneous durvalumab into Imfinzi, the RENAL LIFECYCLE
  dapagliflozin arm into Farxiga, CAPTIVA's ticagrelor plus aspirin regimen into Brilinta,
  the GSK W candidate into the V candidate's row, the Humalog Phase 4 studies filed as
  "Lispro SC" into Humalog, the ofatumumab maintenance study into Kesimpta, and the
  aztreonam-avibactam infant study into Pfizer's ATM-AVI row.

Two rows of `data/discontinued_programmes.csv` were keyed by the old spellings
("RO7198457 intravenous (IV)", "LY3016859 ISA") and are re-keyed to the new names; the
retirement of BioNTech's own CRC study of autogene cevumeran stands, with the molecule
continuing on Roche's row as the basis already said.

Applied to the book in the refresh's own order (merge, arm pruning, indication pairs,
retirements) the reading is empty across the universe, and
`tests/test_arm_name_registers.py` holds every one of the 46 rows on the built book and asks
the reading to stay empty. The two AstraZeneca strays that failed
`test_a_split_model_is_named_in_the_alias_map` on the published book (the dapagliflozin
arm and "Ticagrelor + Aspirin") are among the folds, so that test passes again.

Side effect worth knowing: naming "Lispro SC" to Humalog moves two Phase 4 Humalog studies
onto the product. The row had been created by the comparator arm of LY4057996's Phase 1
(NCT06945406), where insulin lispro is the control, so a comparator arm of a Lilly product
in a Lilly study now lands on the product rather than standing as a programme.

## 2. Acquisition rows without terms: 147 read, 147 closed

The reading (`acquisitions.without_terms`) lists acquisition rows in `deals` within five
years that carry no figure. On the published book: 147 rows across 36 companies, from
headlines and from filings alike. Read one by one, they were three things.

### 2a. Not acquisitions: the parser's misreads

About a third. The headline parser (`fetchers/deals_news.py`) had read as an acquisition:

- an analyst's buy rating, where "Buy" is a rating and not a verb ("Capricor Therapeutics'
  Buy Thesis Ahead Of Deramiocel PDUFA Date", "Hidden Biotech Multibagger Stock To Buy
  Now", "Buy The Pullback", "BlackRock's Q3 Buy List", "Switching From Sell To Buy");
- a report of talks ("AstraZeneca said to offer $10B to acquire Rhythm", "Sanofi
  considering a deal to acquire Insmed, according to report");
- an option or a right ("right to buy Kestrel", "Holds Option to Acquire" Sail
  Biomedicines), a lapsed right ("Gilead will not buy Tizona"), a cancelled property
  purchase (Hackett Hill), a priority review voucher (Arrowhead; BioNTech's "Buys FDA
  Speed");
- a compound or its rights with no seller named ("Buys TQC3721 Rights", "Acquires SPR2015
  in $2.13 Billion Licensing Deal", "Acquires Felzartamab Rights");
- another company's deal under a shared press name ("Germany's Merck buys Silence
  Therapeutics"; Rapid Micro Biosystems, also Merck KGaA's);
- and a stray spelling of a real deal's party: a place ("St. Louis", "Boston-area",
  "Belgian", "Austin"), a description ("PET", "Prader-Will", "Bone Disease Treatment",
  "Rare-Disease Biotech Amicus Therapeutics", "Yale-spinout Modifi Bio"), or the capitals
  running into the next clause ("Vega To Add Late Stage", "Is Just What").

The parser now refuses each shape, reads the party past a place or a description, cuts a
name where the capitals ran on, reads a seller after a lower-case "from", types a purchase
of rights as a licence, and drops a headline about another company that shares the press
name before reading it. Every new test case in `tests/test_deals_news.py` is a headline the
book actually held. The one case that changed direction: "Gilead acquires German ADC
specialist Tubulis" was refused before because its capitals named nobody; the description
now leads to Tubulis.

The rows already in the table are removed by the ledger: a row with status
`not an acquisition` or `misread` in `data/acquisitions.csv` names the party, says in its
note what the headline was, and `acquisitions.load` deletes the uncurated rows for it on
every refresh and writes nothing.

### 2b. Real acquisitions, terms from the acquirer's own filings

For every real deal, a ledger row with the consideration as the acquirer's filing states
it: cash paid net of cash acquired and the maximum contingent consideration for a business
combination, the acquired IPR&D charge for an asset acquisition, each quoted verbatim from
the 10-K, 10-Q, 20-F, 8-K or 6-K and checked as a substring of the saved document. Where the
filing has not caught up, the acquirer's or the target's announcement, with the status
saying so. Bayer and Roche file with no regulator the book reads, so their media releases
are the source. A figure in euros, pounds or kroner stays in the announcement's words and is
never converted.

Conventions the rows follow, because a single "value" would be wrong whichever it picked:
upfront is the net-of-cash line of the cash flow statement for a business combination
(Reata $6,926.1m, HI-Bio $1,074.8m, Apellis $5,071.1m, Amicus $5,067.6m, Soleno $2,358.5m)
or the IPR&D charge for an asset acquisition (Merck's Imago $1.2bn, Prometheus $10.2bn,
Cidara $9.0bn, Terns $5.7bn; Incyte's Escient $679.4m, Vega $1,232m); contingent is the
stated maximum, never the fair value; total is the filed "up to" aggregate where one exists,
else upfront plus the maximum. Each note says which figure was taken and gives the
alternatives the filing also states.

Things the filings corrected in the table:

- dates: the table's date was the headline's, not the closing's (Terns 2026-08-04 against
  2026-05-05; Meilleur 2024-07-15 against 2024-06-18; Clade 2024-05-05 against 2024-04-11;
  Villaris 2024-02-12 against a 2022-11-17 close, the 2024 headline being a re-run);
- figures: the headline's number was often not the filing's (Life Molecular Imaging "up to
  $750 million" against $355.2m plus up to $400m; Nimble "$200M" against $210m upfront and
  up to $130m more; Biotheus "$800 million" against approximately $850m);
- parties: "Felzartamab rights" is a purchase of the greater China rights from TJ Biopharma;
  "Sunosi" is a purchase from Jazz Pharmaceuticals; "Clinigen's IL-2 product" is Clinigen SP
  Limited and the Proleukin business.

Because Amgen agreed Horizon on 2022-12-12 and closed on 2023-10-06, and a wire re-ran
Incyte's 2022 Villaris deal in 2024, the loader no longer asks a headline to sit within 200
days of the ledger's date where the ledger holds one deal with that target; the window
applies only where a target repeats.

### 2c. What stays without a filed figure

A ledger row whose filer states no figure is not a gap: the terms were looked for and the
filing says what it says. The reading excludes a curated row that carries the ledger's note
or the announcement's words. On this book those are: Omniose (AstraZeneca, terms not
disclosed), Targenomix (Bayer, not stated), Attralus (Bayer, "financial details not
disclosed", an asset purchase of two radiotracers), CureVac (BioNTech, consideration in
euros: 12,075,629 ADSs at EUR 1,001.1m fair value), Adverum (Lilly, per-share terms only,
no aggregate in a Lilly filing), Atraverse (J&J, undisclosed), Sironax (Novartis, an
option exercised with no figure in the Q3 release), Insmed (Sanofi, agreed on 2026-11-23 at
$175.00 a share, about $41.0bn equity value, with no Sanofi filing yet; the pending register
carries it). Eight rows in all. Two more carry a figure only from an announcement: Modifi
Biosciences (Merck; the target's release, since no Merck filing names it) and Chimagen's
second deal (GSK; "up to $750 million" with no upfront stated). Each is a row a reader can
open and see what the filing says.

### 2d. Counts

| Reading | Published book | After |
|---|---|---|
| Acquisition rows without terms, five years | 147 across 36 companies | 0 |
| Ledger rows | 24 (Lilly) | 141 (36 companies) |
| of which real acquisitions with a filed or announced figure | 24 | 101 |
| of which real acquisitions whose filer states no figure or a non-US one | 0 | 8 |
| of which not an acquisition or a misread headline | 0 | 32 |
| Headline and filing rows folded into a ledger row | 0 | 124 |
| Headline rows removed as not an acquisition or misread | 0 | 34 |
| Curated acquisition rows in the deals table | 24 | 109 |

The one measured pass fetched 198 documents from EDGAR, roche.com, bayer.com and the trade
press into a working folder, and every quote in the ledger was checked as a substring of
the document it cites before the row was written. The documents are not committed.

Things learned on the way that are not in the rows: GSK's Nuvalent deal (June to July 2026,
$9.6bn net of cash) was a completed business combination the book held as a $10.6bn
headline; Novartis India's purchase of Pfizer's Minipress trademark was made after
ChrysCapital took control of Novartis India, so it is another company's deal; Avidity's
lead asset was impaired by $1.94bn within seven months of Novartis closing; Excellergy's
headline "$2bn upfront" was $0.9bn upfront and up to $1.1bn more; BioMarin discontinued
Inozyme's BMN 401 in August 2026; Merck's Cidara and Terns deals, like all its
acquisitions in the period, were accounted as asset acquisitions, so their upfront figures
are IPR&D charges and not cash net of cash acquired, which each note says.

## 3. Sources

ClinicalTrials.gov API v2, each NCT named in the register rows, read 2026-11-27. EDGAR
full-text search and the filings named in each ledger row's `source` column; the documents
quoted are saved beside the work. Bayer's and Roche's media releases at the URLs cited.

## 4. Stale anchors: 158 read, 136 re-struck, 22 left with a reason (2026-11-28)

The third reading, `book_gaps.stale_anchors`, named 158 marketed seeds and company lines
across 20 companies whose anchor cited the first half of 2026 or earlier while the company
had filed its third quarter. Each company's Q3 2026 earnings exhibit and 10-Q was fetched
and the product's row read: third quarter and nine months, 2026 and 2025. Every figure was
checked against the cells of the row it quotes in the saved document.

Each anchor keeps the convention it was written in and moves one quarter on:

- a rate struck on the halves (Pfizer, Merck, Bristol Myers, BioMarin, most of AbbVie) is
  struck on the nine months of 2026 against the nine months of 2025;
- a 2026 implied by the first half and a second-quarter pace (Amgen, Axsome, Krystal) is
  implied by the nine months and a third-quarter pace, against the FY2025 base;
- a launch's run-rate base (Vyalev, Aucatzyl, Yeztugo, Caplyta) likewise, with Caplyta's
  rate re-solved to its unchanged $2,700mm peak by 2031;
- a line anchored on the latest quarter annualised (Syfovre, Empaveli) takes the third
  quarter; Dupixent follows Sanofi's nine months in euros (15,011 against 11,468).

Four anchors are sums of rows the filer prints and never adds (Botox Therapeutic and
Cosmetic; Parsabiv and Lumakras, US and ROW; Biogen's two anti-CD20 rows); each row says
so and gives the parts.

**22 anchors were read and left**, recorded in `data/stale_anchor_reviews.csv` with the
quarter they were read against, so the reading drops them until a later quarter is filed:

- AbbVie no longer prints Lumigan, Ozurdex, Combigan, Other Eye Care or Duodopa; they sit
  inside All other and Other Neuroscience, which are therefore no longer on their FY2025
  composition either (seven anchors).
- Pfizer moved sterile injectables and biosimilars into a new Hospital and Biosimilars
  portfolio and restated 2025, so its four "All other" lines are off their base's
  classification.
- Sarepta prints its three PMOs as one group. J&J's two lines are residuals the segment
  figure alone does not give. Amgen's Other revenues is printed gross of BeOne.
- Gilead's royalty line carries one-off IP revenue in both years; Biogen's contract
  manufacturing is held flat by judgement; Ionis's Dawnzera rate is tied to unchanged
  guidance; Vertex's Other revenues is nil as before; setrusumab is not marketed.

**A second defect surfaced and is fixed.** 23 rows held a value no ledger entry accounts
for, so `reconcile_seeds` read them as an analyst's and a corrected file never reached the
book. Lilly's Jardiance rate was the first, reported on 2026-11-27. `data/seed_row_adoptions.csv`
names each row with the exact value it holds; a row still holding it is the file's to
correct once, after which the ledger owns it.

| Company | Fair value before | After | Modelled 2026 before ($m) | After | Guidance |
|---|---|---|---|---|---|
| AbbVie | 221.08 | 222.72 | | | |
| Pfizer | 26.46 | 26.24 | 62,952 | 63,478 | 62,000 to 64,000 |
| Amgen | 454.66 | 505.99 | 39,961 | 40,597 | 38,200 to 39,400 |
| Merck | 187.38 | 187.77 | 68,483 | 68,328 | 66,300 to 67,300 |
| Bristol Myers | 105.14 | 102.43 | 50,407 | 50,544 | 49,750 to 50,250 |
| BioMarin | 20.24 | 20.19 | 3,323 | 3,326 | 3,825 to 3,925 |
| Biogen | 240.13 | 253.91 | | | |
| Gilead | 146.14 | 146.03 | | | |
| Sarepta | 19.22 | 17.90 | 2,550 | 2,614 | 1,200 to 1,400 |
| J&J | 214.11 | 214.16 | 102,692 | 102,766 | 101,200 |
| Axsome | 130.95 | 174.85 | | | |
| Lantheus | 58.84 | 59.80 | | | |
| Vertex | 507.76 | 508.16 | 13,181 | 13,209 | 13,150 to 13,250 |
| Ionis | 40.44 | 40.44 | | | |
| Krystal | 116.84 | 124.71 | | | |
| Lilly | 511.78 | 521.40 | 92,476 | 94,043 | 91,000 to 92,000 |

Ultragenyx, Regeneron, Autolus, Neurocrine and United Therapeutics return no sum-of-the-parts
value on this book, before or after.

Three moves a reader should look at before trusting them:

- **Amgen, +$51 a share.** The implied-year convention turns a strong third quarter into a
  starting rate: Uplizna +129%, Imdelltra +117%, Repatha +33%, each fading over its band.
  Modelled 2026 is now 3.0% above the top of Amgen's guidance, which is the flag's line.
- **Axsome, +$44 a share.** Auvelity's rate moves from +37% to +48% on the same convention.
- **Lilly, +$9.6 a share.** Jardiance's re-struck rate (48%, on years that carry BI
  milestones at both ends, as its row says) finally reached the book. Modelled 2026 is
  2.2% above the top of guidance.

Things the filings said that the rates alone do not: Merck's Bridion fell to $144mm in
the quarter on generic entry while its nine-month rate is only -17%; Gardasil's quarter
carried favourable purchase timing; BioMarin will no longer market Roctavian; Sarepta's
Elevidys is down 64% for the nine months. Gilead's Yeztugo sits in the book both as a
company line (grown to its 2026 run rate and held) and as a seed starting in 2027, which
reads as a possible double count from 2027 and was left for a decision.
