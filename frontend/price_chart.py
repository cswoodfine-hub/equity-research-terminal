"""Interactive price chart: a TradingView lightweight-charts component.

The rest of the terminal draws hand-built SVG, which is display-only by design. The
price chart is the one place that needs real trading interaction: smooth two-finger
zoom that stretches the sticks with the y-axis auto-fitting the visible range, a
candlestick view, and intraday intervals. Plotly-in-Streamlit cannot do the y-auto-fit
(Streamlit never reports a zoom back to the code), so this uses TradingView's
lightweight-charts, embedded through ``st.components.v1.html`` with the library bundled
locally, no CDN, the same rule the fonts follow.

Pure: it turns price bars and saved tags into series data, markers and the component
HTML, and knows nothing about Streamlit, the API, or the database. Colour comes only
from the palette tokens.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from components import tokens as TK

LINE, CANDLE = "Line", "Candlestick"

# An event is dated to a day, but the bars may be weekly, monthly or intraday, so it
# snaps to the nearest bar within this many days and is dropped if the nearest is further
# off. This also drops events outside the chart's window: an approval older than the
# history, or a loss-of-exclusivity years in the future, is years from any bar.
_SNAP_DAYS = 40

# How each event type is drawn: an approval below the bar in the up colour, a loss of
# exclusivity above it in the down colour, so the two read apart without a legend.
_EVENT_STYLE = {
    "approval": {"position": "belowBar", "color": TK.UP, "shape": "arrowUp"},
    "loe": {"position": "aboveBar", "color": TK.DOWN, "shape": "arrowDown"},
    # A change the analyst made, rather than one the world made. Above the bar in the
    # flag colour, the one marker on the chart that is about this book rather than about
    # the company.
    "model": {"position": "aboveBar", "color": TK.FLAG, "shape": "circle"},
    "change": {"position": "belowBar", "color": TK.MUTED, "shape": "circle"},
    "catalyst": {"position": "belowBar", "color": TK.MUTED, "shape": "circle"},
}

# Which event speaks for a day that carries several. A model move leads because it is the
# half of the record a reader cannot see from outside; then an approval, then a loss of
# exclusivity, then the rest.
_EVENT_RANK = {"model": 0, "approval": 1, "loe": 2, "catalyst": 3, "change": 4}

# The library, bundled once into assets like the fonts, inlined into the component so
# nothing loads from a network. A missing file degrades to an empty script rather than
# erroring, and the chart simply does not draw.
_LWC_PATH = Path(__file__).resolve().parent / "assets" / "lightweight-charts.standalone.production.js"
_LWC_JS = _LWC_PATH.read_text() if _LWC_PATH.exists() else ""


def _parse_day(value):
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _bar_time(as_of, intraday: bool):
    """lightweight-charts time: a UTC epoch (seconds) for intraday, a 'YYYY-MM-DD' string
    otherwise. The intraday stamp is the exchange-local clock read as UTC, so the library
    prints the market's own time rather than shifting it."""
    s = str(as_of or "")
    if not s:
        return None
    if not intraday:
        return s[:10]
    try:
        moment = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    return int(moment.replace(tzinfo=dt.timezone.utc).timestamp())


def series_data(bars, mode: str = LINE, intraday: bool = False) -> list[dict]:
    """Bars to a lightweight-charts series. Candlestick needs full OHLC on a bar, so a bar
    missing one is dropped rather than faked; line needs only the close."""
    out = []
    for bar in bars:
        time = _bar_time(bar.get("as_of"), intraday)
        if time is None or bar.get("close") is None:
            continue
        if mode == CANDLE:
            if any(bar.get(k) is None for k in ("open", "high", "low")):
                continue
            out.append({"time": time, "open": float(bar["open"]),
                        "high": float(bar["high"]), "low": float(bar["low"]),
                        "close": float(bar["close"])})
        else:
            out.append({"time": time, "value": float(bar["close"])})
    return out


