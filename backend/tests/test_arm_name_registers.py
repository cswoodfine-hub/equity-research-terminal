"""The 2026-11-27 arm names across the universe are named or folded on the built book.

The arm-name reading (book_gaps.summary, trial_mapping.arm_named_assets) listed 44
pipeline rows whose name was a study's arm rather than a molecule: a route ("LY4057996
IV"), a dose ("GSK3772701 50 mg"), a tracer ("[14C]AZD4954 Oral Solution"), a part or
cohort ("AZD1613 - Part A"). Each was given its molecule's name through
data/programme_names.csv, cited to the registry record, or folded into the product it
is an arm of through data/asset_alias_map.csv. These tests read the built book, as the
Lilly register tests do, and skip without one: an arm name that reappears as its own
row is the gap coming back.
"""

import pytest

import db
import trial_mapping

# (ticker, the registry's arm name, the name the row answers to now)
NAMED = (
    ("ARGX", "Adimanebart IV", "adimanebart"),
    ("AZN", "AZD9793 Intravenous (IV) monotherapy", "AZD9793"),
    ("AZN", "AZD2373-Arm 1", "opemalirsen"),
    ("AZN", "AZD8965 low dose", "AZD8965"),
    ("AZN", "[14C]AZD4954 Oral Solution", "AZD4954"),
    ("AZN", "AZD1613 - Part A", "AZD1613"),
    ("BEAM", "BEAM-301: Single dose of BEAM-301 administered by IV", "BEAM-301"),
    ("BMRN", "Dose 1 of BMN 331", "BMN 331"),
    ("BNTX", "RO7198457 intravenous (IV)", "autogene cevumeran"),
    ("GILD", "Cilofexor Dose A", "cilofexor"),
    ("GSK", "RSV/hMPV_V low dose vaccine", "RSV/hMPV combination vaccine"),
    ("GSK", "Low dose Strep A Alum", "4-component Strep A vaccine"),
    ("GSK", "Candidate UTI vaccine low dose formulation 1", "UTI vaccine"),
    ("GSK", "GSK4425689A IV", "GSK4425689A"),
    ("GSK", "Low dose of iNTS-TCV", "iNTS-TCV"),
    ("GSK", "GSK3772701 50 mg", "GSK3772701"),
    ("GSK", "Pan-Salmonella-with-Alum (Low dose) vaccine", "GVGH quadrivalent pan-Salmonella vaccine"),
    ("LLY", "LY3016859 ISA", "fepixnebart"),
    ("LLY", "LY4057996 IV", "LY4057996"),
    ("LLY", "LY4152199 - IV", "LY4152199"),
    ("LLY", "MER511 (IV)", "MER511"),
    ("LLY", "AAVAnc80-antiVEGF via Akouos Delivery Device", "AAVAnc80-antiVEGF"),
    ("LLY", "LY3839056 IV", "LY3839056"),
    ("LNTH", "LNTH2403 Phase 1 dose", "LNTH2403"),
    ("MRK", "V118C (Stage 1)", "V118C"),
    ("NVO", "NNC0662-3168 (Test product-A)", "NNC0662-3168"),
    ("NVS", "EDK060, dose A", "EDK060"),
    ("NVS", "Exl-111 (MAD)", "Exl-111"),
    ("REGN", "Trevogrumab-Part A", "trevogrumab"),
    ("ROG", "RO7121932 IV", "RO7121932"),
    ("SNY", "VXB-241 240 mcg", "VXB-241"),
    ("SNY", "Flu H5 egg pandemic low dose vaccine, with adjuvant",
     "egg-based H5N8 pandemic influenza vaccine"),
    ("SRPT", "SRP-1003 IV Infusion", "SRP-1003"),
    ("VKTX", "SC VK3019", "VK3019"),
    ("VYGR", "VY1706 Low dose", "VY1706"),
)

# (ticker, the arm name, the product or programme it folded into)
FOLDED = (
    ("AZN", "Anifrolumab: SC formulation via AI", "Saphnelo"),
    ("AZN", "Anifrolumab + APFS", "Saphnelo"),
    ("AZN", "AZD9291 80 mg/40 mg", "Tagrisso"),
    ("AZN", "Part A - AZD9291 in combination with AZD6094", "Tagrisso"),
    ("AZN", "SC durvalumab + rHu", "Imfinzi"),
    ("AZN", "Dapagliflozin 10 mg/day (oral)", "Farxiga"),
    ("AZN", "Ticagrelor + Aspirin", "Brilinta"),
    ("GSK", "RSV/hMPV_W low dose vaccine", "RSV/hMPV combination vaccine"),
    ("LLY", "Lispro SC", "Humalog"),
    ("NVS", "Ofatumumab approved dose", "Kesimpta"),
    ("PFE", "Part A: ATM-AVI Single Dose, Cohorts 1-4", "ATM-AVI"),
)


def _conn():
    if not db.DB_PATH.exists():
        pytest.skip(f"no built database at {db.DB_PATH}")
    return db.get_connection()


def _ids(conn, ticker, name):
    return {r["id"] for r in conn.execute(
        """SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
            WHERE c.ticker = ? AND (LOWER(TRIM(COALESCE(a.brand_name, ''))) = LOWER(?)
                   OR LOWER(TRIM(COALESCE(a.generic_name, ''))) = LOWER(?)
                   OR a.id IN (SELECT asset_id FROM asset_aliases
                                WHERE LOWER(TRIM(internal_code)) = LOWER(?)))""",
        (ticker, name, name, name))}


@pytest.mark.parametrize("ticker, arm, name", NAMED)
def test_the_arm_name_is_an_alias_of_one_row_named_for_the_molecule(ticker, arm, name):
    conn = _conn()
    try:
        rows = _ids(conn, ticker, name)
        assert len(rows) == 1, f"{ticker}: {len(rows)} rows answer to {name!r}"
        assert _ids(conn, ticker, arm) == rows, f"{ticker}: {arm!r} is not {name!r}"
        generic = conn.execute("SELECT generic_name FROM assets WHERE id = ?",
                               (next(iter(rows)),)).fetchone()[0]
        assert generic.strip().lower() == name.lower(), f"{ticker}: row still named {generic!r}"
    finally:
        conn.close()


@pytest.mark.parametrize("ticker, arm, product", FOLDED)
def test_the_arm_folded_into_its_product(ticker, arm, product):
    conn = _conn()
    try:
        product_rows = _ids(conn, ticker, product)
        assert len(product_rows) == 1, f"{ticker}: {len(product_rows)} rows answer to {product!r}"
        assert _ids(conn, ticker, arm) == product_rows, f"{ticker}: {arm!r} stands apart from {product!r}"
        own = conn.execute(
            "SELECT COUNT(*) FROM assets a JOIN companies c ON c.id = a.owner_company_id"
            " WHERE c.ticker = ? AND LOWER(TRIM(a.generic_name)) = LOWER(?)",
            (ticker, arm)).fetchone()[0]
        assert own == 0, f"{ticker}: a row is still named {arm!r}"
    finally:
        conn.close()


def test_no_pipeline_row_reads_as_an_arm_on_this_book():
    conn = _conn()
    try:
        left = []
        for ticker, in conn.execute("SELECT ticker FROM companies ORDER BY ticker"):
            left += [(ticker, o["name"]) for o in trial_mapping.arm_named_assets(conn, ticker)]
    finally:
        conn.close()
    assert not left, f"rows named for a study's arm: {left}"
