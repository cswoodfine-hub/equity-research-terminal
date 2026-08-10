# Roadmap: from state machine to forecasting tool

The terminal knows what is (filings, approvals, trials, revenue history) and what changed
(the diff engine). An analyst spends most of the day on the half it does not do: the
forward half. The gap, in order, is forecasts, consensus, catalysts with stakes, and
readout context. That order is the roadmap.

Source: a call on 2026-08-06 with a sell-side biopharma research ED covering EMEA large
caps, plus supporting detail from a second contact. The conventions below are theirs, not
inferred.

## The conventions the builds have to match

- Everything is relative to consensus. The question at a readout is never "is this good
  data" but "is this better than what is already priced".
- Probability of success ramps 20% to 100% across phases; a Phase 3 asset sits in 50 to
  80%. Models carry Phase 2 and Phase 3 only. Phase 1 goes in only for a biotech small
  enough that one asset moves the name.
- FX is an explicit line. European pharma reports in dollars or sells into the US.
- Uptake is gated by coverage, step-through, severity ordering and how it is paid for. A
  one-time therapy depletes its prevalent pool and then runs at incidence, which is why
  Zolgensma plateaued.
- Geography drives erosion. Semaglutide goes generic in India and China before the US, and
  Chinese generic makers cannot easily launch into western markets.
- The forecast is a DCF rolling into a 12-month forward price target that deliberately
  ignores short-term noise.

## Build 1: drug-level revenue forecasting

A forecast object per drug: addressable population, penetration as an S-curve with
adjustable steepness, net price after a gross-to-net haircut, geography split (US, EU, RoW
at minimum, because pricing and erosion differ), and an FX assumption per region.

- LOE-triggered erosion as a parameterised decay, small-molecule cliff against the slower
  biosimilar shape, start date from the exclusivity map.
- One-time therapy mode: prevalent pool depletion into an incidence-only run rate.
- PoS weighting by phase, with the phase-transition base rates surfaced and editable
  rather than buried.

Done when the CASGEVY model is rebuilt in-terminal in an afternoon rather than a
spreadsheet-week, and any drug rolls up to company revenue.

## Build 3: catalysts with stakes attached

The calendar already exists. The upgrade is consequence: forecast revenue under success
against failure, the PoS step the event would trigger, and therefore the modelled value
swing, per share where share count is loaded. Rank by dollars at stake rather than by
date; that is the difference between a diary and a research tool. A one-click resolve
updates PoS and reflows the forecast while preserving the pre-event snapshot.

## Build 2: consensus layer

Company guidance from transcripts and releases as management consensus, public analyst
price targets and estimates where visible, manual columns for anything gated. The value is
not the data but the delta view: mine against guidance against street, per drug and per
company, divergences ranked.

## Build 4: readout context pack

Per indication, every drug approved or in Phase 2/3 by modality, with headline efficacy
and safety where extractable. A comparison table the analyst fills where extraction fails.
The no-fabrication rule holds: blank beats guessed. Output is the "what is the bar"
one-pager for an upcoming readout.

## Build 5: the quarterly loop

Preview, actual, revision per company. Guidance against forecast going in, actuals on the
day, variance decomposed into volume, price and FX (which is why FX sits in Build 1), and
the revision logged with a timestamped reasoning note. Over quarters this becomes a track
record of forecast error.

## Order, and what the database already supports

Order is 1, 3, 2, 4, 5. The forecast object unlocks everything. Catalysts with stakes is
the highest-leverage differentiator and mostly reuses Build 1. Consensus can start as
manual columns. The context pack is scope-heavy. The quarterly loop only pays once
quarters have passed.

Checked against the live database on 2026-08-10.

Already present: `asset_revenue` 712 rows over 301 assets; `exclusivities` 2,788 rows with
expiry, region, protection type and patent kind, plus `biologic_loe`; `assets` carrying
`modality`, which is what picks the erosion shape; `fx_rates` from the ECB; `drug_demand`
from CMS as the nearest free stand-in for IQVIA; trial phases for the PoS ramp; and
`WeightedAverageDilutedShares`, so per-share value swings in Build 3 need no new source.

Two gaps decide the shape of Build 1. Both are settled below.

