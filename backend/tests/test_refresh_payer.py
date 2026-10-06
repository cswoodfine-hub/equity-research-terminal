"""The payer stage of the universe refresh: the drug codes, Part D Prescribers, Medicaid
SDUD and Part D formulary fetchers run once each, in that order, after the asset rows
are final and before the diff, with the run's force and id. A dry wiring test: the
universe and company downloads are switched off and the four fetchers are probes, so
nothing here touches the network."""

from __future__ import annotations

import inspect
import json

import db
import refresh
from fetchers.base import BaseFetcher
from fetchers.codes_rxnav import DrugCodesRxNavFetcher
from fetchers.deals_news import DealsNewsFetcher
from fetchers.formulary_cms import PartDFormularyFetcher
from fetchers.prescribers_cms import PartDPrescribersFetcher
from fetchers.utilization_medicaid import MedicaidSdudFetcher

PAYER = (DrugCodesRxNavFetcher, PartDPrescribersFetcher, MedicaidSdudFetcher,
         PartDFormularyFetcher)


def _probe(name, log):
    class Probe(BaseFetcher):
        source = name
        ttl_seconds = 0

        @property
        def entity_key(self):
            return name

        def fetch(self):
            log.append((name, self.force, self.refresh_run_id))
            return []

        def normalise(self, raw):
            return []

        def snapshot(self, rows):
            pass

        def _snapshot_cache(self):
            pass

        def upsert(self, rows):
            from fetchers.base import RefreshResult
            return RefreshResult(name, 0)

    return Probe


def _harness(tmp_path, monkeypatch, payer):
    """An empty book, no downloads, and an order log of the stages around the payer
    one: the brand split (the last step that moves asset rows), the deals headlines and
    the diff."""
    path = str(tmp_path / "t.db")
    db.init(path)
    log: list = []
    monkeypatch.setattr(refresh, "_universe_fetchers", lambda db_path: [])
    monkeypatch.setattr(refresh, "_payer_fetchers", lambda db_path: payer(db_path, log))
    monkeypatch.setattr(DealsNewsFetcher, "fetch",
                        lambda self: {"feeds": {}, "companies": [], "errors": []})
    split, detect, deals_run = (refresh.brand_split.split, refresh.diff.detect_changes,
                                DealsNewsFetcher.run)

    def logged_split(db_path):
        log.append(("brand_split",))
        return split(db_path)

    def logged_detect(db_path, run_id):
        log.append(("diff",))
        return detect(db_path, run_id)

    def logged_deals(self):
        log.append(("deals_news",))
        return deals_run(self)

    monkeypatch.setattr(refresh.brand_split, "split", logged_split)
    monkeypatch.setattr(refresh.diff, "detect_changes", logged_detect)
    monkeypatch.setattr(DealsNewsFetcher, "run", logged_deals)
    return path, log


def test_the_four_payer_fetchers_codes_first(tmp_path):
    path = str(tmp_path / "t.db")
    db.init(path)
    assert [type(f) for f in refresh._payer_fetchers(path)] == list(PAYER)


def test_they_run_after_the_asset_rows_settle_and_before_the_diff(tmp_path, monkeypatch):
    names = ("rxnav_codes", "partd_prescribers", "medicaid_sdud", "partd_formulary")

    def payer(db_path, log):
        return [_probe(n, log)(db_path) for n in names]

    path, log = _harness(tmp_path, monkeypatch, payer)
    run = refresh.run_refresh_all(path, force=True)
    stages = [entry[0] for entry in log]
    assert stages == ["brand_split", *names, "deals_news", "diff"]
    # Each ran once, forced, under this run's id, and reported into its detail.
    assert {entry[1:] for entry in log if entry[0] in names} == {(True, run["id"])}
    reported = {s["source"]: s for s in run["detail"]["sources"]}
    assert all(reported[n]["ran"] == 1 for n in names)
    assert run["status"] == "complete"


def test_an_unforced_run_passes_force_false(tmp_path, monkeypatch):
    def payer(db_path, log):
        return [_probe("rxnav_codes", log)(db_path)]

    path, log = _harness(tmp_path, monkeypatch, payer)
    refresh.run_refresh_all(path)
    assert [e for e in log if e[0] == "rxnav_codes"][0][1] is False


def test_a_failing_payer_fetcher_makes_the_run_partial_with_an_error_snapshot(
        tmp_path, monkeypatch):
    def unreachable(refresh=False):
        raise RuntimeError("data.cms.gov did not answer")   # not retried as transient

    def payer(db_path, log):
        return [PartDFormularyFetcher(db_path, load_catalogue=unreachable)]

    path, log = _harness(tmp_path, monkeypatch, payer)
    run = refresh.run_refresh_all(path, force=True)
    assert run["status"] == "partial"
    formulary = next(s for s in run["detail"]["sources"] if s["source"] == "partd_formulary")
    assert "did not answer" in formulary["errors"][0]
    conn = db.get_connection(path)
    try:
        payload = json.loads(conn.execute(
            "SELECT payload FROM snapshots WHERE source = 'partd_formulary'"
            " ORDER BY id DESC LIMIT 1").fetchone()["payload"])
    finally:
        conn.close()
    assert payload["fetch_kind"] == "error"
    # The rest of the run still finished: the diff ran after it.
    assert log[-1] == ("diff",)


def test_a_single_company_refresh_never_starts_a_payer_pull(tmp_path):
    path = str(tmp_path / "t.db")
    db.init(path)
    company = {"ticker": "LLY", "cik": "59478", "lei": None, "is_sec_filer": 1,
               "ir_rss_url": None, "ir_news_url": None}
    assert not [f for f in refresh._company_fetchers(company, path) if isinstance(f, PAYER)]
    assert not [f for f in refresh._universe_fetchers(path) if isinstance(f, PAYER)]
    assert "_payer_fetchers" not in inspect.getsource(refresh._run_refresh)
