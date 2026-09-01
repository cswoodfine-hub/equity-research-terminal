-- Revenue a company reports that no asset carries.
--
-- Every forecast so far hangs off an asset, and a company's revenue does not. Vertex
-- reports Kalydeco, Orkambi and Symdeko as one line, "Other CF product revenues", and
-- never splits it; Biogen books Ocrevus royalties and contract manufacturing that are not
-- products of its own at all. The company call was measuring its coverage against the
-- product rows it happened to hold, so a name with a third of its revenue in lines like
-- these read as fully modelled while a third of it was invisible.
--
-- A line is a marketed forecast without an asset: a reported base, a growth rate, margins
-- and a discount rate, run through the same engine. It sits beside the assets in the
-- rollup and the revenue build, and it is what lets modelled revenue reconcile to the
-- reported total rather than to a subset of it. The shape follows assumptions: one row
-- per key, a source on every row, and a scenario column so a bear case can restate a
-- line the way it restates an asset.
CREATE TABLE company_lines (
    id          INTEGER PRIMARY KEY,
    company_id  INTEGER NOT NULL REFERENCES companies(id),
    line        TEXT NOT NULL,                      -- as the filer names it
    scenario    TEXT NOT NULL DEFAULT 'base',
    key         TEXT NOT NULL,                      -- the marketed vocabulary in forecast.py
    value       REAL,
    text_value  TEXT,
    unit        TEXT,
    source      TEXT,
    note        TEXT,
    updated_at  TEXT DEFAULT (datetime('now')),
    UNIQUE (company_id, line, scenario, key)
);
