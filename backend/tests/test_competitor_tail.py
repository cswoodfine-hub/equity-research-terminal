"""A cliff behind a product goes on falling where a competitor is on the market, and holds
where nothing copies it. The engine treated both as flat for ever."""

import pytest

import assumptions
import competitors as C
import db
import forecast as F
from fetchers import exclusivity_purplebook as PB

DEFAULTS = {"small molecule": {"year1_pct": 0.71, "decay_pct": 0.31, "late_decay_pct": 0.23,
                               "late_from_year": 4, "tail_decay_pct": None, "source": "s"},
            "biologic": {"year1_pct": 0.25, "decay_pct": 0.25, "late_decay_pct": None,
                         "late_from_year": None, "tail_decay_pct": 0.08, "source": "s"}}
SELLING = {"kind": "generic", "since": "2023-07-31", "basis": "FDA Paragraph IV list"}


def _past(modality="small molecule", growth=0.0, competitor=None, share_abroad=0.5, **over):
    """A marketed product whose loss of exclusivity is three years behind the forecast."""
    scalars = {"therapy_mode": "marketed", "base_revenue": 1000.0, "revenue_growth_pct": growth,
               "wacc": 0.08, "forecast_start_year": 2026, "forecast_years": 10,
               "cogs_pct": 0.2, "sga_pct": 0.2, "rd_pct": 0.1, "tax_rate": 0.2, "pos": 1.0}
    scalars.update(over)
    return {"scalars": scalars, "indications": [], "is_marketed": True, "modality": modality,
            "loe": {"year": 2023, "basis": "generic marketed", "observed": True},
            "erosion_defaults": DEFAULTS, "competitor": competitor,
            # the rule is for the US share, so the product has to report one
            "regions": [{"region": "INTL", "label": "Outside the US", "share": share_abroad,
                         "year": None, "in_base": True, "basis": "expired"}]
            if share_abroad else []}


def test_a_line_goes_on_falling_at_the_tail_rate_and_never_slower():
    flat = F.continue_decline([100.0, 100.0, 100.0], 100.0, 0.10)
    assert flat == pytest.approx([90.0, 81.0, 72.9])
    rising = F.continue_decline([110.0, 121.0], 100.0, 0.10)
    assert rising == pytest.approx([90.0, 81.0])                # a rise is not kept
    # a fall steeper than the tail is the path's own, and the tail takes over after it
    steep = F.continue_decline([70.0, 56.0, 53.2, 53.2], 100.0, 0.10)
    assert steep == pytest.approx([70.0, 56.0, 50.4, 45.36])
    # with nothing reported before the path, its first year stands
    assert F.continue_decline([100.0, 100.0], None, 0.10) == pytest.approx([100.0, 90.0])


def test_the_terminal_value_of_a_falling_line_is_the_falling_stream():
    rate, tail = 0.08, 0.10
    multiple = F.terminal_multiple(0.0, rate, 2035, 2023, True, 0.71, 0.31, 0.23, 4, tail)
    assert multiple == pytest.approx((1 - tail) / (rate + tail))
    assert multiple < F.terminal_multiple(0.0, rate, 2035, 2023, True, 0.71, 0.31, 0.23, 4)
    path = F.terminal_path(0.0, 2035, 2023, True, 0.71, 0.31, 0.23, 4,
                           years=range(2036, 2400), tail=tail)
    assert path[2036] == pytest.approx(0.9) and path[2037] == pytest.approx(0.81)
    present = sum(f / (1 + rate) ** (y - 2035) for y, f in path.items())
    assert present == pytest.approx(multiple, rel=1e-6)          # the stream it discounts


def test_nothing_copying_it_and_the_product_holds_as_it_always_did():
    got = F.build(_past())
    assert got["loe_in_base"] is True and got["competitor_tail"] is None
    assert got["revenue_after_loe"] == pytest.approx([1000.0] * 10)
    assert all(len(part) == 3 for part in got["terminal_tail"]["parts"])


def test_a_competitor_on_the_market_and_the_us_line_goes_on_falling():
    held, falling = F.build(_past()), F.build(_past(competitor=SELLING))
    assert falling["competitor_tail"]["rate"] == pytest.approx(0.23)     # the late rate
    assert falling["revenue_after_loe"][0] == pytest.approx(500.0 + 500.0 * 0.77)
    assert falling["revenue_after_loe"][1] == pytest.approx(500.0 + 500.0 * 0.77 ** 2)
    us, abroad = falling["terminal_tail"]["parts"]
    assert us[3] == pytest.approx(0.23) and len(abroad) == 3
    assert falling["rnpv"] < held["rnpv"]
    assert any("goes on falling, never slower than 23% a year" in n
               for n in falling["notes"])
    # the terminal value of the US share is the falling stream, not a flat one
    assert falling["terminal_pv"] < held["terminal_pv"]


def test_a_biologic_takes_the_tail_rate_the_file_gives_it():
    got = F.build(_past(modality="biologic", competitor={**SELLING, "kind": "biosimilar"}))
    assert got["competitor_tail"]["rate"] == pytest.approx(0.08)
    assert got["revenue_after_loe"][:2] == pytest.approx([500.0 + 460.0, 500.0 + 423.2])
    # and a seed may state its own
    own = F.build(_past(modality="biologic", competitor=SELLING, erosion_tail_decay_pct=0.15))
    assert own["revenue_after_loe"][0] == pytest.approx(500.0 + 425.0)


