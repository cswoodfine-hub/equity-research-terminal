# Patents into the revenue build: the plan

Status: proposed 2026-10-29. Steps 0 and the sources for step 1 are built; the
backtest (`BACKTEST.md`) revised step 1, and the base-date rule is Charles's decision.

## Update after the backtest (2026-10-29)

Built: the Paragraph IV fetcher reads FDA's spreadsheet (333 products challenged, 413
launch dates); the USPTO's extension lists are a source (1,141 certificates, 709
applications); each product reports its molecule patent as the floor of its range; a
recorded generic launch dates a loss beneath a filer's own date.

What the backtest changed: the molecule patent is the floor, not the date. Against 122
real launches it is a median 1.6 years out, while filers' disclosed dates are 0.4 years
out. So step 1's order stands with one change: rung 2 (the molecule patent) becomes the
bear date and the range's floor, and the base date for a product with no disclosure is
Charles's choice between the latest substance patent (today's rule, untestable) and the
molecule patent plus paediatric extension (tested, near unbiased, 1.6 years typical
error). The bar in step 6 is revised from "80% within 6 months" to the measured errors
above, and the first accuracy work is disclosures for the largest patent-dated products.

Charles chose to keep today's base rule (latest substance patent), with the molecule
patent shown as the floor.

Step 3 done the same day (`EROSION.md`): small-molecule erosion measured on 104 generic
launches in Medicare Part D, in two rows by the Orange Book route (oral keeps 0.245 of
the brand in year one, non-oral 0.41), replacing the literature row. A recorded generic
launch with no fall since stays in the base (Symbicort). Biologics unchanged.


## The problem in one paragraph

The forecast stops a product's growth at a single loss-of-exclusivity (LOE) year, then
applies an erosion curve. Both halves are weaker than they look. The date comes from the
filer's disclosure where there is one. Where there is not, it comes from the latest patent
the Orange Book flags "drug substance", and that flag does not mark which patent covers the
molecule. The curve is one curated default for each modality. Errors in either half compound
over the whole tail, and the tail is most of the value of a product with six or more years
to run.

## What the book holds today

Measured on the published copy, 2026-10-29, over 376 marketed modelled products.

| LOE basis | products | how good |
|---|---|---|
| filer disclosure (10-K / 20-F) | 119 | best available; the filer's own expected date |
| biologic reference-product exclusivity (BPCIA 12 years) | 100 | a floor, not a date: biosimilars usually launch later |
| latest drug-substance patent | 82 | 25 of these carry substance patents 2 or more years apart, so the pick matters |
| latest patent of any kind | 11 | set by a method-of-use patent (Spravato, Vanrafia 2043, Multaq, Airsupra) |
| no LOE | 37 | the forecast runs with no cliff |
| curated compound patent (`compound_patent.csv`) | 5 products, 9 rows | the only rows that name the molecule patent |

Other facts that shape the plan:

- Orange Book patent flags held: substance 727, product 494, use 896, none 1,432. The use
  code is stored only as a boolean, so the book cannot tell which indication a method-of-use
  patent covers.
- `patent_challenges` (Paragraph IV) is **empty**, and the cause is a defect. FDA now
  publishes the Paragraph IV list as a spreadsheet (`9-28-2026 Paragraph IV List
  (Public)`, 1,649 rows). The fetcher opens it as a PDF and fails with "Stream has ended
  unexpectedly". Read correctly, the list covers **330 of the book's NDAs in 461 rows**.
  Of those rows, 117 carry the date the first generic filer began commercial marketing:
  a real generic launch date, the ground truth a backtest needs.
- 31 combination products.
- Erosion defaults: small molecule 60% in year one, 35% a year after, 10% from year four,
  all from the literature. Biologic 25% then 20%, from 8 filer observations whose year-one
  loss ranges from +3% to -43%. The file's own note says what separates them is the number
  of entrants and how much of the year they had, not the modality.
- IRA negotiated prices are held (`negotiated_prices`) but do not enter value.

Live examples of the date being wrong or arguable: Wayrilz (latest substance patent 2041,
compound 2033), Lumakras (2040 crystal form against the 2038 compound), Vanrafia (2043, a
method-of-use patent), Xofluza (an approved generic since June 2026 while the book shows
it protected).

## The principle

