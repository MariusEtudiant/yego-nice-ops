"""
Indicateurs sur plusieurs jours, partages par la note francaise (build_report.py) et le rapport
anglais (build_latex.py), pour que les deux documents donnent toujours les memes chiffres.

Les moyennes "journee type" ne portent que sur les jours complets (collecte sur les 24 heures),
pour ne pas sur-representer les heures des jours partiels.
"""

from __future__ import annotations

import json
import os
import pathlib
import time

import duckdb
import pandas as pd
import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
TRANSFORM = ROOT / "transform"
DB_PATH = ROOT / "data" / "yego.duckdb"
ZONE_NAMES_CACHE = ROOT / "data" / "static" / "zone_names.json"

CITY = "nice"
REPO_URL = "github.com/MariusEtudiant/yego-nice-ops"
DISABLE_BATTERY_PCT = 15
IDLE_HOURS = 24
EVENING_HOURS = (16, 22)        # fenetre ou l'on cherche le pic de demande du soir
MIDDAY_HOURS = (11, 15)         # desactivations de mi-journee
LATE_HOURS = (19, 23)           # desactivations de soiree
OUT_OF_AREA_MIN_HOURS = 24      # vehicule hors zone signale s'il y reste au moins 24 h


# --- Acces aux donnees -----------------------------------------------------


def connect() -> duckdb.DuckDBPyConnection:
    # Les vues staging lisent les Parquet en chemin relatif au dossier dbt.
    os.chdir(TRANSFORM)
    return duckdb.connect(str(DB_PATH), read_only=True)


def q(con, sql: str, **params) -> pd.DataFrame:
    return con.execute(sql, params).df() if params else con.sql(sql).df()


def reverse_geocode(key: str, lat: float, lon: float, cache: dict, zoom: int = 16) -> str:
    """Nom de lieu OpenStreetMap (Nominatim), mis en cache pour ne pas solliciter le service."""
    if cache.get(key, key) != key:   # un echec precedent (nom = cle) est retente
        return cache[key]
    name = key
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "jsonv2", "zoom": zoom, "accept-language": "fr"},
            headers={"User-Agent": "yego-nice-ops/1.0 (portfolio, usage ponctuel)"},
            timeout=15,
        )
        addr = r.json().get("address", {})
        keys = (("neighbourhood", "quarter", "suburb", "road", "city_district") if zoom >= 14
                else ("village", "town", "city", "municipality", "county"))
        for k in keys:
            if addr.get(k):
                name = addr[k]
                break
        else:   # ex. Monaco : pays sans champ ville, on prend le premier element du nom affiche
            name = r.json().get("display_name", key).split(",")[0].strip() or key
        time.sleep(1.1)  # politique d'usage Nominatim : 1 requete / seconde
    except Exception:  # noqa: BLE001 - un nom manquant ne doit pas bloquer le rapport
        pass
    cache[key] = name
    return name


def zone_label(zone_id: str, lat: float, lon: float, cache: dict) -> str:
    """Quartier, suivi de la commune quand la zone n'est pas a Nice (ex. Cagnes-sur-Mer)."""
    name = reverse_geocode(zone_id, lat, lon, cache)
    town = reverse_geocode(f"town_{zone_id}", lat, lon, cache, zoom=12)
    if town not in (CITY.title(), name, f"town_{zone_id}"):
        name = f"{name} ({town})"
    return name


def dbt_test_summary() -> dict:
    """Etat des tests du dernier dbt build (target/run_results.json)."""
    path = TRANSFORM / "target" / "run_results.json"
    summary = {"pass": 0, "warn": 0, "fail": 0}
    if path.exists():
        for r in json.loads(path.read_text(encoding="utf-8"))["results"]:
            if r["unique_id"].startswith("test."):
                summary[{"pass": "pass", "warn": "warn"}.get(r["status"], "fail")] += 1
    return summary


# --- Indicateurs -----------------------------------------------------------


def full_days(con, city: str) -> list:
    """Jours dont la collecte couvre les 24 heures (au moins 95 % du nombre maximal de releves)."""
    d = q(con, """
        select cast(snapshot_at_local as date) as day, count(*) as n
        from stg_snapshots where city = $city group by 1 order by 1""", city=city)
    d["day"] = pd.to_datetime(d["day"]).dt.date
    return list(d.loc[d["n"] >= 0.95 * d["n"].max(), "day"])


