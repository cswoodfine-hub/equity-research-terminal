"""The three ways into the terminal: who lands on which engine, and what a card may claim.

The assignment tests carry most of the weight. A card that overstates a figure is a bad
sentence; a company on the wrong engine is asked questions its filings cannot answer, and
that is where the empty charts came from.
"""

import db
import engines


# --- the assignment rule --------------------------------------------------------------

def _universe(tmp_path, companies):
    """companies: {ticker: {revenue, marketed, themes, reports}}"""
    path = str(tmp_path / "t.db")
    db.init(path)
    conn = db.get_connection(path)
    for ticker, spec in companies.items():
        conn.execute("INSERT INTO companies (ticker, name) VALUES (?, ?)",
                     (ticker, ticker.title()))
        cid = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                           (ticker,)).fetchone()[0]
        if spec.get("reports", True):
            conn.execute(
                "INSERT INTO financials (company_id, metric, value, period_end,"
                "  period_type, fiscal_year, unit) VALUES (?, 'Revenues', ?,"
                "  '2025-12-31', 'FY', 2025, 'USD')", (cid, spec.get("revenue") or 0))
        for index in range(spec.get("marketed", 0)):
            conn.execute("INSERT INTO assets (owner_company_id, generic_name,"
                         "  is_marketed) VALUES (?, ?, 1)", (cid, f"drug{index}"))
        for theme in spec.get("themes", ()):
            conn.execute("INSERT INTO company_themes (company_id, theme, evidence)"
                         " VALUES (?, ?, 'x')", (cid, theme))
    conn.commit()
    conn.close()
    return path


def test_revenue_places_a_major(tmp_path):
    path = _universe(tmp_path, {"BIG": {"revenue": 40e9}})
    assert engines.home(path) == {"BIG": engines.PHARMA}


def test_the_threshold_is_the_gap_not_a_round_number(tmp_path):
    """Biogen at 9.9bn is a major and Incyte at 5.1bn is not, which is what the line
    between them exists to say."""
    path = _universe(tmp_path, {"BIIB": {"revenue": 9.9e9}, "INCY": {"revenue": 5.1e9}})
    homes = engines.home(path)
    assert homes["BIIB"] == engines.PHARMA
    assert homes["INCY"] == engines.BIOTECH


def test_a_platform_under_the_revenue_line_is_cell_and_gene(tmp_path):
    path = _universe(tmp_path, {"ALLO": {"revenue": 0, "themes": ["CAR-T"]}})
    assert engines.home(path)["ALLO"] == engines.CELLGENE


def test_a_platform_earning_billions_is_read_as_a_product_company(tmp_path):
    """Sarepta earns two billion from Elevidys. It is genuinely gene therapy and it is
    answerable on revenue, which is not the question the cell and gene engine asks."""
    path = _universe(tmp_path, {"SRPT": {"revenue": 2.2e9, "themes": ["Gene therapy"]}})
    assert engines.home(path)["SRPT"] == engines.BIOTECH


def test_a_major_with_a_platform_stays_a_major(tmp_path):
    path = _universe(tmp_path, {"VRTX": {"revenue": 12e9, "themes": ["Gene editing"]}})
    assert engines.home(path)["VRTX"] == engines.PHARMA


def test_a_non_filer_with_a_large_register_is_a_major(tmp_path):
    """Roche and Bayer are not SEC registrants, so EDGAR holds no revenue for either and
    the rule has nothing to compare. Both market more than fifty products."""
    path = _universe(tmp_path, {"ROG": {"reports": False, "marketed": 54}})
    assert engines.home(path)["ROG"] == engines.PHARMA


def test_a_non_filer_with_no_register_is_not_promoted(tmp_path):
    """The register route exists for the two European majors, not as a way in for any
    company that files nothing."""
    path = _universe(tmp_path, {"SMALL": {"reports": False, "marketed": 2}})
    assert engines.home(path)["SMALL"] == engines.BIOTECH


def test_a_company_with_no_revenue_and_no_platform_is_biotech(tmp_path):
    path = _universe(tmp_path, {"VKTX": {"revenue": 0}})
    assert engines.home(path)["VKTX"] == engines.BIOTECH


def test_every_company_lands_on_exactly_one_engine(tmp_path):
    path = _universe(tmp_path, {
        "BIG": {"revenue": 40e9}, "MID": {"revenue": 2e9},
        "CG": {"revenue": 0, "themes": ["Gene therapy"]},
        "ROG": {"reports": False, "marketed": 40}})
    homes = engines.home(path)
    assert len(homes) == 4
    assert set(homes.values()) <= set(engines.ENGINES)


def test_an_engine_covers_only_its_own_cohort(tmp_path):
    path = _universe(tmp_path, {
        "BIG": {"revenue": 40e9}, "MID": {"revenue": 2e9},
        "CG": {"revenue": 0, "themes": ["CAR-T"]}})
    assert engines.tickers_for(path, engines.PHARMA) == ["BIG"]
    assert engines.tickers_for(path, engines.BIOTECH) == ["MID"]
    assert engines.tickers_for(path, engines.CELLGENE) == ["CG"]


