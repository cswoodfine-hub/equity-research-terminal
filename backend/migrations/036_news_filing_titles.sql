-- The 8-K item description, recovered for news rows written before it existed.
--
-- 501 of 3281 news rows read "8-K: 8-K" or "6-K: 6-K", and for six companies it was
-- near total: LLY 42/42, BNTX 59/59, SNY 62/63, AMGN 43/45, JNJ 46/50, BIIB 41/45. A
-- News tab where every line says only which form was filed is not a News tab.
--
-- The item codes were being read correctly the whole time. The news upsert was
-- ON CONFLICT(url) DO NOTHING, so a title written once was frozen for good, while the
-- filings row beside it used DO UPDATE and healed itself on the next refresh. When the
-- item taxonomy landed on 2026-07-19, every filing written on the 18th picked up its
-- description and the news row pointing at the same document did not. So the answer is
-- read off the filings table, which has had it all along, joining on url because that
-- is what the news row stores and what makes it unique.

-- First, the titles that only name the form. A filer types the form's own name into
-- primaryDocDescription when it has nothing else to say, spelled "FORM 6-K" or
-- "CURRENT REPORT", and the fetcher took it for a description. These rows are older
-- than the sixty most recent per company, so a refresh will never revisit them.
UPDATE filings
   SET title = form_type
 WHERE title IS NOT NULL
   AND title <> form_type
   AND (upper(title) = upper(form_type)
        OR upper(title) = 'FORM ' || upper(form_type)
        OR upper(title) IN ('CURRENT REPORT', 'ANNUAL REPORT', 'QUARTERLY REPORT',
                            'TRANSITION REPORT', 'REPORT OF FOREIGN PRIVATE ISSUER',
                            'REPORT OF FOREIGN ISSUER'));

-- Then the news headline, taken from the filing it points at.
UPDATE news
   SET title = f.form_type || ': ' || f.title
  FROM filings f
 WHERE f.url = news.url
   AND news.source = 'edgar_8k'
   AND f.title IS NOT NULL
   AND f.title <> f.form_type
   AND news.title <> f.form_type || ': ' || f.title;

-- What is left is the 6-K. A foreign private issuer files no item codes, because the
-- taxonomy belongs to the domestic forms, and most write "6-K" into the description as
-- well. Nothing can be recovered, so the form is said once rather than twice.
UPDATE news
   SET title = f.form_type
  FROM filings f
 WHERE f.url = news.url
   AND news.source = 'edgar_8k'
   AND (f.title IS NULL OR f.title = f.form_type)
   AND news.title <> f.form_type;
