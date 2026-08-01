# Build log, overnight autonomous build

## Smaller trial ticks; centre the charts in their column — 2026-07-26 22:40
The horizon trial tick was as wide as its month dash, so member and group competed. It
is now narrower (tick width 3 against the month dash), so a trial reads as a small mark
under the wider green month marker.

Charts are fixed-width SVGs that sat jammed against the left of a wider column. The
chart-mount now centres its SVG and lets an over-wide one shrink to fit without
distorting, so a chart sits balanced in its space rather than left-aligned. The horizon
rail keeps its own class and is left as is; tables already stretch to the column.

## Deal dates from the release; the horizon opens the study — 2026-07-26 22:00
Two follow-ups on the horizon and the deals.

A deal now carries its announcement date, not the filing date, when the release states
one. The extractor reads the date and keeps it only when it appears in the filing in a
common written form, so a date is read from the text and never invented; when the text
states none the filing date stands. On the re-backfill Vertex and Crinetics moved to
their 2026-07-06 announcement, Biogen and Apellis to the 2026-03-31 agreement, Pfizer and
Metsera to 2025-11-04. Lilly's four April acquisitions stay on the filing date, because
the earnings release that lists them states no date the guard could match, which is the
honest result rather than a guessed one.

The horizon rail's clicks changed. A trial tick no longer pins; it opens the study on
ClinicalTrials.gov in a new tab, and a hover previews the full trial title, which the
rail truncates to twenty characters. Exclusivity ticks, which have no study page, keep
the pin. The catalyst spine item carries the study URL and the full title for this.
Suite 426 green.

## Key insights, restructured; the readout budget fixed — 2026-07-26 20:45
The Key insights tab led with "changes since the last refresh", a list of snapshot-diff
lines (trial status and date wording) that read as jargon. It is dropped. The view is now
broken into the things that move a case: catalysts inside 60 days, deals, trial readouts,
and loss of exclusivity, each its own section. Deals and readouts are read from two new
endpoints (/companies/{ticker}/deals and /readouts) over structured readers; the deals
reader de-duplicates a deal filed several times to one row, and the readout reader returns
the signed Phase 2/3 rows. A deal renders as a type badge, the counterparty, the value
where known and the area; a readout as a check or cross, the phase and sign, the drug and
the sentence that carried it, coloured by outcome.

The trial-readout extractor carried the same 700-token budget that truncated the deal
JSON, so gemini-flash's reasoning was eating it and a real readout was silently stored as
"none". Raised to 2048 with the reasoning capped and re-run: the signed count went from 7
to 23 (20 positive, 3 negative), surfacing GSK camlipixant, NVO CagriSema and semaglutide
misses, AZN baxdrostat and tozorakimab, the NVS Pluvicto and Scemblix wins and more.

A note on the dates: a deal's date is the filing date, not the announcement date. Lilly's
four April acquisitions all read 2026-04-30 because that is when the earnings 8-K that
disclosed them was filed. Extracting the true announcement date is a later step; it
carries a date-fabrication risk the filing date does not. Suite 423 green.

## Deals: read the earnings release and the multi-deal filing — 2026-07-26 19:30
The user asked why Lilly's $7bn Kelonia acquisition was not showing. EDGAR full-text
search settled it: Lilly filed no standalone acquisition 8-K. It listed four
acquisitions, Orna, Centessa, Kelonia and Ajax, in a line of its Q1 earnings release,
inside an earnings 8-K (item 2.02), in an exhibit named descriptively rather than ex99.
The deal reader missed it three ways: it skipped earnings 8-Ks, it found an exhibit only
by the ex99 name, and it read one deal per filing.

All three are fixed. The candidate filter now includes earnings and other-events 8-Ks;
the press release is resolved as the largest content document in the filing folder, so a
descriptively named earnings release is found; and the extractor lists every deal a
filing announces, stored one row per deal against a no-longer-unique accession
(migration 011 relaxed, the table rebuilt in place since it is derived). The guard is
unchanged: each party and quote must be in the text, and a value is kept only verbatim.
A deal can now be filed twice, agreed then completed, or recapped in a later earnings
release, so the note de-duplicates on the counterparty, keeps the earliest date, when the
market first saw it, and fills the value from whichever filing states it.

Live: the LLY note now carries the Kelonia acquisition into in vivo CAR-T cell therapies,
alongside Orna, Centessa and Ajax, and the clean single-deal cases, Gilead/Arcellx,
Vertex/Crinetics, Biogen/Apellis, still read as before. Suite green.

## Deals extractor: name US M&A from the 8-K exhibit — 2026-07-26 18:30
The news-headline deal path named a foreign filer's 6-K but a US 8-K names only the item
category, "Material agreement signed", never the party. The counterparty, the price and
what the deal is for live in the EX-99 press release the 8-K attaches. deals.py reads it,
the same way the trial-readout and PDUFA extractors read theirs, over the model seam and
into a deals table (migration 011). It runs on new filings in the refresh, so it spends
credits only when a deal is genuinely new.

The guard is the same as the readout reader: the counterparty and the quoted sentence
must both appear in the filing, so a name from the model's own knowledge cannot become an
event, and a value is kept only when it appears verbatim, so a price is never rounded or
invented. gemini-flash truncated the JSON at a small token budget, the note's problem
again, so the budget is 2048 with the reasoning capped. notecontext now reads the deals
table, de-duplicates the stages of one deal on the counterparty, and trims a value or a
party that carried its whole legal clause down to the headline.

Backfill of the live database, 12 filings read, 7 deals found: Gilead's $7.8 billion
acquisition of Arcellx, Vertex and Crinetics at $85 a share, Biogen and Apellis at $41,
GSK and Nuvalent at $124, plus the GSK and AstraZeneca collaborations. The GILD note now
reads "Gilead acquired Arcellx for 7.8 billion USD, bringing in innovative immunotherapies
for patients with cancer". Suite 419 green; adds a deals test file.

Honest gap: the user's example, Lilly's Kelonia acquisition, is in no LLY filing on EDGAR
in the data window (latest LLY 8-K is 2026-05-20, no acquisition item), so it is not a
fetch we dropped; it will appear when Lilly files the 8-K and a refresh reads it.

## Note: name the deals, drop the risk-factor churn — 2026-07-26 17:20
Two pieces of feedback on the morning note. The line "143 additions and 332 removals
in the Form 10-Q" was data-dumpy: a count of changed risk-factor paragraphs is filing
churn, not a signal, and means nothing to a reader. And the note said nothing about
M&A, the thing that most reshapes a portfolio.

Both are now handled from data already in the database. notecontext gained a deals
block read from the IR news feed, whose headlines name the counterparty and often the
area in the company's own words, so there is no model call and no invented party: GSK
completes the acquisition of Nuvalent and a collaboration with CTTQ for bepirovirsen;
AstraZeneca licenses a novel EGFR inhibitor and agrees an obesity and T2D deal with
CSPC. A deal is announced, tendered and completed under three headlines that share the
target's name, so they are de-duplicated to the latest state by keying on the
distinctive words once the company's own name and the deal vocabulary are removed. A US
8-K item that names no party still matches nothing, which is correct.

