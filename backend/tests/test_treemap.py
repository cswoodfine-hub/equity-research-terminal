"""The treemap: area, colour, and the labels that only appear where they fit."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "frontend"))

import treemap  # noqa: E402


def _rows(*sizes):
    return [{"ticker": f"T{i}", "name": f"Co {i}", "size": s, "change": 0.1}
            for i, s in enumerate(sizes)]


def test_every_company_gets_a_box():
    svg = treemap.build(_rows(10, 5, 3, 2))
    assert svg.count("<rect") == 4


def test_the_boxes_fill_the_canvas():
    """Area is the encoding, so the areas have to add up to the space they are drawn in."""
    boxes = treemap._squarify([10, 5, 3, 2], 0, 0, 400, 300)
    drawn = sum(w * h for _x, _y, w, h in boxes)
    assert abs(drawn - 400 * 300) < 1.0


def test_area_is_proportional_to_size():
    boxes = treemap._squarify([10, 5], 0, 0, 400, 300)
    first, second = (w * h for _x, _y, w, h in boxes)
    assert abs(first / second - 2.0) < 0.01


def test_the_boxes_stay_inside_the_canvas():
    for x, y, w, h in treemap._squarify([9, 7, 5, 4, 3, 2, 1], 0, 0, 400, 300):
        assert x >= -0.01 and y >= -0.01
        assert x + w <= 400.01 and y + h <= 300.01


def test_a_rise_and_a_fall_are_different_colours():
    up = treemap._colour(0.2)
    down = treemap._colour(-0.2)
    assert up != down


def test_an_unknown_move_takes_no_colour():
    """An unknown move is not a flat one."""
    from components import tokens as TK
    assert treemap._colour(None) == TK.PANEL


def test_a_move_past_the_clip_does_not_keep_intensifying():
    """One company up 700% otherwise makes every other box the same shade."""
    assert treemap._colour(0.6) == treemap._colour(7.0)


def test_a_box_too_small_for_its_ticker_has_none():
    """A ticker clipped by its own box is worse than a box a reader hovers."""
    svg = treemap.build([{"ticker": "BIG", "name": "Big", "size": 10000, "change": 0.1},
                         {"ticker": "TINY", "name": "Tiny", "size": 1, "change": 0.1}])
    assert ">BIG<" in svg
    assert ">TINY<" not in svg


def test_every_box_carries_its_company_for_a_hover():
    svg = treemap.build([{"ticker": "AAA", "name": "Alpha", "size": 5, "change": -0.12}])
    assert "<title>AAA: Alpha · -12%</title>" in svg


def test_nothing_to_draw_is_nothing():
    assert treemap.build([]) == ""
    assert treemap.build([{"ticker": "A", "name": "A", "size": 0, "change": 0}]) == ""
