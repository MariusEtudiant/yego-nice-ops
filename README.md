# YEGO Nice — Operations Monitor

Analysis of the YEGO shared e-scooter fleet in Nice (and Barcelona), using only the operator's
public GBFS feed.

**Report:** [`reports/yego_nice_report.tex`](reports/yego_nice_report.tex) (3 pages, LaTeX) ·
one-page note in French: [`reports/note_yego_nice.pdf`](reports/note_yego_nice.pdf)

## Key findings (Nice, 11–12 October 2026)

- YEGO disables every scooter below 15% battery.
- At the 19h demand peak, 16 scooters were waiting for a battery, while 50 of the 57 battery
  swaps happened between 20h and 02h, after the peak.
- About 11% of the fleet is disabled for reasons other than battery.

## How it works

1. `src/collector.py` saves the GBFS feed every 2 minutes as Parquet files.
2. `src/track_vehicles.py` rebuilds a stable ID for each scooter, because the feed changes
   `bike_id` at every request.
3. `transform/` contains the dbt models (DuckDB) and the data quality tests.
4. `src/build_latex.py` and `src/build_report.py` write the reports.

## Run

```bash
pip install -r requirements.txt
python src/collector.py --loop   # collect data
python src/pipeline.py           # tracking, dbt build, reports
```

The collected data is in `data/compact/` (one Parquet file per city).
