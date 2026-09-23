-- Indications that name the same population, so competitors for it can be found.
--
-- pool_crowding has to know which assets are fighting over the same patients. It found
-- them by matching on an identical prevalence figure, which worked by luck: the eight
-- obesity assets happen to carry the same CDC row to the digit. Two drugs treating one
-- disease from prevalence rows sourced differently would not have pooled, and two
-- treating different diseases whose populations happen to round the same way would.
--
-- The right key is the asset-indication pair, which this repository calls its unit of
-- analysis. The difficulty is that one population is written under several names. Of the
-- eight obesity assets, seven sit on Obesity and Viking's VK2735 sits on Weight Loss,
-- and Overweight appears beside Obesity on 44 of its 45 rows describing the same people.
-- Keyed naively on the indication id, VK2735 would be handed a private copy of the same
-- 107.6mm adults, which is the error the crowding correction exists to remove.
--
-- So a group is a statement that two indication ids name one population for the purpose
-- of competing for it. It is deliberately not a disease ontology. The indications table
-- carries a mesh_id and MeSH does relate these terms, but it relates them in ways that
-- are wrong here: Overweight and Obesity are siblings under Overnutrition, while Weight
-- Loss sits under Body Weight Changes with Weight Gain, so a MeSH walk would either miss
-- the pairing or sweep in the opposite condition. A short curated table says what is
-- meant and can be argued with, which a graph traversal cannot.
--
-- Only groups that a crowding solve actually needs are seeded. An indication in no group
-- is its own group, so the table stays small and nothing depends on it being complete.
--
-- group_key is free text and is what the solve groups on. note carries the reason, which
-- is the part a reader needs, since every row here is a judgement about sameness.

-- Keyed on the indication NAME rather than its id. The id is assigned when the
-- derivation first meets a MeSH descriptor, so it does not exist when this migration
-- runs against a fresh database and would seed nothing at all. The name is the stable
-- handle: indications.name is unique and is the descriptor MeSH itself publishes.

CREATE TABLE IF NOT EXISTS indication_groups (
    indication_name TEXT PRIMARY KEY,
    group_key       TEXT NOT NULL,
    note            TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_indication_groups_key ON indication_groups(group_key);

INSERT OR IGNORE INTO indication_groups (indication_name, group_key, note) VALUES
 ('Obesity',          'obesity', 'the branded incretin class is prescribed against one population of adults with obesity or overweight; the modelled assets split across these names while competing for the same patients'),
 ('Overweight',       'obesity', 'appears beside Obesity on 44 of its 45 rows and describes the same people'),
 ('Weight Loss',      'obesity', 'Viking VK2735 sits here while the other seven sit on Obesity; without the group it would be handed a private copy of the same adults'),
 ('Obesity, Morbid',  'obesity', 'a severity band of the same population'),
 ('Pediatric Obesity','obesity', 'a subpopulation of the same disease; kept in the group so a paediatric asset competes rather than standing alone');
