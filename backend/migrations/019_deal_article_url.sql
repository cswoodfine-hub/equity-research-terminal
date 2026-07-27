-- The article that announced a deal, kept beside the filing that reported it.
--
-- A deal read out of a 10-Q links to the filing, which is the primary record and close
-- to unreadable: the reader wants the announcement. Both are now stored, the article is
-- what the card opens, and the filing stays as the record it was read from.
--
-- Populated for news-sourced rows from their own link, since for those the source and
-- the article are the same thing.

ALTER TABLE deals ADD COLUMN article_url TEXT;

UPDATE deals SET article_url = source_url WHERE accession IS NULL;