The note prompt now names a deal, its type and what it adds using only what the headline
and the snapshot support, and it is told to drop bare risk-factor counts and mention a
filing's risk factors only when the feed says what specifically changed. The model note
also runs off the snapshot alone now, so a company with a quiet change feed still gets a
real note. Live: the GSK note leads its business-development on Nuvalent and CTTQ, the
AZN note ties the EGFR and CSPC deals to oncology and metabolic targets, and the LLY
note no longer carries a risk-factor count. Suite green; adds two deal tests.

## Daily auto-refresh at 06:00, note left on demand — 2026-07-26 16:10
The whole session's work was landed on main by fast-forward (main was 94 commits
behind at 51ce799; no merge commit, no conflicts, the live database untouched since
it is gitignored). The permanent checkout is now the home the schedule runs from.

A macOS LaunchAgent, deploy/com.novatalis.ertool.refresh.plist, runs the refresh at
06:00 local against the database the app reads (ER_TOOL_DB), so the morning's prices,
financials, filings, trials, approvals, exclusivity books and the change feed are
ready before the desk opens. A 06:00 missed while the Mac is asleep runs on the next
wake. The .env was copied to the checkout root so env.py finds the keys.

The note is deliberately not part of the schedule. run_refresh_all never regenerated
notes, and it stays that way on the user's instruction: a note is a wholesale Gemini
call per company, wasteful to run daily when nothing changed, so it stays the
on-demand button. The three extractors the refresh does run, trial readouts, PDUFA
dates and biologic LOE, only read filings they have not seen, so they spend credits
only when there is genuinely new filing text, often nothing on a quiet day.

One macOS obstacle, handled honestly. The repo lives under ~/Documents, a TCC-protected
location, so the first kickstart failed with PermissionError on pyvenv.cfg: a launchd
job has no user session and cannot read there, nor prompt for access. The job now runs
through deploy/run_refresh.sh so a single stable binary, /bin/bash, is the one that
needs Full Disk Access; the python it launches inherits it. The agent is installed and
loaded, and once Full Disk Access was granted to /bin/bash in System Settings the run
went through: a kickstart wrote refresh run 27 (partial, the only error a benign 404
for the not-yet-published 2026 Q3 SEC dataset) and advanced the database, with no note
regenerated and the extractors finding nothing new to read. README documents the grant,
install, test, time change and removal.

## Morning note on Gemini, with a company snapshot — 2026-07-26 15:30
The morning note was reading like a machine walking a list: it opened "The most
significant item is", never carried a single company number, and ran on whatever
the global LLM_PROVIDER happened to be (Groq). Two changes.

**Pinned to Gemini, decoupled from the bulk classifiers.** llm.provider,
model_name and complete take an optional prefer, so the note pins Gemini while the
PDUFA and readout classifiers keep sharing the global LLM_PROVIDER. The pin
degrades to the normal selection when Gemini has no key, so it never fails the
note. NOTE_LLM_PROVIDER overrides the default. gemini-flash-latest is a thinking
model whose reasoning ate the whole output budget and truncated the note
mid-sentence; complete gained an optional thinking_budget that caps the reasoning
(512, soft) with maxOutputTokens raised to 4096, and the note now completes.
Groq and Anthropic ignore both new arguments, so no existing caller changed.

**A company snapshot to lead with.** notecontext.py reads a factual snapshot from
the tables a refresh already fills: reported revenue with its year-on-year change,
net income, R&D, the latest quarter, the share move over one and three months, and
recent signed Phase 2/3 trial readouts. Every line is a stored fact; a missing one
is left out, never estimated, and a foreign filer keeps its own currency (NVO in
DKK). The prompt was rewritten from a list-reader into an analyst voice: lead with
the number that moves the case, connect a loss of exclusivity to the revenue it
exposes and a readout to its programme, write trials in prose rather than pasting
the feed's bracketed detail line, and hold to two paragraphs. The absolute
no-fabrication guard and the house style stay verbatim.

Verified live on the paid Gemini key: LLY leads on FY2025 revenue +45% to 65.2B
USD and net income +95%; NVO note carries its CagriSema Phase 3 miss; PFE reads
the quarter stabilising after a full-year contraction; MRK writes "revenue exposed
is no free data" where the LOE revenue is unknown. Notes complete with no
truncation and no bracket dumps. Suite 411 green (new test_llm.py, test_notecontext.py,
and a snapshot-reaches-the-prompt test in test_insights.py). The 8010 API was
restarted on the new code.

## Roadmap tier 1 to 3 — 2026-07-25 11:30
Working down the additions roadmap in order.