def test_a_steeper_reported_fall_runs_first_and_the_tail_takes_over_from_it():
    """Stelara fell 41% in its first year of biosimilars. The model fades that to nil in
    five years; the line now fades to the tail rate and keeps it."""
    got = F.build(_past(modality="biologic", growth=-0.40, terminal_growth_pct=0.0,
                        growth_fade_years=5, competitor={**SELLING, "kind": "biosimilar"}))
    abroad = got["regions"][0]["revenue_after_loe"]
    revenue = [total - other for total, other in zip(got["revenue_after_loe"], abroad)]
    revenue = [v * 2 for v in revenue]                         # the US half, as a whole
    changes = [b / a - 1 for a, b in zip([1000.0] + revenue, revenue)]
    assert changes[0] == pytest.approx(-0.40)
    assert all(c <= -0.08 + 1e-9 for c in changes)
    assert changes[-1] == pytest.approx(-0.08)


def test_only_the_us_share_falls():
    """Symbicort earns 59% outside the United States, where the generic is not the
    question. The regions hold; the US share falls."""
    got = F.build(_past(competitor=SELLING, share_abroad=0.6))
    europe = got["regions"][0]["revenue_after_loe"]
    assert europe == pytest.approx([600.0] * 10)
    assert got["revenue_after_loe"][0] == pytest.approx(600.0 + 400.0 * 0.77)
    parts = got["terminal_tail"]["parts"]
    assert parts[0][3] == pytest.approx(0.23) and len(parts[1]) == 3


def test_a_line_with_no_split_on_file_is_not_made_to_fall():
    """The record is of the US market. With no regional split there is no US share to
    apply it to, and taking the whole line as American cut Yaz by 88%."""
    got = F.build(_past(competitor=SELLING, share_abroad=None))
    assert got["competitor_tail"] is None
    assert got["competitor_unsplit"] == {"kind": "generic", "since": "2023-07-31"}
    assert got["revenue_after_loe"] == pytest.approx([1000.0] * 10)
    assert any("US share of revenue is not on file" in n for n in got["notes"])
    assert F.build(_past(share_abroad=None))["competitor_unsplit"] is None


def test_a_cliff_still_ahead_is_untouched_by_a_competitor_record():
    inputs = _past(competitor=SELLING)
    inputs["loe"] = {"year": 2030, "basis": "patent"}
    ahead = F.build(inputs)
    inputs["competitor"] = None
    assert ahead["revenue_after_loe"] == F.build(inputs)["revenue_after_loe"]
    assert ahead["competitor_tail"] is None


def test_the_engine_is_told_only_where_a_competitor_is_selling(tmp_path):
    PURPLE = (
        "N/R/U,Applicant,BLA Number,Proprietary Name,Proper Name,License Type,Marketing Status,"
        "Approval Date,Ref. Product Proper Name,Ref. Product Proprietary Name\n"
        ',Amgen Inc.,761024,Amjevita,adalimumab-atto,351(k) Biosimilar,Rx,"April 6, 2023",'
        "adalimumab,Humira\n")
    path = tmp_path / "t.db"
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'ABBV', 'AbbVie')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, modality, is_marketed,"
                 " internal_code) VALUES (1, 1, 'Humira', 'biologic', 1, 'BLA125057'),"
                 " (2, 1, 'Botox', 'biologic', 1, 'BLA103000')")
    PB.write_biosimilars(conn, PB.parse_biosimilars(PURPLE))
    conn.commit()
    none = tmp_path / "none.csv"
    none.write_text("ticker,brand,loe,basis,note\n")
    launches = tmp_path / "launches.csv"
    launches.write_text(
        "ticker,product,market,kind,status,launched,accession,form,filed,quote,note\n"
        "ABBV,Humira,US,biosimilar,on the market,2023-01,0001551152-24-000011,10-K,"
        '2024-02-20,"direct biosimilar competition",\n')
    # licensed and listed is not selling
    assert C.selling(conn, 1, launches=none, disclosed=none) is None
    got = C.selling(conn, 1, launches=launches, disclosed=none)
    assert got["kind"] == "biosimilar" and got["since"] == "2023-01"
    assert "0001551152-24-000011" in got["basis"]
    assert C.selling(conn, 2, launches=launches, disclosed=none) is None    # nothing copies it
    assert C.selling(conn, 99, launches=launches, disclosed=none) is None
    conn.close()


def test_the_file_gives_a_biologic_its_tail_and_a_small_molecule_its_late_rate():
    rows = assumptions.erosion_defaults()
    assert rows["biologic"]["tail_decay_pct"] == pytest.approx(0.08)
    assert rows["biologic"]["late_decay_pct"] is None        # a cliff ahead keeps one rate
    assert rows["small molecule"]["tail_decay_pct"] is None
    assert rows["small molecule"]["late_decay_pct"] == pytest.approx(0.23)
