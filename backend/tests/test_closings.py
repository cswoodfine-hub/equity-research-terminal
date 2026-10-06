"""The closing reader and the target's numbers, on saved EDGAR payloads.

Fixtures are real filings: Neurocrine's Item 2.01 8-K for Soleno (0001193125-26-228013),
Rocket's Item 2.01 8-K for the sale of a priority review voucher (0001140361-26-024997),
the projections sections of Soleno's SC 14D-9 (0001193125-26-162853) and Intra-Cellular's
DEFM14A (0001193125-25-028672), two full-text search answers and Soleno's revenue facts.
"""

import json
from pathlib import Path

import closings
import filingtext

FIXTURES = Path(__file__).parent / "fixtures"


def _text(name):
    return filingtext.html_to_text((FIXTURES / name).read_text())


def test_an_item_201_merger_names_the_target_and_the_day():
    found = closings.find_closings(_text("closings_8k_201_nbix_soleno.htm"),
                                   closings.aliases("Neurocrine Biosciences, Inc.", "NBIX"),
                                   item_201=True)
    assert [(a["target"], a["closing_date"]) for a in found["acquisitions"]] == [
        ("Soleno Therapeutics, Inc.", "2026-05-18")]
    assert "The Company completed the acquisition of Soleno on May 18, 2026" in found[
        "acquisitions"][0]["quote"]


def test_an_item_201_sale_is_a_disposition_not_an_acquisition():
    found = closings.find_closings(_text("closings_8k_201_rckt_prv_sale.htm"),
                                   closings.aliases("Rocket Pharmaceuticals, Inc.", "RCKT"),
                                   item_201=True)
    assert found == {"acquisitions": [], "disposition": True}


def test_the_subject_has_to_be_the_filer():
    # Beam's 10-K reports Lilly's closing, in which Beam sold a stake.
    beam = closings.aliases("Beam Therapeutics Inc.", "BEAM")
    assert closings.find_closings(
        "During the year ended December 31, 2025, Lilly completed its acquisition of Verve "
        "and as a result, the Company received total proceeds of $5.", beam)[
        "acquisitions"] == []
    jnj = closings.aliases("Johnson & Johnson", "JNJ")
    found = closings.find_closings(
        "Intra-Cellular On April 2, 2025, the Company completed the acquisition of "
        "Intra-Cellular, a biopharmaceutical company focused on the development and "
        "commercialization of therapeutics for central nervous system disorders.", jnj)
    assert [(a["target"], a["closing_date"]) for a in found["acquisitions"]] == [
        ("Intra-Cellular", "2025-04-02")]


def test_names_stop_where_the_name_does():
    bmy = closings.aliases("Bristol-Myers Squibb Co", "BMY")
    assert "bms" in bmy
    found = closings.find_closings(
        "On May 13, 2025, BMS completed the acquisition of 2seventy bio, which provided BMS "
        "with full U.S. rights.", bmy)
    assert found["acquisitions"][0]["target"] == "2seventy bio"
    gild = closings.aliases("Gilead Sciences, Inc.", "GILD")
    found = closings.find_closings(
        "GILEAD COMPLETES ACQUISITION OF ARCELLX AHEAD OF POTENTIAL COMMERCIAL LAUNCH OF "
        "ANITO-CEL FOSTER CITY, Calif., April 28, 2026", gild, lead_only=True)
    assert found["acquisitions"][0]["target"] == "ARCELLX"
    azn = closings.aliases("AstraZeneca PLC", "AZN")
    found = closings.find_closings(
        "On 22 October 2025 AstraZeneca completed the acquisition of the remaining $ 35 m "
        "non-controlling interest in SixPeaks Bio AG in exchange for $ 248 m.", azn)
    assert found["acquisitions"] == []
    found = closings.find_closings(
        "On 29 August 2025, AstraZeneca completed the acquisition of FibroGen International "
        "(Hong Kong) Limited (FibroGen China) and its subsidiaries.", azn)
    assert [(a["target"], a["closing_date"]) for a in found["acquisitions"]] == [
        ("FibroGen International", "2025-08-29")]


def test_one_target_under_two_names_is_one_target():
    assert closings.same_target("Intra-Cellular Therapies, Inc.", "Intra-Cellular")
    assert not closings.same_target("Apogee Therapeutics", "Apellis Pharmaceuticals")


def test_cash_paid_comes_from_the_sentence_that_states_the_total():
    paid = closings.consideration(
        "On May 14, 2026, we completed the acquisition of all of the issued and outstanding "
        "shares of Apellis for $5.3 billion in cash, plus one contingent value right per "
        "share. Revenue of $1,004 million in 2025.", "Apellis Pharmaceuticals, Inc.")
    assert paid["cash"] == 5.3e9
    assert paid["cash_quote"].startswith("On May 14, 2026")
    assert "contingent value right" in paid["cvr_quote"]


def test_soleno_projections_are_read_off_the_table_as_printed():
    html = (FIXTURES / "closings_sc14d9_soleno_projections.htm").read_text()
    found = closings.projections(html)
    revenue = closings.revenue_rows(found)
    assert list(revenue) == ["Revenue"]
    series = revenue["Revenue"]
    assert sorted(series) == list(range(2026, 2038))
    assert series[2026] == (410.0, "410") and series[2034] == (1100.0, "1,100")
    assert series[2036] == (198.0, "198")
    assert found["unit"] == "mm USD"
    # Every number drafted appears verbatim in the filing's text.
    text = filingtext.html_to_text(html)
    assert all(cell in text for _value, cell in series.values())
    assert "Gross Profit" in found["rows"] and "Gross Profit" not in revenue


def test_a_risk_adjusted_whole_company_projection_says_so():
    found = closings.projections(
        (FIXTURES / "closings_defm14a_itci_projections.htm").read_text())
    revenue = closings.revenue_rows(found)
    assert list(revenue) == ["Net Revenue"]
    series = revenue["Net Revenue"]
    assert min(series) == 2025 and max(series) == 2047
    assert max(series.items(), key=lambda kv: kv[1][0]) == (2038, (7397.0, "7,397"))
    assert found["risk_adjusted"] is True
    assert found["rows"]["EBIT"][2025] == (-140.0, "(140)")


def test_no_projection_section_is_none():
    assert closings.projections("<p>Background of the Merger</p><table></table>") is None


def test_search_hits_count_only_when_the_target_filed_them():
    payload = json.loads((FIXTURES / "closings_fts_soleno.json").read_text())
    hits = closings.target_filers(payload, "Soleno Therapeutics, Inc.")
    assert hits and {h["cik"] for h in hits} == {"1484565"}
    assert any(h["root_form"] == "SC 14D9" and h["accession"] == "0001193125-26-162853"
               for h in hits)
    # Other filers' documents that mention Soleno are left out.
    every = payload["hits"]["hits"]
    assert len(every) > len(hits)
    none = json.loads((FIXTURES / "closings_fts_vega_none.json").read_text())
    assert none["hits"]["total"]["value"] > 0
    assert closings.target_filers(none, "Vega Therapeutics, Inc") == []


def test_annual_revenue_is_the_target_s_own_full_years():
    facts = json.loads((FIXTURES / "closings_companyfacts_soleno_revenue.json").read_text())
    history = closings.annual_revenue(facts, before="2026-05-18")
    assert history[-1]["end"] == "2025-12-31"
    assert round(history[-1]["value"] / 1e6, 3) == 190.405
    assert history[-1]["accession"]
    assert all(h["tag"] == history[-1]["tag"] for h in history)
