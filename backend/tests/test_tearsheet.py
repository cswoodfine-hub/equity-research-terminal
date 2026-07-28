"""The tearsheet: a self-contained one-page A4 HTML, honest about gaps."""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


def conn_count(db_file) -> int:
    """However many companies the universe holds. Pinning the number meant the test
    failed on the day a company was added, which is not a defect."""
    import db
    conn = db.get_connection(str(db_file))
    try:
        return conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    finally:
        conn.close()

import db
import diff
import seed
import tearsheet

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "frontend"))


def _seed(db_file):
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    for i in range(5):
        conn.execute(
            "INSERT INTO prices (company_id, as_of, close, interval) VALUES"
            " (?, ?, ?, '1d')", (cid, f"2026-07-0{i + 1}", 100 + i))
    conn.commit()
    conn.close()


def test_tearsheet_writes_a_self_contained_page(tmp_path):
    db_file = tmp_path / "test.db"
    _seed(db_file)

    path = tearsheet.build("LLY", out_dir=tmp_path / "exports", db_path=db_file)
    assert path.exists() and path.name == "LLY_tearsheet.html"
    text = path.read_text()
    # Self-contained: the stylesheet is inline and nothing is fetched from a host.
    # The only http reference is the SVG xmlns, which is a namespace, not a request.
    assert "<style>" in text
    assert "<link" not in text and "<script" not in text
    assert 'src="http' not in text and "@import" not in text
    assert "Eli Lilly" in text and "LLY" in text
    assert "A4" in text                                  # print sized
    # The caveats travel with the sheet.
    assert "US only" in text and "never zero" in text


def test_tearsheet_admits_gaps_rather_than_zeroing(tmp_path):
    """A company with no financials must say so on the sheet, not print zeros."""
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)

    path = tearsheet.build("ROG", out_dir=tmp_path / "exports", db_path=db_file)
    text = path.read_text()
    assert "No SEC financials" in text or "no free data" in text
    assert "Roche" in text


def test_tearsheet_embedded_svgs_are_valid(tmp_path):
    db_file = tmp_path / "test.db"
    _seed(db_file)
    path = tearsheet.build("LLY", out_dir=tmp_path / "exports", db_path=db_file)
    text = path.read_text()
    # Each embedded <svg>...</svg> parses on its own.
    import re
    svgs = re.findall(r"<svg.*?</svg>", text, re.DOTALL)
    assert svgs, "the price line should embed at least one svg"
    for svg in svgs:
        ET.fromstring(svg)


def test_tearsheet_unknown_ticker_raises(tmp_path):
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    with pytest.raises(ValueError, match="unknown ticker"):
        tearsheet.build("ZZZ", out_dir=tmp_path / "exports", db_path=db_file)


def test_build_all_writes_one_sheet_per_company(tmp_path):
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    out = tmp_path / "exports"
    result = tearsheet.build_all(out_dir=out, db_path=db_file)
    assert result["failed"] == []
    # The whole universe, whatever size it is: pinning the number meant the test
    # failed on the day a company was added, which is not a defect.
    expected = conn_count(db_file)
    assert result["count"] == expected
    assert len(list(out.glob("*_tearsheet.html"))) == expected
