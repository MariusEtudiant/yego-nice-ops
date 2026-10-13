"""
Genere le modele semantique Power BI (script TMDL) a partir des tables de data/bi/.

    python powerbi/generate_tmdl.py   ->   powerbi/yego_fleet_model.tmdl

Le script se colle dans la vue TMDL de Power BI Desktop (onglet TMDL, puis Appliquer) : il cree
le parametre DataFolder, les six tables (requetes Power Query sur les fichiers Parquet), les
relations du schema en etoile et les mesures DAX. Les types de colonnes viennent du schema
Parquet, ils ne peuvent donc pas diverger des donnees.
"""

import pathlib
import uuid

import duckdb

ROOT = pathlib.Path(__file__).resolve().parent.parent
BI = ROOT / "data" / "bi"
OUT = ROOT / "powerbi" / "yego_fleet_model.tmdl"
NS = uuid.UUID("6f1c2b0e-7a51-4c5e-9a39-0c8f3d2b1a10")  # lineage tags stables d'une generation a l'autre

TABLES = ["dim_city", "dim_zone", "dim_hour", "fct_fleet_hourly", "fct_zone_hourly", "fct_battery_swaps"]

TYPES = {"VARCHAR": "string", "BIGINT": "int64", "INTEGER": "int64", "DOUBLE": "double", "BOOLEAN": "boolean",
         "TIMESTAMP": "dateTime", "DATE": "dateTime"}

# Cles etrangeres : masquees dans les faits, on filtre par les dimensions.
HIDDEN = {("fct_fleet_hourly", "city"), ("fct_fleet_hourly", "local_hour"), ("fct_zone_hourly", "city"),
          ("fct_zone_hourly", "zone_id"), ("fct_zone_hourly", "local_hour"), ("fct_battery_swaps", "city"),
          ("fct_battery_swaps", "zone_id"), ("fct_battery_swaps", "local_hour"), ("fct_battery_swaps", "track_id"),
          ("dim_zone", "city")}
CATEGORY = {("dim_zone", "zone_lat"): "Latitude", ("dim_zone", "zone_lon"): "Longitude",
            ("dim_city", "city_name"): "City", ("dim_city", "country"): "Country"}
SORT_BY = {("dim_hour", "hour_label"): "local_hour"}

RELATIONSHIPS = [
    ("fct_fleet_hourly", "city", "dim_city", "city"),
    ("fct_fleet_hourly", "local_hour", "dim_hour", "local_hour"),
    ("dim_zone", "city", "dim_city", "city"),
    ("fct_zone_hourly", "zone_id", "dim_zone", "zone_id"),
    ("fct_zone_hourly", "local_hour", "dim_hour", "local_hour"),
    ("fct_battery_swaps", "zone_id", "dim_zone", "zone_id"),
    ("fct_battery_swaps", "local_hour", "dim_hour", "local_hour"),
]

# (table d'accueil, nom, expression DAX, format)
MEASURES = [
    ("fct_fleet_hourly", "Listed Scooters", "AVERAGE ( fct_fleet_hourly[avg_listed] )", "#,0"),
    ("fct_fleet_hourly", "Available Scooters", "AVERAGE ( fct_fleet_hourly[avg_available] )", "#,0"),
    ("fct_fleet_hourly", "Availability Rate",
     "DIVIDE ( SUM ( fct_fleet_hourly[avg_available] ), SUM ( fct_fleet_hourly[avg_listed] ) )", "0.0%"),
    ("fct_fleet_hourly", "Waiting for Battery", "AVERAGE ( fct_fleet_hourly[avg_disabled_battery] )", "#,0"),
    ("fct_fleet_hourly", "Disabled Other Reason", "AVERAGE ( fct_fleet_hourly[avg_disabled_other] )", "#,0"),
    ("fct_fleet_hourly", "Peak Battery Queue",
     "MAXX (\n    VALUES ( fct_fleet_hourly[hour_local] ),\n"
     "    CALCULATE ( SUM ( fct_fleet_hourly[avg_disabled_battery] ) )\n)", "#,0"),
    ("fct_fleet_hourly", "Available vs Daily Average",
     "[Available Scooters] - CALCULATE ( [Available Scooters], REMOVEFILTERS ( dim_hour ) )", "+#,0;-#,0;0"),
    ("fct_zone_hourly", "Departures per Day", "SUM ( fct_zone_hourly[departures_per_day] )", "#,0.0"),
    ("fct_zone_hourly", "Arrivals per Day", "SUM ( fct_zone_hourly[arrivals_per_day] )", "#,0.0"),
    ("fct_zone_hourly", "Net Flow per Day", "[Arrivals per Day] - [Departures per Day]", "+#,0.0;-#,0.0;0"),
    ("fct_zone_hourly", "Zones in Shortage",
     "COUNTROWS (\n    FILTER (\n        SUMMARIZE ( fct_zone_hourly, fct_zone_hourly[zone_id], fct_zone_hourly[local_hour] ),\n"
     "        CALCULATE ( SUM ( fct_zone_hourly[avg_available] ) ) < 1\n"
     "            && CALCULATE ( SUM ( fct_zone_hourly[departures_per_day] ) ) >= 1\n    )\n)", "#,0"),
    ("fct_zone_hourly", "Peak Demand Hour",
     "MAXX (\n    TOPN ( 1, VALUES ( dim_hour[local_hour] ), [Departures per Day], DESC ),\n    dim_hour[local_hour]\n)",
     "0"),
    ("fct_battery_swaps", "Battery Swaps",
     "CALCULATE ( COUNTROWS ( fct_battery_swaps ), fct_battery_swaps[is_confirmed] = TRUE () )", "#,0"),
    ("fct_battery_swaps", "Swaps After Evening Peak %",
     "DIVIDE (\n    CALCULATE ( [Battery Swaps], dim_hour[local_hour] >= 20 || dim_hour[local_hour] < 2 ),\n"
     "    [Battery Swaps]\n)", "0%"),
    ("fct_battery_swaps", "Average Battery Gain",
     "CALCULATE ( AVERAGE ( fct_battery_swaps[battery_gain_pct] ), fct_battery_swaps[is_confirmed] = TRUE () )",
     "0"),
]


