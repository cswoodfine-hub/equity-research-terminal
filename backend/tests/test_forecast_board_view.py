"""The Forecast tab's figures: every choice of every chart draws, the bands add up to the
company, a value not on file is a gap and never a nil, and every block that left the
page is still one click away."""

import itertools
import pathlib
import re
import sys

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
if str(FRONTEND) not in sys.path:
    sys.path.insert(0, str(FRONTEND))

import forecast_board_view as F  # noqa: E402

YEARS_R, YEARS_F = [2024, 2025], [2026, 2027, 2028]


def _series(revenue):
    return {"revenue": revenue, "operating_profit": [v * 0.5 for v in revenue],
            "free_cash_flow": [v * 0.4 for v in revenue],
            "cost_of_goods": [v * 0.2 for v in revenue], "sga": [v * 0.2 for v in revenue],
            "rd": [v * 0.1 for v in revenue], "other_costs": [0.0 for _ in revenue],
            "tax": [v * 0.1 for v in revenue]}


def _asset(i, name, kind, per_share, revenue, pos=1.0, counted=True, loe=None):
    return {"asset_id": i, "name": name, "kind": kind, "counted": counted, "pos": pos,
            "modelled_to": 2027,
            "per_share": per_share, "per_share_success": per_share / pos if pos else None,
            "share_of_value": 0.3, "peak_revenue": max(revenue), "peak_year": 2028,
            "loe_year": loe, "area": "Oncology" if i % 2 else None,
            "next_date": "2027-03-01" if kind == "pipeline" else None, "next_label": "Phase 3",
            "placeholder": not counted,
            "evidence": {"evidence": 6, "partial evidence": 2, "assumption": 2},
            "assumption_share": 0.2, "years": YEARS_F, "series": _series(revenue),
            "reported": {2025: revenue[0] * 0.9} if kind == "marketed" else {}}


def _case(assets, weighted, capex=True):
    def group(kind):
        out = {m: {} for m in _series([0.0])}
        for a in assets:
            if a["kind"] != kind or not a["counted"]:
                continue
            odds = a["pos"] if weighted else 1.0
            for m, vals in a["series"].items():
                for y, v in zip(a["years"], vals):
                    out[m][y] = out[m].get(y, 0.0) + v * odds
        return out
    groups = {"marketed": group("marketed"), "pipeline": group("pipeline"),
              "lines": {m: {y: 10.0 for y in YEARS_F} for m in _series([0.0])},
              "assumed": {m: {y: 5.0 for y in YEARS_F} for m in _series([0.0])}}
    company = {m: {y: sum(groups[g][m].get(y, 0.0) for g in groups) for y in YEARS_F}
               for m in _series([0.0])}
    company["growth_investment"] = {2026: 4.0, 2027: 2.0, 2028: 0.0}
    company["free_cash_flow"] = {y: company["free_cash_flow"][y]
                                 - company["growth_investment"][y] for y in YEARS_F}
    company["capex"] = ({y: 0.03 * company["revenue"][y] + 1.0 for y in YEARS_F}
                        if capex else None)
    return {"company": company, "groups": groups}


