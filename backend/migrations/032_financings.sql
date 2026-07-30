-- Money raised after the balance sheet date the cash figure was read at.
--
-- A balance sheet is one day. Dyne's says 898.5m at 30 June 2026 and the company raised
-- another 405m net in July, three weeks before it filed the 10-Q that says so. No XBRL
-- fact carries it until the Q3 statements land in November, so a runway computed from the
-- newest available facts is 45% short for three months.
--
-- amount_usd is net proceeds, never gross: the difference was 26m on that raise, and a
-- filing that states only gross is skipped rather than discounted by a guessed fee.
--
-- closed_month is a month rather than a date because that is what filings state, and it
-- is compared against balance_sheet_date by month: a raise in the same month as the
-- period end is already in that balance sheet and adding it would count it twice.
--
-- evidence is the sentence the row was read from. These rows change a headline number, so
-- the sentence that moved it has to be readable next to it.

CREATE TABLE financings (
    id                 INTEGER PRIMARY KEY,
    company_id         INTEGER NOT NULL REFERENCES companies(id),
    closed_month       TEXT NOT NULL,      -- YYYY-MM, as the filing states it
    amount_usd         REAL NOT NULL,      -- net proceeds
    kind               TEXT,               -- public offering, term loan, convertible notes
    evidence           TEXT,
    balance_sheet_date TEXT,               -- the cash date this was measured against
    accession          TEXT,
    form_type          TEXT,
    filed_date         TEXT,
    section            TEXT,               -- mdna, exhibit, body
    created_at         TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_financings_company ON financings(company_id, closed_month);
