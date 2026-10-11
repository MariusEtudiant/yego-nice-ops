-- Changements de batterie detectes : meme vehicule (track_id), meme emplacement, batterie qui
-- remonte d'au moins swap_min_gain points d'un snapshot au suivant. Les scooters YEGO ne se
-- rechargent pas sur la voirie : une telle hausse est une intervention terrain.

with obs as (
    select
        city,
        track_id,
        vehicle_type,
        snapshot_ts,
        snapshot_at_local,
        zone_id,
        lat,
        lon,
        battery_pct,
        lag(battery_pct) over (partition by city, track_id order by snapshot_ts) as previous_battery_pct
    from {{ ref('stg_vehicle_snapshots') }}
    where track_id is not null
)

select
    *,
    battery_pct - previous_battery_pct as battery_gain_pct
from obs
where battery_pct - previous_battery_pct >= {{ var("swap_min_gain") }}