def event_markers(bars, events, intraday: bool = False) -> list[dict]:
    """Events to markers, each snapped to the bar nearest its day so it stays put across
    bar sizes; an event whose nearest bar is off the chart (an old approval, a future LOE)
    is dropped. Each event is {date, label, kind}. Sorted by time, which lightweight-charts
    requires.

    A bar gets one marker however many events land on it. The library stacks markers at
    one time until they overlap, and six arrows on a day reads as six days of news rather
    than one day of six. The event that ranks highest speaks, and the rest are counted on
    it: the day is still legible and nothing is hidden, since the list under the chart
    carries them all.
    """
    dated = [(_parse_day(b.get("as_of")), b) for b in bars]
    dated = [(d, b) for d, b in dated if d is not None and b.get("close") is not None]
    on_bar: dict = {}
    for event in events or []:
        day = _parse_day(event.get("date"))
        if day is None or not dated:
            continue
        near_day, near_bar = min(dated, key=lambda p: abs((p[0] - day).days))
        if abs((near_day - day).days) > _SNAP_DAYS:
            continue
        on_bar.setdefault(near_day, []).append((near_bar, event))
    marks = []
    for near_day, landed in on_bar.items():
        landed.sort(key=lambda p: _EVENT_RANK.get(p[1].get("kind"), 9))
        near_bar, lead = landed[0]
        style = _EVENT_STYLE.get(lead.get("kind"), _EVENT_STYLE["approval"])
        text = str(lead.get("label") or "")
        if len(landed) > 1:
            text = f"{text} +{len(landed) - 1}"
        marks.append((near_day, {
            "time": _bar_time(near_bar.get("as_of"), intraday),
            "position": style["position"], "color": style["color"],
            "shape": style["shape"], "text": text}))
    return [m for _, m in sorted(marks, key=lambda p: p[0])]


def forecast_series(points, intraday: bool = False, bars=None) -> list[dict]:
    """The fair value this book stated, as a step line against the price.

    A step and not a slope. The model held its view between the days it stated one, and a
    sloped line would draw a daily rebuild that never happened. A carried day takes the
    muted colour, so the line says which days were stated and which were held, and a day
    with no stated view at all is whitespace: the line stops rather than reaching back
    through dates the book had no view on.

    Clipped to the loaded bars. The fair value record can run far longer than the price
    window on screen, and the chart fits the whole of what it is given: a six-month line
    against a five-day view would silently stretch the view to six months.

    Empty on an intraday view. The model states a view once a day, and drawing it against
    fifteen-minute bars would read as a figure that moves with the price.
    """
    if intraday:
        return []
    window = [d for d in (_parse_day(b.get("as_of")) for b in (bars or [])) if d]
    first, last = (min(window), max(window)) if window else (None, None)
    out = []
    for point in points or []:
        day = _parse_day(point.get("as_of"))
        if first is not None and (day is None or day < first or day > last):
            continue
        time = _bar_time(point.get("as_of"), False)
        if time is None:
            continue
        value = point.get("fair_value")
        if value is None:
            out.append({"time": time})          # whitespace: the line breaks here
            continue
        out.append({"time": time, "value": float(value),
                    "color": TK.FLAG if point.get("stated") else TK.MUTED})
    # Whitespace only between drawn points. It is there to break a line that has started
    # and then stopped; before the first stated day and after the last there is no line to
    # break, and carrying thousands of empty bars across to draw a fortnight is a payload
    # the component pays for on every render.
    drawn = [i for i, point in enumerate(out) if "value" in point]
    return out[drawn[0]:drawn[-1] + 1] if drawn else []


def _visible_range(data, window_days, intraday):
    """The opening view: the last ``window_days`` of the loaded series. The whole series
    is still loaded, so a pan reaches the real limits; this only sets where it opens."""
    if not window_days or not data:
        return None
    last = data[-1]["time"]
    if intraday:
        cutoff = last - window_days * 86400
    else:
        cutoff = (_parse_day(data[-1]["time"])
                  - dt.timedelta(days=window_days)).isoformat()
    start = next((d["time"] for d in data if d["time"] >= cutoff), data[0]["time"])
    return [start, last]