1. **No epidemiology source.** Addressable population, prevalence and incidence per
   indication have no free feed. Resolved: they are analyst inputs, not fetched data. See
   "The assumption layer".
2. **`asset_indications` is empty.** CLAUDE.md calls the asset-indication pair the unit of
   analysis and says every pipeline view builds off it. Build 1 needs population per
   indication and Build 4 is entirely indication-scoped, so this table is a prerequisite
   rather than a detail. See "Assigning asset indications".

Build 2 is cheaper than the order above implies: `consensus_estimates` already exists as a
table and `FMP_API_KEY` is already set, which buys company-level consensus EPS and revenue
immediately. It does not buy drug-level consensus, which is what the delta view wants, so
the ordering stands for the full ambition.

## The assumption layer

Taken from the CASGEVY DCF model, which is the reference implementation of how these
numbers are meant to be held.

Every assumption there is a row of **label, value, source note**, and the analyst owns all
of them: "Source: CDC / FDA" against SCD prevalence, "Source: NIH / literature" against
TDT, "Damodaran US ERP estimate" against the equity risk premium, "Source: ASH/Blood
Advances" against lifetime standard-of-care cost. That is the no-fabrication rule already
satisfied, by curation with provenance rather than by a feed.

So the terminal holds an `assumptions` table keyed on asset and indication, carrying key,
value, unit, source, note, as-of date and scenario, with scenario covering the bear, base
and bull columns the model already runs. It imports from and exports to the workbook, so
the analyst keeps vetting numbers in Excel and the terminal reads them rather than
replacing them.

The population build follows the model's shape: prevalence, eligible percentage,
addressable patients, then ex-US as a multiple of US, per indication.

### The one thing the terminal should do that the spreadsheet cannot

In the model, new patient infusions are typed by hand: 5, 45, 120, 200, 320, 450, 550,
600, 550, 480, 400, 350. The curve rises to a peak in 2031 and then falls away. That hump
is prevalent-pool depletion, drawn freehand.

Meanwhile the Assumptions sheet computes a total global addressable pool of about 46,000
(SCD 16,000 US eligible at 2.5x for ex-US, TDT 1,500 at 4x) and the revenue build never
references it. The pool is a sanity check, not a constraint.

Making it an identity is what Build 1 adds:

```
new(t)            = min(capacity(t), penetration(t) x [pool_remaining(t) + incidence(t)])
pool_remaining(t+1) = pool_remaining(t) + incidence(t) - new(t)
```

The hump then falls out of the arithmetic instead of being drawn, the tail converges on
incidence times penetration by construction, and no forecast can treat more patients than
exist. That is the Zolgensma shape derived rather than asserted, and it is the dissertation
argument made executable.

It needs one input the model does not currently carry: **incidence**. The workbook holds
prevalence only. Incidence per indication becomes a required assumption row.

### Uptake is evidenced, never estimated

A penetration curve is not one assumption. It is a demand funnel and a supply ceiling, and
the forecast takes the lower of the two:

```
demand(t)   = prevalence x diagnosed% x clinically eligible% x referred% x payer approved% x accepts treatment%
capacity(t) = centres(t) x slots per centre per year x utilisation%     (or manufacturing lots)
new(t)      = min(demand(t), capacity(t))
```

Which side binds is a property of the modality, and so is where the evidence comes from.
Two regimes, and the terminal already holds the evidence for both.

**High-volume modalities: fit the curve to realised analogues.** `drug_demand` carries CMS
Part B and Part D for 688 brands over 2020 to 2024, with 565 of them holding the full five
years, and `total_beneficiaries` is an observed patient count rather than a spend figure.
84 brands climb threefold or more inside that window, 40 small molecule and 37 biologic,
which is a usable sample of realised launch ramps:

```
Breztri Aerosphere   4,931 -> 82,611 -> 163,878 -> 257,853 -> 367,055
Kerendia             1,908 -> 25,931 ->  63,625 ->  88,208
Qulipta                826 -> 12,185 ->  25,190 ->  45,046
Opzelura               382 ->  6,243 ->  14,085 ->  19,146
```

So S-curve steepness is fitted to comparable launches in the same modality and setting and
shown as a distribution, not chosen. The analyst moves the curve within an evidenced range
and the range itself has a citation.

