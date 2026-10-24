"""
Exporte les tables du schema en etoile vers data/bi/*.parquet, la source du modele Power BI
et de l'API. Les fichiers sont petits et versionnes : le rapport et l'API marchent sans
relancer la collecte.

    python src/export_bi.py
"""

import pathlib

import duckdb

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "yego.duckdb"
OUT = ROOT / "data" / "bi"

TABLES = {
    "dim_city": "select * from dim_city",
    "dim_zone": "select * from dim_zone",
    "dim_hour": "select * from dim_hour",
    "fct_fleet_hourly": "select * from fct_fleet_hourly",
    "fct_zone_hourly": """
        select city, zone_id, local_hour, avg_available, avg_low_battery,
               departures_per_day, arrivals_per_day
        from fct_zone_hourly
    """,
    "fct_battery_swaps": """
        select city, track_id, zone_id, snapshot_at_local, local_hour,
               previous_battery_pct, battery_pct, battery_gain_pct, previous_is_disabled, is_confirmed
        from fct_battery_swaps
    """,
    "fct_battery_waits": """
        select city, track_id, episode, start_local, start_hour, zone_id, min_battery_pct,
               outcome, wait_hours, left_censored
        from fct_battery_waits
    """,
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB), read_only=True)
    for name, query in TABLES.items():
        path = (OUT / f"{name}.parquet").as_posix()
        # execute + fetchall : compatible DuckDB 1.x et 2.x (en 2.0, une relation n'a plus fetchone() et
        # un resultat lu partiellement bloque la connexion).
        con.execute(f"copy ({query}) to '{path}' (format parquet, compression zstd)").fetchall()
        n = con.execute(f"select count(*) from read_parquet('{path}')").fetchall()[0][0]
        print(f"{name}: {n} lignes")


if __name__ == "__main__":
    main()