def _board(capex=True):
    assets = [_asset(1, "Onsale", "marketed", 6.0, [100.0, 110.0, 90.0], loe=2027),
              _asset(2, "Second", "marketed", 3.0, [50.0, 50.0, 50.0], loe=2040),
              _asset(3, "Pipe", "pipeline", 2.0, [0.0, 40.0, 80.0], pos=0.5),
              _asset(4, "Placeholder", "pipeline", 1.0, [0.0, 500.0, 900.0], pos=0.5,
                     counted=False)]
    return {"ok": True, "ticker": "TEST", "name": "Test Co", "currency": "USD",
            "strip": {"value": 12.0, "price": 10.0, "gap": 0.2, "twelve_month": 13.0,
                      "coverage": 0.9, "rests_on_assumption": 0.2, "close_date": "2026-11-16",
                      "next_catalyst": {"expected_date": "2027-03-01", "title": "Readout"}},
            "years": {"reported": YEARS_R, "forecast": YEARS_F, "carried_from": 2028},
            "reported": {"revenue": {2024: 140.0, 2025: 150.0}, "capex": {2024: 6.0, 2025: 7.0},
                         "operating_profit": {2024: 60.0, 2025: 70.0},
                         "free_cash_flow": {2024: 50.0, 2025: 55.0},
                         "cost_of_goods": {2024: 30.0, 2025: 31.0}, "sga": {2025: 30.0},
                         "rd": {2024: 15.0, 2025: 16.0}, "tax": {2025: 9.0},
                         "operating_cash_flow": {2024: 56.0, 2025: 62.0},
                         "dividends": {2024: 20.0, 2025: 22.0},
                         "buybacks": {2024: 10.0, 2025: 0.0},
                         "acquisitions": {2024: 0.0, 2025: 40.0},
                         "financing": {2024: -35.0, 2025: 3.0}},
            "weighted": _case(assets, True, capex), "success": _case(assets, False, capex),
            "assets": assets,
            "lines": [{"name": "Other", "per_share": 1.0, "years": YEARS_F,
                       "series": _series([10.0, 10.0, 10.0])}],
            "assumed": {"name": "Launches the model assumes", "per_share": 2.0},
            "value": {"equity_per_share": 12.0, "source": [
                {"label": "Products on sale", "per_share": 9.0},
                {"label": "Named pipeline", "per_share": 2.0},
                {"label": "Other revenue lines", "per_share": 1.0},
                {"label": "Launches the model assumes", "per_share": 2.0},
                {"label": "Plant for growth", "per_share": -1.0},
                {"label": "Net cash or debt", "per_share": -1.0}]},
            "capex_rule": ({"upkeep_rate": 0.03, "growth_rate": 0.3, "reason": None,
                            "basis": "plant upkeep at 3.0% of revenue"} if capex
                           else {"upkeep_rate": None, "growth_rate": None,
                                 "reason": "no depreciation line on file"}),
            "basis": {"free_cash_flow": "reported is operating cash flow less capex",
                      "cash_uses": "reported years are the cash flow statement's own lines"},
            "not_valued": ["Legacy"]}


def test_every_choice_of_the_company_chart_draws():
    board = _board()
    for measure, split, view, basis in itertools.product(F.MEASURES, F.SPLITS, F.VIEWS,
                                                         F.BASES):
        svg, caption = F.company_chart(board, measure, split, view, basis)
        assert svg.startswith("<svg") and svg.endswith("</svg>"), (measure, split, view)
        assert caption.startswith("USD "), caption


@pytest.mark.parametrize("measure", ["revenue", "operating_profit", "free_cash_flow", "rd"])
@pytest.mark.parametrize("split", ["group", "product", "none"])
@pytest.mark.parametrize("basis", ["weighted", "success"])
def test_the_bands_add_up_to_the_company(measure, split, basis):
    """However the forecast is split, a year's bands net to the company's figure: the
    plant its growth takes is a band of its own under the cash it comes off."""
    board = _board()
    fig = F.company_figure(board, measure, split, "year", basis)
    company = board[basis]["company"][measure]
    for i, label in enumerate(fig["labels"]):
        year = int(label)
        if year not in YEARS_F:
            continue
        total = sum(b["values"][i] or 0.0 for b in fig["bands"])
        assert total == pytest.approx(company[year]), (label, split)


def test_reported_years_stand_apart_and_cumulative_leaves_them_off():
    board = _board()
    fig = F.company_figure(board, "revenue", "group", "year", "weighted")
    assert fig["labels"][:2] == ["2024", "2025"] and fig["split_at"] == 2
    reported = next(b for b in fig["bands"] if b["name"] == "Reported")
    assert reported["values"] == [140.0, 150.0, None, None, None]
    cum = F.company_figure(board, "revenue", "none", "cum", "weighted")
    assert cum["labels"] == ["2026", "2027", "2028"] and cum["split_at"] is None
    forecast = next(b for b in cum["bands"] if b["name"] == "Forecast")
    yearly = board["weighted"]["company"]["revenue"]
    assert forecast["values"][-1] == pytest.approx(sum(yearly.values()))


def test_reported_free_cash_flow_is_its_two_filed_lines_so_the_plant_is_seen():
    fig = F.company_figure(_board(), "free_cash_flow", "group", "year", "weighted")
    made = next(b for b in fig["bands"] if b["name"] == "Operating cash flow")
    spent = next(b for b in fig["bands"] if b["name"] == "Capex")
    assert made["values"][:2] == [56.0, 62.0] and spent["values"][:2] == [-6.0, -7.0]
    assert made["values"][2:] == [None, None, None]
    # and the forecast's growth charge is its plant and its working capital apart
    i = fig["labels"].index("2026")
    new = next(b for b in fig["bands"] if b["name"] == F.NEW_PLANT)["values"][i]
    working = next(b for b in fig["bands"] if b["name"] == F.WORKING)["values"][i]
    assert new == pytest.approx(-1.0) and new + working == pytest.approx(-4.0)


