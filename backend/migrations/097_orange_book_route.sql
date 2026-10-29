-- The route each Orange Book product is taken by, from the book's own "DF;Route" column
-- ("TABLET;ORAL", "SOLUTION;SUBCUTANEOUS"), reduced to oral or non-oral.
--
-- An oral brand loses its market to generics much faster than an inhaler, a pen or a
-- cream, since a pharmacist substitutes a tablet automatically (work/patents/BACKTEST.md:
-- 0.245 of Part D cost kept in the first full year against 0.41), so the erosion default
-- is chosen by route (dose_route.py). Null where the book has not been read since this
-- column arrived, or where a product's live strengths are taken both ways.
-- route_own says the route came from the asset's own application, which then stands over
-- any other application folded into the asset (Ozempic holds Rybelsus's oral NDA).
ALTER TABLE orange_book_listings ADD COLUMN route TEXT;
ALTER TABLE orange_book_listings ADD COLUMN route_own INTEGER NOT NULL DEFAULT 0;
