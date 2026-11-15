"""
Park (Slopestyle Freeski): prepare one measurement day for the dashboard.

Sessions, runs and jumps are recorded with the SAME method as in the master thesis
(freeski-imu, pages/analyse_page.py → _run_pipeline):
  - Sessions: sensor_lib.detect_sessions_imu / detect_sessions_gnss (timestamp resets)
  - Runs:     sensor_lib.detect_runs on GNSS per session
              (v_start 7.0 m/s, v_hold 1.5 m/s, alt_rise_end 20 m, alt_drop_min 30 m, run_duration_min 15 s)
  - Jumps:    sensor_lib.detect_jumps_snow per run (accVert 0.60 g, accRes 0.70 g, crossing 1.0 g, min. 1.2 s),
              landing parameters + bias correction hip sensor (jump_detector.compute_landing_params, «Bauch»),
              jump_detector.mark_plausible (kicker jump: flight ≥ 1.4 s, max. 3 per run)
The thesis data and dashboards are not touched; utils/sensor_lib.py and utils/jump_detector.py are copies.

Usage:
    python tools/build_park_data.py <folder with CSVs> data/YYYYMMDD_Ort --sport Freeski|Snowboard
    python tools/build_park_data.py <folder with CSVs> data/YYYYMMDD_Ort --sport-map sports.csv   (Athlet,Sport)
    python tools/build_park_data.py <day folder with FS/ and SNB/> data/YYYYMMDD_Ort           (sport from subfolder)
Freeski and snowboard of the same day go into the same folder: athletes processed in a later call
replace only their own rows, all other athletes stay (the output is merged).
File names: <Ort>_<Athlet>_<NN>_<YYYY-MM-DD>_imuData.csv / _gnssData.csv (NN = sensor number, optional).
"""
import argparse
import contextlib
import glob
import io
import os
import re
import sys

import numpy as np
import pandas as pd

APP = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, APP)
sys.path.insert(0, os.path.join(APP, "utils"))
import sensor_lib  # noqa: E402
from utils.jump_detector import preprocess_imu, detect_vertical_axis, compute_landing_params, mark_plausible  # noqa: E402
from utils.gnss_clean import clean_mask  # noqa: E402

# Method parameters from the master thesis app (analyse_page.py defaults)
JUMP = dict(th_core_accVert=0.60, th_core_accRes=0.70, th_crossing=1.0, min_duration_s=1.2)
RUNS = dict(v_start=7.0, v_hold=1.5, alt_rise_end=20.0, alt_drop_min=30.0, run_duration_min=15.0)
POSITION = "Bauch"          # sensor at the hip → bias correction from the validation (Magglingen)
PAD_S = 3.0                 # seconds before/after a run kept for the plots
APPROACH_S = 5.0            # window before take-off for the approach speed

# Names in the file → name in the dashboard
ALIASES = {"Gian": "Juan"}
NAME = re.compile(r"^(?:(?P<ort>[^_]+)_)?(?P<ath>[A-Za-z][A-Za-z]*)(?:_(?P<sensor>\d{1,3}))?_"
                  r"\d{4}-\d{2}-\d{2}_(?P<kind>imu|gnss)Data\.csv$")


