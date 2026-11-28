"""A row written outside the ledger takes a seed file's correction only when the adoption
register names it and it still holds the value the register says. Scratch book only."""

import assumptions as A
import db
import seed

HEADER = "ticker,brand,indication,region,scenario,key,year,value,text_value,unit,source,note\n"


def _book(tmp_path, value="0.10"):
    path = tmp_path / "adopt.db"
    db.init(path)
    seed.load_companies(path)
    conn = db.get_connection(path)
    cid = conn.execute("SELECT id FROM companies WHERE ticker = 'LLY'").fetchone()[0]
    conn.execute("INSERT INTO assets (owner_company_id, brand_name, is_marketed)"
                 " VALUES (?, 'Jardiance', 1)", (cid,))
    conn.commit()
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    _write(seeds, value)
    A.load_seeds(conn, seeds)
    return conn, seeds


def _write(seeds, value):
    (seeds / "lly_jardiance.csv").write_text(
        HEADER + f"LLY,Jardiance,,US,base,revenue_growth_pct,,{value},,annual,a filing,a note\n",
        encoding="utf-8")


def _held(conn):
    return conn.execute("SELECT value FROM assumptions WHERE key = 'revenue_growth_pct'").fetchone()[0]


def test_a_row_changed_outside_the_ledger_is_adopted_only_at_the_value_named(tmp_path, monkeypatch):
    conn, seeds = _book(tmp_path)
    conn.execute("UPDATE assumptions SET value = 0.027237 WHERE key = 'revenue_growth_pct'")
    conn.commit()
    _write(seeds, "0.483683")
    register = tmp_path / "adoptions.csv"
    monkeypatch.setattr(A, "ADOPTIONS", register)
    # No register: the row is nobody's and the file cannot correct it.
    assert A.reconcile_seeds(conn, seeds)["corrected"] == 0 and _held(conn) == 0.027237
    # A register naming another value: still left alone.
    register.write_text("ticker,brand,region,key,held_value,reason\n"
                        "LLY,Jardiance,US,revenue_growth_pct,0.5,why\n")
    assert A.reconcile_seeds(conn, seeds)["corrected"] == 0
    # The value the row holds: corrected once, after which the ledger owns it.
    register.write_text("ticker,brand,region,key,held_value,reason\n"
                        "LLY,Jardiance,US,revenue_growth_pct,0.027237,why\n")
    assert A.reconcile_seeds(conn, seeds)["corrected"] == 1 and _held(conn) == 0.483683
    assert A.reconcile_seeds(conn, seeds)["corrected"] == 0
