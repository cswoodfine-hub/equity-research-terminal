# SNY: 2 indication layers to research

## Dupixent  (asset_id 909)
- mode **marketed**, revenue anchor 15,714mm USD
- **blocked at asset level on discontinuation_pct, net_price_per_patient.** Every layer below needs these, so find them once for the product:
    - `list_price_per_patient` in mm USD a year, from the manufacturer's own WAC disclosure or a state price transparency filing, with the dose and schedule you multiplied shown in the source; plus `gross_to_net_pct`.
    - `discontinuation_pct`, the share of the patient stock stopping each year. Derive it from a published median duration of response, progression-free survival or persistence, and say which and from where.

### Pruritus   [Phase 3, Recruiting]
- unit key `909:285`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT05263206  Phase 3, Recruiting, n=284, primary completion 2027-06-02
    Efficacy and Safety of Subcutaneous Dupilumab for the Treatment of Adult Participants With Chronic Pruritus of Unknown Origin (CPUO) (LIBERTY-CPUO-CHI
- **pending catalyst** 2027-06-02 (data readout): Phase 3, Dupixent

### Colitis, Ulcerative   [Phase 2, Active not recruiting]
- unit key `909:21`, therapeutic area None
- **the book already holds this pool — reuse it verbatim, do not research a second figure:**
    - `incidence` = 20,881 patients a year
      source: Lewis JD et al., Gastroenterology 2023: 6.3 new ulcerative colitis diagnoses per 100,000 person-years, applied to the 2020 census population of 331,449,281
    - `prevalence` = 1,253,000 patients
      source: Lewis JD et al., Gastroenterology 2023;165:1197-1205 (Medicare, Medicaid and commercial claims): 378 per 100,000, an estimated 1.253 million Americans with ulcerative colitis at the 2020 census
- trial NCT05731128  Phase 2, Active not recruiting, n=68, primary completion 2026-05-13
    A Study to Investigate the Efficacy and Safety of Dupilumab Therapy Compared With Placebo in Participants Aged ≥18 Years With Moderately to Severely A

