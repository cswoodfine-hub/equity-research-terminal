"""A study belongs to the company the registry names as its lead sponsor.

Pfizer's completed-studies fetch filed five Orexigen Therapeutics studies of naltrexone
SR/bupropion SR as Pfizer's own, because the company's own query was believed without
checking the lead sponsor the registry states. Orexigen was never a Pfizer company.
"""

import datetime as dt
import io
import json
from pathlib import Path

import ctgov
import db
import sponsor_attribution
from fetchers import trials_completed
from fetchers.trials_completed import TrialsCompletedFetcher

FIXTURE = Path(__file__).parent / "fixtures" / "ctgov_completed_pfe.json"
OREXIGEN = {"NCT00567255", "NCT00711477", "NCT00474630", "NCT00532779", "NCT00456521"}


def _seed(tmp_path):
    path = str(tmp_path / "attribution.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name, ctgov_sponsor)"
                 " VALUES ('PFE', 'Pfizer Inc', 'Pfizer')")
    conn.execute("INSERT INTO companies (ticker, name, ctgov_sponsor)"
                 " VALUES ('LLY', 'Eli Lilly and Company', 'Eli Lilly and Company')")
    pfe = conn.execute("SELECT id FROM companies WHERE ticker = 'PFE'").fetchone()[0]
    conn.execute("INSERT INTO deals (company_id, deal_type, counterparty, event_date)"
                 " VALUES (?, 'acquisition', 'Biohaven Pharmaceuticals', ?)",
                 (pfe, (dt.date.today() - dt.timedelta(days=365)).isoformat()))
    conn.commit()
    conn.close()
    return path, pfe


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _serve(monkeypatch, payload):
    """The registry, answering every query with the one payload."""
    body = json.dumps(payload).encode()
    monkeypatch.setattr(trials_completed.urllib.request, "urlopen",
                        lambda *a, **k: _Response(body))


def test_the_lead_sponsor_decides_whose_study_it_is():
    pfizer = ["Pfizer", "Pfizer Inc"]
    assert not ctgov.lead_names("Orexigen Therapeutics, Inc", pfizer)
    assert ctgov.lead_names("Pfizer", pfizer)
    # A subsidiary names its parent, so its studies are the parent's.
    assert ctgov.lead_names("Wyeth is now a wholly owned subsidiary of Pfizer", pfizer)
    assert ctgov.lead_names("Karuna Therapeutics, Inc., a Bristol Myers Squibb company",
                            ["Bristol-Myers Squibb"])
    assert ctgov.lead_names("Sierra Oncology LLC - a GSK company", ["GSK plc"])
    # Merck & Co is not Merck KGaA: "Co" is part of the name, not a legal form.
    assert not ctgov.lead_names("Merck KGaA, Darmstadt, Germany",
                                ["Merck Sharp & Dohme LLC", "Merck & Co Inc"])
    assert not ctgov.lead_names(None, pfizer)
    assert not ctgov.lead_names("Pfizer", [])


def test_own_names_are_the_registry_term_and_the_legal_name(tmp_path):
    path, _ = _seed(tmp_path)
    assert sponsor_attribution.own_names("PFE", path) == ["Pfizer", "Pfizer Inc"]


def test_the_fetch_keeps_only_studies_the_company_leads(tmp_path, monkeypatch):
    path, pfe = _seed(tmp_path)
    _serve(monkeypatch, json.loads(FIXTURE.read_text()))
    fetcher = TrialsCompletedFetcher("PFE", path)
    raw = fetcher.fetch()
    kept = {s["protocolSection"]["identificationModule"]["nctId"] for s in raw["studies"]}
    assert not kept & OREXIGEN
    assert {"NCT9900001", "NCT9900002"} <= kept


def test_a_misfiled_study_on_file_is_taken_off_on_the_next_fetch(tmp_path, monkeypatch):
    path, pfe = _seed(tmp_path)
    conn = db.get_connection(path)
    for nct_id, lead in (("NCT00567255", "Orexigen Therapeutics, Inc"),
                         # A study of a company Pfizer acquired stays.
                         ("NCT9900003", "Biohaven Pharmaceuticals, Inc."),
                         # A row with no lead on file cannot be judged and stays.
                         ("NCT9900004", None)):
        conn.execute("INSERT INTO completed_trials (nct_id, sponsor_company_id,"
                     " lead_sponsor) VALUES (?, ?, ?)", (nct_id, pfe, lead))
        conn.execute("INSERT INTO trial_interventions (nct_id, name, norm, kind)"
                     " VALUES (?, 'x', 'x', 'DRUG')", (nct_id,))
    conn.commit()
    conn.close()

    _serve(monkeypatch, json.loads(FIXTURE.read_text()))
    fetcher = TrialsCompletedFetcher("PFE", path)
    result = fetcher.upsert(fetcher.normalise(fetcher.fetch()))

    conn = db.get_connection(path)
    on_file = {r[0] for r in conn.execute("SELECT nct_id FROM completed_trials")}
    drugs = {r[0] for r in conn.execute("SELECT nct_id FROM trial_interventions")}
    conn.close()
    assert "NCT00567255" not in on_file and "NCT00567255" not in drugs
    assert {"NCT9900001", "NCT9900002", "NCT9900003", "NCT9900004"} <= on_file
    assert any("taken off PFE" in n for n in result.notes)


def test_a_study_is_refiled_under_the_company_that_leads_it(tmp_path, monkeypatch):
    """A row another company's loose query claimed first moves to its lead sponsor."""
    path, pfe = _seed(tmp_path)
    conn = db.get_connection(path)
    lly = conn.execute("SELECT id FROM companies WHERE ticker = 'LLY'").fetchone()[0]
    conn.execute("INSERT INTO completed_trials (nct_id, sponsor_company_id, lead_sponsor)"
                 " VALUES ('NCT9900001', ?, 'Pfizer')", (lly,))
    conn.commit()
    conn.close()

    _serve(monkeypatch, json.loads(FIXTURE.read_text()))
    fetcher = TrialsCompletedFetcher("PFE", path)
    fetcher.upsert(fetcher.normalise(fetcher.fetch()))
    conn = db.get_connection(path)
    owner = conn.execute("SELECT sponsor_company_id FROM completed_trials"
                         " WHERE nct_id = 'NCT9900001'").fetchone()[0]
    conn.close()
    assert owner == pfe

