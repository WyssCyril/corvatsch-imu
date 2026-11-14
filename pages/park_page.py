"""
Chart building blocks for the park dashboard (same look as the halfpipe dashboard).
Reads the prepared data from data/<YYYYMMDD_Ort>/ (built with tools/build_park_data.py).
"""
import datetime as _dt
import os

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

# Larger text in all charts. Streamlit's chart theme overrides the template, so sizes are set on every figure.
from streamlit.delta_generator import DeltaGenerator as _DG

SS_RED = "#E3001B"
INK = "#2b2b2b"
MUTED = "#8a8a8a"
GREY = "#a8a19c"
_orig_plotly_chart = _DG.plotly_chart


def _plotly_chart_large(self, fig, *args, **kwargs):
    if isinstance(fig, go.Figure):
        fig.update_layout(font=dict(size=14, family="Inter, Source Sans Pro, sans-serif", color=INK),
                          legend=dict(font=dict(size=14)), title_font=dict(size=16))
        fig.update_xaxes(tickfont=dict(size=15), title_font=dict(size=14))
        fig.update_yaxes(tickfont=dict(size=14), title_font=dict(size=14))
        kwargs.setdefault("theme", None)
    return _orig_plotly_chart(self, fig, *args, **kwargs)


if getattr(_DG.plotly_chart, "__name__", "") != "_plotly_chart_large":
    _DG.plotly_chart = _plotly_chart_large
    st.plotly_chart = _plotly_chart_large.__get__(st._main)

DATA_ROOT = os.path.join(os.path.dirname(__file__), "..", "data")
# Aerial image swisstopo (free to use, credit the source)
SWISSIMAGE = "https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.swissimage/default/current/3857/{z}/{x}/{y}.jpeg"


def _days() -> list[str]:
    if not os.path.isdir(DATA_ROOT):
        return []
    return sorted([d for d in os.listdir(DATA_ROOT)
                   if os.path.exists(os.path.join(DATA_ROOT, d, "jumps.parquet"))], reverse=True)


@st.cache_data(show_spinner=False)
def _load(day: str, name: str) -> pd.DataFrame:
    return pd.read_parquet(os.path.join(DATA_ROOT, day, f"{name}.parquet"))


def _day_label(day: str) -> str:
    """'20261114_Corvatsch' -> '14.11.2026 · Corvatsch'"""
    try:
        d, ort = day.split("_", 1)
        return f"{d[6:8]}.{d[4:6]}.{d[:4]} · {ort.replace('-', ' ')}"
    except ValueError:
        return day


def _map_layout(lat, lon, height=520, zoom=16.0):
    lat = pd.Series(lat).dropna(); lon = pd.Series(lon).dropna()
    return dict(
        map=dict(style="white-bg", center=dict(lat=float(lat.median()), lon=float(lon.median())), zoom=zoom,
                 layers=[dict(sourcetype="raster", source=[SWISSIMAGE], below="traces",
                              sourceattribution="© swisstopo")]),
        margin=dict(l=0, r=0, t=0, b=0), height=height,
        legend=dict(bgcolor="rgba(255,255,255,0.85)", x=0.01, y=0.99),
    )


def _jump_label(h: pd.DataFrame) -> list[str]:
    return [f"K{int(k)}" if pd.notna(k) else f"J{int(s)}" for k, s in zip(h["Kicker"], h["Sprung"])]


