"""The chart primitives: valid SVG, correct marks for known input, and the one
absolute rule, a null is never plotted as zero."""

import datetime as dt
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "frontend"))

from components import charts, tokens  # noqa: E402


def _polyline_points(svg: str) -> list[list[tuple]]:
    out = []
    for match in re.findall(r'<polyline points="([^"]+)"', svg):
        out.append([tuple(float(c) for c in pair.split(","))
                    for pair in match.split()])
    return out


def _filled_rects(svg: str, colour: str) -> int:
    return len(re.findall(rf'<rect [^>]*fill="{colour}"', svg))


REPRESENTATIVE = [
    ("sparkline", lambda: charts.sparkline([1.0, 2.0, None, 3.0])),
    ("line_chart", lambda: charts.line_chart(
        [{"name": "a", "values": [1.0, None, 3.0], "colour": tokens.UP},
         {"name": "b", "values": [10.0, 12.0, 9.0], "colour": tokens.TEXT,
          "axis": "right"}], ["Q1", "Q2", "Q3"])),
    ("bar_chart", lambda: charts.bar_chart(
        [{"label": "x", "value": 4.0}, {"label": "y", "value": None}])),
    ("stacked_bar", lambda: charts.stacked_bar(
        [{"label": "r", "segments": [
            {"name": "s", "value": 2.0, "colour": tokens.UP}]}])),
    ("heatmap_grid", lambda: charts.heatmap_grid(
        ["A"], ["m1"], {("A", "m1"): {"count": 2, "weight": 0.5}})),
    ("dumbbell", lambda: charts.dumbbell(
        [{"label": "t", "start": 0.0, "end": 30.0}])),
    ("waterfall", lambda: charts.waterfall(
        [{"label": "s", "value": 10.0, "kind": "start"},
         {"label": "d", "value": -2.0, "kind": "step"},
         {"label": "e", "kind": "end"}])),
    ("small_multiples", lambda: charts.small_multiples(
        [{"label": "LLY", "values": [1.0, 2.0], "sub": "+1%"}])),
    ("timeline_spine", lambda: charts.timeline_spine(
        [{"key": "k", "date": "2026-08-01", "label": "readout", "colour": tokens.UP}],
        dt.date(2026, 7, 25), cliff_years={2031: 2})),
    ("donut", lambda: charts.donut(
        [{"label": "Drug", "value": 5.0, "colour": tokens.UP}])),
]


@pytest.mark.parametrize("name,build", REPRESENTATIVE)
def test_every_primitive_returns_valid_svg(name, build):
    svg = build()
    assert svg.startswith("<svg"), name
    ET.fromstring(svg)  # raises if malformed
    assert 'width="' in svg and 'viewBox="' in svg, f"{name} lacks explicit size"


# --- sparkline ------------------------------------------------------------
def test_sparkline_breaks_at_a_null_rather_than_bridging():
    svg = charts.sparkline([1.0, 2.0, None, 3.0, 4.0], label_last=False)
    lines = _polyline_points(svg)
    assert len(lines) == 2               # the null splits the line in two
    assert sum(len(line) for line in lines) == 4  # and no point is invented


def test_sparkline_labels_the_last_value():
    assert ">4.0<" in charts.sparkline([1.0, 4.0]).replace("4.0", "4.0")
    assert "4.0" in charts.sparkline([1.0, 4.0])


def test_sparkline_with_nothing_renders_nothing():
    assert charts.sparkline([]) == ""
    assert charts.sparkline([None, None]) == ""


def test_sparkline_direction_sets_the_colour():
    assert tokens.DOWN in charts.sparkline([5.0, 1.0])
    assert tokens.UP in charts.sparkline([1.0, 5.0])


# --- line chart -----------------------------------------------------------
def test_line_chart_breaks_series_at_null():
    """The null neither bridges nor swallows its neighbours: the islanded point
    before it still draws, as a dot."""
    svg = charts.line_chart(
        [{"name": "a", "values": [1.0, None, 3.0, 4.0], "colour": tokens.UP}],
        ["a", "b", "c", "d"], hover=False)
    lines = _polyline_points(svg)
    assert sum(len(line) for line in lines) == 2       # only the unbroken pair
    assert svg.count('class="isolated"') == 1          # the lone point survives


def test_line_chart_dual_axis_labels_both_scales_in_their_colours():
    svg = charts.line_chart(
        [{"name": "growth", "values": [0.01, 0.02], "colour": tokens.UP},
         {"name": "margin", "values": [0.30, 0.35], "colour": tokens.TEXT,
          "axis": "right"}],
        ["Q1", "Q2"], hover=False)
    assert svg.count(f'fill="{tokens.UP}"') >= 2      # axis labels + series label
    assert "growth" in svg and "margin" in svg        # direct labels, no legend