def test_where_cash_went_is_the_filed_outlays_then_what_the_model_charges():
    """Reported years: the cash flow statement's own lines, with what financing took or
    gave beyond dividends and buybacks. Forecast years: plant and working capital, and
    what is left over, which the model does not allot. A line not on file is named."""
    board = _board()
    fig = F.company_figure(board, "cash_uses", "group", "year", "weighted")
    by = {b["name"]: b["values"] for b in fig["bands"]}
    assert by["Capex"][:2] == [6.0, 7.0] and by["Dividends"][:2] == [20.0, 22.0]
    assert by["Acquisitions"][1] == 40.0 and by["Share buybacks"][0] == 10.0
    # 2024: financing took 35, of which 30 was dividends and buybacks. 2025: it gave 3
    # and 22 went out in dividends, so 25 was raised.
    assert by["Debt and other financing, net"][:2] == [pytest.approx(5.0),
                                                       pytest.approx(-25.0)]
    assert by["Intangibles bought"] == [None] * 5
    assert "not on file: intangibles bought" in fig["caption"]
    i = fig["labels"].index("2026")
    company = board["weighted"]["company"]
    left = by["Left over, use not forecast"][i]
    assert left == pytest.approx(company["free_cash_flow"][2026])
    uses = sum(by[n][i] or 0.0 for n in ("Plant upkeep", F.NEW_PLANT, F.WORKING))
    assert uses == pytest.approx(0.03 * company["revenue"][2026] + 4.0)
    line = fig["reference"]
    assert line["name"] == "Cash from operations" and line["values"][:2] == [56.0, 62.0]
    assert line["values"][i] == pytest.approx(left + uses)
    svg, _ = F.company_chart(board, "cash_uses")
    assert "Cash from operations" in svg and svg.startswith("<svg")


def test_the_year_a_product_is_carried_on_its_terminal_path_is_ruled_and_said():
    board = _board()
    fig = F.company_figure(board, "revenue", "group", "year", "weighted")
    assert fig["rule_at"] == (fig["labels"].index("2028"), "terminal path")
    assert "terminal value" in fig["caption"]
    svg, caption = F.asset_lines(board, "revenue")
    assert 'class="carried"' in svg and "dashed past the modelled years" in caption
    board["years"]["carried_from"] = None
    assert F.company_figure(board, "revenue")["rule_at"] is None


def test_capex_with_no_rule_is_a_gap_with_its_reason_and_never_nil():
    board = _board(capex=False)
    fig = F.company_figure(board, "capex", "group", "year", "weighted")
    assert [b["name"] for b in fig["bands"]] == ["Reported"]
    assert fig["bands"][0]["values"][2:] == [None, None, None]
    assert "no forecast: no depreciation line on file" in fig["caption"]
    svg, _ = F.company_chart(board, "capex")
    assert ">2026 " not in svg                      # no forecast column was drawn


def test_forecast_capex_is_upkeep_and_new_plant_and_states_its_rule():
    board = _board()
    fig = F.company_figure(board, "capex", "group", "year", "weighted")
    names = [b["name"] for b in fig["bands"]]
    assert names == ["Reported", "Plant upkeep", "New plant for added revenue"]
    i = fig["labels"].index("2027")
    upkeep, new = fig["bands"][1]["values"][i], fig["bands"][2]["values"][i]
    revenue = board["weighted"]["company"]["revenue"][2027]
    assert upkeep == pytest.approx(0.03 * revenue)
    assert upkeep + new == pytest.approx(board["weighted"]["company"]["capex"][2027])
    assert "plant upkeep at 3.0% of revenue" in fig["caption"]


def test_a_name_under_a_year_is_a_product_losing_exclusivity_in_the_forecast():
    fig = F.company_figure(_board(), "revenue", "group", "year", "weighted")
    i = fig["labels"].index("2027")
    assert fig["notes"][i] == "Onsale"
    assert "loses exclusivity" in fig["caption"]


