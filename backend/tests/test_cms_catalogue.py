"""The CMS catalogue: years and dataset ids read from data.json, and the week-old disk
copy. The fixture is the live data.json (2026-10-05) cut to the Part D Prescribers
entries; no network."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

import cms_catalogue

_CATALOGUE = json.loads((Path(__file__).resolve().parent / "fixtures"
                         / "cms_catalogue_partd_prescribers.json").read_text())


def test_years_and_ids_of_a_series():
    provider = cms_catalogue.years(_CATALOGUE,
                                   "Medicare Part D Prescribers - by Provider and Drug")
    assert [r["year"] for r in provider] == [2019, 2020, 2021, 2022, 2023, 2024]
    newest = provider[-1]
    assert newest["uuid"] == "d5aa71a8-dcc0-4570-8bcf-bd39deac69fe"
    assert newest["latest_uuid"] == "9552739e-3d05-4c1b-8eff-ecabf391e2e5"
    assert provider[0]["latest_uuid"] is None
    # "2022-12-30" in the title; the year comes from the temporal period.
    assert provider[3]["year"] == 2022
    geography = cms_catalogue.years(_CATALOGUE,
                                    "Medicare Part D Prescribers - by Geography and Drug")
    assert geography[-1]["uuid"] == "9b4c142c-69cc-4a96-a09a-7cf2ba7f5816"


def test_a_title_that_only_starts_the_same_is_another_series():
    by_provider = cms_catalogue.years(_CATALOGUE, "Medicare Part D Prescribers - by Provider")
    assert [r["year"] for r in by_provider] == [2024]       # not the Provider and Drug years


def test_the_disk_copy_is_used_until_a_week_old_or_a_refresh(tmp_path):
    calls = []

    def download(url):
        calls.append(url)
        return json.dumps({"dataset": [], "n": len(calls)}).encode()

    first = cms_catalogue.load(get_bytes=download, cache_dir=tmp_path)
    again = cms_catalogue.load(get_bytes=download, cache_dir=tmp_path)
    assert first == again and len(calls) == 1
    fresh = cms_catalogue.load(refresh=True, get_bytes=download, cache_dir=tmp_path)
    assert fresh["n"] == 2
    old = time.time() - 8 * 24 * 60 * 60
    os.utime(tmp_path / cms_catalogue.CACHE_FILE, (old, old))
    assert cms_catalogue.load(get_bytes=download, cache_dir=tmp_path)["n"] == 3


def test_a_failed_download_falls_back_to_any_copy_and_raises_without_one(tmp_path):
    def fail(url):
        raise OSError("unreachable")

    with pytest.raises(OSError):
        cms_catalogue.load(get_bytes=fail, cache_dir=tmp_path)
    (tmp_path / cms_catalogue.CACHE_FILE).write_text(json.dumps({"dataset": [], "k": 1}))
    assert cms_catalogue.load(refresh=True, get_bytes=fail, cache_dir=tmp_path)["k"] == 1


_FORMULARY = json.loads((Path(__file__).resolve().parent / "fixtures"
                         / "cms_catalogue_formulary.json").read_text())
_MONTHLY = "Monthly Prescription Drug Plan Formulary and Pharmacy Network Information"


def test_downloads_list_a_file_only_series_oldest_first():
    releases = cms_catalogue.downloads(_FORMULARY, _MONTHLY)
    assert [r["title_date"] for r in releases] == [
        "2025-09-24", "2026-07-29", "2026-08-26", "2026-09-23"]
    newest = releases[-1]
    assert newest["url"].endswith("/2026_20260916.zip")
    assert newest["start"] == "2026-09-01" and newest["modified"] == "2026-09-23"
    # The quarterly file is another series, and the API-only reader sees none of them.
    assert all("SPUF" not in r["url"] for r in releases)
    assert cms_catalogue.years(_FORMULARY, _MONTHLY) == []