def tag(*parts: str) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


def block(text: str, indent: int) -> list[str]:
    return ["\t" * indent + line for line in text.splitlines()]


def table_lines(name: str) -> list[str]:
    schema = duckdb.sql(f"describe select * from read_parquet('{(BI / f'{name}.parquet').as_posix()}')").fetchall()
    out = [f"\ttable {name}", f"\t\tlineageTag: {tag(name)}", ""]
    for table, mname, dax, fmt in MEASURES:
        if table != name:
            continue
        if "\n" in dax:
            out += [f"\t\tmeasure '{mname}' ="] + block(dax, 4)
        else:
            out.append(f"\t\tmeasure '{mname}' = {dax}")
        out += [f"\t\t\tformatString: {fmt}", f"\t\t\tlineageTag: {tag(name, 'measure', mname)}", ""]
    for col, dtype, *_ in schema:
        base = dtype.split("(")[0]
        tmdl_type = "decimal" if base == "DECIMAL" else TYPES[base]
        out += [f"\t\tcolumn {col}", f"\t\t\tdataType: {tmdl_type}"]
        if tmdl_type == "double":
            out.append("\t\t\tformatString: 0.00")
        elif tmdl_type == "dateTime":
            out.append("\t\t\tformatString: General Date")
        if (name, col) in HIDDEN:
            out.append("\t\t\tisHidden")
        if (name, col) in CATEGORY:
            out.append(f"\t\t\tdataCategory: {CATEGORY[(name, col)]}")
        if (name, col) in SORT_BY:
            out.append(f"\t\t\tsortByColumn: {SORT_BY[(name, col)]}")
        numeric = tmdl_type in ("double", "decimal") and not col.startswith(("zone_l",))
        out += [f"\t\t\tlineageTag: {tag(name, col)}", f"\t\t\tsummarizeBy: {'sum' if numeric else 'none'}",
                f"\t\t\tsourceColumn: {col}", "", "\t\t\tannotation SummarizationSetBy = Automatic", ""]
    m = (f'let\n    Source = Parquet.Document ( File.Contents ( DataFolder & "{name}.parquet" ) )\nin\n    Source')
    out += [f"\t\tpartition {name} = m", "\t\t\tmode: import", "\t\t\tsource ="] + block(m, 5) + [""]
    out += ["\t\tannotation PBI_ResultType = Table", ""]
    return out


def main() -> None:
    folder = str(BI.resolve()) + "\\"
    lines = ["createOrReplace", "",
             f'\texpression DataFolder = "{folder}" meta [IsParameterQuery = true, Type = "Text", '
             f'IsParameterQueryRequired = true]',
             f"\t\tlineageTag: {tag('DataFolder')}", "", "\t\tannotation PBI_ResultType = Text", ""]
    for name in TABLES:
        lines += table_lines(name)
    for frm, fcol, to, tcol in RELATIONSHIPS:
        lines += [f"\trelationship {tag('rel', frm, fcol)}", f"\t\tfromColumn: {frm}.{fcol}",
                  f"\t\ttoColumn: {to}.{tcol}", ""]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"{OUT} ({len(TABLES)} tables, {len(RELATIONSHIPS)} relations, {len(MEASURES)} mesures)")


if __name__ == "__main__":
    main()