def test_the_value_split_is_a_bridge_that_ends_on_the_value():
    rows = F.value_rows(_board(), "source")
    assert rows[-1]["label"] == "Value a share" and rows[-1]["value"] == 12.0
    assert sum(r["value"] for r in rows[:-1]) == pytest.approx(12.0)
    assert rows[1]["start"] == pytest.approx(rows[0]["value"])
    for view in F.VALUE_VIEWS:
        svg, caption = F.value_chart(_board(), view)
        assert svg.startswith("<svg") and caption


def test_the_value_by_evidence_splits_each_asset_by_the_grade_of_its_inputs():
    rows = {r["label"]: r["value"] for r in F.value_rows(_board(), "evidence")}
    named = 6.0 + 3.0 + 2.0                        # the placeholder is not counted
    assert rows["Filed or measured"] == pytest.approx(named * 0.6)
    assert rows["Judgement or convention"] == pytest.approx(named * 0.2)
    assert "Launches the model assumes" in rows


def test_what_it_depends_on_is_nearest_first_and_says_each_lever_once():
    breaks = {"name": "Test Co", "direction": "down", "levers": [
        {"name": "Test Co", "lever": "every discount rate", "kind": "rate", "model": 0.08,
         "break": 0.10, "reachable": True, "evidence_class": "evidence"},
        {"name": "Onsale", "lever": "growth fade", "kind": "years", "model": 5, "break": 4,
         "reachable": True, "evidence_class": "partial evidence"},
        {"name": "Test Co", "lever": "uncapped growth fade", "kind": "years", "model": 5,
         "break": 4, "reachable": True, "evidence_class": "partial evidence"},
        {"name": "Onsale", "lever": "exclusivity", "kind": "year", "model": 2030,
         "break": 2028, "reachable": True, "evidence_class": "evidence"},
        {"name": "Pipe", "lever": "peak share", "kind": "rate", "model": 0.1, "break": None,
         "reachable": False}]}
    rows = F.depends_rows(breaks, 2026)
    assert [r["label"] for r in rows] == ["Onsale: growth fade", "Every discount rate",
                                          "Onsale: exclusivity"]
    assert rows[0]["room"] == pytest.approx(0.2)
    assert rows[2]["room"] == pytest.approx(2 / 4)          # of the years still ahead
    svg, caption = F.depends_chart(breaks, 2026, lambda lever: "model to break")
    assert "fall before the value meets the price" in caption and svg.startswith("<svg")
    assert F.depends_chart({}, 2026, str) == ("", "")


def test_every_asset_measure_ranks_and_a_missing_figure_says_none():
    board = _board()
    for measure, show, basis in itertools.product(F.ASSET_MEASURES, F.ASSET_SHOWS, F.BASES):
        rows = F.asset_rows(board, measure, show, basis, 2027, 2026)
        assert rows and all("html" in r for r in rows)
    rows = F.asset_rows(board, "chance", "all", "weighted", None, 2026)
    onsale = next(r for r in rows if r["id"] == 1)
    assert 'class="ab-v none">none<' in onsale["html"] and "width:0%" in onsale["html"]
    ids = [r["id"] for r in F.asset_rows(board, "value", "all", "weighted", None, 2026)
           if r["id"] is not None]
    assert ids == [1, 2, 3, 4]                      # on sale first, each ranked by value
    placeholder = next(r for r in rows if r["id"] == 4)
    assert "ab pipe off" in placeholder["html"] and "placeholder" in placeholder["html"]


def test_weighting_an_asset_takes_its_chance_off_its_revenue_and_not_off_a_product_on_sale():
    board = _board()
    pipe, onsale = board["assets"][2], board["assets"][0]
    assert F.asset_value(pipe, "revenue_year", "weighted", 2028) == pytest.approx(40.0)
    assert F.asset_value(pipe, "revenue_year", "success", 2028) == pytest.approx(80.0)
    assert F.asset_value(onsale, "revenue_year", "weighted", 2026) == 100.0
    assert F.asset_value(onsale, "exclusivity", "weighted", None, 2026) == 1
    assert F.asset_value(board["assets"][1], "revenue_year", "weighted", 2031) is None


