"""The CMS data catalogue (data.json), read for the dataset ids each year carries.

data.cms.gov publishes one dataset per data year, and each has its own API id; a year is
never keyed by hand. The catalogue that lists them, https://data.cms.gov/data.json, is
17.7 MB, so it is kept on disk and read again only once it is a week old, or when a
caller has seen a sign of a new release and asks for a fresh copy. Shared by the CMS
fetchers, so that none imports another.

A dataset title is "<series title> : <date>", and its year is the start of its temporal
period ("Medicare Part D Prescribers - by Provider and Drug : 2024-12-01" covers
2024-01-01 to 2024-12-31). Each year lists an API distribution pinned to that year, and
the newest year also lists one described "latest", which is the series id: it moves to
the next year when CMS publishes one.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from pathlib import Path

CATALOGUE_URL = "https://data.cms.gov/data.json"
CACHE_DIR = Path(os.getenv("ER_TOOL_CACHE",
                           Path(__file__).resolve().parent / "cache"))
CACHE_FILE = "cms_data.json"
MAX_AGE_S = 7 * 24 * 60 * 60
_USER_AGENT = "Novatalis Research cswoodfine@icloud.com"
_TIMEOUT_S = 180
_UUID = re.compile(r"/dataset/([0-9a-f-]{36})/")


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
        return resp.read()


def load(refresh: bool = False, get_bytes=None, cache_dir: Path | None = None,
         max_age_s: float = MAX_AGE_S) -> dict:
    """The catalogue, from the disk copy when it is under a week old.

    refresh=True fetches it whatever the copy's age. A download that fails falls back to
    a copy of any age, since an old list of years is still a list of years; with no copy
    at all the error stands.
    """
    folder = Path(cache_dir) if cache_dir is not None else CACHE_DIR
    path = folder / CACHE_FILE
    fresh = path.exists() and (time.time() - path.stat().st_mtime) < max_age_s
    if fresh and not refresh:
        return json.loads(path.read_text())
    try:
        body = (get_bytes or _download)(CATALOGUE_URL)
        parsed = json.loads(body)
    except Exception:
        if path.exists():
            return json.loads(path.read_text())
        raise
    folder.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(body if isinstance(body, bytes) else json.dumps(parsed).encode())
    tmp.replace(path)
    return parsed


def _uuid(url: str | None) -> str | None:
    match = _UUID.search(url or "")
    return match.group(1) if match else None


def years(catalogue: dict, series_title: str) -> list[dict]:
    """[{year, uuid, latest_uuid, modified}] for every dataset of one series, oldest first.

    uuid is the API id pinned to the year; latest_uuid is the series id, carried only by
    the newest year. A title that merely starts the same way ("... by Provider" against
    "... by Provider and Drug") is not the series.
    """
    out = []
    for dataset in (catalogue or {}).get("dataset") or []:
        title = dataset.get("title") or ""
        head, sep, tail = title.rpartition(" : ")
        if not sep or head.strip() != series_title:
            continue
        temporal = dataset.get("temporal") or []
        start = (temporal[0] or {}).get("startDate") if temporal else None
        year_text = (start or tail.strip())[:4]
        if not year_text.isdigit():
            continue
        pinned = latest = None
        for dist in dataset.get("distribution") or []:
            if dist.get("format") != "API":
                continue
            uuid = _uuid(dist.get("accessURL"))
            if (dist.get("description") or "").strip().lower() == "latest":
                latest = uuid
            elif uuid:
                pinned = uuid
        if pinned or latest:
            out.append({"year": int(year_text), "uuid": pinned or latest,
                        "latest_uuid": latest, "modified": dataset.get("modified")})
    out.sort(key=lambda r: r["year"])
    return out


def downloads(catalogue: dict, series_title: str, media_format: str = "ZIP") -> list[dict]:
    """[{title_date, start, modified, url}] for every file release of one series, oldest
    first.

    Some series publish a file and no API: the monthly Part D formulary is one ZIP a
    month ("Monthly Prescription Drug Plan Formulary and Pharmacy Network Information :
    2026-09-23"), and years() reads API distributions only. title_date is the date in the
    title, start the start of the temporal period, url the distribution's downloadURL.
    """
    out = []
    for dataset in (catalogue or {}).get("dataset") or []:
        title = dataset.get("title") or ""
        head, sep, tail = title.rpartition(" : ")
        if not sep or head.strip() != series_title:
            continue
        temporal = dataset.get("temporal") or []
        start = (temporal[0] or {}).get("startDate") if temporal else None
        for dist in dataset.get("distribution") or []:
            if (dist.get("format") or "").upper() != media_format.upper():
                continue
            if not dist.get("downloadURL"):
                continue
            out.append({"title_date": tail.strip(), "start": start,
                        "modified": dist.get("modified") or dataset.get("modified"),
                        "url": dist["downloadURL"]})
    out.sort(key=lambda r: (r["title_date"], r["url"]))
    return out
