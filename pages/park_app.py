"""
Park app: page structure with a global filter (sessions, athletes, kicker jumps only).

Sections: Team · Overview · Athlete · Compare · Park & GPS · Method.
All data comes from data/<YYYYMMDD_Ort>/*.parquet (built with tools/build_park_data.py).
Same look and structure as the halfpipe dashboard. UI language: English.
"""
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from pages.park_page import (SS_RED, INK, GREY, SPORTS, _days_for, _load, _day_label, _run_plot, _run_map, _gnss_day,
                             _jumps_map, _quality, _jump_label)
from utils import brand

DAY_COLOURS = [INK, SS_RED, GREY, "#39C3D4", "#8B0E13", "#1E8A97", "#F28C96", "#C00418"]
ATHLETE_COLOURS = brand.SEQ
KICKER_COLOURS = {"K1": INK, "K2": SS_RED, "K3": GREY}

METRICS = {  # label -> (column, unit, format)
    "Airtime": ("Airtime_s", "s", "%.2f"),
    "Landing peak": ("Peak_g", "g", "%.1f"),
    "Landing impulse": ("Landeimpuls_025_gs", "g·s", "%.2f"),
    "Speed at take-off": ("Speed_kmh", "km/h", "%.0f"),
    "Approach speed": ("Speed_Anfahrt_kmh", "km/h", "%.0f"),
}
BASE_COLS = {"Athlet": "Athlete", "Messtag": "Session", "Run": "Run", "Start": "Start", "Sprünge": "Jumps",
             "Kicker": "Kicker jumps", "Runs": "Runs", "Zeit": "Time", "KickerLabel": "Kicker"}


def _short_day(day: str) -> str:
    return f"{day[6:8]}.{day[4:6]}.{day[2:4]}" if len(day) >= 8 else day


def _set(key: str, value):
    st.session_state[key] = value


def _table(df: pd.DataFrame, key: str, column_config: dict, height: int | None = None):
    """Table with a search box: keeps rows where any cell contains the search text (case-insensitive)."""
    q = st.text_input("Search", key=f"q_{key}", placeholder="Search (e.g. athlete, run, session, value)",
                      label_visibility="collapsed")
    if q:
        txt = df.astype(str).apply(lambda col: col.str.contains(q, case=False, regex=False))
        df = df[txt.any(axis=1)]
        st.caption(f"{len(df)} matching rows")
    kw = dict(height=height) if height else {}
    st.dataframe(df, hide_index=True, width="stretch", column_config=column_config, **kw)


# ── Data & filter ──────────────────────────────────────────────────────────

# ── Unusual jumps: everything stays in the data, these jumps are only marked red ──
FLAG_IMPULSE_X = 1.8     # landing impulse ≥ 1.8 × the athlete's median of that session ...
FLAG_SHORT_S = 0.25      # ... and airtime ≥ 0.25 s shorter than the athlete's median on that kicker
FLAG_LONG_AIR_S = 2.6    # airtime ≥ 2.6 s ...
FLAG_SOFT_G = 7.0        # ... with a landing peak ≤ 7 g (corr.)


def flag_jumps(j: pd.DataFrame) -> pd.Series:
    """Reason why a kicker jump looks unusual (empty string = normal). Per athlete and session,
    so the result does not depend on the filter."""
    out = pd.Series("", index=j.index, dtype=object)
    k = j[j["Plausibel"]]
    if k.empty:
        return out
    by = [k["Tag"], k["Athlet"]]
    imp_med = k.groupby(by)["Landeimpuls_025_gs"].transform("median")
    air_med_k = k.groupby(by + [k["Kicker"]])["Airtime_s"].transform("median")
    hard_short = (k["Landeimpuls_025_gs"] >= FLAG_IMPULSE_X * imp_med) & (k["Airtime_s"] <= air_med_k - FLAG_SHORT_S)
    long_soft = (k["Airtime_s"] >= FLAG_LONG_AIR_S) & (k["Peak_g"] <= FLAG_SOFT_G)
    for i in k.index[hard_short]:
        out[i] = (f"Short, hard landing – impulse {k.at[i, 'Landeimpuls_025_gs'] / imp_med[i]:.1f}× usual, "
                  f"airtime {air_med_k[i] - k.at[i, 'Airtime_s']:.2f} s shorter (possible crash)")
    for i in k.index[long_soft]:
        out[i] = (f"Long flight ({k.at[i, 'Airtime_s']:.2f} s) with soft landing ({k.at[i, 'Peak_g']:.1f} g) "
                  "– possible fall or missed landing")
    return out


CHECK_STYLE = "background-color: #FDEDEF; color: #8B0E13; font-weight: 600"


def _style_check(df: pd.DataFrame, flag_col: str = "Check"):
    """Rows with a check reason in red (Swiss-Ski red tint)."""
    fmt = {c: f for c, f in {"Airtime_s": "{:.2f}", "Peak_g": "{:.1f}", "Peak_g_roh": "{:.1f}",
                             "Landeimpuls_025_gs": "{:.2f}", "Speed_kmh": "{:.0f}",
                             "Speed_Anfahrt_kmh": "{:.0f}"}.items() if c in df.columns}
    return (df.style.apply(lambda r: [CHECK_STYLE if r[flag_col] else "" for _ in r], axis=1)
            .format(fmt, na_rep="–"))


