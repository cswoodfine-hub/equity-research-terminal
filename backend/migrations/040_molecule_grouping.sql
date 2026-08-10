-- One molecule, several brands, and which brand the studies belong to.
--
-- Novo sells semaglutide as Ozempic, Wegovy and Rybelsus. All three carry the same
-- generic name, so every semaglutide trial normalised identically and the tie was broken
-- by row order: Wegovy is row 589 and Ozempic 597, so Wegovy took all of them, including
-- a diabetic eye disease study and a NASH study that are not obesity trials. Ozempic, on
-- 127bn of revenue, showed no pipeline at all. 159 molecules are sold under more than one
-- brand by one company, so this is not one drug's problem.
--
-- Attributing a study to every brand of the molecule would triple-count it, and the
-- inflation would land on the biggest franchises. So the studies stay on one row and the
-- grouping is written down instead: molecule_id points every sibling at the holder, and a
-- brand's page reaches its molecule's studies through it rather than showing a blank.
--
-- The holder is the earliest approved sibling, so it is the row the molecule has been
-- known by longest, and the choice is stable rather than incidental. A product with no
-- sibling is its own molecule, which keeps every query the same shape.
ALTER TABLE assets ADD COLUMN molecule_id INTEGER REFERENCES assets(id);

CREATE INDEX IF NOT EXISTS idx_assets_molecule ON assets(molecule_id);
