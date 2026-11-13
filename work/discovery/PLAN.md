# Discovery: early-stage research, scored for translation and commercial relevance

Status, 2026-11-13: sources verified and the feasibility backtest run three times
(`RESULTS_STEP1.md`): with SEC Form D and UK Companies House added as company outcomes,
then with OpenAlex author records, which let lab heads be ranked as people. A day-one score matches iCite for clinical translation. For company activity
the authors' record carries the signal (42% of papers by a prior Form D officer lead to
another filing, against 5%), and first-time founders stay hard to rank. So the thing to
build is a ranked feed plus a watchlist of people and labs, not a commercial score. No
app code yet.

## What it is

A section for a VC reader. It takes in every new cell and gene therapy (CGT) paper and
preprint, scores each on evidence the paper itself states, and then watches it: a paper
"lights up" when commercial footprints accumulate around it (a grant to a small business,
a patent, a trial, a new company). Scope: CGT first; US, UK and Europe.

Volume (Europe PMC counts, 2026-11-13): 9,878 CGT papers and 1,708 CGT preprints first
published in 2025, about 32 a day. Small enough for rules and free model tiers.

## Rules it keeps

- The score works with no model key. Rules and a classical model do the ranking; a model
  only extracts facts from a shortlist, and every fact carries a verbatim quote that the
  code checks against the text.
- Nothing is fabricated: a field the paper does not state is null.
- Nothing ships before the backtest says the score beats the baseline.

## Sources, as verified on 2026-11-13

| Source | Host | State | Notes |
|---|---|---|---|
| Europe PMC search | www.ebi.ac.uk | works, keyless | Papers and preprints in one index; `resultType=core` gives abstract, authors, affiliations, MeSH, grants. The `MESH:` field does not exist; use `KW:` or `TITLE_ABS:` |
| Europe PMC annotations | www.ebi.ac.uk | works, keyless | Text-mined genes, diseases, organisms |
| PubTator3 | www.ncbi.nlm.nih.gov | works, keyless | Entities per PMID, BioC JSON |
| PubMed E-utilities | eutils.ncbi.nlm.nih.gov | works, keyless | `<CoiStatement>` is its own field |
| PMC open access (BioC) | www.ncbi.nlm.nih.gov | works, keyless | Full text; a commercial-use subset exists |
| bioRxiv and medRxiv API | api.biorxiv.org | works, keyless | 30 rows a page (not 100). `details` gives licence, category, corresponding institution, JATS link, published DOI; `pubs` links preprint to paper |
| NIH iCite | icite.od.nih.gov | works, keyless | `apt` (potential to translate), `cited_by_clin`, human/animal/molecular shares. The baseline |
| NIH RePORTER | api.reporter.nih.gov | works, keyless | POST search; SBIR and STTR by activity code (R41 to R44), PI names, organisation |
| UKRI Gateway to Research | gtr.ukri.org | works, keyless | Includes Innovate UK awards to companies |
| CORDIS | cordis.europa.eu | works, keyless | Bulk project files (H2020, Horizon Europe) |
| Companies House bulk | download.companieshouse.gov.uk | works, keyless | Company snapshot and persons with significant control (33 files of about 82 MB). A university's tech transfer arm as a controlling party marks a spinout |
| ClinicalTrials.gov | clinicaltrials.gov | works, keyless | Already in the terminal |
| FDA orphan designations | www.accessdata.fda.gov | page answers | Search form; not yet read |
| EMA orphan designations | www.ema.europa.eu | answers, rate limited | Listed among the EMA's medicine data reports |
| SEC EDGAR | www.sec.gov | 403 without an identifier | Needs `SEC_USER_AGENT`, which is unset in this environment |
| OpenAlex | api.openalex.org | needs a free key | Keyless calls now share one daily budget per IP, and it was spent. A key is requested by email |
| Semantic Scholar | api.semanticscholar.org | 429 keyless | Free key by form, for embeddings and summaries |
| SBIR.gov API | api.www.sbir.gov | 403 from the service | RePORTER covers the NIH part of SBIR and STTR |
| HESA spin-out register | www.hesa.ac.uk | bot challenge | Not readable by script; Companies House control data is the route |
| Reliance on Science | zenodo.org | works, 1.4 GB | Patent to paper citations. **CC BY-NC 4.0: non-commercial**, so not for a product |
| Europe PMC patents | www.ebi.ac.uk | gone | `SRC:PAT` returns nothing |

Not yet probed (hosts not allowed here): Open Targets, Orphadata, ORCID, CIRM, the Cell and
Gene Therapy Catapult, Crossref, PatentsView.

## Open decisions

1. **Patent label.** Reliance on Science is non-commercial. The clean route is inventor
   and author matching on USPTO data, which is public domain but needs a free USPTO key
   (`api.uspto.gov`, sent as `X-Api-Key`). Not set up, so patents are not in the
   backtest.
2. **OpenAlex key.** Active from 2026-11-13, $1 of free use a day; the whole corpus cost
   under 15 cents. It is in the backtest (author identifiers, preprint addresses, the
   senior author's prior output). Semantic Scholar's is still open and not needed.
3. **SEC identifier** for Form D: agreed 2026-11-13, and the outcome is in the backtest.
4. **Companies House API key** (free). The bulk files give owners of 25% or more only;
   the API gives directors, which is where a diluted academic founder shows.

## Step 1: the feasibility backtest

- **Corpus.** CGT papers and preprints first published 2017 to 2020 (about 20,500 and
  1,900), from Europe PMC, by title and abstract terms.
- **Outcomes, within three years of publication, each from a free source:**
  - cited by a clinical article (iCite);
  - an SBIR or STTR award whose PI is an author (RePORTER), US;
  - a biotech Form D naming an author as officer or director (SEC data sets), US;
  - a new UK research company an author controls (Companies House bulk files), UK;
  - not done: an Innovate UK or EU company grant naming an author (CORDIS carries no
    investigator names), and a patent (needs the USPTO key).
- **Score, from what was knowable on publication day:** rule features (model ladder from
  species tags, CGT terms such as vg/kg, NHP, neutralising antibodies, off-target
  analysis; conflict-of-interest phrases) plus a word-frequency model, trained on 2017
  and 2018 and tested on 2019 and 2020.
- **Baseline to beat:** iCite's `apt`.
- **Measure:** the share of outcomes captured in the top 1%, 5% and 10% against the base
  rate. Base rates are low, so the top of the list is what is judged.
- **Bias, stated:** name matching misses renamed or licensed-out work; grants and trials
  are the visible outcomes, not every commercial one.

Stop after the report. The section is built only if the top of the list beats the baseline.

Outcome: it does for company activity and ties for clinical translation. See
`RESULTS_STEP1.md` for what that supports building and what it does not.

## Later steps

2. Daily feed: ingestion, extraction with quotes, the score, a Discovery tab.
3. Linkage and alerts: the "lights up" change feed for papers and labs.
4. The VC layer: likely buyers and comparable deals from the terminal's own tables,
   white space, lab watchlists, memo stubs.
