# Sanofi after Insmed: what the book says, and what absorbing Insmed would do

Date: 2026-11-26. Book: the published database of 2026-11-26. Nothing in `data/` or the
book was changed for this note. The Insmed assets were added to a scratch copy only.

## The answer

- Until 2026-11-26 the book had not absorbed Insmed. It held no Insmed product and no
  pending deal row, so none of Sanofi's recorded value came from the acquisition.
- Sanofi's recorded fair value moved from $68.17 to $66.99 per ADR on the day after the
  announcement, for reasons that have nothing to do with Insmed.
- As built on 2026-11-26 (Part 4), the three Insmed assets add $4.19 per ADR and Sanofi's
  fair value goes from $67.01 to $71.34. The price paid is $16.81 per ADR and stays out
  of the valuation by the book's rule. Net of it the figure is $54.53, against a close
  of $54.39.
- The market read the deal as worth more than that: the ADR rose from $46.77 to $54.39
  in two sessions.

## Part 1. What moved, and why

| Call | Price per ADR (close of) | Fair value | Engine |
|---|---|---|---|
| 2026-11-24 | $46.77 (23 Nov) | $68.17 | 33315bcf |
| 2026-11-25 | $51.90 (24 Nov) | $66.99 | 1a3286b0 |
| 2026-11-26 | $54.39 (25 Nov) | $67.01 | 31434cf2 |

The why-moved read for 24 to 25 November (`/companies/SNY/why-moved`):

- Fair value fell $1.18, 1.7%. The cost of equity held still.
- No analyst changed an assumption on Sanofi. The eleven priced gates are worth what
  they were.
- Two things changed underneath: four revenue restatement rows, and the engine itself,
  which took about twenty commits that evening (growth fading past a cliff, regional
  revenue totals, revenue back to FY2014). The record cannot split the $1.18 between
  them without running the old engine on the same book.
- The move sits in marketed products ($29.17 to $28.28) and the future pipeline line
  ($27.43 to $27.01). Neither holds anything of Insmed.

The price is real. Yahoo's daily closes for the Paris line read EUR 85.26, 93.58, 98.16
on 23, 24 and 25 November, the same 15% over two sessions as the ADR.

One thing to check separately: the street target for SNY reads $96.99 mid and $136.99
high on 2026-11-26, against $57.00 the day before and a $54.39 price. That looks like a
Paris-share target against the ADR. Not verified.

## Part 2. What was sourced

| Fact | Value | Source |
|---|---|---|
| Deal | $175.00 a share in cash, merger agreement of 2026-11-23, Item 1.01 | Insmed 8-K 0001140361-26-045364 |
| Total consideration | $41.0bn (EUR 37.6bn), 46% premium to the 18 Nov close, close expected first half of 2027, no financing condition | same filing, Exhibit 99.1 |
| Outside date | 2027-08-23, extendable to 2028-02-23; Insmed termination fee $1,125mm | same filing, Item 1.01 |
| Shares outstanding | 219,380,309 at 2026-10-23 | Insmed 10-Q 0001104506-26-000047 |
| Brinsupri revenue | $400.1mm in Q3 2026, $917.1mm in nine months, $172.7mm in FY2025 | 10-Q note 4; 10-K 0001104506-26-000009 |
| Arikayce revenue | $124.4mm in Q3 2026, $338.8mm in nine months against $314.5mm; $433.8mm in FY2025 | same |
| 2026 guidance | Brinsupri $1.35bn to $1.4bn; Arikayce $460mm to $470mm | Insmed 8-K 0001140361-26-041097, Exhibit 99.1 |
| Management peaks | "more than $7 billion" Brinsupri, "more than $6 billion" TPIP, "more than $1 billion" Arikayce | same |
| Brinsupri patents | drug substance patents to 2035-01-21 and 2035-03-12, before any term extension; later patents to 2039 and 2040 | 10-K, patents section |
| Arikayce patents | thirteen Orange Book patents, the latest 2035-05-15 | same |
| TPIP patents | compound patents to 2034-10-24; pending formulation patents would run to October 2041 | same |
| Royalties out | AstraZeneca: "high single-digit to mid-teens" on brensocatib. OrbiMed: 4.5% of Arikayce and 0.75% of brensocatib | 10-K licence section; 10-Q note 11 |
| Approvals | Brinsupri NDA217673, 2025-08-12. Arikayce NDA207356, 2018-09-28 | openFDA drugsfda |
| TPIP Phase 3 | PALM-PAH NCT07481981 and PALM-ILD NCT07179380, primary completion December 2028 | ClinicalTrials.gov, read 2026-11-26 |
| Arikayce label expansion | sNDA under priority review, target action date 2027-01-28 | 8-K 0001140361-26-041097 |

