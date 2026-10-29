# 8c: what the market moved on past readouts

Run 2026-10-29. Reproduce with
`ER_TOOL_DB=<copy> python3 work/proxies/tools/readout_moves.py --download <dir>`, then
`... readout_moves.py <dir>`.

## Data

- **Events.** The 1,022 "Other events" and "Regulation FD" 8-Ks in the book (2021 on), read
  from EDGAR. A readout is a press release title, or the item's first 500 characters,
  that names a trial or phase and results or data.
  - **Met:** "met its primary", "statistically significant", "positive topline" and
    similar.
  - **Failed:** "did not meet", "failed to", "discontinue" and similar.
  - Otherwise unclassified.
- **Move.** Close before the filing date to the close the day after, less XLV.
- **Market cap.** The close times the latest diluted share count, since prices carry
  none.
- **Model.** The latest `gate_calls` row for each pending catalyst. Its move on success is
  (per_share_success - per_share_now) / price; its move on failure is the same with the
  failure leg.

## Result

200 readouts with prices: 42 met, 4 failed, 154 unclassified.

| band | outcome | n | realised move, median (interquartile) | model's move on that outcome, median |
|---|---|---|---|---|
| over $10bn | met | 12 | +0.9% (-4.6% to +11.1%) | +0.1% (n=57) |
| over $10bn | failed | 2 | -12.5% | -0.1% (n=57) |
| $1bn to $10bn | met | 19 | +1.5% (-1.5% to +17.5%) | +4.0% (n=10) |
| $1bn to $10bn | failed | 2 | -21.1% | -12.2% (n=10) |
| under $1bn | met | 10 | +8.1% (-15.3% to +33.6%) | +16.5% (n=1) |
| under $1bn | unclassified | 66 | -4.2% (-12.5% to +3.1%) | |

## What it says, and what it cannot

- **Success leg:**
  - **Large companies:** the model's stakes and the market agree that one readout barely
    moves them.
  - **Mid caps:** the model's success leg (+4.0%) is larger than the median realised move
    (+1.5%). A positive readout is often partly priced in before it lands, so the
    realised move understates the stake.
- **Failure leg:** not measurable here. Companies rarely title a failure as one. Only 4 of
  200 headlines say so plainly, and the unclassified readouts lean negative (-4.2% for
  small caps), which is where the rest sit.
- **Small caps:** a "met" readout's move is spread from -15% to +34%. Small companies often
  raise straight after good news, and 8b shows how often.

**No change to the gate engine.** Four failures cannot calibrate a stake.

## What would settle it

- **The call log.** `gate_calls` records the model's stake on every pending catalyst
  every day, and the catalysts resolve as their readouts land. Scored automatically as
  they do, about 30 resolved calls per size band would give a calibration with both legs
  measured on the same events, with no headline wording involved.
- **Unclassified readouts.** Reading the press release itself (the 8-K's exhibit 99)
  rather than its title would classify more of the 154, with the same fixed wording.
