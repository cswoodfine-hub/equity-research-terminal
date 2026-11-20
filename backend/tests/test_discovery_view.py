"""The Discovery tab's markup and copy (frontend/discovery_view.py)."""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT / "frontend") not in sys.path:
    sys.path.insert(0, str(ROOT / "frontend"))

import discovery_view as V  # noqa: E402

BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament")

PAPER = {"id": "MED:1", "title": "An <i>AAV</i> vector & a result", "published": "2026-11-01",
         "indexed": "2026-11-03", "journal": "Blood", "preprint": False,
         "senior_author": "Ada Byron", "institution": "Test University",
         "lab": {"id": "A1", "name": "Ada Byron", "rank": 12},
         "lab_match": "name and institution", "areas": ["AAV", "Liver"], "stage": "patients",
         "stage_name": "patients", "company_author": True, "feas_pct": 0.995,
         "comm_pct": 0.6, "feas_top": "top 1%", "comm_top": "top 40%",
         "reasons": {"feas": {"flags": ["in patients"],
                              "phrases": ["patients", "dose", "durable"]},
                     "comm": {"flags": [], "phrases": ["vector"]}},
         "url": "https://europepmc.org/article/MED/1"}
LAB = {"id": "A1", "name": "Ada Byron", "rank": 12, "institutions": ["Test University"]}


def alert(kind, name, sig="medium", paper=PAPER, lab=None, day="2026-11-20", **extra):
    return {"id": hash((kind, day)) % 1000, "date": day, "kind": kind, "kind_name": name,
            "significance": sig, "headline": "The stored headline", "before": None,
            "paper_id": (paper or {}).get("id") or "MED:9",
            "url": "https://europepmc.org/article/MED/1", "lab": lab, "paper": paper, **extra}


GOT = {"label": "Discovery", "days": 14,
       "basis": {"labs": 6345, "labs_ranked_as_of": "2026-11-14",
                 "last_read": "2026-11-20 06:10:00", "held_without_abstract": 3,
                 "top_paper_share": 5, "lab_rank_limit": 300},
       "alerts": [
           alert("discovery_paper_top", "Top paper", "high"),
           alert("discovery_lab_stage", "Lab reached a later model", "high", lab=LAB,
                 before="mice"),
           alert("discovery_lab_company", "Lab's first company co-author", "high", lab=LAB),
           alert("discovery_lab_paper", "Ranked lab published", lab=LAB,
                 paper={**PAPER, "id": "PPR:2", "title": "A preprint", "preprint": True,
                        "journal": "bioRxiv", "institution": None,
                        "lab_match": "name only, one ranked lab of that name"},
                 day="2026-11-19"),
           alert("discovery_paper_top", "Top paper", paper=None, day="2026-11-01")]}


def test_alerts_about_one_paper_are_one_row():
    markup = V.alerts_html(GOT)
    assert markup.count('class="dsc-item') == 3
    assert markup.count("2026-11-20 · 1 paper<") == 1
    first = markup.split('class="dsc-item')[1]
    assert first.count('class="dsc-kind"') == 3 and first.startswith(" high")
    assert "Top 1% for feasibility, top 40% for commercial pull" in first
    assert "Ada Byron, ranked 12: first paper in patients, after mice" in first
    assert "Ada Byron, ranked 12: first paper with a company among the authors" in first
    assert "lab matched by name and institution" in first


def test_a_title_is_escaped_and_links_to_the_paper():
    markup = V.alerts_html(GOT)
    assert "An &lt;i&gt;AAV&lt;/i&gt; vector &amp; a result" in markup
    assert 'href="https://europepmc.org/article/MED/1" target="_blank" rel="noopener"' in markup
    assert "<i>AAV</i>" not in markup


def test_a_preprint_says_so_and_how_its_lab_was_matched():
    markup = V.alerts_html(GOT)
    assert "bioRxiv preprint, 2026-11-01" in markup
    assert "Ada Byron, ranked 12, published" in markup
    assert "lab matched by name only, one ranked lab of that name" in markup


def test_an_alert_whose_paper_has_left_the_table_prints_its_stored_headline():
    assert "<span>The stored headline</span>" in V.alerts_html(GOT)


def test_older_days_are_folded():
    markup = V.alerts_html(GOT, days_open=1)
    assert markup.count("<details") == 2 and markup.count('class="dsc-day"') == 1


def test_no_alert_gives_no_markup():
    assert V.alerts_html({"alerts": []}) == "" and V.alerts_html({}) == ""


def test_the_basis_says_what_the_ranks_stand_on():
    assert V.basis(GOT) == "Europe PMC read 2026-11-20 · 6,345 lab heads ranked 2026-11-14"
    assert V.basis({"basis": None}) == "" and V.basis({}) == ""


def test_the_papers_table_prints_ranks_and_what_raised_them():
    got = {"sort": "feas", "total": 120, "basis": GOT["basis"],
           "papers": [PAPER, {**PAPER, "id": "PPR:2", "lab": None, "company_author": None,
                              "stage_name": None, "reasons": None}]}
    table = V.papers_html(got)
    assert table.count("<tr>") == 3
    assert '<td class="n">1%</td><td class="n">40%</td>' in table
    assert "in patients, dose, durable" in table and "What raised feasibility" in table
    assert '<td class="n" title="Ada Byron">12</td>' in table
    assert "<td>yes</td>" in table and "<td></td>" in table
    assert "What raised commercial pull" in V.papers_html({**got, "sort": "comm"})
    assert V.papers_count(got) == "2 of 120" and V.papers_count({"total": 2, "papers": [1, 2]}) == "2"
    assert V.papers_html({"papers": []}) == ""
    assert V.held_line(got) == "3 papers held without an abstract, scored when one arrives."
    assert V.held_line({"basis": {"held_without_abstract": 0}}) == ""


def test_the_copy_keeps_the_house_style():
    """No em dash, none of the barred words, sentence case on every label."""
    table = V.papers_html({"sort": "feas", "total": 1, "papers": [PAPER]})
    labels = re.findall(r"<th[^>]*>([^<]+)</th>", table) + [label for _k, label in V.SORTS]
    fixed = [V.NOTE, *V.EMPTY_ALERTS, *V.NOT_READ_YET, V.held_line(GOT), V.basis(GOT),
             *labels, *re.findall(r'title="([^"]+)"', table)]
    generated = re.sub(r"<[^>]+>", " ", V.alerts_html(GOT))
    for text in fixed + [generated]:
        assert "—" not in text and "–" not in text, text
        assert not [w for w in BANNED if w in text.lower()], text
    for label in labels:
        words = label.replace(",", "").split()
        assert words[0][0].isupper() and all(w[0].islower() for w in words[1:]), label


def test_the_note_states_the_limits():
    note = V.NOTE
    assert "title and abstract only" in note and "not a finding" in note
    assert "name alone for a preprint" in note and "is not updated daily" in note
    assert "Nothing here moves a value" in note
