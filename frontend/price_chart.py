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
