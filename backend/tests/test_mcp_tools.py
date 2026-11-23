"""The desk tools: what a model is handed when it reads the book.

The tools add no number of their own, so what can go wrong is the shaping: an answer too
large to be useful, a cut list passed off as a whole one, a refusal the model cannot act
on, or a write it did not mean to make. Each is pinned here against a stand-in for the
API, so the suite needs no server.
"""

import ast
import json
import pathlib
import re

import pytest

import mcp_tools as T


class Api:
    """A stand-in for the terminal's API: canned payloads by path, and a record of what
    was asked."""

    def __init__(self, routes=None):
        self.routes = routes or {}
        self.asked = []

    def __call__(self, method, path, params, body):
        self.asked.append((method, path, params, body))
        if (method, path) in self.routes:
            got = self.routes[(method, path)]
        else:
            got = self.routes.get(path, (404, {"detail": f"nothing at {path}"}))
        if isinstance(got, Exception):
            raise got
        return got if isinstance(got, tuple) else (200, got)


# --- the catalogue --------------------------------------------------------------------
def test_every_tool_is_listed_the_way_the_protocol_wants_it():
    names = [t["name"] for t in T.catalogue()]
    assert len(names) == len(set(names))
    for tool in T.catalogue():
        assert re.fullmatch(r"lens_[a-z_]{2,40}", tool["name"])
        assert tool["title"] and len(tool["description"]) > 60
        schema = tool["input_schema"]
        assert schema["type"] == "object" and schema["additionalProperties"] is False
        assert set(schema["required"]) <= set(schema["properties"])
        for prop in schema["properties"].values():
            assert prop.get("description") or prop.get("enum"), tool["name"]
        json.dumps(schema)                                # a plain JSON Schema


def test_exactly_one_tool_writes_and_it_says_so():
    writers = [t for t in T.catalogue() if not t["read_only"]]
    assert [t["name"] for t in writers] == ["lens_log_thesis"]
    assert "cannot be edited" in writers[0]["description"]


def test_the_copy_a_model_reads_keeps_the_house_style():
    banned = re.compile(r"\b(additionally|highlight|underscore|pivotal|showcase|testament)",
                        re.I)
    for text in [T.INSTRUCTIONS] + [t["description"] for t in T.catalogue()]:
        assert chr(0x2014) not in text and not banned.search(text)