def chart_html(bars, events=None, *, mode: str = LINE, ticker: str = "", currency: str = "",
               intraday: bool = False, window_days=None, height: int = 560) -> str:
    """The component HTML: the bundled library plus a script that builds the themed chart.

    ``bars`` are oldest first with as_of and OHLC; ``events`` are {date, label, kind} put
    on the chart as markers (approvals, LOE). The whole series is loaded for panning;
    ``window_days`` sets only the opening view.
    """
    data = series_data(bars, mode, intraday)
    marks = event_markers(bars, events, intraday)
    visible = _visible_range(data, window_days, intraday)

    g, txt, font = TK.GROUND, TK.MUTED, TK.FONT_UI
    grid, rs, up, down, muted = TK.RULE_FAINT, TK.RULE_STRONG, TK.UP, TK.DOWN, TK.MUTED
    if mode == CANDLE:
        series_js = (f"chart.addCandlestickSeries({{ upColor: {up!r}, downColor: {down!r}, "
                     f"borderUpColor: {up!r}, borderDownColor: {down!r}, "
                     f"wickUpColor: {up!r}, wickDownColor: {down!r} }})")
    else:
        series_js = f"chart.addLineSeries({{ color: {up!r}, lineWidth: 2 }})"
    return f"""
<div id="lwc" style="width:100%;height:{height}px"></div>
<script>{_LWC_JS}</script>
<script>
/* chart-mode: {mode} */
(function() {{
  if (typeof LightweightCharts === 'undefined') return;
  const el = document.getElementById('lwc');
  const chart = LightweightCharts.createChart(el, {{
    layout: {{ background: {{ type: 'solid', color: {g!r} }},
              textColor: {txt!r}, fontFamily: {font!r}, fontSize: 10 }},
    grid: {{ vertLines: {{ color: {grid!r} }}, horzLines: {{ color: {grid!r} }} }},
    rightPriceScale: {{ borderColor: {rs!r} }},
    timeScale: {{ borderColor: {rs!r}, rightOffset: 4,
                 timeVisible: {str(intraday).lower()}, secondsVisible: false }},
    crosshair: {{ mode: 0,
                 vertLine: {{ color: {muted!r}, labelBackgroundColor: {rs!r} }},
                 horzLine: {{ color: {muted!r}, labelBackgroundColor: {rs!r} }} }},
    handleScroll: true, handleScale: true,
  }});
  const data = {json.dumps(data)};
  const series = {series_js};
  series.setData(data);
  const markers = {json.dumps(marks)};
  if (markers.length) series.setMarkers(markers);
  const visible = {json.dumps(visible)};
  if (visible) {{ try {{ chart.timeScale().setVisibleRange({{ from: visible[0], to: visible[1] }}); }}
                 catch (e) {{ chart.timeScale().fitContent(); }} }}
  else {{ chart.timeScale().fitContent(); }}
  const fit = () => chart.applyOptions({{ width: el.clientWidth }});
  new ResizeObserver(fit).observe(el);
  fit();
}})();
</script>
"""


# --- The live overlay -----------------------------------------------------
# The chart reads two things. The stored series is the book's: daily closes and the
# intraday windows as the last full refresh left them. The live read is Yahoo's recent
# bars as they stand now, fetched by /companies/{ticker}/prices/live, which writes
# nothing (backend/prices_live.py says why). What follows lays the second over the first
# and puts into words what the reader is then looking at. All of it is pure: the route's
# answer in, bars and sentences out.

# How often the chart re-reads while a session is open.
LIVE_TICK_S = 60
# A session that opens within this long gets one timer set for the bell, so a tab left
# open before the open starts updating by itself. Further off than that and no timer
# runs at all.
LIVE_WAKE_WITHIN_S = 12 * 60 * 60


