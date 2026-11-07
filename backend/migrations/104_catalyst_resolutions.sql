-- What became of each catalyst, as an append-only record beside the register.
--
-- Every one of the 814 catalysts on file is pending, and not because none has happened:
-- derive_readouts deletes a derived readout once its date passes, pdufa rows stay
-- pending for ever, and nothing reads the approvals table or the announced readouts back
-- against the calendar. Zilganersen was approved on 2026-09-03 under NDA220210 and its
-- PDUFA catalyst, due 2026-09-22, is still pending. So call_log has scored no gate, the
-- Brier calibration has never run, and every gate-odds regime is an assertion.
--
-- The register's own status column is the one call_log reads (met, missed), so that is
-- still set. This table is the audit: what resolved it, from which source, on what
-- evidence, and whether a person or the resolver did it, so a resolution can be
-- questioned and overridden without losing the history of what the machine thought.
-- A slip on a derived readout is an event here and not a status there: derive_readouts
-- updates that row in place, and a terminal status would block its own successor.
CREATE TABLE IF NOT EXISTS catalyst_resolutions (
    id            INTEGER PRIMARY KEY,
    catalyst_id   INTEGER NOT NULL REFERENCES catalysts(id),
    outcome       TEXT NOT NULL,         -- met, missed, slipped, unknown, ambiguous
    event_date    TEXT,                  -- the day the market knew, where there is one
    resolved_at   TEXT NOT NULL DEFAULT (datetime('now')),
    source        TEXT NOT NULL,         -- approvals, trial_readouts, registry, calendar, hand
    evidence      TEXT,                  -- the row or filing that decided it
    basis         TEXT,                  -- the rule, in words
    automated     INTEGER NOT NULL DEFAULT 1,
    -- SQLite allows no expression in a UNIQUE constraint, so the dedupe key is a plain
    -- column the writer fills: the evidence, or '' where a resolution carries none.
    dedupe        TEXT NOT NULL DEFAULT '',
    UNIQUE (catalyst_id, outcome, dedupe)
);
CREATE INDEX IF NOT EXISTS idx_catalyst_resolutions_catalyst ON catalyst_resolutions (catalyst_id);
