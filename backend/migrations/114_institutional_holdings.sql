-- Who holds a company's shares, from SEC Form 13F.
--
-- The book could say what a readout was worth and nothing about who was already
-- positioned for it. An institutional manager with investment discretion over $100
-- million or more of Section 13(f) securities reports every such holding each calendar
-- quarter on Form 13F, within 45 days of the quarter's end. The SEC publishes the
-- structured part of every filing as a quarterly data set, and fetchers/holders_13f.py
-- reads the rows that name a CUSIP on the book's register (data/cusips.csv).
--
-- Three tables, because three different things are true of a 13F and they change at
-- different times.
--
-- institutional_holdings is what a filing states and never changes: one row for each
-- filing, security, option flag and amount type, with the filing's lines for that
-- security summed. A manager lists one security on several lines (one for each other
-- manager it shares discretion with: BlackRock's report for 30 June 2026 lists Lilly
-- on 23 lines), and the lines are one position.
--
-- institutional_holdings_filings is which filings count, which does change. A manager
-- amends a report, sometimes a year later, and the amendment arrives in a later data
-- set than the report it corrects. So whether a filing stands is state, kept on the
-- filing and recomputed whenever a new filing arrives for that manager and period.
-- Nothing is deleted when a report is restated: the superseded filing and its rows stay,
-- marked, so what was known on a given date can still be read back.
--
-- institutional_holdings_releases is which data sets have been read. The daily refresh
-- runs forced, so this, not a snapshot, is the guard: a release here is not downloaded
-- again, and each is about 100 MB.

CREATE TABLE institutional_holdings (
    id               INTEGER PRIMARY KEY,
    company_id       INTEGER NOT NULL REFERENCES companies(id),
    accession_number TEXT NOT NULL,     -- the filing, as EDGAR numbers it
    manager_cik      TEXT NOT NULL,     -- the filer, zero padded to ten digits
    manager_name     TEXT,              -- FILINGMANAGER_NAME on the filing's cover page
    period_of_report TEXT NOT NULL,     -- the quarter end the holdings are stated at
    filing_date      TEXT NOT NULL,     -- when it reached the SEC, up to 45 days later
    cusip            TEXT NOT NULL,
    -- '' for a holding of the security itself, 'Put' or 'Call' for an option on it. An
    -- option row counts the shares the option is over and a value worked from the
    -- share price, not the premium, so it is never added to shares held. The empty
    -- string and not NULL because SQLite treats two NULLs as different in a unique key,
    -- which would let the same position be written twice.
    put_call         TEXT NOT NULL DEFAULT '',
    -- SH or PRN, as filed. PRN is a principal amount, which is how a note is reported,
    -- and a few filers tick it against a share by mistake. Only SH is read as shares.
    shares_type      TEXT NOT NULL,
    shares           INTEGER,           -- SSHPRNAMT summed over the filing's lines
    -- VALUE summed, in dollars. The form asked for thousands until 3 January 2023 and
    -- for dollars since, so a filing made before that date is stored null here and
    -- never scaled. A good many filers still report thousands: the figure is stored as
    -- filed and holders.py sets it aside when it does not square with the share count.
    value_usd        INTEGER,
    source_rows      INTEGER NOT NULL,  -- how many INFOTABLE lines the row sums
    release          TEXT NOT NULL,     -- the data set it was read from
    fetched_at       TEXT DEFAULT (datetime('now')),
    UNIQUE(accession_number, cusip, put_call, shares_type)
);
CREATE INDEX idx_inst_holdings_company ON institutional_holdings(company_id, period_of_report);
CREATE INDEX idx_inst_holdings_manager ON institutional_holdings(manager_cik, period_of_report);

-- Every holdings report (13F-HR and 13F-HR/A) for a period the book covers, whether or
-- not it names a company in the universe. The ones that do not are kept for two
-- reasons. A restatement that drops a holding names nothing here and still replaces the
-- report that did. And "this manager filed for the quarter and no longer lists the
-- share" is a different statement from "this manager has not filed", which only the
-- full list of filers can tell apart. Notice reports (13F-NT) are not kept: they say
-- another manager reports the holdings and carry no table.
CREATE TABLE institutional_holdings_filings (
    accession_number TEXT PRIMARY KEY,
    manager_cik      TEXT NOT NULL,
    manager_name     TEXT,
    period_of_report TEXT NOT NULL,
    filing_date      TEXT NOT NULL,
    submission_type  TEXT NOT NULL,     -- 13F-HR or 13F-HR/A
    report_type      TEXT,              -- 13F HOLDINGS REPORT or 13F COMBINATION REPORT
    is_amendment     INTEGER NOT NULL DEFAULT 0,
    amendment_no     INTEGER,
    amendment_type   TEXT,              -- RESTATEMENT or NEW HOLDINGS, the cover page's two boxes
    -- What the manager's own summary page says its table holds, and what the table
    -- actually holds. They agree for 98 filings in 100. Where the table is far short on
    -- both counts the filing is not the manager's whole report: Norges Bank's for 31
    -- March 2026 states 1,507 lines worth $865 billion and its public table is one
    -- placeholder line (issuer NA, CUSIP 000000000, checked against the filing on
    -- EDGAR). Without these four columns that reads as Norges holding nothing in March
    -- and buying everything by June.
    table_entries    INTEGER,           -- TABLEENTRYTOTAL on the summary page
    table_value      INTEGER,           -- TABLEVALUETOTAL on the summary page
    rows_found       INTEGER,           -- INFOTABLE lines carrying the filing's accession
    value_found      INTEGER,           -- their VALUE, summed
    -- live        the filing counts toward the manager's position for the period;
    -- superseded  a later restatement replaced it (superseded_by names the restatement);
    -- unapplied   an amendment that ticks neither box, so it cannot be known whether
    --             it replaces the report or adds to it. Kept, counted, never applied.
    -- A filing ticked NEW HOLDINGS that superseded_by points at was read as a
    -- restatement, because it is the size of the report it amends: see the fetcher.
    status           TEXT NOT NULL DEFAULT 'live',
    superseded_by    TEXT,
    release          TEXT NOT NULL,
    fetched_at       TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_inst_filings_manager ON institutional_holdings_filings(manager_cik, period_of_report);
CREATE INDEX idx_inst_filings_period ON institutional_holdings_filings(period_of_report, status);

CREATE TABLE institutional_holdings_releases (
    release          TEXT PRIMARY KEY,  -- the ZIP's file name on the SEC's listing page
    zip_url          TEXT NOT NULL,
    window_start     TEXT,              -- the filing dates the data set spans, from its name
    window_end       TEXT,
    -- The quarter end most of its holdings reports are for. A data set is cut by filing
    -- date, not by quarter, so it also holds late reports and amendments for older
    -- quarters: the June to August 2026 one names 100 different periods.
    report_period    TEXT NOT NULL,
    zip_bytes        INTEGER,
    submissions      INTEGER,           -- rows in SUBMISSION.tsv, notices included
    filings_kept     INTEGER,           -- holdings reports for a covered period
    filings_dropped  INTEGER,           -- holdings reports for a period no release here covers
    infotable_rows   INTEGER,           -- lines read
    rows_kept        INTEGER,           -- holdings rows written
    companies        INTEGER,           -- companies with at least one row
    -- The register's CUSIPs when the release was read. A release is read again only if
    -- the register has since gained a CUSIP this list lacks, because a company added to
    -- the register would otherwise have no holders until the next quarter's data set.
    cusips_read      TEXT,
    loaded_at        TEXT DEFAULT (datetime('now'))
);
