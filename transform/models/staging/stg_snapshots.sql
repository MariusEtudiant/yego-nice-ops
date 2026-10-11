-- Une ligne = un snapshot (une ville, un instant). Sert au controle de completude de la collecte.

with snapshots as (
    select
        city,
        snapshot_ts,
        min(snapshot_at_local)    as snapshot_at_local,
        count(*)                  as n_vehicles
    from {{ ref('stg_vehicle_snapshots') }}
    group by city, snapshot_ts
)

select
    *,
    snapshot_ts - lag(snapshot_ts)  over (partition by city order by snapshot_ts)   as seconds_since_previous,
    lead(snapshot_ts) over (partition by city order by snapshot_ts) - snapshot_ts   as seconds_to_next
from snapshots
