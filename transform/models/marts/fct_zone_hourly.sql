-- Offre et demande par zone (~500 m) et par heure de la journee, pour une journee moyenne.
--   avg_available       : vehicules disponibles en moyenne (une zone vide dans un snapshot compte 0)
--   departures_per_day  : departs observes (proxy de la demande, inclut les retraits Operations)
--   arrivals_per_day    : arrivees observees (fins de location, depots Operations)

with hours as (
    select
        city,
        hour(snapshot_at_local)                           as local_hour,
        count(*)                                          as n_snapshots,
        count(distinct cast(snapshot_at_local as date))   as n_days
    from {{ ref('stg_snapshots') }}
    group by all
),

supply as (
    select
        city,
        zone_id,
        local_hour,
        count(*) filter (where is_available)                         as available_obs,
        count(*) filter (where is_low_battery and not is_disabled)   as low_battery_obs,
        avg(lat)                                                     as zone_lat,
        avg(lon)                                                     as zone_lon
    from {{ ref('stg_vehicle_snapshots') }}
    where is_valid_position
    group by all
),

departures as (
    select city, end_zone_id as zone_id, hour(last_seen_local) as local_hour, count(*) as n
    from {{ ref('fct_vehicle_stays') }}
    where is_departure
    group by all
),

arrivals as (
    select city, start_zone_id as zone_id, hour(first_seen_local) as local_hour, count(*) as n
    from {{ ref('fct_vehicle_stays') }}
    where is_arrival
    group by all
),

keys as (
    select city, zone_id, local_hour from supply
    union
    select city, zone_id, local_hour from departures
    union
    select city, zone_id, local_hour from arrivals
)

select
    k.city,
    k.zone_id,
    k.local_hour,
    s.zone_lat,
    s.zone_lon,
    coalesce(s.available_obs, 0)  / h.n_snapshots     as avg_available,
    coalesce(s.low_battery_obs, 0) / h.n_snapshots    as avg_low_battery,
    coalesce(d.n, 0) / h.n_days                       as departures_per_day,
    coalesce(a.n, 0) / h.n_days                       as arrivals_per_day
from keys k
join hours h using (city, local_hour)
left join supply s     using (city, zone_id, local_hour)
left join departures d using (city, zone_id, local_hour)
left join arrivals a   using (city, zone_id, local_hour)
