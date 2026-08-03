"""Where the money went: the things a company spends on, by year.

Research done, research bought, plant, acquisitions, buybacks and dividends. The mix is
a decision rather than a result, and nothing else in this repository reads it.
"""

import pytest

import allocation
import db


def _seed(tmp_path, rows, ticker="JNJ"):
    """rows: (period_end, metric, value)."""
    path = tmp_path / "t.db"
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, ?, ?)",
                 (ticker, ticker))
    for period_end, metric, value in rows:
        conn.execute(
            "INSERT INTO financials (company_id, period_end, period_type, metric,"
            "                        value, unit, fiscal_year)"
            " VALUES (1, ?, 'FY', ?, ?, 'USD', ?)",
            (period_end, metric, value, int(period_end[:4])))
    conn.commit()
    conn.close()
    return path


def test_a_year_is_keyed_on_when_it_closes_not_on_the_column(tmp_path):
    """Johnson & Johnson runs a 52/53 week calendar, so its fiscal 2020 closed on
    3 January 2021 and EDGAR files it against 2021. Keyed on the column, every year of
    its spending came out a year late and calendar 2020 was empty because no year end
    fell inside it."""
    path = _seed(tmp_path, [
        ("2021-01-03", "ResearchAndDevelopmentExpense", 12.2e9),
        ("2022-01-02", "ResearchAndDevelopmentExpense", 14.3e9),
    ])
    years = [row["fiscal_year"] for row in allocation.build(path, "JNJ")["years"]]
    assert years == [2021, 2020]


def test_the_five_uses_come_back_per_year(tmp_path):
    path = _seed(tmp_path, [
        ("2025-12-28", "ResearchAndDevelopmentExpense", 14.7e9),
        ("2025-12-28", "CapitalExpenditure", 4.8e9),
        ("2025-12-28", "AcquisitionsNet", 17.5e9),
        ("2025-12-28", "ShareRepurchases", 6.0e9),
        ("2025-12-28", "DividendsPaid", 12.4e9),
        ("2025-12-28", "CashFlowOperating", 24.5e9),
    ])
    row = allocation.build(path, "JNJ")["years"][0]
    assert row["rd"] == pytest.approx(14.7e9)
    assert row["capex"] == pytest.approx(4.8e9)
    assert row["acquisitions"] == pytest.approx(17.5e9)
    assert row["buybacks"] == pytest.approx(6.0e9)
    assert row["dividends"] == pytest.approx(12.4e9)
    assert row["operating"] == pytest.approx(24.5e9)


def test_a_line_the_filer_never_tags_is_named_rather_than_zeroed(tmp_path):
    """Biogen pays no dividend and Dyne has never bought a company. Neither is a zero,
    and drawing one would say the company chose to spend nothing where in fact it does
    not report the line at all."""
    path = _seed(tmp_path, [
        ("2025-12-28", "ResearchAndDevelopmentExpense", 2.0e9),
        ("2025-12-28", "CapitalExpenditure", 0.15e9),
    ], ticker="BIIB")
    built = allocation.build(path, "BIIB")
    assert built["untagged"] == ["Acquisitions", "Buybacks", "Dividends"]
    assert built["years"][0]["dividends"] is None


def test_a_year_with_nothing_tagged_is_dropped(tmp_path):
    """The chart starts where the filer's own disclosure does, not at an empty bar."""
    path = _seed(tmp_path, [
        ("2025-12-28", "ResearchAndDevelopmentExpense", 14.7e9),
        # 2024 carries only an operating line, which is not one of the five uses.
        ("2024-12-29", "CashFlowOperating", 24.3e9),
    ])
    assert [r["fiscal_year"] for r in allocation.build(path, "JNJ")["years"]] == [2025]


def test_years_come_back_newest_first_and_capped(tmp_path):
    path = _seed(tmp_path, [
        (f"{year}-12-31", "ResearchAndDevelopmentExpense", 1e9)
        for year in range(2012, 2026)
    ])
    years = [r["fiscal_year"] for r in allocation.build(path, "JNJ", years=5)["years"]]
    assert years == [2025, 2024, 2023, 2022, 2021]


def test_an_unknown_ticker_is_none(tmp_path):
    assert allocation.build(_seed(tmp_path, []), "NOPE") is None