Its limits have to be stated wherever it is used. It is Medicare only, so it is a poor
proxy for any young or Medicaid-weighted population, which includes sickle cell disease
and therefore CASGEVY itself. The window is five years, so only launches from roughly 2019
to 2022 show a full early ramp. And no cell or gene therapy appears in the ramp sample at
all, which is itself the finding: those products are not claims-visible and are not
demand-limited.

**Cell and gene therapy: count the centres.** Here capacity binds for years after launch,
and the constraint is disclosed rather than inferred. Across the filings already stored,
47 mention authorised treatment centres, 39 apheresis and 28 cell collection. What they
say is specific enough to model:

- Iovance, August 2026: Amtagvi "available at more than 95 authorized treatment centers".
- Abeona names each activation with its date, so ZEVASKYN's centre count is a time series
  rather than a snapshot: NewYork-Presbyterian/Columbia on 2 April 2026, Children's
  Hospital of Philadelphia on 11 May 2026.
- Beam gives throughput per patient: a median of one stem cell collection cycle (range 1
  to 5) over a median of three collection days (range 1 to 13).
- Gilead names apheresis centre certification as a live constraint on commercialisation.

That gives centres(t) as a countable series from filings, slots per centre from disclosed
collection throughput, and a manufacturing lag between collection and infusion. Companies
disclose cell collections separately from infusions, which makes collections a leading
indicator of revenue one lag ahead.

**The factors that are neither, and must be curated with a source.** Acceptance rate is the
one the CASGEVY model buries inside its freehand curve: myeloablative busulfan
conditioning, infertility risk and weeks of inpatient stay mean a materially eligible
patient may still decline. Diagnosis rate is another, and for some indications it is
public infrastructure rather than literature: newborn screening panel adoption is
state-by-state and published, and it sets what share of incidence is even captured.

Every factor above is a row in `assumptions` with its own source, so a curve can be
audited back to the sentence it came from.

### Calibration is a first-class output, not a footnote

The model already compares itself to reported revenue: 2024 modelled 9.0 against 10.0
reported, 2025 modelled 115.2 against 95.0, so the forecast is running about 21% hot on
the most recent year. The block computes the variance and nothing consumes it. In the
terminal that variance is an output from day one rather than waiting for Build 5.

## Geography: US bottom-up, ex-US as an observed ratio

Decided 2026-08-10. The forecast does not model ex-US patients. It models the US patient
funnel in full and takes ex-US as a revenue ratio, because companies report that ratio and
nobody has to defend it. Gilead prints Biktarvy as U.S. 2,573, Europe 437, Rest of World
352 every quarter; that is the US/EU/RoW split, sourced.

`revenue_earnings.read_geography_blocks` already parses those blocks and then sums them to
worldwide, because `asset_revenue` has no region column. So the work is to add `region` and
stop discarding what is already read. `asset_economics.region` and
`asset_indications.region` already exist and are empty, so the schema anticipated this.

Region is a dimension from day one, with the US the only populated region in v1. CASGEVY is
a US launch story, so the first milestone does not slip, and ex-US later arrives by filling
a column rather than reshaping a schema.

US-only was considered and rejected. Seven of the seventy companies are non-US domiciled
(AZN, GSK, ROG, NVS, SNY, NVO, BAYN) and those are the European large caps the work is
aimed at. US-only would also delete two conventions taken from the analyst call: FX as an
explicit line only exists if there are non-USD geographies, and the erosion-by-geography
argument, semaglutide going generic in India and China before the US, is the whole point.

For a pre-launch asset with no reported ratio, use the observed distribution of US:ex-US
ratios across analogues of the same modality and area, labelled as such.

## Loss of exclusivity

**US is already the rule.** `loe.effective()` lets the drug-substance patent set the date
even where a use patent runs longer, because a molecule patent gates a generic outright
while a method-of-use patent covers one indication and can be carved out of a generic's
label. No policy change needed.

**The binding problem is coverage.** Of 1,696 marketed assets, 601 (35%) carry any
exclusivity row and only **216 (13%) carry a drug-substance patent**. 51 have a Purple Book
row against 347 marketed biologics. So the rule answers a small fraction of the book, and
fixing the asset-to-Orange-Book match matters more than any refinement to the rule.

