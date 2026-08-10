# Audit: what the CASGEVY patient curve actually assumes

2026-08-10. The forecast tab draws two patient curves for CASGEVY: the workbook's
hand-typed series, and the pool identity run on the workbook's own population inputs.
They agree through the ramp and part after 2031, the hand curve declining to 350 while
the identity plateaus near 505. This audit asks which is right, with the evidence on
file. The short answer: the decline is real but its stated basis is not. The curve is a
depletion curve of a small willing pool, roughly 4 to 12 percent of the population the
workbook calls eligible, and neither of the two usual explanations survives contact with
the numbers.

## The three candidate explanations

**Saturation of the stated eligible pool: disproved by the workbook's own arithmetic.**
The stated pool is 46,000 (SCD 100,000 x 16% x 2.5 for ex-US, TDT 3,000 x 50% x 4.0).
Cumulative patients treated by 2035 in the hand curve: 5,699, which is 12.4% of it. A
pool that is 87% untouched cannot be why the curve falls.

**Treatment-centre capacity: disproved by Vertex's own disclosures, all on file.**

| date | ATCs activated | first cell collections | infusions |
|---|---|---|---|
| end 2024 (10-K, 2025-02-13) | more than 50 | more than 50 | 5 in 2024 |
| 1 May 2025 (8-K, 2025-05-05) | more than 65 | ~90 | |
| 30 Jun 2025 (8-K, 2025-08-04) | more than 75, goal met | ~115 | 29 cumulative, 16 in Q2 |
| 30 Sep 2025 (8-K, 2025-11-03) | | ~165, 50 in Q3 | 39 cumulative, 10 in Q3 |
| FY2025 (8-K, 2026-02-12) | | 147 during 2025 | 64 during 2025, 30 in Q4 |

Collections annualised off Q3 2025 run at ~200 a year across more than 75 centres:
about 2.7 collections per centre per year, against a plausible 10 to 20 per centre.
The centres are a fraction utilised, Vertex kept activating them past its stated goal,
and a capacity-bound curve would plateau at the cap rather than decline. Capacity is
not binding, and nothing on file suggests it starts binding in 2032.

**Exhaustion of a small willing pool: what the curve itself encodes.** Fitting the pool
identity to the hand series with the pool and inflow left free, rather than taken from
the workbook:

- SCD and TDT together: an implied pool of ~2,500 with ~325 a year of inflow reproduces
  the curve to an rmse of 15 patients a year.
- SCD alone: ~1,400 with ~260 a year, rmse 10.
- Forcing one acceptance rate on both stock and flow: 12% fits with rmse 18
  (pool 4,800, inflow 38 a year), and its 2033-35 tail (496, 419, 343) sits on the
  hand curve's (480, 400, 350).

So the curve behaves, to within its own freehand precision, exactly like the depletion
of a willing pool between ~1,500 and ~5,000 patients: 4 to 12 percent of the stated
eligible population. The decline the identity "argues with" is not wrong; it is the
signature of an implicit assumption the workbook never states, that roughly one eligible
patient in ten ever comes forward for myeloablative conditioning, weeks of hospital stay
and an infertility risk.

## What the curve cannot decide, and what would

Whether acceptance is one rate (~12% of everyone) or differential (a few percent of the
prevalent adults, most of the newly eligible flow) cannot be told from the curve: both
fit inside its precision, because the pool is still draining in 2035 either way. The
discriminating fact is the mix of infusions between newly eligible patients and
prevalent adults, which Vertex does not disclose. That is a question for investor
relations, and the answer moves the tail: at one rate the run rate beyond the horizon
decays toward ~40 a year; at the differential it holds near ~260.

## The near-term check

The 2026 curve says 170 infusions. H1 2026 revenue of 76.4m at 1.8m net is ~42, so H2
must deliver ~128. The 2025 collection cohort (147 collected, 64 infused, a backlog of
~130 with a roughly six-month lag) makes 100 to 150 plausible; 170 is the optimistic
edge of what the disclosed funnel supports.

## What was done with this

- The engine now filters incidence by the eligibility share before it enters the pool
  (2,000 births a year are not 2,000 eligible patients), which was a bug this audit
  surfaced.
- The identity's on-screen parameters stay fitted to the stated pool, so the divergence
  after 2031 remains visible: it is the size of the acceptance assumption.
- The implied acceptance range is seeded against the SCD indication as
  `implied_acceptance_low` 0.035 and `implied_acceptance_high` 0.12, sourced to this
  audit, so the sheet carries the audited quantity an analyst should vet.
- A modelling note for the roadmap: expressing acceptance properly needs it as a
  population gate, possibly with separate prevalent and incident rates. Today's funnel
  factors multiply the pace, which can slow a curve but never produce this decline.

## Sources

Every figure above is on file: Vertex filing sections (accessions of 2025-02-13,
2025-05-05, 2025-08-04, 2025-11-03, 2026-02-12), asset_revenue rows for asset 371
(FY2025 115.8m, H1 2026 76.4m), and CASGEVY_DCF_Model_v2.xlsx read with data_only=True.
The Zolgensma precedent is deliberately not cited as evidence: its history predates the
revenue extraction window and it is absent from CMS because its patients are Medicaid
infants, which is itself the claims-invisibility the roadmap records for one-time
therapies.