def _run_plot(ts: pd.DataFrame, gps: pd.DataFrame, h: pd.DataFrame) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.06, row_heights=[0.62, 0.38],
                        subplot_titles=("Resultant acceleration (g)", "GPS speed (km/h)"))
    step = max(1, len(ts) // 15000)
    d = ts.iloc[::step] if step > 1 else ts
    fig.add_trace(go.Scatter(x=d["t_s"], y=d["accRes_g"], mode="lines", line=dict(color=INK, width=1),
                             name="Acceleration", showlegend=False,
                             hovertemplate="%{x:.2f} s · %{y:.1f} g<extra></extra>"), row=1, col=1)
    fig.add_hline(y=16, line_dash="dot", line_color=MUTED, annotation_text="16 g sensor range", row=1, col=1)
    if len(h):
        t_peak = h["t_run_s"] + h["Airtime_s"] + h["Time_to_peak_s"].fillna(0)
        col = [SS_RED if p else GREY for p in h["Plausibel"]]
        fig.add_trace(go.Scatter(x=t_peak, y=h["Peak_g_roh"], mode="markers+text",
                                 marker=dict(color=col, size=10), text=_jump_label(h),
                                 textposition="top center", name="Landing (peak)",
                                 customdata=np.c_[h["Peak_g"], h["Airtime_s"], h["Grund"].fillna("")],
                                 hovertemplate="%{text}<br>Peak %{customdata[0]:.1f} g (corr.)"
                                               "<br>Airtime %{customdata[1]:.2f} s<br>%{customdata[2]}<extra></extra>"),
                      row=1, col=1)
    fig.add_trace(go.Scatter(x=gps["t_s"], y=gps["speed_kmh"], mode="lines", line=dict(color=SS_RED, width=1.6),
                             name="Speed", showlegend=False,
                             hovertemplate="%{x:.1f} s · %{y:.1f} km/h<extra></extra>"), row=2, col=1)
    for _, x in h.iterrows():
        for r in (1, 2):
            fig.add_vrect(x0=float(x["t_run_s"]), x1=float(x["t_run_s"] + x["Airtime_s"]),
                          fillcolor="#9ec5e8" if x["Plausibel"] else "#dddddd",
                          opacity=0.35, line_width=0, layer="below", row=r, col=1)
    fig.update_layout(template="plotly_white", height=520, showlegend=True, margin=dict(l=10, r=10, t=40, b=10),
                      legend=dict(orientation="h", y=1.08, x=1, xanchor="right"))
    fig.update_xaxes(title_text="Time in run (s)", row=2, col=1)
    return fig


def _run_map(gps: pd.DataFrame, h: pd.DataFrame) -> go.Figure:
    tr = [go.Scattermap(lat=gps["lat"], lon=gps["lon"], mode="markers",
                        marker=dict(size=6, color=gps["speed_kmh"], colorscale="Turbo", cmin=0,
                                    cmax=max(40, float(gps["speed_kmh"].max())),
                                    colorbar=dict(title="km/h", thickness=12, x=0.98)),
                        name="Track", hovertemplate="%{marker.color:.1f} km/h<extra></extra>")]
    hp = h.dropna(subset=["Lat", "Lon"])
    tr.append(go.Scattermap(lat=hp["Lat"], lon=hp["Lon"], mode="markers+text",
                            marker=dict(size=13, color=[SS_RED if p else GREY for p in hp["Plausibel"]]),
                            text=_jump_label(hp), textposition="top right", textfont=dict(color="white", size=13),
                            name="Take-off", customdata=np.c_[hp["Peak_g"], hp["Airtime_s"], hp["Speed_kmh"]],
                            hovertemplate="%{text}<br>%{customdata[0]:.1f} g · %{customdata[1]:.2f} s"
                                          "<br>%{customdata[2]:.0f} km/h<extra></extra>"))
    fig = go.Figure(tr)
    fig.update_layout(**_map_layout(hp["Lat"] if len(hp) else gps["lat"], hp["Lon"] if len(hp) else gps["lon"],
                                    height=520, zoom=16.3))
    return fig


def _gnss_day(day: str, athletes: list[str]):
    track = _load(day, "gps_track")
    g1, g2 = st.columns([2, 3])
    ath = g1.selectbox("Athlete", athletes, key="gnss_ath")
    d = track[track["Athlet"] == ath]
    okd = d.loc[~d["gefiltert"], "t_min"]
    lo, hi = float(okd.quantile(0.001)), float(okd.quantile(0.999))
    fmt = lambda m: f"{int(m // 60):02d}:{int(m % 60):02d}"
    to_t = lambda m: _dt.time(int(m // 60) % 24, int(m % 60))
    t_rng = g2.slider("Time window", min_value=to_t(lo), max_value=to_t(min(hi + 1, 1439)),
                      value=(to_t(lo), to_t(min(hi + 1, 1439))), step=_dt.timedelta(minutes=1),
                      format="HH:mm", key=f"gnss_rng_{ath}")
    rng = (t_rng[0].hour * 60 + t_rng[0].minute, t_rng[1].hour * 60 + t_rng[1].minute + 1)
    d = d[(d["t_min"] >= rng[0]) & (d["t_min"] <= rng[1])]
    ok, bad = d[~d["gefiltert"]], d[d["gefiltert"]]
    show_bad = st.checkbox(f"Show filtered-out GPS points ({len(bad)})", value=False, key="gnss_bad")
    c = st.columns(4)
    c[0].metric("GPS points (5 Hz)", f"{len(ok)}")
    c[1].metric("Max. speed", f"{ok['speed_kmh'].max():.0f} km/h" if len(ok) else "–")
    c[2].metric("Altitude min–max", f"{ok['alt'].min():.0f}–{ok['alt'].max():.0f} m" if len(ok) else "–")
    c[3].metric("Filtered out", f"{len(bad)}")
    if ok.empty:
        st.info("No valid GPS points in this time window.")
        return
    tr = [go.Scattermap(lat=ok["lat"], lon=ok["lon"], mode="markers",
                        marker=dict(size=5, color=ok["speed_kmh"], colorscale="Turbo", cmin=0,
                                    cmax=max(40, float(ok["speed_kmh"].quantile(0.995))),
                                    colorbar=dict(title="km/h", thickness=12, x=0.98)),
                        text=ok["Zeit"], name="GPS", hovertemplate="%{text} · %{marker.color:.1f} km/h<extra></extra>")]
    if show_bad and len(bad):
        tr.append(go.Scattermap(lat=bad["lat"], lon=bad["lon"], mode="markers",
                                marker=dict(size=6, color="black", opacity=0.6), text=bad["Zeit"],
                                name="filtered out", hovertemplate="%{text} · filtered<extra></extra>"))
    fig = go.Figure(tr)
    fig.update_layout(**_map_layout(ok["lat"], ok["lon"], height=600, zoom=14.5))
    st.plotly_chart(fig, width="stretch", config={"scrollZoom": True})
    f = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                      subplot_titles=("Speed (km/h)", "Altitude (m)"))
    f.add_trace(go.Scatter(x=ok["t_min"], y=ok["speed_kmh"], mode="lines", line=dict(color=SS_RED, width=1),
                           text=ok["Zeit"], hovertemplate="%{text} · %{y:.1f} km/h<extra></extra>"), row=1, col=1)
    f.add_trace(go.Scatter(x=ok["t_min"], y=ok["alt"], mode="lines", line=dict(color=INK, width=1),
                           text=ok["Zeit"], hovertemplate="%{text} · %{y:.0f} m<extra></extra>"), row=2, col=1)
    ticks = np.arange(np.floor(ok["t_min"].min() / 15) * 15, ok["t_min"].max() + 15, 15)
    f.update_xaxes(tickvals=ticks, ticktext=[fmt(t) for t in ticks])
    f.update_layout(template="plotly_white", height=420, showlegend=False, margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(f, width="stretch")


def _jumps_map(day: str, jumps: pd.DataFrame, sel: list, col: str, colour: str):
    hp = jumps.dropna(subset=["Lat", "Lon"])
    if hp.empty:
        st.info("No jumps with a GPS position.")
        return
    show_track = st.checkbox("Show day track (filtered GPS)", value=False)
    tr = []
    if show_track:
        track = _load(day, "gps_track")
        track = track[track["Athlet"].isin(sel) & ~track["gefiltert"]].iloc[::5]
        for a, d in track.groupby("Athlet"):
            tr.append(go.Scattermap(lat=d["lat"], lon=d["lon"], mode="markers", marker=dict(size=3, opacity=0.5),
                                    name=a, hovertemplate=a + " · %{text}<extra></extra>", text=d["Zeit"]))
    tr.append(go.Scattermap(lat=hp["Lat"], lon=hp["Lon"], mode="markers",
                            marker=dict(size=10, color=hp[col], colorscale="Reds" if col == "Peak_g" else "Turbo",
                                        colorbar=dict(title=colour, thickness=12, x=0.98), opacity=0.9),
                            name="Jumps", text=hp["Athlet"] + " · " + hp["Run"] + " · " + pd.Series(_jump_label(hp), index=hp.index),
                            customdata=np.c_[hp["Peak_g"], hp["Airtime_s"], hp["Speed_kmh"]],
                            hovertemplate="%{text}<br>%{customdata[0]:.1f} g · %{customdata[1]:.2f} s · "
                                          "%{customdata[2]:.0f} km/h<extra></extra>"))
    fig = go.Figure(tr)
    fig.update_layout(**_map_layout(hp["Lat"], hp["Lon"], height=600, zoom=16.3))
    st.plotly_chart(fig, width="stretch", config={"scrollZoom": True})


def _quality(day: str):
    st.dataframe(_load(day, "qc"), hide_index=True, width="stretch",
                 column_config={"Athlet": "Athlete", "Sprünge_in_Runs": "Jumps detected in runs",
                                "Kicker": "Kicker jumps (plausible)", "GPS_Punkte": "GPS points",
                                "GPS_gefiltert": "GPS points removed", "GPS_gefiltert_pct": "removed (%)"})
