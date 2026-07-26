"""Interactive price chart: a Plotly figure for the Prices tab.

The rest of the terminal draws hand-built SVG, which is display-only by design. The price
chart is the one place that needs live interaction: grab-to-pan, zoom in and out, a
candlestick view, and a click on a bar to leave a tag. So it alone uses Plotly, through
Streamlit's first-party ``st.plotly_chart``; everything else stays SVG.

Pure: it turns price rows and any saved tags into a ``go.Figure`` and knows nothing about
Streamlit, the API, or the database. Colour comes only from the palette tokens.
"""

from __future__ import annotations

import datetime as dt

import plotly.graph_objects as go

from components import tokens as TK

LINE, CANDLE = "Line", "Candlestick"

# A tag label runs on the chart; the full note is on hover, so the label stays short.
_LABEL_MAX = 22
# A tag is stored against a day, but the bars may be weekly or monthly, so a tag snaps to
# the nearest bar within this many days and is dropped if the nearest bar is further off.
_TAG_SNAP_DAYS = 40


def _parse_day(value):
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _axis_font():
    return dict(family=TK.FONT_MONO, size=11, color=TK.MUTED)


def figure(rows, tags=None, *, mode: str = LINE, ticker: str = "",
           currency: str = "", uirevision: str = "price") -> go.Figure:
    """A themed Plotly figure of the daily price history.

    ``rows`` are oldest first, each with ``as_of`` and OHLC. ``close`` is always present;
    ``open``/``high``/``low`` may be null on an older bar and Plotly gaps the candle rather
    than inventing it. ``tags`` are saved annotations, each with ``entity_id`` (the bar's
    ``as_of``) and ``body``, drawn as a marker on the matching bar so a note shows in
    either view. ``mode`` is Line or Candlestick.
    """
    tags = tags or []
    xs = [r["as_of"] for r in rows]
    closes = [r.get("close") for r in rows]

    fig = go.Figure()
    if mode == CANDLE:
        fig.add_trace(go.Candlestick(
            x=xs,
            open=[r.get("open") for r in rows],
            high=[r.get("high") for r in rows],
            low=[r.get("low") for r in rows],
            close=closes,
            name=ticker or "price",
            increasing=dict(line=dict(color=TK.UP), fillcolor=TK.UP),
            decreasing=dict(line=dict(color=TK.DOWN), fillcolor=TK.DOWN),
            line=dict(width=1),
            whiskerwidth=0.3,
            showlegend=False,
        ))
        # A faint close marker per bar, so a click still lands on a bar to tag it: a
        # candlestick trace is awkward to click-select, a scatter point is not. WebGL, so
        # a thousand of them stay smooth to pan and zoom.
        fig.add_trace(go.Scattergl(
            x=xs, y=closes, mode="markers", name="close",
            marker=dict(size=5, color="rgba(126,144,152,0.28)", line=dict(width=0)),
            hovertemplate="%{x|%Y-%m-%d}  %{y:.2f}<extra></extra>",
            showlegend=False,
        ))
    else:
        # WebGL line with small markers on it: the markers are the click targets, and the
        # GL canvas keeps a thousand points smooth to drag and zoom where SVG stutters.
        fig.add_trace(go.Scattergl(
            x=xs, y=closes, mode="lines+markers", name=ticker or "price",
            line=dict(color=TK.UP, width=1.6),
            marker=dict(size=3, color=TK.UP),
            hovertemplate="%{x|%Y-%m-%d}  %{y:.2f}<extra></extra>",
            showlegend=False,
        ))

    # Tags sit on the bar nearest their day, at that bar's close, so a note stays put when
    # the bars are weekly or monthly rather than daily. A tag whose day is off the chart is
    # dropped. A short label rides above the point; the full body is on hover.
    bars = [(_parse_day(r["as_of"]), str(r["as_of"])[:10], r.get("close")) for r in rows]
    bars = [b for b in bars if b[0] is not None and b[2] is not None]
    tx, ty, labels, bodies = [], [], [], []
    for tag in tags:
        day = _parse_day(tag.get("entity_id"))
        if day is None or not bars:
            continue
        near = min(bars, key=lambda b: abs((b[0] - day).days))
        if abs((near[0] - day).days) > _TAG_SNAP_DAYS:
            continue
        body = str(tag.get("body") or "")
        tx.append(near[1])
        ty.append(near[2])
        labels.append(body if len(body) <= _LABEL_MAX else body[:_LABEL_MAX - 1] + "…")
        bodies.append(body)
    if tx:
        fig.add_trace(go.Scatter(
            x=tx, y=ty, mode="markers+text", name="tags",
            marker=dict(symbol="triangle-down", size=12, color=TK.FLAG,
                        line=dict(width=0)),
            text=labels, textposition="top center",
            textfont=dict(family=TK.FONT_MONO, size=10, color=TK.FLAG),
            customdata=bodies,
            hovertemplate="%{customdata}<extra></extra>",
            showlegend=False,
        ))

    unit = f" · {currency}" if currency else ""
    fig.update_layout(
        height=540,
        # Held constant across reruns so Plotly keeps the user's pan and zoom instead of
        # snapping back to the window; the caller varies it by ticker, window and view, so
        # changing a control still resets the frame on purpose.
        uirevision=uirevision,
        paper_bgcolor=TK.GROUND, plot_bgcolor=TK.GROUND,
        font=dict(family=TK.FONT_UI, color=TK.TEXT, size=12),
        margin=dict(l=8, r=58, t=10, b=8),
        dragmode="pan",
        clickmode="event+select",
        hovermode="x unified",
        hoverlabel=dict(bgcolor=TK.PANEL, bordercolor=TK.RULE_STRONG,
                        font=dict(family=TK.FONT_MONO, color=TK.TEXT, size=11)),
        showlegend=False,
        # No range slider: zoom is the trackpad (two-finger scroll) and the modebar, and
        # the slider only ate height. Pan is a drag.
        xaxis=dict(
            gridcolor=TK.RULE, zerolinecolor=TK.RULE, showline=False,
            tickfont=_axis_font(), ticklabelposition="outside",
            rangeslider=dict(visible=False),
        ),
        # Price on the right and auto-ranged to the data, not to zero, so the series fills
        # the height rather than being squashed against the top.
        yaxis=dict(
            title=dict(text=f"price{unit}", font=_axis_font()),
            gridcolor=TK.RULE, zeroline=False, side="right",
            tickfont=_axis_font(), tickformat=".2f", autorange=True,
        ),
    )
    return fig
