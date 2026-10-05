# Medicare growth split

Build 4 of the commercial-analytics audit (5 Oct 2026). The user asked for "a Medicare split of each marketed brand's growth into new patients, refills per patient and price, beside its growth rate". This is a read-only lens over the CMS series already in `drug_demand`.
- No migration, no new source, no fetcher change.
- No assumption, rNPV, per-share value, range, scorecard rank or rating moves.
- A direction that disagrees with the model is a flag. It feeds nothing.
- Key insights is unchanged. Revision 4 is a one-screen layout and the user's steer is fewer words.

## 1. The identity

CMS Spending by Drug gives, per drug, part and calendar year, total spending S, claims C and distinct beneficiaries B. Spending is exactly S = B x (C / B) x (S / C), so a year's change multiplies through three factors:

| Factor | Formula | Part D name | Part B name |
|---|---|---|---|
| Patients | B1/B0 - 1 | Patients | Patients |
| Use per patient | (C1/B1)/(C0/B0) - 1 | Fills per patient | Claims per patient |
| Price | (S1/C1)/(S0/C0) - 1 | Cost per fill | Cost per claim |

(1 + patients)(1 + use)(1 + price) = 1 + spend growth, to floating-point rounding.
- **Points.** Each factor is also given in points of spend growth by log share: pts_f = g ln(1+f) / ln(1+g). The logs of the factors add to the log of the whole, so the points add exactly to g. A flat year (|ln(1+g)| < 1e-12) takes each factor's own log instead.
- **Span.** 2020 to 2024 uses CAGRs read on the end years only. The nth root of a product is the product of the nth roots, so the CAGRs multiply the same way.
- **Cross-check.** Price per claim splits into units per claim x cost per unit. That exposes a 30-day to 90-day fill shift in Part D and a dose change in Part B. The headline price stays per claim, as the user asked, with per unit shown beside it.
- **Two parts.** Each part is split on its own. A brand total is given in points only, each part weighted by its prior-year spend, so sum w_p g_p is the brand's spend growth exactly. Beneficiaries are never added across parts: a patient can be in both.
- **A missing patient count.** The step splits into claims and price only. Nothing missing is ever read as zero.
- **A minor part.** A part under 5% of the brand's latest Medicare spend (`MATERIAL_PART_SHARE`) is reported, not split.

Measured on a copy of the book (5 Oct 2026): every one of the 3,699 year steps on file splits, and the largest error in either the product or the sum of points is 2.3e-13.

## 2. What CMS's own documents confirm

Every label clause was checked live on 5 Oct 2026 against the data dictionaries (`/data-api/v1/dataset/{id}/dictionary`), the catalogue (`data.json`) and the methodology PDFs the dataset's `/resources` list links.

