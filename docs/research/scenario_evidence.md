# Scenario evidence: in-base readouts and the figures that could price them

Research date: 2026-11-16. Free sources only. Nothing written to `backend/er_tool.db` or
anything under `data/`. This file replaces the notes of an earlier pass that were lost from a
temp directory; every claim that pass made was checked again here against the primary
document, and where it was wrong or incomplete that is said.

## The standard

A readout inside the population a product already sells to can be priced in the book only
through a named scenario (`backend/catalyst_scenarios.py`, `data/catalyst_scenarios.csv`),
and a scenario can be written only from one of two things:

1. the company's own published peak-sales or growth figure for that product alone, or
2. a statement tying a figure to this readout.

A franchise, portfolio or band figure does not qualify. Neither does an analyst's number put
to management in a question, a journalist's characterisation, or a consensus a company
compiles from analysts.

## Result

**No row of the fifteen named has a citable figure. No scenario row and no assumption rows
are drafted.** `data/catalyst_scenarios.csv` should stay empty for all of them.

Two findings correct the earlier pass:

- **AbbVie has published a product-level figure for Ubrelvy, twice.** "Ubrelvy represents a
  $1Bn+ peak sales opportunity" (J.P. Morgan deck, 12 Jan 2021) and ">$1B in peak sales" for
  acute treatment (J.P. Morgan deck, 10 Jan 2023). Both are for the acute label only, both
  were superseded on 2 Feb 2024 by the combined ">$3 billion" with Qulipta, and neither is
  conditional on the preventive readout. So the earlier "only a combined figure" was wrong
  as history, right as to what is current, and the verdict does not change.
- **The two AstraZeneca figures the earlier pass reported could not be traced to an
  AstraZeneca document.** The baxdrostat ">$5bn" is an AstraZeneca statement as reported by
  Reuters and Dow Jones, but no AstraZeneca filing carries it. The Calquence "$3-5bn across
  all indications" was not found in any source at all. Neither should be cited from this
  file as an AstraZeneca figure.

A count note. The brief says sixteen readouts and names fifteen NCTs. The live queue
(`docs/research/queue_2026-11-16.json`, `in_the_base` rows) holds, besides the fifteen, two
triage bucket-B rows of low conviction: AZN Tezspire ARRIVAL (NCT06473779) and BMY Augtyro
TRIDENT-3 (NCT06140836). Either may be the sixteenth. Both had a light check (section 16) and
neither has a figure.

## Summary table

| # | Ticker | Asset | NCT | Trial readout (registry, primary completion) | Verdict | Next company event where a figure could appear |
|---|---|---|---|---|---|---|
| 1 | ABBV | Ubrelvy | NCT06417775 | 2027-11 (est.) | NO CITABLE FIGURE (a superseded acute-only product figure exists) | J.P. Morgan Healthcare Conference, 11-14 Jan 2027 (third-party listings); Q4 2026 results, date not published |
| 2 | ABBV | Venclexta | NCT06428019 | 2028-03 (est.) | NO CITABLE FIGURE | Same as Ubrelvy |
| 3 | AZN | Baxfendy | NCT07007793 (BaxPA) | 2027-07-27 (est.); AZN says data H2 2027 | NO CITABLE FIGURE | FY and Q4 2026 results, date not published (FY 2025 was 10 Feb 2026) |
| 4 | AZN | Calquence | NCT05057494 (MAJIC) | 2027-07-15 (est.) | NO CITABLE FIGURE | Same as Baxfendy |
| 5 | LLY | Foundayo | NCT06952530 | 2027-09 (est.) | NO CITABLE FIGURE | Q4 2026 results, date not published (Q4 2025 was 4 Feb 2026) |
| 6 | LLY | Foundayo | NCT06948435 | 2027-09 (est.) | NO CITABLE FIGURE | Same |
| 7 | LLY | Foundayo | NCT07202884 (RESTRAIN-SUI) | 2028-03 (est.) | NO CITABLE FIGURE | Same |
| 8 | LLY | Foundayo | NCT07153471 (ATTAIN-OA PAIN) | 2028-04 (est.) | NO CITABLE FIGURE | Same |
| 9 | MRK | Gardasil / Gardasil 9 | NCT04199689 | 2027-01-15 (est.) | NO CITABLE FIGURE | Q4 2026 results, date not published (Q4 2025 was 3 Feb 2026) |
| 10 | MRK | Gardasil / Gardasil 9 | NCT07785843 | 2027-12-18 (est.) | NO CITABLE FIGURE | Same |
| 11 | NVS | Leqvio | NCT05030428 (VICTORION-2P) | 2027-05-10 (est.) | NO CITABLE FIGURE | **Meet Novartis Management, London, 18-19 Nov 2026**; then Q4 2026 results, 3 Feb 2027 |
| 12 | PFE | Abrysvo | NCT05035212 (RENOIR) | 2027-01-18 (est.) | NO CITABLE FIGURE | Full-year 2027 guidance call, expected mid-December 2026, date not found published (2026 guidance was 16 Dec 2025) |
| 13 | PFE | Abrysvo | NCT07768345 | 2028-02-02 (est.) | NO CITABLE FIGURE | Same |
| 14 | PFE | Abrysvo | NCT06866405 | 2028-02-24 (est.) | NO CITABLE FIGURE | Same |
| 15 | PFE | Litfulo | NCT06873945 (ALLEGRO-100) | 2028-03-19 (est.) | NO CITABLE FIGURE | Same |