def test_an_unknown_engine_returns_the_whole_universe(tmp_path):
    """The picker falls back to everything rather than to nothing, so a stale link cannot
    empty the terminal."""
    path = _universe(tmp_path, {"A": {"revenue": 1e9}, "B": {"revenue": 0}})
    assert engines.tickers_for(path, "nonsense") == ["A", "B"]
    assert engines.tickers_for(path, None) == ["A", "B"]


# --- the big pharma card ---------------------------------------------------------------

def _row(**kw):
    base = {"ticker": "AAA", "name": "A", "fresh_share": 0.5, "revenue_latest": 40e9,
            "inferred_revenue": None, "curated_revenue": None}
    return {**base, **kw}


def test_the_headline_names_the_two_ends():
    card = engines._pharma([_row(ticker="TOP", fresh_share=0.73),
                            _row(ticker="MID", fresh_share=0.2),
                            _row(ticker="LOW", fresh_share=0.0)])
    assert "TOP earns 73%" in card["headline"]
    assert "LOW 0%" in card["headline"]


def test_an_inferred_figure_stays_out_of_the_headline():
    """Moderna reads 100% inferred from its whole marketed register rather than from any
    drug's own date. The page's most prominent line should not rest on its weakest
    evidence."""
    card = engines._pharma([
        _row(ticker="INF", fresh_share=1.0, inferred_revenue=2e9),
        _row(ticker="REAL", fresh_share=0.73),
        _row(ticker="LOW", fresh_share=0.0)])
    assert "INF" not in card["headline"]
    assert "REAL earns 73%" in card["headline"]


def test_a_curated_figure_stays_out_of_the_headline():
    card = engines._pharma([
        _row(ticker="CUR", fresh_share=0.99, curated_revenue=5e9),
        _row(ticker="REAL", fresh_share=0.73),
        _row(ticker="LOW", fresh_share=0.0)])
    assert "CUR" not in card["headline"]


def test_the_count_is_everything_measurable_not_the_headline_pool():
    """Reusing one list for both reported 14 of 28 measurable when 23 were."""
    card = engines._pharma([
        _row(ticker="A", fresh_share=1.0, inferred_revenue=1e9),
        _row(ticker="B", fresh_share=0.5),
        _row(ticker="C", fresh_share=0.1),
        _row(ticker="D", fresh_share=None)])
    assert card["detail"].startswith("3 of 4")


def test_no_comparable_pair_gives_no_headline_rather_than_half_a_sentence():
    assert engines._pharma([_row(ticker="ONLY")])["headline"] is None


def test_a_company_with_no_figure_keeps_its_slot_in_the_strip():
    """Dropping it would flatter the spread and hide the coverage the card reports."""
    strip = engines._pharma([_row(ticker="A", fresh_share=0.5),
                             _row(ticker="B", fresh_share=None)])["strip"]
    assert [bar["ticker"] for bar in strip] == ["A", "B"]
    assert strip[1]["height"] is None and strip[1]["tone"] == engines.MUTED


# --- the biotech card -----------------------------------------------------------------

def _cash(**kw):
    base = {"ticker": "BIO", "name": "Bio", "runway_months": 30.0,
            "funded_to_readout": True, "burn_flattered": False}
    return {**base, **kw}


def test_the_biotech_card_names_the_split_and_the_tightest_balance_sheet():
    card = engines._biotech([_cash(ticker="SELLS"), _cash(ticker="BURNS",
                                                          runway_months=14.0)],
                            {"SELLS": 3e9, "BURNS": None})
    assert "1 of the 2 book no revenue at all" in card["headline"]
    assert "BURNS has the least room at 14 months" in card["headline"]


def test_collaboration_income_counts_as_revenue_and_the_card_says_so_no_more():
    """Arrowhead's 340m is a partner payment. Calling the total product revenue would be
    reporting a figure the Revenues tag does not support."""
    card = engines._biotech([_cash(ticker="ARWR")], {"ARWR": 340e6})
    assert card["detail"].startswith("1 book revenue of some kind")


def test_the_biotech_card_falls_back_when_every_name_earns_something():
    card = engines._biotech([_cash(ticker="OK", runway_months=18.0)], {"OK": 2e9})
    assert "tightest balance sheet" in card["headline"]


def test_a_runway_bar_turns_below_a_year():
    bars = {b["ticker"]: b for b in engines._runway_strip(
        [_cash(ticker="TIGHT", runway_months=8.0), _cash(ticker="FINE"),
         _cash(ticker="NONE", runway_months=None)])}
    assert bars["TIGHT"]["tone"] == engines.DOWN
    assert bars["FINE"]["tone"] == engines.UP
    assert bars["NONE"]["tone"] == engines.MUTED


