"""The block on the Catalysts tab: what has landed, and what was reported and is held."""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "frontend"))


def test_the_block_says_landed_and_reported_as_two_things_and_never_may_have():
    import catalysts_page as P
    landed = P.landed_html({"asset": "Sacituzumab Tirumotecan", "study": "TroFuse-015",
                            "nct_id": "NCT06356311", "outcome": "met", "event_date": "2026-11-20",
                            "sentence": "TroFuse-015 Trial Met Primary Endpoint",
                            "url": "https://www.merck.com/news/x/", "automated": True,
                            "tied_by": "study name", "effect": "the gate's odds moved from 46% to 91%"})
    assert "TroFuse-015 (NCT06356311) met its primary endpoint" in landed
    assert 'href="https://www.merck.com/news/x/"' in landed and "merck.com ›" in landed
    assert "tied to the study by its study name" in landed and "46% to 91%" in landed
    held = P.reported_html({"asset": "VK2735", "state": "not_tied", "published_at": "2026-09-22",
                            "sentence": "Positive Topline Results from Maintenance Study",
                            "url": "https://ir.vikingtherapeutics.com/r",
                            "reason": "it names VK2735 and no study the book holds"})
    assert "tied to no study" in held and "Not recorded because it names VK2735" in held
    for text in (landed, held, pathlib.Path(P.__file__).read_text()):
        assert "may have landed" not in text and "—" not in text
