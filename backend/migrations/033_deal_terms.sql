-- What a deal pays, split into the four commitments a filing states separately.
--
-- A deal captured from a headline has no size. "Johnson & Johnson Announces Collaboration
-- with Sail Biomedicines" says something happened and nothing about whether it matters.
-- The press release furnished with the same day's 8-K says J&J pays 785m now, of which
-- 465m buys equity rather than rights, 140m more if development milestones are hit, and
-- 2.58bn only if it exercises its option to acquire.
--
-- Four numbers, four meanings. A single value column flattens them into one figure that is
-- wrong whichever it picks: 2.58bn overstates what is being spent, 785m understates what
-- the deal is worth if it runs. So each is stored as itself and nothing is summed.
--
-- equity_usd is part of upfront_usd, not additional to it, because that is what the filing
-- says: "total initial payments of $785 million, including a $465 million equity
-- investment". Any display has to say it the same way.
--
-- terms_evidence is the sentence the figures were read from. These numbers rank a deal on
-- the front page, so the clause that produced them travels with them.

ALTER TABLE deals ADD COLUMN upfront_usd REAL;
ALTER TABLE deals ADD COLUMN equity_usd REAL;
ALTER TABLE deals ADD COLUMN milestones_usd REAL;
ALTER TABLE deals ADD COLUMN option_usd REAL;
ALTER TABLE deals ADD COLUMN total_usd REAL;
ALTER TABLE deals ADD COLUMN headline_usd REAL;   -- the one figure to rank and sort on
ALTER TABLE deals ADD COLUMN terms_evidence TEXT;
ALTER TABLE deals ADD COLUMN terms_source TEXT;   -- the accession the terms were read from
