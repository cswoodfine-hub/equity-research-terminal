# Indication backfill — progress ledger

**Resumable by design.** A fresh session reads this file top to bottom, finds the first
step not marked DONE, and continues. Every step is idempotent: re-running a DONE step
must not corrupt anything, so when in doubt, re-run it. If a session ends mid-step,
nothing is lost — the state lives in `worklist.json` and in git, not in a conversation.

Started 2026-10-26 by Claude, for Charles, who asked for research on ~230 unapproved
indications "at the standard you set" and then left for the evening.

## Rules that do not bend

- **Never fabricate a value.** A number with no source is left empty with a stated reason.
- Every numeric seed row names a source a person can open.
- `evidence.grade(source)` must return filed/measured/published for a pool row. If it
  grades as judgement or None, the row is not sourced and does not ship.
- A gate probability (`pos`) is the published chain, a stated result, or a judgement
  that says what would replace it.
- Seeds are insert-only. Edit numbers in the terminal, not in the CSV.
- A pool may not contradict one already in the book (`test_no_two_assets_disagree`).

## What the measurement changed

Read MEASUREMENT.md for the numbers. The short version, and it matters:

The job is **not** mostly epidemiology. Three things block the gate surface, in order
of size, and research is the third:

1. **Catalysts that name no disease** — 212 of the 340 at `no_gate`. Deterministic.
   86 fixed (commit 9d0bc56); 186 remain, mostly genuinely ambiguous or paediatric.
2. **Assets carrying no model at all** — 71 catalysts. Needs a whole forecast, not a layer.
3. **Layers on selling products with no seeds** — 57 catalysts, 44 units. The research job.

And within the research job, the binding constraint is **not the disease pool**. Asked
unit by unit, the engine says all 182 open units lack `discontinuation_pct` and 170
lack a net price per patient. 73 assets carry that gap. One price found unlocks every
layer on that product, so the agents do asset-level numbers first.

## Steps

- [x] 1. **MEASURE** — `work/indication_backfill/nogate.py`, `why_nogate.py`. DONE.
- [x] 2. **LINK** — three refusal rules fixed; 406 unlinked catalysts to 320. DONE,
      commit 9d0bc56, 4,302 tests passing.
- [x] 3. **WORKLIST** — `worklist.py`, idempotent, merges and never clobbers a status.
      225 units: 95 todo, 87 reuse_pool, 23 parked, 20 already seeded. DONE.
- [x] 4. **VERIFIER** — `verify_seeds.py`. Calibrated both ways: the six Lilly files
      pass clean, a deliberately fabricated file fails on eleven counts. DONE, 6109d86.
- [x] 5. **DOSSIERS** — `dossier.py`, one per company, asset-level gaps first. DONE.
- [x] 5b. **TWO CONTAMINATION GUARDS** — found while Wave 1 ran, both of which would
      have produced layers that double-count revenue. See "Where the worklist was
      wrong" below. DONE.
- [ ] 6. **WAVE 1** — three agents running on AZN (28 units), PFE (26), BMY (18).
      Drafts land in `work/indication_backfill/drafts/`. **Not yet verified or loaded.**
- [ ] 7. **VERIFY WAVE 1** — run verify_seeds.py over the drafts; then read a sample by
      hand. The verifier catches unsourced and inconsistent; it cannot catch a real
      citation misread, so a human spot-check stays irreducible.
- [ ] 8. **LOAD** — move passing files to `data/assumptions/`, run `load_seeds`, rebuild,
      `make verify`, and re-run `nogate.py` to measure what actually got priced.
- [ ] 9. **WAVE 2** — only if Wave 1's accept rate justifies it. ABBV dossier is ready.

## Where the worklist was wrong, and how it was caught

Both defects make an already-approved indication read as pending. The failure mode is
silent and expensive: a layer on an approved indication rebuilds the business the
product already has, underneath the revenue that already contains it.

**1. No label, so nothing to compare against (17 units, status `blocked_no_label`).**
`approved_indications.for_asset` asks the label what the product already covers. With
no label text the only test left is "is the phase 4", so every indication reads as
unapproved. Tezspire is the proof: the book holds no label for it, and its four
"unapproved" units include Asthma, approved 2021-12-17, and Rhinosinusitis, approved
2025-10-17. Also Jakafi (5), Braftovi/Mektovi (2), Dupixent (2), Trikafta, Nurtec,
Prevnar, Gardasil. Held, not researched — the fix is a label, not a pool.

Narrowed to assets that actually have revenue. A pipeline asset with no label is
approved in nothing, so every indication on it is genuinely unapproved; ceralasertib
and monalizumab are that case and are correctly left in scope.

**2. MeSH spells out what a label leaves implicit (11 units, `check_already_approved`).**
The test is the descriptor's tokens as a subset of the label's. MeSH writes "Carcinoma,
Non-Small-Cell Lung"; the label writes "non-small cell lung cancer". MeSH writes
"Leukemia, Lymphocytic, Chronic, B-Cell"; the label writes "chronic lymphocytic
leukemia", because in CLL the B-cell lineage goes without saying. So Calquence read as
pending in CLL, which it has been approved in since 2019 — along with Alecensa,
Enhertu, Krazati, Rybrevant, Imbruvica, Venclexta, Elahere, Imdelltra, Otezla, Leqvio.

Not auto-decided. Dropping the words and matching anyway is a guess, so each is flagged
for someone to read the actual label — a question an agent with the label in front of
it answers in one step. The three running agents have been told.

**Both were found by the research agents, not by the code.** The AZN agent's own
sub-research established the Calquence 2019 approval and the Tezspire CRSwNP approval
while answering a different question. That is the adversarial pass working earlier than
designed, and it is an argument for keeping a research step in front of the seeding
step rather than automating straight through.

## If you are picking this up cold

```bash
cd "ER Tool"
python3 work/indication_backfill/worklist.py            # refresh state, keeps statuses
python3 work/indication_backfill/verify_seeds.py work/indication_backfill/drafts/
```

## Log

- 2026-10-26 — measured the gate surface: 133 priced, 340 no_gate; split the causes.
- 2026-10-26 — fixed three catalyst-linking refusals; 86 readouts now name their disease.
- 2026-10-26 — built the worklist (225 units) and the verifier; calibrated on the Lilly files.
- 2026-10-26 — found the real blocker: 73 assets have no price per patient on file.
- 2026-10-26 — launched Wave 1: AZN, PFE, BMY research agents.
- 2026-10-26 — caught two contamination sources in the worklist; 28 units pulled from
  research (17 blocked_no_label, 11 check_already_approved). Open units 182 -> 154.
- 2026-10-26 — corrected all three running agents mid-flight with their own exclusions.