def merge_live(stored, live) -> list[dict]:
    """The stored bars with the live ones laid over them, oldest first.

    Keyed on the bar's timestamp. Where both hold a bar the live one wins: it is the
    later look at the same bar, and the stored one may be a session caught half formed
    by a refresh run during market hours. No timestamp appears twice, and the order is
    by time whatever order the two lists came in.
    """
    by_time: dict = {}
    for bar in list(stored or []) + list(live or []):
        key = str(bar.get("as_of") or "")
        if key:
            by_time[key] = bar
    return [by_time[key] for key in sorted(by_time)]


def live_gap(stored, live) -> dict | None:
    """Where the stored bars stop short of the live ones, or None where they meet.

    The live read reaches back a few sessions. If the last full refresh is older than
    that, the chart would join the last stored bar to the first live one across days
    nobody fetched, and a line through them reads as data. A weekday between the two is
    taken as a session missed. It may have been a holiday, which is why the sentence
    built from this says what is on file and not what happened.
    """
    stored_days = [str(b.get("as_of") or "") for b in stored or [] if b.get("as_of")]
    live_days = [str(b.get("as_of") or "") for b in live or [] if b.get("as_of")]
    if not stored_days or not live_days:
        return None
    ends, begins = max(stored_days), min(live_days)
    if begins <= ends:
        return None
    last, first = _parse_day(ends), _parse_day(begins)
    if last is None or first is None:
        return None
    between = [last + dt.timedelta(days=n) for n in range(1, (first - last).days)]
    if not any(day.weekday() < 5 for day in between):
        return None
    return {"stored_ends": ends, "live_begins": begins}


def _moment(value) -> str:
    """A timestamp from either side, as comparable text: 'YYYY-MM-DD HH:MM:SS'."""
    return str(value or "").replace("T", " ").replace("Z", "")[:19]


def live_daily_applies(stored, live_daily, stored_read_at=None) -> bool:
    """Whether the session's live daily bar goes on the daily chart.

    It does whenever the stored series has no bar for that day, and whenever it has one
    that may not be the day's close: a session still open, or a stored bar read before
    the session ended, which is the last trade at the hour of the refresh and not a
    close. Only a stored bar read after the bell is left standing, because that one is
    the finished session with the consolidated volume, and the live bar is five minute
    bars added up.
    """
    if not live_daily or not live_daily.get("as_of") or live_daily.get("close") is None:
        return False
    day = str(live_daily["as_of"])[:10]
    if not any(str(b.get("as_of") or "")[:10] == day for b in stored or []):
        return True
    ended = _moment(live_daily.get("session_end"))
    read = _moment(stored_read_at)
    return not (live_daily.get("complete") and ended and read and read >= ended)


def poll_seconds(live):
    """Seconds until the chart should read again, or None for no timer.

    Sixty while the regular session is open. One timer set for the bell when the
    session opens within twelve hours. Otherwise nothing: a closed market is not asked
    the same question every minute.
    """
    market = (live or {}).get("market") or {}
    if market.get("regular_open"):
        return LIVE_TICK_S
    wait = market.get("seconds_to_open")
    if wait is not None and 0 <= wait <= LIVE_WAKE_WITHIN_S:
        return max(int(wait) + 5, 15)
    return None


def poll_kind(seconds) -> str:
    """Which of the three timers a figure from ``poll_seconds`` is: 'tick' while a
    session is open, 'wake' when waiting for the bell, 'off' for none."""
    if seconds is None:
        return "off"
    return "tick" if seconds == LIVE_TICK_S else "wake"


def _utc_clock(stamp, seconds: bool = True) -> str:
    """'2026-11-23T14:47:05Z' as '14:47:05 UTC'."""
    text = _moment(stamp)
    return f"{text[11:19] if seconds else text[11:16]} UTC" if len(text) >= 16 else ""


def _span(seconds) -> str:
    seconds = max(int(seconds), 0)
    if seconds < 90:
        return f"{seconds} seconds"
    return f"{round(seconds / 60)} minutes"