**Item 1, GitHub Actions daily refresh (done).** history.py exports the
app-produced tables to data/history/*.ndjson (id-ordered, git delta-friendly)
and rebuilds from them with FK off; refresh.yml runs the git-scraping cycle
daily. Round-trip verified against 5988 live snapshots; a rebuilt db lets the
diff continue without replaying. Needs a GitHub remote and SEC_USER_AGENT secret
to activate, both documented.

**Item 2, DailyMed label changes (done).** dailymed.py polls SPL version history,
parses the LOINC 34067-9 indications section, and extracts the population over
the LLM seam into age floor, age ceiling, indication count and a phrase.
Migration 003; the diff turns a version bump into label_change / new_indication /
population_expansion with the numbers in the headline. A Labels tab. Verified
live for LLY: 33 labels, 8 populations resolved (the rest hit the free model rate
limit on a first-run burst and self-heal, since only changed labels re-extract).

**Item 3, efficacy supplements plus the CBER path (done).** parse_supplements
reads the approved EFFICACY submissions already in the drugsfda payload; migration
004 stores them; the diff detects a newly seen recent one as efficacy_supplement.
Verified live: 347 real supplements (LLY 103, MRK 245). The CBER gap is stated
plainly in the view rather than scraped: drugsfda is CDER only, and cell and gene
therapies are already covered by the DailyMed labels and the Purple Book.

**Item 4, FDA announcement feeds (done).** rssfeed.py parses the FDA press,
drug and MedWatch RSS feeds; fetchers/news_fda.py is one universe fetcher that
matches each item to a company and writes it to the news table, so an approval
or a supplement shows here as the announcement that corroborates it. It reaches
the CBER products drugsfda cannot: the sickle-cell gene-therapy press release
binds to VRTX through Casgevy. A /regulatory-news endpoint and an FDA
announcements section on the Universe tab, matched items first so a bound
approval never falls below agency housekeeping; the News tab gains a source
column. Verified live: 58 FDA items, 6 correct company matches (VRTX Casgevy,
ROG Xofluza, SNY Tzield, GILD Hepcludex, JNJ Abiomed), 774 EDGAR rows untouched.

Company matching is the hard part and the first live run bound wrong: the
product-revenue parser had written 10-K segment lines into brand_name (GENERAL,
Liver Disease Products Vemlidy, Children'S Allegra Allergy), so any title with a
common word stuck to a company. Fixed by trusting only a single coined word as a
brand token: a brand_name with a space is a revenue label or a two-drug combo
and there is no safe way to know which word is the brand, so it is dropped rather
than guessed, and a lone segment or ingredient word is dropped too. Re-ran clean.

EMA's general news RSS was retired; only per-medicine feeds remain, so the EU
indication-extension signal is deferred to item 7, the EPAR downloadable data,
and noted rather than scraped.

**Item 5, AdComm calendar plus Paragraph IV challenges (done).** Two sources, one
theme: the regulatory dates and risks the LOE and catalyst views were missing.

fedreg.py reads FDA advisory committee meetings off the Federal Register API,
whose notice title carries the committee, application number, sponsor and product
in a stable template and whose dates field carries the meeting date. The fetcher
stores the whole scheduled calendar (migration 005) and writes the universe
matches as AdCom catalysts with is_curated=0, matched on the application number
against internal_code or on the sponsor and product names. A /adcomm-calendar
endpoint and a calendar section on the Universe tab. Verified live: 52 scheduled
meetings, 0 in the universe right now, which is honest; the two near meetings are
both small-biotech gene therapies. User-fee and board meetings are filtered so
only real panels show.

paragraph_iv.py reads the FDA Paragraph IV certifications list, the generic
filings that challenge a small molecule's patents years before expiry. The list
is a PDF; pypdf extracts the text, whose rows reduce to a reference-drug NDA
number and the first certification date. Matched to an asset by that number
(migration 006), it gives the LOE view a challenged state between protected and
expired, in oxblood on the cliff table. Verified live: 1227 certifications, 361
matched to the universe, 160 of them still protected and so shown as challenged;
biologics correctly show none, since Paragraph IV is a small molecule mechanism.

Two parsing bugs found and fixed against the live payloads. The application-number
match first failed because \bNDA\b needs a word boundary the concatenated
internal_code "NDA21780" does not have; a lookbehind fixed it and still rejects
the NDA inside ANDA. The Paragraph IV list link first resolved to a guidance PDF
because the heading is named three times on the page; anchoring on the heading's
closing tag and taking the first media link after it fixed it. Both now have a
fixture that would have caught the bug.

Suite 377. Six migrations now (annotations, fx, labels, supplements, adcomm
meetings, patent challenges), all additive. pypdf added, pure Python, the one new
dependency and only the Paragraph IV list needs it.

**Item 6, CMS Medicare demand (done).** Company revenue is what a drug earned;
this is how many people took it. cms.py reads the CMS Spending by Drug data API,
Part D for retail pharmacy and Part B for clinic-administered drugs, each with
per-drug, per-year spending, claims and distinct beneficiaries. The fetcher
matches a drug to an asset by brand name (migration 007) and stores the five
published years as a demand time series; demand.py rolls it up per drug with the
year before for direction. A /companies/{ticker}/demand endpoint and a Medicare
demand section on the Approvals tab, sorted by spending, the year-on-year move in
green or oxblood. Verified live: 4424 CMS rows, 3037 records across 568 universe
assets. Keytruda reads 5.99bn under Part B on 75,361 beneficiaries, Januvia
3.81bn under Part D on 828,288, and a drug that sits in both parts, like Eylea,
shows both. A beneficiary count CMS suppressed for privacy reads as a dash, never
zero, and the view says US Medicare only, so commercial and ex-US volume is
absent by construction.

Suite 382. Seven migrations now, all additive.

**Item 7, filing text diff (done).** The numbers in a 10-K change on their own
schedule; the words change once a year and say what management is worried about.
filingtext.py pulls two sections out of a filing, Risk Factors and MD&A, and
diffs one filing against the last of the same form at the paragraph level. A
per-company fetcher reads the primary document of the recent 10-K and 10-Q
filings already in the filings table, extracts the sections and stores them
(migration 008); the diff engine turns a rewritten risk factors section into a
change row that flows into the What Changed feed, and a /companies/{ticker}/
filing-text endpoint plus a section on the News tab show the passages that were
actually added.

Only risk factors is flagged. It is prose that turns over slowly, so what is
added or removed is a real signal; MD&A is rewritten wholesale every period, a
ratio of about 0.15 against the prior, so it is stored but never an event.
Verified live: ABBV 31 added and 22 removed year on year, MRK 72 and 58, and the
added ABBV passages are the new IRA pricing and most-favored-nation risks naming
Imbruvica, Vraylar and Botox as Medicare price-negotiation drugs, which is
exactly the paragraph an analyst wants surfaced.

Section extraction is the hard part and two live bugs shaped it. MD&A first came
back empty because the end pattern matched the many in-text cross-references to
"Item 8" inside the section; anchoring the end on the next section's own title,
"Quantitative and Qualitative Disclosures", fixed it. A section is named twice on
the page, in the contents and for real, so every candidate start is tried and the
longest run of text wins. Foreign 20-F filers lay their sections out under
different item numbers and are left for a later pass, stated in the view.

Suite 390. Eight migrations now, all additive.

**Item 8, valuation scaffold (done).** A marketed drug is worth, roughly, the cash
it throws off while still protected. valuation.py takes each product's latest
reported revenue, holds it flat, and discounts it over the years left to its LOE
at a stated 10%; post-LOE generic revenue is zero. No new table and no fetcher,
since every input, revenue, LOE and FX, is already on file. A
/companies/{ticker}/valuation endpoint and a Protected value section on the
Revenue at risk tab, with the rNPV per product and a company total.

Nothing is invented, so the gaps are named rather than filled. MRK reads a
protected value of 30.2bn across 12 products, and 43.6bn of revenue it cannot
value, Keytruda alone 31.6bn, because those are biologics whose only free
protection date is orphan exclusivity, which does not gate a biosimilar, so the
Purple Book gives no cliff to discount to. That unvalued number is shown as
prominently as the valued one; hiding it would be the dishonest reading. The
phase-to-probability benchmarks are documented as the framework for a pipeline
asset, but no free source gives a pipeline drug its peak sales, so the pipeline
carries no dollar value. USD is treated as identity rather than read from the FX
table, so a company reporting in USD values without a stored rate.

Suite 393. Still eight migrations; this layer is computation over what the earlier
items already collect.

**Item 8b, biologic LOE for the valuation (done).** The first cut left the
biologics unvalued, which for most companies is the larger half. A biologic's
cliff is patent-driven and no free source publishes it, so biologic_loe.py derives
one (migration 009): the later of the 12-year BPCIA reference-product exclusivity,
counted from the approval on file, and the biosimilar year the company states in
its own 10-K risk factors, read over the model seam with the same guard the PDUFA
extractor uses, a year only counts when a sentence in the filing names it. The
later of the two is right because a biologic is protected until both lapse, and it
turns the disclosure into a check on itself, since a disclosed year below the floor
is a misread. The valuation takes the later of this and any published Orange or
Purple date, and labels each product's basis.

The floor runs without a model, so MRK's protected value rose from 30.2bn to
39.3bn on the floor alone as Winrevair and others came in; the disclosure refines
it upward when a model answers. The Groq free tier's daily token budget was spent
by the day's other extractions, so the live disclosure pass returned nothing this
run and the biologics sit on the floor; the extractor was verified against Merck's
real 10-K text, which yields Keytruda 2028 and rejects a fabricated finding, and
it will populate on the next refresh. Keytruda's own floor, 2026, has already
passed, so it stays unvalued until that disclosure lands, and is named in the
unvalued list until then.

Suite 399. Nine migrations now, all additive.

**Item 8c, patent-section extraction for biologic LOE (done).** The first cut read
only Item 1A risk factors, where only Merck and Pfizer state a clean per-drug cliff
year. A drug's cliff is more often in Item 1's patent discussion and its patent
table, by generic name and as individual patents, so filingtext.patent_passages
harvests every line in the whole 10-K that pairs patent, exclusivity or biosimilar
language with a future year, the fetcher stores that as a patents section, and the
extractor now reads risk factors and patents together, matches a finding by brand
or generic name, and keeps the latest year for a product since protection runs to
the last patent. Verified live: the pass added JNJ Tremfya 2031, read out of the
patent discussion, which values it to 5.2bn of revenue over five years; the
universe protected value reads 1.33tn. Three products now carry a disclosed cliff
(Keytruda 2028, Tremfya 2031, Elrexfio 2036) and 39 biologics sit on the statutory
floor, which is the honest split: most 10-Ks simply do not commit to a per-product
year, and none is invented for them.

Suite 401. Still nine migrations; this reads more of a filing already fetched.

**Item 10, the signal backtest (done, final item).** The reason to keep the
snapshot history is that over time it becomes a labelled set of events whose worth
can be measured against what the stock did. backtest.py replays it: for each change
with a real event date, it takes the forward return over one day, one week and one
month, subtracts the equal-weight return of the rest of the universe over the same
window so a sector move does not read as signal, and aggregates the abnormal return
and hit rate by change type. A /backtest endpoint and a section on the Universe
tab.

The honest design choices are the whole point. An approval and a filing carry a
real event date, which can sit years before we first saw it, and the five-year
daily price series covers it; a trial status or completion-date change has only our
detection time and no forward window yet, so it is left out and said to be rather
than measured against a date that is not the event. Verified live: 37 of 90 changes
measured, dated 2026-02 to 2026-07. An FDA approval beat the sector 80% of the time
the next day and 70% the next week; a risk-factors change, which happens at every
annual filing, sat at 37 to 53%, correctly reading as noise. The view says in plain
words that tens of events are a direction and a hit rate, not a p-value.

Suite 403. Nine migrations. The additions roadmap, items 1 through 10, is complete.

**Follow-up: the run-up and the trial-readout signal.** Two additions to the
backtest on request. The first generalises the return to a window with an offset
before and after the event, adding the run-up: a three-month, one-month and
one-week window into the event alongside the day, week and month after. It sharpens
the approval read, into an approval the stock lags the sector by 3.4% over the
quarter and reacts only after, so an approval is not priced in.

The second is the biggest catalyst in the field, a pivotal readout, which carries a
sign the numeric diff cannot. trial_readouts.py classifies the 8-K and 6-K press
releases that announce Phase 2 and Phase 3 results, over the model seam with the
PDUFA extractor's guard: the drug and a result sentence must appear in the filing,
and a trial that is starting, submitted or approved is recorded as no readout so it
is not fetched again but is never signed. A US 8-K keeps the release in an EX-99
exhibit, resolved off the accession index; a foreign 6-K carries it directly.
Migration 010 stores one row per filing read; the backtest reads the signed ones
and splits the study into Phase 2 and Phase 3, positive and negative. Without a
model it does nothing and says so.

Verified live: 335 filings read, six positive and one negative Phase 2/3 readout
found, each with the verbatim result sentence, among them Novo's CagriSema Phase 3
miss, "the trial did not achieve its primary endpoint". The split reads the way it
should. Positive Phase 3 readouts, five of them, react +0.7%, +2.3% and +2.8% over
the day, week and month after, on a flat run-up. The negative one had the stock
already 44.7% below the sector over the month into it and falling further after. A
positive Phase 2 was priced in, a 9.9% run-up and nothing after. Small samples on a
young, capped filing history, and the view keeps saying so, but the sign lands
where a readout's sign should. Suite 408, ten migrations.

## Follow-up: the five V2 recommendations — 2026-07-25 07:20
All five items from the final message, implemented, tested, committed one concern
each on top of the overnight build.

1. **FX.** Migration 002 fx_rates + fetchers/fx_ecb.py pull the free ECB daily
   reference set (no key) as USD-quoted rates; revenue-at-risk gains USD absolutes
   and the tab a converted bar labelled with the rate date. NVO 224.5bn DKK reads
   as 34.2bn USD; GSK/REGN, whose currency does not resolve, stay null, never
   fabricated. 10 tests.
2. **Spine click.** Each spine tick is now an SVG anchor to ?ticker=X&sel=key (no
   script); the app pins the selected item's full detail above the tabs and draws
   the hairline to it. Keys are a stable content hash, so the selection round-trips
   through the URL and is shareable. Verified in the browser.
3. **/as-of field grain.** Reconstructs the financial report in force at the date
   and the approvals known by then, joined to current brands, not just counts.
   Verified: 16 financial snapshots and 908 approvals reconstructed at 2026-07-20.
