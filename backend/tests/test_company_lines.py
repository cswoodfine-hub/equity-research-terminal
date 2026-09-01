"""Revenue no asset carries, and coverage measured against what was actually reported.

The company call measured its coverage against the product rows on file, which are only
what the data sets tag: 94% of Vertex, 64% of Johnson & Johnson. A fully modelled J&J
would have read 100% with a third of the company invisible. Streams are the lines a filer
reports and does not split, run through the marketed engine, so the model can reconcile
to the reported total; the denominator is that total; and what has neither a row nor a
line is named.
"""

import pytest

import company_lines
import db
import forecast_view

MM = 1e6


def _seed(tmp_path, *, reported=None, stream=True, placeholder_asset=False):
    tmp_path.mkdir(parents=True, exist_ok=True)   # a second seed lives in a subdir
    path = str(tmp_path / "s.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'VRTX', 'Vertex')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (1, 1, 'Trikafta', 1)")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (2, 1, 'Kalydeco', 1)")
    # Two tagged products, one modelled. Values in dollars, as asset_revenue holds them.
    conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, period, value, unit,"
                 " source) VALUES (1, 2025, 'FY', ?, 'USD', 'test')", (10_000 * MM,))
    conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, period, value, unit,"
                 " source) VALUES (2, 2025, 'FY', ?, 'USD', 'test')", (1_000 * MM,))
    if reported is not None:
        conn.execute(
            "INSERT INTO financials (company_id, period_end, period_type, metric, value,"
            " unit, fiscal_year, fiscal_period) VALUES (1, '2025-12-31', 'FY',"
            " 'Revenues', ?, 'USD', 2025, 'FY')", (reported * MM,))
    conn.execute(
        "INSERT INTO financials (company_id, period_end, period_type, metric, value,"
        " unit, fiscal_year, fiscal_period) VALUES (1, '2025-12-31', 'FY',"
        " 'WeightedAverageDilutedShares', 100000000, 'shares', 2025, 'FY')")
    marketed = [("therapy_mode", None, "marketed"), ("base_revenue", 10_000, None),
                ("revenue_growth_pct", 0.02, None), ("wacc", 0.08, None),
                ("forecast_start_year", 2026, None), ("forecast_years", 5, None),
                ("cogs_pct", 0.1, None), ("sga_pct", 0.1, None), ("rd_pct", 0.1, None),
                ("tax_rate", 0.2, None), ("pos", 1.0, None)]
    for key, value, text in marketed:
        conn.execute("INSERT INTO assumptions (asset_id, key, value, text_value, source)"
                     " VALUES (1, ?, ?, ?, 'test')", (key, value, text))
    if placeholder_asset:
        conn.execute("INSERT INTO assets (id, owner_company_id, generic_name,"
                     " is_marketed) VALUES (3, 1, 'Pipeline', 0)")
        conn.execute("INSERT INTO indications (id, name) VALUES (1, 'Obesity')")
        for key, value, text, ind in [
                ("therapy_mode", None, "chronic", None),
                ("net_price_per_patient", 0.01, None, None),
                ("discontinuation_pct", 0.3, None, None), ("wacc", 0.09, None, None),
                ("forecast_start_year", 2026, None, None),
                ("forecast_years", 5, None, None), ("cogs_pct", 0.1, None, None),
                ("sga_pct", 0.1, None, None), ("rd_pct", 0.1, None, None),
                ("tax_rate", 0.2, None, None), ("pos", 0.5, None, None),
                ("prevalence", 1_000_000, None, 1), ("eligible_pct", 0.5, None, 1),
                ("incidence", 50_000, None, 1), ("ramp_steepness", 1.2, None, 1)]:
            conn.execute("INSERT INTO assumptions (asset_id, indication_id, key, value,"
                         " text_value, source) VALUES (3, ?, ?, ?, ?, 'test')",
                         (ind, key, value, text))
    if stream:
        company_lines.save(conn, 1, "Royalties", [
            {"key": "base_revenue", "value": 500, "source": "test"},
            {"key": "revenue_growth_pct", "value": 0.0, "source": "test"},
            {"key": "wacc", "value": 0.08, "source": "test"},
            {"key": "forecast_start_year", "value": 2026, "source": "test"},
            {"key": "forecast_years", "value": 5, "source": "test"},
            {"key": "cogs_pct", "value": 0.0, "source": "test"},
            {"key": "sga_pct", "value": 0.0, "source": "test"},
            {"key": "rd_pct", "value": 0.0, "source": "test"},
            {"key": "tax_rate", "value": 0.2, "source": "test"}])
    conn.commit()
    conn.close()
    return path


