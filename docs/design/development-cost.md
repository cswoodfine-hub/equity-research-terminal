# Development cost beside rNPV

Build 1 of the gates work, 6 October 2026. The user asked for "per-phase development costs
from published benchmarks, giving the expected value at the next milestone minus the cost
of getting there", alongside the valuation: headline rNPV and the ratings unchanged, and
Sertkaya's point at its own price year.

`backend/development.py` is the engine, `data/development_costs.csv` the published figures,
and two GET routes serve it. Nothing here is written to the book and nothing feeds a value.

## 1. Why it sits beside the value and never in it

The company's R&D ratio already pays for today's trials. A marketed line's P&L charges
`rd_pct x revenue` in `forecast.fcff`, and the future pipeline grows from that same R&D
(`book_rd` in `forecast_view._future_pipeline`, taken at each pipeline part's probability
since the defect 2 fix, 7d0797c). A development cost taken off an asset's rNPV would count
the same spend twice. So the view never reaches rNPV, the sum of the parts, the 12-month
value, a rating, a break-point or fair value. `tests/test_development.py` holds the fence:
an AST scan proves none of forecast, forecast_view, assumptions, pos_granular,
company_score, breakpoints, fair_value, comps_valuation, future_pipeline, launch_timing,
company_lines or insights imports the module, and `tests/test_development_api.py` proves the
sum of the parts is identical read, unread, or with the module unimportable.

How `book_rd` itself is risked is the future pipeline's business and is not touched here.

## 2. The gate and the headline

