"""The register decides what a company sells, and it has to decide both ways.

Krystal Biotech has sold Vyjuvek since 2023 and every asset it had read unmarketed,
because Vyjuvek is a BLA and drugsfda carries none. Sana Biotechnology sells nothing and
had 82 register rows, because the labeler search matched every company in the directory
with "Biotechnology" in its name. Both payloads are saved here as openFDA returned them,
trimmed, and the same code has to resolve the first and refuse the second.
"""

import json
from pathlib import Path

import db
import marketed
from fetchers.ndc_marketing import NdcMarketingFetcher

FIXTURES = Path(__file__).parent / "fixtures"


def _register(tmp_path, ticker, name, fixture, assets=()):
    """A company, its saved NDC payload written to the register, and its assets."""
    path = str(tmp_path / f"{ticker}.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES (?, ?)", (ticker, name))
    company_id = conn.execute("SELECT id FROM companies").fetchone()[0]
    for generic in assets:
        conn.execute("INSERT INTO assets (owner_company_id, generic_name, is_marketed)"
                     " VALUES (?, ?, 0)", (company_id, generic))
    conn.commit()
    conn.close()

    payload = json.loads((FIXTURES / fixture).read_text())["results"]
    fetcher = NdcMarketingFetcher(ticker, path)
    calls = []

    def fake_run(query):
        calls.append(query)
        return payload if len(calls) == 1 else []

    fetcher._run = fake_run
    fetcher.upsert(fetcher.normalise(fetcher.fetch()))
    return path, calls


def _assets(path):
    conn = db.get_connection(path)
    rows = conn.execute(
        "SELECT brand_name, generic_name, internal_code, modality, is_marketed"
        "  FROM assets").fetchall()
    conn.close()
    return rows


def test_a_gene_therapy_company_resolves_from_the_register(tmp_path):
    """Krystal's own row, among forty-four that are not its own. Its eight assets came
    from its trials and are named KB301 and KB407, so the brand never matches one of
    them and the product has to be written."""
    path, _calls = _register(tmp_path, "KRYS", "Krystal Biotech, Inc.",
                             "ndc_krystal.json", assets=("KB301", "KB407"))

    assert marketed.derive(path) == {"created": 1, "promoted": 0}

    sold = [a for a in _assets(path) if a["is_marketed"]]
    assert len(sold) == 1
    assert sold[0]["brand_name"] == "VYJUVEK"
    assert sold[0]["internal_code"] == "BLA125774"
    assert sold[0]["modality"] == "biologic"
    # And the pipeline it already had is left alone.
    assert {a["generic_name"] for a in _assets(path) if not a["is_marketed"]} == {
        "KB301", "KB407"}


def test_a_clinical_stage_company_stays_clinical_stage(tmp_path):
    """Sana markets nothing. Every row the search returned belongs to a cosmetics house
    that shares the word "Biotechnology" with it, and none of them survives the labeler
    test, so there is nothing left for the register to promote."""
    path, _calls = _register(tmp_path, "SANA", "Sana Biotechnology, Inc.",
                             "ndc_sana.json", assets=("SC291",))

    conn = db.get_connection(path)
    kept = conn.execute("SELECT COUNT(*) FROM ndc_products").fetchone()[0]
    conn.close()
    assert kept == 0

    assert marketed.derive(path) == {"created": 0, "promoted": 0}
    assert [a["is_marketed"] for a in _assets(path)] == [0]


def test_the_search_asks_for_the_company_not_its_category(tmp_path):
    """The query is half the precision. Searching "biotech" is what returned Janssen's
    catalogue in the first place, and a query capped at 100 records can lose the row
    that matters."""
    _path, calls = _register(tmp_path, "KRYS", "Krystal Biotech, Inc.",
                             "ndc_krystal.json")
    assert all("krystal" in call for call in calls)


# --- what the register is allowed to call a product -------------------------------------

def _seed(tmp_path, rows, assets=()):
    path = str(tmp_path / "r.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('BAYN', 'Bayer AG')")
    company_id = conn.execute("SELECT id FROM companies").fetchone()[0]
    for brand, application, started in rows:
        conn.execute(
            "INSERT INTO ndc_products (company_id, brand_name, application_number,"
            "  first_marketed) VALUES (?, ?, ?, ?)",
            (company_id, brand, application, started))
    for brand, code, is_marketed in assets:
        conn.execute("INSERT INTO assets (owner_company_id, brand_name, internal_code,"
                     "  is_marketed) VALUES (?, ?, ?, ?)",
                     (company_id, brand, code, is_marketed))
    conn.commit()
    conn.close()
    return path


def test_a_monograph_product_is_not_a_drug(tmp_path):
    """A company labels its own sunscreen and its own hand sanitiser, and neither is a
    product this terminal has any business calling one. The application number is what
    separates them: a monograph row has none."""
    path = _seed(tmp_path, [("Coppertone Sport", "M020", "2019-04-01"),
                            ("Hand Sanitizer", "505G(a)(3)", "2020-04-20")])
    assert marketed.derive(path) == {"created": 0, "promoted": 0}


def test_packages_of_one_product_are_one_asset(tmp_path):
    """The register lists packages. Aleve is five brand rows against one NDA, and one
    drug, so the application is the key and the shortest brand names it."""
    path = _seed(tmp_path, [("Aleve Caplets Easy Open Arthritis", "NDA020204", "2004-01-01"),
                            ("Aleve Gelcaps", "NDA020204", "2002-06-01"),
                            ("Aleve Caplets", "NDA020204", "2001-03-01")])
    assert marketed.derive(path) == {"created": 1, "promoted": 0}
    sold = _assets(path)
    assert len(sold) == 1
    assert sold[0]["brand_name"] == "Aleve Caplets"
    assert sold[0]["internal_code"] == "NDA20204"


def test_a_product_already_on_file_is_marked_rather_than_written_again(tmp_path):
    """The Orange Book, the Purple Book and openFDA all key on the application, so a
    product one of them already recorded is found by the same key."""
    path = _seed(tmp_path, [("Nubeqa", "NDA212099", "2019-08-16")],
                 assets=[("Nubeqa", "NDA212099", 0)])
    assert marketed.derive(path) == {"created": 0, "promoted": 1}
    assert [a["is_marketed"] for a in _assets(path)] == [1]


def test_a_product_named_by_the_revenue_table_is_found_by_name(tmp_path):
    """A filing names a product and the register licenses it, with no application number
    connecting the two rows. Matching the brand keeps it one asset."""
    path = _seed(tmp_path, [("XARELTO", "NDA202439", "2011-07-01")],
                 assets=[("Xarelto", None, 0)])
    assert marketed.derive(path) == {"created": 0, "promoted": 1}
    rows = _assets(path)
    assert len(rows) == 1
    assert rows[0]["internal_code"] == "NDA202439"


def test_running_twice_changes_nothing(tmp_path):
    path = _seed(tmp_path, [("Nubeqa", "NDA212099", "2019-08-16")])
    marketed.derive(path)
    assert marketed.derive(path) == {"created": 0, "promoted": 0}
    assert len(_assets(path)) == 1
