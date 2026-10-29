-- The Orange Book use codes a listed patent carries ("U-4229"), kept as codes.
--
-- A method-of-use patent covers the approved uses its code names, and a generic can
-- carve those out of its label (section viii) while launching on the rest. Stored only as
-- a flag (patent_kind = 'use'), the book could not say which indication a use patent
-- holds, which is what an indication-level carve-out needs. Comma separated, sorted;
-- null where the patent carries none. The code's wording is in FDA's Orange Book
-- appendix, not in the data files.
ALTER TABLE exclusivities ADD COLUMN use_codes TEXT;