Registry dates are from the ClinicalTrials.gov v2 API, read 2026-11-16
(`https://clinicaltrials.gov/api/v2/studies/{NCT}`).

## How the search was run

- **SEC EDGAR full-text search** (`https://efts.sec.gov/LATEST/search-index`), by company CIK
  from `https://www.sec.gov/files/company_tickers.json` (ABBV 1551152, AZN 901832, LLY 59478,
  MRK 310158, NVS 1114448, PFE 78003, BMY 14272), 2019-01-01 to 2026-11-16, phrase queries
  shown per row. FTS indexes 8-K and 6-K exhibits, 10-K, 10-Q, 20-F and proxy statements. A
  hit means both terms appear somewhere in the document, so every hit was opened and the
  terms read in context.
- **Company documents outside EDGAR**: investor presentations, clinical trials appendices and
  aide-memoires, fetched from the company site where reachable. AbbVie, Merck, Lilly and
  Pfizer investor-event pages returned HTTP 403 or 404 to an automated fetch on 2026-11-16, so
  their next-event dates come from filings and prior-year pattern, and are labelled so.
- **Call transcripts**: none of the six companies posts a text transcript for 2025-2026 calls
  on its own site that could be reached. Where a third-party transcript was read it is named.

---

## 1. ABBV Ubrelvy: menstrual migraine prevention, NCT06417775

**What a win changes** (triage B1, high conviction): the label claim, from acute-only to
preventive. The label's Limitations of Use says "UBRELVY is not indicated for the preventive
treatment of migraine"; preventive dosing would be scheduled units on top of PRN use in the
same patient.

**Verdict: NO CITABLE FIGURE.** A product-level Ubrelvy figure exists in history, but it is
for the acute label, it is superseded, and nothing ties a figure to this readout.

Sources checked:

