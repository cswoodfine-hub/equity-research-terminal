"""The refresh's mapping block, with no fetches: aliases, trial overrides, merges,
indications. Mirrors backend/refresh.py _run_refresh between the fetchers and the seeds."""
import sys
sys.path.insert(0, "backend")
import db
import acquired_sponsors, retained_programmes, trial_mapping, molecules
from fetchers import product_revenue_sec
import asset_merge, asset_identity, indication_mapping
import curated_register, discontinued
p = db.DB_PATH
out = {}
for name, fn in (("release_acq", lambda: acquired_sponsors.release(p)),
                 ("release_ret", lambda: retained_programmes.release(p)),
                 ("derive", lambda: trial_mapping.derive_pipeline_assets(p)),
                 ("molecules", lambda: molecules.assign(p)),
                 ("map", lambda: trial_mapping.map_trials(p)),
                 ("prune", lambda: trial_mapping.prune_orphan_pipeline_assets(p)),
                 ("rev_prune", lambda: product_revenue_sec.prune(p)),
                 ("merge", lambda: asset_merge.merge(p)),
                 ("arms", lambda: trial_mapping.prune_arms(p)),
                 ("identity", lambda: asset_identity.fill(p)),
                 ("molecules2", lambda: molecules.assign(p)),
                 ("indications", lambda: indication_mapping.build(p)),
                 ("register", lambda: curated_register.apply(p)),
                 ("discontinued", lambda: discontinued.apply(p))):
    try:
        r = fn()
        out[name] = {k: v for k, v in (r or {}).items() if isinstance(v, (int, float))} if isinstance(r, dict) else r
    except Exception as exc:
        out[name] = f"ERROR {type(exc).__name__}: {exc}"
for k, v in out.items():
    print(k, v)
