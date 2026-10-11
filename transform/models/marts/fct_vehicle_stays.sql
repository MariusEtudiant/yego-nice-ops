-- Une ligne = un sejour d'un vehicule a un emplacement (un track_id), du moment ou il apparait
-- dans le flux jusqu'a celui ou il en disparait.
--
-- Un vehicule disparait du flux quand il est loue (ou retire par les Operations) : la fin d'un
-- sejour est donc un DEPART, son debut une ARRIVEE.
--
-- Censure : un sejour deja en cours au debut de la collecte, ou juste apres un trou de collecte,
-- a une duree sous-estimee et une arrivee inconnue (left_censored). Symetriquement, un sejour
-- qui se termine sur un trou n'est pas un depart observe.

with obs as (
    select *
    from {{ ref('stg_vehicle_snapshots') }}
    where track_id is not null
),

snapshots as (
    select
        city,
        snapshot_ts,
        seconds_since_previous,
        seconds_to_next,
        snapshot_ts = min(snapshot_ts) over (partition by city)   as is_first_snapshot,
        snapshot_ts = max(snapshot_ts) over (partition by city)   as is_last_snapshot
    from {{ ref('stg_snapshots') }}
),

stays as (
    select
        city,
        track_id,
        any_value(vehicle_type)                     as vehicle_type,
        min(snapshot_ts)                            as first_seen_ts,
        max(snapshot_ts)                            as last_seen_ts,
        min(snapshot_at_local)                      as first_seen_local,
        max(snapshot_at_local)                      as last_seen_local,
        count(*)                                    as n_observations,
        arg_min(zone_id, snapshot_ts)               as start_zone_id,
        arg_max(zone_id, snapshot_ts)               as end_zone_id,
        arg_max(lat, snapshot_ts)                   as end_lat,
        arg_max(lon, snapshot_ts)                   as end_lon,
        arg_min(battery_pct, snapshot_ts)           as battery_start_pct,
        arg_max(battery_pct, snapshot_ts)           as battery_end_pct,
        arg_max(is_disabled, snapshot_ts)           as is_disabled_at_end,
        bool_or(is_disabled)                        as was_disabled
    from obs
    group by city, track_id
)

select
    s.*,
    (s.last_seen_ts - s.first_seen_ts) / 3600.0                                         as stay_hours,
    f.is_first_snapshot
        or coalesce(f.seconds_since_previous, 0) > {{ var("gap_tolerance_s") }}         as left_censored,
    l.is_last_snapshot                                                                  as still_listed,
    not l.is_last_snapshot
        and coalesce(l.seconds_to_next, 0) <= {{ var("gap_tolerance_s") }}              as is_departure,
    not f.is_first_snapshot
        and coalesce(f.seconds_since_previous, 0) <= {{ var("gap_tolerance_s") }}       as is_arrival
from stays s
join snapshots f on f.city = s.city and f.snapshot_ts = s.first_seen_ts
join snapshots l on l.city = s.city and l.snapshot_ts = s.last_seen_ts