def _check_table(jf: pd.DataFrame, key: str, with_athlete: bool = True):
    c = jf[jf["Check"] != ""].sort_values(["Tag", "Athlet", "Run", "Sprung"])
    st.markdown(f"#### Jumps to check ({len(c)})")
    if c.empty:
        st.caption("No unusual kicker jumps in the selection.")
        return
    cols = (["Messtag", "Athlet"] if with_athlete else ["Messtag"]) + [
        "Run", "KickerLabel", "Zeit", "Airtime_s", "Peak_g", "Landeimpuls_025_gs", "Speed_kmh", "Check"]
    st.dataframe(_style_check(c[cols].round(2)), hide_index=True, width="stretch", key=key,
                 column_config={**BASE_COLS, "Airtime_s": "Airtime (s)", "Peak_g": "Landing peak (g)",
                                "Landeimpuls_025_gs": "Landing impulse (g·s)", "Speed_kmh": "Speed (km/h)",
                                "Check": st.column_config.TextColumn("Why to check", width="large")})
    st.caption("Marked automatically, nothing is removed: the jumps stay in all values. "
               "Check them with video or the coach (rules on the Method page).")


@st.cache_data(show_spinner=False)
def _days_data(days: tuple, sport: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    jumps, runs = [], []
    for d in days:
        jumps.append(_load(d, "jumps").assign(Tag=d))
        runs.append(_load(d, "runs").assign(Tag=d))
    if not jumps:
        return pd.DataFrame(), pd.DataFrame()
    j, r = pd.concat(jumps, ignore_index=True), pd.concat(runs, ignore_index=True)
    j, r = j[j["Sport"] == sport].reset_index(drop=True), r[r["Sport"] == sport].reset_index(drop=True)
    j["KickerLabel"] = [f"K{int(k)}" if pd.notna(k) else "–" for k in j["Kicker"]]
    j["Check"] = flag_jumps(j)
    for df in (j, r):
        df["Messtag"] = df["Tag"].map(_day_label)
    return j, r


def filters(sport: str) -> dict | None:
    """Global filter at the top of every page (within the chosen sport). Returns the filtered data."""
    days = _days_for(sport)
    if not days:
        st.info(f"No {sport.lower()} sessions in the dashboard yet.")
        return None
    # the session list depends on the sport: reset the selection when the sport changes
    if st.session_state.get("_f_sport") != sport:
        st.session_state["_f_sport"] = sport
        st.session_state["f_days"] = days
        st.session_state.pop("f_ath", None)
    if "f_days" not in st.session_state:
        st.session_state["f_days"] = days
    st.session_state["f_days"] = [d for d in st.session_state["f_days"] if d in days]

    c1, c3 = st.columns([5, 1.3])
    sel_days = c1.pills("Sessions", days, selection_mode="multi", format_func=_day_label, key="f_days")
    with c1.container(horizontal=True, gap="medium"):
        st.button("All", key="f_days_all", on_click=_set, args=("f_days", days), type="tertiary")
        st.button("None", key="f_days_none", on_click=_set, args=("f_days", []), type="tertiary")
    only_k = c3.toggle("Kicker jumps only", value=True, key="f_kicker",
                       help="Kicker jump = flight time ≥ 1.4 s, max. 3 per run (method of the master thesis). "
                            "Switch off to count all detected jumps (e.g. shorter jumps on rollers).")
    jumps_all, runs_all = _days_data(tuple(sorted(sel_days or [])), sport)
    athletes = sorted(runs_all["Athlet"].unique()) if len(runs_all) else []
    if "f_ath" not in st.session_state:
        st.session_state["f_ath"] = athletes
    st.session_state["f_ath"] = [a for a in st.session_state["f_ath"] if a in athletes]
    sel_ath = st.pills("Athletes", athletes, selection_mode="multi", key="f_ath",
                       help="Click a name to select or deselect it.")
    with st.container(horizontal=True, gap="medium"):
        st.button("All", key="f_ath_all", on_click=_set, args=("f_ath", athletes), type="tertiary")
        st.button("None", key="f_ath_none", on_click=_set, args=("f_ath", []), type="tertiary")
    if not sel_days or not sel_ath:
        st.info("Choose at least one session and one athlete.")
        return None
    jumps = jumps_all[jumps_all["Athlet"].isin(sel_ath)]
    runs = runs_all[runs_all["Athlet"].isin(sel_ath)]
    jumps_f = jumps[jumps["Plausibel"]] if only_k else jumps
    return dict(days=sorted(sel_days), athletes=sel_ath, jumps=jumps, jumps_f=jumps_f, runs=runs, only_k=only_k,
                sport=sport)


def _metric_rows(items: list[tuple[str, str]], per_row: int = 5):
    for i in range(0, len(items), per_row):
        cols = st.columns(per_row)
        for c, (k, v) in zip(cols, items[i:i + per_row]):
            c.metric(k, v)


def _fmt(v, f):
    return f % v if pd.notna(v) else "–"


def _kpis(F: dict, jf: pd.DataFrame, runs: pd.DataFrame, extra: list | None = None):
    n = len(jf)
    items = (extra or []) + [
        ("Runs", f"{len(runs)}"),
        ("Kicker jumps" if F["only_k"] else "Jumps", f"{n}"),
        ("Avg. jumps per run", _fmt(n / len(runs), "%.1f") if len(runs) else "–"),
        ("Avg. airtime", _fmt(jf["Airtime_s"].mean(), "%.2f s")),
        ("Max. airtime", _fmt(jf["Airtime_s"].max(), "%.2f s")),
        ("Avg. landing peak", _fmt(jf["Peak_g"].mean(), "%.1f g")),
        ("Max. landing peak", _fmt(jf["Peak_g"].max(), "%.1f g")),
        ("Avg. landing impulse", _fmt(jf["Landeimpuls_025_gs"].mean(), "%.2f g·s")),
        ("Max. speed", _fmt(runs["Speed_max_kmh"].max(), "%.0f km/h")),
        ("Landings at 16 g", _fmt(100 * jf["Geclippt_16g"].mean(), "%.0f %%") if n else "–"),
    ]
    _metric_rows(items)
    st.caption(("Kicker jumps only (≥ 1.4 s, max. 3 per run). " if F["only_k"] else "All detected jumps. ")
               + "Landing peak bias-corrected (hip sensor); landing impulse = net impulse 0–0.25 s after landing "
               "(validated with force plate). «Landings at 16 g»: the sensor range was reached, the real peak "
               "is higher than shown.")


def _agg(jf: pd.DataFrame, runs: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    agg = jf.groupby(by).agg(
        Sprünge=("Sprung", "size"), Airtime_mittel_s=("Airtime_s", "mean"), Airtime_max_s=("Airtime_s", "max"),
        Peak_g_mittel=("Peak_g", "mean"), Peak_g_max=("Peak_g", "max"),
        Impuls_mittel_gs=("Landeimpuls_025_gs", "mean"), Impuls_max_gs=("Landeimpuls_025_gs", "max"),
        Speed_Absprung_kmh=("Speed_kmh", "mean"), Clip_pct=("Geclippt_16g", lambda x: 100 * x.mean()))
    agg.insert(0, "Runs", runs.groupby(by).size())
    agg["Speed_max_kmh"] = runs.groupby(by)["Speed_max_kmh"].max()
    agg = agg.reset_index()
    if "Tag" in by:
        agg.insert(0, "Messtag", agg.pop("Tag").map(_day_label))
    return agg


AGG_COLS = {**BASE_COLS,
    "Airtime_mittel_s": st.column_config.NumberColumn("Avg. airtime", format="%.2f s"),
    "Airtime_max_s": st.column_config.NumberColumn("Max. airtime", format="%.2f s"),
    "Peak_g_mittel": st.column_config.NumberColumn("Avg. landing peak", format="%.1f g"),
    "Peak_g_max": st.column_config.NumberColumn("Max. landing peak", format="%.1f g"),
    "Impuls_mittel_gs": st.column_config.NumberColumn("Avg. landing impulse", format="%.2f g·s",
                                                      help="Net impulse 0–0.25 s after landing"),
    "Impuls_max_gs": st.column_config.NumberColumn("Max. landing impulse", format="%.2f g·s"),
    "Speed_Absprung_kmh": st.column_config.NumberColumn("Avg. speed at take-off", format="%.0f km/h"),
    "Speed_max_kmh": st.column_config.NumberColumn("Max. speed", format="%.0f km/h"),
    "Clip_pct": st.column_config.NumberColumn("Landings at 16 g", format="%.0f %%"),
}

DAY_METRICS = [("Airtime_median_s", "Airtime (s)", "median per jump", "%.2f s"),
               ("Peak_g_mittel", "Landing peak (g)", "mean, corrected", "%.1f g"),
               ("Impuls_mittel_gs", "Landing impulse (g·s)", "mean", "%.2f"),
               ("Speed_Absprung_kmh", "Speed at take-off (km/h)", "median", "%.0f")]


def _day_summary(jf: pd.DataFrame, runs: pd.DataFrame) -> pd.DataFrame:
    s = jf.groupby("Tag").agg(Sprünge=("Sprung", "size"), Airtime_median_s=("Airtime_s", "median"),
                              Airtime_max_s=("Airtime_s", "max"), Peak_g_mittel=("Peak_g", "mean"),
                              Peak_g_max=("Peak_g", "max"), Impuls_mittel_gs=("Landeimpuls_025_gs", "mean"),
                              Speed_Absprung_kmh=("Speed_kmh", "median"))
    s.insert(0, "Runs", runs.groupby("Tag").size())
    s["Speed_max_kmh"] = runs.groupby("Tag")["Speed_max_kmh"].max()
    s = s.reset_index()
    s.insert(0, "Messtag", s["Tag"].map(_day_label))
    return s


def _dev_chart(summ: pd.DataFrame, title_suffix: str = ""):
    metrics = [m for m in DAY_METRICS if m[0] in summ.columns]
    fig = make_subplots(rows=1, cols=len(metrics),
                        subplot_titles=[f"{t}<br><sup>{sub}</sup>" for _, t, sub, _ in metrics])
    for i, (c, t, _, fmt) in enumerate(metrics, start=1):
        fig.add_trace(go.Scatter(x=summ["Tag"].map(_short_day), y=summ[c], mode="lines+markers+text",
                                 line=dict(color=SS_RED, width=2),
                                 marker=dict(size=10, color=SS_RED, line=dict(color="white", width=2)),
                                 text=[fmt % v if pd.notna(v) else "" for v in summ[c]], textposition="top center",
                                 cliponaxis=False, showlegend=False,
                                 hovertemplate="%{x}: %{text}<extra>" + t + "</extra>"), row=1, col=i)
        lo, hi = summ[c].min(), summ[c].max()
        pad = max((hi - lo) * 0.6, abs(hi) * 0.08) if pd.notna(hi) else 1
        fig.update_yaxes(range=[lo - pad, hi + pad], row=1, col=i)
    fig.update_layout(template="plotly_white", height=330, margin=dict(l=10, r=10, t=70, b=10),
                      title=f"Development across sessions{title_suffix}" if title_suffix else None)
    fig.update_annotations(font_size=12)
    st.plotly_chart(fig, width="stretch")


# ── Team cards ──

CARD_CSS = """
<style>
.tc-card { background:#fff; border:1px solid #E3E3E3; border-radius:14px; margin-bottom:6px; overflow:hidden; }
.tc-head { display:flex; align-items:center; gap:14px; padding:16px 20px; border-bottom:1px solid #eee; }
.tc-av { width:46px; height:46px; border-radius:10px; background:#3E3E3E; color:#fff; display:flex; align-items:center;
         justify-content:center; font-weight:700; font-size:17px; letter-spacing:.03em; }
.tc-name { font-size:21px; font-weight:700; color:#3E3E3E; }
.tc-body { padding:14px 20px 18px; }
.tc-stance { margin-left:auto; font-size:12px; font-weight:700; letter-spacing:.06em; text-transform:uppercase;
             color:#6E6E6E; background:#F4F4F4; padding:4px 10px; border-radius:999px; }
.tc-sub { display:flex; align-items:center; gap:10px; margin-bottom:12px; }
.tc-sub b { font-size:13px; letter-spacing:.08em; color:#3E3E3E; }
.tc-badge { background:#FDEDEF; color:#C00418; font-size:12px; font-weight:700; letter-spacing:.05em; padding:3px 9px;
            border-radius:999px; }
.tc-grid { display:grid; grid-template-columns:repeat(4, 1fr); gap:10px; }
.tc-tile { background:#F7F7F7; border:1px solid #E8E8E8; border-radius:10px; padding:10px 12px; min-height:92px; }
.tc-tile.best { background:#FDEDEF; border-color:#F5B3BB; }
.tc-v { font-size:22px; font-weight:700; color:#3E3E3E; line-height:1.15; }
.tc-tile.best .tc-v { color:#E2001A; }
.tc-tile.check { border:2px dashed #8B0E13; }
.tc-chk { font-size:10px; font-weight:700; letter-spacing:.06em; color:#8B0E13; text-transform:uppercase; }
.tc-l { font-size:13px; color:#6E6E6E; margin-top:2px; }
.tc-s { font-size:12px; color:#6E6E6E; margin-top:4px; }
.tc-s b { color:#3E3E3E; }
.tc-flag { font-size:10px; font-weight:700; letter-spacing:.06em; color:#E2001A; text-transform:uppercase; }
@media (max-width: 900px) { .tc-grid { grid-template-columns:repeat(2, 1fr); } }
</style>
"""

CARD_KPIS = [  # key, label, format (higher = team best)
    ("avg_g", "Avg. landing g", "{:.1f} g"),
    ("max_g", "Max. landing g", "{:.1f} g"),
    ("avg_imp", "Avg. landing impulse", "{:.2f} g·s"),
    ("max_imp", "Max. landing impulse", "{:.2f} g·s"),
    ("max_speed", "Max. speed", "{:.0f} km/h"),
    ("avg_to", "Avg. speed at take-off", "{:.0f} km/h"),
    ("avg_air", "Avg. airtime", "{:.2f} s"),
    ("max_air", "Max. airtime", "{:.2f} s"),
    ("jumps", "Kicker jumps", "{:.0f}"),
    ("runs", "Runs", "{:.0f}"),
]


MAX_KEYS = {"max_g": "Peak_g", "max_imp": "Landeimpuls_025_gs", "max_air": "Airtime_s"}


def _max_flagged(jf: pd.DataFrame) -> set:
    """Card keys whose maximum comes from a jump marked for checking."""
    if jf.empty:
        return set()
    return {key for key, col in MAX_KEYS.items()
            if jf[col].notna().any() and jf.at[jf[col].idxmax(), "Check"] != ""}


def _card_values(jf: pd.DataFrame, runs: pd.DataFrame) -> dict:
    e = len(jf) == 0
    return dict(
        avg_g=np.nan if e else jf["Peak_g"].mean(), max_g=np.nan if e else jf["Peak_g"].max(),
        avg_imp=np.nan if e else jf["Landeimpuls_025_gs"].mean(),
        max_imp=np.nan if e else jf["Landeimpuls_025_gs"].max(),
        max_speed=runs["Speed_max_kmh"].max() if len(runs) else np.nan,
        avg_to=np.nan if e else jf["Speed_kmh"].mean(),
        avg_air=np.nan if e else jf["Airtime_s"].mean(), max_air=np.nan if e else jf["Airtime_s"].max(),
        jumps=len(jf), runs=len(runs), per_run=len(jf) / len(runs) if len(runs) else np.nan)


def _open_athlete(name: str):
    st.session_state["active_tab"] = "Athlete"
    st.session_state["pa_ath"] = name
    st.session_state["_scroll_top"] = True


def _sensor_of(jumps: pd.DataFrame, a: str, day: str) -> str:
    s = jumps.loc[(jumps["Athlet"] == a) & (jumps["Tag"] == day), "Sensor"].dropna()
    return f"Sensor {int(s.iloc[0]):02d}" if len(s) else ""


def page_team(F: dict):
    jumps, runs = F["jumps"], F["runs"]
    jk = jumps[jumps["Plausibel"]]  # cards always on kicker jumps
    rows = {}
    for a in F["athletes"]:
        ra = runs[runs["Athlet"] == a]
        if ra.empty:
            continue
        ja = jk[jk["Athlet"] == a]
        last = ra["Tag"].max()
        rows[a] = dict(total=_card_values(ja, ra), last_day=last, n_days=ra["Tag"].nunique(), check=_max_flagged(ja),
                       last=_card_values(ja[ja["Tag"] == last], ra[ra["Tag"] == last]))
    if not rows:
        st.info("No runs for the selected athletes and sessions.")
        return

    team = _card_values(jk, runs)
    st.markdown("#### Team")
    _metric_rows([(label, fmt.format(team[key]) if pd.notna(team[key]) else "–") for key, label, fmt in CARD_KPIS])

    s1, _ = st.columns([1, 3])
    order_by = s1.selectbox("Sort cards by", ["Name"] + [label for _, label, _ in CARD_KPIS], key="tc_sort")
    names = sorted(rows)
    if order_by != "Name":
        key = next(k_ for k_, label, _ in CARD_KPIS if label == order_by)
        names = sorted(rows, key=lambda a: -(rows[a]["total"][key] if pd.notna(rows[a]["total"][key]) else -1e9))
    best = {key: max((rows[a]["total"][key] for a in rows if pd.notna(rows[a]["total"][key])), default=None)
            for key, _, _ in CARD_KPIS}
    multi = len(F["days"]) > 1

    st.markdown(CARD_CSS, unsafe_allow_html=True)
    cols = st.columns(2)
    for i, a in enumerate(names):
        r = rows[a]
        tiles = []
        for key, label, fmt in CARD_KPIS:
            v, lv = r["total"][key], r["last"][key]
            is_best = len(rows) > 1 and pd.notna(v) and v == best[key]
            sub = (f'<div class="tc-s">Last session <b>{fmt.format(lv)}</b></div>'
                   if multi and r["n_days"] > 1 and pd.notna(lv) else "")
            chk = key in r["check"]
            flag = ('<div class="tc-flag">Team best</div>' if is_best else "") + (
                '<div class="tc-chk">Check – from a marked jump</div>' if chk else "")
            tiles.append(f'<div class="tc-tile{" best" if is_best else ""}{" check" if chk else ""}">{flag}'
                         f'<div class="tc-v">{fmt.format(v) if pd.notna(v) else "–"}</div>'
                         f'<div class="tc-l">{label}</div>{sub}</div>')
        days_txt = f"{r['n_days']} session{'s' if r['n_days'] > 1 else ''}"
        html = (f'<div class="tc-card"><div class="tc-head"><div class="tc-av">{a[:2].upper()}</div>'
                f'<div class="tc-name">{a}</div><div class="tc-stance">{_sensor_of(jumps, a, r["last_day"])}</div>'
                f'</div><div class="tc-body"><div class="tc-sub"><b>KEY FIGURES</b>'
                f'<span class="tc-badge">LAST {_day_label(r["last_day"]).split(" · ")[0]}</span>'
                f'<span class="tc-s">{days_txt}</span></div><div class="tc-grid">{"".join(tiles)}</div></div></div>')
        with cols[i % 2]:
            st.markdown(html, unsafe_allow_html=True)
            st.button(f"Open {a} →", key=f"tc_open_{a}", on_click=_open_athlete, args=(a,),
                      use_container_width=True, help=f"Show {a} on the Athlete page")
            st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    st.caption(("Values over all selected sessions; «Last session» = the athlete's most recent selected session. "
                if multi else "") + "Cards always count kicker jumps (≥ 1.4 s, max. 3 per run). Landing g "
               "bias-corrected; when the 16 g sensor range is reached the real peak is higher. Red = team best. "
               "Dashed dark-red frame = the maximum comes from a jump marked for checking (see Overview).")


# ── Pages ──────────────────────────────────────────────────────────────────

def page_overview(F: dict):
    jf, runs = F["jumps_f"], F["runs"]
    _kpis(F, jf, runs, extra=[("Sessions", f"{len(F['days'])}"), ("Athletes", f"{len(F['athletes'])}")])

    if len(F["days"]) > 1:
        _dev_chart(_day_summary(jf, runs))
        st.caption("Team values per session. The line-up changes from session to session – "
                   "for a fair development look at individual athletes under «Athlete» or «Compare».")

    st.markdown("#### Overview per athlete")
    split = st.radio("Grouping", ["Total over selected sessions", "Per session"], horizontal=True,
                     key="ov_split", label_visibility="collapsed")
    by = ["Athlet"] if split.startswith("Total") or len(F["days"]) == 1 else ["Athlet", "Tag"]
    _table(_agg(jf, runs, by), "ov_agg", AGG_COLS)

    st.markdown("#### Per kicker")
    jk = jf.dropna(subset=["Kicker"])
    if len(jk):
        k = jk.groupby("KickerLabel").agg(Sprünge=("Sprung", "size"), Airtime_mittel_s=("Airtime_s", "mean"),
                                          Airtime_max_s=("Airtime_s", "max"), Peak_g_mittel=("Peak_g", "mean"),
                                          Peak_g_max=("Peak_g", "max"),
                                          Impuls_mittel_gs=("Landeimpuls_025_gs", "mean"),
                                          Speed_Absprung_kmh=("Speed_kmh", "mean"),
                                          Clip_pct=("Geclippt_16g", lambda x: 100 * x.mean())).reset_index()
        st.dataframe(k, hide_index=True, width="stretch", column_config=AGG_COLS)
        st.caption("K1–K3 = 1st to 3rd kicker jump within a run (order in the run, not a fixed kicker of the park).")

    _check_table(jf, "ov_check")

    with st.expander(f"All runs ({len(runs)})"):
        cols = ["Messtag", "Athlet", "Run", "Start", "Dauer_s", "Hoehenverlust_m", "Sprünge", "Kicker",
                "Airtime_mittel_s", "Airtime_max_s", "Peak_g_mittel", "Peak_g_max", "Speed_max_kmh"]
        _table(runs[[c for c in cols if c in runs.columns]].round(2), "ov_runs",
               column_config={**AGG_COLS, "Dauer_s": "Duration (s)", "Hoehenverlust_m": "Altitude loss (m)"})


def page_athlete(F: dict):
    a1, _ = st.columns([1, 3])
    if st.session_state.pop("_scroll_top", False):
        import streamlit.components.v1 as components
        components.html("<script>const d=window.parent.document;"
                        "(d.querySelector('[data-testid=\"stMain\"]')||d.scrollingElement).scrollTo(0,0);"
                        "window.parent.scrollTo(0,0);</script>", height=0)
    ath = a1.selectbox("Athlete", F["athletes"], key="pa_ath")
    jumps = F["jumps"][F["jumps"]["Athlet"] == ath]
    jf = F["jumps_f"][F["jumps_f"]["Athlet"] == ath]
    runs = F["runs"][F["runs"]["Athlet"] == ath]
    days = sorted(runs["Tag"].unique())
    if not days:
        st.info(f"{ath} has no runs in the selected sessions.")
        return
    _kpis(F, jf, runs, extra=[("Sessions", f"{len(days)}")])

    summ = _day_summary(jf, runs)
    if len(days) > 1:
        _dev_chart(summ, f" · {ath}")
    st.markdown("#### Metrics per session")
    _table(summ.drop(columns="Tag"), "pa_days", {**AGG_COLS,
           "Airtime_median_s": st.column_config.NumberColumn("Airtime (median)", format="%.2f s"),
           "Speed_Absprung_kmh": st.column_config.NumberColumn("Speed at take-off (median)", format="%.0f km/h")})

    k1, k2 = st.columns(2)
    jk = jf.dropna(subset=["Kicker"]).sort_values(["Tag", "Kicker"])
    for c, col, unit, title in [(k1, "Airtime_s", "s", "Airtime per kicker"),
                                (k2, "Peak_g", "g", "Landing peak per kicker (corr.)")]:
        f = px.box(jk, x="KickerLabel", y=col, points="all", color="Messtag" if len(days) > 1 else None,
                   color_discrete_sequence=DAY_COLOURS if len(days) > 1 else [SS_RED], title=title,
                   labels={col: unit, "KickerLabel": "", "Messtag": "Session"},
                   category_orders={"KickerLabel": ["K1", "K2", "K3"]})
        f.update_layout(template="plotly_white", height=360, margin=dict(l=10, r=10, t=40, b=10))
        c.plotly_chart(f, width="stretch")

    _check_table(jf, "pa_check", with_athlete=False)

    st.markdown("#### Run in detail")
    r1, r2 = st.columns([1, 3])
    day = r1.selectbox("Session", days[::-1], format_func=_day_label, key="pa_day")
    rr = runs[runs["Tag"] == day].set_index("Run")
    flagged_runs = set(jumps.loc[(jumps["Tag"] == day) & (jumps["Check"] != ""), "Run"])
    run = r2.selectbox("Run", rr.index.tolist(), key="pa_run",
                       format_func=lambda r: f"{r} · {rr.loc[r, 'Start']} · {int(rr.loc[r, 'Kicker'])} kicker jumps"
                                             + (f" · avg. airtime {rr.loc[r, 'Airtime_mittel_s']:.2f} s"
                                                if pd.notna(rr.loc[r, 'Airtime_mittel_s']) else "")
                                             + ("  ·  CHECK" if r in flagged_runs else ""))
    _run_detail(day, ath, run, jumps[(jumps["Tag"] == day) & (jumps["Run"] == run)])


def _run_detail(day: str, ath: str, run: str, h: pd.DataFrame):
    ts = _load(day, "imu_runs"); ts = ts[(ts["Athlet"] == ath) & (ts["Run"] == run)]
    gps = _load(day, "gps_runs"); gps = gps[(gps["Athlet"] == ath) & (gps["Run"] == run)]
    st.plotly_chart(_run_plot(ts, gps, h), width="stretch")
    st.caption("Red = kicker jump (K1–K3), grey = detected jump that does not count (reason in the table). "
               "Blue band = flight phase. Dark-red ring = jump marked for checking.")
    if len(gps):
        st.plotly_chart(_run_map(gps, h), width="stretch", config={"scrollZoom": True})
    t = h.assign(Label=_jump_label(h))
    cols = ["Label", "Zeit", "Airtime_s", "Peak_g", "Peak_g_roh", "Landeimpuls_025_gs", "Speed_kmh",
            "Speed_Anfahrt_kmh", "Geclippt_16g", "Grund", "Check"]
    st.dataframe(_style_check(t[cols].round(2)), hide_index=True, width="stretch",
                 column_config={**BASE_COLS, "Label": "Jump", "Airtime_s": "Airtime (s)",
                                "Peak_g": "Landing peak (g, corr.)", "Peak_g_roh": "Landing peak (g, raw)",
                                "Landeimpuls_025_gs": "Landing impulse (g·s)", "Speed_kmh": "Speed at take-off (km/h)",
                                "Speed_Anfahrt_kmh": "Approach speed (km/h)", "Geclippt_16g": "16 g reached",
                                "Grund": "Not counted because",
                                "Check": st.column_config.TextColumn("Why to check", width="large")})


def page_compare(F: dict):
    jf, runs = F["jumps_f"], F["runs"]
    if len(F["athletes"]) < 2:
        st.info("Choose at least two athletes in the filter above to compare.")
    c1, c2 = st.columns([2, 2])
    name = c1.radio("Metric", list(METRICS), horizontal=True, key="pc_metric")
    col, unit, fmt = METRICS[name]
    split_by = c2.radio("Split by", ["None", "Session", "Kicker (K1–K3)"],
                        index=1 if len(F["days"]) > 1 else 0, horizontal=True, key="pc_split_by")
    split_col = {"Session": "Messtag", "Kicker (K1–K3)": "KickerLabel"}.get(split_by)

    data = jf.dropna(subset=["Kicker"]) if split_col == "KickerLabel" else jf
    order = data.groupby("Athlet")[col].median().sort_values(ascending=False).index.tolist()
    f = px.box(data.sort_values(["Tag", "Sprung"]), x="Athlet", y=col, points="all" if split_col is None else False,
               color=split_col,
               color_discrete_map=KICKER_COLOURS if split_col == "KickerLabel" else None,
               color_discrete_sequence=DAY_COLOURS if split_col else [SS_RED],
               category_orders={"Athlet": order, "KickerLabel": ["K1", "K2", "K3"]},
               title=f"{name} per jump ({unit})",
               labels={col: unit, "Athlet": "", "Messtag": "Session", "KickerLabel": "Kicker"})
    f.update_layout(template="plotly_white", height=420, margin=dict(l=10, r=10, t=40, b=10),
                    legend=dict(orientation="h", y=1.08, x=1, xanchor="right", title=None))
    st.plotly_chart(f, width="stretch")

    if len(F["days"]) > 1:
        per = jf.groupby(["Athlet", "Tag", "Messtag"])[col].median().reset_index().sort_values("Tag")
        f = px.line(per, x="Messtag", y=col, color="Athlet", markers=True, color_discrete_sequence=ATHLETE_COLOURS,
                    title=f"{name}: development per athlete (median)",
                    labels={col: unit, "Messtag": "", "Athlet": "Athlete"})
        f.update_layout(template="plotly_white", height=400, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(f, width="stretch")

    st.markdown("#### Ranking")
    _table(_agg(jf, runs, ["Athlet"]).sort_values("Airtime_mittel_s", ascending=False), "pc_rank", AGG_COLS)

    k1, k2 = st.columns(2)
    f = px.scatter(jf, x="Speed_kmh", y="Airtime_s", color="Athlet", opacity=0.75,
                   color_discrete_sequence=ATHLETE_COLOURS, title="Speed at take-off vs. airtime",
                   labels={"Speed_kmh": "km/h", "Airtime_s": "s", "Athlet": "Athlete"})
    f.update_layout(template="plotly_white", height=380, margin=dict(l=10, r=10, t=40, b=10))
    k1.plotly_chart(f, width="stretch")
    f = px.scatter(jf, x="Airtime_s", y="Peak_g", color="Athlet", opacity=0.75,
                   color_discrete_sequence=ATHLETE_COLOURS, title="Airtime vs. landing peak",
                   labels={"Airtime_s": "s", "Peak_g": "g (corr.)", "Athlet": "Athlete"})
    f.update_layout(template="plotly_white", height=380, margin=dict(l=10, r=10, t=40, b=10))
    k2.plotly_chart(f, width="stretch")


def page_park(F: dict):
    jf = F["jumps_f"]
    p1, p3 = st.columns([3, 2])
    colour = p1.radio("Colour", ["Peak (g)", "Airtime (s)", "Speed (km/h)", "Kicker"], horizontal=True,
                      key="pp_colour")
    col = {"Peak (g)": "Peak_g", "Airtime (s)": "Airtime_s", "Speed (km/h)": "Speed_kmh", "Kicker": "Kicker"}[colour]
    day = p3.selectbox("Session", F["days"][::-1], format_func=_day_label, key="pp_day")
    jd = jf[jf["Tag"] == day]
    _jumps_map(day, jd.dropna(subset=[col]) if col == "Kicker" else jd, F["athletes"], col, colour)
    st.caption("Take-off positions (GPS, ±2–5 m depending on the sensor). Aerial image © swisstopo.")

    st.markdown("#### GNSS for the whole day")
    _gnss_day(day, [a for a in F["athletes"] if a in set(F["runs"].loc[F["runs"]["Tag"] == day, "Athlet"])]
              or F["athletes"])


def page_method(F: dict):
    st.markdown("""
#### How the values are computed
Sessions, runs and jumps are recorded with **the same method as in the master thesis** (freeski-imu).
The thesis data and its dashboard are not changed; this dashboard only reuses the method.

- **Freeski and snowboard** are evaluated with exactly the same method and shown separately
  (choose the discipline at the top). Thresholds are not yet adapted to snowboard.
- **Sensor** at the hip (IMU 200 Hz, GNSS 10 Hz), AdMos sensors as in the freeski project.
- **Sessions**: a new session starts when the sensor clock is reset (sensor restarted).
- **Runs** from GNSS per session: a run starts at > 7 m/s going downhill, pauses below 1.5 m/s and ends when
  the altitude rises by 20 m again (lift). Counted with ≥ 30 m altitude loss and ≥ 15 s duration.
- **Jumps** per run from the acceleration (vertical 0.60 g, resultant 0.70 g, crossing 1.0 g, min. 1.2 s in the air).
- **Kicker jump** = flight time ≥ 1.4 s, at most 3 per run (from Corvatsch 22.04.2026: kicker jumps fly ≥ 1.4 s,
  shorter events were on a roller below the kickers). **K1–K3** = order of the kicker jumps within the run.
- **Landing peak** bias-corrected for the hip sensor (0.4323 × raw + 3.98, validation Magglingen).
  **Landing impulse** = net impulse 0–0.25 s after landing (validated with force plate).
- **Speed at take-off** = GPS speed (3D) at take-off; **approach speed** = highest GPS speed in the 5 s before.
- **Marked for checking** (shown in dark red, nothing is removed – the jumps stay in all values):
  1. *Short, hard landing (possible crash)*: landing impulse ≥ 1.8 × the athlete's median of that session
     **and** airtime ≥ 0.25 s shorter than the athlete's median on that kicker.
  2. *Long flight, soft landing (possible fall or missed landing)*: airtime ≥ 2.6 s with a landing peak ≤ 7 g.
  Team cards show a dashed dark-red frame when an athlete's maximum comes from such a jump.
- **Limits**: each sensor axis measures up to 16 g. Landings where an axis reaches this range are marked
  («16 g reached»); their real peak is higher than shown. GPS positions are offset by a few metres depending on the sensor.
- Tricks are not recorded (no trick protocol), and rails are not evaluated.
""")
    for d in F["days"][::-1]:
        st.markdown(f"**Data quality {_day_label(d)}**")
        _quality(d, F["sport"])
