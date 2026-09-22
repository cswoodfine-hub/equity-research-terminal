"""China-linked business development, off deals already stored.

The whole difficulty is precision and direction. Of the 1,115 stored rows, 21 mention
China and 6 of those are about somebody else entirely, and of the rest the direction
cannot be read from the headline at all.
"""

import pytest

import db
import deals


def _seed(tmp_path, name, rows):
    path = str(tmp_path / name)
    db.init(path)
    conn = db.get_connection(path)
    for cid, ticker, company in ((1, "PFE", "Pfizer Inc"),
                                 (2, "BMRN", "BioMarin Pharmaceutical Inc"),
                                 (3, "KRYS", "Krystal Biotech, Inc.")):
        conn.execute("INSERT INTO companies (id, ticker, name) VALUES (?, ?, ?)",
                     (cid, ticker, company))
    for i, (cid, deal_type, counterparty, date, quote, value, accession) in enumerate(
            rows, start=1):
        # headline_usd is the parsed figure; announced_value is the phrase a release
        # used, which is often a phrase and nothing more.
        phrase = value if isinstance(value, str) else None
        number = value if isinstance(value, (int, float)) else None
        conn.execute(
            """INSERT INTO deals (id, company_id, deal_type, counterparty, event_date,
                                  quote, announced_value, headline_usd, accession,
                                  source_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'u')""",
            (i, cid, deal_type, counterparty, date, quote, phrase, number, accession))
    conn.commit()
    return conn


def test_a_china_rights_headline_is_counted_once(tmp_path):
    conn = _seed(tmp_path, "one.db", [
        (1, "licensing", "3SBio, Inc.", "2025-08-05",
         "Pfizer announced an exclusive global, ex-China, in-licensing agreement with "
         "3SBio, Inc.", None, "0000078003-25-000001"),
    ])
    got = deals.china_linked(conn, "PFE")
    conn.close()
    assert got["count"] == 1
    assert got["deals"][0]["counterparty"] == "3SBio, Inc."
    assert got["evidence"] if False else got["deals"][0]["evidence"] == "filing"


def test_a_headline_naming_no_china_is_not_counted(tmp_path):
    conn = _seed(tmp_path, "none.db", [
        (1, "licensing", "Somebody Ltd", "2025-08-05",
         "Pfizer announced an exclusive in-licensing agreement with Somebody Ltd",
         None, "0000078003-25-000001"),
    ])
    got = deals.china_linked(conn, "PFE")
    conn.close()
    assert got["count"] == 0
    assert got["announced_value_total"] is None


def test_a_headline_about_another_company_is_refused(tmp_path):
    """Two copies of "Amoytop Acquires Skyline To Kickstart China 2025 M&A Activity"
    are stored, one under BioMarin and one under Regenxbio. Neither is their deal."""
    conn = _seed(tmp_path, "other.db", [
        (2, "acquisition", "Skyline", "2025-01-02",
         "Amoytop Acquires Skyline To Kickstart China 2025 M&A Activity", None, None),
    ])
    got = deals.china_linked(conn, "BMRN")
    conn.close()
    assert got["count"] == 0
    assert len(got["refused"]) == 1
    assert "does not name this company" in got["refused"][0]["why"]


def test_a_generic_word_in_a_company_name_does_not_match(tmp_path):
    """Matching on "biotech" put "US lawmakers reveal policy to curb collaboration with
    Chinese biotech" on Krystal Biotech."""
    conn = _seed(tmp_path, "generic.db", [
        (3, "collaboration", "Chinese", "2025-03-01",
         "US lawmakers reveal policy to curb collaboration with Chinese biotech",
         None, None),
    ])
    got = deals.china_linked(conn, "KRYS")
    conn.close()
    assert got["count"] == 0
    assert deals._own_words("Krystal Biotech, Inc.") == ["krystal"]
    assert deals._own_words("BioMarin Pharmaceutical Inc") == ["biomarin"]


