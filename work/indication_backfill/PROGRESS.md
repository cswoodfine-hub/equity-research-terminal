# Indication backfill — progress ledger

Resumable. A fresh session reads this file top to bottom, finds the first step not
marked DONE, and continues from there. Every step is idempotent: re-running a DONE
step must not corrupt anything, so when in doubt re-run it.

Started 2026-10-26. Author: Claude, for Charles.

## Why this exists

Charles asked for research on ~230 unapproved indications. Measuring first changed the
job. See MEASUREMENT.md for the numbers and how to reproduce them.

The short version: the thing blocking the alpha surface is mostly **not** missing
epidemiology. 340 catalysts sit at `no_gate`; only 57 of them (44 asset-indication
units) are waiting on an indication layer. The other 283 are waiting on a *link* —
the catalyst does not say which disease it reads out in — or on the asset having no
model at all. Linking is deterministic and costs no research.

## Rules that do not bend

- Never fabricate a value. A number with no source is left empty with a stated reason.
- Every numeric seed row names a source a person can open.
- `evidence.grade(source)` must return filed/measured/published for a pool row. If it
  grades as judgement or None, the row is not sourced and does not ship.
- A judgement says in its note what would replace it.
- Seeds are insert-only. Edit numbers in the terminal, not in the CSV.

## Steps

- [ ] 1. MEASURE — reproduce the counts. `work/indication_backfill/measure_all.py`
- [ ] 2. LINK-A — run the existing linker; count what it attaches.
- [ ] 3. LINK-B — the ambiguity rule (165 catalysts, mostly Obesity/Overweight).
- [ ] 4. LINK-C — condition strings that resolve to no MeSH descriptor (143).
- [ ] 5. TRIAGE — the layer worklist: reuse pools already in the book, park Phase 1.
- [ ] 6. VERIFIER — the mechanical acceptance test, written before any agent runs.
- [ ] 7. WAVE 1 — research agents, one company, measured.
- [ ] 8. WAVE 2+ — scale only if Wave 1's accept rate justifies it.

## Log

(append one line per completed action, newest last)