The LOE is the **first date a generic or biosimilar can lawfully launch and is likely to**.
It is not the last patent to expire. Hemphill and Sampat found that challenges fall
disproportionately on later-expiring, lower-quality patents. Effective market life stayed
stable over the decade they studied, which means secondary patents rarely buy the full term
they list. They also found high-sales drugs are challenged more often, and the book is full
of high-sales drugs ([DOI](https://doi.org/10.1016/j.jhealeco.2012.01.004)). Amin and
Kesselheim show how far the listed stack can run past the molecule: 108 patents on
ritonavir and lopinavir/ritonavir could reach 2028, twelve years beyond the compound
patents ([DOI](https://doi.org/10.1377/hlthaff.2012.0107)). Olsen et al. found 59% of
insulin products were drug-device combinations, about 63% of their patents covered the
device, and on 9 products patents filed after approval extended expected protection by a
median of 6 years ([DOI](https://doi.org/10.1371/journal.pmed.1004309)). So the plan sets the base date
from the patents and exclusivities that actually hold a generic off the market. It carries
the later stack as a range, not as the answer.

## The rules the dates are built from

These are statute, applied without estimating anything:

- **NCE exclusivity**: 5 years from approval. An ANDA with a Paragraph IV certification may
  be filed at year 4, and the 30-month stay then runs from that filing, so an NCE generic
  is held to at least 7.5 years from approval unless the patents fall sooner.
- **New clinical investigation exclusivity**: 3 years, and it covers only the change
  approved.
- **Orphan exclusivity**: 7 years, for the orphan indication only. It is not a cliff on the
  whole product (`loe.NOT_A_CLIFF` already says so).
- **Paediatric exclusivity (PED)**: 6 months added to every listed patent and exclusivity
  on the active moiety.
- **Patent term extension (35 USC 156)**: one patent per product. The extension restores up
  to 5 years, and the restored term may not run more than 14 years past approval. The
  Orange Book expiry already includes any extension granted.
- **BPCIA**: 12 years of reference-product exclusivity, with no biosimilar application
  accepted in the first 4. A floor, since biosimilar launch is usually set by patents and
  settlements.
- **180-day exclusivity**: the first Paragraph IV filer has 180 days in which no later
  generic can be approved, so year one after a small-molecule LOE often has one or two
  generics, not many.
- **Section viii carve-out**: a generic may launch with the patented indication removed
  from its label. A method-of-use patent therefore holds one indication, not the molecule,
  and never sets the product's date. *GSK v. Teva* (Fed. Cir. 2021) found induced
  infringement on a carved-out label, so a use patent is a bear-to-bull risk on the
  covered indication's share, not on the product.

## Step 0: fix the Paragraph IV fetcher, then measure the baseline

1. Read the spreadsheet with `openpyxl` (already installed). Store every column: drug,
   form, strength, RLD and NDA, submission date, number of ANDAs, 180-day status and its
   posting date, first approval, first commercial marketing, and the expiry of the last
   qualifying patent. Saved fixture, unit test, no PDF path left behind. CLAUDE.md asks for
   the payload discrepancy to be reported: FDA changed format.
2. Before changing any date, record the baseline: each product's current LOE, its basis,
   and its NPV. Every later step reports its delta against this.

## Step 1: get the date right

A fixed source hierarchy. Each product's `loe_basis` names the rung it came from.

1. **Filer disclosure** (`disclosed_loe.csv`, 119 products), and a **settlement** the filer
   or the court docket discloses. A disclosed date beats a computed one because the filer
   knows its settlements.
2. **The compound patent**, identified by evidence rather than by the latest flag:
   - the drug-substance patent that received the term extension. Only one patent per
     product can be extended, and companies extend the molecule patent almost every time.
     A patent whose Orange Book expiry runs past 20 years from filing was extended, so the
     test needs the filing date. That comes from the USPTO (blocked; see the hosts below).
     Until it is reachable, research agents fill `compound_patent.csv` from the patent
     record, with a basis line per row, through the existing seed rules.
   - plus its PED where the Orange Book lists a `*PED` line.
3. **Statutory exclusivity**: NCE + 30-month stay for a small molecule; BPCIA 12 years for
   a biologic.
4. Method-of-use patents never set the product date. They are stored with their use code
   (the code itself, not a boolean), so step 4 can apply them to one indication.

**Combinations.** The base date is the latest compound patent among the components, since
a generic of the fixed dose needs every molecule free. Whether erosion starts earlier, when
one component goes generic and prescribers switch to two pills, is measured in step 3
(Exforge, Caduet, Janumet and Invokamet are on the Paragraph IV list). It is not assumed.

**Already generic.** A product with an approved and marketed generic (the Paragraph IV
first commercial marketing date, or an openFDA ANDA approval) is past LOE, whatever its
patents say. That fixes Xofluza.

## Step 2: the date as a range

Three dates per product, each with its source:

| case | date |
|---|---|
| bear | the earliest lawful entry: a Paragraph IV filing plus 30 months, or NCE + 30 months, where the challenged patents are later than the compound patent |
| base | step 1's date |
| bull | the latest product or crystal-form patent that is unchallenged on the Paragraph IV list |

The base case stays the valuation. The range shows the reader how much of the NPV depends
on which patents hold. A product with no Paragraph IV filing and nothing after the
compound patent has one date and no range, which is correct.

## Step 3: measure erosion instead of assuming it

The earlier attempt found 11 observations because it filtered CMS to the universe's own
brands with an LOE inside 2020 to 2024. The fix is to measure over **every** drug, not
just the universe, then apply the curve by the features that predict it:

- events: first generic or biosimilar launch dates from the Paragraph IV list (409 rows
  with a launch date) and openFDA ANDA approvals, plus biosimilar launches from the Purple
  Book;
- outcome: the brand's share of Medicare Part D and Medicaid gross spending and claims in
  each year after entry, from the CMS series the book already reads (Part D Spending by
  Drug for every year CMS publishes; Medicaid State Drug Utilization back to 1991);
- features: modality, route (oral, injectable, inhaled, device), number of entrants in
  year one (180-day status says whether one filer held it), and whether an authorised
  generic launched.

The output replaces `erosion_defaults.csv` with a measured table, each row carrying its
sample size and spread. The forecast picks the row matching the product's features. Where
a cell has too few events, it falls back to the modality row and says so. Part D and
Medicaid figures are before rebates, so they measure volume and share, never revenue, as
the house rules require.

## Step 3b: close the erosion caveats

Step 3 was built on 2026-10-29 (`EROSION.md`) with four caveats. Each one has a free data
route. Each fix is measured, and none is assumed. Every route below was checked as
reachable on 2026-10-29.

### 1 and 2: gross of rebates, and Medicare only. Calibrate to the filers' US lines

A filer's printed US product line is net of rebates and covers every channel (commercial,
Medicare, Medicaid). So it closes both caveats at once, wherever it can be read.

- **Data.**
  - The SEC quarterly Financial Statement Data Sets keep the product and geography tags
    back to 2009. The 2016 Q1 set holds 12,521 product-tagged rows, 321 of them revenue by
    product and geography. Merck, Lilly and Pfizer tag Zetia, Cialis and Lyrica by product
    that year. Which filers also tag the US split is the first thing measured.
  - Where a filer does not tag the US split, its 10-K or 20-F product table does.
    `revenue_mdna` already reads those tables, and `region_revenue.csv` holds them for
    2025.
  - The 20-F filers (AstraZeneca, Novartis, GSK, Novo, Sanofi) print the US by product in
    their tables.
- **Events.** Every product in the universe with a recorded generic launch, from 2010 to
  2025 (Paragraph IV list, CMS deselections). Each needs a US line in the year before
  launch and in at least one of the three years after. Expected: 30 to 50 events. The
  count is reported, not assumed.
- **Measure.**
  - For each event, the filer's US line retained, beside the Part D brand cost retained
    for the same product in the same years. The two measures sit on the same events, so
    their ratio is a measurement of the rebate and channel gap, year by year.
  - With 15 or more oral events, the oral row is refitted on the filer lines and Part D
    becomes the cross-check. With fewer, the Part D curve is scaled by the median ratio,
    and the ratio's spread is carried as the uncertainty.
- **Authorised generics.** A filer's US line can include its own authorised generic, as
  AstraZeneca's Symbicort does. Each event is flagged from FDA's "Listing of Authorized
  Generics" (a PDF on fda.gov, the issue of 2026-10-05 reachable). Events with one and without one are measured as separate
  rows, and a product that will launch one takes the row that matches.
- **What stays.** Filer lines exist only for the universe's own products, which are large
  brands, so the calibration describes large brands. That is what the book values. It is
  said, not corrected.

### 3: non-oral rows are thin. More events, and a row per route

- **More launches.**
  - Generic entry is read from Part D directly: the first year a product under the same
    generic name from another labeler passes 5% of the molecule's claims. That adds
    launches the Paragraph IV list never recorded because no patent was challenged
    (Advair's Wixela in 2019, glatiramer's generics).
  - The detector is checked first against the 104 Paragraph IV events, on whether it
    names the same launch year, and that agreement rate is reported.
- **Physician-given injectables.** Small-molecule injectables are mostly Medicare Part B,
  not Part D. Medicare Physician & Other Practitioners by Geography and Service (one
  dataset a year, 2013 to 2024) gives national services and allowed amounts by billing
  code, so Velcade, Alimta, Abraxane and Treanda are measurable on their own codes.
- **Rows.** A row per route where a route reaches 15 events (inhaled, injectable, topical
  or transdermal, eye); the pooled non-oral row below that. Each row carries its count and
  spread, and a hold-out test as in step 6.

### 4: biologics untouched. Measure them in Part B, where they are billed

- **Data.**
  - Medicare Physician & Other Practitioners by Geography and Service (2013 to 2024) and
    Medicare Outpatient Hospitals by Geography and Service (2015 to 2024), by billing
    code.
  - A biosimilar carries its own Q code (Zarxio's Q5101 from 2015), so the launch year and
    the brand's share read straight from the data.
  - Part B pays from the average sales price, which is net of the discounts and rebates
    manufacturers give purchasers. That is closer to net revenue than Part D's gross cost.
- **Events.** About 10 to 12 launches:

  | biosimilar launch year | brands |
  |---|---|
  | 2015 | Neupogen |
  | 2016 | Remicade |
  | 2018 | Epogen and Procrit, Neulasta |
  | 2019 | Herceptin, Avastin, Rituxan |
  | 2022 | Lucentis |
  | 2024 | Actemra and others |

  Humira (2023) and Stelara (2025) are pharmacy drugs. They are read on Part D claims
  share, since Part D gross cost rose through Humira's cliff.
- **Fit.** The Part B curves, the Part D share curves and the eight filers' US lines on
  file are three sources on overlapping events. They are fitted together, with the number
  of biosimilars in year one as the feature that the eight filer lines already say
  separates the outcomes. With too few events for a feature, one row with its spread.
- **What stays.** Launches from 2025 on enter only as CMS publishes the year, plus the
  quarterly Part B spending file for 2025 and 2026 Q1.

### Order, and the stop

1. The filer US-line events table, with its coverage reported.
2. The authorised-generic flag.
3. The Part D entry detector, checked against the Paragraph IV events.
4. Part B small-molecule injectables.
5. Part B and outpatient biologics.
6. The rows refitted, with a hold-out test for each.
7. The value delta on a copy, as in step 6. **Stop for agreement** before the defaults
   file changes.

No new host is needed: sec.gov, data.cms.gov and fda.gov are all reachable.

## Step 4: tie the peak and the tail to the date

- **Peak before LOE.** The growth fade must finish by the LOE year. A product whose
  ceiling is reached after its LOE has a contradiction in its seeds, and the validator
  flags it rather than trimming it.
- **Indication by indication.** Where a method-of-use patent outlives the compound patent
  and covers one indication (step 1's use codes), that indication's layer keeps the brand
  share the section viii evidence supports, from measured carve-out cases in step 3. The
  rest of the product erodes from the compound date. Without measured cases, the layer
  erodes with the product and the later patent shows in the bull case only.
- **IRA.** A product selected for negotiation takes its maximum fair price from the year
  it applies, as a pre-LOE step-down in the bear case. The base case is unchanged until
  the step is backtested against the 2026 prices CMS has published. The MFP file is on
  www.cms.gov (blocked).

## Step 5: regional dates

The US date drives US revenue. Europe and Japan have their own:

- EU: 8 years of data protection, plus 2 of market protection, plus 1 for a new
  indication; a supplementary protection certificate up to 5 years, capped at 15 years from
  first EU authorisation; 6 months more for a paediatric plan.
- Japan: an 8-year re-examination period for a new active ingredient, and up to 5 years
  of patent extension.

`disclosed_loe_regions.csv` and `region_revenue.csv` exist. Where a filer discloses the
regional date it is used. Otherwise the statutory date is used, labelled as such, and a
region with neither keeps the US date with a note.

## Step 6: validate before it goes live

The test is whether the method would have called past LOEs correctly, run blind:

- **Date.** For every product with a known generic launch (the 117 universe rows with a
  first commercial marketing date, plus disclosed biosimilar launches), apply step 1 to
  the patent and exclusivity data as it stood before launch and compare. Report median
  absolute error, the share within 6 months, and every miss over a year with its cause.
  Proposed bar: 80% within 6 months, beating the current latest-substance rule on the same
  set.
- **Erosion.** Hold out a fifth of step 3's events, fit on the rest, and report the
  error in year-one and year-three brand share against the current defaults.
- **Value.** For each product, the NPV under the old and new dates and curves, sorted by
  change. Any product moving more than 10% is reviewed by hand before it ships.

Nothing reaches the book until these three reports are read and agreed.

## Step 7: show it

The LOE view and each product page show the stack behind the date: compound patent and
expiry with its extension and PED, later patents with their kind and use code, Paragraph IV
filings and their 30-month dates, the exclusivities, the chosen basis and the bear, base
and bull dates. The erosion row in use shows its sample size. A reader can see why the
cliff is where it is and argue with it.

## Step 8: proxies the book's own data can infer

Agreed 2026-10-29. Five proxies, each built from data the book already holds, each
tested against a number a company later reports before it touches value. Each one stops
for agreement with a value delta on a copy, as step 3b did.

### 8a. Trial spend: R&D ahead, bottom up

- **Exists.** `development.py` costs each registry study at a per-patient rate
  (`data/development_costs.csv`) over its run from start to primary completion. It is
  deliberately beside the valuation, because the forecast already charges company R&D as
  `rd_pct` × revenue.
- **Build.** For each company and calendar year, the cost of every study it sponsors that
  is running in that year: active studies (`trials`) and completed ones
  (`completed_trials`). That is the company's clinical spend path.
- **Test.** Can the change in that path predict the change in reported R&D (`financials`,
  `ResearchAndDevelopmentExpense`) the next year, better than `rd_pct` × revenue does?
  The test runs on every company-year the registry and the filings both cover, and
  reports the error of each rule.
  - Look-ahead bias, stated: the registry is today's record, so enrolment is often the
    actual figure rather than the target known at the time.
  - Two fields the fetcher should add: enrolment type (actual or anticipated) and site
    count.
- **Use, if it wins.** It sets company R&D for the first two to three forecast years as a
  company-level line in the sum of the parts. The difference from `rd_pct` × revenue is a
  cash-flow adjustment, so nothing is counted twice. `rd_pct` resumes after those years.
- **Show.** On the company page: R&D ahead by phase, stacked, against reported R&D. In
  What Changed: when a large study starts or ends.

### 8b. Cash runway, and the dilution it implies

- **Exists.** `runway.py` (cash with marketable securities, trailing twelve-month burn)
  and `financings.py` (raises after the balance sheet date).
- **Build.**
  - Forward burn: 8a's clinical path plus the company's non-clinical spend, its reported
    operating cash outflow less clinical.
  - Months of cash ahead, and whether the cash runs out before the next priced catalyst.
- **Test.** On the history in `financings`: did companies with under 12, 18 or 24 months
  of cash raise within the next six months, and how much, as a share of market
  capitalisation and at what discount?
- **Use.** Expected dilution in the per-share value of clinical-stage companies: the
  probability of a raise, times its size, at the measured discount. Today per-share value
  uses current diluted shares, as if no raise were coming.
- **Show.** The runway list ranked by months left, with "raise before readout" flagged; a
  dilution line on the company valuation.

### 8c. What the market prices in

- **Exists.** `event_moves.py` sets the model's move on a readout beside the move options
  imply, where a chain exists. `gate_calls` and `call_log` score the model's calls.
- **Build.** The share price move net of the sector index (`benchmark_prices`) over a
  window around each past dated catalyst (`catalysts`, `trial_readouts`, approvals), by
  outcome, phase and therapy area.
- **Test.** For resolved catalysts, the model's stake against the realised move.
- **Use.** A calibration of the gate engine. A measured bias in the stake size is
  reported and, if agreed, corrected. No market price enters a value.
- **Show.** A "model against market" column in the catalyst calendar, and the catalysts
  where the two differ most.

### 8d. Safety signal

- **Exists.** `trial_result_safety` (serious adverse events by arm, shown only in the
  landscape) and `labels` with its snapshots (boxed warnings).
- **Build.**
  - Each completed study's serious adverse event rate against its comparator arm.
  - The rate for each mechanism class within an indication.
  - Boxed warnings added between label snapshots.
- **Test.**
  - Does an imbalance predict the next phase failing or the programme stopping?
    Measured on completed studies and what became of their assets.
  - For marketed drugs: the change in Part D prescriber counts after a boxed warning.
- **Use.** Only where measured: a probability adjustment, or a peak-share adjustment.
  Otherwise a flag that does not move value.
- **Show.** A safety column in the landscape and on drug cards, and a What Changed entry.

### 8e. Deal appetite

- **Exists.** `deals` (161 rows with terms), LOE dates, the pipeline rNPV, and
  `future_pipeline.py`.
- **Build.** Each company's gap, its US revenue losing exclusivity within five years over
  the pipeline rNPV plus future-pipeline value, beside its capacity to pay (net cash,
  leverage).
- **Test.** Did the companies that bought have the larger gaps beforehand? The `deals`
  history, by year.
- **Use.**
  - For buyers: where their cash goes.
  - For targets: a takeover probability and premium as a bull-case overlay, never in the
    base case.
- **Show.** A universe screen of who must buy and who could be bought, matched by
  therapy area.

### Order

8a, 8b, 8c, 8d, 8e. 8b needs 8a's path. Each lands as a view first, then stops for
agreement before it moves value.

## Order of work, one concern per commit

1. Paragraph IV fetcher on the spreadsheet; fixture and test. Baseline report.
2. Orange Book use codes stored as codes; exclusivity codes kept.
3. Date hierarchy (step 1), with the compound-patent seeds researched for the 25 products
   with spread-out substance patents and the 11 set by a use patent first.
4. The range (step 2).
5. Measured erosion (step 3) and its backtest.
6. Date backtest and NPV delta report (step 6). **Stop for agreement.**
7. Peak and tail coupling, indication-level carve-outs, IRA bear step (step 4).
8. Regional dates (step 5).
9. UI (step 7).

Steps 1 to 6 need no new host. The rest need these allowed in the environment's network
settings:

- `www.uspto.gov` and `data.uspto.gov`: patent filing dates and the term-extension list,
  to identify the compound patent without research by hand;
- `www.federalregister.gov`: FDA's regulatory review period notices, the second source for
  an extension;
- `www.cms.gov`: the negotiated price file.

## What this will not do

It will not predict litigation outcomes, invent a settlement date, or put a number on a
"patent thicket" that no source states. Where the date depends on a court, the range says
so and the base case uses the evidence the hierarchy names.

## Sources

According to PubMed:

- Hemphill CS, Sampat BN. Evergreening, patent challenges, and effective market life in
  pharmaceuticals. *J Health Econ* 2012;31(2):327-39.
  [DOI](https://doi.org/10.1016/j.jhealeco.2012.01.004)
- Amin T, Kesselheim AS. Secondary patenting of branded pharmaceuticals: a case study of
  how patents on two HIV drugs could be extended for decades. *Health Aff* 2012;31(10):
  2286-94. [DOI](https://doi.org/10.1377/hlthaff.2012.0107)
- Olsen A, Beall RF, Knox RP, Tu SS, Kesselheim AS, Feldman WB. Patents and regulatory
  exclusivities on FDA-approved insulin products: a longitudinal database study,
  1986-2019. *PLoS Med* 2023;20(11):e1004309.
  [DOI](https://doi.org/10.1371/journal.pmed.1004309)

Data: FDA Orange Book data files; FDA Paragraph IV certifications list (spreadsheet,
2026-09-28); openFDA drugsfda; FDA Purple Book; CMS Part D Spending by Drug and Medicaid
State Drug Utilization Data; 21 USC 355(j), 355a, 360cc; 35 USC 156; 42 USC 262(k)(7).
