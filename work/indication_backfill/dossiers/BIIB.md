# BIIB: 3 indication layers to research

## Litifilimab  (asset_id 1934)
- mode **launch**
- **blocked at asset level on discontinuation_pct, net_price_per_patient.** Every layer below needs these, so find them once for the product:
    - `list_price_per_patient` in mm USD a year, from the manufacturer's own WAC disclosure or a state price transparency filing, with the dose and schedule you multiplied shown in the source; plus `gross_to_net_pct`.
    - `discontinuation_pct`, the share of the patient stock stopping each year. Derive it from a published median duration of response, progression-free survival or persistence, and say which and from where.

### Lupus Erythematosus, Cutaneous   [Phase 3, Active not recruiting]
- unit key `1934:139`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT05531565  Phase 2/3, Active not recruiting, n=450, primary completion 2026-10-20
    A 2-Part Study to Learn Whether Litifilimab (BIIB059) Injections Can Improve Symptoms of Adult Participants Who Have Active Cutaneous Lupus Erythemato
- trial NCT06044337  Phase 3, Enrolling by invitation, n=306, primary completion 2029-06-26
    A Long-Term Extension Study to Learn More About the Safety of Litifilimab (BIIB059) Injections and Whether They Can Improve Symptoms of Adult Particip

### Lupus Erythematosus, Discoid   [Phase 3, Active not recruiting]
- unit key `1934:140`, therapeutic area None
- the book holds no pool for this disease; it has to be researched and sourced
- trial NCT05531565  Phase 2/3, Active not recruiting, n=450, primary completion 2026-10-20
    A 2-Part Study to Learn Whether Litifilimab (BIIB059) Injections Can Improve Symptoms of Adult Participants Who Have Active Cutaneous Lupus Erythemato
- trial NCT06044337  Phase 3, Enrolling by invitation, n=306, primary completion 2029-06-26
    A Long-Term Extension Study to Learn More About the Safety of Litifilimab (BIIB059) Injections and Whether They Can Improve Symptoms of Adult Particip

### Lupus Erythematosus, Systemic   [Phase 3, Active not recruiting]
- unit key `1934:411`, therapeutic area None
- **the book already holds this pool — reuse it verbatim, do not research a second figure:**
    - `incidence` = 14,263 patients a year
      source: data/epidemiology.csv, 'Lupus Erythematosus, Systemic', the same CDC registries row
    - `prevalence` = 204,295 patients
      source: data/epidemiology.csv, 'Lupus Erythematosus, Systemic': CDC national lupus registries programme, the five state registries, age-standardised to the US population
- trial NCT04961567  Phase 3, Active not recruiting, n=562, primary completion 2026-09-27
    A Study to Learn About the Safety of Litifilimab (BIIB059) Injections and Whether They Can Improve Symptoms of Adult Participants Who Have Systemic Lu
- trial NCT04895241  Phase 3, Active not recruiting, n=548, primary completion 2026-09-30
    A Study to Learn About the Safety of Litifilimab (BIIB059) Injections and Whether They Can Improve Symptoms of Adult Participants Who Have Systemic Lu
- trial NCT05531565  Phase 2/3, Active not recruiting, n=450, primary completion 2026-10-20
    A 2-Part Study to Learn Whether Litifilimab (BIIB059) Injections Can Improve Symptoms of Adult Participants Who Have Active Cutaneous Lupus Erythemato
- trial NCT05352919  Phase 3, Enrolling by invitation, n=864, primary completion 2032-05-03
    A Study to Learn More About the Long-Term Safety of Litifilimab (BIIB059) Injections and it's Effects on Symptoms in Adults With Systemic Lupus Erythe