def test_a_filing_row_needs_no_name_because_it_is_already_this_company(tmp_path):
    """A filing-sourced row says "the Company". Requiring the name would drop Biogen's
    TJ Biopharma agreement and Pfizer's 3SBio one, which are both real."""
    conn = _seed(tmp_path, "filed.db", [
        (1, "licensing", "TJ Biopharma", "2026-04-29",
         "Nephrology franchise further enhanced by agreement with TJ Biopharma to "
         "acquire exclusive rights in China", None, "0000078003-26-000002"),
    ])
    got = deals.china_linked(conn, "PFE")
    conn.close()
    assert got["count"] == 1 and got["deals"][0]["evidence"] == "filing"


def test_a_divestiture_is_dropped_because_rights_go_the_other_way(tmp_path):
    conn = _seed(tmp_path, "div.db", [
        (1, "divestiture", "Sanofi", "2025-11-25",
         "Pfizer signed an asset purchase agreement covering its China joint venture",
         None, None),
    ])
    got = deals.china_linked(conn, "PFE")
    conn.close()
    assert got["count"] == 0
    assert "divestiture" in got["refused"][0]["why"]


def test_two_headlines_on_one_day_are_one_deal_and_the_priced_one_wins(tmp_path):
    """Novartis and Argo arrived twice on 2025-09-03, once with the figure and once
    without. The counterparty cannot dedupe them: it is "RNA" on one row."""
    conn = _seed(tmp_path, "dupe.db", [
        (1, "licensing", "RNA", "2025-09-03",
         "Pfizer licenses RNA drugs in deal with China-based Argo", None, None),
        (1, "licensing", "China's", "2025-09-03",
         "Pfizer signs up to $5.2 billion licensing deal with China's biotech Argo",
         "up to $5.2 billion", None),
    ])
    got = deals.china_linked(conn, "PFE")
    conn.close()
    assert got["count"] == 1
    assert got["deals"][0]["announced_value"] == "up to $5.2 billion"
    # The phrase is kept verbatim and nothing is parsed out of it.
    assert got["deals"][0]["headline_usd"] is None


def test_a_missing_value_makes_the_sum_null_rather_than_partial(tmp_path):
    """A partial sum of announced consideration reads as a total and is not one."""
    conn = _seed(tmp_path, "sum.db", [
        (1, "licensing", "Argo", "2025-09-03",
         "Pfizer signs licensing deal with China's Argo", 5_200_000_000, None),
        (1, "licensing", "Sciwind", "2026-05-05",
         "Pfizer and Hangzhou Sciwind Biosciences announced a collaboration",
         None, None),
    ])
    got = deals.china_linked(conn, "PFE")
    assert got["count"] == 2 and got["priced"] == 1
    assert got["announced_value_total"] is None
    conn.close()

    conn = _seed(tmp_path, "sum2.db", [
        (1, "licensing", "Argo", "2025-09-03",
         "Pfizer signs licensing deal with China's Argo", 5_200_000_000, None),
        (1, "licensing", "Sciwind", "2026-05-05",
         "Pfizer and Hangzhou Sciwind Biosciences announced a China collaboration",
         1_000_000_000, None),
    ])
    got = deals.china_linked(conn, "PFE")
    conn.close()
    assert got["announced_value_total"] == pytest.approx(6.2e9)


def test_the_direction_is_never_claimed(tmp_path):
    """Alnylam's "Exclusive Agreement with BeOne Medicines for Commercialization of
    AMVUTTRA in China" is Alnylam licensing out, and it reads exactly like an agreement
    with a Chinese party. A headline does not state which way the rights went."""
    conn = _seed(tmp_path, "dir.db", [
        (1, "licensing", "BeOne Medicines", "2026-07-30",
         "Pfizer Entered Into an Exclusive Agreement with BeOne Medicines for "
         "Commercialization of a product in China", None, None),
    ])
    got = deals.china_linked(conn, "PFE")
    conn.close()
    assert got["count"] == 1
    assert got["direction_stated"] is False
    assert not any("in_licens" in k or "inbound" in k for k in got["deals"][0])
