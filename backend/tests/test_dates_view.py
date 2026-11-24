"""Completion dates that moved and exclusivities ending, read from a company's change
feed for its Trials and Portfolio tabs (frontend/dates_view.py)."""

from __future__ import annotations

import datetime as dt
import pathlib
import sys

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
if str(FRONTEND) not in sys.path:
    sys.path.insert(0, str(FRONTEND))

import dates_view as DV  # noqa: E402

TODAY = dt.date(2026, 11, 24)


def _slip(nct, was, now, seen, ticker="ROG"):
    return {"ticker": ticker, "change_type": "date_slip", "date": seen, "detected_at": seen,
            "headline": f"{ticker} trial {nct}: primary completion slips {was} -> {now}"}


def test_a_study_moved_twice_is_one_slip_from_its_first_date_to_its_last():
    feed = [_slip("NCT00000001", "2026-12-31", "2027-05-03", "2026-11-10"),
            _slip("NCT00000001", "2027-05-03", "2027-10-01", "2026-11-20"),
            _slip("NCT00000002", "2027-03", "2027-11", "2026-11-21")]
    rows = DV.slip_rows(feed, TODAY)
    assert [r["nct"] for r in rows] == ["NCT00000001", "NCT00000002"]
    one = rows[0]
    assert (one["was"], one["now"], one["moves"]) == ("2026-12-31", "2027-10-01", 2)
    assert one["days"] == (dt.date(2027, 10, 1) - dt.date(2026, 12, 31)).days
    assert rows[1]["days"] == (dt.date(2027, 11, 1) - dt.date(2027, 3, 1)).days


def test_an_old_move_and_a_correction_of_a_past_date_are_left_out():
    feed = [_slip("NCT00000003", "2027-01-01", "2027-06-01", "2026-09-01"),      # too old
            _slip("NCT00000004", "2026-10-22", "2026-12-22", "2026-11-20"),      # was past
            {"change_type": "loe", "headline": "x", "date": "2026-12-01"}]
    assert DV.slip_rows(feed, TODAY) == []


def test_exclusivities_ending_soon_are_read_by_brand_inside_the_window():
    feed = [{"change_type": "loe", "date": "2026-12-10",
             "headline": "MRK LOE: Gardasil 9 (BLA125508) reference product exclusivity "
                         "(12y) expires 2026-12-10"},
            {"change_type": "loe", "date": "2026-11-24",
             "headline": "MRK LOE: Janumet Xr (NDA202270) drug substance patent expires 2026-11-24"},
            {"change_type": "loe", "date": "2027-03-11",
             "headline": "MRK LOE: Zolinza (NDA21991) drug substance patent expires 2027-03-11"},
            {"change_type": "loe", "date": "2026-10-01",
             "headline": "MRK LOE: Gone (NDA1) drug substance patent expires 2026-10-01"}]
    got = DV.loe_soon(feed, TODAY)
    assert [(e["date"], e["brand"]) for e in got] == [
        ("2026-11-24", "Janumet Xr"), ("2026-12-10", "Gardasil 9")]
    assert got[0]["what"] == "NDA202270 drug substance patent"
    assert got[1]["what"] == "BLA125508 reference product exclusivity (12y)"


def test_the_module_is_pure():
    source = (FRONTEND / "dates_view.py").read_text()
    assert "streamlit" not in source and "urllib" not in source