def test_the_module_imports_nothing_from_the_backend():
    """It runs inside the MCP server process too, on a different interpreter that has
    none of the backend's modules or packages to hand."""
    tree = ast.parse(pathlib.Path(T.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"__future__", "json"}


def test_the_instructions_tell_a_model_not_to_estimate_and_not_to_advise():
    assert "do not estimate" in T.INSTRUCTIONS
    assert "not advice" in T.INSTRUCTIONS
    assert "as-of" in T.INSTRUCTIONS


# --- refusing -------------------------------------------------------------------------
def test_an_unknown_tool_names_the_ones_there_are():
    with pytest.raises(T.ToolError) as exc:
        T.call("lens_nope", {}, Api())
    assert "lens_company" in str(exc.value)


def test_an_argument_the_tool_does_not_take_is_refused_with_the_ones_it_does():
    with pytest.raises(T.ToolError) as exc:
        T.call("lens_runway", {"ticker": "DYN", "horizon": 3}, Api())
    assert "horizon" in str(exc.value) and "ticker" in str(exc.value)


def test_a_missing_argument_is_named():
    with pytest.raises(T.ToolError) as exc:
        T.call("lens_asset", {"ticker": "DYN"}, Api())
    assert "asset_id" in str(exc.value)


def test_a_ticker_the_book_does_not_hold_comes_back_in_the_books_own_words():
    api = Api({"/companies/ZZZ/runway": (404, {"detail": "unknown ticker ZZZ"})})
    out = T.call("lens_runway", {"ticker": "zzz"}, api)
    assert out["runway"] == {"absent": "unknown ticker ZZZ"}
    with pytest.raises(T.ToolError) as exc:
        T.call("lens_breakpoints", {"ticker": "zzz"},
               Api({"/companies/ZZZ/breakpoints": (404, {"detail": "unknown ticker ZZZ"})}))
    assert str(exc.value) == "unknown ticker ZZZ"


def test_an_api_that_is_down_says_how_to_start_it():
    api = Api({"/gate-odds": ConnectionRefusedError("refused")})
    with pytest.raises(T.ToolError) as exc:
        T.call("lens_gates", {}, api)
    assert "port 8000" in str(exc.value) and "./run.sh" in str(exc.value)


# --- shaping --------------------------------------------------------------------------
def test_a_cut_list_says_how_many_rows_there_were():
    got = T._rows([{"a": i, "series": [1, 2, 3]} for i in range(50)], limit=10)
    assert got["shown"] == 10 and got["total"] == 50
    assert got["rows"][0] == {"a": 0}                     # the nested series is dropped


def test_an_answer_over_the_budget_is_cut_and_marked():
    huge = {"rows": [{"text": "x" * 500, "n": i} for i in range(400)]}
    got = T._fit(huge)
    assert len(json.dumps(got)) <= T.MAX_CHARS
    assert "cut_to_fit" in got
    assert any(isinstance(r, str) and "more rows cut" in r for r in got["rows"])


def test_an_answer_inside_the_budget_is_left_alone():
    small = {"rows": [{"n": 1}]}
    assert T._fit(small) == {"rows": [{"n": 1}]}


def test_a_long_quote_is_cut_and_says_so():
    assert T._clip("a" * 700).endswith("[cut]") and len(T._clip("a" * 700)) < 620


# --- the tools ------------------------------------------------------------------------
def test_what_if_refuses_with_no_lever_and_says_which_there_are():
    with pytest.raises(T.ToolError) as exc:
        T.call("lens_whatif", {"ticker": "DYN", "asset_id": 9}, Api())
    assert "pos" in str(exc.value) and "loe_year" in str(exc.value)


def test_what_if_sends_only_the_levers_given_and_states_the_change():
    run = {"years": [2027, 2028], "revenue": [10.0, 30.0], "rnpv": 100.0, "pos": 0.5}
    varied = dict(run, rnpv=160.0, pos=0.8)
    api = Api({"/companies/DYN/forecast/9/whatif":
               {"ok": True, "base": run, "varied": varied,
                "ignored": {"price": "this build has no price"}}})
    out = T.call("lens_whatif", {"ticker": "dyn", "asset_id": 9, "pos": 0.8, "price": 2}, api)
    _method, _path, params, _body = api.asked[0]
    assert params == {"scenario": "base", "pos": 0.8, "price": 2}
    assert out["rnpv_change"] == 0.6
    assert out["base"]["peak_revenue"] == 30.0 and out["base"]["peak_year"] == 2028
    assert "years" not in out["base"]                    # the series is not the answer
    assert out["ignored"] == {"price": "this build has no price"}
    assert "nothing in the book was changed" in out["note"]


def test_gates_with_no_ticker_is_the_universe_table_and_with_one_is_the_companys_legs():
    odds = {"as_of": "2026-11-08", "regimes": {"odds": 1},
            "rows": [{"ticker": "DYN", "p_book": 0.53, "p_mkt": 0.94},
                     {"ticker": "VKTX", "p_book": 0.64, "p_mkt": 0.77}]}
    api = Api({"/gate-odds": odds,
               "/companies/DYN/catalysts/stakes":
                   {"diluted_shares": 10.0, "priced": [{"id": 1, "held": {"open": 2}}],
                    "unpriced": []}})
    universe = T.call("lens_gates", {}, api)
    assert universe["as_of"] == "2026-11-08"
    assert universe["single_gate_names"]["total"] == 2
    one = T.call("lens_gates", {"ticker": "dyn"}, api)
    assert one["market_implied"]["rows"] == [{"ticker": "DYN", "p_book": 0.53, "p_mkt": 0.94}]
    assert one["priced"]["rows"][0]["held"] == {"open": 2}
    assert one["gate_odds_as_of"] == "2026-11-08"


def test_as_of_gives_the_call_recorded_on_or_before_the_day_and_never_a_later_one():
    calls = [{"as_of": "2026-10-09", "fair_value": 14.0},
             {"as_of": "2026-10-20", "fair_value": 14.6},
             {"as_of": "2026-11-08", "fair_value": 17.0}]
    api = Api({"/calls/DYN": calls,
               "/as-of": {"history_begins": "2026-07-01", "before_history": False,
                          "financials": {"DYN": {"revenue": 0}, "LLY": {"revenue": 1}},
                          "by_ticker": {}}})
    out = T.call("lens_as_of", {"ticker": "DYN", "date": "2026-10-25"}, api)
    assert out["call_on_or_before"]["fair_value"] == 14.6
    assert out["financials"] == {"revenue": 0}
    before = T.call("lens_as_of", {"ticker": "DYN", "date": "2026-09-01"}, api)
    assert before["call_on_or_before"] is None
    assert before["first_call_on_file"] == "2026-10-09"
    with pytest.raises(T.ToolError):
        T.call("lens_as_of", {"ticker": "DYN", "date": "October"}, api)


def test_evidence_filters_rows_and_refuses_a_kind_it_does_not_hold():
    trials = {"trials": [{"nct_id": "NCT1", "title": "Retatrutide in obesity"},
                         {"nct_id": "NCT2", "title": "Orforglipron in diabetes"}]}
    api = Api({"/companies/LLY/trials": trials})
    out = T.call("lens_evidence", {"ticker": "LLY", "kind": "trials",
                                   "contains": "RETATRUTIDE"}, api)
    assert [r["nct_id"] for r in out["rows"]] == ["NCT1"] and out["total"] == 1
    with pytest.raises(T.ToolError) as exc:
        T.call("lens_evidence", {"ticker": "LLY", "kind": "rumours"}, api)
    assert "trials" in str(exc.value)


def test_the_company_overview_lists_assets_with_their_ids_and_survives_a_missing_part():
    api = Api({"/companies/DYN/fair-value":
                   {"name": "Dyne", "close": 15.5, "price_date": "2026-11-20",
                    "equity_per_share": 17.0, "rating": {"rating": "Hold"}, "lenses": []},
               "/companies/DYN/forecast":
                   {"rnpv_per_share": 12.0, "refused": [],
                    "lines": [{"asset_id": 2069, "name": "DYNE-101", "revenue": [1, 2]}]}})
    out = T.call("lens_company", {"ticker": "DYN"}, api)
    assert out["assets"]["rows"] == [{"asset_id": 2069, "name": "DYNE-101"}]
    assert out["fair_value"]["equity_per_share"] == 17.0
    assert "absent" in out["runway"]                      # no runway route in the stand-in


def test_logging_a_thesis_posts_what_was_given_and_surfaces_a_refusal():
    api = Api({("POST", "/theses"): {"id": 3, "due": "2026-12-23"}})
    args = {"ticker": "DYN", "side": "underperform", "horizon_days": 30,
            "claim": "c" * 30, "rests_on": "r" * 30, "wrong_if": "w" * 30}
    out = T.call("lens_log_thesis", args, api)
    method, path, _params, body = api.asked[0]
    assert (method, path) == ("POST", "/theses") and body == args
    assert out["logged"]["id"] == 3 and "cannot be edited" in out["note"]

    refused = Api({("POST", "/theses"): (422, {"detail": "no closing price on file"})})
    with pytest.raises(T.ToolError) as exc:
        T.call("lens_log_thesis", args, refused)
    assert "no closing price on file" in str(exc.value)

    with pytest.raises(T.ToolError) as exc:
        T.call("lens_log_thesis", {"ticker": "DYN"}, api)
    assert "side" in str(exc.value)


def test_base_rates_reads_the_table_an_asset_or_the_record():
    api = Api({"/base-rates": {"rows": [{"pos": 0.58, "n": 1928}]},
               "/base-rates/asset/7": {"asset_id": 7, "placement": None},
               "/base-rates/record": {"catalysts_resolved": []}})
    assert T.call("lens_base_rates", {"cut": "area"}, api)["rows"][0]["n"] == 1928
    assert api.asked[0][2] == {"cut": "area"}
    assert T.call("lens_base_rates", {"asset_id": 7}, api)["asset_id"] == 7
    assert T.call("lens_base_rates", {"record": True}, api) == {"catalysts_resolved": []}


def test_the_edit_ledger_is_read_without_who_made_each_edit():
    """The ledger records the analyst's address against every edit. A model reading the
    book has no use for it, so it is not among the fields handed over."""
    api = Api({"/changes": [],
               "/model-changes": {"count": 1, "changes": [
                   {"key": "pos", "old_value": 0.4, "new_value": 0.5, "reason": "readout",
                    "changed_by": "analyst@example.test", "batch_id": "b1"}]}})
    out = T.call("lens_changes", {"ticker": "LLY"}, api)
    (row,) = out["assumption_edits"]["rows"]
    assert row == {"key": "pos", "old_value": 0.4, "new_value": 0.5, "reason": "readout"}
    assert "changed_by" not in T.EDIT_FIELDS


def test_insider_dealing_keeps_the_summary_whole_and_cuts_the_list():
    line = {"transaction_date": "2026-11-13", "owner": "An Officer", "code": "S",
            "shares": 231.0, "price": 16.82, "footnotes": "F1: " + "x" * 400,
            "url": "https://example.test/ownership.xml", "accession": "0001-26-000007"}
    summary = {"open_market": {"sales": {"largest": [{"owner": "A Director",
                                                      "value": 99_402_433.0}]}}}
    api = Api({"/companies/DYN/insiders": {"summary": summary, "transactions": [line] * 60,
                                           "transactions_in_window": 60}})
    out = T.call("lens_insiders", {"ticker": "DYN"}, api)
    assert out["summary"] == summary                      # nested, and not cut away
    assert out["transactions"]["shown"] == 30 and out["transactions"]["total"] == 60
    row = out["transactions"]["rows"][0]
    assert "url" not in row and row["footnotes"].endswith("[cut]")