**Ex-US comes from statute, not from a peer group.** EU loss of exclusivity is the later of
the patent plus its SPC, capped at 15 years from first EU marketing authorisation
(Reg. 469/2009), and the 8 years data plus 2 years market exclusivity rule, plus one more
year for a significant new indication. That is cited to a regulation rather than defended
with an analogue set, and it is the pattern the codebase already uses: `merged_loe` applies
the BPCIA 12-year biologic floor and labels the basis "statutory floor (12y)".

It needs the first EU marketing authorisation date, which is not held: `approvals.region`
is 100% US. Two free routes, the EMA EPAR medicines table, and the press feed, which
already catches EU approvals and CHMP opinions and dates an opinion about two months ahead
of the decision. A modality and indication analogue remains the labelled fallback where no
EU date exists, expressed as an offset from the US date, and it can only be calibrated once
real EU dates are in.

## Sensitivity on LOE timing, and why it is not optional

Neither axis of post-LOE value can be pinned down from owned data, so the model's output
here is a range and the sensitivity grid is the deliverable rather than an appendix.

- **The date** is unknown for 87% of marketed assets in the US and is statutory-inferred
  rather than observed ex-US.
- **The erosion steepness** cannot currently be evidenced from the CMS series at all.
  Filtering `drug_demand` to brands whose LOE year falls inside the 2020 to 2024 window
  with data either side leaves **eleven observations, every one a biologic, and one of them
  Prevnar 13, which fell because Prevnar 20 replaced it rather than because it lost
  exclusivity**. Unfiltered decline is not erosion: that wider sample is full of safety
  withdrawals (Chantix), franchise switches, channel shifts (Narcan going OTC) and coding
  artefacts, and its medians are not a measurement of anything.

So erosion steepness is a curated assumption with a literature citation, cut by modality,
until a longer window makes it observable. The grid is LOE year against year-one erosion,
reporting rNPV and the share of NPV at risk, with the basis of each axis printed beside it:
substance patent, statutory floor, or assumed.

## Assigning asset indications

The data needed is already in the database. `trials` holds 3,184 rows of which **3,159
(99%) carry both an `asset_id` and a `conditions` list**, and `completed_trials` adds
6,949 more. So asset to indication is a derivation, not a collection problem.

The obstacle is vocabulary. `trials.conditions` stores
`protocolSection.conditionsModule.conditions`, which is the sponsor's free text, and it
yields 2,061 distinct strings for 3,184 trials. Two failure modes, both visible in the
counts:

- **Synonyms split one indication.** "Non-Small Cell Lung Cancer" (50), "Carcinoma,
  Non-Small-Cell Lung" (49) and "Non-small Cell Lung Cancer" (43) are one indication in
  three spellings, 142 trials scattered across them.
- **Non-indications.** "Healthy" (65), "Healthy Volunteers" (46) and "Healthy
  Participants" (30) are 141 Phase 1 studies with no indication at all.

The fix is the controlled vocabulary ClinicalTrials.gov already derives and the fetcher
does not yet request: `derivedSection.conditionBrowseModule.meshes`, which returns MeSH
descriptors with stable ids. One id collapses the three lung spellings. Take `meshes`
only, never the ancestor branches, which is where terms like "Physiological Effects of
Drugs" come from and which would file every oncology asset under neoplasms.

Plan:

1. Add `mesh_id` to `indications` and pull the browse module in the trials fetcher. The
   MeSH descriptor becomes the canonical indication; the sponsor's free text maps to it.
2. Populate `asset_indications` per (asset, indication): phase as the maximum across that
   asset's trials in that indication, development status from overall status,
   `first_seen_phase` from the earliest snapshot so phase advances are diffable.
3. `is_lead` from highest phase, breaking ties on enrolment.
4. A curated override table for misses, following the `trial_asset_map` pattern already
   established for the harder asset mapping problem.
5. Marketed assets take approved indications from their label via the existing DailyMed
   route rather than from trials, since an approved indication is a fact and a trial
   condition is an intention.

Drop healthy-volunteer conditions before writing rows: they are a study population, not
an indication.

This is deep-block work, one block at a time. It does not jump the queue.