def test_line_chart_hover_band_per_x_slot():
    svg = charts.line_chart(
        [{"name": "a", "values": [1.0, 2.0, 3.0], "colour": tokens.UP}],
        ["x", "y", "z"])
    assert svg.count('class="hoverband"') == 3
    assert "no free data" not in svg


# --- bar chart ------------------------------------------------------------
def test_bar_null_is_a_hatched_band_not_a_zero_bar():
    svg = charts.bar_chart([{"label": "a", "value": 3.0},
                            {"label": "b", "value": None}])
    assert svg.count('class="nullband"') == 1
    assert "no free data" in svg
    assert _filled_rects(svg, tokens.UP) == 1         # only the real bar is a bar


def test_bar_chart_negative_takes_the_down_colour():
    svg = charts.bar_chart([{"label": "a", "value": -2.0}], horizontal=True)
    assert _filled_rects(svg, tokens.DOWN) == 1


def test_horizontal_bar_null_band_says_so_in_text():
    svg = charts.bar_chart([{"label": "a", "value": None}], horizontal=True)
    assert "no free data" in svg and 'class="nullband"' in svg


# --- stacked bar ----------------------------------------------------------
def test_stacked_bar_draws_each_segment_and_the_total():
    svg = charts.stacked_bar([{"label": "r", "segments": [
        {"name": "one", "value": 2.0, "colour": tokens.UP},
        {"name": "two", "value": 3.0, "colour": tokens.FLAG}]}])
    assert _filled_rects(svg, tokens.UP) == 1
    assert _filled_rects(svg, tokens.FLAG) == 1
    assert "5.0" in svg                                # the printed total


def test_stacked_bar_empty_row_prints_a_dash_not_a_zero_bar():
    svg = charts.stacked_bar([{"label": "r", "segments": []}])
    assert ">—<" in svg


# --- heatmap --------------------------------------------------------------
def test_heatmap_missing_cell_stays_ground_with_no_figure():
    svg = charts.heatmap_grid(["A", "B"], ["m1"], {
        ("A", "m1"): {"count": 3, "weight": 1.0}})
    assert _filled_rects(svg, tokens.GROUND) == 1     # B/m1 is absence, not zero
    assert ">3<" in svg


def test_heatmap_flagged_cell_carries_the_amber_tick():
    svg = charts.heatmap_grid(["A"], ["m1"], {
        ("A", "m1"): {"count": 1, "weight": 0.5, "flagged": True}})
    assert f'fill="{tokens.FLAG}"' in svg
    assert "uncurated" in svg


# --- dumbbell -------------------------------------------------------------
def test_dumbbell_a_slip_reads_down_and_a_pull_in_reads_up():
    svg = charts.dumbbell([
        {"label": "slipped", "start": 0.0, "end": 45.0},
        {"label": "pulled in", "start": 60.0, "end": 30.0}])
    assert f'stroke="{tokens.DOWN}" stroke-width="2"' in svg
    assert f'stroke="{tokens.UP}" stroke-width="2"' in svg
    assert "+45d" in svg
    assert f"{charts.MINUS}30d" in svg


def test_dumbbell_drops_rows_missing_either_end():
    svg = charts.dumbbell([{"label": "half", "start": None, "end": 3.0},
                           {"label": "whole", "start": 0.0, "end": 3.0}])
    assert "half" not in svg and "whole" in svg


def test_dumbbell_with_nothing_renders_nothing():
    assert charts.dumbbell([]) == ""


# --- waterfall ------------------------------------------------------------
def test_waterfall_null_step_hatches_at_the_running_level():
    svg = charts.waterfall([
        {"label": "start", "value": 10.0, "kind": "start"},
        {"label": "unknown", "value": None, "kind": "step"},
        {"label": "down", "value": -3.0, "kind": "step"},
        {"label": "end", "kind": "end"}])
    assert svg.count('class="nullband"') == 1
    assert "no free data" in svg
    assert "7.0" in svg                                # 10 - 3, null added nothing


def test_waterfall_steps_take_direction_colours():
    svg = charts.waterfall([
        {"label": "s", "value": 5.0, "kind": "start"},
        {"label": "up", "value": 2.0, "kind": "step"},
        {"label": "dn", "value": -1.0, "kind": "step"}])
    assert _filled_rects(svg, tokens.UP) == 1
    assert _filled_rects(svg, tokens.DOWN) == 1


# --- small multiples ------------------------------------------------------
def test_small_multiples_renders_every_panel_and_names_missing_data():
    panels = [{"label": f"T{i}", "values": [1.0, 2.0, 1.5], "sub": ""}
              for i in range(17)]
    panels.append({"label": "ROG", "values": [], "sub": None})
    svg = charts.small_multiples(panels, cols=6)
    for i in range(17):
        assert f">T{i}<" in svg
    assert "no free data" in svg                       # ROG says so, draws nothing


