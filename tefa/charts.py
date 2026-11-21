"""Shared Plotly chart builders so every page looks the same.

Palette: validated categorical order (blue, orange, aqua) — the first three slots pass
colorblind-separation checks against each other, so never more than three series share
a chart. Releases and metrics are assigned fixed colors so a color always means the
same thing on every page. Swap PALETTE values for brand colors in one place.
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from . import config as C

PALETTE = ["#2a78d6", "#eb6834", "#1baf7a"]
SEQUENTIAL = ["#cde2fb", "#86b6ef", "#3987e5", "#256abf", "#104281"]
MUTED = "#9a998f"

RELEASE_COLORS = dict(zip(C.RELEASE_ORDER, PALETTE))
METRIC_COLORS = {"eligible": "#86b6ef", "funded": PALETTE[0], "share_funded": PALETTE[0], "count": PALETTE[0]}
METRIC_LABELS = {"eligible": "Eligible applicants", "funded": "Funded participants",
                 "share_funded": "Share of funded", "count": "Count", "funded_rate": "Funded ÷ eligible"}


def _style(fig: go.Figure, height=420, money=False, pct=False) -> go.Figure:
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=40, b=10), bargap=0.25,
                      legend=dict(orientation="h", y=1.08, x=0, title=None),
                      hoverlabel=dict(namelength=-1), font=dict(size=13))
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.18)", zeroline=False)
    fig.update_traces(marker_line_width=0, selector=dict(type="bar"))
    if money:
        fig.update_yaxes(tickprefix="$", tickformat="~s")
    if pct:
        fig.update_yaxes(tickformat=".0%")
    return fig


def compare_bars(df: pd.DataFrame, color: str = "metric", title: str = "", pct=False, orientation="v") -> go.Figure:
    """Grouped bars of a tidy breakdown (category on the axis, `color` as series)."""
    d = df.copy()
    cmap = METRIC_COLORS if color == "metric" else RELEASE_COLORS
    if color == "metric":
        d["series"] = d.metric.map(METRIC_LABELS).fillna(d.metric)
        cmap = {METRIC_LABELS.get(k, k): v for k, v in METRIC_COLORS.items()}
    else:
        d["series"] = d[color]
    x, y = ("category", "value") if orientation == "v" else ("value", "category")
    fig = px.bar(d, x=x, y=y, color="series", barmode="group", orientation=orientation,
                 color_discrete_map=cmap, title=title,
                 category_orders={"series": C.RELEASE_ORDER + list(cmap)},
                 labels={"value": "", "category": "", "series": ""},
                 hover_data={"release": True, "series": True, "value": ":,.4~f" if pct else ":,.0f"})
    if orientation == "h":
        fig.update_yaxes(autorange="reversed")
    return _style(fig, pct=pct)


def rate_bars(p: pd.DataFrame, title="Funded ÷ eligible") -> go.Figure:
    d = p.dropna(subset=["funded_rate"])
    fig = px.bar(d, x="category", y="funded_rate", color="release", title=title,
                 color_discrete_map=RELEASE_COLORS, barmode="group",
                 category_orders={"release": C.RELEASE_ORDER},
                 labels={"funded_rate": "", "category": "", "release": ""},
                 hover_data={"eligible": ":,.0f", "funded": ":,.0f", "funded_rate": ":.1%"})
    return _style(fig, pct=True)


def hbar(df: pd.DataFrame, label: str, value: str, title="", money=False, n=None, color=PALETTE[0]) -> go.Figure:
    d = df.sort_values(value, ascending=False)
    if n:
        d = d.head(n)
    fig = px.bar(d, x=value, y=label, orientation="h", title=title, labels={label: "", value: ""},
                 hover_data={value: ":$,.0f" if money else ":,.0f"})
    fig.update_traces(marker_color=color)
    fig.update_yaxes(autorange="reversed")
    fig = _style(fig, height=max(300, 26 * len(d) + 80))
    if money:
        fig.update_xaxes(tickprefix="$", tickformat="~s")
    return fig


def share_bar(df: pd.DataFrame, label: str, value: str, title="", money=False) -> go.Figure:
    """Single horizontal stacked bar for part-to-whole with few parts."""
    d = df.copy()
    d["share"] = d[value] / d[value].sum()
    fig = go.Figure()
    for i, r in enumerate(d.itertuples()):
        v = getattr(r, value)
        txt = f"${v:,.0f}" if money else f"{v:,.0f}"
        fig.add_bar(x=[r.share], y=[""], orientation="h", name=str(getattr(r, label)),
                    marker_color=PALETTE[i % len(PALETTE)] if len(d) <= 3 else SEQUENTIAL[-1 - (i % 5)],
                    marker_line=dict(color="white", width=2),
                    hovertemplate=f"{getattr(r, label)}<br>{txt} ({r.share:.1%})<extra></extra>",
                    text=f"{getattr(r, label)}: {r.share:.0%}", textposition="inside")
    fig.update_layout(barmode="stack", title=title, showlegend=False)
    fig.update_xaxes(tickformat=".0%", range=[0, 1])
    return _style(fig, height=160)


def district_map(geojson: dict, df: pd.DataFrame, col: str, label_col: str = "label",
                 hover_cols: dict | None = None, money: bool = False, height: int = 640,
                 bounds: tuple | None = None) -> go.Figure:
    """Choropleth drawn as filled shapes on plain axes.

    Unlike Plotly's geo/map traces this needs no CDN topojson, map tiles, or WebGL, so it
    renders offline, behind firewalls, and in exported PNG/SVG. One trace per district;
    districts with no value are drawn in light gray."""
    from plotly.colors import sample_colorscale

    hover_cols = hover_cols or {}
    d = df.set_index("district")
    vals = d[col]
    lo, hi = vals.min(), vals.max()
    span = (hi - lo) or 1
    fig = go.Figure()

    def _has_hole(f):
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        return any(len(p) > 1 for p in polys)

    # Interior rings aren't cut out of the fill, so a district with a hole (e.g. HD 54
    # around HD 55) is drawn first and the district inside it is drawn on top.
    for f in sorted(geojson["features"], key=lambda f: not _has_hole(f)):
        did = int(f["id"])
        geom = f["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        xs, ys = [], []
        for poly in polys:
            ring = poly[0]  # exterior ring; holes are rare in district plans
            xs += [p[0] for p in ring] + [None]
            ys += [p[1] for p in ring] + [None]
        v = vals.get(did)
        fill = MUTED if v is None or pd.isna(v) else sample_colorscale(SEQUENTIAL, [(v - lo) / span])[0]
        row = d.loc[did] if did in d.index else None
        lines = [f"<b>{row[label_col] if row is not None else did}</b>"]
        if v is not None and not pd.isna(v):
            lines.append(f"${v:,.0f}" if money else (f"{v:,.1f}" if abs(v) < 100 else f"{v:,.0f}"))
        else:
            lines.append("no value")
        if row is not None:
            for c, lab in hover_cols.items():
                if c in row and pd.notna(row[c]):
                    lines.append(f"{lab}: {row[c]:,.0f}" if isinstance(row[c], (int, float)) else f"{lab}: {row[c]}")
        fig.add_scatter(x=xs, y=ys, fill="toself", mode="lines", fillcolor=fill,
                        line=dict(color="white", width=0.6), hoveron="fills",
                        text="<br>".join(lines), hoverinfo="text", showlegend=False)
    # invisible trace carrying the color bar
    fig.add_scatter(x=[None], y=[None], mode="markers", showlegend=False, hoverinfo="skip",
                    marker=dict(colorscale=SEQUENTIAL, cmin=lo, cmax=hi, color=[lo], showscale=True,
                                colorbar=dict(thickness=12, tickformat="$,.0f" if money else ",.0f")))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False, scaleanchor="x", scaleratio=1 / 0.857)  # cos(31°N) keeps Texas' shape
    fig.update_layout(height=height, margin=dict(l=0, r=0, t=0, b=0), plot_bgcolor="rgba(0,0,0,0)",
                      paper_bgcolor="rgba(0,0,0,0)", hoverlabel=dict(bgcolor="white"), dragmode="pan")
    if bounds:  # (lon_min, lon_max, lat_min, lat_max)
        fig.update_xaxes(range=bounds[:2])
        fig.update_yaxes(range=bounds[2:])
    return fig


# Metro views for the district map: (lon_min, lon_max, lat_min, lat_max)
FOCUS = {
    "Statewide": None,
    "Houston": (-96.1, -94.8, 29.35, 30.35),
    "Dallas–Fort Worth": (-97.65, -96.35, 32.45, 33.35),
    "San Antonio": (-98.85, -98.15, 29.2, 29.75),
    "Austin": (-98.1, -97.4, 30.05, 30.65),
    "El Paso": (-106.65, -106.15, 31.6, 32.0),
    "Rio Grande Valley": (-98.6, -97.2, 25.85, 26.6),
}
