"""An acquisition agreed and not completed, stated wherever the asset is valued.

Vertex's valuation holds Palsonify, and Vertex had not completed its acquisition of
Crinetics: an 8-K Item 1.01 is a deal agreed, an Item 2.01 a deal done, and only the
first had been filed. Keeping the product in the acquirer's book was a deliberate
choice, so the notes say so rather than letting it pass as owned.
"""

import forecast_note
import pending_acquisitions as P

_HEADER = "acquirer,asset,target,announced,terms,basis\n"
_ROW = ("VRTX,Palsonify,Crinetics Pharmaceuticals,2026-07-06,"
        "\"$85.00 a share in cash\",an Item 1.01 and no Item 2.01\n")


def _file(tmp_path):
    f = tmp_path / "pending.csv"
    f.write_text(_HEADER + _ROW)
    return f


def test_the_deal_is_found_by_acquirer_and_by_asset(tmp_path):
    f = _file(tmp_path)
    assert [r["asset"] for r in P.for_company("vrtx", f)] == ["Palsonify"]
    assert P.for_asset("VRTX", "palsonify", f)["target"] == "Crinetics Pharmaceuticals"
    assert P.for_asset("VRTX", "Trikafta", f) is None
    assert P.for_company("NVS", f) == []


def test_the_sentence_says_the_price_is_missing_not_only_that_the_deal_is_pending(tmp_path):
    """The point of the flag. Pending is not the risk; the valuation counting an asset
    the company has not bought, without the price it agreed to pay, is."""
    said = P.sentence(P.for_asset("VRTX", "Palsonify", _file(tmp_path)), "Vertex")
    assert "has not completed its acquisition of Crinetics Pharmaceuticals" in said
    assert "does not yet own" in said
    assert "leaves out the price it has agreed to pay" in said


def test_the_note_states_the_deal_first_on_both_pages():
    """It decides whether the asset is the company's at all, so it comes before anything
    the model says about value, and it is shown even before the asset has a model."""
    line = "Palsonify is held in Vertex's book, but ..."
    no_model = forecast_note.write({"ok": False, "name": "Palsonify",
                                    "missing": ["base_revenue"],
                                    "pending_acquisitions": [line]})
    assert no_model["body"][0] == line
    company = forecast_note.write_company({"ok": False, "pending_acquisitions": [line]})
    assert company["body"] == [line]


def test_a_company_reads_by_its_name_in_a_sentence():
    assert P.short_name("Vertex Pharmaceuticals Inc") == "Vertex"
    assert P.short_name("Eli Lilly and Company") == "Eli Lilly"
    assert P.short_name("Novartis AG") == "Novartis"


def test_the_shipped_register_cites_the_filing_that_proves_the_deal_is_open():
    entries = P.rows()
    assert entries, "the register is empty"
    for e in entries:
        assert "1.01" in e["basis"] and "Item 2.01" in e["basis"], e["asset"]
        assert e["terms"] and e["announced"], e["asset"]
