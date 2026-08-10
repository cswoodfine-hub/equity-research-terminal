-- Where a company lists its press releases, for the sixteen that publish no feed.
--
-- Fifty-four of seventy carry an RSS url in ir_rss_url. The rest, which includes GSK,
-- Merck, Johnson & Johnson, Sanofi, Roche and Novo Nordisk, publish their releases as a
-- web page and nothing else. That page is read through Jina Reader rather than parsed as
-- a feed, so it gets its own column: a company can have one, the other, or neither, and
-- which one it has decides which fetcher runs.
ALTER TABLE companies ADD COLUMN ir_news_url TEXT;