def live_status(live) -> str:
    """The few words that ride on the tab's section rule: whose prices, read when, and
    whether the market is open."""
    if not live:
        return ""
    parts = []
    read = _utc_clock(live.get("fetched_at"))
    if not live.get("ok"):
        parts.append("Yahoo did not answer" + (f", last read {read}" if read else ""))
    elif read:
        parts.append(f"Yahoo, read {read}")
    market = live.get("market") or {}
    exchange = market.get("exchange") or "market"
    if market.get("regular_open"):
        parts.append(f"{exchange} open, re-read every minute")
    elif market:
        opens = (_utc_clock(market.get("regular_start"), seconds=False)
                 if market.get("seconds_to_open") is not None else "")
        parts.append(f"{exchange} closed" + (f", opens {opens}" if opens else ""))
    return " · ".join(parts)


def live_bar_words(live, base: str, applied, stored=None) -> str:
    """What the legend says about the live bars on screen, in words, so that nobody has
    to tell a forming bar from a finished one by its colour. Empty when the live read
    put nothing on the chart that the stored series did not already hold.

    ``base`` is the stored series the view is built from ('1d', '5m' or '60m'),
    ``applied`` the live bars laid over it and ``stored`` the series itself.
    """
    applied = list(applied or [])
    if not applied:
        return ""
    if base != "1d":
        ends = max((str(b.get("as_of") or "") for b in stored or []), default="")
        fresh = sorted(str(b.get("as_of") or "") for b in applied
                       if str(b.get("as_of") or "") > ends)
        if not fresh:
            return ""
        return f"live from {fresh[0]}: Yahoo's bars, not in the stored history"
    bar = applied[-1]
    day = str(bar.get("as_of") or "")[:10]
    zone = ((live or {}).get("market") or {}).get("timezone") or "exchange time"
    if bar.get("complete"):
        return (f"{day} is live: the finished session added up from Yahoo's five minute "
                "bars, not yet a stored close")
    upto = str(bar.get("last_bar") or "")[11:16]
    return (f"{day} is live: the session so far"
            + (f", to the {upto} {zone} bar" if upto else "") + ", not a close")


def live_gap_words(gap) -> str:
    """The plain statement that the stored bars stop short of the live ones."""
    if not gap:
        return ""
    return (f"Stored bars end {gap['stored_ends']} and the live read begins "
            f"{gap['live_begins']}. Nothing between the two is on file, so the line "
            "across it is not data; a full refresh fills it.")


def live_note(live) -> str:
    """The sentences for the folded byline: whose prices these are, when they were read,
    what the market is doing and how far behind the feed runs."""
    if not live:
        return ""
    out = []
    read = _utc_clock(live.get("fetched_at"))
    if not live.get("ok"):
        why = live.get("reason") or "no reason given"
        out.append(f"Yahoo did not answer the live read ({why}). "
                   + (f"The live bars shown were read at {read}. " if read
                      else "The chart shows the stored bars only. "))
    elif read:
        out.append(f"Live prices are Yahoo's, read at {read}. The live read writes "
                   "nothing to the book, so the stored history still ends at the last "
                   "full refresh and no close is filed during a session. ")
    market = live.get("market") or {}
    exchange = market.get("exchange") or "The market"
    if market.get("regular_open"):
        out.append(f"{exchange}'s regular session is open until "
                   f"{_utc_clock(market.get('regular_end'), seconds=False)} and the "
                   "chart reads again every minute while it is. ")
        if market.get("traded_this_session") is False:
            out.append("No trade has printed in this session yet. ")
        stated, age = market.get("stated_delay_minutes"), market.get("quote_age_seconds")
        if stated is not None:
            out.append(f"Yahoo states a delay of {stated} minutes. ")
        elif age is not None:
            out.append("Yahoo does not state a delay on this feed; the last trade was "
                       f"{_span(age)} before the read. ")
    elif market:
        opens = (_utc_clock(market.get("regular_start"), seconds=False)
                 if market.get("seconds_to_open") is not None else "")
        out.append(f"{exchange}'s regular session is closed"
                   + (f" and opens at {opens}" if opens else "")
                   + ", so nothing is read again until it opens. Refresh reads Yahoo "
                     "again at once. ")
    return "".join(out)
