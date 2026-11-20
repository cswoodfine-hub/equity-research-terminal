# Equity research terminal

A research terminal for 75 biopharma companies, read on three engines: big pharma,
biotech, and cell and gene. One refresh pulls live and near-live data from free sources,
stores a timestamped snapshot, computes what changed since the last snapshot, and renders
charts, derived analytics and a short written note per company. On top of the data sits a
valuation: each asset forecast from patients and price to a risk-adjusted value, and each
company read as a range across lenses.

The differentiator is change detection and synthesis over free data, not raw breadth. A
value is what a source reported or it is absent: nothing is estimated to fill a gap.

- [CLAUDE.md](CLAUDE.md): the rules of the project and of each data source.
- [docs/design/](docs/design): the contract for each tab, with notes on what was built.
- [docs/ROADMAP.md](docs/ROADMAP.md) and [docs/ACTION_PLAN.md](docs/ACTION_PLAN.md): where it is going.

## Quick start

```bash
./run.sh          # or: make dev
```

`run.sh` creates the venv, installs dependencies, builds and seeds the database if
needed, and starts the API on 8000 and the UI on 8501. Set `SEC_USER_AGENT` in `.env`
first (a real identifier, for example `Your Name your@email`): EDGAR blocks requests
without it. Everything else in `.env.example` is optional. The app runs with no model
key and the notes fall back to their rules layer.

```bash
make verify         # the suite with a real exit code; what the pre-push hook runs
make hooks          # install that hook
make test           # the suite plus the ten network tests of test_refresh.py
make refresh        # pull every source for the universe (needs the API up)
make refresh-daily  # the same with no server; logs to logs/
make tearsheets-all # a one-page tearsheet for every company, to exports/
```

