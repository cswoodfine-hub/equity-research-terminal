"""The sensitivity grid's second axis is the input the build's mode makes revenue from.

A grid over an input the build never reads is the same figure twenty-five times. That
was every franchise member, every launch and every marketed product carrying a price,
because the axis followed whether a price was on file rather than how revenue is built.
"""

from __future__ import annotations

import pytest

import forecast
import forecast_view as V

COSTS = {"cogs_pct": 0.2, "sga_pct": 0.25, "rd_pct": 0.15, "tax_rate": 0.15,
         "wacc": 0.08, "pos": 1.0, "forecast_start_year": 2026, "forecast_years": 10}


def _inputs(mode: str) -> dict:
    """The least each mode needs to build, with no loss of exclusivity in the window."""
    scalars = dict(COSTS, therapy_mode=mode)
    indications = []
    if mode == "marketed":
        scalars.update(base_revenue=1000.0, revenue_growth_pct=0.05,
                       terminal_growth_pct=0.0, growth_fade_years=5)
    elif mode == "franchise":
        scalars.update(franchise_revenue=5000.0, franchise_growth_pct=0.04,
                       terminal_growth_pct=0.0, share_now=0.2, share_plateau=0.4,
                       share_ramp_pct=0.3)
    elif mode == "launch":
        scalars.update(peak_revenue_musd=2000.0, years_to_peak=6)
    elif mode == "chronic":
        scalars.update(net_price_per_patient=0.05, discontinuation_pct=0.3)
        indications = [{"name": "A disease", "scalars": {
            "prevalence": 100000.0, "incidence": 10000.0, "eligible_pct": 0.5,
            "penetration_peak_pct": 0.05, "ramp_midpoint_year": 3,
            "ramp_steepness": 1.0}, "series": {}}]
    elif mode == "one_time":
        scalars.update(net_price_per_patient=2.0, cogs_per_patient=0.5)
        indications = [{"name": "A disease", "scalars": {}, "series": {
            "new_patients": {2026 + i: 100.0 * (i + 1) for i in range(10)}}}]
    return {"scalars": scalars, "indications": indications, "loe": None,
            "actuals": [], "is_marketed": mode in ("marketed", "franchise")}


MODES = ("marketed", "franchise", "launch", "chronic", "one_time")


def test_each_mode_is_graded_on_the_input_it_builds_revenue_from():
    keys = {mode: V.grid_axis(mode, _inputs(mode)["scalars"],
                              forecast.net_price(_inputs(mode)["scalars"]))["key"]
            for mode in MODES}
    assert keys == {"marketed": "revenue_growth_pct",
                    "franchise": "franchise_growth_pct",
                    "launch": "peak_revenue_musd",
                    "chronic": "net_price_per_patient",
                    "one_time": "net_price_per_patient"}


def test_the_centre_is_the_value_the_build_read_unrounded():
    scalars = dict(_inputs("franchise")["scalars"], franchise_growth_pct=0.0412345)
    axis = V.grid_axis("franchise", scalars, None)
    assert axis["values"][2] == 0.0412345
    assert axis["values"] == pytest.approx([0.0412345 + s for s in V.RATE_STEPS],
                                           abs=1e-4)
    peak = V.grid_axis("launch", dict(peak_revenue_musd=1234.5678), None)
    assert peak["values"][2] == 1234.5678
    assert peak["values"] == pytest.approx([1234.5678 * f for f in V.LEVEL_FACTORS],
                                           rel=1e-3)


def test_a_cheap_price_keeps_five_distinct_steps():
    """A price in millions rounded to three places put a $1,200 drug on one value."""
    axis = V.grid_axis("chronic", {}, 0.0012)
    assert len(set(axis["values"])) == 5
    assert axis["values"] == sorted(axis["values"])


def test_an_axis_with_no_centre_is_refused_not_centred_on_nought():
    scalars = dict(_inputs("marketed")["scalars"])
    scalars.pop("revenue_growth_pct")
    axis = V.grid_axis("marketed", scalars, None)
    assert axis["values"] is None and "revenue_growth_pct" in axis["reason"]
    assert V.grid_axis("chronic", {}, None)["values"] is None
    unknown = V.grid_axis("nonsense", {}, 1.0)
    assert unknown["key"] is None and "nonsense" in unknown["reason"]