## Part 3. First pass, in a scratch copy

Kept as the record of the first run. It charged royalties as a cost at the top of the
stated range, which Part 4 does not.

Method. Each asset was built the way the book builds one: Sanofi's company cost rows
copied from an existing Sanofi small molecule, the product rows from the facts above,
dollars converted at the book's own reference rate of 1.0935 per euro, and royalties
added to other costs (15.75% for Brinsupri at the top of the stated range, 4.5% for
Arikayce). The assets, their approvals and their patents were written to a scratch copy
of the book, and `fair_value.company` was asked for Sanofi.

Two cases:

- Floor. Arikayce on FY2025 grown at the nine-month rate of 7.7%, fading. Brinsupri held
  flat at its 2026 run rate of $1,317mm, the convention for a launch with no ceiling.
  TPIP as a launch at the management peak, launching 2030, at the published Phase 3
  cardiovascular rate of 45.6%.
- Management peaks. Arikayce to $1bn and Brinsupri to $7bn, each by 2034, the rate
  solved to arrive there. TPIP unchanged.

| | Floor | Management peaks |
|---|---|---|
| Arikayce, rNPV | EUR 843mm | EUR 1,281mm |
| Brinsupri, rNPV | EUR 1,078mm | EUR 3,873mm |
| TPIP, rNPV | EUR 893mm | EUR 893mm |
| Sanofi fair value per ADR, before | $67.01 | $67.01 |
| Sanofi fair value per ADR, with Insmed held | $68.32 | $70.49 |
| Added per ADR, gross | $1.31 | $3.48 |
| Price paid per ADR | $16.81 | $16.81 |
| Net of the price paid | -$15.50 | -$13.33 |
| Fair value net of the price | $51.51 | $53.68 |

The price per ADR is $41.0bn over the 2,439mm ADRs the book's own divisor implies.
The book's rule for a pending deal keeps the price out of the valuation, so the middle
rows are what the book would print and the last two are the arithmetic beside it.

### What would have to be true for the price to be covered

The three assets at the management peaks, in $mm, under looser assumptions:

| Costs charged | Stated patents, 45.6% | Longest case |
|---|---|---|
| Sanofi's full cost ratios, the book's convention | 7,081, 17% of the price | 12,250, 30% |
| No added R&D charge | 13,269, 32% | 22,441, 55% |
| No added R&D or SG&A | 20,797, 51% | 34,836, 85% |
| Cost of goods, royalties and tax only | 25,911, 63% | 43,258, 106% |

The longest case is exclusivity to 2039 for Brinsupri (a full patent term extension)
and 2041 for TPIP (the pending patents issue), TPIP at the respiratory rate of 61.6%,
and Brinsupri at its peak by 2031.

So the price is covered only if every management peak is met, every exclusivity runs
to its longest date, and the revenue carries no selling, research or overhead cost at
all. Three conventions drive the gap, in this order:

1. Cost. The book charges an acquired product the acquirer's whole cost structure:
   68.6% of revenue for Sanofi before royalties.
2. Exclusivity. Brinsupri's compound patents end in early 2035, so a $7bn peak in 2034
   is followed by 71% erosion in a year.
3. TPIP's issued patents end in 2034, four years after a 2030 launch.

The earlier report on `claude/magical-brahmagupta-kn5sjw` reached $7.3bn for the same
assets on the book's method and a base loss of $13.93 per ADR. This run is independent
of it and lands in the same place.

## Part 4. As built, 2026-11-26

The analyst's decisions of 2026-11-26: hold the three assets in Sanofi's name while the
deal is pending, add the deal to the precedent register, and settle the two open
questions from the book's own conventions.

### What was decided

1. Cost. An acquired product carries the acquirer's cost ratios, as every product in a
   company's book does. No exception is made. No filer has published a margin or a
   synergy for the combination. Insmed's own ratios describe a company spending ahead of
   a launch: SG&A 59.5% and R&D 54.9% of revenue in the nine months to 2026-09-30. And
   Sanofi's ratios are re-struck from its filed lines each year, so they describe the
   combined company once Insmed is consolidated.
2. Brinsupri. The published peak with the book's measured time to reach one. Insmed's
   "more than $7 billion" is taken at its lower bound. It carries no year, so the year
   is the launch year plus the nine years the average launch takes to peak
   (`data/launch_ramp.csv`, 41 products): 2034. The growth rate is solved to arrive
   there, 42.3% fading to nought. The flat run rate was rejected as the base because a
   named, dated peak exists, which is the case the floor convention is not for.
