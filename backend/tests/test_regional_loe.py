"""Regional revenue shares and exclusivity dates, resolved into the engine's regions."""

import pytest

import db
import regional_loe as R


def _db(tmp_path):
    path = str(tmp_path / "r.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'NVO', 'Novo'), (2, 'LLY', 'Lilly')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, generic_name, is_marketed)"
                 " VALUES (1, 1, 'Ozempic', 'Semaglutide', 1), (2, 2, 'Zepbound', 'Tirzepatide', 1)")
    for aid, value in ((1, 127089e6), (2, 13542e6)):
        conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, period, value, unit, is_curated)"
                     " VALUES (?, 2025, 'FY', ?, 'X', 0)", (aid, value))
    for member, region, value in (("US", "US", 88467e6), ("InternationalOperations", "INTL", 38622e6),
                                  ("EUCAN", "EU", 22774e6), ("EmergingMarkets", "EM", 7235e6),
                                  ("APAC", "APAC", 3214e6), ("CN", "CN", 5399e6)):
        conn.execute("INSERT INTO asset_revenue_regions (asset_id, fiscal_year, member, region, value,"
                     " unit, source) VALUES (1, 2025, ?, ?, ?, 'DKK', 'sec_fsds')", (member, region, value))
    for member, region, value in (("US", "US", 13484e6), ("NonUs", "INTL", 58e6)):
        conn.execute("INSERT INTO asset_revenue_regions (asset_id, fiscal_year, member, region, value,"
                     " unit, source) VALUES (2, 2025, ?, ?, ?, 'USD', 'sec_fsds')", (member, region, value))
    conn.execute("INSERT INTO eu_medicines (ema_product_number, name, active_substance, authorised_on)"
                 " VALUES ('EMEA/H/C/004174', 'Ozempic', 'semaglutide', '2018-02-08'),"
                 " ('EMEA/H/C/005422', 'Wegovy', 'semaglutide', '2022-01-06')")
    conn.commit()
    return conn


def _dates(tmp_path, body):
    path = tmp_path / "regions.csv"
    path.write_text("ticker,brand,region,loe,basis,accession,quote,note\n" + body)
    return path


def test_the_finest_split_that_makes_up_the_parent_is_used(tmp_path):
    conn = _db(tmp_path)
    got = R.split(conn, 1)
    assert [p["region"] for p in got["parts"]] == ["US", "EU", "EM", "APAC", "CN"]
    assert got["total"] == pytest.approx(127089e6)


def test_a_two_way_split_is_everything_outside_the_us(tmp_path):
    conn = _db(tmp_path)
    assert [p["region"] for p in R.split(conn, 2)["parts"]] == ["US", "INTL"]
    conn.execute("UPDATE asset_revenue_regions SET region = 'ROW' WHERE asset_id = 2 AND member = 'NonUs'")
    assert [p["region"] for p in R.split(conn, 2)["parts"]] == ["US", "INTL"]


def test_a_split_that_does_not_make_up_the_product_is_not_used(tmp_path):
    conn = _db(tmp_path)
    conn.execute("UPDATE asset_revenue SET value = 20000e6 WHERE asset_id = 2")
    assert R.split(conn, 2) is None


def test_stated_dates_govern_and_the_eu_floor_sits_under_europe(tmp_path):
    conn = _db(tmp_path)
    path = _dates(tmp_path, "NVO,Ozempic,CN,2026,compound patent,0000353278-26-000012,\"q\",\n"
                            "NVO,Ozempic,EU,2027,compound patent,0000353278-26-000012,\"q\",\n"
                            "NVO,Ozempic,ROW,expired,patent lapsed,0000353278-26-000012,\"q\",\n")
    regions = {r["region"]: r for r in R.for_asset(conn, 1, disclosed_path=path)}
    assert regions["CN"]["year"] == 2026 and "China 2026" in regions["CN"]["basis"]
    assert regions["CN"]["share"] == pytest.approx(5399 / 127089)
    # Europe's stated 2027 sits under ten years from Ozempic's 2018 authorisation.
    assert regions["EU"]["year"] == 2028 and "Directive 2001/83/EC" in regions["EU"]["basis"]
    assert regions["EM"]["in_base"] is True and regions["EM"]["year"] is None
    # Asia Pacific takes Japan's date, and none is stated, so it carries none.
    assert regions["APAC"]["year"] is None and "floor_year" not in regions["APAC"]


def test_outside_the_us_takes_the_european_date_and_a_missing_one_leaves_the_floor(tmp_path):
    conn = _db(tmp_path)
    path = _dates(tmp_path, "LLY,Zepbound,JP,2036,compound patent,a,\"q\",\n")
    (intl,) = R.for_asset(conn, 2, disclosed_path=path)
    assert intl["region"] == "INTL" and intl["year"] is None
    assert "floor_year" not in intl                  # tirzepatide is not in this EMA slice
    path = _dates(tmp_path, "LLY,Zepbound,EU,2036,compound patent with SPC,a,\"q\",\n")
    (intl,) = R.for_asset(conn, 2, disclosed_path=path)
    assert intl["year"] == 2036 and "outside the US taken on the European date" in intl["basis"]


def test_a_curated_split_outranks_a_fetched_one(tmp_path):
    conn = _db(tmp_path)
    path = tmp_path / "rev.csv"
    path.write_text("ticker,brand,fiscal_year,region,region_label,value,unit,accession,quote\n"
                    "LLY,Zepbound,2025,US,U.S.,13000,USD,a,\"q\"\n"
                    "LLY,Zepbound,2025,INTL,Outside U.S.,542,USD,a,\"q\"\n")
    assert R.load_curated_revenue(conn, path) == 2
    got = R.split(conn, 2)
    assert {p["member"]: p["value"] for p in got["parts"]} == {"U.S.": 13000e6, "Outside U.S.": 542e6}
