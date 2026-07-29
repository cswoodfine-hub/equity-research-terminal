"""The modality view and the thematic brief.

The tests that matter here are about what the view refuses to imply. A theme's counts
are a floor, not a total, because an asset named only by a code number states nothing
about itself in any free source. A reader who takes the counts for totals concludes that
a company absent from a theme does not work in that modality, which is false and is the
one wrong reading this view can produce. So coverage travels with the counts, and both
the rules brief and the model prompt say so.
"""

import pytest

import brief
import db
import themes
import themes_view


@pytest.fixture()
def universe(tmp_path):
    """Two companies: one whose drugs name their modality, one whose do not."""
    path = str(tmp_path / "t.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('AAA', 'Alpha Bio')")
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('BBB', 'Beta Bio')")
    alpha = conn.execute("SELECT id FROM companies WHERE ticker='AAA'").fetchone()[0]
    beta = conn.execute("SELECT id FROM companies WHERE ticker='BBB'").fetchone()[0]

    conn.execute("INSERT INTO assets (owner_company_id, brand_name, generic_name,"
                 " is_marketed) VALUES (?, 'Carvykti', 'Ciltacabtagene autoleucel', 1)",
                 (alpha,))
    conn.execute("INSERT INTO assets (owner_company_id, generic_name, is_marketed)"
                 " VALUES (?, 'Lisocabtagene maraleucel', 0)", (alpha,))
    # Beta's programmes are code numbers, which is the coverage gap made concrete.
    for code in ("BBB-101", "BBB-102", "BBB-103"):
        conn.execute("INSERT INTO assets (owner_company_id, internal_code, is_marketed)"
                     " VALUES (?, ?, 0)", (beta, code))

    unapproved = conn.execute(
        "SELECT id FROM assets WHERE generic_name='Lisocabtagene maraleucel'"
    ).fetchone()[0]
    conn.execute("INSERT INTO trials (nct_id, sponsor_company_id, asset_id, phase,"
                 " title) VALUES ('NCT9', ?, ?, 'Phase 2', 'A study')",
                 (alpha, unapproved))
    conn.commit()
    conn.close()
    themes.derive(path)
    return path


def test_build_groups_by_theme(universe):
    rows = themes_view.build(universe)
    car_t = next(r for r in rows if r["theme"] == "CAR-T")
    assert car_t["assets"] == 2
    assert car_t["companies"] == 1
    assert car_t["marketed"] == 1


def test_marketed_leads_the_stage_mix(universe):
    """A marketed drug has passed every phase, so it reads first. Sorting it by phase
    rank put it last, below Phase 1, and the mix read backwards."""
    car_t = next(r for r in themes_view.build(universe) if r["theme"] == "CAR-T")
    assert list(car_t["stage_mix"])[0] == "Marketed"


def test_a_car_t_is_also_counted_as_cell_therapy(universe):
    """The parent theme is the reason a drug carries several: counting a CAR-T only
    under its most specific label empties the broader view."""
    names = {r["theme"] for r in themes_view.build(universe)}
    assert {"CAR-T", "Cell therapy"} <= names


def test_coverage_reports_the_gap_rather_than_hiding_it(universe):
    cover = themes_view.coverage(universe)
    assert cover["assets"] == 5
    assert cover["tagged"] == 2
    assert cover["untagged"] == 3
    assert [c["ticker"] for c in cover["companies_untagged"]] == ["BBB"]


def test_detail_carries_the_evidence(universe):
    """A tag is a judgement read from text, so the phrase travels with the row."""
    detail = themes_view.detail("CAR-T", universe)
    assert detail["assets"]
    assert all(a["evidence"] for a in detail["assets"])


def test_detail_reports_the_furthest_phase(universe):
    detail = themes_view.detail("CAR-T", universe)
    clinical = [a for a in detail["assets"] if not a["is_marketed"]]
    assert clinical[0]["phase"] == "Phase 2"


# --- the brief -----------------------------------------------------------------------

def test_rules_brief_needs_no_model(universe):
    """The rules layer is always available, and a deployment with no key gets it."""
    body = brief.build_rules_brief("CAR-T", universe)
    assert "CAR-T covers 2 programmes across 1 company" in body
    assert "floor" in body


def test_rules_brief_names_a_concentrated_theme_as_a_company_story(universe):
    """One company holding most of a theme is a company story, not a sector one, and
    that distinction is the whole reason to read by modality."""
    assert "company story" in brief.build_rules_brief("CAR-T", universe)


def test_rules_brief_on_an_empty_theme_says_so(universe):
    assert "No programmes on file" in brief.build_rules_brief("Radioligand", universe)


def test_context_always_states_the_coverage_floor(universe):
    """The model must never read a company's absence from a count as a company that
    does not work in the modality, so the gap is in every prompt."""
    facts = brief.context(universe, "CAR-T")
    assert "floor" in facts
    assert "describe a platform in their filing" in facts


def test_generate_degrades_to_the_rules_brief(universe, monkeypatch):
    """A dead model API degrades the brief and is reported. It never raises."""
    monkeypatch.setattr(brief.llm, "provider", lambda prefer=None: "gemini")
    monkeypatch.setattr(brief.llm, "complete",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("503")))
    out = brief.generate(universe, theme="CAR-T")
    assert out["model"] == brief.RULES_MODEL
    assert "RuntimeError" in out["error"]
    assert "CAR-T covers" in out["body"]


def test_generate_stores_and_reads_back(universe, monkeypatch):
    monkeypatch.setattr(brief.llm, "provider", lambda prefer=None: None)
    brief.generate(universe, theme="CAR-T")
    stored = brief.latest(universe, theme="CAR-T")
    assert stored["model"] == brief.RULES_MODEL
    assert stored["theme"] == "CAR-T"


def test_briefs_are_appended_not_overwritten(universe, monkeypatch):
    """History is the product. A brief written today has to be readable against the one
    written last month, or the change in the read is lost."""
    monkeypatch.setattr(brief.llm, "provider", lambda prefer=None: None)
    brief.generate(universe, theme="CAR-T")
    brief.generate(universe, theme="CAR-T")
    conn = db.get_connection(universe)
    n = conn.execute("SELECT COUNT(*) FROM briefs WHERE theme='CAR-T'").fetchone()[0]
    conn.close()
    assert n == 2