def test_the_pair_and_the_lines_draw_and_the_table_lists_every_asset():
    board = _board()
    for x, y in itertools.permutations(F.ASSET_MEASURES, 2):
        F.asset_pair_chart(board, x, y, "all", "weighted", 2027, 2026)
    assert F.asset_pair_chart(board, "peak", "value").startswith("<svg")
    for measure, show in itertools.product(F.TIME_MEASURES, F.ASSET_SHOWS):
        svg, caption = F.asset_lines(board, measure, show)
        assert svg.startswith("<svg") and caption
    svg, caption = F.asset_lines(board, "revenue")
    assert 'class="reported"' in svg and "rings are reported years" in caption
    assert "Placeholder" not in svg                  # not counted, so not drawn
    table = F.asset_table(board, 2026)
    assert all(a["name"] in table for a in board["assets"])


def test_the_strip_is_seven_figures_and_a_missing_one_is_none():
    board = _board()
    items = F.strip_items(board, "Buy")
    assert [i[0] for i in items] == ["value a share", "price", "value over price",
                                     "in 12 months", "revenue covered",
                                     "rests on judgement", "next catalyst"]
    assert items[2][1] == "+20%" and items[2][3] == "Buy"
    board["strip"]["twelve_month"] = None
    assert F.strip_items(board)[3][1] is None


def test_the_asset_view_opens_on_five_figures_about_the_assets():
    items = F.asset_strip_items(_board())
    by = {i[0]: i for i in items}
    assert list(by) == ["assets valued", "on sale", "pipeline", "largest", "next gate"]
    assert by["assets valued"][1] == "3" and "1 more on a placeholder" in by["assets valued"][5]
    assert by["on sale"][1] == "$9.00" and by["pipeline"][1] == "$2.00"
    assert by["largest"][1] == "Onsale"
    assert by["next gate"][1] == "2027-03-01" and "Pipe" in by["next gate"][5]
    empty = F.asset_strip_items({"assets": []})
    assert empty[1][1] is None and empty[3][1] is None        # no free data, not nil


def test_axis_ticks_cover_the_tallest_column():
    for lo, hi in ((0.0, 53.4), (-2.7, 18.3), (0.0, 0.9), (-10.0, 0.0), (0.0, 2666.0)):
        ticks = F._ticks(lo, hi)
        assert ticks[0] <= lo and ticks[-1] >= hi and 0.0 in ticks, (lo, hi, ticks)


BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament")


def test_house_style_on_every_word_the_page_prints():
    board = _board()
    text = " ".join(
        [c for m, s, v, b in itertools.product(F.MEASURES, F.SPLITS, F.VIEWS, F.BASES)
         for c in F.company_chart(board, m, s, v, b)]
        + [c for v in F.VALUE_VIEWS for c in F.value_chart(board, v)]
        + [r["html"] for r in F.asset_rows(board)]
        + [F.asset_table(board, 2026)] + list(F.asset_lines(board))
        + [str(x) for d in (F.MEASURES, F.SPLITS, F.VIEWS, F.BASES, F.VALUE_VIEWS,
                            F.ASSET_MEASURES, F.ASSET_SHOWS, F.ASSET_VIEWS, F.TIME_MEASURES)
           for x in d.values()])
    visible = re.sub(r"<[^>]+>", " ", text)
    assert "—" not in visible
    for word in BANNED:
        assert word not in visible.lower(), word


def test_every_block_that_left_the_page_is_one_click_away():
    """The redesign moved the company's deeper blocks behind buttons and the workbench
    into the asset's card. None was dropped: each is still called from a card."""
    source = (FRONTEND / "streamlit_app.py").read_text()
    more = source[source.index("def _fc_more("):source.index("def _fc_page(")]
    for block in ("_sotp_bridge(", "_revenue_split(", "_revenue_build(",
                  "_fair_value_range(", "_what_breaks_it(", "_pipeline_development(",
                  "_peer_value_section(", "_ira_strip("):
        assert block in more, block
    card = source[source.index("def _fc_card("):source.index("def _fc_more(")]
    assert "_asset_bench(" in card
    bench = source[source.index("def _asset_bench("):]
    for layer in ("_drivers_layer(", "_next_gate_layer(", "_render_patient_chart(",
                  "_cash_profile_section(", "_pnl_section(", "_sensitivity_grid(",
                  "_forecast_editor(", "_change_log(", "_lever_controls(",
                  "_revenue_path(", "_value_bridge("):
        assert layer in bench, layer
