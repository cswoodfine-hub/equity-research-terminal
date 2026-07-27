-- Where a deal's date came from.
--
-- A deal read from a 10-Q is dated to the filing, because that is the only date the
-- filing gives: Lilly's April 10-Q listed four acquisitions and dated all four to the
-- day it was filed, though the market saw Orna in February and Centessa in March. The
-- headline that announced each one carries the day it was announced, which is the date
-- the field has always meant, so a headline may move a date earlier and this column
-- records that it did. Later is never taken: a recap is not an announcement.
--
-- 'filing' or 'news'.

ALTER TABLE deals ADD COLUMN event_date_source TEXT;

UPDATE deals SET event_date_source = CASE WHEN accession IS NULL THEN 'news'
                                          ELSE 'filing' END
 WHERE event_date IS NOT NULL;