By hand:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -c "import db; db.init()"          # schema and migrations, idempotent
python seed.py                            # load the universe, resolve CIKs
uvicorn main:app --reload                 # API on 8000
# in another shell, from the repo root:
streamlit run frontend/streamlit_app.py   # UI on 8501
```

The database is `backend/er_tool.db`; `ER_TOOL_DB` overrides it. It is never committed.

## The app

A Streamlit client over the JSON API. One company is selected in the top bar and the
address carries it (`?engine=pharma&ticker=AZN`). Every chart is hand-built SVG from
`frontend/components/charts.py`; colour, type and spacing come from one token set
(`frontend/assets/tokens.css`, mirrored in `frontend/components/tokens.py`).

The tabs depend on the engine and on whether the company sells anything:

| Tab | What it holds | Shown for |
|---|---|---|
| Universe | The ranked change feed, prices and catalysts across the engine | all |
| Key insights | The morning note and the company at a glance | all |
| Prices | The price chart | all |
| Financials | The three statements at every period the filer tags | all |
| Pipeline | Trials by asset and indication | all |
| Portfolio | Revenue mix and loss of exclusivity | big pharma, and biotech once the company markets a product |
| Catalysts | Dated events ahead and the readouts behind | all |
| Forecast | The company and its assets year by year, and what the value is made of | all |
| Themes | Coverage by modality across companies | biotech, cell and gene |
| Runway | Cash against burn | cell and gene, and companies with nothing on sale |
| Comps | Companies (scorecard, figures, table) and pipelines; on big pharma also indications and disease areas | all |
| Holdings | Your own Trading 212 account beside the model. The same whichever company is picked | all |

## Where the data comes from

Every source is one module under `backend/fetchers/`. All are free; one reads a login
of your own (Trading 212, read only) and one is an optional paid dataset (FMP consensus).

| Source | What it gives |
|---|---|
| Yahoo chart data, ECB, FRED | Prices and benchmarks, FX, the rates behind discount rates |
| SEC EDGAR | Reported financials, filings and their text, product revenue from the Financial Statement Data Sets |
| The filers' own workbooks, ESEF reports | Financials for the two filers outside the SEC (Roche, Bayer); ESEF is the route for any other EU filer |
| ClinicalTrials.gov | Active studies, completed studies, posted results |
| openFDA, DailyMed, EMA, PMDA | Approvals and labels in the US, Europe and Japan |
| FDA Orange Book and Purple Book, Paragraph IV list, USPTO | Patents, exclusivity, generic challenges, term extensions |
| CMS and Medicaid | Part D prescribing, formulary coverage, spending, negotiated prices, Medicaid utilisation |
| RxNav | The drug codes the payer files are keyed on |
| Company IR feeds and pages, FDA feeds, Federal Register | Press releases, FDA announcements, advisory committees |
| Google News headlines | Deals the filings never name |
| Nasdaq analyst pages, FMP | Street consensus |
| The daily pulse | An AI-written summary of the trade press, labelled as such, for news only |

What no source publishes is curated by hand in `data/*.csv` and `data/assumptions/`,
each row with its source.

## Refreshing

Each source has its own freshness window, so a refresh inside it is a no-op for that
source and says so. Snapshots are written on every run regardless.

**Refresh only before 08:00 UTC or after the US close.** A refresh while a market is
open stores an intraday price as that day's close, and no later run corrects it.

The schedule is `.github/workflows/refresh.yml`:

- 06:00 UTC daily: start from the database the last run published (or rebuild it from
  the committed history), seed, refresh the universe, export the history to
  `data/history/*.ndjson`, commit it, and publish the database for the deployed app.
- 10:00 UTC on weekdays: read the daily pulse and publish. It fetches no source.

The binary database is never committed. The history that no source can hand back
(snapshots, detected changes, catalysts, notes) is committed as NDJSON, so any machine
can restore it:

```bash
git pull
make history-rebuild
```

The workflow needs a repository secret `SEC_USER_AGENT`. Model and openFDA keys are
optional.

A local schedule is also possible. `deploy/com.novatalis.ertool.refresh.plist` is a
launchd job that runs `deploy/run_refresh.sh` at 06:00. Its paths are absolute and were
written for another machine, so edit them before installing it. A launchd job has no
user session: if the repo sits in a folder macOS protects (Documents, Desktop, iCloud
Drive), `/bin/bash` needs Full Disk Access or the run fails with a `PermissionError`.

## Deployment

`streamlit_cloud_app.py` runs the API and the UI in one process for Streamlit Cloud. A
fresh container has no database, so it looks for the published one first and says which
it found. An empty universe reads as an empty universe.

## Generated notes

The what-changed feed has two layers. The rules layer always runs. The note layer
summarises one company's slice of it into a short paragraph.

Every model call goes through `backend/llm.py`. Groq (`GROQ_API_KEY`) and Google Gemini
(`GEMINI_API_KEY`) have free tiers and are called over REST; Anthropic
(`ANTHROPIC_API_KEY`) uses its SDK. With several keys set the first present wins, in
that order, and `LLM_PROVIDER` pins one. The notes default to Gemini
(`NOTE_LLM_PROVIDER`). The model is given only the feed items and told never to invent
a number; the response records which model wrote the note.

With no key the note is a deterministic list of the flagged items and its model reads
`rules`. If the model errors, the note falls back to the rules layer and reports the
error.

The model is also used to read stated facts out of filing, label and press text: PDUFA
dates, trial readouts, guidance, deal terms. Nothing it returns is trusted on its own.
For a PDUFA date, the date must parse and sit in a plausible review window, the product
must appear in the filing, and the quote must appear there near-verbatim; a row that
fails is dropped. The model never sets a value, a forecast or a rule.

The feed needs two refreshes of a company to show anything: the first sets the
baseline and the next detects differences. A first-seen filing or approval is reported
only when its own date is within the last 180 days, which keeps back catalogue out.

## A few endpoints

```bash
curl localhost:8000/health
curl -X POST 'localhost:8000/refresh?scope=all'      # the whole universe
curl localhost:8000/runs/latest                      # the last refresh
curl localhost:8000/changes                          # the ranked change feed
curl localhost:8000/companies                        # the universe
curl localhost:8000/engines                          # the three engines
curl localhost:8000/companies/LLY/forecast           # every forecast of one company, summed
curl localhost:8000/companies/LLY/forecast-board     # the same, laid out by year
curl localhost:8000/companies/LLY/competitors        # who sells against its products
curl localhost:8000/comps/valuation                  # the Comps tab's payload
curl 'localhost:8000/as-of?date=2026-07-01'          # the universe as of a past date
curl -X POST localhost:8000/companies/LLY/tearsheet  # one page, to exports/
```

`backend/main.py` holds the rest.

## Reading the numbers

- A blank is no free data, not zero. A line a filer does not tag is a dash.
- Foreign names are quoted by their US ADR (Roche as RHHBY, Bayer as BAYRY), so a bare
  home ticker never resolves to an unrelated US company.
- Product revenue comes from the SEC Financial Statement Data Sets. The company-facts
  API collapses every XBRL dimension and returns the consolidated revenue line alone;
  the quarterly bulk sets keep the product dimension. A filer that tags no product axis
  shows none.
- A primary completion date in the past is usually normal. ClinicalTrials.gov marks each
  date actual or estimated and the app stores which: an actual date that has passed
  means the endpoint was reached; an estimated one that has passed is a forecast missed.
- Part D and Medicaid amounts are gross of rebates. They are volume, never revenue.
- A deal value is announced consideration, milestones included, never the cash paid.

## Tests

```bash
make verify
```

About 4,750 tests in six to eight minutes (17 November 2026). They do not touch the
network; only `backend/tests/test_refresh.py` does, and `make verify` leaves it out.

Two parts are skipped quietly when their tool is missing, so a green run has not tested
them: the app tests need the API on 8000, and the JavaScript tests of the Comps frame
(`frontend/tests/compsval/`) need `node`.

## Where things are

| Folder | What is in it |
|---|---|
| `backend/` | The API, the fetchers, the model, the tests |
| `frontend/` | The Streamlit app and its components |
| `data/` | The universe, the curated registers, the assumption seeds, the committed history |
| `docs/design/` | The contract for each tab |
| `docs/research/` | Dated research notes and the rows they produced |
| `docs/PRD.md`, `TERMINAL_OVERVIEW.md` | The July 2026 spec and tour. History: both describe the first build, not this one |
| `work/` | Finished working papers. No code reads them; data files cite them as sources |
| `archive/` | Superseded documents |