| Claim | Source | Used |
|---|---|---|
| Part D Tot_Clms counts prescription fills, original and refills | Part D dictionary | "Fills per patient", "Cost per fill" |
| Part D spending is gross drug cost (ingredient, dispensing fee, tax, vaccine fee), plan plus patient, with no manufacturer rebates or other price concessions | Part D methodology, June 2026 | "Part D is gross cost before manufacturer rebates" |
| Part D covers Part D enrollees, about 81% of Medicare beneficiaries | Part D methodology | doc only |
| Part D '*' means the cost per unit blends routes of administration priced differently | Part D dictionary | the Part D footnote |
| Part B Tot_Clms is "number of claims" | Part B dictionary | "Claims per patient", "Cost per claim" |
| Part B covers fee-for-service beneficiaries only; Medicare Advantage is excluded | Part B dictionary and methodology | "Part B is fee-for-service only" |
| Part B spending is Medicare payment plus deductible plus coinsurance | Part B methodology | doc only |
| Most Part B payments are based on ASP; ASP payment amounts include the statutory 6% add-on | Part B methodology, dictionary (Avg_DY24_ASP_Price) | "paid mostly at average sales price plus 6%" |
| Part B '*' means several brand or generic names under one HCPCS code; '**' means names unavailable | Part B dictionary | the Part B footnote (Prolia's J0897 also bills Xgeva) |
| Beneficiaries are unique beneficiaries using the drug in the year | both dictionaries (Avg_Spnd_Per_Bene) | "Patients are distinct beneficiaries ... net additions, not new starts" |
| Drugs under 11 claims are dropped; earlier years under 11 claims are redacted | both methodologies | doc only |
| Both annual files were modified 25 Jun 2026 and carry calendar 2024 | `data.json` | the label's CMS year |

Left out, because CMS's documents do not say it:
- **A 2024 point-of-sale break in Part D.** The Part D median cost per fill turned from +5.7% (2022 to 2023) to -2.6% (2023 to 2024) while Part B shows no break. The methodology says nothing about pharmacy price concessions at the point of sale under CMS-4192-F. There is no `point_of_sale_2024` flag; the tracked-brand baseline carries the break instead.
- **Why Part D patients jumped in 2024.** The median rose 9.7% against 0.8% to 5.1% in earlier years. The cause is not stated, so it is not named.
- **"Already net of most discounts" for Part B.** Not in the methodology.
- **A Part B claim as one administration.** CMS says "number of claims", so the factor is called claims per patient, not administrations per patient. The design had "administrations"; this is the one wording change.
- **Why a patient count is blank.** The rows show blanks; the methodology's suppression rule is about claims. The note says "CMS gives no patient count", not "suppressed".

The Prescribers files that build 5 adds carry a different Eliquis patient count (4,423,497 against 4,424,796 here). Each view names its file, and the two files are never mixed in one identity.

## 3. Labels

The label line, on every view: "Medicare only. Part D is gross cost before manufacturer rebates; Part B is fee-for-service only, paid mostly at average sales price plus 6%. CMS calendar 2024, 1 year behind the FY2025 filing." The lag is computed per asset from its latest FY revenue on file.

Beside it:
- "Patients are distinct beneficiaries on the drug during the year, so their growth is net additions, not new starts."
- The gap column: US reported growth less Medicare spend growth, "not explained by Medicare gross spend: net price, other payers, inventory". It is never called a net price. It is shown in dollars only: a growth rate in another currency carries the exchange rate, and the book has no FX history before 24 Jul 2026.
- A brand CMS reports in both parts is read from its main part, and every line says so: the sentence and the flag say "Medicare Part B patients" and "Part B spend", the gap is taken against the brand's spend across all parts, and the both-parts total in points says "use per patient" and "price", since a Part D fill and a Part B claim are not one thing. Prolia: Part B patients +3.0% while Part D's rose 11.5% and the brand's spend 11.8%.

## 4. Flags

Attached per step as `{code, words}`. Only `containers_changed` makes a step not like for like: its patient segments are hatched and it stays out of the baseline.

| Code | When | Words |
|---|---|---|
| containers_changed | the container count or name set differs between the years | CMS changed the containers it lists (n to m), so patient counts are not like for like |
| name_changed | one container both years, renamed | CMS renamed the row from a to b |
| containers_summed | more than one container in either year | patients summed across containers, an upper bound |
| beneficiaries_suppressed | a patient count is blank in either year | CMS gives no patient count for one of the two years, so only claims and price are split |
| partial_suppression | the fetcher's note records blank container counts | CMS gives no patient count for some containers, so the patient total is short |
| footnoted_name | '*' on the CMS name | Part B: CMS reports this billing code, which can carry other brands. Part D: CMS marks this drug: its cost per unit blends routes of administration priced differently |
| fill_size_moved | abs(ln(1 + units per claim)) >= 0.05 | units per fill moved x%, so read cost per unit |
| units_blend | more than one container | cost per unit blends the containers' units |
| launch_part_year | the step starts in the brand's first CMS year, after the file's first year | first year in Medicare, a part year: approved {date}; or first year in the CMS file, though approved {date} |
| negotiated_price | the brand has a negotiated price (ira.selected), on the latest step | Medicare's negotiated price applies from {ipay}, so the price factor breaks then |

## 5. The tracked-brand baseline

Every step is set against the median of tracked brands for the same part and year pair. The programme moves under every brand, so a brand's own factor has to be read against it.
- In: one-year steps whose prior-year spend is at least $50mm (`BASELINE_MIN_SPEND`), with both patient counts and no container change.
- A CMS row stored against two asset records counts once. There are 20 such stale duplicates (section 9). Part D 2023 to 2024 has n = 231, 234 before the duplicates are counted once; the design measured 236, a difference this build does not explain.
- Cached in-process on the table's row count and latest `fetched_at`.

Measured on the copy:

| Part, years | n | Spend | Patients | Use | Price | Per unit |
|---|---|---|---|---|---|---|
| D 2020-21 | 200 | +3.6% | +0.8% | -1.0% | +4.8% | +5.7% |
| D 2021-22 | 211 | +5.1% | +1.7% | 0.0% | +5.4% | +5.5% |
| D 2022-23 | 219 | +8.8% | +5.1% | -0.1% | +5.7% | +5.8% |
| D 2023-24 | 231 | +6.8% | +9.7% | +0.8% | -2.6% | -3.1% |
| B 2020-21 | 66 | +1.4% | +0.8% | +1.2% | +0.7% | +0.7% |
| B 2021-22 | 71 | +3.7% | +1.0% | +0.2% | +3.5% | +3.8% |
| B 2022-23 | 74 | -0.1% | -1.0% | -0.1% | +0.7% | +1.1% |
| B 2023-24 | 77 | +4.1% | +1.8% | +0.6% | +2.9% | +2.6% |

## 6. Beside the split

- **The model's growth** (`model_growth`): the base scenario's asset-level scalar, `revenue_growth_pct` for a marketed product and `franchise_growth_pct` (the pool's growth) for a franchise member, with `terminal_growth_pct` and `growth_fade_years`. It runs from the latest FY on file, else `forecast_start_year` less one. Any other mode, or no row, is None, never a number from elsewhere.
- **Reported growth** (`reported_growth`): worldwide from `asset_revenue` FY rows; the US from `regional_loe.us_series`, which applies `split()`'s rule per year (a curated row outranks fetched ones, exactly one US row must remain). Growth is in the filer's own currency and only between two years in the same unit. CMS calendar year Y pairs with FY Y only, which assumes December year ends.
- **Direction** (`direction_disagrees`): the model's growth and the latest Medicare patient growth (claims where there is no count) have opposite signs, each beyond one point (`DIRECTION_DEADBAND`).

## 7. A brand on two records

Medicare is brand level, and the CMS fetcher binds a brand to one asset. When an asset has no rows, `resolve` reads the series from another asset with the same brand name and returns `held_on` {asset_id, ticker}. Every asset sharing the brand lists the other companies in `shared_with`. Nothing is inferred about which company books the US sales.

Twelve modelled assets gain a series this way: PFE Eliquis (BMY), AMGN Enbrel (PFE), AZN Tezspire (AMGN), NVS Xolair and Lucentis (ROG), NVS Aimovig (AMGN), SNY Dupixent (REGN), MRK Reblozyl (BMY), MRK Lynparza (AZN), INCY Tabrecta (NVS), INCY Olumiant (LLY) and UTHR Adcirca (PFE).

Coverage: 251 of the 339 modelled marketed and franchise assets have their own series, and 12 more are held on another record. Together they carry $209.1bn of the $246.4bn of 2024 Medicare spend on file.

## 8. Where it lives

- `backend/demand_split.py`: pure `step`, `points`, `span`, `combine`; `_series`, `flags_for`, `baseline`, `resolve`; `model_growth`, `reported_growth`, `direction_disagrees`, `sentence`; readers `for_asset` and `company_split`.
- `GET /companies/{ticker}/forecast/{asset_id}/demand`: one asset, owner or partner (`forecast_view._accessible`), 404 otherwise. ok False with "not in the CMS files" when no record has a series.
- `GET /companies/{ticker}/demand/split`: one row per brand and part for owned and partnered assets, by latest spend, with the tracked median for the latest pair per part. 404 for an unknown ticker.
- **Forecast tab.** A "Medicare" layer between Drivers and Uptake, shown only when the asset has a series. Its own read, so a failure empties this layer alone. From the top: the label, the sentence, a flag line when the model and Medicare point opposite ways, `charts.growth_split` for the main part (a second, smaller chart only when two parts are material), then a table by year pair. The table has spend, patients, use, price and cost per unit, each with the tracked median under it, then US and worldwide reported growth for the same FY and the gap in points. A span row and the model's row ("Model from FY2025: growth +18.9% a year fading to 0.0% over 5 years") come last. Flags are numbered notes, then "held on" and "also modelled by".
- **Portfolio tab.** A fourth layer, "Medicare demand", only when the company split has rows. It has one row per brand and part: the first fifteen, then "{n} more" folded. A part under 5% of its brand is one muted row, "not split". The model's growth carries an "opposite" marker where it disagrees. The tracked medians come last, with their count and floor.
- **Fact profile.** The Medicare spend tile reads "US 2024, +13.7% YoY, patients +12.7%", patients only where the main part's step is like for like, and "in Part D" when the brand has two parts. `_profile_detail` picks the product's rows by `asset_id`.
- Two fixes in the same build: `demand.company_demand` carries `asset_id`, and `product_profile._demand` no longer sums beneficiaries across parts. It returns `parts` instead; spend and spend growth are unchanged.

## 9. Measured on a copy of the book (5 Oct 2026)

| Brand | 2024 Medicare | Spend | Patients | Use | Price (per unit) | Points | Model | FY2024 US, worldwide |
|---|---|---|---|---|---|---|---|---|
| Eliquis (BMY), D | $20.77bn | +13.7% | +12.7% | +0.8% | +0.1% (-1.1%) | 12.71 + 0.82 + 0.16 = 13.69 | +18.9% from FY2025 | none on file, +9.2% |
| Keytruda (MRK), B | $5.99bn | +10.2% | +5.5% | +0.1% | +4.3% (+3.3%) | 5.65 + 0.14 + 4.42 = 10.21 | pool +3.8% | +18.2%, +17.9%; gap +7.8 pts |
| Ozempic (NVO), D | $12.97bn | +41.1% | +33.3% | +12.8% | -6.2% (-10.0%) | 34.34 + 14.35 - 7.61 = 41.07 | -7.6%, opposite | +33.6%, +25.7% in DKK |
| Jardiance (LLY), D | $11.44bn | +29.4% | +35.1% | +3.2% | -7.2% (-6.8%) | 34.30 + 3.61 - 8.55 = 29.37 | +2.7% | -0.1%, +21.7%; gap -29.5 pts |
| Dupixent (REGN; SNY held), D | $2.49bn | +45.3% | +42.3% | +0.4% | +1.7% (+0.2%) | 42.76 + 0.53 + 2.03 = 45.32 | +20.2% | SNY: +17.2%, +22.0% in EUR |

- Eliquis 2020 to 2024: spend CAGR +20.2% = patients +13.8% x fills per patient -0.8% x cost per fill +6.6%.
- Jardiance shows why the gap is never a net price: Medicare gross spend rose 29.4% while US reported sales fell 0.1%.
- Eliquis, Ozempic and Jardiance carry the negotiated-price flag; Dupixent's patients are summed over Pen and Syringe, an upper bound.

Data issue found: 20 CMS rows sit on two asset records, stale rows from an earlier brand map. Examples are Simponi on JNJ 7043 (fetched 6 Sep) and MRK 6489, and Fiasp on NVO 591 and 6511. The baseline counts each once; the stale rows themselves are left for a cleanup outside this build.

## 10. Not in this build

- The provisional 2025 year from CMS's quarterly files, and patient bounds on summed containers. Both were declined; if taken later they need migrations 084 and 085.
- A standardised-fills factor from the Prescribers by Geography 30-day fills, which build 5 stores. It would be its own identity on its own file, never mixed with this one.
- Any Key insights clause.