4. **Scheduled refresh.** backend/scheduled_refresh.py runs the universe refresh
   directly, logs to logs/refresh.log, holds an overlap lock that reclaims a stale
   one; cron and launchd documented. 5 tests on the wrapper's own behaviour.
5. **Batch tearsheets.** tearsheet.build_all + make tearsheets-all wrote all 18
   with zero failures.

Suite 337. Ran the ECB fetcher once against the live database, which stored 30
real rates dated 2026-07-24; append-only, no other mutation.

## Phase 7: testing pass — 2026-07-25 05:40
- Full suite 319 green. No native Streamlit/Altair chart call anywhere
  (grep-confirmed; the one LineChartColumn is a table column, not a chart).
- All 18 tickers: 280 endpoint calls across every per-company and universe route
  returned 200; a builder sweep (revenue-at-risk + full tearsheet) ran clean for
  every ticker including ROG and BAYN; the loaded app showed zero stException
  nodes, which given Streamlit runs every tab body per pass proves all twelve
  tabs execute clean.
- No keys: provider() is None and the note falls back to the rules layer with no
  error. Empty database: schema-only API serves []/empty; the seeded-but-empty
  UI renders designed empty states on every tab, zero exceptions.
- Layout verified at 1280 and 1920; nulls render as "no free data" or a dash;
  focus is a visible outline via :focus-visible on every control.
- Not browser-exercised: the time-machine sidebar interaction (the automation
  layer toggled the Streamlit sidebar unreliably), though asof.state_at is unit
  tested for reconstruction, bad-date rejection and prehistory, and /as-of
  returned 200. The only console errors are WebSocket-reconnect noise from the
  many dev-server restarts, not app errors; fonts and CSS are inlined so there
  are no external asset requests to 404.

## Phase 8: scripts and docs — 2026-07-25 06:00
- run.sh (venv, deps, db init + seed, both processes, Ctrl-C stops both) and a
  Makefile with dev/test/refresh/tearsheets/clean. README rewritten around the
  twelve views, the component layer, and the new endpoints.
