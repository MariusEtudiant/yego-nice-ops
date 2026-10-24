# YEGO Nice — Operations Monitor

[![ci](https://github.com/MariusEtudiant/yego-nice-ops/actions/workflows/ci.yml/badge.svg)](https://github.com/MariusEtudiant/yego-nice-ops/actions/workflows/ci.yml)

A data product on the YEGO shared e-scooter fleets of Nice and Barcelona, built only from the
operator's public GBFS feed: collection through a REST API, dbt models with data quality tests,
a star schema for a Power BI model, a FastAPI service with a web page, and CI on every push.

**Report:** [`reports/yego_nice_report.pdf`](reports/yego_nice_report.pdf) (3 pages, source in
[LaTeX](reports/yego_nice_report.tex)) · one-page note in French:
[`reports/note_yego_nice.pdf`](reports/note_yego_nice.pdf)

![Web app](docs/web_app.jpg)

## Key findings (Nice, 11–24 October 2026, 10 complete days)

- YEGO disables every scooter below 15% battery, and the battery queue never empties: 23 to 31
  scooters wait for a battery at any hour of an average day.
- Demand peaks every evening at 17h or 18h, but most battery swaps come after the peak (9 evenings
  out of 10). A scooter disabled for low battery waits 5.3 h (median) before its swap, twice as
  long as in Barcelona (2.6 h).
- About 13% of the fleet is disabled for reasons other than battery, often for days. The data
  quality tests also found scooters left for days outside the service area (one in Monaco).

## Pipeline

```
GBFS REST API ──► collector.py ──► Parquet ──► track_vehicles.py ──► dbt (DuckDB)
  every 2 min                     (raw)        stable scooter IDs     staging → marts → star schema
                                                                            │
                         ┌──────────────────────────────┬──────────────────┤
                         ▼                              ▼                  ▼
              Power BI semantic model         FastAPI + web page     LaTeX / PDF reports
              (TMDL, DAX measures)            (map, KPIs, OpenAPI)
```

1. `src/collector.py` saves the GBFS feed every 2 minutes as Parquet files.
2. `src/track_vehicles.py` rebuilds a stable ID for each scooter, because the feed changes
   `bike_id` at every request.
3. `transform/`: dbt models on DuckDB. Staging, then marts, then a star schema (`dim_city`,
   `dim_zone`, `dim_hour` around four fact tables, including `fct_battery_waits`: how long each
   scooter waits for its battery swap). Data quality is checked by 37 tests:
   not-null and unique keys, referential integrity between facts and dimensions, battery in
   range, coordinates inside the city, collection gaps, and a business rule (no active scooter
   under 15% battery).
4. `src/export_bi.py` writes the star schema to `data/bi/` (68 KB, versioned).
5. `powerbi/`: the Power BI semantic model as a TMDL script, generated from the Parquet schema:
   relationships, hidden keys, sort orders, geographic categories and 18 DAX measures. See
   [`powerbi/README.md`](powerbi/README.md).
6. `api/` and `web/`: a FastAPI service (`/api/cities`, `/api/cities/{city}/fleet`,
   `/zones?hour=`, `/swaps`, typed responses, OpenAPI docs at `/docs`) and a web page with a zone
   map, KPIs and the fleet status by hour.
7. `.github/workflows/ci.yml`: on every push, rebuilds the dbt models and tests from the
   versioned data in `data/compact/`, exports the star schema and runs the API tests.
8. `.github/workflows/collect.yml`: collects the feed in the cloud. Every hour, 55 minutes of
   snapshots (one every 2 minutes) are merged into one file per city and committed to the
   `data` branch, so no computer has to stay on.

## Run

```bash
pip install -r requirements.txt
git fetch origin data && git archive origin/data data | tar -x   # get the cloud collection
python src/pipeline.py                  # tracking, dbt build, reports, BI export, TMDL
uvicorn api.main:app --reload           # web page on http://127.0.0.1:8000, API docs on /docs
pytest                                  # API tests
```

Without a local collection, dbt runs on the versioned sample in `data/compact/` (the first night,
11–12 October), which is also what the CI uses:

```bash
cd transform && dbt build --profiles-dir . --vars '{source: compact}'
```
