# Paediatric rows: readouts with no row

Checked 2026-10-28 against the registry (clinicaltrials.gov API v2) and the FDA labels on api.fda.gov.

- AZN Fasenra NCT06512883 (CLIPS): several diseases. Enrols ages 6 to 17 only, but in two diseases, eosinophilic granulomatosis with polyangiitis and hypereosinophilic syndrome, so it cannot link to one row. (Label: EGPA adults only, HES from 12 years.)
- CABA CABA-201 NCT06154252 (RESET-Myositis): adults enrolled. The registry gives ages 6 to 75 and indexes it across adult and juvenile myositis together.
- GSK Investigational varicella vaccine NCT07406360: several diseases. A combined measles, mumps, rubella and varicella vaccine, indexed under all four.
- GSK Investigational varicella vaccine NCT07742644: several diseases, for the same reason (MMRV, ages 4 to 6).
- JNJ Stelara NCT05092269: several diseases. A basket long-term extension, ages 2 to 17, across Crohn's disease, ulcerative colitis and psoriatic arthritis.
- PFE Hympavzi NCT05611801: several diseases. Enrols ages 1 to 17 only, but in hemophilia A and hemophilia B, which MeSH and the book hold as separate diseases. (Label, set id a2cc631e, effective 2026-06-22: either disease from 6 years.) What would settle it: a decision that one Hympavzi row covers both haemophilias, as the label does.
- PRAX elsunersen NCT07019922: adults enrolled, and no paediatric subset exists. The registry gives 1 day to 18 years with no upper bound in the criteria, so an 18 year old can enrol. Its condition, early-onset SCN2A DEE with seizures before 3 months, is a disease of infancy with no adult population to keep apart, and MeSH has no concept for it (the registry indexes the study under no MeSH term). It needs an ordinary curated addition, like relutrigine's in data/asset_indication_additions.csv, not a paediatric row.
- SNY Yf-Vax NCT07103148: not a study of the asset. The registry's summary says it tests vYF, an investigational yellow fever vaccine, against the licensed Stamaril and YF-VAX, so Yf-Vax is the comparator. What would settle it: decide whether vYF is held as Yf-Vax's successor, the way PG4 is folded into the Prevnar family (data/asset_alias_map.csv). If it is, the row is "Pediatric yellow fever", adult_mesh_id D015004, ages 9 months to 5 years, and the YF-VAX label age is still to be read.

# Rows written with a field not established

- GSK PENMENVY, PFE Prevnar / Prevenar family, SNY Menquadfi: label_from_age is empty. Vaccine package inserts (CBER) are not on api.fda.gov, and dailymed.nlm.nih.gov and www.fda.gov were refused by this session's network policy. What would settle it: read each insert's indications section on DailyMed or fda.gov once those hosts are allowed.
- MeSH concepts: id.nlm.nih.gov and eutils.ncbi.nlm.nih.gov were also refused. The three paediatric concepts used (C536215 Pediatric Crohn's disease, C536315 Pediatric ulcerative colitis, D063766 Pediatric Obesity) and every adult_mesh_id were confirmed from the registry's own MeSH indexing (conditionBrowseModule). A sweep of registry studies with paediatric condition text found no other paediatric concept for these diseases, but only a MeSH lookup can confirm that none exists.

# Spelling and book notes

- paed.txt cuts the asset column at 22 characters. Four names are written in full, as the book spells them elsewhere: "Investigational varicella vaccine", "Prevnar / Prevenar family", "0.5 mL of the low dose VAX-31" (data/asset_alias_map.csv folds it into "31 valent pneumococcal conjugate vaccine"; if the fold has already run, the row's asset should read that instead) and "Low dose of iNTS-TCV", which fits whole.
- AMGN Avacopan is held unmarketed in paed.txt, but it is approved as Tavneos (NDA214487) for ANCA-associated vasculitis in adults, and the row says so.