def hourly_table(con, city: str) -> pd.DataFrame:
    """Une ligne par heure observee : etat de la flotte, departs, changements de batterie."""
    h = q(con, """
        with f as (select hour_local, n_snapshots, avg_listed, avg_available, avg_reserved,
                          avg_disabled_battery, avg_disabled_other
                   from fct_fleet_hourly where city = $city),
        s as (select date_trunc('hour', snapshot_at_local) as hour_local, count(*) as swaps
              from fct_battery_swaps where city = $city and is_confirmed group by 1),
        d as (select date_trunc('hour', last_seen_local) as hour_local, count(*) as departures
              from fct_vehicle_stays where city = $city and is_departure group by 1)
        select f.*, coalesce(s.swaps, 0) as swaps, coalesce(d.departures, 0) as departures
        from f left join s using (hour_local) left join d using (hour_local)
        order by hour_local""", city=city)
    h["day"] = h["hour_local"].dt.date
    h["hour"] = h["hour_local"].dt.hour
    h["weekend"] = h["hour_local"].dt.dayofweek >= 5
    return h


def evenings(h: pd.DataFrame, days: list) -> pd.DataFrame:
    """Soir par soir : pic de demande entre 16h et 22h, file batterie au pic, part des changements
    de batterie faits apres le pic. La nuit est rattachee au soir qui la precede (10h -> 10h)."""
    h = h.assign(evening=(h["hour_local"] - pd.Timedelta(hours=10)).dt.date)
    rows = []
    for ev, g in h.groupby("evening"):
        if ev not in days:
            continue
        win = g[g["hour"].between(*EVENING_HOURS)]
        if win.empty:
            continue
        peak = win.loc[win["departures"].idxmax()]
        swaps = g["swaps"].sum()
        after = g.loc[g["hour_local"] > peak["hour_local"], "swaps"].sum()
        rows.append(dict(
            evening=pd.Timestamp(ev), peak_hour=int(peak["hour"]), peak_departures=int(peak["departures"]),
            queue_at_peak=peak["avg_disabled_battery"], listed_at_peak=peak["avg_listed"],
            swaps=int(swaps), share_after_peak=after / swaps if swaps else float("nan"),
            morning_queue=g.loc[g["hour"].between(5, 9), "avg_disabled_battery"].min(),
        ))
    return pd.DataFrame(rows)


def battery_waits(con) -> pd.DataFrame:
    return q(con, "select * from fct_battery_waits")


def wait_stats(w: pd.DataFrame) -> pd.Series:
    x = w.loc[(w["outcome"] == "swapped") & ~w["left_censored"], "wait_hours"]
    return pd.Series(dict(n=len(x), median=x.median(), p75=x.quantile(0.75), p90=x.quantile(0.9)))


def zone_balance(con, city: str, days: list, cache: dict) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    """Zones en tension (beaucoup de departs, peu de scooters) et en surplus, en moyenne par jour
    complet, avec le nombre de jours ou la zone figure dans le top 10 des zones en tension."""
    d = q(con, """
        with n as (select cast(snapshot_at_local as date) d, count(*) n_snap
                   from stg_snapshots where city = $city group by 1),
        st as (select cast(snapshot_at_local as date) d, zone_id, count(*) filter (where is_available) obs,
                      avg(lat) lat, avg(lon) lon
               from stg_vehicle_snapshots where city = $city and is_valid_position group by all),
        dp as (select cast(last_seen_local as date) d, end_zone_id zone_id, count(*) dep
               from fct_vehicle_stays where city = $city and is_departure group by all)
        select coalesce(st.d, dp.d) d, coalesce(st.zone_id, dp.zone_id) zone_id, st.lat, st.lon,
               coalesce(st.obs, 0) / n.n_snap stock, coalesce(dp.dep, 0) dep
        from st full join dp on st.d = dp.d and st.zone_id = dp.zone_id
        join n on n.d = coalesce(st.d, dp.d)""", city=city)
    d["d"] = pd.to_datetime(d["d"]).dt.date
    d = d[d["d"].isin(days)].copy()
    d["pressure"] = d["dep"] / (d["stock"] + 1)
    d["rank"] = d.groupby("d")["pressure"].rank(ascending=False)
    z = d.groupby("zone_id").agg(lat=("lat", "mean"), lon=("lon", "mean"),
                                 stock=("stock", "sum"), dep=("dep", "sum")).reset_index()
    z[["stock", "dep"]] = z[["stock", "dep"]] / len(days)       # moyenne par jour complet
    z["pressure"] = z["dep"] / (z["stock"] + 1)
    z = z.merge(d[d["rank"] <= 10].groupby("zone_id").size().rename("days_top10").reset_index(),
                on="zone_id", how="left").fillna({"days_top10": 0})
    z = z.dropna(subset=["lat"])

    tension = z[z["dep"] >= 5].sort_values("pressure", ascending=False).head(3).copy()
    surplus = (z[(z["stock"] >= 3) & ~z["zone_id"].isin(tension["zone_id"])]
               .sort_values(["dep", "stock"], ascending=[True, False]).head(8).copy())
    for df in (tension, surplus):
        df["name"] = [zone_label(i, la, lo, cache) for i, la, lo in zip(df.zone_id, df.lat, df.lon)]
    # Deux zones voisines peuvent porter le meme nom : pas de quartier a la fois en tension et en surplus.
    surplus = surplus[~surplus["name"].isin(tension["name"])].head(3)
    return tension, surplus, len(days)