3. Royalties follow the book's rule: netted through the economics share at the bottom
   of the stated range. 7% for AstraZeneca on Brinsupri, 4% for PARI on Arikayce.

### What was built

- `data/pending_acquisitions.csv`: three rows, one an asset.
- `backend/acquired_sponsors.py`: a pending row now tells the trial and approval fetchers
  to read the target as the acquirer's. Before this the only route was a headline the
  deals table trusted, and for this deal it held a rumour and a counterparty parsed as
  "Is Just What". That phrase is now refused as a company name.
- `data/loe_link.csv`: the two NDAs, so the Orange Book attaches their patents.
- `data/disclosed_loe.csv`: TPIP's issued compound patents, 2034-10-24.
- `data/assumptions/`: `sny_brinsupri.csv`, `sny_arikayce_kit.csv`,
  `sny_treprostinil_palmitil.csv`.
- `data/precedent_transactions.csv`: Sanofi and Insmed, $40,398mm of enterprise value on
  $1,520mm of trailing revenue, 26.6 times.

### What arrived, on a local copy of the 2026-11-26 book

Sanofi's trials, approvals and labels were fetched again with the pending rows in place,
then the Orange Book, then the seeds.

- Arikayce Kit (NDA207356, approved 2018-09-28) and Brinsupri (NDA217673, approved
  2025-08-12), created by the approvals fetch.
- Treprostinil Palmitil, derived from eight Insmed studies now filed under Sanofi, four
  of them Phase 3. The engine placed its odds itself: 45.5%, the published Phase 3
  cardiovascular rate.
- Patents from the Orange Book: Brinsupri's drug substance patent 9,522,894 to
  2035-03-12; Arikayce's latest to 2035-05-15.

| Asset | rNPV, Sanofi's share | Per ADR | Peak | Exclusivity |
|---|---|---|---|---|
| Brinsupri | EUR 7,219mm | $3.24 | EUR 6,401mm in 2034 | 2035, drug substance patent |
| Arikayce Kit | EUR 1,113mm | $0.50 | EUR 600mm in 2035 | 2035, patent |
| Treprostinil Palmitil | EUR 1,010mm | $0.45 | EUR 5,487mm in 2039 | 2034, issued compound patents |
| Together | EUR 9,342mm | $4.19 | | |

| Sanofi, per ADR | |
|---|---|
| Fair value before | $67.01 |
| Fair value with Insmed held | $71.34 |
| Range | $62.62 to $82.60 |
| Price paid, not in the valuation | $16.81 |
| Fair value less the price paid | $54.53 |
| Close of 2026-11-25 | $54.39 |

The three assets are $10.2bn, a quarter of the $41.0bn paid.

### What would have to be true, on the built assets

| Costs charged | Share of the price covered |
|---|---|
| Sanofi's full cost ratios, as built | 25% |
| No added R&D charge | 39% |
| No added R&D or SG&A | 56% |
| Cost of goods, royalty and tax only | 68% |
| As built, with Brinsupri to 2039 and TPIP to 2041 | 35% |
| Cost of goods, royalty and tax only, and those longer dates | 96% |

### Two things the conventions hide

- The royalty. The economics share takes 7% off Brinsupri's value. A 7% royalty charged
  on sales takes 16% off at Sanofi's margins, and a mid-teens royalty 44%. The book nets
  every royalty this way; Brinsupri is the largest product it applies to.
- The precedents lens. With this deal it reads thirteen transactions. For Sanofi its
  midpoint moves from $120.28 to $126.16 per ADR. It moves for every company the lens
  covers.

### After merging

The assets arrive at the next daily refresh. The Orange Book is read weekly, and until
it is read Brinsupri would carry the default exclusivity of fourteen years from
approval, 2039, and be overstated. Run the refresh workflow once with `force_all` to
read everything at once.

The rows come out when Insmed files its Item 2.01, or if the deal breaks.

## Limits

- Sanofi's cost ratios stand in for Insmed's. Insmed's own cost of product revenues was
  15.4% of revenue in the nine months to September 2026.
- No synergy, financing cost or tax effect of the debt is modelled. Sanofi has not
  quantified any.
- TPIP is valued from a management peak at a base rate, not from patients and price.
- Insmed's earlier-stage programmes are given no value.
- The scratch assets carry no route, so Arikayce and TPIP erode at the oral rate after
  their patents end. The effect is small.
