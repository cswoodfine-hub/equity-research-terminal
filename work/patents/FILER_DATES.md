# Filer-stated US dates: re-read for every valued product without a row

Run 2026-10-29, after Keytruda was found valued on its 12-year floor (2026-09-04) while
Merck's 10-K states December 2028. The 2026-09-16 pass wrote a row only where the filer's
date differed from the one the model then held; the date rules have changed since, so
agreement then is not agreement now.

## Method

1. **Candidates.** Every marketed product with a forecast and no row in
   `data/disclosed_loe.csv`: 252 of 372, 1.77tn of the book's 2.61tn NPV. 221 belong to
   the 22 SEC filers.
2. **Filings.** Each filer's latest annual report from EDGAR, all FY2025 and filed in
   2026 (`tools/filer_dates/get_annual.py`).
3. **Reading.** Five agents read the filings in parallel against a fixed brief
   (`tools/filer_dates/BRIEF.md`): the molecule's date only, a settled entry date over
   the patent, pending extensions flagged and not resolved, every quote verbatim.
4. **Checks** (`tools/filer_dates/verify.py`, then by hand):
   - every quote was found in its filing;
   - each stated date was compared with the model's at the precision the filer
     states: a year against the model's year, a month or a day against its date.

Every finding, with its quote, is in `filer_dates_2026-10-29.json`.

## Result

| outcome | products |
|---|---|
| filing states nothing for the US | 102 |
| agrees with the model | 42 |
| same year as the model (a table year against an exact Orange Book date) | 40 |
| differs | 26 |
| "expired" or lost, with no year | 4 |
| a range of years the text cannot resolve (AstraZeneca, GSK), read from the HTML below | 7 |

### Rows added (11)

| product | model before | filer | NPV, mm |
|---|---|---|---|
| Tremfya (JNJ) | 2029-07-13, 12-year floor | 2031, composition patent | 19,136 to 24,476 |
| Alyftrek (VRTX) | 2040-08-13, latest substance patent | 2039, basic product patent | 28,412 to 26,842 |
| Auvelity (AXSM) | 2043-11-28 | 2038-09-30, Teva settlement | 4,581 to 3,815 |
| Lumakras (AMGN) | 2040-05-20, a crystalline form | 2038-05-21, compounds patent | 2,602 to 2,391 |
| Sunosi (AXSM) | 2038-11-01 | 2040-03-01, Hikma settlement | 896 to 1,054 |
| Dificid (MRK) | 2027-07-31 | lost July 2025 | 44 to 13 |
| Bridion (MRK) | 2026-01-27 | 2026-07-27, pediatric exclusivity | unchanged |
| Otezla (AMGN) | 2028-02-16 | 2028-08-16, pediatric exclusivity | unchanged |
| Sarclisa (SNY) | 2032-03-02 | 2032-10, compound with PTA and PTE | unchanged |
| Mozobil (SNY) | no date | 2023, generic competition | unchanged |
| Symdeko (VRTX) | 2031-07-10 | 2027, basic product patent | no forecast value |

+2,921mm across the book on a copy. A date that stays inside the same year moves
nothing, since the engine works in years.

Alyftrek and Lumakras show the substance rule's known failing: the Orange Book flags a
crystal form as "drug substance", and the latest one is not the molecule.

### Not taken, and why

- **Pending or estimated extensions:**
  - Ozempic and Wegovy: Novo's 2032 includes estimated extensions; the USPTO certificate
    takes the semaglutide compound patent to 2031-12-05, the model's date.
  - Pluvicto, Welireg, Jemperli, Wayrilz, Exdensur, Nexviazyme.
  - Omvoh: Lilly does not say which of its extensions are granted.
- **Ungranted pediatric exclusivity:** Rinvoq. Its April 2037 assumes pediatric
  exclusivity; without it, entry falls at about the model's 2036-10-17.
- **A biologic compound patent ending inside its 12 years:** Evenity, Arexvy, Tecartus,
  Nexviazyme.
