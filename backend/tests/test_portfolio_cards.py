"""The Portfolio tab's asset cards: a marketed product and a compound in development.

Lives here so ``cd backend && pytest -q`` stays the one test command. Figures synthetic.
"""

import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "frontend"))

import portfolio_cards as PC  # noqa: E402

TODAY = dt.date(2026, 11, 22)
BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament")


def _text(markup: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", markup)).strip()


def _programme(**over):
    base = {"asset_id": 7, "name": "Examplatide", "modality": None, "phase": "Phase 3",
            "areas": ["Metabolic", "Renal and hepatic"], "area": "Metabolic",
            "source": "registry", "trials": 3, "next_readout": "2027-01",
            "studies": [
                {"nct_id": "NCT00000003", "title": "Late study", "phase": "Phase 3",
                 "status": "Recruiting", "due": "2028-04-01", "enrollment": 600,
                 "area": "Metabolic"},
                {"nct_id": "NCT00000001", "title": "First <b>study</b>", "phase": "Phase 3",
                 "status": "Active not recruiting", "due": "2026-08-27", "enrollment": 1250,
                 "area": "Metabolic"},
                {"nct_id": "NCT00000002", "title": "Undated study", "phase": "Phase 2",
                 "status": "Enrolling by invitation", "due": None, "enrollment": None,
                 "area": "Renal and hepatic"}]}
    base.update(over)
    return base


def _verdict():
    return {"diluted_shares": 1_000_000_000,
            "modelled": [{"asset_id": 7, "per_share": 20.34, "pos": 0.875,
                          "per_share_success": 20.78, "per_share_failure": 0.0,
                          "is_marketed": False,
                          "gate": {"label": "Phase 3 readout", "date": "2026-11", "due": True}},
                         {"asset_id": 1, "per_share": 150.59, "pos": 1.0, "is_marketed": True}],
            "placeholders": [{"asset_id": 8, "rnpv_share": 500.0}],
            "refused": [{"asset_id": 9, "missing": ["therapy_mode", "wacc"]}]}


# --- the phase track ------------------------------------------------------------------
def test_a_phase_stands_on_the_step_it_names_and_a_seamless_one_between_two():
    assert PC.phase_position("Phase 1") == 1 and PC.phase_position("Phase 3") == 3
    assert PC.phase_position("Phase 1/2") == 1.5 and PC.phase_position("Phase 2/3") == 2.5
    # Off the track: a study after approval, a stage out of a filing, nothing at all.
    for off in ("Phase 4", "IND cleared", "", None):
        assert PC.phase_position(off) is None


def test_the_track_fills_what_is_reached_and_half_fills_what_is_being_run_into():
    two = PC.phase_track_html("Phase 2")
    assert two.count('class="n on"') == 2 and 'class="n half"' not in two
    seamless = PC.phase_track_html("Phase 2/3")
    assert seamless.count('class="n on"') == 2 and seamless.count('class="n half"') == 1
    # The half step is the third, the one Phase 3 names.
    assert re.search(r'class="n half" title="Phase 3"', seamless)


def test_a_phase_off_the_track_prints_as_words_and_fills_no_step():
    for off, said in (("Phase 4", "Phase 4"), (None, "phase not stated")):
        drawn = PC.phase_track_html(off)
        assert "pc-track" not in drawn and said in drawn


# --- dates ----------------------------------------------------------------------------
def test_how_far_off_a_date_is_said_to_the_month():
    assert PC.how_far("2026-10", TODAY) == "date passed"
    assert PC.how_far("2026-11-30", TODAY) == "this month"
    assert PC.how_far("2026-12", TODAY) == "in 1 month"
    assert PC.how_far("2028-01-15", TODAY) == "in 14 months"
    assert PC.how_far("2029-05", TODAY) == "in 2.5 years"
    assert PC.how_far(None, TODAY) == "" and PC.how_far("soon", TODAY) == ""
    assert PC.month_text("2027-01-15") == "Jan 2027" and PC.month_text("") == ""


# --- the studies ----------------------------------------------------------------------
def test_the_studies_are_counted_and_patients_summed_only_where_stated():
    s = PC.studies_summary(_programme()["studies"])
    assert s == {"n": 3, "enrolling": 2, "patients": 1850}
    assert PC.studies_line(_programme()["studies"]) == "3 trials · 2 enrolling · 1,850 patients"
    # No enrolment on any study is no figure, never a nought.
    lone = [{"status": "Completed", "enrollment": None}]
    assert PC.studies_summary(lone)["patients"] is None
    assert PC.studies_line(lone) == "1 trial"
    assert PC.studies_line([]) == ""


# --- the book -------------------------------------------------------------------------
def test_the_book_says_which_of_three_things_it_makes_of_a_compound():
    book = PC.book_from_verdict(_verdict())
    assert book[7]["state"] == "valued" and book[7]["per_share"] == 20.34
    assert book[7]["gate"]["due"] is True and book[1]["marketed"] is True
    assert book[8] == {"state": "held", "per_share": 0.5}
    assert book[9] == {"state": "refused", "missing": ["therapy_mode", "wacc"]}
    assert 10 not in book                      # not looked at is not in the book
    assert PC.book_from_verdict(None) == {} and PC.book_from_verdict({}) == {}


# --- the pipeline card ----------------------------------------------------------------
def test_a_valued_compound_shows_its_track_its_next_gate_its_odds_and_its_value():
    card = PC.pipeline_card_html(_programme(), PC.book_from_verdict(_verdict())[7], TODAY)
    text = _text(card)
    assert card.startswith('<div class="pf-card pc pipe">')   # the frame clicks on pf-card
    assert "Examplatide" in text and "Metabolic +1" in text
    assert card.count('class="n on"') == 3
    # The gate the book prices, not the registry's next study, and overdue by the
    # forecast's own flag though the date is in the current month.
    assert "Phase 3 readout" in text and "Nov 2026" in text and "overdue" in text
    assert 'class="far late"' in card and PC.OVERDUE_TIP in card
    assert "88%" in text and "20.34" in text and "a share" in text
    assert "3 trials · 2 enrolling · 1,850 patients" in text


def test_a_compound_the_book_does_not_price_says_why_and_prints_no_figure():
    refused = PC.pipeline_card_html(_programme(asset_id=9), {"state": "refused",
                                    "missing": ["therapy_mode", "wacc"]}, TODAY)
    assert "not valued" in _text(refused) and "therapy_mode, wacc" in refused
    unread = PC.pipeline_card_html(_programme(asset_id=10), None, TODAY)
    assert "not modelled" in _text(unread)
    held = PC.pipeline_card_html(_programme(asset_id=8), {"state": "held", "per_share": 0.5},
                                 TODAY)
    assert "0.50 held" in _text(held)
    for card in (refused, unread):
        assert "0.00" not in card and "odds" not in _text(card)
        # With no priced gate the next event is the registry's.
        assert "next study due" in _text(card) and "Jan 2027" in _text(card)


def test_a_compound_named_only_in_a_filing_prints_its_stage_as_words():
    card = PC.pipeline_card_html(
        _programme(source="filing", phase=None, stage="IND cleared", studies=[],
                   next_readout=None, indication="Sickle cell disease", form_type="10-K",
                   filed_date="2026-02-25", evidence="We received IND clearance."), None, TODAY)
    text = _text(card)
    assert "pc-track" not in card and "IND cleared" in text
    assert "Sickle cell disease" in text and "10-K 2026-02-25" in text
    assert "no date on file" in text


def test_the_cards_are_ordered_by_value_then_by_the_nearest_study():
    book = {1: {"state": "valued", "per_share": 2.0}, 2: {"state": "valued", "per_share": 9.0},
            3: {"state": "refused", "missing": []}}
    progs = [{"asset_id": 3, "name": "c", "next_readout": "2027-05"},
             {"asset_id": 1, "name": "a", "next_readout": "2029-01"},
             {"asset_id": 4, "name": "d", "next_readout": "2026-12"},
             {"asset_id": 2, "name": "b", "next_readout": None}]
    assert [p["asset_id"] for p in PC.pipeline_order(progs, book)] == [2, 1, 4, 3]


def test_the_summary_counts_the_pipeline_and_names_the_next_study_ahead():
    progs = [_programme(), _programme(asset_id=9, name="Refused", phase="Phase 2/3",
                                      next_readout="2026-12-05"),
             _programme(asset_id=11, name="Early", phase="Phase 1", next_readout="2026-09")]
    s = PC.pipeline_summary(progs, PC.book_from_verdict(_verdict()), TODAY)
    assert s["n"] == 3 and s["late"] == 2
    assert s["n_valued"] == 1 and s["value"] == 20.34
    # A study whose date has passed is not the next one.
    assert s["next"] == ("2026-12", "Refused")
    empty = PC.pipeline_summary([], {}, TODAY)
    assert empty["value"] is None and empty["next"] is None


# --- the studies, in full -------------------------------------------------------------
def test_the_dialog_lists_every_study_soonest_first_with_its_registry_link():
    markup = PC.trials_html(_programme(), PC.book_from_verdict(_verdict())[7], TODAY)
    order = re.findall(r"NCT0000000\d(?=\")", markup)
    assert order == ["NCT00000001", "NCT00000003", "NCT00000002"]     # undated last
    assert 'href="https://clinicaltrials.gov/study/NCT00000001"' in markup
    # A title is the registry's text and is escaped, never read as markup.
    assert "First &lt;b&gt;study&lt;/b&gt;" in markup
    # Past its date and still open is flagged; a study with no enrolment prints no nought.
    assert markup.count('class="d late"') == 1
    assert ">no free data<" in markup and ">no date<" in markup
    text = _text(markup)
    assert "overdue, no readout on file" in text
    assert "if the next gate passes 20.78 a share" in text and "if it fails 0.00 a share" in text


def test_a_compound_with_no_study_says_so():
    markup = PC.trials_html(_programme(studies=[]), None, TODAY)
    assert "No registered study is bound to this compound." in markup and "<table" not in markup


def test_one_table_draws_a_study_for_a_compound_and_for_a_marketed_product():
    studies = _programme()["studies"]
    table = PC.studies_table_html(studies, TODAY)
    # The compound's dialog is this table under its facts, not a second drawing of it.
    assert table in PC.trials_html(_programme(), None, TODAY)
    assert table.count("<tr>") == 1 + len(studies)          # the head and a row a study
    # A study with no area prints its registry number alone, with no stray separator.
    bare = PC.studies_table_html([{"nct_id": "NCT9", "title": "T", "due": "2027-03"}], TODAY)
    assert "<span>NCT9</span>" in bare and "Mar 2027" in bare


def test_completed_studies_are_newest_first_with_the_outcome_the_registry_names():
    done = [{"nct_id": "NCT1", "title": "Older", "phase": "Phase 3",
             "completion_date": "2024-07-23", "enrollment": 400,
             "primary_outcome": "Change From Baseline in HbA1c"},
            {"nct_id": "NCT2", "title": "Newer", "phase": "Phase 1",
             "completion_date": "2025-09-26", "enrollment": None, "primary_outcome": ""}]
    table = PC.completed_table_html(done)
    assert table.index("Newer") < table.index("Older")
    assert 'href="https://clinicaltrials.gov/study/NCT1?tab=results"' in table
    assert "primary outcome: Change From Baseline in HbA1c" in table
    # No outcome on file is no outcome line, and no enrolment is no nought.
    assert "<span>NCT2</span>" in table and ">no free data<" in table
    assert "Sep 2025" in table and "Jul 2024" in table


def test_a_figure_a_period_is_a_bar_on_the_blocks_own_scale():
    drawn = PC.bars_html([("FY2023", "5.16 USD bn", 5.16e9), ("FY2024", "11.54 USD bn", 11.54e9),
                          ("FY2025", "22.97 USD bn", 22.97e9), ("FY2026", "none", None)])
    assert drawn.count('class="pb-r"') == 3                 # a period with no figure is left out
    assert "width:100.0%" in drawn and "width:22.5%" in drawn
    assert ">22.97 USD bn<" in drawn and "FY2026" not in drawn
    # A negative figure is printed and has no length.
    assert "width:0.0%" in PC.bars_html([("Q1", "1.0", 1.0), ("Q2", f"{PC.MINUS}0.5", -0.5)])
    assert PC.bars_html([]) == "" and PC.bars_html([("FY", "x", None)]) == ""


# --- the marketed card ----------------------------------------------------------------
def _rows():
    return [{"asset_id": 1, "fiscal_year": 2023, "value": 5.0e9},
            {"asset_id": 1, "fiscal_year": 2025, "value": 22.0e9},
            {"asset_id": 1, "fiscal_year": 2024, "value": 11.0e9},
            {"asset_id": 1, "fiscal_year": 2022, "value": None},      # a gap, not a nought
            {"asset_id": 2, "fiscal_year": 2025, "value": 3.0e9}]


def test_a_products_history_is_its_own_years_oldest_first_with_gaps_left_out():
    assert PC.history(_rows(), 1) == [(2023, 5.0e9), (2024, 11.0e9), (2025, 22.0e9)]
    assert PC.history(_rows(), 2) == [(2025, 3.0e9)] and PC.history(_rows(), 3) == []
    many = [{"asset_id": 1, "fiscal_year": y, "value": float(y)} for y in range(2015, 2026)]
    assert [y for y, _v in PC.history(many, 1)] == [2021, 2022, 2023, 2024, 2025]


def test_growth_is_one_year_on_the_one_before_and_never_across_a_gap():
    assert PC.growth([(2024, 11.0e9), (2025, 22.0e9)]) == 1.0
    assert PC.growth([(2023, 11.0e9), (2025, 22.0e9)]) is None      # a two-year rate
    assert PC.growth([(2025, 22.0e9)]) is None
    assert PC.growth([(2024, 0.0), (2025, 22.0e9)]) is None


def test_the_history_draws_a_column_a_year_and_nothing_for_a_single_year():
    drawn = PC.history_html(PC.history(_rows(), 1), "USD")
    assert drawn.count("<i ") == 3 and drawn.count('class="now"') == 1
    assert "FY2023 5.00 · FY2024 11.00 · FY2025 22.00 USD bn" in drawn
    assert f"height:{PC.HISTORY_H:.1f}px" in drawn            # the largest year is the full height
    assert PC.history_html([(2025, 3.0e9)]) == ""


def test_the_runway_is_years_left_on_fifteen_and_solid_only_to_the_earliest_patent():
    assert PC.runway_html(None) == ""                         # no date is no bar, not an empty one
    plain = PC.runway_html(6, "bio")
    assert 'class="pc-run bio"' in plain and "width:40.0%" in plain and 'class="w"' not in plain
    window = PC.runway_html(9, "small", False, 6)
    assert "width:40.0%" in window and "left:40.0%;width:20.0%" in window
    assert "width:100.0%" in PC.runway_html(22)               # capped at the scale
    assert 'class="pc-run small near"' in PC.runway_html(2, "small", True)


def _marketed(**over):
    d = {"brand": "Examplo", "generic": "examplatide", "modality": "small molecule",
         "book": "small", "revenue": 22.0e9, "revenue_unit": "USD", "share": 0.43,
         "points": PC.history(_rows(), 1), "loe_label": "exclusivity to",
         "loe_text": "2036 · 10y", "years_left": 10, "near": False,
         "note": "compound patent · 9474780", "approved": "2022-05-13", "value": 150.59}
    d.update(over)
    return d


def test_a_marketed_card_leads_on_what_it_earns_and_how_long_it_is_protected():
    card = PC.marketed_card_html(_marketed())
    text = _text(card)
    assert card.startswith('<div class="pf-card pc mkt small">')
    assert "22.00" in text and "USD bn" in text and "+100%" in text and "43% of revenue" in text
    assert "exclusivity to 2036 · 10y" in text and 'class="pc-run small"' in card
    assert "compound patent · 9474780" in text
    assert "approved 2022 · book 150.59 a share" in text


def test_a_marketed_card_never_draws_what_is_not_on_file():
    card = PC.marketed_card_html(_marketed(revenue=None, share=None, points=[], years_left=None,
                                           loe_text="lapsed 1994", loe_label="exclusivity",
                                           value=None, note="", shelved=True))
    text = _text(card)
    assert "no free data" in text and "0.00" not in card
    assert "pc-run" not in card and "pc-hist" not in card and "of revenue" not in text
    assert "book" not in text and " shelved" in card
    # A falling product reads as falling.
    falling = PC.marketed_card_html(_marketed(points=[(2024, 4.0e9), (2025, 3.0e9)]))
    assert f"{PC.MINUS}25%" in falling and 'class="g dn"' in falling


def test_names_from_a_source_are_escaped_and_the_copy_keeps_house_style():
    card = PC.marketed_card_html(_marketed(brand="A<b>&", generic='x"y'))
    assert "A&lt;b&gt;&amp;" in card and "x&quot;y" in card
    visible = " ".join(_text(m) for m in (
        card, PC.pipeline_card_html(_programme(), PC.book_from_verdict(_verdict())[7], TODAY),
        PC.pipeline_card_html(_programme(), None, TODAY),
        PC.trials_html(_programme(), None, TODAY)))
    assert "—" not in visible                             # no em dash
    assert not any(word in visible.lower() for word in BANNED)