def test_small_multiples_link_base_makes_each_panel_a_link():
    panels = [{"label": "LLY", "values": [1.0, 2.0], "sub": ""},
              {"label": "ROG", "values": [], "sub": None}]   # a no-data panel too
    svg = charts.small_multiples(panels, cols=6, link_base="?ticker=")
    assert '<a href="?ticker=LLY">' in svg
    assert '<a href="?ticker=ROG">' in svg                  # even the empty panel links
    assert svg.count("<a ") == 2 and svg.count("</a>") == 2
    # without link_base there are no anchors
    assert "<a " not in charts.small_multiples(panels, cols=6)


def test_small_multiples_share_one_scale():
    """A flat series must stay flat against the volatile one, which only holds if
    both map through the same domain."""
    svg = charts.small_multiples([
        {"label": "flat", "values": [10.0, 10.0], "sub": ""},
        {"label": "wild", "values": [0.0, 20.0], "sub": ""}], cols=2)
    lines = _polyline_points(svg)
    flat = min(lines, key=lambda ln: abs(ln[0][1] - ln[1][1]))
    assert abs(flat[0][1] - flat[1][1]) < 0.01


# --- timeline spine -------------------------------------------------------
def _spine(**kwargs):
    items = [
        {"key": "near", "date": "2026-08-10", "label": "readout", "colour": tokens.UP},
        {"key": "mid", "date": "2027-03-01", "label": "PDUFA", "colour": tokens.FLAG,
         "flagged": True},
        {"key": "far", "date": "2031-01-01", "label": "loe", "colour": tokens.DOWN},
    ]
    return charts.timeline_spine(items, dt.date(2026, 7, 25),
                                 cliff_years={2031: 3, 2034: 1}, **kwargs)


def test_spine_places_ticks_only_inside_the_two_dated_windows():
    svg = _spine()
    assert "08-10" in svg                              # near, day resolution
    assert "2027-03" in svg                            # mid, month resolution
    assert "2031-01" not in svg                        # beyond 24m has no tick
    assert ">2031<" in svg and ">3<" in svg            # it lands in the cliff bars


def test_spine_groups_by_month_with_a_green_dash_and_marks_today():
    svg = _spine()
    assert "today 2026-07-25" in svg
    assert "Aug 2026" in svg and "Mar 2027" in svg          # a labelled month group each
    assert f'stroke="{tokens.UP}" stroke-width="2"' in svg  # the green month dash


def test_spine_selected_item_draws_the_connecting_hairline():
    plain, selected = _spine(), _spine(selected_key="near")
    assert 'x1="0"' not in plain
    assert 'x1="0"' in selected                        # hairline from the panel edge


def test_spine_flags_uncurated_items_in_amber():
    svg = _spine()
    assert f'fill="{tokens.FLAG}"><title>uncurated' in svg


def test_spine_items_become_anchors_when_a_link_base_is_given():
    """A click on the spine navigates to ?…&sel=key, which is how selection
    round-trips with no script."""
    plain = _spine()
    linked = _spine(link_base="?ticker=LLY&sel=")
    assert "<a href=" not in plain
    assert '<a href="?ticker=LLY&amp;sel=near">' in linked   # the near item's key
    assert linked.count("<a href=") == linked.count("</a>")  # every anchor closed


def test_spine_item_with_a_url_opens_the_study_and_previews_the_full_title():
    """A catalyst carries the study URL and its full title: a hover previews the trial
    and a click opens its page in a new tab, which wins over the pin link base."""
    item = {"key": "c", "date": "2026-08-10", "label": "readout",
            "full": "Phase 3, A big long trial name (2026-08) · NCT01",
            "url": "https://clinicaltrials.gov/study/NCT01", "colour": tokens.UP}
    svg = charts.timeline_spine([item], dt.date(2026, 7, 25), link_base="?sel=")
    assert 'href="https://clinicaltrials.gov/study/NCT01" target="_blank"' in svg
    assert "Phase 3, A big long trial name (2026-08)" in svg   # the hover title
    assert "sel=c" not in svg                                  # the URL wins over the pin


def test_spine_places_a_month_only_date_without_inventing_a_day():
    """Registry dates often carry no day. The tick lands at the month and the
    label stays month-precision rather than growing a fabricated day."""
    svg = charts.timeline_spine(
        [{"key": "m", "date": "2026-08", "label": "readout",
          "colour": tokens.UP}],
        dt.date(2026, 7, 25))
    assert "2026-08" in svg                            # the honest label
    assert "08-01" not in svg                          # no invented day