- **Not US-approved:** Awiqli. 2037 is Novo's estimate of data protection.
- **"Expired" without saying generics or biosimilars are on the US market:**
  - Lutathera: orphan exclusivity only.
  - Benlysta and Toujeo: compound patent expired, no biosimilar named.
  - Breo Ellipta: a Paragraph IV trial is set for November 2026.
- **AstraZeneca and GSK ranges:** read from the HTML, below.
- **Jevtana:** generics are on the market, but no US entry date is given.

## AstraZeneca and GSK, read from the HTML

The two 20-F tables mark which year is the molecule's, and plain text loses the marks.
`tools/filer_dates/html_tables.py` reads the tables from the filing's HTML with each
cell's runs marked bold or italic: inherited from the enclosing element, with an
explicit style overriding it. GSK's spans set `font-style:normal` inside italic cells.

- **AstraZeneca.**
  - The key: "Bolded expiry dates relate to new molecular entity patents. The
    remaining dates relate to other patents."
  - The dates include granted SPC, PTE and paediatric exclusivity; regulatory data
    exclusivity is not shown.
  - A bold range is several molecule patents, so its end is the date; the existing
    Strensiq row already reads it that way.
  - Agree with the model: Tagrisso, Lynparza, Farxiga, Koselugo, Tezspire, Wainua and
    Beyfortus. This confirms the first-listed-year reading.
  - No US molecule patent listed: Lokelma, Fasenra, Airsupra, Breztri, Symbicort,
    FluMist and Imjudo.
  - Saphnelo's molecule patents run to 2029, inside its 12 years, so the floor sets its
    date. The floor exposed the fetcher bug below.
- **GSK.** "Patent expiry dates ... in normal text relate to the latest expiring new
  molecular entity patents ... Patent expiry dates in italics relate to other patents",
  and `*` marks a pending PTE.
  - Agree with the model: Apretude, Cabenuva, Zejula, Trelegy, Anoro, Bexsero and
    Shingrix.
  - Pending (not taken): Exdensur, Jemperli and Ojjaara.
  - Arexvy's 2030 is inside its 12 years.
  - Nucala lists no US molecule patent and Benlysta's has expired, so both rest on the
    floor, which the bug below had set late.
  - Breo Ellipta's molecule patent has expired. The model's 2031 comes from other
    patents, and a Paragraph IV trial on them is set for November 2026; it is kept
    until a generic is on the market.

No rows were added from either table.

### The 12-year floor counted from a later BLA

`fetchers/exclusivity_purplebook.py` computed each BLA's floor from that BLA's own
approval date. A later BLA from the same sponsor for the same molecule earns no new
exclusivity (42 U.S.C. 262(k)(7)(C)), yet it set a later floor. Now every BLA of one
sponsor's proper name counts from the earliest licensure among them.

Simulated on a copy (setting each asset's floors to its earliest, which is what the fixed
parser writes), four values move, +7,769mm net:

| product | floor before | after | NPV, mm |
|---|---|---|---|
| Benlysta | 2029-07-20 (the 2017 SC BLA) | 2023-03-09 | 3,124 to 9,461 |
| Actemra | 2025-10-21 | 2022-01-08 | 2,520 to 6,726 |
| Nucala | 2031-06-06 | 2027-11-04 | 3,866 to 2,262 |
| Saphnelo | 2038-04-24 (the 2026 SC BLA) | 2033-07-30 | 4,490 to 3,320 |

The real book takes it at the next Purple Book fetch. This environment's proxy refuses
the host, so it could not be refetched here.

The two rises come from a date that falls before the forecast's first year: the loss
then sits in the base, with no erosion.

- **Actemra:** right, since its US biosimilars launched in 2024.
- **Benlysta:** no biosimilar is filed, so it now runs with no cliff. The legal date is
  right; whether to model a biosimilar before one exists is a curated call, not a
  reading of the filing.

## Not covered

- **Roche and Bayer** are not SEC registrants: 31 valued products without a row.
- **Next season:** rerun when the FY2026 reports file.
  1. `get_annual.py <dir> TICKER:CIK ...`
  2. `snippets.py`
  3. The brief.
  4. `verify.py`.
