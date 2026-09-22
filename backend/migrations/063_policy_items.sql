-- Dated policy documents, on their own route, carrying no modelled number.
--
-- Everything else in this branch had to state a measured per-share effect before it
-- earned a place. No policy fact can, without an applied tariff or price assumption,
-- and neither is published: the imported share of cost of goods is not free data and
-- the most-favoured-nation deal terms are undisclosed. So an applied number here would
-- be invention with a citation attached.
--
-- The second route admits a document instead, on a stricter test than the first: a
-- publication date and a stable document number from a primary source. It gets no
-- threshold, no per-share sentence and no forecast hook. It is context, and the column
-- names say so.
--
-- Two lanes, both measured from 2025-01-01 before being built, because the agency and
-- term filters alone are not precise enough to trust:
--
--   bis_pharma   Bureau of Industry and Security, term "pharmaceuticals". Five hits,
--                of which a Framework for Artificial Intelligence Diffusion and a
--                Section 232 investigation into personal protective equipment and
--                medical devices are not about medicines. A title gate on
--                "pharmaceutical" leaves the two that are, including the Section 232
--                pharmaceutical investigation of 2025-04-16 that started all of it.
--   cms_ira      Centers for Medicare and Medicaid Services, term "drug price
--                negotiation". Twenty-seven hits, of which the CMS-42xx docket gate
--                keeps seven. The twenty it drops are hospital payment rules, Medicaid
--                managed care, the ACA benefit notice, and six recurring "Agency
--                Information Collection Activities" notices that carry a real
--                comments_close_on and would otherwise write a junk deadline onto the
--                horizon rail.
--
-- document_number is the dedupe key and is the agency's own, so a re-run writes nothing
-- and a document revised in place updates rather than duplicating.
--
-- published_on, effective_on and comments_close_on are the document's own dates. No
-- fetch date is ever substituted for one, and a null stays null: four of the seven
-- gated CMS rows carry no comment deadline and inventing one would put a date on the
-- rail that nobody set.
--
-- company_id stays null. Neither lane's documents name a manufacturer today, and
-- rssfeed.match_company returns a single company on a first match over an unordered
-- map, so reusing it here would bind a universe-wide rule to whichever company
-- happened to match first. An item with no company is kept, the way the news feed
-- keeps one.

CREATE TABLE IF NOT EXISTS policy_items (
    id                INTEGER PRIMARY KEY,
    lane              TEXT NOT NULL,
    document_number   TEXT NOT NULL,
    title             TEXT NOT NULL,
    doc_type          TEXT,
    subtype           TEXT,
    docket_id         TEXT,
    published_on      TEXT NOT NULL,
    effective_on      TEXT,
    comments_close_on TEXT,
    url               TEXT,
    company_id        INTEGER REFERENCES companies(id),
    fetched_at        TEXT DEFAULT (datetime('now')),
    UNIQUE(document_number)
);

CREATE INDEX IF NOT EXISTS idx_policy_items_date ON policy_items(published_on);
CREATE INDEX IF NOT EXISTS idx_policy_items_lane ON policy_items(lane, published_on);
