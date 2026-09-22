"""What currency basis a company guided on, and why the lens will not guess it.

fair_value.guidance applies a growth guide to the prior year's reported revenue. That
is right for a company guiding on a reported basis and wrong for one guiding at
constant exchange rates, and the code used to know the difference and do nothing with
it: it grepped the note for "constant", then used the answer only to append a caption
to a number computed the same way either way.
"""

import csv
import pathlib

import pytest

import consensus
import db
import fair_value
import fx

SEED = pathlib.Path(__file__).resolve().parents[2] / "data" / "consensus" / "guidance_2026.csv"


def _seed_rows():
    lines = [l for l in SEED.read_text().split("\n")
             if l.strip() and not l.startswith("#")]
    rows = list(csv.reader(lines))
    header = rows[0]
    return header, [dict(zip(header, r)) for r in rows[1:]]


def test_every_seeded_basis_is_one_of_the_three_or_blank():
    """Three values and a null, which are the four cases the twelve releases contain.
    SQLite cannot add a CHECK with ALTER TABLE, so this is where the enumeration is
    pinned."""
    header, rows = _seed_rows()
    assert "fx_basis" in header
    assert len(rows) == 12
    for row in rows:
        basis = (row["fx_basis"] or "").strip()
        assert basis == "" or basis in consensus.FX_BASES, row["ticker"]
    assert consensus.FX_BASES == {"cer", "reported",
                                  "reported_with_stated_rate_date"}


def test_each_basis_is_the_one_its_own_sentence_states():
    """Transcription, not extraction. Every value has to be readable in the note
    stored beside it, which is what makes twelve rows of hand-entry safe."""
    _header, rows = _seed_rows()
    by_ticker = {r["ticker"]: r for r in rows}

    for ticker, needle in (("AZN", "at cer"), ("NVO", "at cer"), ("SNY", "at cer"),
                           ("NVS", "in cc")):
        assert by_ticker[ticker]["fx_basis"] == "cer"
        assert needle in by_ticker[ticker]["note"].lower(), ticker

    assert by_ticker["AMGN"]["fx_basis"] == "reported"
    assert "reported usd" in by_ticker["AMGN"]["note"].lower()
    assert by_ticker["GILD"]["fx_basis"] == "reported"
    assert "reported usd" in by_ticker["GILD"]["note"].lower()

    # Both name the rates assumed, which is what separates these from plain reported.
    assert by_ticker["MRK"]["fx_basis"] == "reported_with_stated_rate_date"
    assert "mid-july 2026 exchange rates" in by_ticker["MRK"]["note"].lower()
    assert by_ticker["BIIB"]["fx_basis"] == "reported_with_stated_rate_date"
    assert "as of july 24, 2026" in by_ticker["BIIB"]["note"].lower()


def test_the_blank_rows_are_blank_because_the_release_says_nothing():
    """Three guide no revenue at all and one names no currency basis. A blank here is
    a fact about the release, not a gap somebody forgot to fill."""
    _header, rows = _seed_rows()
    by_ticker = {r["ticker"]: r for r in rows}
    for ticker in ("ABBV", "REGN", "UTHR", "INCY"):
        assert (by_ticker[ticker]["fx_basis"] or "") == "", ticker
    assert "no revenue guidance" in by_ticker["ABBV"]["note"].lower()
    assert "no revenue guidance" in by_ticker["REGN"]["note"].lower()
    assert "no full-year 2026 financial guidance" in by_ticker["UTHR"]["note"].lower()


def _guided(tmp_path, name, metric, value, basis, note="a sentence"):
    path = str(tmp_path / name)
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'SNY', 'Sanofi')")
    conn.execute(
        """INSERT INTO consensus_estimates (company_id, metric, period, value, currency,
                                            source, as_of, note, fx_basis)
           VALUES (1, ?, 'FY2026', ?, 'EUR', 'guidance', '2026-07-30', ?, ?)""",
        (metric, value, note, basis))
    conn.commit()
    return conn