| Source | What it contains |
|---|---|
| AbbVie 8-K, 12 Jan 2021, acc. 0001104659-21-003462, ex. 99.1 (J.P. Morgan deck), `https://www.sec.gov/Archives/edgar/data/1551152/000110465921003462/tm212802d1_ex99-1.htm` | "Based on competitive profile and strong launch, we believe Ubrelvy represents a $1Bn+ peak sales opportunity". **Product-level, acute only, unconditional.** Atogepant (Qulipta) gets its own "$1Bn+" on the same deck. |
| AbbVie 8-K, 10 Jan 2023, acc. 0001104659-23-002452, ex. 99.1 (J.P. Morgan deck), `https://www.sec.gov/Archives/edgar/data/1551152/000110465923002452/tm232769d1_ex99-1.htm` | Slide headed "Acute Migraine Treatment": "Leading treatment for migraine attacks ... Expect >$1B in peak sales"; "Migraine Prevention" (Qulipta): "Expect peak sales of >$1B". The brand name is a logo, not in the text layer; the acute product is Ubrelvy. **Product-level, acute only, unconditional.** |
| AbbVie 8-K, 2 Feb 2024, acc. 0001551152-24-000007, ex. 99.1 (Q4 2023 results), `https://www.sec.gov/Archives/edgar/data/1551152/000155115224000007/abbv-20231231xexhibit991.htm` | Headline: "Raises Peak Sales Outlook for Ubrelvy and Qulipta to More Than $3 Billion Combined". Body: "The company now expects peak combined Ubrelvy and Qulipta revenues of more than $3 billion, an increase of approximately $1 billion compared to previous guidance". **Combined; supersedes the product-level figures.** |
| EDGAR FTS `"Ubrelvy" "peak sales"` (ABBV, 2019-2026) | 3 hits: the two decks above and the 2 Feb 2024 release, plus 31 Jul 2026 (acc. 0001551152-26-000023), where "peak sales" refers only to the Apogee acquisition. |
| EDGAR FTS `"billion" "Ubrelvy and Qulipta"` from 2024-03-01 | 12 quarterly releases to 30 Oct 2026. None restates or updates the peak outlook; they report combined quarterly revenue only. |
| AbbVie 8-K, 30 Oct 2026, acc. 0001551152-26-000033, ex. 99.1 (Q3 2026 results), `https://www.sec.gov/Archives/edgar/data/1551152/000155115226000033/abbv-20260930xexhibit991.htm` | Ubrelvy Q3 2026 revenue $449m (+26.9%). "Peak" appears only in boilerplate. **And:** "AbbVie announced positive topline results from the Phase 3 LUNA study, which evaluated Qulipta (atogepant) ... for the preventive treatment of menstrual migraine in adults ... meeting the primary and all eight ranked secondary endpoints". |
| AbbVie 10-Q for Q3 2026, acc. 0001551152-26-000037 | Repeats the LUNA result (September 2026). No figure. |

Note for the model. The menstrual-migraine preventive claim AbbVie has already won in-house
is Qulipta's (LUNA, Sept 2026), not Ubrelvy's. Whatever UBRO MM adds, it adds against a
sister product with that claim in hand, and AbbVie's only current peak figure covers both.
No figure can be split between them from anything AbbVie has published.

