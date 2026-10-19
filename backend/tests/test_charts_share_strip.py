"""The share strip: one full-width bar split by count, used for the Part D tier mix."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "frontend"))

from components import charts  # noqa: E402

NS = "{http://www.w3.org/2000/svg}"
# Eliquis, Part D release 2026-09-16: its lowest tier on each of 328 formularies.
ELIQUIS = [{"label": "1", "value": 61, "colour": "#111111"},
           {"label": "2", "value": 10, "colour": "#222222"},
           {"label": "3", "value": 257, "colour": "#333333"}]


def _segs(svg):
    return [r for r in ET.fromstring(svg).iter(f"{NS}rect") if r.get("class") == "seg"]


def test_segments_fill_the_width_in_proportion():
    svg = charts.share_strip(ELIQUIS, width=328, height=20)
    widths = [float(r.get("width")) for r in _segs(svg)]
    assert widths == [61.0, 10.0, 257.0]
    titles = [r.find(f"{NS}title").text for r in _segs(svg)]
    assert titles == ["1: 61", "2: 10", "3: 257"]


def test_a_label_prints_only_where_it_fits():
    svg = charts.share_strip([{"label": "tier 3", "value": 99, "colour": "#333"},
                              {"label": "tier 5", "value": 1, "colour": "#555"}],
                             width=300)
    printed = [t.text for t in ET.fromstring(svg).iter(f"{NS}text")]
    assert printed == ["tier 3"]


def test_nothing_to_draw_is_an_empty_string_and_a_null_is_left_out():
    assert charts.share_strip([]) == ""
    assert charts.share_strip([{"label": "1", "value": None, "colour": "#111"}]) == ""
    svg = charts.share_strip([{"label": "1", "value": None, "colour": "#111"},
                              {"label": "2", "value": 4, "colour": "#222"}], width=100)
    assert [float(r.get("width")) for r in _segs(svg)] == [100.0]
