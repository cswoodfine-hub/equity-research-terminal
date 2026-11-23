"""One summary of whether a run was normal, written into the run's own record.

A run finishes "complete" or "partial", and partial is what 106 of the first 143
committed runs said: a press page that refuses one company makes a run partial, and so
does a model that refuses every call. The word stopped carrying anything, and what it
hid sat further down the detail where nobody was looking. Read back on 2026-11-23:

* the readers that pull PDUFA dates, guidance and readouts out of filings had not read
  one filing in a scheduled run. Until 2026-11-09 no key was set; from that day every
  call was answered 404, and each reader still reported ``"status": "ok"``;
* every run from 2026-10-10 began between 10:26 and 18:14 UTC against a 06:00 schedule,
  several of them while the US market was trading;
* three Medicare and Medicaid sources were reported "gone quiet" on every run from
  2026-10-30, which was their release guards working (see ``fetchers.base.run``).

So the run says it in one place. ``summarise`` is pure: it is handed what the run
already knows and decides nothing the run did not measure.

What makes a run abnormal, and what does not:

* the hour it began does not. The start, whether it fell inside the US regular session,
  and when the scheduled job itself began are in the summary and in its line on every
  run, and none of them makes a run abnormal. The owner's decision of 2026-11-23. A
  mid-session start used to file an intraday price as that day's close; the price and
  benchmark fetchers now hold back the bar of a session still trading
  (``market_session.py``), so the start no longer damages the record, and the hosted
  runner starts late on most weekdays, so a line that called it abnormal would say so
  most days. The session is weekday hours only: this module holds no exchange calendar,
  so a market holiday reads as a session;
* a source fetched nothing and erred on every attempt. A source that erred for one
  company of seventy-five is listed and does not by itself make the run abnormal,
  because one has done so on almost every run since August and a line that says
  abnormal every day is the word "partial" again;
* a source has been quiet for ``QUIET_RUNS`` runs in a row (``refresh.went_quiet``).
  A shorter spell is listed and is not abnormal: most are a quiet day at the source;
* a reader's every model call failed, or no model is configured at all.
"""

from __future__ import annotations

import datetime as dt

_STAMP = "%Y-%m-%d %H:%M:%S"          # the shape of datetime('now'), always UTC
US_OPEN, US_CLOSE = dt.time(9, 30), dt.time(16, 0)
US_ZONE = "America/New_York"
# How many runs in a row a source may return nothing before the run is called abnormal.
# Measured on the committed log to 2026-11-23, leaving out the sources that hold a
# release guard: of the 33 quiet spells that ended by themselves, 31 lasted one or two
# runs, and the other two (three and five runs) were gaps in the pulse feed, which are
# worth a notice. The Purple Book fault this guards against ran for weeks.
QUIET_RUNS = 3


