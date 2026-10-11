-- Etat de la flotte par ville et par heure.
-- Le flux GBFS ne liste que les vehicules a l'arret : un vehicule en cours de location disparait
-- du flux. La baisse du nombre de vehicules listes est donc un proxy de l'usage.

with per_snapshot as (
    select
        city,
        snapshot_ts,
        any_value(snapshot_at_local)                                       as snapshot_at_local,
        count(*)                                                           as n_listed,
        count(*) filter (where is_available)                               as n_available,
        count(*) filter (where is_disabled)                                as n_disabled,
        count(*) filter (where is_reserved)                                as n_reserved,
        count(*) filter (where is_low_battery and not is_disabled)         as n_low_battery,
        avg(battery_pct)                                                   as avg_battery_pct
    from {{ ref('stg_vehicle_snapshots') }}
    where is_valid_position
    group by city, snapshot_ts
)

select
    city,
    date_trunc('hour', snapshot_at_local)   as hour_local,
    hour(snapshot_at_local)                 as local_hour,
    count(*)                                as n_snapshots,
    avg(n_listed)                           as avg_listed,
    avg(n_available)                        as avg_available,
    avg(n_disabled)                         as avg_disabled,
    avg(n_reserved)                         as avg_reserved,
    avg(n_low_battery)                      as avg_low_battery,
    avg(avg_battery_pct)                    as avg_battery_pct
from per_snapshot
group by all
order by city, hour_local
