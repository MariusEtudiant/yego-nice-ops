-- Changements de batterie detectes : meme vehicule (track_id), batterie qui remonte d'au moins
-- swap_min_gain points d'un snapshot au suivant. Les scooters YEGO ne se rechargent pas sur la
-- voirie : une telle hausse est une intervention terrain.
--
-- is_confirmed : le vehicule etait desactive juste avant (cas typique : desactive sous 15 %,
-- batterie changee, reactive) ou n'a pas bouge de plus de swap_max_move_m metres. Les autres
-- cas peuvent etre deux vehicules differents gares au meme endroit.

with obs as (
    select
        city,
        track_id,
        snapshot_ts,
        snapshot_at_local,
        zone_id,
        lat,
        lon,
        battery_pct,
        is_disabled,
        lag(battery_pct) over w   as previous_battery_pct,
        lag(is_disabled) over w   as previous_is_disabled,
        lag(lat) over w           as previous_lat,
        lag(lon) over w           as previous_lon
    from {{ ref('stg_vehicle_snapshots') }}
    where track_id is not null
    window w as (partition by city, track_id order by snapshot_ts)
),

swaps as (
    select
        *,
        battery_pct - previous_battery_pct as battery_gain_pct,
        111320 * sqrt(
            power(lat - previous_lat, 2)
            + power((lon - previous_lon) * cos(radians(lat)), 2)
        )                                  as moved_m
    from obs
    where battery_pct - previous_battery_pct >= {{ var("swap_min_gain") }}
)

select
    *,
    previous_is_disabled or moved_m <= {{ var("swap_max_move_m") }} as is_confirmed
from swaps