**Next event.** J.P. Morgan Healthcare Conference, San Francisco, 11-14 Jan 2027 (dates from
third-party listings, e.g. Bass Berry and VLS Research; AbbVie's attendance not confirmed).
This is the venue where AbbVie published both product-level migraine figures. Then Q4 2026
results; AbbVie has not published the date (Q4 2025 results were 4 Feb 2026, 8-K acc.
0001551152-26-000004).

## 2. ABBV Venclexta: shorter ramp-up in 1L CLL, NCT06428019

**What a win changes** (triage B13, medium): Dosage and Administration (section 2) and the
TLS monitoring burden that is the documented reason community prescribers pick a BTKi.

**Verdict: NO CITABLE FIGURE.** AbbVie has never published a Venclexta peak figure in any
filing reached.

Sources checked:

| Source | What it contains |
|---|---|
| EDGAR FTS `"Venclexta" "peak sales"` (ABBV, 2019-2026) | 4 hits (12 Jan 2021, 10 Jan 2023, 2 Feb 2024, 31 Jul 2026). Read in context with a 400-character proximity search: no peak figure is attached to Venclexta in any. The 2023 deck says only "Strengthen Venclexta's position in CLL / AML and position for long-term growth by broadening indications". |
| EDGAR FTS `"Venclexta" "ramp-up"` | 0 hits. AbbVie has made no filed statement about this trial's commercial effect. |
| AbbVie Q3 2026 results, acc. 0001551152-26-000033 | Venclexta Q3 2026 revenue $803m (+10.7%). No outlook. |

**Next event.** As Ubrelvy: J.P. Morgan, 11-14 Jan 2027; Q4 2026 results, date not
published.

## 3. AZN Baxfendy: BaxPA, primary aldosteronism, NCT07007793

**What a win changes** (triage B12, medium): a disease-specific claim including renin
normalisation, and an Endocrine Society guideline position, in a diagnosed population where
MRAs are entrenched. The patients are inside the current hypertension label.

**Verdict: NO CITABLE FIGURE.** The only AstraZeneca-attributed figure is a molecule total
spanning standalone and Farxiga-combination use, and no AstraZeneca filing carries it.

Sources checked:

| Source | What it contains |
|---|---|
| EDGAR FTS `"baxdrostat" "$5bn"`, `"baxdrostat" "5bn"`, `"peak year revenue" "baxdrostat"` (AZN) | **0 hits each.** No 6-K, 20-F or annual report carries a baxdrostat revenue figure. |
| EDGAR FTS `"baxdrostat" "peak"` (AZN) | 16 hits; read in context, every one is pharmacokinetic ("reached peak levels in the blood within 2 to 4 hours") or unrelated. |
| AZN 6-K, 18 May 2026, acc. 0001654954-26-005044, "Baxfendy approved in the US for hypertension" | No revenue figure. |
| AZN 6-K, 30 Oct 2026, acc. 0001654954-26-009256, 9M and Q3 2026 results, `https://www.sec.gov/Archives/edgar/data/901832/000165495426009256/a0835b.htm` | Soriot: "Our rich series of upcoming readouts in 2027 has a potential of more than twenty billion dollars." Collective, not product-level. |
| AZN 9M and Q3 2026 clinical trials appendix, as of 30 Oct 2026, `https://www.astrazeneca.com/content/dam/az/PDF/2026/9mq3/9M-and-Q3-2026-results-clinical-trials-appendix.pdf` | p.3 lists "Baxfendy \| primary aldosteronism \| BaxPA" as a key Phase III readout, where "Key upcoming pipeline catalysts are defined by a threshold of non-risk adjusted global peak year revenue expectations as of 27 July 2026". The threshold value is not stated. p.73: BaxPA, n=250, "Data anticipated: H2 2027". So AstraZeneca rates BaxPA above its materiality bar and gives no number. |
| AZN post-Q2 2026 aide-memoire, Aug 2026, `https://www.astrazeneca.com/content/dam/az/PDF/2026/AZN-PostQ2-Aide-memoire-2026.pdf` | "Baxfendy ... is mainly a Medicare Part D product and no major revenues are anticipated in 2026." Its "Pipeline peak sales" tab is a template for **analysts** to return estimates for a company-compiled consensus; it is not AstraZeneca guidance. |
| Dow Jones Newswires (Adria Calatayud), 18 May 2026, via MarketScreener, `https://www.marketscreener.com/news/astrazeneca-gets-u-s-approval-for-hypertension-drug-ce7f5adad980f622` | "revenue from the product could top $5 billion at its peak", attributed to company executives, previously. No indication split, no mention of primary aldosteronism. |
| Reuters (July 2025, syndicated copies; the reuters.com original was not reached) | AstraZeneca expects peak annual sales above $5bn, "driven by its use as a standalone therapy and in combination with Farxiga". **Spans programmes; secondary source; not conditional on BaxPA.** |

The earlier pass's "spans six programmes" was not verified; what the reporting supports is
"standalone and in combination with Farxiga", which is already more than one programme. The
book's own `azn_baxfendy.csv` base solves to UBS's roughly $4bn, not to the AstraZeneca
figure, which is the right call while the AstraZeneca figure has no primary document.

**Next event.** FY and Q4 2026 results. AstraZeneca has not published the date: its IR page,
read 2026-11-16, lists only November roadshows. FY 2025 results were 10 Feb 2026 (6-K acc.
0001654954-26-001073). A post-Q3 aide-memoire, if issued, would follow the Aug 2026 pattern.

## 4. AZN Calquence: MAJIC, NCT05057494

**What a win changes** (triage B10, high): guideline preference between two in-label
fixed-duration 1L CLL regimens, acalabrutinib-venetoclax against venetoclax-obinutuzumab, and
so the split of that pool between AstraZeneca and AbbVie/Roche.

**Verdict: NO CITABLE FIGURE.** The "$3-5bn across all indications" the earlier pass reported
was not found in any source.

Sources checked:

| Source | What it contains |
|---|---|
| EDGAR FTS `"Calquence" "peak"` (AZN, 2019-2026) | 27 hits. Proximity search (`Calquence` within 300 characters of `peak`) in the H1 2024 6-K (acc. 0001104659-24-082531), 9M 2024 6-K (acc. 0001654954-24-014089) and 9M 2026 6-K (acc. 0001654954-26-009256): **0 matches.** The hits are the two words far apart. |
| EDGAR FTS `"Calquence" "peak year revenue"` | 1 hit, the 9M 2026 6-K, where the phrase is the collective readout line quoted under Baxfendy. |
| EDGAR FTS `"MAJIC"` (AZN) | **0 hits.** AstraZeneca has never named the trial in a filing. |
| AZN 9M and Q3 2026 clinical trials appendix (URL above) | Calquence entries: AMPLIFY (NCT03836261, "Primary endpoint met"), ECHO, ESCALADE. **MAJIC is absent from the appendix entirely**, though AstraZeneca is the registry's lead sponsor. The appendix lists AMPLIFY (CN) as an H2 2026 regulatory decision. |
| AZN 6-K, 18 Feb 2025, acc. 0001654954-25-001189 | No "3-5", no Calquence figure. |
| AZN post-Q2 2026 aide-memoire (URL above) | "Calquence delivered growth of 16% in Q2 2026 ... The Company continues to see the AMPLIFY finite duration treatment as a significant growth driver through the remainder of 2026". No figure, no MAJIC. |
| Web search for "Calquence" with "3-5bn", "$3bn-$5bn", "$3 billion to $5 billion" | Nothing from AstraZeneca. Nearest: New Street Research "Calquence set to be $5bn drug" (analyst, undated in the listing) and Citeline's "nearly $4bn in 2030" (a forecast, paywalled). Neither qualifies. |

That MAJIC is missing from AstraZeneca's own catalyst appendix is itself evidence: the
company does not count it among readouts above its peak-revenue threshold.

**Next event.** As Baxfendy: FY and Q4 2026 results, date not published.

## 5-8. LLY Foundayo: NCT06952530, NCT06948435, NCT07202884, NCT07153471

**What a win changes** (triage B8/B9 high; B16/B17 medium): new claims inside the approved
obesity population: systolic blood pressure lowering (the two ATTAIN-HYPERTENSION ISAs),
incontinence-episode frequency (RESTRAIN-SUI), WOMAC pain (ATTAIN-OA PAIN). These are the
comorbidity claims that move payer coverage beyond weight alone.

**Verdict, all four: NO CITABLE FIGURE.** Lilly has never published a peak or annual revenue
figure for orforglipron.

Sources checked:

| Source | What it contains |
|---|---|
| EDGAR FTS `"orforglipron" "peak sales"` (LLY, 2019-2026) | **0 hits.** |
| EDGAR FTS `"Foundayo" "peak"` | **0 hits.** |
| EDGAR FTS `"Foundayo" "billion"` | 6 hits (Q1-Q3 2026 releases and 10-Qs); each is a revenue table or company total. |
| EDGAR FTS `"orforglipron" "hypertension"` | 3 hits (10-Qs Q2 and Q3 2025, 10-K FY2025): pipeline listings only. |
| Lilly 8-K, 29 Oct 2026, acc. 0000059478-26-000104, Q3 2026 results, `https://www.sec.gov/Archives/edgar/data/59478/000005947826000104/q326lillysalesandearningsp.htm` | Foundayo Q3 2026 revenue $184m, year to date $281m. No outlook for it; "hypertension", "osteoarthritis", "incontinence" do not appear. |
| Q4 2025 earnings call, 4 Feb 2026, transcript as published by The Motley Fool, `https://www.fool.com/earnings/call-transcripts/2026/02/04/eli-lilly-lly-q4-2025-earnings-call-transcript/` | **Confirmed:** "$5 billion" appears only in the question of Steve Scala (TD Cowen): "without orforglipron being a $5 billion product in 2026?" CFO Lucas Montarce answered qualitatively ("consistent with our expectations and our guide") and gave no number. "Peak" does not occur. |

The book's base (`lly_foundayo.csv`) uses an $18bn ceiling from Bloomberg News consensus as
reported by GEN on 2026-04-05. That is a consensus, correctly labelled as such, and it is
unconditional; it cannot be split into a with-claim and without-claim case.

**Next event.** Q4 2026 results; Lilly has not published the date (Q4 2025 results were
4 Feb 2026, 8-K acc. 0000059478-26-000008). Lilly's IR events page returned 403.

## 9-10. MRK Gardasil / Gardasil 9: NCT04199689, NCT07785843

**What a win changes.** NCT04199689 (triage B5, high): it is the confirmatory trial for the
accelerated-approval oropharyngeal and head-and-neck cancer claim in men; a win converts the
claim. NCT07785843 (B18, medium): whether Chinese women already vaccinated with a bivalent
vaccine become recommendable for the nine-valent.

**Verdict, both: NO CITABLE FIGURE.** Merck's only figure was a franchise revenue target, and
it was withdrawn.

Sources checked:

| Source | What it contains |
|---|---|
| Merck DEF 14A, 3 Apr 2023, acc. 0001193125-23-089525 | "We expect our HPV vaccines to continue growing substantially, potentially more than doubling 2021 sales and generating over $11 billion ... in revenue by 2030." **Franchise (GARDASIL and GARDASIL 9 together), a 2030 revenue target, unconditional.** |
| Merck 8-K, 4 Feb 2025, acc. 0001104659-25-008863, ex. 99.1 (Q4 2024 results) | GARDASIL/GARDASIL 9 Q4 2024 sales $1,550m (-17%), "primarily due to lower demand in China". The release text does not mention the $11bn target. |
| STAT, 4 Feb 2025, `https://www.statnews.com/2025/02/04/merck-gardasil-keytruda-cancer-drug-china/` | Merck "withdrew a target for sales of its HPV vaccine, Gardasil, to reach $11 billion by 2030". **Withdrawal confirmed; it was made on the call, not in the filed release.** |
| Merck 10-K FY2024, filed 25 Feb 2025, acc. 0001628280-25-007732 | The decision "to temporarily pause shipments to China beginning in February 2025". The only "$11 billion" in it is US capital spending. |
| EDGAR FTS `"Gardasil" "peak"` (MRK, 2019-2026) | **0 hits.** |
| EDGAR FTS `"GARDASIL" "billion" "2030"` from 2025-02-05 | 10 hits; read in context, none restates an HPV revenue target. |
| Merck 8-K, 29 Oct 2026, acc. 0001104659-26-119825, Q3 2026 results | GARDASIL/GARDASIL 9 Q3 2026 $1,995m (+14%), "higher sales in the U.S. reflecting favorable public-sector purchasing patterns and higher net pricing". No target. |
| Merck 10-Q Q2 2026, acc. 0000310158-26-000212 | Merck "will not proceed with" single-dose V503 trials after FDA and EMA feedback. No figure. Neither trial here is named. |

**Next event.** Q4 2026 results; Merck has not published the date (Q4 2025 results were
3 Feb 2026, 8-K acc. 0001104659-26-009495). Merck's IR events page returned 403.

## 11. NVS Leqvio: VICTORION-2 PREVENT, NCT05030428

**What a win changes** (triage B3, high): inclisiran's own cardiovascular outcomes claim; the
label's MACE sentence today names only statins and PCSK9 antibodies. Plus guideline and payer
position.

**Verdict: NO CITABLE FIGURE.** Re-verified; `docs/leqvio_cvot.md` (2026-11-11) holds the full
record and stands.

Sources re-checked in this pass:

| Source | What it contains |
|---|---|
| Novartis 6-K, 20 Nov 2025, acc. 0001171843-25-007445, `https://www.sec.gov/Archives/edgar/data/1114448/000117184325007445/f6k_112025.htm` | "Novartis now has eight de-risked, in-market assets with peak sales potential of USD 3-10 billion: Kisqali, Cosentyx, Kesimpta, Pluvicto, Scemblix, Leqvio, Fabhalta and Rhapsido." Kisqali and Scemblix get their own figures in the same release; Leqvio does not. **Band, eight assets.** |
| Novartis 20-F FY2025, acc. 0001114448-26-000004 | "peak sales": 0 occurrences. "VICTORION": 0. |
| EDGAR FTS `"Leqvio" "peak"` (NVS) | Last hit is the 20 Nov 2025 6-K above. |
| EDGAR FTS `"ORION-4"`, 2026-10-01 to 2026-11-16 | 0 hits. No ORION-4 result filed as of today. |
| Novartis 6-K, 27 Oct 2026, acc. 0001114448-26-000014, ex. 99.1 (Q3 2026 financial report) | "Important dates: November 18-19, 2026 Meet Novartis Management 2026 (London, UK); February 3, 2027 Fourth quarter & full year 2026 results; March 5, 2027 Annual General Meeting". |
| Novartis 6-K, 12 Nov 2026, acc. 0001104659-26-126289 | A debt-offering 6-K. No Leqvio content. |

The FiercePharma "above $4 billion" (21 Jul 2026) remains the journalist's own
characterisation; see `docs/leqvio_cvot.md`.

**Next event.** **Meet Novartis Management, London, 18-19 November 2026**, with "Updated peak
sales potential for key growth drivers" on the agenda (Novartis Q3 2026 investor
presentation, p.26, per `docs/leqvio_cvot.md`). It has not happened yet; nothing is assumed
about what it will say. Then Q4 2026 results, 3 Feb 2027.

