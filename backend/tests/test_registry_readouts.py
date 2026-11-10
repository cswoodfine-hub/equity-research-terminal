"""The registry's record of the trials the calendar waits on: a stop for futility is a
negative pinned to its trial; a stop for enrolment is not a result."""

import datetime as dt

import catalyst_outcomes as CO
import db
import registry_readouts as RR

TODAY = dt.date(2026, 11, 8)


def _book(tmp_path):
    path = str(tmp_path / "r.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'AAA', 'AAA')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, generic_name, is_marketed)"
                 " VALUES (10, 1, 'Rhapsido', 'remibrutinib', 0)")
    for i, nct in enumerate(("NCT00000001", "NCT00000002", "NCT00000003"), start=1):
        conn.execute("INSERT INTO trials (nct_id, sponsor_company_id, asset_id, title, phase, overall_status,"
                     " primary_completion_date) VALUES (?, 1, 10, 'T', 'Phase 3', 'Active not recruiting', '2026-08-01')", (nct,))
        conn.execute("INSERT INTO catalysts (id, company_id, asset_id, catalyst_type, expected_date, date_confidence,"
                     " title, description, is_curated, status, source_url) VALUES (?, 1, 10, 'data readout', '2026-08-01',"
                     " 'estimated', 'Phase 3, Rhapsido', ?, 0, 'pending', ?)",
                     (i, nct, f"https://clinicaltrials.gov/study/{nct}"))
    conn.commit()
    return path, conn


def _payload(entries):
    def study(nct, status, why, pcd="2026-08-01", upd="2026-09-15"):
        return {"protocolSection": {
            "identificationModule": {"nctId": nct},
            "statusModule": {"overallStatus": status, "whyStopped": why,
                             "primaryCompletionDateStruct": {"date": pcd},
                             "lastUpdatePostDateStruct": {"date": upd}}}}
    return {"studies": [study(*e) for e in entries]}


def test_classify_stop_reads_the_registrys_reason():
    assert RR.classify_stop("TERMINATED", "Study stopped for futility at the interim analysis") == "negative"
    assert RR.classify_stop("TERMINATED", "The interim analysis found no benefit") == "negative"
    assert RR.classify_stop("TERMINATED", "Slow enrollment") == "stopped"
    assert RR.classify_stop("TERMINATED", "Business decision; the interim analysis was not the reason") == "stopped"
    assert RR.classify_stop("WITHDRAWN", None) == "stopped"
    assert RR.classify_stop("COMPLETED", None) is None
    assert RR.classify_stop("RECRUITING", "") is None


def test_a_futility_stop_is_a_negative_pinned_to_its_trial_and_resolves_missed(tmp_path):
    path, conn = _book(tmp_path)
    payload = _payload([("NCT00000001", "TERMINATED", "Terminated for futility following the pre-planned interim analysis"),
                        ("NCT00000002", "TERMINATED", "Sponsor decision owing to slow enrollment"),
                        ("NCT00000003", "ACTIVE_NOT_RECRUITING", None, "2027-03-01")])
    asked = []

    def get(url, params):
        asked.append(params["filter.ids"])
        return payload
    got = RR.extract(path, today=TODAY, get=get)
    assert got == {"status": "ok", "due": 3, "asked": 3, "negative": 1, "stopped": 1,
                   "trials_updated": 3, "errors": []}
    assert asked == ["NCT00000001,NCT00000002,NCT00000003"]
    row = conn.execute("SELECT outcome, nct_id, source, event_date, quote FROM trial_readouts").fetchone()
    assert (row["outcome"], row["nct_id"], row["source"], row["event_date"]) == ("negative", "NCT00000001", "registry", "2026-09-15")
    assert row["quote"].startswith("Terminated: Terminated for futility")
    status = {r[0]: r[1] for r in conn.execute("SELECT nct_id, overall_status FROM trials")}
    assert status == {"NCT00000001": "Terminated", "NCT00000002": "Terminated", "NCT00000003": "Active not recruiting"}
    assert conn.execute("SELECT primary_completion_date FROM trials WHERE nct_id='NCT00000003'").fetchone()[0] == "2027-03-01"

    # Asked again, the same termination is one row.
    RR.extract(path, today=TODAY, get=get)
    assert conn.execute("SELECT COUNT(*) FROM trial_readouts").fetchone()[0] == 1

    # The resolver takes the pinned result directly, and the slow-enrolment stop is left
    # to the derivation, which withdraws a stopped study.
    out = CO.resolve(path, today=TODAY, fetch=False)
    assert out["missed"] == 1 and out["slipped"] == 1
    assert conn.execute("SELECT status, updated_at FROM catalysts WHERE id = 1").fetchone()[:] == ("missed", "2026-09-15")
    led = [r for r in CO.ledger(path) if r["catalyst_id"] == 1][0]
    assert led["source"] == "trial_readouts:registry" and "registry id" in led["basis"]


def test_a_registry_result_overturns_an_unknown(tmp_path):
    path, conn = _book(tmp_path)
    conn.execute("UPDATE catalysts SET status = 'unknown' WHERE id = 1")
    conn.commit()
    payload = _payload([("NCT00000001", "TERMINATED", "lack of efficacy at interim")])
    RR.extract(path, today=TODAY, get=lambda url, params: payload)
    out = CO.resolve(path, today=TODAY, fetch=False)
    assert out["overturned"] == 1 and out["missed"] == 1
    assert conn.execute("SELECT status FROM catalysts WHERE id = 1").fetchone()[0] == "missed"


def test_only_due_derived_readouts_are_asked(tmp_path):
    path, conn = _book(tmp_path)
    conn.execute("UPDATE catalysts SET is_curated = 1 WHERE id = 2")                 # the analyst's
    conn.execute("UPDATE catalysts SET expected_date = '2027-01-01' WHERE id = 3")   # not due
    conn.commit()
    assert [r["nct"] for r in RR.due(conn)] == ["NCT00000001"]