def test_a_very_long_runway_is_capped_rather_than_flattening_the_strip():
    """Arrowhead reads 590 months once a licence receipt offsets the burn."""
    bar = engines._runway_strip([_cash(ticker="ODD", runway_months=590.0)])[0]
    assert bar["height"] == 1.0


# --- the cell and gene card ------------------------------------------------------------

def test_the_cell_and_gene_card_leads_on_the_unfunded():
    card = engines._cellgene(
        [_cash(ticker="SHORT", runway_months=4.0, funded_to_readout=False),
         _cash(ticker="OK")],
        {"SHORT": "Phase 2", "OK": "Phase 3"})
    assert "1 of the 2 reach their next readout only after the cash runs out" \
        in card["headline"]
    assert "SHORT has 4 months" in card["headline"]


def test_a_burn_flattered_by_a_receipt_is_not_counted_as_unfunded():
    """A licence payment that offsets the burn is not a company about to run out."""
    card = engines._cellgene(
        [_cash(ticker="ODD", funded_to_readout=False, burn_flattered=True),
         _cash(ticker="OK")], {"ODD": "Phase 1", "OK": "Phase 1"})
    assert "reach their next readout" not in (card["headline"] or "")


def test_marketed_outranks_every_phase(tmp_path):
    """Abeona runs a Phase 4 trial because Zevaskyn is approved, and a reader looking for
    who is furthest wants that said rather than inferred from the trial number."""
    card = engines._cellgene([_cash(ticker="MKT"), _cash(ticker="P3")],
                             {"MKT": engines.MARKETED, "P3": "Phase 3"})
    assert [leader["ticker"] for leader in card["leaders"]] == ["MKT", "P3"]
    assert card["strip"][0]["height"] == 1.0


def test_a_company_with_no_trial_is_counted_rather_than_dropped():
    card = engines._cellgene([_cash(ticker="A"), _cash(ticker="B")],
                             {"A": "Phase 3", "B": None})
    assert card["detail"] == "1 at Phase 3 or beyond, 1 with no trial on file"
    assert card["strip"][-1]["display"] == "no trial on file"


def test_the_lead_stage_reads_a_marketed_product_before_a_trial(tmp_path):
    path = _universe(tmp_path, {"MKT": {"revenue": 0, "marketed": 1, "themes": ["CAR-T"]}})
    conn = db.get_connection(path)
    try:
        assert engines._lead_stage(conn, ["MKT"]) == {"MKT": engines.MARKETED}
    finally:
        conn.close()


# --- the signal strip ------------------------------------------------------------------

def test_a_risk_factor_rewrite_ranks_below_an_approval(tmp_path):
    """113 of one week's 183 high-significance items were risk-factor diffs. Ranking those
    level with an approval buries every approval."""
    assert (engines.SIGNAL_ORDER.index("new_approval")
            < engines.SIGNAL_ORDER.index("risk_factors_change"))


def test_the_signal_strip_takes_one_item_per_company(tmp_path, monkeypatch):
    path = _universe(tmp_path, {"AAA": {"revenue": 40e9}, "BBB": {"revenue": 0}})
    monkeypatch.setattr(engines.whatchanged, "build_feed", lambda *a, **k: [
        {"kind": "change", "ticker": "AAA", "change_type": "risk_factors_change",
         "headline": "AAA risk factors changed", "date": "2026-07-29",
         "significance": "high"},
        {"kind": "change", "ticker": "AAA", "change_type": "date_slip",
         "headline": "AAA trial slipped", "date": "2026-07-28", "significance": "high"},
        {"kind": "change", "ticker": "BBB", "change_type": "new_approval",
         "headline": "BBB FDA approval: Thing", "date": "2026-07-20",
         "significance": "high"},
    ])
    strip = engines.signals(path)
    assert [item["ticker"] for item in strip] == ["BBB", "AAA"]
    # The approval leads, and the ticker prefix is stripped because the row shows it.
    assert strip[0]["headline"] == "FDA approval: Thing"
    assert strip[0]["kind"] == "approval"
    assert strip[0]["engine"] == engines.BIOTECH
    # AAA's slip beats AAA's risk-factor diff, so the one row it gets is the material one.
    assert strip[1]["headline"] == "Trial slipped"


def test_a_catalyst_or_expiry_is_not_a_signal(tmp_path, monkeypatch):
    """The strip is what changed. A dated event that has not happened yet belongs on the
    calendar, not in a list of moves."""
    path = _universe(tmp_path, {"AAA": {"revenue": 40e9}})
    monkeypatch.setattr(engines.whatchanged, "build_feed", lambda *a, **k: [
        {"kind": "catalyst", "ticker": "AAA", "change_type": None,
         "headline": "AAA PDUFA", "date": "2026-09-01", "significance": "high"}])
    assert engines.signals(path) == []
