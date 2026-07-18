"""Curated catalysts CRUD + calendar window, no network."""

import datetime as dt

import pytest

import catalysts
import db
import seed


def test_add_list_delete(tmp_path):
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)

    near = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    far = (dt.date.today() + dt.timedelta(days=200)).isoformat()
    near_id = catalysts.add_catalyst(db_file, "LLY", "PDUFA", near, "Near PDUFA")
    catalysts.add_catalyst(db_file, "MRK", "data readout", far, "Far readout")

    # The 90-day calendar shows only the near catalyst.
    calendar = catalysts.list_catalysts(db_file, within_days=90)
    assert [c["ticker"] for c in calendar] == ["LLY"]
    assert calendar[0]["is_curated"] == 1 and calendar[0]["status"] == "pending"

    with pytest.raises(ValueError):
        catalysts.add_catalyst(db_file, "ZZZZ", "PDUFA", near, "bad ticker")

    assert catalysts.delete_catalyst(db_file, near_id) is True
    assert catalysts.list_catalysts(db_file, within_days=90) == []  # far one is beyond 90d
