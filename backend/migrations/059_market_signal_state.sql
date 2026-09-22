-- Where each market signal was last flagged from, so a slow move is still caught.
--
-- The app's stated differentiator is change detection, and on the market series it was
-- disconnected: three stored snapshots had produced no change rows at all while the
-- ten-year travelled 104bp across the stored history.
--
-- A rule comparing one snapshot to the one before it cannot catch that. Over 275 stored
-- DGS10 observations the median daily move is 3bp and the largest is 14bp, so at a 25bp
-- bar a day-on-day rule fires zero times in thirteen months, and it fires zero times for
-- every other series too. The move happens, it just never happens in a day.
--
-- So the comparison is against an anchor: the level the last flag was written from,
-- which only moves when a flag is written. A rate that walks 3bp a day for nine days
-- crosses 25bp and is caught, once. Measured over the stored history a 10bp anchor on
-- DGS10 fires 27 times and a 25bp anchor 8 times, against 3 and 0 for a day-on-day rule.
--
-- One row per signal, not per series, because a series can carry two bars with separate
-- anchors: the ten-year writes a feed row at 10bp and a note sentence at 25bp, and if
-- they shared an anchor the smaller bar would keep resetting it and the larger one could
-- never be reached. The key is "<series>:<bp>".
--
-- anchor_value is a rate as a fraction, 0.0501 for 5.01%, matching market_rates.
-- Written by backend/market_signals.py, called from diff.detect_changes on each refresh.
-- armed is kept for a signal a reader has silenced; nothing sets it to 0 yet.

CREATE TABLE IF NOT EXISTS market_signal_state (
    signal_key    TEXT PRIMARY KEY,
    anchor_value  REAL NOT NULL,
    anchor_as_of  TEXT NOT NULL,
    armed         INTEGER NOT NULL DEFAULT 1,
    flagged_at    TEXT
);