def quiet(fn, *a, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


def to_local(posix_ms):
    t = pd.to_datetime(posix_ms, unit="ms", utc=True)
    return t.dt.tz_convert("Europe/Zurich") if isinstance(t, pd.Series) else t.tz_convert("Europe/Zurich")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", help="folder with *_imuData.csv / *_gnssData.csv")
    ap.add_argument("out", help="target folder, e.g. data/20261114_Corvatsch")
    ap.add_argument("--only", nargs="*", help="only these athletes (file names)")
    ap.add_argument("--sport", choices=["Freeski", "Snowboard"],
                    help="discipline of all athletes in this call (default for athletes missing in --sport-map)")
    ap.add_argument("--sport-map", help="CSV with columns Athlet,Sport (dashboard names, e.g. Juan,Freeski)")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    sports = {}
    if args.sport_map:
        m = pd.read_csv(args.sport_map)
        sports = dict(zip(m["Athlet"].astype(str).str.strip(), m["Sport"].astype(str).str.strip()))
        bad = sorted(set(sports.values()) - {"Freeski", "Snowboard"})
        if bad:
            sys.exit(f"--sport-map: unknown sport {bad} (allowed: Freeski, Snowboard)")

    def sport_of(ath: str) -> str:
        sp = sports.get(ath, args.sport)
        if sp is None:
            sys.exit(f"No sport for {ath}: add it to --sport-map or pass --sport")
        return sp

    # Day folder with FS/ (freeski) and SNB/ (snowboard) subfolders: the subfolder sets the sport.
    # The ASI/ subfolders hold the raw sensor files and are not read.
    sub = {"FS": "Freeski", "SNB": "Snowboard"}
    sources = [(os.path.join(args.src, d), sp) for d, sp in sub.items() if os.path.isdir(os.path.join(args.src, d))]
    if not sources:
        sources = [(args.src, None)]
    files, folder_sport = {}, {}
    for src, sp in sources:
        for f in sorted(glob.glob(os.path.join(src, "*Data.csv"))):
            m = NAME.match(os.path.basename(f))
            if m:
                files.setdefault(m.group("ath"), {})[m.group("kind")] = (f, m.group("sensor"))
                if sp:
                    folder_sport[ALIASES.get(m.group("ath"), m.group("ath"))] = sp
    for ath, sp in folder_sport.items():
        sports.setdefault(ath, sp)  # --sport-map wins over the folder

    out = {k: [] for k in ("jumps", "runs", "imu_runs", "gps_runs", "gps_track", "qc")}
    done = []
    for ath_file, ff in files.items():
        if args.only and ath_file not in args.only:
            continue
        if "imu" not in ff or "gnss" not in ff:
            print(f"{ath_file}: IMU or GNSS file missing – skipped")
            continue
        ath = ALIASES.get(ath_file, ath_file)
        sensor = ff["imu"][1]
        sensor = int(sensor) if sensor else None
        problem = gnss_problem(ff["gnss"][0])
        if problem:  # runs need GNSS (thesis method) – no guessing without it
            print(f"{ath}: skipped – {problem}")
            continue
        process(ath, sensor, ff["imu"][0], ff["gnss"][0], out)
        done.append(ath)

    for k, parts in out.items():
        if not parts:
            continue
        df = pd.DataFrame(parts) if isinstance(parts[0], dict) else pd.concat(parts, ignore_index=True)
        if k in ("jumps", "runs", "qc", "gps_track"):
            df.insert(1, "Sport", df["Athlet"].map(sport_of))
        path = os.path.join(args.out, f"{k}.parquet")
        if os.path.exists(path):  # merge: keep other athletes, replace the ones processed now
            old = pd.read_parquet(path)
            if k in ("jumps", "runs", "qc", "gps_track") and "Sport" not in old.columns:
                old.insert(1, "Sport", "Freeski")
            df = pd.concat([old[~old["Athlet"].isin(done)], df], ignore_index=True)
        df.to_parquet(path, index=False, compression="zstd")
    print(f"written to {args.out}")


GNSS_COLS = ["time [POSIXms]", "timestamp [us]", "latitude [deg]", "longitude [deg]",
             "speedN [m/s]", "speedE [m/s]", "speedD [m/s]", "altitude [m]"]


def gnss_problem(f_gnss) -> str | None:
    """Reason why a GNSS file cannot be used, or None."""
    head = pd.read_csv(f_gnss, nrows=2000)
    missing = [c for c in GNSS_COLS if c not in head.columns]
    if missing:
        return f"GNSS file without {', '.join(missing)} (no GPS fix recorded?)"
    full = pd.read_csv(f_gnss, usecols=["time [POSIXms]", "latitude [deg]"])
    if not ((full["time [POSIXms]"] > 1.7e12) & (full["latitude [deg]"] != 0)).any():
        return "GNSS file has no valid position"
    return None


def process(ath, sensor, f_imu, f_gnss, out):
    raw = pd.read_csv(f_imu, dtype="float64")
    gnss = pd.read_csv(f_gnss)
    axis_vert = detect_vertical_axis(raw)
    df = preprocess_imu(raw)
    del raw
    imu_sessions, _ = quiet(sensor_lib.detect_sessions_imu, df)
    gnss_all = sensor_lib.add_resultant_speed(gnss)
    gnss_sessions, _ = quiet(sensor_lib.detect_sessions_gnss, gnss_all)
    if len(imu_sessions) != len(gnss_sessions):
        print(f"{ath}: {len(imu_sessions)} IMU sessions but {len(gnss_sessions)} GNSS sessions – "
              "only sessions present in both are used")

    run_no, n_jumps_total, n_gps, n_bad = 0, 0, 0, 0
    for s_id, imu_s in imu_sessions.items():
        g = gnss_sessions.get(s_id)
        if g is None or len(g) < 50:
            continue
        # real time: median offset between GPS time and sensor clock (valid fixes only)
        valid = (g["time [POSIXms]"] > 1.7e12)
        if not valid.any():
            print(f"{ath} {s_id}: no valid GPS time – skipped")
            continue
        off = g.loc[valid, "time [POSIXms]"] * 1000 - g.loc[valid, "timestamp [us]"]
        off_us = float(np.median(off))
        valid &= (off - off_us).abs() < 5e6

        # ---- runs: thesis method on the GNSS of this session
        runs = quiet(sensor_lib.detect_runs, g, **RUNS)

        # ---- GPS for display: speed in km/h (3D) + outlier filter
        gv = g[valid].reset_index(drop=True)
        gv["speed_kmh"] = gv["speedRes [m/s]"] * 3.6
        keep = clean_mask(gv["latitude [deg]"], gv["longitude [deg]"], gv["time [POSIXms]"],
                          gv["altitude [m]"], gv["speed_kmh"])
        n_gps += len(gv)
        n_bad += int((~keep).sum())
        gc = gv[keep].reset_index(drop=True)
        gt = gc["timestamp [us]"].values

        def at(col, t):
            v = np.interp(t, gt, gc[col].values, left=np.nan, right=np.nan)
            near = np.abs(gt[np.clip(np.searchsorted(gt, t), 0, len(gt) - 1)] - t) <= 2e6
            return np.where(near, v, np.nan)

        t_imu = imu_s["imuTimestamp [us]"].values
        for _, r in runs.iterrows():
            seg = imu_s[(t_imu >= r["start_time_us"]) & (t_imu <= r["end_time_us"])].reset_index(drop=True)
            if len(seg) < 100:
                continue
            try:
                j = quiet(sensor_lib.detect_jumps_snow, seg, axis_vert=axis_vert, **JUMP)
            except Exception:
                j = pd.DataFrame()
            if len(j):
                j = mark_plausible(compute_landing_params(seg, j, position_label=POSITION))
            run_no += 1
            rid = f"Run {run_no:02d}"
            t0 = float(r["start_time_us"])
            t_seg = seg["imuTimestamp [us]"].values
            jumps = []
            k = 0
            for _, x in (j.sort_values("takeoff_idx").iterrows() if len(j) else []):
                t_to = float(t_seg[int(x["takeoff_idx"])])
                t_la = float(t_seg[int(x["landing_idx"])])
                plaus = bool(x["plausible"])
                k += plaus
                a_lo = (gt >= t_to - APPROACH_S * 1e6) & (gt <= t_to)
                jumps.append(dict(
                    Athlet=ath, Sensor=sensor, Session=s_id, Run=rid, Sprung=len(jumps) + 1,
                    Kicker=k if plaus else None, Plausibel=plaus, Grund=x["exclusion_reason"],
                    Zeit=to_local((t_to + off_us) / 1000).strftime("%H:%M:%S"),
                    t_run_s=round((t_to - t0) / 1e6, 3),
                    Airtime_s=round(float(x["flight_time_s"]), 3),
                    Peak_g=round(float(x["peak_res_g"]), 2), Peak_g_roh=round(float(x["peak_res_g_raw"]), 2),
                    Time_to_peak_s=x["time_to_peak_s"], RFD_g_s=x["rfd_g_per_s"],
                    Landeimpuls_025_gs=x["landing_impulse_025_g_s"], Geclippt_16g=bool(x["clipped_16g"]),
                    Landung=x.get("landing_type", ""),
                    Speed_kmh=round(float(at("speed_kmh", np.array([t_to]))[0]), 1),
                    Speed_Anfahrt_kmh=round(float(gc.loc[a_lo, "speed_kmh"].max()), 1) if a_lo.any() else np.nan,
                    Lat=float(at("latitude [deg]", np.array([t_to]))[0]),
                    Lon=float(at("longitude [deg]", np.array([t_to]))[0]),
                    Hoehe_m=float(at("altitude [m]", np.array([t_to]))[0])))
            n_jumps_total += len(jumps)
            out["jumps"].extend(jumps)
            jk = [x for x in jumps if x["Plausibel"]]
            gr = gc[(gt >= t0 - PAD_S * 1e6) & (gt <= r["end_time_us"] + PAD_S * 1e6)]
            sp = gc.loc[(gt >= t0) & (gt <= r["end_time_us"]), "speed_kmh"]
            out["runs"].append(dict(
                Athlet=ath, Sensor=sensor, Session=s_id, Run=rid,
                Start=to_local((t0 + off_us) / 1000).strftime("%H:%M:%S"),
                Dauer_s=round(float(r["duration_s"]), 1), Hoehenverlust_m=round(float(r["alt_drop_m"]), 1),
                Sprünge=len(jumps), Kicker=len(jk),
                Airtime_mittel_s=np.mean([x["Airtime_s"] for x in jk]) if jk else np.nan,
                Airtime_max_s=max([x["Airtime_s"] for x in jk]) if jk else np.nan,
                Peak_g_mittel=np.mean([x["Peak_g"] for x in jk]) if jk else np.nan,
                Peak_g_max=max([x["Peak_g"] for x in jk]) if jk else np.nan,
                Speed_mittel_kmh=round(float(sp.mean()), 1) if len(sp) else np.nan,
                Speed_max_kmh=round(float(sp.max()), 1) if len(sp) else np.nan))
            # time series for the plots: IMU 200 Hz (accRes), GPS 10 Hz
            m = (t_imu >= t0 - PAD_S * 1e6) & (t_imu <= r["end_time_us"] + PAD_S * 1e6)
            out["imu_runs"].append(pd.DataFrame({
                "Athlet": ath, "Run": rid, "t_s": ((t_imu[m] - t0) / 1e6).astype("float32"),
                "accRes_g": imu_s["accRes [g]"].values[m].astype("float32")}))
            out["gps_runs"].append(pd.DataFrame({
                "Athlet": ath, "Run": rid, "t_s": ((gr["timestamp [us]"].values - t0) / 1e6).astype("float32"),
                "lat": gr["latitude [deg]"].values, "lon": gr["longitude [deg]"].values,
                "alt": gr["altitude [m]"].values.astype("float32"),
                "speed_kmh": gr["speed_kmh"].values.astype("float32")}))

        # day track 5 Hz incl. filtered points (to check the filter)
        tr = gv.iloc[::2].assign(ok=keep[::2])
        tr = pd.concat([tr, gv[~keep].assign(ok=False)]).drop_duplicates("timestamp [us]").sort_values("timestamp [us]")
        zt = to_local(tr["time [POSIXms]"])
        out["gps_track"].append(pd.DataFrame({
            "Athlet": ath, "Session": s_id, "Zeit": zt.dt.strftime("%H:%M:%S").values,
            "t_min": (zt.dt.hour * 60 + zt.dt.minute + zt.dt.second / 60).values.astype("float32"),
            "lat": tr["latitude [deg]"].values, "lon": tr["longitude [deg]"].values,
            "alt": tr["altitude [m]"].values.astype("float32"),
            "speed_kmh": tr["speed_kmh"].values.astype("float32"),
            "gefiltert": ~tr["ok"].values.astype(bool)}))

    mine = [x for x in out["jumps"] if x["Athlet"] == ath]
    out["qc"].append(dict(Athlet=ath, Sensor=sensor, Sessions=len(imu_sessions), Runs=run_no,
                          Sprünge_in_Runs=n_jumps_total, Kicker=sum(x["Plausibel"] for x in mine),
                          GPS_Punkte=n_gps, GPS_gefiltert=n_bad,
                          GPS_gefiltert_pct=round(100 * n_bad / n_gps, 1) if n_gps else np.nan))
    print(out["qc"][-1], flush=True)


if __name__ == "__main__":
    main()
