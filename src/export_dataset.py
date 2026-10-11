"""
Exporte un jeu de donnees compact et versionnable : un Parquet par ville avec toutes les
observations et leur track_id (le bike_id volatil, sans valeur analytique, n'est pas conserve).

    python src/export_dataset.py   ->   data/compact/<ville>.parquet
"""

import pathlib

import duckdb

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW_GLOB = (ROOT / "data" / "raw" / "*" / "*" / "*.parquet").as_posix()
TRACKS_GLOB = (ROOT / "data" / "tracks" / "*" / "tracks.parquet").as_posix()
OUT = ROOT / "data" / "compact"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for (city,) in duckdb.sql(f"select distinct city from read_parquet('{TRACKS_GLOB}', hive_partitioning = true)").fetchall():
        path = (OUT / f"{city}.parquet").as_posix()
        duckdb.sql(f"""
            copy (
                select r.snapshot_ts, r.feed_last_updated, t.track_id, r.lat, r.lon, r.vehicle_type_id,
                       r.current_fuel_percent, r.current_range_meters, r.is_reserved, r.is_disabled
                from read_parquet('{RAW_GLOB}', hive_partitioning = true) r
                left join read_parquet('{TRACKS_GLOB}', hive_partitioning = true) t
                  on t.city = r.city and t.snapshot_ts = r.snapshot_ts and t.volatile_bike_id = r.bike_id
                where r.city = '{city}'
                  and r.snapshot_ts <= (select max(snapshot_ts) from read_parquet('{TRACKS_GLOB}', hive_partitioning = true) x
                                        where x.city = '{city}')
                order by r.snapshot_ts, t.track_id
            ) to '{path}' (format parquet, compression zstd)
        """)
        size_mb = pathlib.Path(path).stat().st_size / 1e6
        print(f"{city}: {path} ({size_mb:.1f} Mo)")


if __name__ == "__main__":
    main()