def test_a_constant_currency_growth_draws_no_lens(tmp_path):
    """Sanofi guiding around 10% at CER is not guiding 10% reported, and the
    difference is whatever the euro did. Before this the lens applied it anyway and put
    Sanofi at 63.48 a share on the football field."""
    conn = _guided(tmp_path, "cer.db", "RevenueGrowth", 10.0, "cer")
    got = fair_value.guidance(conn, 1, 2026, prior_revenue=40e9, unit="EUR")
    conn.close()
    assert "reason" in got and "constant exchange rates" in got["reason"]
    assert "mid" not in got


def test_a_growth_with_no_stated_basis_draws_no_lens_either(tmp_path):
    """GSK's stored sentence is a bare "turnover growth of between 3% to 5%". That GSK
    guides at constant currency is something a reader knows, not something the file
    records, and guessing it is how a fabricated value gets into a fair value."""
    conn = _guided(tmp_path, "null.db", "RevenueGrowth", 4.0, None)
    got = fair_value.guidance(conn, 1, 2026, prior_revenue=40e9, unit="EUR")
    conn.close()
    assert "reason" in got and "states no currency basis" in got["reason"]


def test_a_reported_growth_still_draws_its_lens(tmp_path):
    conn = _guided(tmp_path, "rep.db", "RevenueGrowth", 10.0, "reported")
    got = fair_value.guidance(conn, 1, 2026, prior_revenue=40e9, unit="EUR")
    conn.close()
    assert got["mid"] == pytest.approx(40e9 / 1e6 * 1.10)
    assert "on a reported basis" in got["basis"]
    assert "exchange rates the release names" not in got["basis"]


def test_a_reported_growth_with_a_stated_rate_date_says_so(tmp_path):
    conn = _guided(tmp_path, "dated.db", "RevenueGrowth", 5.0,
                   "reported_with_stated_rate_date")
    got = fair_value.guidance(conn, 1, 2026, prior_revenue=40e9, unit="EUR")
    conn.close()
    assert got["mid"] == pytest.approx(40e9 / 1e6 * 1.05)
    assert "at the exchange rates the release names" in got["basis"]


def test_an_absolute_guide_is_untouched_by_the_basis(tmp_path):
    """A dollar figure is the reported figure. The constant-currency problem exists
    only for a growth rate, so an absolute guide is not withheld for lacking a basis."""
    conn = _guided(tmp_path, "abs.db", "Revenue", 46e9, None)
    got = fair_value.guidance(conn, 1, 2026, prior_revenue=40e9, unit="EUR")
    conn.close()
    assert got["mid"] == pytest.approx(46e3)
    assert got["fx_basis"] is None


def test_the_loader_refuses_a_basis_that_is_not_one_of_the_three(tmp_path):
    """A typo in the seed stops the load rather than becoming a fourth silent value
    that the lens would then read as "not cer" and let through."""
    folder = tmp_path / "seeds"
    folder.mkdir()
    (folder / "bad.csv").write_text(
        "ticker,metric,period,value,low,high,currency,source,as_of,note,fx_basis\n"
        "SNY,RevenueGrowth,FY2026,10,,,EUR,guidance,2026-07-30,x,constant_currency\n")
    path = str(tmp_path / "loader.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'SNY', 'Sanofi')")
    conn.commit()
    with pytest.raises(ValueError, match="fx_basis"):
        consensus.load_seeds(conn, folder)
    conn.close()


def test_a_rate_date_the_history_does_not_reach_has_no_level(tmp_path):
    """Novartis guided on 2026-07-21 and the ECB set stored here starts 2026-07-24, so
    there is no rate on file for the day that guide was struck. It reads as absent
    rather than being given the nearest one: a basis date is not an invitation to
    substitute a rate from a different day."""
    path = str(tmp_path / "rate.db")
    db.init(path)
    fx.store(path, "2026-07-24", {"EUR": 1.1377, "CHF": 1.2516, "USD": 1.0})
    assert fx.rates_on(path, "2026-07-21") == {}
    assert fx.rates_on(path, "2026-07-24")["as_of"] == "2026-07-24"