The gate, its chance and its success leg are build 2's, from
`pos_granular.legs_for_inputs`: the gate `next_gate` names, `p_gate`, and `pos_success`.
The value "if it passes" is the same figure every view shows, npv x pos_success at the
company's share. A stated probability uses build 2's implied split (Retatrutide's 97.9%,
sac-TMT's 77.3%), never the published one.

The headline is the user's own wording:

    net = p_gate x success leg - cost to reach the gate

Because p_gate x pos_success is the probability in force, `p_gate x success leg` is today's
rNPV at the company's share, so the net is that rNPV less the cost to the gate. It breaks
even at `cost / success leg`. A gate "funds" when the net is not negative.

Where no open study at the gate's phases sits in an indication the forecast values, and
nothing has been sunk into the gate, the cost to reach it is not read. `unread` is true,
`cost`, `net`, `breakeven_p` and `funds` are None, and the basis says how many studies sit
outside. A nil there would read as a gate that costs nothing to reach and breaks even at
0%, which no source says. The values if each gate passes still read, since they rest on
later costs only; the ladder's first net, its risked cost and today's value after cost are
None with it.

## 3. The ladder, after later trial costs

Behind the headline sits the backward induction to approval over every gate in the split:
`V_k = p_(k+1) x V_(k+1) - C_(k+1)`, from the value on approval at the top. The top is the
success leg over the later gates' odds, so before later costs the first gate's value is the
success leg itself; it equals npv x share to the success leg's four-place rounding, and
taking it this way makes the reconciliation exact: today, after every stage's cost, equals
rNPV x share less the risked cost of all stages ahead (1e-15 relative across the book). Each
row reports the value if passed, the expected value at the gate, the cost, the net, the
break-even chance and whether it funds, plus a floored series in which any stage a sponsor
would not fund on these numbers is taken at nil.

## 4. The costs

| Route | When | Cost | Grade |
|---|---|---|---|
| Registry | An open study at the gate's phases, in an indication the forecast values | enrolment x Sertkaya's per-patient rate for the area and phase x the share of its run still ahead, on a straight line from its start to its primary completion | convention (rate analogue, enrolment measured, straight line convention) |
| Peer | A Phase 3 not yet registered after a Phase 2 gate, with at least 3 other assets holding Phase 3 or 2/3 studies in the same MeSH indication (trials plus completed_trials) | the median of those peers' total Phase 3 enrolment x the area's Phase 3 per-patient rate, spread over Sertkaya's Phase 3 duration for the area from the Phase 2 readout | analogue |
| Benchmark | The same with fewer than 3 peers | Sertkaya's Phase 3 out-of-pocket programme cost for the area, over the same duration | analogue |
| Seamless | The Phase 2 gate study is a Phase 2/3 in that indication | nil: the study already carries its Phase 3 | |
| Review | The FDA decision | Sertkaya's $2.6mm, spent as the review starts | analogue |

- Phase 2 studies take the Phase 2 rate; Phase 3 and Phase 2/3 the Phase 3 rate. Phase 1 is
  never counted.
- Money already spent is sunk: a study past its primary completion has nothing ahead, so a
  gate study that is reading out costs nothing to reach. A study with no start date, or not
  started, has all of its run ahead.
- A study that has read out (a resolved readout catalyst) is skipped, as `next_gate` skips
  it.
- Only studies in an indication the forecast values count, by the same MeSH test every
  gate view uses. A study in another disease (`other`), or one whose MeSH terms match no
  indication (`unmapped`), is listed under `outside` with its remaining cost as one separate
  figure for the whole programme, never in the headline. At an FDA gate the still-open
  Phase 3s are listed there as "not needed for this gate", and a Phase 2 run beside a
  Phase 3 or FDA gate, in any indication, as "beside the gate, not on the path to it". So
  every open Phase 2 and 3 study of the asset is either counted (headline or ladder) or in
  that figure; a book guard holds it.
- At the FDA gate the review is the only cost to reach it.

### Money as the valuation counts it

- Converted from US dollars into the owner's reporting currency at the latest ECB rate
  (`forecast_view.price_unit_rate`).
- After tax at the asset's `tax_rate` where the company bearing the cost is on the pharma
  engine (`engines.assign(conn, company_id, revenue)`), where the deduction can be used now;
  pre-tax elsewhere. That is the owner on its own view and a partner on the partner's: only
  Casgevy, a marketed product, has a partner row today, so no pipeline line differs yet.
- At the company's economics share; a partner's cost is assumed to follow its share of the
  economics. A deal in which the partner funds development differently will be wrong until a
  curated cost-share row exists.
- Discounted at the asset's WACC to 31 December of the valuation year, the anchor rNPV is
  discounted to (`forecast.periods_from`), spending evenly over each window.
- Per share through `forecast_view._diluted_shares`, as the verdict's gate is.

## 5. Sources and price years

- Point: Sertkaya A, Beleche T, Jessup A, Sommers BD. Costs of Drug Development and Research
  and Development Intensity in the US, 2000-2018. JAMA Netw Open 2024;7(6):e2415445,
  doi:10.1001/jamanetworkopen.2024.15445, PMC11214120. Table 1, 2018 dollars, all 14 columns
  read from the PMC full-text XML on 6 October 2026 and saved as
  `backend/tests/fixtures/sertkaya2024_table1.xml`; a test pins every transcribed figure
  against it.
- High bound: DiMasi JA, Grabowski HG, Hansen RW. J Health Econ 2016;47:20-33,
  doi:10.1016/j.jhealeco.2016.01.012, Table 2, 2013 dollars on the GDP implicit price
  deflator: Phase II 58.6 (n 78), Phase III 255.4 (n 42), the mean cost per compound entering
  the phase. It includes long-term animal testing run during the clinical phases and the
  cost of compounds that fail within the phase. It is applied as its ratio to Sertkaya's All
  row (Phase 2 2.79x, Phase 3 2.86x) to each stage, the review unchanged.
- No inflation step. The book holds no price index (`market_rates` carries rates only), so
  every figure is labelled in its own price year and the DiMasi ratio, 2013 against 2018
  dollars, is if anything low. Restating needs a historical series such as FRED GDPDEF in a
  table of its own, which waits on a yes.
- Sertkaya's printed out-of-pocket rows are stored as printed and never recomputed:
  oncology Phase 3 is 93,145 x 293 x 1.63 trials per application (supplement eTable 3) =
  $44.5mm against 37.7 printed, while the All row reproduces (89.1 against 89.3).

The area map, the model's word to Sertkaya's:

| Model | Sertkaya |
|---|---|
| Oncology | Oncology |
| Immunology and inflammation | Immunomodulation |
| Metabolic | Endocrine, a judgement: Sertkaya has no metabolic class |
| Neuroscience | Central nervous system |
| Cardiovascular | Cardiovascular |
| Infectious disease | Anti-infective |
| Respiratory | Respiratory system |
| Haematology | Hematology |
| Urology | Genitourinary system |
| Ophthalmology | Ophthalmology |
| Renal and hepatic, Healthy volunteers, Other, none | All |

## 6. Refusals

Returned as `{ok: false, reason, why}`, never as a guess (`development.REFUSALS`):

| Reason | Meaning |
|---|---|
| marketed | A marketed product has no gate ahead |
| no_forecast | The forecast does not build |
| no_gate_split | The probability is not placed by gate: pos_granular places big pharma Phase 2 and 3 assets only |
| no_gate | Nil probability in force, or the Phase 3 read out negative |
| no_indication | No modelled indication carries a MeSH descriptor, so no study can be counted |
| stated_legs | Stated success and failure legs on file; the view reads derived gates only |
| vaccine | /vaccin/ in the asset's names or the gate study's title: neither source has a vaccine class |
| no_fx_rate | No exchange rate for the owner's currency |
| cost_table | The cost file cannot be read |

## 7. Routes

- `GET /companies/{ticker}/forecast/{asset_id}/development`: the asset's gate, ladder,
  stages with every study, the outside figure, the 12-month named spend and the sources.
  404 for an unknown ticker or an asset the company cannot see (the verdict's
  `_accessible` rule).
- `GET /companies/{ticker}/development`: every counted pipeline line, `failing` first then
  `rows` by net per share, `uncosted` (the cost to the gate is not read), `refused`, and
  `reconciliation`: the registered studies' spend in
  the next 12 months at the company's share, pre-tax and unrisked, against the R&D the book
  charges its marketed lines and streams in the first forecast year. Off the `/forecast/`
  prefix so it cannot collide with `/forecast/{asset_id}`.

Both are plain GETs, so the response cache keeps them against a stamp that includes the
day, which matters because each study's share ahead moves daily.

## 8. What it says on the book (copy of 6 October 2026)

- 201 of 213 counted pipeline lines read. Refused: 5 `no_gate_split` (MRNA mRNA-4157, UTHR
  Ralinepag and Oral Treprostinil, VKTX VK2735, VRTX VX-147: owners off the pharma engine or
  unplaced), 4 `vaccine` (GSK varicella and mRNA flu, SNY PCV21, PFE VLA15 through its study
  title) and 3 `no_gate` (AZN Ceralasertib and Monalizumab at a stated nil, GSK Camlipixant
  after a negative Phase 3).
- 11 next gates fail at Sertkaya's cost and 25 at DiMasi's level. The failing eleven are
  AZD5335, AZD0120, ponsegromab, MORF-057, REGN7508, ibuzatrelvir, osivelotor, zilovertamab
  vedotin, AGN-151607-DP, KAE609 and EYU688; REGN7508 is the largest at -$0.21 a share. 19
  assets have a ladder stage that fails.
- Risked development cost is a median 14.5% of an asset's rNPV.
- Routes: 192 registry stages, 58 peer, 25 benchmark, 5 seamless, 1 mixed peer and
  benchmark, and a review on every asset.
- A year of named trial spend against the R&D the book charges its marketed lines in 2026
  runs from 0.0% (GILD) to 7.4% (AMGN), NVO 5.3%, so the ratio covers it with room to spare.
- Named assets (per share; "if it passes" is build 2's leg):

| Asset | Gate | Chance | Cost to reach | If it passes | Net | Breaks even at |
|---|---|---|---|---|---|---|
| LLY Retatrutide | Phase 3 readout, NCT06662383, Nov 2026 | 97.9% implied | $41mm, $0.05 | $20.65 | $20.18 | 0.22% |
| LLY Eloralintide | Phase 3 readout, NCT07282600, Jan 2028 | 61.0% published | $138mm, $0.15 | $8.23 | $4.87 | 1.9% |
| AZN Elecoglipron | Phase 3 readout, NCT07775404, Apr 2028 | 61.5% published | $12mm, $0.01 | $6.63 | $4.07 | 0.12% |
| MRK sac-TMT | Phase 3 readout, NCT06074588, May 2027 | 77.3% implied | $258mm, $0.10 | $1.09 | $0.74 | 9.5% |
| NVO Cagrilintide | Phase 3 readout, NCT05567796, due since Oct 2024 | 61.0% published | DKK 725mm, $0.02 | $6.65 | $4.03 | 0.37% |

  Elecoglipron counts one study: of its eight other open Phase 3s, six are in indications
  the forecast does not value and two carry MeSH terms that match no indication, about
  $1.1bn of remaining spend in 2018 dollars, pre-tax, shown under `outside`. Cagrilintide's
  gate study is past its completion, so its own cost is sunk, and seven other open Phase 3s
  in the modelled indication carry the cost to the gate.

## 9. Risks

- Sertkaya and DiMasi disagree by about 3x, so the high bound stays on screen.
- Per-patient means come from trials of average size; the 17,000 to 33,000-patient outcome
  trials probably cost less per patient, so their costs may read high. Registry enrolment is
  a target that can change.
- Straight-line spend is a convention: trial spend is usually front-loaded and close-out
  follows primary completion. The full cost of each open study is shown beside its share
  ahead for that reason.
- The trials table holds only active studies mapped to the asset under the owner's sponsor
  query, so a study run by a partner or missed by `trial_asset_map` is invisible and cost is
  understated.
- PoS is asset-level, so a multi-indication asset gets one gate chain while costs sum across
  its modelled indications (sac-TMT's four under one stated 73.5%).
- Costs are timed from the registry and Sertkaya's durations while the success leg keeps
  the seeded start year, since the launch year is flag only (build 3).
- A reader may take "today, after development cost" as a lower fair value. The UI must say
  it is already paid inside the R&D ratio; the `paid_note` carries that sentence.

## 10. What the UI pass needs (not built here)

- Forecast tab, asset view: one "Next gate" block with the gate study and date, the chance,
  if it passes / if it fails / held (build 2), the cost to reach and the net from
  `/forecast/{id}/development` `gate` (`cost_per_share`, `net_per_share`, `breakeven_p`,
  `high`), and the earliest approval from that gate (build 3). The ladder goes in an
  expander labelled "after later trial costs", with `stages[].studies` and `outside` as the
  detail and `paid_note` as the footnote.
- Key insights pipeline rows: build 1's failing-gate fact (`funds` false) in the shared
  tooltip, no extra mark.
- Company view: `/companies/{t}/development`, `failing` first, and
  `reconciliation.sentence` under the table.