def out_of_area(con, cache: dict) -> pd.DataFrame:
    """Scooters immobiles hors de la zone de service pendant au moins un jour (hors point 0,0)."""
    o = q(con, f"""
        select city, round(lat, 3) lat, round(lon, 3) lon, count(distinct snapshot_ts) snaps,
               min(snapshot_at_local) first_seen, max(snapshot_at_local) last_seen,
               bool_and(is_disabled) always_disabled
        from stg_vehicle_snapshots
        where not is_valid_position and not (lat = 0 and lon = 0)
        group by all
        having (max(snapshot_ts) - min(snapshot_ts)) >= {OUT_OF_AREA_MIN_HOURS} * 3600
        order by city, first_seen""")
    o["days"] = (o["last_seen"] - o["first_seen"]).dt.total_seconds() / 86400
    o["place"] = [reverse_geocode(f"place_{la}_{lo}", la, lo, cache, zoom=10) for la, lo in zip(o.lat, o.lon)]
    return o


def build() -> dict:
    con = connect()
    cache = json.loads(ZONE_NAMES_CACHE.read_text(encoding="utf-8")) if ZONE_NAMES_CACHE.exists() else {}

    window = q(con, """
        select min(snapshot_at_local) as start_at, max(snapshot_at_local) as end_at, count(*) as n_snapshots,
               count(*) filter (where seconds_since_previous > 360) as n_gaps,
               max(seconds_since_previous) / 3600.0 as max_gap_h
        from stg_snapshots where city = $city""", city=CITY).iloc[0]
    days = full_days(con, CITY)

    h = hourly_table(con, CITY)
    hf = h[h["day"].isin(days)]
    profile = hf.groupby("hour").agg(
        available=("avg_available", "mean"), battery=("avg_disabled_battery", "mean"),
        other=("avg_disabled_other", "mean"), listed=("avg_listed", "mean"),
        departures=("departures", "mean"), swaps=("swaps", "mean")).reset_index()
    profile["departures_weekday"] = hf[~hf["weekend"]].groupby("hour")["departures"].mean().values
    weekend_dep = hf[hf["weekend"]].groupby("hour")["departures"].mean()
    profile["departures_weekend"] = profile["hour"].map(weekend_dep)

    ev = evenings(h, days)
    waits = battery_waits(con)
    w_nice = waits[waits["city"] == CITY]
    swapped = w_nice[(w_nice["outcome"] == "swapped") & ~w_nice["left_censored"]]
    ongoing = w_nice[w_nice["outcome"] == "ongoing"]

    swaps = q(con, "select * from fct_battery_swaps where city = $city and is_confirmed", city=CITY)
    swaps_full = swaps[swaps["snapshot_at_local"].dt.date.isin(days)]

    stays = q(con, "select * from fct_vehicle_stays where city = $city", city=CITY)
    other_idle = stays[stays["still_listed"] & stays["is_disabled_at_end"]
                       & (stays["battery_end_pct"] >= DISABLE_BATTERY_PCT)]

    tension, surplus, n_zone_days = zone_balance(con, CITY, days, cache)

    compare = q(con, """
        with s as (select city, cast(snapshot_at_local as date) dt, snapshot_ts, count(*) n,
                          count(*) filter (where is_available) a,
                          count(*) filter (where unavailability_reason = 'battery') b,
                          count(*) filter (where unavailability_reason = 'other') o
                   from stg_vehicle_snapshots where is_valid_position group by all),
        d as (select city, cast(last_seen_local as date) dt, count(*) dep
              from fct_vehicle_stays where is_departure group by all),
        sw as (select city, cast(snapshot_at_local as date) dt, count(*) swaps
               from fct_battery_swaps where is_confirmed group by all)
        select s.city, s.dt, avg(n) fleet, avg(a) a, avg(b) b, avg(o) o,
               any_value(d.dep) dep, coalesce(any_value(sw.swaps), 0) swaps
        from s left join d using (city, dt) left join sw using (city, dt)
        group by s.city, s.dt""")
    compare["dt"] = pd.to_datetime(compare["dt"]).dt.date
    compare = compare[compare["dt"].isin(days)].groupby("city").agg(
        fleet=("fleet", "mean"), a=("a", "mean"), b=("b", "mean"), o=("o", "mean"),
        dep=("dep", "mean"), swaps=("swaps", "mean")).reset_index()
    compare["pct_available"] = compare["a"] / compare["fleet"]
    compare["pct_battery"] = compare["b"] / compare["fleet"]
    compare["pct_other"] = compare["o"] / compare["fleet"]
    compare["dep_per_scooter_day"] = compare["dep"] / compare["fleet"]
    compare = compare.merge(
        pd.DataFrame([dict(city=c, **wait_stats(g)) for c, g in waits.groupby("city")]), on="city")
    compare = compare.sort_values("city", ascending=False)

    quality = q(con, """
        select
            count(*) filter (where battery_pct > 100)                                    as over_100_obs,
            count(distinct track_id) filter (where battery_pct > 100)                    as over_100_vehicles,
            count(*) filter (where not is_disabled and battery_pct < 15 and is_valid_position) as active_low_obs,
            count(*) filter (where is_valid_position)                                    as valid_obs,
            count(distinct snapshot_ts) filter (where lat = 0 and lon = 0)               as null_island_snaps
        from stg_vehicle_snapshots""").iloc[0]

    tracking_rate = q(con, """
        select avg((st.first_seen_ts < o.snapshot_ts)::int) as rate
        from stg_vehicle_snapshots o
        join stg_snapshots s using (city, snapshot_ts)
        join fct_vehicle_stays st using (city, track_id)
        where o.city = $city and o.track_id is not null
          and s.seconds_since_previous <= 360""", city=CITY).iloc[0].rate

    oa = out_of_area(con, cache)
    ZONE_NAMES_CACHE.parent.mkdir(parents=True, exist_ok=True)
    ZONE_NAMES_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    fleet = hf["avg_listed"].mean()
    return dict(
        window=window, days=days, n_days=len(days), profile=profile, evenings=ev,
        fleet=fleet,
        pct_available=hf["avg_available"].mean() / fleet,
        pct_battery=hf["avg_disabled_battery"].mean() / fleet,
        pct_other=hf["avg_disabled_other"].mean() / fleet,
        battery_queue_min=profile["battery"].min(), battery_queue_max=profile["battery"].max(),
        departures_per_day=hf["departures"].sum() / len(days),
        swaps_per_day=len(swaps_full) / len(days),
        swaps_from_disabled=swaps_full["previous_is_disabled"].mean(),
        swap_battery_before=swaps_full["previous_battery_pct"].mean(),
        swap_battery_after=swaps_full["battery_pct"].mean(),
        wait=wait_stats(w_nice),
        wait_midday=swapped.loc[swapped["start_hour"].between(*MIDDAY_HOURS), "wait_hours"].median(),
        wait_late=swapped.loc[swapped["start_hour"].between(*LATE_HOURS), "wait_hours"].median(),
        waiting_now=len(ongoing), waiting_now_max_days=ongoing["wait_hours"].max() / 24 if len(ongoing) else 0,
        other_now=len(other_idle),
        other_now_long=int((other_idle["stay_hours"] >= IDLE_HOURS).sum()),
        other_now_3d=int((other_idle["stay_hours"] >= 72).sum()),
        other_now_max_days=other_idle["stay_hours"].max() / 24 if len(other_idle) else 0,
        tension=tension, surplus=surplus, n_zone_days=n_zone_days,
        compare=compare, quality=quality, out_of_area=oa,
        tracking_rate=tracking_rate, tests=dbt_test_summary(),
    )
