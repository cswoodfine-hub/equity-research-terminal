"""A release that names its study in its opening is tied to it, a study that has just
completed is one a release can be tied to, and a release that names two studies ties to
neither. The cases are the six held as tied to no study on 2026-11-24."""

from __future__ import annotations

import datetime as dt

import db
import landed_readouts as L
import press_readouts as P

TODAY = dt.date(2026, 11, 24)
NONE = "/nonexistent/file.csv"


def _book(tmp_path):
    path = str(tmp_path / "book.db")
    db.init(path)
    c = db.get_connection(path)
    c.executemany("INSERT INTO companies (id, ticker, name) VALUES (?, ?, ?)",
                  [(1, "LLY", "Eli Lilly"), (2, "PFE", "Pfizer")])
    c.executemany("INSERT INTO assets (id, owner_company_id, brand_name, generic_name,"
                  " is_marketed) VALUES (?, ?, ?, ?, 1)",
                  [(212, 1, "Foundayo", "Orforglipron Calcium"),
                   (28, 2, "Litfulo", "Ritlecitinib Tosylate")])
    recent = (TODAY - dt.timedelta(days=120)).isoformat()
    c.executemany("INSERT INTO completed_trials (nct_id, sponsor_company_id, asset_id, title,"
                  " phase, completion_date, acronym) VALUES (?, ?, ?, ?, 'Phase 3', ?, ?)",
                  [("NCT06649045", 1, 212, "A Master Protocol for Orforglipron in OSA",
                    recent, "ATTAIN-OSA"),
                   ("NCT05583526", 2, 28, "A 52-Week Study of Ritlecitinib in Vitiligo",
                    recent, "Tranquillo")])
    c.execute("INSERT INTO trials (nct_id, asset_id, sponsor_company_id, phase, overall_status,"
              " title, acronym) VALUES ('NCT06072183', 28, 2, 'Phase 3', 'Active not recruiting',"
              " 'A 104-Week Study of Ritlecitinib (Tranquillo 2)', 'Tranquillo 2')")
    c.execute("INSERT INTO catalysts (id, company_id, asset_id, catalyst_type, expected_date,"
              " date_confidence, title, is_curated, source_url, status) VALUES (576, 2, 28,"
              " 'data readout', '2026-09-30', 'estimated', 'Phase 3, Tranquillo 2', 0,"
              " 'https://clinicaltrials.gov/study/NCT06072183', 'pending')")
    c.commit()
    return path, c


OSA_LEAD = ("Lilly's Foundayo (orforglipron) significantly reduced obstructive sleep apnea "
            "severity. INDIANAPOLIS -- In the Phase 3 ATTAIN-OSA program, Foundayo met the "
            "primary endpoint at 52 weeks.")
VITILIGO_LEAD = ("Pfizer today presented results from two Phase 3 trials. In the two studies, "
                 "TRANQUILLO 2 and TRANQUILLO, LITFULO significantly improved repigmentation.")


def test_a_completed_study_is_one_a_release_can_name(tmp_path):
    _path, c = _book(tmp_path)
    index = {s["nct_id"]: s for s in L.studies(c, {})}
    assert index["NCT06649045"]["names"] == ["ATTAIN-OSA"]
    assert index["NCT06649045"]["catalysts"] == []


def test_the_opening_ties_a_release_to_the_one_study_it_names(tmp_path):
    _path, c = _book(tmp_path)
    index = L.studies(c, {})
    row = {"company_id": 1, "drug": "Foundayo", "lead": OSA_LEAD}
    [(study, how)] = L.lead_tie(row, index)
    assert study["nct_id"] == "NCT06649045" and how == "study name in the release's opening"
    # Another drug's study named in the opening does not tie.
    assert L.lead_tie({**row, "drug": "Mounjaro"}, index) == []


def test_a_release_naming_two_studies_ties_to_neither_whatever_their_case(tmp_path):
    """"Tranquillo" is too plain a word to tie by, so only TRANQUILLO 2 matched, and the
    release that reports both studies was tied to the one still running."""
    _path, c = _book(tmp_path)
    assert L.lead_tie({"company_id": 2, "drug": "Litfulo", "lead": VITILIGO_LEAD},
                      L.studies(c, {})) == []


def test_a_result_on_a_study_with_no_readout_on_the_calendar_is_kept_and_closes_nothing(
        tmp_path):
    path, c = _book(tmp_path)
    study = next(s for s in L.studies(c, {}) if s["nct_id"] == "NCT06649045")
    got = L.land(path, study, "met", "2026-11-09", "met the primary endpoint", None,
                 "press", TODAY, step=False)
    assert got["state"] == "no_gate" and got["catalyst_id"] is None and not got["new"]
    assert "ATTAIN-OSA (NCT06649045)" in got["reason"]


def test_the_run_ties_through_the_opening_and_settles_the_headline_held_as_untied(tmp_path):
    path, c = _book(tmp_path)
    url = "https://investor.lilly.com/foundayo-osa"
    c.execute("INSERT INTO news (id, company_id, source, title, url, published_at) VALUES"
              " (9, 1, 'press_ir', 'Foundayo significantly reduced OSA severity', ?,"
              " '2026-11-09')", (url,))
    c.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome,"
              " event_date, quote, source_url, source, read_from, lead) VALUES ('news:9', 1,"
              " 'Foundayo', 3, 'positive', '2026-11-09', 'Foundayo met the primary endpoint',"
              " ?, 'press', 'release', ?)", (url, OSA_LEAD))
    c.execute("INSERT INTO readout_reports (source_key, company_id, source, kind, url,"
              " published_at, sentence, state, reason, dedupe) VALUES (?, 1, 'press',"
              " 'readout', ?, '2026-11-09', 'Foundayo significantly reduced OSA', 'not_tied',"
              " 'it names Foundayo and no study', ?)", (url, url, f"{url}|"))
    c.commit()
    c.close()
    L.run(path, today=TODAY, step=False, names_path=NONE, set_aside_path=NONE)
    c = db.get_connection(path)
    rows = {(r["nct_id"], r["state"]) for r in c.execute(
        "SELECT nct_id, state FROM readout_reports")}
    assert ("NCT06649045", "no_gate") in rows
    assert (None, "on_file") in rows and (None, "not_tied") not in rows


def test_the_opening_starts_at_the_result_past_the_sites_menus():
    page = ("Investors About Leadership Mission Press Releases " * 40
            + "THOUSAND OAKS -- Amgen announced results from the Phase 3 OASIZ-301 study. "
              "Dazodalibep met the primary endpoint, improving disease activity. "
            + "More text. " * 20 + "\nAbout Amgen Amgen discovers medicines.")
    lead = P.lead_of(page, ("AMGEN ANNOUNCES", "dazodalibep"),
                     "Dazodalibep met the primary endpoint, improving disease activity")
    assert "OASIZ-301" in lead and "Dazodalibep met the primary" in lead
    assert "About Amgen" not in lead
    # With no quote, the headline anchors it; an "About" in the menu above is not the end.
    plain = P.lead_of("Menu About Us. HEADLINE HERE " + "Body text naming ATTAIN-OSA. " * 30
                      + "About Lilly ...", ("Headline here",))
    assert plain.startswith("HEADLINE HERE") and "About Lilly" not in plain


def test_a_head_to_head_win_said_as_a_comparison_is_read():
    title = ("Lilly's retatrutide delivered greater A1C reduction and more than double the "
             "weight loss of Ozempic's highest approved dose in head-to-head trial")
    assert P.TITLE_HINT.search(title)
    assert not P.TITLE_HINT.search("Lilly to present new data at ObesityWeek 2026")
