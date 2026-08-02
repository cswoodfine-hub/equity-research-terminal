-- A priority review voucher sold, which is the largest cheque a small company ever
-- receives without issuing a share.
--
-- The FDA awards a voucher on approval of a rare paediatric or tropical disease drug, and
-- it is transferable. Abeona was awarded one when ZEVASKYN was approved and sold it for
-- 155m gross against a balance sheet of 226m: two thirds of the company's cash, arriving
-- from a source no financing table and no revenue line records.
--
-- Neither does anything else here. It is not revenue, so no product carries it. It is not
-- a financing, because no security was issued and no shareholder was diluted. It is not
-- an operating item. XBRL tags the gain, not the sale, and the gain nets off a carrying
-- value that is usually zero and sometimes not. So it gets its own row.
--
-- gross_usd and net_usd are separate columns and neither is derived from the other. A
-- filing states one, the other, or both, and the difference is the banker's fee: Abeona
-- printed 155.0m gross and a 152.4m net gain. Storing one figure would mean choosing a
-- fee where none was stated, which is the estimate this repository does not make. A row
-- with only a gross figure is honest about being a gross figure.
--
-- sold_month is a month rather than a date because that is what a press release states,
-- and it is compared against a balance sheet date by month, the same way financings are:
-- a sale in the month of the period end is already inside that cash figure.
--
-- evidence is the sentence the row was read from. These rows move a runway, so the
-- sentence that moved it has to be readable beside it.

CREATE TABLE priority_review_vouchers (
    id          INTEGER PRIMARY KEY,
    company_id  INTEGER NOT NULL REFERENCES companies(id),
    sold_month  TEXT NOT NULL,      -- YYYY-MM, as the filing states it
    gross_usd   REAL,               -- proceeds before fees, where stated
    net_usd     REAL,               -- proceeds after fees, where stated
    evidence    TEXT,
    accession   TEXT,
    form_type   TEXT,
    filed_date  TEXT,
    section     TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_prv_company ON priority_review_vouchers(company_id, sold_month);
