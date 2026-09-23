"""How many people have a disease, held once for the disease rather than once per drug."""

import pytest

import assumptions
import db
import epidemiology as E


def test_the_file_parses_and_every_figure_is_a_number_or_blank():
    got = E.load()
    assert len(got) >= 20
    for name, row in got.items():
        for key in ("prevalence", "incidence"):
            assert row[key] is None or isinstance(row[key], float), (name, key)
            assert row[key] is None or row[key] > 0, (name, key)
        assert row["source"], f"{name} carries no source"


def test_a_disease_with_no_free_citable_count_carries_a_blank_rather_than_a_guess():
    """Six diseases have no US prevalence anybody publishes. A zero would read as a
    disease nobody has, and a plausible number would be an invention."""
    overweight = E.for_indication("Overweight")
    assert overweight is not None, "the row exists"
    assert overweight["prevalence"] is None
    assert "NOT carried as a pool" in overweight["source"]
    assert E.for_indication("Fallopian Tube Neoplasms")["prevalence"] is None


def test_an_unknown_disease_returns_none():
    assert E.for_indication("A Disease Nobody Has") is None
    assert E.for_indication("") is None


def test_every_name_in_the_file_matches_an_indication_the_book_knows():
    """A row keyed on a name the indications table does not use reaches nothing."""
    conn = db.get_connection()
    known = {r["name"] for r in conn.execute("SELECT name FROM indications")}
    conn.close()
    unmatched = [n for n in E.load() if n not in known]
    assert unmatched == [], f"these names reach no indication: {unmatched}"


def test_the_disease_figure_fills_a_gap_but_never_overrides_the_asset(tmp_path):
    """An analyst may model a narrower population than the disease carries, so an
    asset's own row wins. What the file removes is the accidental disagreement."""
    path = str(tmp_path / "epi.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name, reporting_currency)"
                 " VALUES (1, 'LLY', 'Eli Lilly', 'USD')")
    conn.execute("INSERT INTO indications (id, name) VALUES (1, 'Alzheimer Disease')")
    for asset_id, own in ((1, None), (2, 500.0)):
        conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                     " VALUES (?, 1, ?, 0)", (asset_id, f"drug{asset_id}"))
        conn.execute("INSERT INTO asset_indications (asset_id, indication_id, phase,"
                     " region) VALUES (?, 1, 'Phase 3', 'US')", (asset_id,))
        conn.execute("INSERT INTO assumptions (asset_id, indication_id, region, scenario,"
                     " key, value) VALUES (?, 1, 'US', 'base', 'eligible_pct', 1.0)",
                     (asset_id,))
        if own is not None:
            conn.execute("INSERT INTO assumptions (asset_id, indication_id, region,"
                         " scenario, key, value) VALUES (?, 1, 'US', 'base',"
                         " 'prevalence', ?)", (asset_id, own))
    conn.commit()

    filled = assumptions.load(conn, 1)
    kept = assumptions.load(conn, 2)
    conn.close()
    assert filled["indications"][0]["scalars"]["prevalence"] == 7_400_000.0
    assert [f["key"] for f in filled["epidemiology"]] == ["prevalence", "incidence"]
    assert kept["indications"][0]["scalars"]["prevalence"] == 500.0
    # Its prevalence is its own and untouched. Its incidence is still filled, because
    # it never stated one, and the fill is per figure rather than per disease.
    assert [f["key"] for f in kept["epidemiology"]] == ["incidence"]


def test_no_two_assets_disagree_about_how_many_people_have_a_disease():
    """The guard. Four assets said multiple myeloma was 36,110 people and a fifth said
    36,000; two said follicular lymphoma was 13,619 and 13,960. Prevalence is a fact
    about a disease, so a disagreement is one of them being wrong."""
    conn = db.get_connection()
    rows = conn.execute(
        """SELECT i.name, COUNT(DISTINCT s.value) n,
                  GROUP_CONCAT(DISTINCT CAST(s.value AS TEXT)) vals
             FROM assumptions s JOIN indications i ON i.id = s.indication_id
            WHERE s.key = 'prevalence' AND s.scenario = 'base'
            GROUP BY s.indication_id HAVING n > 1""").fetchall()
    conn.close()
    assert rows == [], "; ".join(f"{r['name']}: {r['vals']}" for r in rows)