@pytest.mark.parametrize("mode", MODES)
def test_every_modes_grid_rises_along_every_column(mode):
    inputs = _inputs(mode)
    built = forecast.build(inputs)
    assert built["mode"] == mode
    axis = V.grid_axis(mode, inputs["scalars"], forecast.net_price(inputs["scalars"]))
    assert axis["values"] == sorted(axis["values"])
    grid = forecast.sensitivity(inputs, "wacc", [0.07, 0.08, 0.09],
                                axis["key"], axis["values"])
    # The middle cell is the model's own figure.
    assert grid["grid"][2][1] == pytest.approx(built["rnpv"])
    for j in range(len(grid["x_values"])):
        column = [row[j] for row in grid["grid"]]
        assert all(v is not None for v in column)
        assert all(b > a for a, b in zip(column, column[1:])), (mode, column)


def test_a_price_on_a_marketed_product_does_not_take_the_axis():
    """Journavx carries a price and is grown from reported revenue. The old axis took
    the price because one was on file, and the grid did not move."""
    inputs = _inputs("marketed")
    inputs["scalars"].update(list_price_per_patient=0.3, gross_to_net_pct=0.25)
    price = forecast.net_price(inputs["scalars"])
    axis = V.grid_axis("marketed", inputs["scalars"], price)
    assert axis["key"] == "revenue_growth_pct" and axis["label"] == "growth"
    priced = forecast.sensitivity(inputs, "wacc", [0.08], "net_price_per_patient",
                                  [price * 0.78, price, price * 1.22])
    assert len({row[0] for row in priced["grid"]}) == 1      # what the old axis drew


# --- through the view, on a database --------------------------------------------

def _db(tmp_path, mode: str, extra=()):
    import db
    import assumptions as A
    path = str(tmp_path / f"{mode}.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'AZN', 'Astra')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed,"
                 " modality) VALUES (1, 1, 'Product', ?, 'small molecule')",
                 (1 if mode in ("marketed", "franchise") else 0,))
    scalars = dict(_inputs(mode)["scalars"], loe_year=2040, **dict(extra))
    rows = [{"key": k, "value": v, "source": "t"} for k, v in scalars.items()
            if k != "therapy_mode"]
    rows.append({"key": "therapy_mode", "text_value": mode, "source": "t"})
    A.save(conn, 1, rows)
    conn.commit()
    conn.close()
    return path


def test_the_view_grades_a_marketed_product_with_a_price_on_growth(tmp_path):
    path = _db(tmp_path, "marketed",
               extra={"list_price_per_patient": 0.3, "gross_to_net_pct": 0.25})
    grid = V.sensitivity(path, "AZN", 1, preset="price")
    assert grid["ok"] and grid["y_key"] == "revenue_growth_pct"
    assert grid["labels"] == {"x": "WACC", "y": "growth"}
    rows = [tuple(row) for row in grid["grid"]]
    assert len(set(rows)) == len(rows)
    assert grid["grid"][2][2] == pytest.approx(V.verdict(path, "AZN", 1)["rnpv"])


@pytest.mark.parametrize("mode,key,label", [
    ("franchise", "franchise_growth_pct", "pool growth"),
    ("launch", "peak_revenue_musd", "peak, mm")])
def test_the_view_grades_franchise_and_launch_on_what_they_read(tmp_path, mode, key,
                                                                 label):
    path = _db(tmp_path, mode)
    grid = V.sensitivity(path, "AZN", 1, preset="price")
    assert grid["ok"] and grid["y_key"] == key and grid["labels"]["y"] == label
    centre = [row[2] for row in grid["grid"]]
    assert all(b > a for a, b in zip(centre, centre[1:]))


def test_the_growth_slider_moves_a_franchise_through_its_pool(tmp_path):
    path = _db(tmp_path, "franchise")
    faster = V.whatif(path, "AZN", 1, growth=0.10)
    assert faster["varied"]["rnpv"] > faster["base"]["rnpv"]
    assert faster["growth_key"] == "franchise_growth_pct"
    assert faster["ignored"] == {}
    still = V.whatif(path, "AZN", 1, volume=0.5)
    assert still["varied"]["rnpv"] == pytest.approx(still["base"]["rnpv"])
    assert "volume" in still["ignored"]


