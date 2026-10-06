"""The Universe tab's command centre read (backend/universe_command.py).

Three layers. The rules, on small dicts: the helpers that read a phase, a short name, an
application type or a policy label off source text, and ``assemble``, which is pure. Then
the route over a seeded book in a temporary directory, which has the companies and a few
closes and nothing else, so every block it serves is the empty case. Then a guard on the
built book, skipped where none is built, that checks the served figures against the
prices table they come from.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import statistics

import pytest
from fastapi.testclient import TestClient

import db
import main
import seed
import universe_command as uc

TODAY = dt.date(2026, 10, 6)


# --------------------------------------------------------------------------- helpers
def test_short_company_drops_the_legal_tail():
    assert uc.short_company("AstraZeneca PLC", "AZN") == "AstraZeneca"
    assert uc.short_company("Eli Lilly and Company", "LLY") == "Eli Lilly"
    assert uc.short_company("Novo Nordisk A/S", "NVO") == "Novo Nordisk"
    assert uc.short_company(None, "AZN") == "AZN"


def test_phase_reads_seamless_studies_at_the_phase_they_reach():
    assert uc.phase_of("Phase 3, Truqap") == "p3"
    assert uc.phase_of("Phase 2/3, Sotyktu") == "p3"
    assert uc.phase_of("Phase 1/2, something") == "p2"
    assert uc.phase_of("PDUFA, bepirovirsen") is None


def test_data_phase_reads_the_data_not_the_study():
    text = "Lifitlimab Demonstrates Durable Efficacy in New 52-Week Phase 2 Data from Ongoing Phase 2/3 AMETHYST Study"
    assert uc.data_phase(text) == "2"
    assert uc.data_phase("Phase III camizestrant results") == "3"
    assert uc.data_phase("no phase named") is None


def test_short_event_keeps_words_from_the_title_only():
    assert uc.short_event("Phase 3, Truqap") == "Truqap"
    assert uc.short_event("bepirovirsen PDUFA, treatment of adults with chronic hepatitis B "
                          "(CHB)") == "Bepirovirsen"
    assert uc.short_event("Phase 2, A Study of AZD0901 in Gastric Cancer Patients") == "AZD0901"
    named = uc.short_event("Phase 2, A Randomised Open Label Study in Adults With Disease X",
                           ["Hepatobiliary Neoplasm", "Other"])
    assert named == "Hepatobiliary Neoplasm"
    long = uc.short_event("Phase 3, Comparing two widely used regimens in elderly people")
    assert len(long) <= 22 and "Comparing" in long


def test_short_event_reads_the_drug_a_title_names_before_any_condition():
    """A long registry title gives the first drug it names, by compound code or by the
    stem of its nonproprietary name, before the registry's first condition: the dialog's
    asset column read "Metastatic", "Early-stage" and "Primary Immune" for named drugs."""
    b = uc.short_event_basis
    assert b("Phase 3, Study of Ianalumab Versus Placebo in Addition to First-line "
             "Corticosteroids in Primary Immune Thrombocytopenia",
             ["Primary Immune Thrombocytopenia"]) == ("Ianalumab", "drug")
    # Eight-digit codes, which the seven-digit limit missed.
    assert b("Phase 2, A Study of JNJ-95597528 in Participants With Moderate to Severe "
             "Atopic Dermatitis", ["Dermatitis, Atopic"]) == ("JNJ-95597528", "drug")
    assert b("Phase 3, A Study to Learn How PF-06821497 (Mevrometostat) Works in Men With "
             "Metastatic Castration-Resistant Prostate Cancer", ["Metastatic"]) == (
        "PF-06821497", "drug")
    # A biosimilar's spaced code comes before the reference product it is compared with.
    assert b("Phase 3, Pharmacokinetic Similarity Between ABP 234 and Keytruda® "
             "(Pembrolizumab)", ["Early-stage NSCLC"]) == ("ABP 234", "drug")
    # A year after an acronym is not a code.
    assert b("Phase 3, Results presented at ESMO 2026 for a long running study",
             ["Breast Cancer"]) == ("Breast Cancer", "condition")
    # A condition the registry joins with a semicolon is cut there.
    assert b("Phase 3, A Study of Milvexian in Participants After an Acute Ischemic Stroke",
             ["Ischemic Stroke; Transient Ischemic Attack"]) == ("Ischemic Stroke",
                                                                 "condition")
    # AZN's 27 Oct study names no drug: the condition stands in, and says so.
    assert b("Phase 2, Study of Novel Immunomodulators as Monotherapy and in Combination "
             "With Anticancer Agents in Participants With Advanced Hepatobiliary Cancer",
             ["Hepatocellular Carcinoma", "Biliary Tract Cancer"]) == (
        "Hepatocellular", "condition")
    assert b("Phase 3, Truqap") == ("Truqap", "asset")
    assert b("Phase 3, Comparing two widely used regimens in elderly people")[1] == "title"


def test_application_type_is_read_off_the_number_and_never_guessed():
    assert uc.application_type("NDA220359") == "NDA"
    assert uc.application_type("BLA761123") == "BLA"
    assert uc.application_type("ANDA078654") == "ANDA"
    assert uc.application_type("220359") is None
    assert uc.application_type(None) is None


def test_policy_labels_come_from_the_title():
    rule = {"title": "Medicare Program; Contract Year 2027 Policy and Technical Changes",
            "doc_type": "Rule"}
    assert uc.policy_short(rule) == "CY2027 final rule"
    guidance = {"title": "Medicare Drug Price Negotiation Program: Draft Guidance",
                "doc_type": "Notice"}
    assert uc.policy_short(guidance) == "Negotiation draft guidance"
    rfi = {"title": "Request for Information; Medicare Part D Reasonable and Relevant "
                    "Pharmacy Contracting Standards", "doc_type": "Notice"}
    assert uc.policy_short(rfi) == "Pharmacy contracting RFI"


def test_note_rate_move_reads_the_stored_sentence_or_nothing():
    body = ("The 10-year Treasury is 5.29%, 62bp above the 4.67% the book last priced. "
            "At that rate equity per share falls 9.5%, from 193.34 to 174.97. "
            "Dates compared: 2026-08-27 and 2026-09-30.")
    out = uc.note_rate_move({"body": body, "generated_at": "2026-10-02 06:00:00"})
    assert out["move_bp"] == 62 and out["anchor"] == pytest.approx(0.0467)
    assert out["change_pct"] == pytest.approx(-0.095)
    assert (out["before"], out["now"]) == (193.34, 174.97)
    assert (out["from"], out["to"], out["generated_at"]) == ("2026-08-27", "2026-09-30",
                                                             "2026-10-02")
    assert uc.note_rate_move({"body": "no such sentence"}) is None
    assert uc.note_rate_move(None) is None


def test_a_month_only_date_is_in_only_when_its_month_ends_inside():
    start, end = TODAY, TODAY + dt.timedelta(days=89)
    assert uc._in_ahead({"expected_date": "2026-11", "date_confidence": "month"},
                        start, end) == "in"
    assert uc._in_ahead({"expected_date": "2027-01", "date_confidence": "month"},
                        start, end) == "left"
    assert uc._in_ahead({"expected_date": "2026-09", "date_confidence": "month"},
                        start, end) == "out"
    assert uc._in_ahead({"expected_date": "2026-10-27"}, start, end) == "in"
    assert uc._in_ahead({"expected_date": "2027-02-01"}, start, end) == "out"


# --------------------------------------------------------------------------- assemble
def _rec(ticker, region, own, rel, upside=None, cap=100_000.0, price=100.0, rating=None,
         change_5d=-0.02, target=None):
    rel_w = {k: {"relative_pct": rel, "company_pct": own, "covers_window": True}
             for k in ("1m", "3m", "1y")}
    return {
        "ticker": ticker, "name": f"{ticker} Inc.", "engine": "pharma", "region": region,
        "reporting_currency": "USD",
        "market": {"price": price, "price_as_of": "2026-10-05", "change_1d": 0.01,
                   "change_5d": change_5d, "close_5d_as_of": "2026-09-28",
                   "range_52w": {"low": 80.0, "high": 120.0}, "ttm_change": own,
                   "market_cap_usd_m": cap, "beta": 0.6},
        "model": {"state": "modelled" if upside is not None else "not_modelled",
                  "rating": rating, "upside_12m": upside,
                  "forward_12m": price * (1 + upside) if upside is not None else None,
                  "fair_value_per_share": None, "range_today": None},
        "street": {"price_target": ({"value": target, "low": None, "high": None,
                                     "ratings": {"buy": 3, "hold": 1, "sell": 0}}
                                    if target else None)},
        "healthcare": {"catalysts_12m": 4, "late_trials": 9},
        "detail": {"relative": rel_w},
    }


def _src(**over):
    records = [_rec("AZN", "Europe", -0.175, -0.21, 0.15, 245_000.0, 156.53, "Buy",
                    target=209.46),
               _rec("NVS", "Europe", -0.10, -0.12, 0.29, 269_000.0, rating="Strong buy"),
               _rec("BAYN", "Europe", 0.30, 0.32, None, 49_000.0, change_5d=None),
               _rec("LLY", "US", 0.10, 0.17, -0.55, 1_028_000.0, rating="Sell"),
               _rec("MRK", "US", 0.06, 0.39, 0.18, 344_000.0, rating="Buy"),
               _rec("JNJ", "US", 0.08, 0.16, -0.22, 610_000.0, rating="Sell")]
    src = {
        "today": TODAY.isoformat(), "ticker": "AZN",
        "valuation": {"complete": True, "companies": records,
                      "scorecard": {"cohorts": {"big_pharma": {"label": "Big pharma",
                                                               "noun": "big pharma",
                                                               "medians": {"score": 49}}},
                                    "companies": {"AZN": {"cohort": "big_pharma", "score": 58,
                                                          "rank": 2, "ranked_of": 6,
                                                          "rank_range": [1, 4],
                                                          "pillars": {"growth": {"score": 77,
                                                                                 "median": 48}}}}}},
        "cohort": ["AZN", "BAYN", "JNJ", "LLY", "MRK", "NVS"],
        "closes": {"AZN": [["2026-09-28", 166.15], ["2026-10-05", 156.53]]},
        "benchmark": [["2026-09-28", 150.0], ["2026-10-05", 147.0]],
        "relative": {"1y": {"benchmark_pct": 0.18, "first_as_of": "2025-10-06",
                            "last_as_of": "2026-10-05"}},
        "fair_value": None, "rar_focal": {}, "readouts": [], "note": None,
        "stakes": {"priced": [], "unpriced": [{"id": 1, "missing": ["pos_success",
                                                                  "pos_failure"]}]},
        "catalysts": [
            {"id": 1, "ticker": "AZN", "catalyst_type": "data readout",
             "expected_date": "2026-10-31", "date_confidence": "estimated",
             "title": "Phase 3, Truqap", "description": "NCT00000001"},
            {"id": 2, "ticker": "LLY", "catalyst_type": "PDUFA", "expected_date": "2026-10-26",
             "date_confidence": "confirmed", "title": "PDUFA, orforglipron"},
            {"id": 3, "ticker": "AZN", "catalyst_type": "data readout",
             "expected_date": "2027-01", "date_confidence": "month",
             "title": "Phase 3, Imfinzi"},
            {"id": 4, "ticker": "MRK", "catalyst_type": "data readout",
             "expected_date": "2027-03-01", "date_confidence": "estimated",
             "title": "Phase 3, far away"}],
        "slippage": [{"ticker": "AZN", "trials_moved": 60, "slipped": 35, "pulled_in": 24,
                      "median_days": 28.0}],
        "changes": [], "trials": {"NCT00000001": {"title": "A study", "phase": "PHASE3",
                                                  "enrollment": 293,
                                                  "conditions": ["Breast Cancer"]}},
        "rar": [{"ticker": "AZN", "share_5y": 0.2566, "at_risk_5y_usd": 14.9e9,
                 "priced_total_usd": 58.1e9}],
        "ira": {"AZN": {"exposure": {"share": 0.119, "part_d_spending": 6.99e9,
                                     "revenue_usd": 58.7e9, "spending_years": [2024]},
                        "selected": [{"brand": "FARXIGA", "ipay": 2026, "ceiling_cut": 0.80},
                                     {"brand": "FARXIGA", "ipay": 2026, "ceiling_cut": 0.80}]},
                "LLY": {"exposure": {}, "selected": [], "reason": "none_selected"}},
        "approvals": [{"ticker": "AZN", "label": "Etcamah", "date": "2026-09-04",
                       "application_number": "NDA220359"},
                      {"ticker": "LLY", "label": "generic", "date": "2026-05-01",
                       "application_number": "ANDA078654"}],
        "headlines": [], "markets": {"rates": [], "fx": [], "benchmarks": [], "days": 30},
        "paths": {"rates": {}, "fx": {}}, "policy": [],
    }
    src.update(over)
    return src


def test_assemble_is_pure_and_strict_json():
    src = _src()
    before = json.dumps(src, sort_keys=True)
    out = uc.assemble(src, "AZN", "3m")
    assert json.dumps(src, sort_keys=True) == before
    json.dumps(out, allow_nan=False)
    assert out["window"] == "3m" and out["complete"] is True
    assert out["tickers"][0] == "LLY"                        # largest cap first
    assert out["cohort"]["n"] == 6 and out["cohort"]["noun"] == "big pharma"


def test_lead_medians_are_true_medians_by_region():
    lead = uc.assemble(_src(), "AZN")["lead"]["1y"]
    assert lead["us_median"] == pytest.approx(statistics.median([0.10, 0.06, 0.08]))
    assert lead["eu_median"] == pytest.approx(statistics.median([-0.175, -0.10, 0.30]))
    assert lead["us_n"] == 3 and lead["eu_n"] == 3


def test_a_missing_figure_stays_null():
    out = uc.assemble(_src(), "AZN")
    bayn = out["companies"]["BAYN"]
    assert bayn["model"]["upside"] is None
    assert bayn["change_5d"] is None
    assert bayn["street"]["upside"] is None                  # no target, never 0
    assert bayn["loe"]["share_5y"] is None
    assert "ira" not in bayn                                 # not read, not zero
    assert out["companies"]["LLY"]["ira"]["share"] is None
    assert out["companies"]["MRK"]["slip"]["on_file"] is False


def test_the_board_takes_the_next_90_days_and_counts_what_it_leaves():
    out = uc.assemble(_src(), "AZN")
    ids = [e["id"] for e in out["events"]]
    assert ids == [2, 1]                                     # by date
    assert out["events_left_off"] == 1                       # January, month only
    firm = [e for e in out["events"] if e["firm"]]
    assert [e["ticker"] for e in firm] == ["LLY"] and firm[0]["regulatory"]
    azn = next(e for e in out["events"] if e["id"] == 1)
    assert azn["short"] == "Truqap" and azn["enrollment"] == 293
    assert out["companies"]["AZN"]["n90"] == 1


def test_the_focal_block_and_exposure():
    out = uc.assemble(_src(), "AZN")
    focal = out["focal"]
    assert focal["short"] == "AZN" and focal["ticker"] == "AZN"
    assert [a["application_type"] for a in focal["approvals"]] == ["NDA"]
    assert focal["pillars"]["growth"] == {"score": 77, "median": 48}
    assert focal["fair_value"]["ok"] is False and focal["fair_value"]["lenses"] == []
    stake = focal["events"][0]["stake"]
    assert stake["priced"] is False and stake["per_share"] is None
    assert stake["missing"] == ["pos_success", "pos_failure"]
    priced = uc.assemble(_src(stakes={"priced": [{"id": 1, "per_share": 1.25,
                                                  "share_swing": 2000.0}],
                                      "unpriced": []}), "AZN")["focal"]["events"][0]["stake"]
    assert priced == {"priced": True, "per_share": 1.25, "share_swing_usd_m": 2000.0}
    ira = out["companies"]["AZN"]["ira"]
    assert len(ira["selected"]) == 1                         # a duplicate row folds
    assert ira["share"] == pytest.approx(0.119)
    lane_types = {a["application_type"] for a in out["lanes"]["approvals"]}
    assert lane_types == {"NDA", "ANDA"}


def test_the_xlv_week_is_read_on_the_same_five_sessions():
    bench = [[f"2026-09-{d:02d}", 100.0 + d] for d in (24, 25, 28, 29, 30)] + \
            [["2026-10-01", 140.0], ["2026-10-02", 141.0], ["2026-10-05", 142.0]]
    out = uc.assemble(_src(benchmark=bench), "AZN")
    assert out["xlv_week"]["from"] == "2026-09-28" and out["xlv_week"]["to"] == "2026-10-05"
    assert out["xlv_week"]["change"] == pytest.approx(142.0 / 128.0 - 1)


def test_part_focal_skips_the_cohort_blocks():
    out = uc.assemble(_src(), "AZN", part="focal")
    assert "week_items" not in out and "lanes" not in out
    assert out["focal"]["events"] and out["closes"]["AZN"]


# --------------------------------------------------------------------------- the route
@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    path = tmp_path_factory.mktemp("universe") / "book.db"
    db.init(path)
    seed.load_companies(path)
    conn = db.get_connection(path)
    try:
        cid = conn.execute("SELECT id FROM companies WHERE ticker = 'AZN'").fetchone()[0]
        day = dt.date(2026, 9, 21)
        for i in range(11):
            if day.weekday() < 5:
                conn.execute(
                    "INSERT INTO prices (company_id, as_of, close, high, low, source, interval)"
                    " VALUES (?, ?, ?, ?, ?, 'yahoo_chart', '1d')",
                    (cid, day.isoformat(), 150.0 + i, 151.0 + i, 149.0 + i))
            day += dt.timedelta(days=1)
        conn.commit()
    finally:
        conn.close()
    return path


def test_route_on_a_seeded_book(seeded, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", seeded)
    monkeypatch.setattr(uc, "_fair_value", lambda ticker: None)
    client = TestClient(main.app)
    assert client.get("/universe/command?ticker=NOPE").status_code == 404
    response = client.get("/universe/command?ticker=AZN&window=1m")
    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "AZN" and body["window"] == "1m"
    # The cohort is the companies on AZN's engine, which revenue decides; a book with no
    # revenue on file puts the whole universe on one.
    assert "AZN" in body["tickers"] and len(body["tickers"]) == body["cohort"]["n"]
    azn = body["companies"]["AZN"]
    closes = body["closes"]["AZN"]
    assert closes[-1][0] == azn["price_as_of"]
    assert azn["price"] == closes[-1][1]
    assert azn["change_5d"] == pytest.approx(closes[-1][1] / closes[-6][1] - 1)
    # Nothing else is on file, so every block is its empty case, never a zero.
    assert body["events"] == [] and body["week_items"] == []
    assert azn["model"]["upside"] is None and azn["street"]["upside"] is None
    assert body["companies"]["LLY"]["price"] is None
    focal = client.get("/universe/command?ticker=AZN&part=focal").json()
    assert "lanes" not in focal and focal["focal"]["ticker"] == "AZN"


# --------------------------------------------------------------------------- the book
def test_book_guard_served_figures_match_the_prices_table(book, monkeypatch):
    monkeypatch.setattr(uc, "_fair_value", lambda ticker: None)
    out = uc.build("AZN")
    json.dumps(out, allow_nan=False)
    assert out["companies"]["AZN"]["name"].startswith("AstraZeneca")
    assert len(out["tickers"]) == out["cohort"]["n"] >= 10
    for t, c in out["companies"].items():
        rows = [tuple(r) for r in book.execute(
            """SELECT substr(p.as_of, 1, 10), p.close FROM prices p
                 JOIN companies c ON c.id = p.company_id
                WHERE c.ticker = ? AND p.interval = '1d' AND p.close IS NOT NULL
                  AND substr(p.as_of, 1, 10) <= ?
                ORDER BY p.as_of DESC LIMIT 6""", (t, out["today"]))]
        if not rows:
            assert c["price"] is None and out["closes"][t] == []
            continue
        # The series ends on the latest close, which is the price the page prints.
        assert out["closes"][t][-1][0] == rows[0][0], t
        assert c["price"] == pytest.approx(rows[0][1]), t
        if len(rows) == 6 and c["change_5d"] is not None:
            assert c["change_5d"] == pytest.approx(rows[0][1] / rows[5][1] - 1), t
    for w, lead in out["lead"].items():
        for region, key in (("US", "us_median"), ("Europe", "eu_median")):
            vals = [c["rel"][w]["own"] for c in out["companies"].values()
                    if c["region"] == region and c["rel"][w]["own"] is not None]
            if vals:
                assert lead[key] == pytest.approx(statistics.median(vals)), (w, region)
    start, end = out["events_window"]["start"], out["events_window"]["end"]
    for e in out["events"]:
        if not e["month"]:
            assert start <= e["date"] <= end
    assert all(not (isinstance(v, float) and math.isnan(v))
               for c in out["companies"].values() for v in (c["change_5d"], c["price"]))
