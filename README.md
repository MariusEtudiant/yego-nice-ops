# YEGO feed collected in the cloud

This branch only holds data. It is filled every hour by the `Collect YEGO feed` workflow of the
`master` branch: `data/raw/city=<city>/date=<day>/` holds one Parquet file per hour (snapshots every
2 minutes), `data/static/` the daily static feeds.
