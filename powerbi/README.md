# Power BI semantic model

`yego_fleet_model.tmdl` is the semantic model as a TMDL script, generated from the Parquet
tables in `data/bi/` by `generate_tmdl.py`.

| Table | Grain | Key measures |
|---|---|---|
| `dim_city` | one city | |
| `dim_zone` | one ~500 m zone, with centre and district name | |
| `dim_hour` | one local hour (0–23), with period of the day | |
| `fct_fleet_hourly` | city × hour | Availability Rate, Waiting for Battery, Peak Battery Queue, Available vs Daily Average |
| `fct_zone_hourly` | zone × hour of day | Departures / Arrivals / Net Flow per Day, Zones in Shortage, Peak Demand Hour |
| `fct_battery_swaps` | one detected battery swap | Battery Swaps, Swaps After Evening Peak %, Average Battery Gain |

Relationships are single-direction, one-to-many: `dim_city → dim_zone → zone and swap facts`,
`dim_city → fct_fleet_hourly`, and `dim_hour → every fact`. Foreign keys are hidden in the facts.

## Load it

1. Power BI Desktop: open a blank report, go to **TMDL view**, paste the content of
   `yego_fleet_model.tmdl` and click **Apply**.
2. If the repository is not at `C:\Users\Marius\Desktop\yego-nice-ops`, change the
   `DataFolder` parameter (Transform data → Manage parameters), keeping the final backslash.
3. **Refresh** to load the data.
4. Save as a Power BI Project (`File → Save as → .pbip`) in this folder, so the report and the
   model are versioned as text.