- Screenshots: live Streamlit does not capture reliably headless (snaps the
  loading skeleton) and its tabs are not URL-addressable, so docs/screenshots
  holds the deterministic artefact renders instead (tearsheet, analyst views,
  the primitive gallery, the spine), which draw the same components; noted in
  docs/screenshots/README.md. Every tab was verified in a real browser through
  the build.

## Phase 6: tearsheet and brief polish — 2026-07-25 05:05
- One-page A4 tearsheet per company to exports/, self-contained (inline styles,
  inline SVG from the shared primitives), POST endpoint plus a Key insights
  button. LLY/BMY/MRK generated; LLY verified to print to exactly one A4 page.
- Backend imports the frontend component layer over a sys.path insert; safe
  because components/ has no Streamlit dependency, and it keeps one source of
  chart truth for both the screen and the print sheet.
- exports/*.html gitignored (generated artefacts), directory kept with .gitkeep.
- Suite 319 green.

## Phase 5: new analyst views — 2026-07-25 04:30
- Universe brief as landing tab, revenue at risk (waterfall + universe bars),
  slippage dumbbell, catalyst grid with accept control, screen (comps + derived
  columns + inline sparkline). Plus annotations inline on changes, time machine
  with banner, and ?ticker= shareable URL from the should/nice-to-have list.
- Deviation recorded in phase 3 stands: the universe revenue-at-risk view is a
  per-company share bar, not a currency-stacked bar, because no FX source exists.
- Verification: the Streamlit automation layer would not switch tabs reliably
  (ref-to-pixel mismatch), so the five new charts were verified by rendering
  them from the live 8010 API into a headless-Chrome sheet, all correct
  including the honesty states (hatched no-free-data bars for ABBV/BAYN/ROG/SNY,
  true 0.0% for protected-but-not-soon). The app itself was confirmed to mount
  all twelve tabs with zero stException nodes: Streamlit runs every tab body on
  each script pass, so a clean load proves every tab executed without raising.
- Suite 315 green.

## Phase 4: tab rebuild — 2026-07-25 03:20
- Zero Altair remains. All nine tabs render through components/charts.py; the
  horizon rail is now the timeline spine and rail.py is deleted; the donut
  renders through the leader-line primitive over revenue_mix's bracketing.
- Pivot taken (playbook row 2): st.html turns out to sanitise SVG away
  entirely, verified by the charts being absent from the DOM with no error.
  The mount now uses markdown injection, the app's proven path.
- Real defects caught by browser verification, fixed at the root with tests:
  month-only registry dates ("2026-08") never reached the spine because ISO
  parsing rejects them; they now place at their month and the label refuses to
  invent a day. A mid-script write to the select's key desynced its displayed
  label from its state; the search jump moved into an on_change callback.
- A stray automation click on Refresh all ran a full universe refresh through
  the new code against the live database (run 24, complete in 47s): unplanned
  but a genuine end-to-end exercise of the new refresh path, idempotent
  derive_readouts confirmed (added 0 on rerun), restatement diff ran clean.
- Suite 315 green.

## Phase 3: backend analytics — 2026-07-25 02:05
- materiality.py is now the single home of flagging thresholds; diff and
  whatchanged import it, every feed item carries a reason, P3 slips over 30d
  rank high, and revenue restatements over 5% are a new detected change type
  built on asset_revenue snapshots.
- Revenue at risk extends the existing build_exposure rather than duplicating
  it: shares of tagged product revenue, cumulative curve, unpriced band as
  counts. The universe endpoint reports shares only; stacking absolute values
  across DKK, EUR, GBP and USD without an FX source would fabricate a number,
  so the brief's universe stacked-bar-by-year becomes per-company share bars.
  Recorded as a deliberate deviation for honesty.
- Slippage, catalyst grid, screen (revenue per late trial, named for trials
  because asset mapping is empty), as-of reconstruction, annotations with an
  additive migration, /price-grid, /runs/latest. 20 new tests; suite 312.
- Hand checks: BMY 2031 share 0.258 = Eliquis 14.443bn / 56.015bn tagged,
  matches to the third decimal; LLY 5y share 0.0 verified as a true zero under
  the latest-protection convention; as-of 2026-07-01 correctly returns nothing,
  history begins 2026-07-18.
- Observed: refresh run 23 (scope=all) fired tonight from the user's own
  long-running instance on port 8000, not from this build; it pulled fresh
  registry state and the diff wrote 46 real trial changes, which gives the
  slippage view live rows. Append-only history, no conflict.
- Probe annotation created during endpoint verification was deleted; the live
  annotations table is empty.

## Phase 2: chart primitives — 2026-07-25 01:15
- All ten primitives in components/charts.py as pure data-to-SVG functions with
  explicit dimensions; 37 unit tests (validity, mark counts, null paths).
- The null rule surfaced a real defect during testing: a value islanded between
  two nulls was silently dropped because a one-point run cannot draw a polyline.
  Fixed across sparkline, line chart and small multiples: islanded points draw
  as dots. The test was corrected to demand this rather than relaxed.
- Visual smoke test via a headless-Chrome gallery caught three geometry issues
  (colliding series end labels, spine date/label crowding, flag dot on the date)
  and one robustness flaw: the hover CSS lived only in the page stylesheet, so
  an exported chart would paint every tooltip at once. Hover rules now ship
  inside the SVG itself.
- Decisions: drag-to-zoom is not carried by the SVG line chart (no scripts in
  st.html); the price view keeps its window buttons and gains CSS hover
  readouts per slot. Recorded as the pivot playbook's fallback.
- Suite 292 green.

## Phase 1: design system — 2026-07-25 00:45
- tokens.css and components/tokens.py written and mirrored, with a test that fails
  if they drift. Six palette values, phase ramp, spacing base 8, radius 0/2, three
  type roles.
- Ten woff2 files (Archivo 400-700, Archivo Narrow 600, IBM Plex Mono 400-600,
  Newsreader 400-500) downloaded from Fontsource and bundled in assets/fonts,
  162KB total, inlined as base64 @font-face with font-display swap. No CDN.
- theme.py rebuilt on the tokens; the legacy Palette field names stay as the
  compatibility layer so rail, trend, revenue_mix and calendar_view shift palette
  without edits. Light palette retained only for the ramp tests.
- Top bar: sticky strip with ticker select, identity, global search (Enter jumps
  to ticker or company-name match), last-refresh state from new GET /runs/latest,
  and a universe refresh button. All inputs squared; figures in mono.
- Decisions: fonts inline rather than static-served (no config dependency);
  widget styling global rather than wrapper-scoped, since Streamlit's sanitiser
  closes injected wrapper divs before widgets mount.
- Pivots: none. Suite 255 green. Shell verified in the browser on live data.
- Known issues: browser pane is 764px wide, so 1280/1920 layout checks move to
  headless-Chrome screenshots in phase 7.

## Phase 0: research — 2026-07-25 00:05
- Read every file named in the brief plus refresh.py, comps.py, theme.py in full.
- Verified schema and data coverage against the live database; findings and all
  decisions in RESEARCH_NOTES.md.
- Notable: changes table holds only new_approval rows so far, so the slippage view
  ships with a designed empty state on live data and seeded tests; asset_indications
  is empty, so the screen's per-asset column is computed per Phase 3 trial and named
  so; 15 of 18 tickers carry product revenue, so revenue-at-risk is real for most
  and the unpriced band carries ABBV, GSK, REGN, ROG, BAYN.
- Pivots taken: none yet.
- Known issues: none yet.

## Session: deals, product record, area classification — 2026-07-27
- Added the news deal source: Google News RSS, rules-only extraction, 156 deals across
  the universe against 58 from filings alone. Filings win on any deal both hold; a
  headline may fill a size or an area the filing left blank and move a date earlier to
  the announcement, each recorded in its own `*_source` column.
- Split announced deal value from filed cash. `deals.value` became `announced_value`,
  and the financials tab labels its own line cash paid.
- Migration ledger in `db.init()`, which is what made `ALTER TABLE` usable at all.
- Trial attribution: `asset_merge.py` folds a derived compound into the marketed product
  it turns out to be (Jaypirca/Pirtobrutinib); `brand_split.py` routes a study to the
  brand whose label covers its condition (Mounjaro/Zepbound) and, where labels cannot
  separate them, to the base brand (Rinvoq over Rinvoq LQ).
- `trials_completed.py`: completed studies with results, in their own table so nothing
  that counts the pipeline picks them up. 1397 for Lilly, 670 bound to a product.
- `product_areas.py`: a product's disease area from its label, with fallbacks to a
  sibling row's label, its own trials, and the ingredient name. Portfolio groups by it
  and the revenue mix draws a second donut by it.
- LOE now takes the molecule patent over the longest listed one: Mounjaro read
  2027-2041, where 2027 is a regulatory exclusivity and 2041 a method-of-use patent.
  It reads 2036-2039 with the use tail reported beside it.
- Known gaps: product revenue is still only what the SEC data sets tag (247 products
  universe-wide); the revenue-by-product table sits unparsed in the stored MD&A text.
  Vyndaqel has no DailyMed label matched, so it has no area. No git remote is
  configured, so nothing is pushed anywhere.

## 20-F for the foreign filers — 2026-07-27
- The filing text fetch now reads 20-F as well as 10-K and 10-Q. A 20-F's risk factors
  are Item 3.D; its financial review is kept whole rather than cut to an item span,
  because the review AstraZeneca's Item 5 points at is printed further down the same
  document. AZN, NVS, NVO and SNY now carry 180k to 700k chars each. GSK files no 20-F
  in the window the filings fetch covers, and Roche and Bayer are not SEC registrants.
- html_to_text strips zero-width characters: AstraZeneca's 20-F carries 16,553 of them,
  invisible in the text and fatal to any pattern expecting a number and a space.
- The revenue reader learned four more table shapes off the back of it: thousands
  separated by spaces (Novartis), signed percentages (Sanofi), a total printed before
  its parts (Novo), and trademark symbols between a name and its number.
- A spaced table is read by its own arithmetic. "Fabhalta 3 505 129 291" is footnote 3
  then 505, and "Entresto 7 748" is seven thousand seven hundred and forty-eight;
  nothing in the shape separates them, so the change column decides and a row that
  proves neither reading is refused.
- Universe: 67 product-years parsed, 57 cross-checked against the SEC data sets, none
  disagree. Ten of them are values the data sets do not tag.

## Three engines, and a front door — 2026-07-30
- The universe is partitioned once, into big pharma (18), biotech (25) and cell and gene
  (27), and each engine asks only what its cohort can answer. The rule is derived: revenue
  at or above 8bn is a major, which is the widest gap in the distribution (Biogen 9.9,
  Incyte 5.1); a cell or gene platform in a company's own filings under 1bn of revenue is a
  platform developer; everything else is biotech. Two non-filers have no revenue to read,
  so a marketed register above thirty places them, which is Roche and Bayer and nobody
  else.
- The revenue test is what keeps the third engine honest. Vertex, Gilead and Bristol all
  describe cell or gene platforms and all earn billions, as do Sarepta and BioNTech and
  Legend; they are answerable on revenue, which is not the question a startup engine asks.
  Neurocrine's tag came from a capability list and Pfizer's from a divestment, and both
  fall out on revenue too.
- Tabs now key on the engine rather than the raw stage. Abeona had a Portfolio tab reading
  100% fresh off 3.4m of product revenue, because the stage test only asks whether
  inventory exists. It reads on cash now, like the rest of its cohort.
- The Universe tab is the open engine's universe. Seventy price panels is a wall, and two
  thirds of it answers a different question from the one the engine is asking. An empty
  approvals tape now says whether the cohort was quiet or the source was, instead of
  pointing at the refresh button either way.
- The landing page is one component: hero, three clickable panels, and the week's six most
  material changes. Each panel carries its cohort's spread as a bar per company, falling
  left to right, with a stub below the baseline where there is no figure, because a zero
  and an unknown must not be the same mark.
- Signals rank by kind before significance. 113 of the week's 183 high-significance items
  were risk-factor diffs, which is a rewrite of boilerplate, and level with an approval
  they buried every approval. The change feed keeps its own rank; this orders the strip.
- Known gap: the cell and gene strip says "furthest stage on file" rather than "reached".
  Krystal markets Vyjuvek and is not in the marketed register, because Vyjuvek is a CBER
  licence and drugsfda covers CDER only. The NDC register lists it, and also lists labelers
  for companies that market nothing, so there is no free route that would not mark a
  developer marketed.

## The pipeline the registry cannot see — 2026-07-30
- Two derived rows for one programme now merge on the development code. canonical() strips
  parentheticals first, which is right for a study's "(LEN)" and wrong for Dyne's Phase 3
  registering "zeleciment basivarsen (DYNE-101)" against a Phase 1/2 registering
  "DYNE-101": the names stopped agreeing, so the pipeline showed Dyne four programmes for
  two drugs, each split across the phase it was in when the trial was written. 19 groups
  folded across the universe, 21 trials moved.
- Three guards, each from a real case. A name carrying two codes is a combination
  ("MET233 and MET097") or a regimen ("AZD9291 in combination with AZD6094"). Two rows
  differing by radioisotope are a diagnostic and a therapeutic, not one programme
  ([68Ga]Ga-DWJ155 against [177Lu]Lu-DWJ155). And a token that looks like a code but names
  a target, an isotope, a capsid or a rating scale is not one.
- Programmes are now read out of the MD&A as well. Every previous route into the asset
  table needed a registered study or an approval, so anything preclinical or newly
  IND-cleared could not exist: Dyne names eight programmes and the app held two. DYNE-302
  had FDA clearance to start a Phase 1 in FSHD and was nowhere. 85 programmes recovered
  across 39 companies.
- It never assigns a phase. A phase means a registered study; "we plan to evaluate
  DYNE-302 in a Phase 1" is a plan. What it records is the stage the filing states, IND
  cleared through to discovery, with the sentence it was read from and the accession.
- Ownership is a first-person sentence, and a sentence naming another party is not
  evidence: Merck's filing names TERN-701 and Solid's names Entrada's compound.
- What it still gets wrong: a trial's name has a compound's shape. The tests are the word
  next to it ("the STELLAR-303 trial") and whether its prefix appears lower case in the
  same document ("forward-looking" makes FORWARD-53 a trial). Exelixis lists STELLAR-001
  to STELLAR-316 with neither signal, so four read as programmes. Every row carries its
  sentence, so the error is visible rather than silent.
- Unrelated: tests/test_refresh.py fails intermittently on openFDA HTTP 429. It calls the
  network. Reproduced on unmodified code.

## Between the quarters — 2026-07-30
- 8-K and 6-K text is stored now. The body was never the news: Dyne's quarterly 8-K says
  only that "a copy of the press release is furnished as Exhibit 99.1", and the results,
  the cash position and the IND clearance are all in that exhibit. So a current report is
  read twice, the body for its item numbers and the exhibit for what happened, which needs
  one extra request for the filing's own index.json to find. 79 sections stored across
  nine companies on the first pass, 25 of them exhibits.
- The press release an analyst reads on the IR page is an EDGAR document. Nothing here
  needs a feed or a scrape.
- Post-period financings are read out of the MD&A and the 8-K exhibit. A balance sheet is
  one day: Dyne's says 898.5m at 30 June and the company raised 405m net in July, three
  weeks before filing the 10-Q that says so, and no XBRL fact carries it until November.
  Five companies corrected. Dyne's runway goes 23 to 33 months, Cabaletta's 10 to 22,
  Allogene's 20 to 50.
- Net proceeds only. Dyne's raise was 431m gross and 405m net, and there is no free way to
  know the fee, so a gross-only statement is skipped rather than discounted by a guess.
- Five guards, each from a company that produced a wrong figure first: a figure more than
  sixty characters from the words "net proceeds" is some other number (Dyne's quarterly
  R&D expense read as a raise); a sentence about spending the proceeds is not a receipt
  (Allogene); a closed quarter is already on the balance sheet (Cabaletta's Q1 ATM sales);
  nothing closes after the filing that reports it (Sanofi's 2032 note maturities); and one
  raise stated at two figures is one raise (an 8-K states proceeds before and after the
  underwriters' option).
- The month is bounded before it is chosen. A liquidity sentence names the balance sheet
  date and the raise date, and nearest-first picked the date the money was not there.
- The balance sheet figure is untouched. cash, raised_since and available are three fields,
  so a reader can see which part was tagged and which part was read out of a sentence, and
  the row drops itself once the next quarter's balance sheet includes it.
- tests/test_refresh.py stubbed the NDC fetcher. It was the one fetcher still reaching the
  network in that test, and openFDA's rate limit made the run come back partial.

## Terms, headlines, and a filter on the agency — 2026-07-30
- The J&J/Sail deal was captured on the 29th from a Google News headline: a counterparty,
  a type, and no size. The same day's 8-K furnished the press release as Exhibit 99.2, and
  it states all of it. Deals now carry upfront, equity, milestones, option and total as
  five figures rather than one, read out of that text with no model: $785m upfront, of
  which $465m is equity, $140m on milestones, $2.58bn if the option is exercised.
- The equity sits inside the upfront and nothing is summed, because that is what the
  filing says. A single value column has to pick one number and is wrong whichever it
  picks: 2.58bn overstates what is being spent, 785m understates what the deal is worth.
- Roles bind from the phrase to the figure, within a clause. The other way round, a word
  already spoken for claims a second figure: "we will pay $50 million upfront and up to
  $450 million in milestones" put both under upfront, because "upfront" sat eleven
  characters from the wrong figure and twelve from the right one.
- The exhibit matcher missed J&J's naming. Filing agents spell it out as often as they
  abbreviate, and "exhibit991firefly.htm" contains no "ex99". Each exhibit is also its own
  section now: one 8-K furnished two press releases, Firefly at 1bn and Sail at 2.58bn,
  and joined into one document each read as the other's price.
- The Universe tab leads with headlines: the few things ranked by kind, most material
  first, one per company, each carrying what makes it matter. A deal with no terms is not
  a headline at all.
- FDA regulatory is filtered to events. Of 83 items over four months, 69 were the agency's
  own website upkeep, guidances and user-fee programmes and resource pages reposted, and
  most of the rest were device recalls at companies this universe does not cover. Fourteen
  survive. The count of what was set aside is on the section header, so a short list reads
  as filtered rather than as broken.
- A resource page matched to a company is still not an event: "New Approach Methodologies
  (NAMs)" was bound to Revolution Medicines.

## The terms, everywhere a deal is read — 2026-07-30
- The structure now reaches all three places a deal appears, not just the headline block:
  the Key insights deals panel, the morning note, and the ranked headlines. Each was
  reading a single announced_value string, which for the J&J deal was either nothing or
  the option price, and never what the company is spending this year.
- deals.recent_rows carries the four commitments and the sentence they came from, and
  merges them across filings: a deal arrives on a wire and its structure lands with the
  8-K a day or two later, so the row that announced it and the row that priced it are not
  the same row.
- The card shows the structure where there is one and falls back to the announced figure
  where there is not, with the terms sentence as the tooltip. The panel's total now reads
  3.6bn across 2 of 6 rather than 1.0bn across 1 of 6.
- notecontext built its own deal lines with its own SQL and its own formatting, so it was
  the one consumer the earlier change missed. It reads the same fields now.

## Two directions, one form — 2026-07-30
- Headlines run over the last week, not a fortnight. The page answers "what happened since
  I last looked", and fourteen days put things on it that had already been read.
- The FDA approvals timeline leads the tab now, above the headlines.
- Headlines and the forward view are boxes that open onto their own detail, a native
  disclosure so nothing reruns. A deal opens onto its four commitments as separate rows
  and the sentence they were read from; a readout onto its study, its date and where the
  date came from.
- "Next 30 days" and "FDA regulatory" were two sections asking the same question, split
  only by which table the date came out of. They are one "Looking ahead" list now, soonest
  first, and within a day the firmest kind leads: a decision date, then the panel vote
  that informs it, then a readout. The announced half of the regulatory stream moved into
  the headlines as its own kind, so nothing was dropped in the merge.
- Each forward box says where its date came from in the words that name the real source. A
  PDUFA date is read out of an 8-K and a readout out of ClinicalTrials.gov, and one
  sentence for both named a source that never carried half of them. A date somebody stated
  counts as firm whether it was typed in or extracted; a registry completion date is
  nobody's commitment.
- The announcing sentence stored against a PDUFA row was being labelled "Study", which is
  the field an NCT id goes in. It reads as a quote now.

## What a quiet week actually looked like — 2026-07-30
- Headlines lead the tab again, titled "Headlines this week", with the approvals tape
  under them.
- Three headlines for eighteen majors read as a broken filter, so the week was counted:
  168 tracked items, of which 33 trial dates slipped, 32 trial statuses changed, 16 labels
  were revised, 16 filings landed and 3 were approvals. None of the 32 status changes was
  a stop; every one was a trial opening or closing enrolment. So the filter was mostly
  right and twice wrong.
- A foreign filer's 6-K carries a free-text title that is the announcement itself:
  "HANSOH POSITIVE 2ND PHASE III RESULTS FOR RIZ-REZ", "UPDATE ON ULTOMIRIS PHASE III
  TRIAL IN HSCT-TMA". Nothing else in the model carries those, and they are headlines by
  any reading. An 8-K's title is an item label from a fixed vocabulary and never is.
- Most 6-Ks are UK listing-rule housekeeping: a director's share dealing, a buyback
  tranche, a voting-rights total. Excluded by name.
- A shouted title is softened to a sentence, keeping what was meant to be capitals. A
  vowel test alone fails: "III" is all vowels and "HSCT-TMA" contains one. Roman numerals,
  compounds, four letters or fewer outside a stoplist, and the company's own drug names
  are all kept. Proper nouns it cannot know stay lower case, which is why the title as
  filed rides along in the detail.
- The limit is six rather than four: one per company means six is six different filers,
  and four was making a week with a 2.58bn deal and a Phase 3 result look empty.
- Label revisions stay out. "Neupogen revised to version 166" is a document increment with
  no statement of what changed, and sixteen of them a week would be the whole page.

## The box says it — 2026-07-30
- Both captions are gone. With the chip naming the kind, the ticker leading the line in
  mono and the date on the right, a paragraph explaining the layout was explaining
  something the layout already said.
- The kind is one accent colour per box, set as a custom property and used by the rail,
  the chip, the open state and the source link, so a kind cannot be one colour in one
  place and another somewhere else. A panel vote takes the Orange Book amber rather than
  the flag amber, because a vote and a PDUFA sit in the same forward list.
- A drawn chevron rather than a caption, since with no explanatory text the box has to say
  it opens.
- The headline wraps instead of truncating with an ellipsis, and is cut at 104 characters
  only where a registry title would otherwise set the height of every box beside it. The
  whole title is the first row of the detail either way.
- A money figure keeps its own case. The chip's uppercase rule was rendering "$2.58bn" as
  "$2.58BN".

## Sizes where there are sizes — 2026-07-30
- The enrichment reaches a press release that is not stored yet. The filing-text fetcher
  keeps the latest few current reports per company, a month or two of an active filer, so
  a deal from last summer had nothing to read: 99 of 155 deals had no size and only 2 of
  those had stored text naming the party. It now falls back to fetching the release for
  the filing in the deal's own window, bounded at 40 lookups a run and cached by
  accession, since one 8-K can carry two deals and a company files several a quarter.
- 69 of 155 deals carry a size now, up from 56, and 27 carry the full structure.
- The rest have nothing to find, and that was checked rather than assumed. AbbVie's
  Gilgamesh release and Beam's Bio Palette release both name the party and state no terms
  at all, which is how most pharma business development is announced.
- So "size not stated" is gone. It was the commonest thing on the panel and told a reader
  nothing the empty space does not. The section header still counts how many carry one,
  which is the honest place for it: "$3.6bn announced across 2 of 6".
- The deals header stops counting the absence too. "$3.6bn announced across 2 of 6" said
  in the header what the cards had stopped saying on every row. It reads "$3.6bn
  announced" now, beside the deal count that was always there.

## A counterparty has to be a party — 2026-07-30
- Every bad row on the deals panel was the same mistake in five shapes, and all of them
  came from a news headline rather than a filing. The thing being bought read as the
  buyer: "Axsome Acquires Selective PDE10A Inhibitor" named an asset and "Arrowhead
  Licenses Clinical MASH Program Targeting PNPLA3 to Madrigal" named the programme rather
  than Madrigal. A truncated name left a bare noun: the capital-letter match stops where a
  name runs on in lower case, so "acquire China rights" gave "China" and "Collaboration
  with Department of Health - Abu Dhabi" gave "Department". A building read as a company:
  "Rubicon Point Partners Acquires Shockwave Medical Headquarters Campus" is a real-estate
  deal that mentions a covered company's address. A roundup paired the wrong two parties:
  the World Health Organization ended up against Johnson & Johnson because the headline
  named Gilead first. And a marketing tie-up read as business development: a Champion of
  the Year award.
- is_party() is the test, applied in both routes so the model and the headline parser are
  guarded by the same rule. Deliberately strict: a wrong party puts another company's
  transaction on this company's page, and the panel is read as a record of what the
  company did.
- Twenty rows cleared from the table, and prune_parties keeps clearing them, so a rule
  tightened later reaches what was already written rather than only what arrives after it.
- One thing that had to be scoped rather than shared. Applying the headline rule to a
  filing's quote deleted a real J&J acquisition, because a sentence about acquiring a
  company mentions its headquarters in passing. The rule now runs only where the quote is
  a headline.
- A filer's HTML that spaces letters out is rejoined: "K YOWA K IRIN C O ., L TD ." became
  "KYOWA KIRIN CO., LTD.". Three or more single-letter tokens is a rendering artefact and
  two is a person's initials, so J P Morgan is left alone.
- A publisher's hyphenated description is trimmed too. "Prostate Cancer Treatment-Maker
  Halda" and "CT-based Halda Therapeutics" were two more rows for one deal.
- BIOG was the last one, and it was a holder rather than a party: "argenx SE to acquire
  BIOG portfolio company, Forte Biosciences, Inc" names the trust that owns Forte, and
  BIOG is its ticker. The parser steps over a holder phrase now, portfolio company,
  subsidiary, affiliate, spin-out, and takes the name after it, so the row reads Forte
  Biosciences. The prune clears the ones written before it did, matching the phrase only
  where it sits directly after the captured name: a headline that mentions a subsidiary
  elsewhere in the sentence is still that party's deal.

## A map, and sixteen years instead of seven — 2026-07-30
- Financial history was capped at seven fiscal years by MAX_FISCAL_YEARS, which is one
  cycle: long enough to see a growth rate and not long enough to see a patent cliff and
  what replaced it. Company facts carry the whole history in one response, so the cap cost
  storage rather than calls. Seventeen years now, and forty quarters.
- Depth was not only the cap. JNJ's history started in 2018 whatever the cap, because ASC
  606 moved revenue from SalesRevenueGoodsNet to the contract concept on a date and the
  old tag was not in the candidate list. Adding it was half the fix; the other half is
  that the two series never overlap by construction, and the agreement test refuses a
  series with no shared period. A handover is allowed now where the periods are adjacent
  and the values at the join are within a factor, so a concept the filer stopped using
  extends the history and a concept measuring something else still cannot. JNJ 2010-2025,
  LLY and Merck and Vertex 2009-2025.
- The Universe tab has a map: every company on the engine as a box, area what the engine
  runs on and colour the ninety-day move.
- Area is not market capitalisation and the byline says why. It would be shares
  outstanding times the last close, and for a company quoted as an ADR the share count is
  in ordinary shares while the price is per receipt: GSK computes to 223bn against a real
  ninety and Sanofi to 53 against a real hundred and thirty. The ADR ratio is in no free
  source, so five of the eighteen majors would be wrong by a factor.
- So area is revenue on the two engines whose companies are run on revenue, and cash on
  the one whose companies are not. No map mixes the two. A company the metric cannot size
  is counted rather than drawn at nothing, since an area of nothing reads as a company of
  nothing.
- Squarified rather than sliced, so the small boxes stay square enough to hold a ticker,
  and the label appears only where it fits.