## 12-14. PFE Abrysvo: NCT05035212, NCT07768345, NCT06866405

**What a win changes.** RENOIR substudies (B6, high) and the immunocompromised interval study
(B19, medium): a revaccination schedule, which decides whether adult RSV is a one-time or a
repeating purchase. NCT06866405 (B7, high): a dose per pregnancy rather than one per woman.

**Verdict, all three: NO CITABLE FIGURE.** Pfizer has not used the words "peak sales" in any
SEC filing since 2019.

Sources checked:

| Source | What it contains |
|---|---|
| EDGAR FTS `"peak sales"` (PFE, 2019-2026, all forms) | **0 hits.** |
| EDGAR FTS `"peak sales potential"` | **0 hits.** |
| EDGAR FTS `"peak revenue"` | 1 document: DEF 14A, 16 Mar 2023, acc. 0000078003-23-000040. Pfizer filed for RSV, pneumococcal, meningococcal, alopecia areata and ulcerative colitis products, "several of which are expected to potentially deliver more than $1 billion in annual peak revenue, if approved". **Unattributed among five filings; not product-level.** |
| EDGAR FTS `"peak year revenue"` | 1 document: DEF 14A, 12 Mar 2026, acc. 0000078003-26-000033. The phrase describes how executive pipeline goals are measured; no product, no figure. |
| EDGAR FTS `"Abrysvo" "peak"` | 5 hits (10-Q Aug 2023, proxies 2025 and 2026); proximity search finds no figure attached to Abrysvo. |
| EDGAR FTS `"Abrysvo" "revaccination"` | **0 hits.** Pfizer has made no filed statement about revaccination's commercial effect. |
| Pfizer 8-K, 3 Nov 2026, acc. 0000078003-26-000125, Q3 2026 results | Abrysvo Q3 2026 revenue $303m (+9%), nine months $691m (+25%), US down, international up. No outlook. |