def test_only_full_years_count(tmp_path):
    """A quarter's research is not a year's, and the band is annual."""
    path = _seed(tmp_path, [("2025-12-28", "ResearchAndDevelopmentExpense", 14.7e9)])
    conn = db.get_connection(path)
    conn.execute(
        "INSERT INTO financials (company_id, period_end, period_type, metric, value,"
        "                        unit, fiscal_year)"
        " VALUES (1, '2025-09-28', 'Q', 'ResearchAndDevelopmentExpense', 3.6e9,"
        "         'USD', 2025)")
    conn.commit()
    conn.close()
    assert allocation.build(path, "JNJ")["years"][0]["rd"] == pytest.approx(14.7e9)


def test_research_is_marked_as_sitting_above_the_line():
    """It is expensed through operating cash flow, so the total is what the company
    spent rather than what it did with its free cash flow."""
    assert "rd" in allocation.ABOVE_THE_LINE
    assert all(key not in allocation.ABOVE_THE_LINE
               for key in ("capex", "acquisitions", "buybacks", "dividends"))


def test_molecules_bought_are_drawn_where_research_is_known_to_exclude_them(tmp_path):
    """Lilly structures most of its business development as asset acquisitions, so it
    tags no acquisitions line and three billion a year of its spending sat in no segment.
    It publishes research excluding acquired in-process cost, which is what makes the two
    separable."""
    path = _seed(tmp_path, [
        ("2025-12-31", "ResearchAndDevelopmentExpense", 13.34e9),
        ("2025-12-31", "ResearchExcludingAcquiredIprd", 13.34e9),
        ("2025-12-31", "AcquiredIprd", 3.01e9),
    ], ticker="LLY")
    row = allocation.build(path, "LLY")["years"][0]
    assert row["acquired_rd"] == pytest.approx(3.01e9)
    assert row["rd"] == pytest.approx(13.34e9)


def test_molecules_bought_are_dropped_where_research_may_already_contain_them(tmp_path):
    """Allogene's 2018 research of 152m is 109m of acquired in-process cost and the rest
    spent in the labs. It never publishes the excluding concept, so the two cannot be
    told apart, and drawing both would count that 109m twice."""
    path = _seed(tmp_path, [
        ("2018-12-31", "ResearchAndDevelopmentExpense", 152e6),
        ("2018-12-31", "AcquiredIprd", 109e6),
    ], ticker="ALLO")
    built = allocation.build(path, "ALLO")
    assert built["years"][0]["acquired_rd"] is None
    assert built["years"][0]["rd"] == pytest.approx(152e6)
    # The money is not lost, it stays inside research where the filer put it, and the
    # year is named so the panel can say so. Allogene does file the line, so calling it
    # untagged would be untrue.
    assert built["inside_research"] == [2018]
    assert "Acquired R&D" not in built["untagged"]


def test_the_separability_test_is_made_year_by_year(tmp_path):
    """Lilly began publishing the excluding concept in 2021. The years before it are
    plain-tag years and are read as such."""
    path = _seed(tmp_path, [
        ("2021-12-31", "ResearchAndDevelopmentExpense", 6.93e9),
        ("2021-12-31", "ResearchExcludingAcquiredIprd", 6.93e9),
        ("2021-12-31", "AcquiredIprd", 0.67e9),
        ("2020-12-31", "ResearchAndDevelopmentExpense", 5.98e9),
        ("2020-12-31", "AcquiredIprd", 0.66e9),
    ], ticker="LLY")
    built = allocation.build(path, "LLY")
    drawn = {row["fiscal_year"]: row["acquired_rd"] for row in built["years"]}
    assert drawn[2021] == pytest.approx(0.67e9)
    assert drawn[2020] is None
    assert built["inside_research"] == [2020]


def test_a_reported_zero_is_not_an_untagged_line(tmp_path):
    """Johnson & Johnson tags zero acquisitions for fiscal 2023, three times over three
    annual reports: it bought nothing that year, having closed Abiomed in the one before.
    Biogen files no dividend line at all. Neither draws a segment, because neither has a
    width, and only the second is an absence of disclosure."""
    path = _seed(tmp_path, [
        ("2023-12-31", "ResearchAndDevelopmentExpense", 15.1e9),
        ("2023-12-31", "AcquisitionsNet", 0.0),
    ])
    built = allocation.build(path, "JNJ")
    assert "Acquisitions" not in built["untagged"]
    assert built["reported_nil"]["Acquisitions"] == [2023]
    # Dividends were never filed, so they are the absence.
    assert "Dividends" in built["untagged"]
    assert "Dividends" not in built["reported_nil"]
