-- A deal value is an announced number, not money that has left the building.
--
-- "up to $3.8 billion" is a headline consideration: it usually includes milestones that
-- may never be earned, often includes stock, and says nothing about when any of it is
-- paid. Cash actually spent on acquisitions is a separate figure, filed in the cash flow
-- statement and read from XBRL into ``financials``. The two never sum, and a column
-- named ``value`` in the deals table invited exactly that.
--
-- So the column is renamed to say what it is. Every stored value moves across unchanged:
-- both sources of this table, the filing extractor and the news headlines, record what
-- an announcement stated, so all of them are announced values.
--
-- Applied once, through the migration ledger.

ALTER TABLE deals ADD COLUMN announced_value TEXT;   -- consideration as announced

UPDATE deals SET announced_value = value WHERE value IS NOT NULL;

ALTER TABLE deals DROP COLUMN value;
