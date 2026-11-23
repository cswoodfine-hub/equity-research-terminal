-- What a company's own directors and officers did with its shares, from SEC Form 4.
--
-- The book knew what a company filed about its business and nothing about what the
-- people running it did with their own money in the weeks before a readout. A Form 4 is
-- due two business days after an insider's transaction and says who, when, how many, at
-- what price and what they hold afterwards. It is the one dated, attributable record of
-- a decision made by somebody who has seen the data.
--
-- insider_transactions holds one row a line of a form's two transaction tables:
-- Table I (non-derivative: the shares themselves) and Table II (derivative: options,
-- warrants, convertible notes). A row is keyed by the filing's accession number and its
-- position in the filing, non-derivative rows first and then derivative rows, each in
-- document order and counted from zero. A filing never changes once accepted, so the
-- position is stable and reading a filing twice writes the same rows.
--
-- Every column is what the form states. A field the form leaves empty is null: a price
-- given only in a footnote is null with the footnote kept, and the Rule 10b5-1 box is
-- null on a form filed before the box existed (April 2023), which is not the same as a
-- box left unticked. Nothing here is worked out. shares times price is done at read
-- time, in insiders.py, and only where both are stated.
--
-- An amendment (4/A) is stored as its own rows under its own accession, beside the
-- rows of the form it corrects. Which of them counts is decided at read time, because
-- an amendment sometimes restates the whole form and sometimes one line of it and the
-- form does not say which.
CREATE TABLE IF NOT EXISTS insider_transactions (
    id                    INTEGER PRIMARY KEY,
    company_id            INTEGER NOT NULL REFERENCES companies(id),
    accession             TEXT NOT NULL,
    row_index             INTEGER NOT NULL,  -- position in the filing, from 0
    form_type             TEXT NOT NULL,     -- 4 or 4/A, as the document itself says
    filed_date            TEXT,              -- ISO date EDGAR lists the filing under
    accepted_at           TEXT,              -- the moment EDGAR accepted it, UTC
    original_filed_date   TEXT,              -- 4/A only: the filing it amends
    period_of_report      TEXT,              -- date of the earliest transaction reported
    owner_name            TEXT,              -- first reporting owner, as EDGAR prints it
    owner_cik             TEXT,
    other_owners          TEXT,              -- joint filers on the same form, '; ' between
    is_director           INTEGER,           -- 1, 0, or null where the form has no box.
    is_officer            INTEGER,           -- True of any reporting owner on the form.
    officer_title         TEXT,
    is_ten_percent_owner  INTEGER,
    is_other              INTEGER,
    security_title        TEXT,
    transaction_date      TEXT,
    transaction_code      TEXT,              -- P, S, A, M, F, G and the rest of Form 4's codes
    shares                REAL,              -- Table II: the number of derivative securities
    price_per_share       REAL,              -- Table II: the price of the derivative security
    acquired_disposed     TEXT,              -- A or D
    shares_owned_after    REAL,
    ownership             TEXT,              -- D direct, I indirect
    ownership_nature      TEXT,              -- for an indirect holding: by trust, by spouse
    is_derivative         INTEGER NOT NULL DEFAULT 0,  -- 1 for a Table II row
    exercise_price        REAL,              -- Table II only
    underlying_title      TEXT,              -- Table II only: the security it converts into
    underlying_shares     REAL,              -- Table II only
    plan_10b5_1           INTEGER,           -- the form's Rule 10b5-1 box: 1, 0, null
    footnotes             TEXT,              -- verbatim, the footnotes this row cites
    url                   TEXT NOT NULL,     -- the ownership XML the row was read from
    fetched_at            TEXT DEFAULT (datetime('now')),
    UNIQUE (accession, row_index)
);
CREATE INDEX IF NOT EXISTS idx_insider_transactions_company
    ON insider_transactions (company_id, transaction_date);

-- Every Form 4 the fetcher has opened for a company, and what became of it.
--
-- insider_transactions alone cannot say which filings have been read, because many
-- filings leave no row there. A company's filing list on EDGAR carries the Form 4s it
-- filed as a shareholder of somebody else beside the ones filed about its own shares
-- (GSK's list holds its purchases of Wave Life Sciences, Sanofi's its conversions in two
-- newly listed biotechs), and the list does not say which is which: only the document's
-- issuer does. A form can also report holdings and no transaction. Without a record of
-- those, each would be downloaded again on every run for as long as it sat inside the
-- lookback.
--
-- One row a company and accession, not an accession alone: where the shareholder and the
-- issuer are both in the universe the same filing is on two lists, stored for the issuer
-- and set aside for the holder.
CREATE TABLE IF NOT EXISTS insider_filings (
    company_id   INTEGER NOT NULL REFERENCES companies(id),
    accession    TEXT NOT NULL,
    form_type    TEXT,
    filed_date   TEXT,
    outcome      TEXT NOT NULL,   -- stored, no_transactions, not_issuer, unreadable
    issuer_cik   TEXT,            -- who the form is about, where it could be read
    row_count    INTEGER NOT NULL DEFAULT 0,
    url          TEXT,
    read_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (company_id, accession)
);
