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

# A tag is stored against a day, but the bars may be weekly, monthly or intraday, so a
# tag snaps to the nearest bar within this many days and is dropped if the nearest is
# further off (a note left on a bar the chart no longer holds).
_TAG_SNAP_DAYS = 40

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


def markers_for(bars, tags, intraday: bool = False) -> list[dict]:
    """Saved tags to markers, each snapped to the bar nearest its day so a note stays put
    across bar sizes; a tag whose nearest bar is off the chart is dropped. Sorted by time,
    which lightweight-charts requires."""
    dated = [(_parse_day(b.get("as_of")), b) for b in bars]
    dated = [(d, b) for d, b in dated if d is not None and b.get("close") is not None]
    marks = []
    for tag in tags or []:
        day = _parse_day(tag.get("entity_id"))
        if day is None or not dated:
            continue
        near_day, near_bar = min(dated, key=lambda p: abs((p[0] - day).days))
        if abs((near_day - day).days) > _TAG_SNAP_DAYS:
            continue
        marks.append((near_day, {
            "time": _bar_time(near_bar.get("as_of"), intraday),
            "position": "aboveBar", "color": TK.FLAG, "shape": "arrowDown",
            "text": str(tag.get("body") or "")}))
    return [m for _, m in sorted(marks, key=lambda p: p[0])]


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


def chart_html(bars, tags=None, *, mode: str = LINE, ticker: str = "", currency: str = "",
               intraday: bool = False, window_days=None, height: int = 560) -> str:
    """The component HTML: the bundled library plus a script that builds the themed chart.

    ``bars`` are oldest first with as_of and OHLC; ``tags`` are saved annotations. The
    whole series is loaded for panning; ``window_days`` sets only the opening view.
    """
    data = series_data(bars, mode, intraday)
    marks = markers_for(bars, tags, intraday)
    visible = _visible_range(data, window_days, intraday)

    g, txt, font = TK.GROUND, TK.MUTED, TK.FONT_UI
    rule, rs, up, down, muted = TK.RULE, TK.RULE_STRONG, TK.UP, TK.DOWN, TK.MUTED
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
              textColor: {txt!r}, fontFamily: {font!r}, fontSize: 11 }},
    grid: {{ vertLines: {{ color: {rule!r} }}, horzLines: {{ color: {rule!r} }} }},
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
