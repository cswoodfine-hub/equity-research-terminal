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


def test_spine_marks_the_scale_breaks_and_today():
    svg = _spine()
    assert "90d, month scale" in svg
    assert "24m, year scale" in svg
    assert "today 2026-07-25" in svg


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


def test_spine_places_a_month_only_date_without_inventing_a_day():
    """Registry dates often carry no day. The tick lands at the month and the
    label stays month-precision rather than growing a fabricated day."""
    svg = charts.timeline_spine(
        [{"key": "m", "date": "2026-08", "label": "readout",
          "colour": tokens.UP}],
        dt.date(2026, 7, 25))
    assert "2026-08" in svg                            # the honest label
    assert "08-01" not in svg                          # no invented day


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