def parse_utc(stamp) -> dt.datetime | None:
    """A ``refresh_runs.started_at`` as an aware UTC datetime, or None."""
    if isinstance(stamp, dt.datetime):
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=dt.timezone.utc)
    try:
        return dt.datetime.strptime(str(stamp)[:19], _STAMP).replace(
            tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def in_us_session(started: dt.datetime | None) -> bool | None:
    """True where ``started`` falls in the US regular session, 09:30 to 16:00 New York
    on a weekday. None where it cannot be worked out, which is not the same as no."""
    if started is None:
        return None
    try:
        from zoneinfo import ZoneInfo
        local = started.astimezone(ZoneInfo(US_ZONE))
    except Exception:                  # no time zone data on this machine
        return None
    return local.weekday() < 5 and US_OPEN <= local.time() < US_CLOSE


def _source_rows(sources) -> list[dict]:
    """Each source as {source, rows, errors, attempts}, from either shape a run holds:
    the universe run's per-source totals or one company's list of results."""
    rows = []
    for s in sources or []:
        ran = int(s.get("ran", 1) or 0)
        skipped = int(s.get("skipped_ttl") or 0)
        rows.append({"source": s.get("source"),
                     "rows": int(s.get("rows_fetched") or 0),
                     "errors": len(s.get("errors") or []),
                     "attempts": max(ran - skipped, 0)})
    return rows


def summarise(started_at, sources, quiet=None, readers=None, model=None,
              job_started_at=None, no_model=None) -> dict:
    """The health summary for one finished run.

    ``sources`` is the run's source list as it goes into the detail. ``quiet`` is what
    ``refresh.went_quiet`` returned. ``readers`` maps a reader's name to the count the
    model seam kept for it (``llm.Count.as_dict``). ``model`` is the provider the run
    had, or None where it had none, and ``no_model`` is then why, in the seam's words
    (``llm.reader_gap``). ``job_started_at`` is when the scheduled job itself began,
    where the schedule says (``ER_JOB_STARTED_AT``).
    """
    started = parse_utc(started_at)
    session = in_us_session(started)
    quiet_runs = {q["source"]: int(q.get("quiet_runs") or 1) for q in quiet or []}
    quiet_names = sorted(quiet_runs)
    quiet_long = [n for n in quiet_names if quiet_runs[n] >= QUIET_RUNS]

    erred, failed = [], []
    for row in _source_rows(sources):
        # A quiet source carries the error went_quiet wrote on it; it is counted once,
        # as quiet.
        if not row["errors"] or row["source"] in quiet_names:
            continue
        nothing = row["rows"] == 0 and row["errors"] >= max(row["attempts"], 1)
        erred.append({"source": row["source"], "errors": row["errors"],
                      "attempts": row["attempts"], "fetched_nothing": nothing})
        if nothing:
            failed.append(row["source"])

    asked, readers_failed = [], []
    for name, count in (readers or {}).items():
        calls, bad = int(count.get("calls") or 0), int(count.get("failed") or 0)
        if not calls:
            continue
        entry = {"reader": name, "calls": calls, "failed": bad}
        if bad:
            entry["error"] = count.get("last_error")
        asked.append(entry)
        if bad == calls:
            readers_failed.append(name)

    # The hour is stated in the line and is never a reason: see the module docstring.
    reasons = []
    clock = started.strftime("%H:%M") if started else "an unknown hour"
    job = parse_utc(job_started_at)
    if failed:
        reasons.append(f"{len(failed)} source{'s' if len(failed) != 1 else ''} fetched "
                       f"nothing and erred: {', '.join(failed)}")
    if quiet_long:
        reasons.append(
            f"{len(quiet_long)} source{'s' if len(quiet_long) != 1 else ''} returned "
            f"nothing for {QUIET_RUNS} runs or more: "
            + ", ".join(f"{n} ({quiet_runs[n]} runs)" for n in quiet_long))
    if readers_failed:
        by_name = {e["reader"]: e for e in asked}
        reasons.append("every model call failed in: " + ", ".join(
            f"{n} ({by_name[n]['failed']} of {by_name[n]['calls']})"
            for n in readers_failed))
    if model is None:
        reasons.append(no_model or
                       "no model provider is configured, so the readers read nothing")

    abnormal = bool(reasons)
    where = {True: "inside", False: "outside"}.get(session)
    line = (f"{'abnormal' if abnormal else 'normal'}: started {clock} UTC"
            + (f", {where} the US session" if where else ", session not known")
            + (f", job began {job.strftime('%H:%M')} UTC" if job else "")
            + f"; sources erred: {', '.join(e['source'] for e in erred) or 'none'}"
            + "; quiet: " + (", ".join(
                f"{n} ({quiet_runs[n]} run{'s' if quiet_runs[n] != 1 else ''})"
                for n in quiet_names) or "none")
            + f"; readers failing every call: {', '.join(readers_failed) or 'none'}"
            + ("" if model else "; readers did not run: no model"))
    out = {"abnormal": abnormal, "line": line, "reasons": reasons,
           "started_at": started.strftime(_STAMP) if started else None,
           "start_hour_utc": started.hour if started else None,
           "in_us_session": session,
           "sources_erred": erred, "sources_failed": failed,
           "sources_quiet": [{"source": n, "runs": quiet_runs[n]} for n in quiet_names],
           "sources_quiet_long": quiet_long,
           "model": model, "readers": asked, "readers_failed": readers_failed}
    if job_started_at:
        out["job_started_at"] = str(job_started_at)
    return out


def crashed(started_at, exc: BaseException) -> dict:
    """The summary for a run the code crashed out of: abnormal, and why."""
    started = parse_utc(started_at)
    reason = f"the run crashed: {type(exc).__name__}: {exc}"[:400]
    return {"abnormal": True, "line": f"abnormal: {reason}", "reasons": [reason],
            "started_at": started.strftime(_STAMP) if started else None,
            "start_hour_utc": started.hour if started else None,
            "in_us_session": in_us_session(started)}


def mark_failed_readers(health: dict, outputs: dict) -> None:
    """Write the failure onto each reader's own entry in the run detail.

    A reader returns ``"status": "ok"`` when its loop finished, which says nothing about
    whether the model answered. Where every call failed the entry says so, in the place
    a person reading the detail looks first. A status the reader set itself ("api
    unavailable") is more specific and is left alone.
    """
    counts = {e["reader"]: e for e in health.get("readers") or []}
    for name in health.get("readers_failed") or []:
        entry = outputs.get(name)
        if not isinstance(entry, dict):
            continue
        count = counts[name]
        if entry.get("status") in (None, "ok"):
            entry["status"] = "failed"
        entry["model_failed"] = (f"every one of {count['calls']} model calls failed: "
                                 f"{count.get('error')}")
