# Watch list: dated events that could price a `no_free_data` row

Written 2026-11-16, when the real queue reached zero. Seventeen readouts in
`data/settled_readouts.csv` carry the kind `no_citable_figure`: a win would move share
inside a business already sold, and no company filing states the figure that would price
it (the search behind each is in `scenario_evidence.md`). These are the scheduled events
where a company has historically filed such a figure.

## The test a figure has to pass

A figure prices a readout only if it is the company's own, filed or furnished (an 8-K or
6-K exhibit, a 10-K, a results release), product-level, with a year, and **conditional on
the readout** or on the claim it decides. An unconditional product peak re-anchors the
base model, not the catalyst. Analyst figures, press paraphrase and conference chatter do
not qualify. When one passes:

1. Write the case in `data/catalyst_scenarios.csv`.
2. Delete the readout's row from `data/settled_readouts.csv` in the same change (a test
   refuses a study that is both settled and priced).
3. Re-run the queue and the gate.

## Events

| Date | Event | Rows it could move | What to look for |
|---|---|---|---|
| 18 to 19 Nov 2026 | Meet Novartis Management, London (Novartis 6-K confirms) | NVS Leqvio, VICTORION-2 PREVENT (NCT05030428) | The agenda promises peak-sales figures. A Leqvio figure of its own, and whether it is tied to the outcomes trials. Today Leqvio sits in a shared "USD 3-10 billion" band with seven assets (6-K 0001171843-25-007445). |
| Mid Dec 2026, date not published | Pfizer full-year 2027 guidance | PFE Abrysvo (NCT05035212, NCT07768345, NCT06866405), PFE Litfulo (NCT06873945) | Pfizer has not written "peak sales" in a filing since 2019. Any revaccination or per-pregnancy revenue statement for Abrysvo; any Litfulo line at all (it is not reported separately). |
| 11 to 14 Jan 2027 | J.P. Morgan Healthcare Conference | ABBV Ubrelvy (NCT06417775), ABBV Venclexta (NCT06428019); also AZN, LLY, MRK, BMY decks if furnished | AbbVie filed product peaks in its 2021 and 2023 J.P. Morgan decks (8-K exhibits). A preventive-migraine figure for Ubrelvy separate from the combined Ubrelvy and Qulipta ">$3 billion". |
| Late Jan to Feb 2027 | Q4 2026 results: AbbVie, Lilly, Merck, AstraZeneca, BMS | LLY Foundayo (four ATTAIN/RESTRAIN appendices), MRK Gardasil (NCT04199689, NCT07785843), AZN Baxfendy (NCT07007793), AZN Calquence (NCT05057494), AZN Tezspire (NCT06473779), BMY Augtyro (NCT06140836) | Any product-level figure. AstraZeneca rates BaxPA above an undisclosed materiality threshold in its clinical trials appendix; a stated threshold would be a floor, not a case. |

## Also dated

- **Redemplo, severe hypertriglyceridaemia.** Curated catalyst dated 2027-06-30, the end
  of the quarter Arrowhead guides launch in. No PDUFA date is filed, because under the
  FDA's STAR pilot the clock starts at a second submission no filing dates. Replace the
  date when Arrowhead files one.
- **Uplizna.** Uncapped by choice: Horizon's 2022 ">$1B" is the only published peak, and
  it is a floor the product has passed. A figure from Amgen would cap the model; see the
  note at the top of `data/assumptions/amgn_uplizna.csv`.
- **Vertex debt weight.** Re-strike from the FY2026 10-K balance sheet; the 0.031369 now
  in every VRTX seed is from the 10-Q for the quarter to 2026-09-30.
