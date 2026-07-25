"""FDA advisory committee meetings from the Federal Register: parsing the notice
titles, the exact and conservative company matches, and the idempotent catalyst write.
No network."""

import json
from pathlib import Path

import db
import fedreg
import seed
from fetchers.adcomm_fedreg import AdCommFetcher

_FIX = Path(__file__).resolve().parent / "fixtures"
_PAYLOAD = json.loads((_FIX / "fedreg_adcomm.json").read_text())
_RAW = _PAYLOAD["results"]


# --- parsing --------------------------------------------------------------
def test_parse_keeps_meetings_and_drops_the_renewal():
    meetings = fedreg.parse_documents(_PAYLOAD)
    # Four of the five notices schedule a meeting; the renewal carries no meeting date.
    assert len(meetings) == 4
    assert all(m["meeting_date"] for m in meetings)
    assert not any("Renewal" in m["title"] for m in meetings)


def test_parse_reads_committee_application_sponsor_and_product():
    first = fedreg.parse_documents(_PAYLOAD)[0]
    assert first["committee"] == "Oncologic Drugs Advisory Committee"
    assert first["application_number"] == "NDA21780"
    assert first["application_label"] == "NDA 21780"
    assert first["sponsor"] == "Eli Lilly and Company"
    assert first["product"] == "Zepbound"
    assert first["meeting_date"] == "2099-03-15"


def test_normalise_appno_strips_leading_zeros_and_ignores_anda():
    assert fedreg.normalise_appno("(BLA) 125827") == "BLA125827"
    assert fedreg.normalise_appno("NDA 021780") == "NDA21780"
    assert fedreg.normalise_appno("ANDA 064033") is None   # generic, not an AdComm app
    assert fedreg.normalise_appno("no number here") is None


# --- fetcher --------------------------------------------------------------
def _seed(db_file):
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    lly = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    conn.execute("INSERT INTO assets (owner_company_id, brand_name, internal_code,"
                 " is_marketed) VALUES (?, 'Zepbound', 'NDA21780', 1)", (lly,))
    conn.commit()
    conn.close()


def _catalysts(db_file):
    conn = db.get_connection(db_file)
    try:
        return [dict(r) for r in conn.execute(
            "SELECT cat.*, c.ticker FROM catalysts cat"
            " JOIN companies c ON c.id = cat.company_id"
            " WHERE cat.catalyst_type = 'AdCom' ORDER BY cat.expected_date")]
    finally:
        conn.close()


def _meetings(db_file):
    conn = db.get_connection(db_file)
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM adcomm_meetings ORDER BY meeting_date")]
    finally:
        conn.close()


def test_normalise_keeps_the_whole_future_calendar_and_marks_matches(tmp_path):
    db_file = tmp_path / "t.db"
    _seed(db_file)
    rows = AdCommFetcher(db_file).normalise(_RAW)
    # Three future scheduled meetings: two LLY and the Replimune one; the renewal has no
    # date and the 2020 meeting is in the past.
    assert len(rows) == 3
    assert sorted(r["ticker"] or "-" for r in rows) == ["-", "LLY", "LLY"]


def test_fetcher_stores_the_calendar_and_catalysts_only_for_matches(tmp_path):
    db_file = tmp_path / "t.db"
    _seed(db_file)
    fetcher = AdCommFetcher(db_file)
    fetcher.upsert(fetcher.normalise(_RAW))

    meetings = _meetings(db_file)
    assert len(meetings) == 3                                  # whole calendar stored
    replimune = next(m for m in meetings if "Replimune" in (m["sponsor"] or ""))
    assert replimune["company_id"] is None                    # kept, but unmatched

    cats = _catalysts(db_file)
    assert len(cats) == 2                                      # only the LLY meetings
    assert all(c["is_curated"] == 0 and c["date_confidence"] == "confirmed"
               and c["ticker"] == "LLY" for c in cats)
    by_title = {c["title"]: c for c in cats}
    assert set(by_title) == {"Zepbound", "Retevmo"}
    assert by_title["Zepbound"]["asset_id"] is not None       # matched on the NDA
    assert by_title["Retevmo"]["asset_id"] is None            # matched on the name
    assert "NDA 21780" in by_title["Zepbound"]["description"]
    assert not any("Vusolimogene" in c["title"] for c in cats)   # non-universe dropped


def test_upsert_is_idempotent(tmp_path):
    db_file = tmp_path / "t.db"
    _seed(db_file)
    fetcher = AdCommFetcher(db_file)
    fetcher.upsert(fetcher.normalise(_RAW))
    fetcher.upsert(fetcher.normalise(_RAW))                   # twice
    assert len(_catalysts(db_file)) == 2
    assert len(_meetings(db_file)) == 3


def test_a_meeting_pulled_from_the_calendar_is_withdrawn(tmp_path):
    db_file = tmp_path / "t.db"
    _seed(db_file)
    fetcher = AdCommFetcher(db_file)
    fetcher.upsert(fetcher.normalise(_RAW))
    assert len(_catalysts(db_file)) == 2 and len(_meetings(db_file)) == 3

    # The NDA meeting drops off the next payload; its future catalyst and calendar row
    # are both withdrawn.
    without_first = [r for r in _RAW if r["document_number"] != "2099-00001"]
    fetcher.upsert(fetcher.normalise(without_first))
    assert [c["title"] for c in _catalysts(db_file)] == ["Retevmo"]
    assert len(_meetings(db_file)) == 2
