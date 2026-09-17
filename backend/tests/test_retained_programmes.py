"""A programme the seller kept is released from the acquirer, and nothing else is."""

import db
import retained_programmes as RP
import trial_mapping


def _db(tmp_path):
    path = str(tmp_path / "r.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (4, 'PFE', 'Pfizer')")
    conn.execute("INSERT INTO indications (id, name) VALUES (1, 'Spinocerebellar Ataxias')")
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                 " VALUES (3000, 4, 'troriluzole', 0)")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, generic_name,"
                 " is_marketed) VALUES (10, 4, 'Nurtec ODT', 'rimegepant', 1)")
    conn.execute("INSERT INTO asset_indications (asset_id, indication_id, phase)"
                 " VALUES (3000, 1, 'Phase 3')")
    for nct, asset, drug in (("NCT03701399", 3000, "troriluzole"),
                             ("NCT04649242", 10, "Rimegepant")):
        conn.execute("INSERT INTO trials (nct_id, sponsor_company_id, asset_id, phase,"
                     " lead_sponsor) VALUES (?, 4, ?, 'Phase 3',"
                     " 'Biohaven Pharmaceuticals, Inc.')", (nct, asset))
        for name in (drug, "Placebo"):
            conn.execute("INSERT INTO trial_interventions (nct_id, name, norm)"
                         " VALUES (?, ?, ?)", (nct, name, trial_mapping.normalise(name)))
    conn.commit()
    conn.close()
    return path


def _kept(tmp_path):
    path = tmp_path / "kept.csv"
    path.write_text("# c\nticker,programme,seller,accession,quote,note\n"
                    "PFE,Troriluzole,Biohaven Ltd,0000078003-25-000054,\"q\",\n")
    return path


def test_the_kept_programme_is_released_and_the_acquirers_own_drug_stays(tmp_path):
    path = _db(tmp_path)
    out = RP.release(path, _kept(tmp_path))
    assert out == {"released": 1, "pairs_removed": 1}
    conn = db.get_connection(path)
    trials = {r["nct_id"]: (r["sponsor_company_id"], r["asset_id"])
              for r in conn.execute("SELECT * FROM trials")}
    assert trials == {"NCT03701399": (None, None), "NCT04649242": (4, 10)}
    snap = conn.execute("SELECT entity_key, payload FROM snapshots").fetchone()
    assert snap["entity_key"] == "PFE:Troriluzole" and "NCT03701399" in snap["payload"]
    conn.close()
    assert trial_mapping.prune_orphan_pipeline_assets(path)["pruned"] == 1
    assert RP.release(path, _kept(tmp_path)) == {"released": 0, "pairs_removed": 0}