# --- approvals timeline ---------------------------------------------------
def test_approvals_timeline_dots_each_with_a_hover_and_empty_is_blank():
    svg = charts.approvals_timeline([
        {"ticker": "SNY", "label": "Sarclisa Escena", "date": "2026-07-09",
         "full": "Sarclisa Escena (BLA761445) — 2026-07-09"},
        {"ticker": "GSK", "label": "Utebzi", "date": "2026-06-17",
         "full": "Utebzi (NDA215960) — 2026-06-17"}],
        today=dt.date(2026, 7, 26))
    assert "SNY" in svg and "GSK" in svg
    assert "Sarclisa Escena (BLA761445)" in svg        # the hover carries the full name
    assert svg.count("<circle") == 2                   # one dot per approval
    assert "Jul 26" in svg or "Jun 26" in svg          # a month gridline label
    assert charts.approvals_timeline([]) == ""


def test_small_multiples_draw_a_zero_line_when_the_shared_scale_crosses_it():
    svg = charts.small_multiples([
        {"label": "UP", "values": [0.0, 5.0, 12.0]},
        {"label": "DN", "values": [0.0, -3.0, -6.0]}], width=400, height=120)
    # the shared domain spans -6..12, so each panel gets a zero reference line
    assert svg.count(f'stroke="{tokens.RULE}"') >= 2


# --- scatter and sparkline marks ------------------------------------------
def test_scatter_labels_every_point_and_weights_the_selected_one():
    svg = charts.scatter([
        {"label": "LLY", "x": 44.7, "y": 31.7, "selected": True},
        {"label": "PFE", "x": -0.2, "y": 14.6},
        {"label": "gap", "x": None, "y": 3.0}])          # no honest place
    assert "LLY" in svg and "PFE" in svg and "gap" not in svg
    assert svg.count(f'fill="{tokens.DOWN}"') == 1       # only the selected dot
    assert charts.scatter([]) == ""


def test_sparkline_session_marks_are_dashes_not_data():
    svg = charts.sparkline([1.0, 2.0, 3.0, 4.0], marks=[0, 2], label_last=False)
    assert svg.count('class="mark"') == 2
    assert svg.count("<polyline") == 1                   # marks add no series


# --- donut ----------------------------------------------------------------
def test_donut_every_slice_gets_an_outside_label_on_a_leader():
    svg = charts.donut([
        {"label": "Keytruda", "value": 31.6, "colour": tokens.UP},
        {"label": "Gardasil", "value": 5.2, "colour": tokens.FLAG},
        {"label": "everything else", "value": 20.8, "colour": tokens.PANEL,
         "muted": True}],
        centre_label="65.0", centre_sub="USD bn")
    assert svg.count("<path") == 3
    assert svg.count("<polyline") == 3                 # one leader per slice
    assert "Keytruda" in svg and "everything else" in svg
    assert "65.0" in svg


def test_donut_with_no_total_renders_nothing():
    assert charts.donut([{"label": "x", "value": 0, "colour": tokens.UP}]) == ""


# --- tornado ---------------------------------------------------------------
# dumbbell was the nearest thing and it is built for date slippage: it hardcodes days as
# the unit and colours by direction, so a lever worth $945mm rendered as "945d" in the
# down colour whichever way it moved.

def test_a_tornado_draws_both_sides_of_the_centre():
    svg = charts.tornado([{"label": "net price", "low": -945, "high": 945}],
                         value_fmt=lambda v: f"{v:,.0f}")
    assert svg.startswith("<svg")
    assert "net price" in svg
    # Both ends printed, so the geometry is never the only signal.
    assert "-945" in svg and "945" in svg


def test_the_two_sides_carry_different_colours():
    from components import tokens as TK
    svg = charts.tornado([{"label": "x", "low": -10, "high": 10}])
    assert TK.DOWN in svg and TK.UP in svg


def test_an_asymmetric_lever_looks_asymmetric():
    """A discount rate helps more falling than it hurts rising. That has to show as a
    longer arm, not as two numbers to compare in your head."""
    import re
    svg = charts.tornado([{"label": "wacc", "low": -100, "high": 400}])
    widths = [float(w) for w in re.findall(r'<rect[^>]*width="([\d.]+)"', svg)]
    assert len(widths) == 2 and max(widths) > 2 * min(widths)


def test_rows_without_both_ends_are_dropped():
    assert charts.tornado([]) == ""
    assert charts.tornado([{"label": "x", "low": None, "high": 1}]) == ""


def test_the_centre_can_sit_away_from_zero():
    # The scenario range is centred on the base case, not on nothing.
    svg = charts.tornado([{"label": "per share", "low": 1.42, "high": 8.91}],
                         centre=4.45, value_fmt=lambda v: f"${v:,.2f}")
    assert "$4.45" in svg