**Next event.** Pfizer's full-year 2027 guidance call. Pfizer has not published the date;
the 2026 guidance call was 16 Dec 2025 (Pfizer release, "Pfizer Reaffirms Full-Year 2025 EPS
Guidance and Provides Full-Year 2026 Guidance"), and third-party coverage of the Q3 2026 call
says 2027 guidance comes around mid-December. Pfizer's IR events page returned 404. Then Q4
2026 results, date not published.

## 15. PFE Litfulo: ALLEGRO-100, NCT06873945

**What a win changes** (triage B11, high): a 100 mg dose, with dose-up for 50 mg
non-responders, recapturing patients who now stop.

**Verdict: NO CITABLE FIGURE.** Pfizer does not even report Litfulo as a revenue line.

Sources checked:

| Source | What it contains |
|---|---|
| Pfizer 10-K FY2025, acc. 0000078003-26-000026 | Litfulo appears three times: in a portfolio list ("select products include: Xeljanz, Enbrel ..., Cibinqo, Litfulo"), in the patent-expiry table ("Litfulo 2034 (2037 pending PTE) 2038 2039"), and in the pipeline (vitiligo). **No revenue line.** |
| Pfizer Q3 2026 results, acc. 0000078003-26-000125 | Litfulo is inside "Launched and Acquired Products", footnote (1), with nine other launches. No line, no figure. Also: Phase 3 vitiligo results (TRANQUILLO, TRANQUILLO 2), October 2026. |
| EDGAR FTS `"ritlecitinib" "peak"` | 6 hits 2020-2023, pipeline-era filings; none carries a figure. |
| DEF 14A 2023 (above) | Alopecia areata is one of five filings "several of which" may exceed $1bn. Not attributable to Litfulo. |

**Next event.** As Abrysvo: the full-year 2027 guidance call, expected mid-December 2026,
date not published.

---

## 16. The two candidates for a sixteenth row (light check only)

| Ticker | Asset | NCT | Triage | Check | Result |
|---|---|---|---|---|---|
| AZN | Tezspire | NCT06473779 (ARRIVAL) | B20, low: an ICS step-down claim | EDGAR FTS `"Tezspire" "peak"` (22 hits), `"ARRIVAL" "Tezspire"` (0) | No Tezspire figure found; hits read in context (e.g. the 27 Aug 2026 CROSSING 6-K) use "peak" for eosinophil counts. ARRIVAL is never named. |
| BMY | Augtyro | NCT06140836 (TRIDENT-3) | B21, low: firms a guideline category | EDGAR FTS `"Augtyro" "peak"` (1 hit, 13 Jan 2025, no proximity match), `"repotrectinib" "peak"` (2), `"TRIDENT-3"` (0) | Only "Late-stage pipeline: $10B+ peak non-risk-adjusted revenue potential" across several assets including repotrectinib (BMS 8-K, 9 Jan 2023, acc. 0001140361-23-000970). Portfolio-level. |

Neither qualifies.

## What to do with this

1. Leave `data/catalyst_scenarios.csv` empty for all fifteen. There is nothing to write a
   scenario from, and an unsourced scenario would read as priced while saying nothing.
2. Re-read Novartis after 19 Nov 2026. Meet Novartis Management is the only scheduled event
   in this set whose published agenda promises peak-sales figures. If it gives Leqvio a
   figure of its own, it is still unconditional unless Novartis ties it to the outcomes
   trials; record which it is before writing a row.
3. Watch the December and February calendar: Pfizer's 2027 guidance (mid-December), J.P.
   Morgan (11-14 Jan 2027, where AbbVie has historically filed product peak figures), then the
   Q4 results of AbbVie, Lilly, Merck and AstraZeneca. None of these has promised a product
   figure.
4. Do not cite the baxdrostat ">$5bn" or a Calquence "$3-5bn" as AstraZeneca figures. The
   first has no AstraZeneca document behind it in any free source reached; the second has no
   source at all.