def test_coverage_is_measured_against_the_reported_total(tmp_path):
    """11,000 of tagged rows, 500 of stream, 12,000 reported. The old denominator was
    11,000 and would have called 10,000 of modelled assets 91%. It is 87.5% of the
    company, and 500 of it is in no row and no line."""
    v = forecast_view.company_verdict(_seed(tmp_path, reported=12_000), "VRTX")
    c = v["coverage"]
    assert c["basis"] == "reported total"
    assert c["reported_revenue"] == pytest.approx(12_000 * MM)
    assert c["tagged_revenue"] == pytest.approx(11_000 * MM)
    assert c["modelled_revenue"] == pytest.approx(10_000 * MM)
    assert c["stream_revenue"] == pytest.approx(500 * MM)
    assert c["untagged_revenue"] == pytest.approx(500 * MM)
    assert c["share"] == pytest.approx(10_500 / 12_000)


def test_without_a_reported_total_the_rows_are_the_denominator_and_say_so(tmp_path):
    v = forecast_view.company_verdict(_seed(tmp_path, reported=None), "VRTX")
    c = v["coverage"]
    assert c["basis"] == "tagged rows"
    assert c["untagged_revenue"] is None
    assert c["share"] == pytest.approx(10_500 / 11_000)


def test_a_stream_is_valued_and_counted(tmp_path):
    v = forecast_view.company_verdict(_seed(tmp_path, reported=12_000), "VRTX")
    assert [s["line"] for s in v["streams"]] == ["Royalties"]
    stream = v["streams"][0]
    assert stream["rnpv"] > 0
    assert stream["per_share"] == pytest.approx(stream["rnpv"] * MM / 100_000_000)
    only_asset = forecast_view.company_verdict(
        _seed(tmp_path / "b", reported=12_000, stream=False), "VRTX")
    assert v["per_share"] > only_asset["per_share"]


def test_a_stream_is_in_the_revenue_build(tmp_path):
    rollup = forecast_view.company_rollup(_seed(tmp_path, reported=12_000), "VRTX")
    combined = dict(rollup["combined"])
    assert combined[2026] == pytest.approx(10_000 * 1.02 + 500)


def test_a_placeholder_asset_is_drawn_and_not_counted(tmp_path):
    path = _seed(tmp_path, reported=12_000, placeholder_asset=True)
    v = forecast_view.company_verdict(path, "VRTX")
    names = {m["name"]: m for m in v["modelled"]}
    assert "Pipeline" in names and names["Pipeline"]["counted"] is False
    assert [p["name"] for p in v["placeholders"]] == ["Pipeline"]
    assert "Pipeline" not in [r["name"] for r in v["refused"]]
    counted_only = forecast_view.company_verdict(
        _seed(tmp_path / "b", reported=12_000), "VRTX")
    assert v["per_share"] == pytest.approx(counted_only["per_share"])
    rollup = forecast_view.company_rollup(path, "VRTX")
    line = next(l for l in rollup["lines"] if l["name"] == "Pipeline")
    assert max(line["revenue_share"]) > 0            # it is in the build


def test_save_refuses_a_key_a_line_cannot_carry(tmp_path):
    path = _seed(tmp_path, reported=12_000)
    conn = db.get_connection(path)
    with pytest.raises(ValueError):
        company_lines.save(conn, 1, "Royalties", [{"key": "prevalence", "value": 1}])
    conn.close()


def test_seeds_bootstrap_and_never_overwrite(tmp_path):
    path = _seed(tmp_path, reported=12_000)
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "vrtx.csv").write_text(
        "ticker,line,scenario,key,value,text_value,unit,source,note\n"
        "VRTX,Royalties,base,base_revenue,999,,mm USD,seed,\n"
        "VRTX,Milestones,base,base_revenue,40,,mm USD,seed,\n")
    conn = db.get_connection(path)
    got = company_lines.load_seeds(conn, seeds)
    assert got == {"written": 1, "skipped": 0}
    by_line = {e["line"]: e["scalars"]["base_revenue"] for e in company_lines.load(conn, 1)}
    assert by_line["Royalties"] == 500                # the row on file wins
    assert by_line["Milestones"] == 40
    conn.close()
