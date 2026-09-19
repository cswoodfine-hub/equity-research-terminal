"""The claims between enterprise value and the shareholders, read from the filings."""

from __future__ import annotations

import pathlib
import zipfile

import pytest

import db
import other_claims as OC

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def cache(tmp_path):
    """A data-set archive of the shape the SEC publishes, from the saved sample."""
    directory = tmp_path / "cache"
    directory.mkdir()
    with zipfile.ZipFile(directory / "fsds_2026q1.zip", "w") as archive:
        archive.writestr("sub.txt", (FIXTURES / "fsds_sub_sample.txt").read_text())
        archive.writestr("num.txt", (FIXTURES / "fsds_num_sample.txt").read_text())
    return directory


@pytest.fixture
def empty_curated(tmp_path):
    return tmp_path / "none.csv"


def test_each_item_is_read_from_its_own_concept(cache):
    got = OC.build([200406, 1131399, 879169], cache)
    jnj = got["200406"]["items"]
    assert jnj["pension_deficit"]["value"] == 6957000000.0
    assert jnj["pension_deficit"]["as_of"] == "20251231"      # not the prior year end
    assert "noncontrolling_interests" not in jnj              # a segmented row is not the group
    gsk = got["1131399"]["items"]
    assert gsk["pension_deficit"]["value"] == 1687000000.0
    assert gsk["equity_method_investments"]["value"] == 89000000.0
    assert got["1131399"]["form"] == "20-F"


def test_a_current_and_non_current_half_are_added(cache):
    incy = OC.build([879169], cache)["879169"]["items"]
    assert incy["contingent_consideration"]["value"] == 121000000.0
    assert "+" in incy["contingent_consideration"]["tag"]     # the source names both


def test_a_negative_minority_interest_is_taken_as_nil_with_the_reason(cache,
                                                                     empty_curated):
    filing = OC.build([1131399], cache)["1131399"]
    lines = {l["item"]: l for l in OC._lines(filing, "GSK", {})}
    nci = lines["noncontrolling_interests"]
    assert nci["value"] == 0.0
    assert "not a credit" in nci["note"] and "-421" in nci["note"]
    # The other three still stand, so the company's net claim is a deduction.
    assert round(sum(l["sign"] * l["value"] for l in lines.values()), 3) == -2946.0


def test_the_curated_file_carries_a_sign_and_a_source(tmp_path):
    path = tmp_path / "c.csv"
    path.write_text("# note\nticker,item,label,kind,value,as_of,source,note\n"
                    "JNJ,talc_reserve,talc,liability,3400,2025-12-28,10-K note 19,tail not counted\n"
                    "SNY,stake,a stake,asset,3259,2025-12-31,20-F note D.1,\n"
                    "SNY,broken,,asset,not a number,,,\n")
    got = OC.curated(path)
    assert [r["sign"] for r in got["JNJ"]] == [-1]
    assert got["SNY"][0]["value"] == 3259.0 and got["SNY"][0]["sign"] == 1
    assert len(got["SNY"]) == 1              # the unparseable row is dropped, not guessed


def test_store_writes_the_rows_and_clears_what_a_filer_no_longer_reports(tmp_path, cache):
    path = str(tmp_path / "claims.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name, cik) VALUES"
                 " ('JNJ', 'J&J', 200406), ('GSK', 'GSK', 1131399),"
                 " ('AMGN', 'Amgen', 318154)")
    conn.commit()
    curated_path = tmp_path / "c.csv"
    curated_path.write_text("ticker,item,label,kind,value,as_of,source,note\n"
                            "JNJ,talc_reserve,talc claims,liability,3400,2025-12-28,10-K,\n")

    got = OC.store(conn, cache, curated_path)
    assert got["companies"] == 3
    jnj = OC.for_company(conn, "JNJ")
    assert round(jnj["total"], 3) == -10357.0          # 6,957 pension plus 3,400 talc
    assert {l["item"] for l in jnj["lines"]} == {"pension_deficit", "talc_reserve"}
    assert any(l["basis"] == "filed" for l in jnj["lines"])
    # A filer with no claims tagged says so rather than reading nil.
    assert OC.for_company(conn, "AMGN")["reason"]

    # Run again with the talc row settled: the stale row goes and the filed one stays.
    curated_path.write_text("ticker,item,label,kind,value,as_of,source,note\n")
    again = OC.store(conn, cache, curated_path)
    assert again["removed"] == 1
    assert {l["item"] for l in OC.for_company(conn, "JNJ")["lines"]} == {"pension_deficit"}
    conn.close()


def test_a_filer_outside_the_book_is_not_indexed(cache):
    assert "999999" not in OC.build([200406], cache)


def test_the_committed_curated_file_sources_every_row():
    rows = OC.curated()
    assert rows, "the curated claims file read nothing"
    for ticker, lines in rows.items():
        for line in lines:
            assert line["source"], f"{ticker} {line['item']} has no source"
            assert line["value"] > 0, "a claim is stored with its sign, not a negative value"
