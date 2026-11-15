# Park Impact Corvatsch (Freeski Slopestyle)

Dashboard für Kicker-Sprünge und Landebelastung im Park (Swiss Freeski), Saison 2026/27.
Darstellung wie das Halfpipe-Dashboard (`snowboard-halfpipe-imu`), Erfassung von Sessions, Runs und
Sprüngen nach der Methode der Masterarbeit (`freeski-imu`). **Unabhängig von der Masterarbeit:**
Masterarbeit, MA-Dashboard und Halfpipe-Dashboard werden nicht verändert.

## Start lokal

    pip install -r requirements.txt
    streamlit run app.py

## Neuen Messtag aufbereiten

    python tools/build_park_data.py "<Tagesordner mit FS/ und SNB/>" data/YYYYMMDD_Ort   # Sportart aus dem Unterordner
    python tools/build_park_data.py "<Ordner mit CSVs>" data/YYYYMMDD_Ort --sport Freeski   # oder Snowboard

Dateinamen: `<Ort>_<Athlet>_<Sensor>_<YYYY-MM-DD>_imuData.csv` / `_gnssData.csv`
(z. B. `Corvatsch_Nils_01_2026-11-14_imuData.csv`). Namen im Dateinamen → Dashboard über `ALIASES`
in `tools/build_park_data.py` (Gian → Juan). Roh-CSVs gehören nicht ins Repo, nur `data/<Messtag>/*.parquet`.

## Methode (aus der Masterarbeit übernommen)
- Sessions: Reset der Sensor-Zeitstempel (`sensor_lib.detect_sessions_imu/gnss`)
- Runs: `sensor_lib.detect_runs` auf GNSS (v_start 7 m/s, v_hold 1.5 m/s, alt_rise_end 20 m, alt_drop_min 30 m, ≥ 15 s)
- Sprünge: `sensor_lib.detect_jumps_snow` pro Run (0.60 / 0.70 / 1.0 g, min. 1.2 s), Landeparameter und
  Bias-Korrektur Bauch (`jump_detector.compute_landing_params`), Kicker = `mark_plausible` (≥ 1.4 s, max. 3 pro Run)
- `utils/sensor_lib.py` und `utils/jump_detector.py` sind unveränderte Kopien aus `freeski-imu`.

## Seiten
Team (Karten pro Athlet:in) · Overview · Athlete (Run im Detail) · Compare · Park & GPS · Method.
Repo muss **privat** bleiben (Athletendaten).
