-- The biosimilars the FDA has licensed, each against the reference product it copies.
--
-- The book knew when a biologic's exclusivity lapsed and not whether anything had been
-- licensed against it. Those are different facts: Botox's twelve years ran out in 2003
-- and nothing copies it, while Humira's ran out in 2014 and ten biosimilars are licensed.
-- Both read "lapsed", and the valuation held both flat.
--
-- One row per biosimilar brand and BLA, reduced from the Purple Book's one row per
-- presentation: the earliest approval, and "Rx" where any presentation is still listed
-- for sale. A licence is not a launch. Etanercept's biosimilars are licensed and every
-- presentation is "Disc"; aflibercept's are "Rx" and most are held off the market by
-- settlement. So this table says what is licensed and listed, and a launch is taken
-- only from a filer's own statement (data/competitor_launches.csv).
CREATE TABLE IF NOT EXISTS biosimilar_licences (
    id                    INTEGER PRIMARY KEY,
    bla_number            TEXT NOT NULL,
    proprietary_name      TEXT NOT NULL,
    proper_name           TEXT,
    applicant             TEXT,
    licence_type          TEXT,          -- 351(k) Biosimilar | 351(k) Interchangeable
    reference_proprietary TEXT NOT NULL, -- the brand it copies, as the FDA prints it
    reference_proper      TEXT,
    approval_date         TEXT,          -- ISO, the earliest presentation
    marketing_status      TEXT,          -- Rx where any presentation is; else Disc
    fetched_at            TEXT DEFAULT (datetime('now')),
    UNIQUE (bla_number, proprietary_name)
);
CREATE INDEX IF NOT EXISTS biosimilar_licences_reference
    ON biosimilar_licences (reference_proprietary);
