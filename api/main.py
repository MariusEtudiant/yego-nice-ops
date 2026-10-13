"""
API de lecture du produit data YEGO : flotte, zones et changements de batterie, servie a partir
des tables Parquet du schema en etoile (data/bi/). Sert aussi la page web (web/index.html).

    uvicorn api.main:app --reload
    -> http://127.0.0.1:8000        page web
    -> http://127.0.0.1:8000/docs   documentation OpenAPI
"""

import pathlib
from typing import Literal

import duckdb
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

ROOT = pathlib.Path(__file__).resolve().parent.parent
BI = ROOT / "data" / "bi"
WEB = ROOT / "web"

# Seuils de statut d'une zone a une heure donnee (vehicules disponibles en moyenne, departs par jour).
SHORTAGE_MAX_AVAILABLE = 1.0
SHORTAGE_MIN_DEPARTURES = 1.0
SURPLUS_MIN_AVAILABLE = 5.0


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    for path in sorted(BI.glob("*.parquet")):
        con.execute(f"create view {path.stem} as select * from read_parquet('{path.as_posix()}')")
    return con


CON = connect()


def rows(sql: str, params: list | None = None) -> list[dict]:
    cur = CON.cursor()  # un curseur par requete : la connexion DuckDB n'est pas partagee entre threads
    cur.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def check_city(city: str) -> None:
    if not rows("select 1 from dim_city where city = ?", [city]):
        raise HTTPException(status_code=404, detail=f"Unknown city '{city}'")


class City(BaseModel):
    city: str
    city_name: str
    country: str
    hours_observed: int
    avg_listed: float
    avg_available: float
    availability_rate: float
    avg_waiting_battery: float
    battery_swaps: int


class FleetHour(BaseModel):
    hour_local: str
    local_hour: int
    avg_listed: float
    avg_available: float
    avg_disabled_battery: float
    avg_disabled_other: float
    availability_rate: float


class Zone(BaseModel):
    zone_id: str
    zone_name: str
    lat: float
    lon: float
    avg_available: float
    departures_per_day: float
    arrivals_per_day: float
    net_flow_per_day: float
    status: Literal["shortage", "balanced", "surplus"]


class SwapHour(BaseModel):
    local_hour: int
    swaps: int
    confirmed_swaps: int


app = FastAPI(
    title="YEGO fleet data API",
    description="Fleet availability, zone supply and demand, and battery swaps for the YEGO "
                "e-scooter fleets of Nice and Barcelona, rebuilt from the public GBFS feed.",
    version="1.0.0",
)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "tables": sorted(p.stem for p in BI.glob("*.parquet"))}


@app.get("/api/cities", response_model=list[City])
def cities() -> list[dict]:
    return rows("""
        select
            c.city, c.city_name, c.country,
            count(*)                                            as hours_observed,
            avg(f.avg_listed)                                   as avg_listed,
            avg(f.avg_available)                                as avg_available,
            sum(f.avg_available) / sum(f.avg_listed)            as availability_rate,
            avg(f.avg_disabled_battery)                         as avg_waiting_battery,
            (select count(*) from fct_battery_swaps s where s.city = c.city and s.is_confirmed) as battery_swaps
        from dim_city c
        join fct_fleet_hourly f using (city)
        group by all
        order by c.city
    """)


@app.get("/api/cities/{city}/fleet", response_model=list[FleetHour])
def fleet(city: str) -> list[dict]:
    check_city(city)
    return rows("""
        select
            strftime(hour_local, '%Y-%m-%d %H:%M')   as hour_local,
            local_hour, avg_listed, avg_available, avg_disabled_battery, avg_disabled_other,
            avg_available / avg_listed               as availability_rate
        from fct_fleet_hourly
        where city = ?
        order by fct_fleet_hourly.hour_local
    """, [city])


@app.get("/api/cities/{city}/zones", response_model=list[Zone])
def zones(city: str, hour: int = Query(19, ge=0, le=23, description="Local hour (0-23)")) -> list[dict]:
    check_city(city)
    return rows(f"""
        select
            z.zone_id, z.zone_name, z.zone_lat as lat, z.zone_lon as lon,
            h.avg_available, h.departures_per_day, h.arrivals_per_day,
            h.arrivals_per_day - h.departures_per_day                         as net_flow_per_day,
            case
                when h.avg_available < {SHORTAGE_MAX_AVAILABLE}
                     and h.departures_per_day >= {SHORTAGE_MIN_DEPARTURES}   then 'shortage'
                when h.avg_available >= {SURPLUS_MIN_AVAILABLE}
                     and h.departures_per_day = 0                            then 'surplus'
                else 'balanced'
            end                                                               as status
        from fct_zone_hourly h
        join dim_zone z using (city, zone_id)
        where h.city = ? and h.local_hour = ?
        order by h.departures_per_day desc
    """, [city, hour])


@app.get("/api/cities/{city}/swaps", response_model=list[SwapHour])
def swaps(city: str) -> list[dict]:
    check_city(city)
    return rows("""
        select
            h.local_hour,
            count(s.track_id)                                   as swaps,
            count(s.track_id) filter (where s.is_confirmed)     as confirmed_swaps
        from dim_hour h
        left join fct_battery_swaps s on s.local_hour = h.local_hour and s.city = ?
        group by h.local_hour
        order by h.local_hour
    """, [city])