def test_volume_scales_a_launch_peak_and_growth_says_it_has_no_rate(tmp_path):
    path = _db(tmp_path, "launch")
    half = V.whatif(path, "AZN", 1, volume=0.5)
    assert half["varied"]["revenue_pre_loe"] == pytest.approx(
        [v * 0.5 for v in half["base"]["revenue_pre_loe"]])
    assert half["varied"]["rnpv"] < half["base"]["rnpv"]
    flat = V.whatif(path, "AZN", 1, growth=0.10)
    assert flat["varied"]["rnpv"] == pytest.approx(flat["base"]["rnpv"])
    assert "published peak" in flat["ignored"]["growth"]
    assert flat["growth_key"] is None


def test_the_growth_slider_still_moves_a_marketed_product(tmp_path):
    path = _db(tmp_path, "marketed")
    faster = V.whatif(path, "AZN", 1, growth=0.20)
    assert faster["growth_key"] == "revenue_growth_pct"
    assert faster["varied"]["revenue"][0] == pytest.approx(1000.0 * 1.2)


# --- the book ------------------------------------------------------------------

def _nil_whatever_the_axis(built: dict, inputs: dict) -> bool:
    """Worth nothing at any value of the axis: a programme whose probability is nil, or a
    marketed line held at no revenue (Vertex's CF products reported as one line)."""
    scalars = inputs["scalars"]
    return (not built["pos"]) or (built["mode"] == "marketed"
                                  and not scalars.get("base_revenue"))


def _at_its_ceiling_from_year_one(built: dict, inputs: dict, axis: dict) -> bool:
    """A marketed product whose stated ceiling binds in the first forecast year at every
    step of the growth axis: growth cannot move it, its ceiling does (Jemperli)."""
    scalars = inputs["scalars"]
    ceiling = scalars.get("revenue_ceiling_musd")
    if built["mode"] != "marketed" or ceiling is None:
        return False
    run_rate, _ = forecast.latest_run_rate(inputs.get("actuals"))
    if run_rate is not None and run_rate > ceiling:
        ceiling = run_rate
    return scalars["base_revenue"] * (1.0 + min(axis["values"])) >= ceiling


def test_every_modelled_assets_grid_moves_on_its_second_axis(book):
    """Every product the book models is moved by its grid's second axis, read down the
    centre column, except the ones nothing can move. Those are named, not hidden."""
    import assumptions as A
    import db
    path = str(db.DB_PATH)
    assets = book.execute(
        """SELECT DISTINCT a.asset_id, COALESCE(s.brand_name, s.generic_name) AS name,
                  c.ticker
             FROM assumptions a JOIN assets s ON s.id = a.asset_id
             JOIN companies c ON c.id = s.owner_company_id
            WHERE a.key = 'therapy_mode' ORDER BY c.ticker, name""").fetchall()
    failures, exempt, checked = [], [], 0
    for row in assets:
        inputs = A.load(book, row["asset_id"], "base")
        try:
            built = forecast.build(inputs)
        except forecast.ForecastError:
            continue                    # refused by the engine, so no grid to draw
        axis = V.grid_axis(built["mode"], inputs["scalars"],
                           forecast.net_price(inputs["scalars"]))
        label = f"{row['ticker']} {row['name']} ({built['mode']})"
        if axis["values"] is None:
            failures.append(f"{label}: {axis['reason']}")
            continue
        if _nil_whatever_the_axis(built, inputs):
            exempt.append(f"{label}: nil value")
            continue
        if _at_its_ceiling_from_year_one(built, inputs, axis):
            exempt.append(f"{label}: at its ceiling")
            continue
        column = [r[0] for r in forecast.sensitivity(
            inputs, "wacc", [built["wacc"]], axis["key"], axis["values"])["grid"]]
        checked += 1
        values = [v for v in column if v is not None]
        if len(values) < 2 or max(values) - min(values) < 1e-6:
            failures.append(f"{label}: flat on {axis['key']} at {values[:1]}")
        elif any(b < a - 1e-9 for a, b in zip(values, values[1:])):
            failures.append(f"{label}: falls as {axis['key']} rises")
    assert checked, f"no modelled asset on {path}"
    assert not failures, "\n".join(failures)
