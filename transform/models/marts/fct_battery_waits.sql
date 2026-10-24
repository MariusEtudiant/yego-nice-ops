-- Une ligne = une periode d'attente d'un scooter desactive faute de batterie (sous le seuil),
-- de sa premiere observation dans cet etat jusqu'a sa sortie de la file.
--
-- Issue de l'attente :
--   swapped  : batterie changee sur place (la batterie remonte d'au moins swap_min_gain points) ;
--   left     : le scooter disparait du flux (recupere par une camionnette, ou suivi perdu) ;
--   ongoing  : encore en attente au dernier releve (censure a droite) ;
--   other    : sortie de l'etat sans changement de batterie (reactivation, autre motif).
-- Une attente commencee au premier releve ou juste apres un trou de collecte a un debut inconnu
-- (left_censored) : sa duree est sous-estimee.

with obs as (
    select
        city,
        track_id,
        snapshot_ts,
        snapshot_at_local,
        zone_id,
        battery_pct,
        coalesce(unavailability_reason = 'battery', false)                          as is_waiting,
        lag(coalesce(unavailability_reason = 'battery', false)) over w               as was_waiting,
        lead(coalesce(unavailability_reason = 'battery', false)) over w              as next_waiting,
        lead(battery_pct) over w                                                     as next_battery_pct,
        lead(snapshot_ts) over w                                                     as next_ts
    from {{ ref('stg_vehicle_snapshots') }}
    where track_id is not null and is_valid_position
    window w as (partition by city, track_id order by snapshot_ts)
),

numbered as (
    select
        *,
        sum(case when is_waiting and not coalesce(was_waiting, false) then 1 else 0 end)
            over (partition by city, track_id order by snapshot_ts rows unbounded preceding) as episode
    from obs
),

episodes as (
    select
        city,
        track_id,
        episode,
        min(snapshot_ts)                                                      as start_ts,
        max(snapshot_ts)                                                      as end_ts,
        min(snapshot_at_local)                                                as start_local,
        arg_min(zone_id, snapshot_ts)                                         as zone_id,
        min(battery_pct)                                                      as min_battery_pct,
        -- Valeurs de l'observation qui suit la derniere observation en attente.
        max(next_ts) filter (where not coalesce(next_waiting, false))         as exit_ts,
        max(next_battery_pct) filter (where not coalesce(next_waiting, false)) as exit_battery_pct,
        arg_max(battery_pct, snapshot_ts)                                     as last_battery_pct
    from numbered
    where is_waiting
    group by city, track_id, episode
),

snapshots as (
    select
        city,
        snapshot_ts,
        seconds_since_previous,
        snapshot_ts = min(snapshot_ts) over (partition by city) as is_first_snapshot,
        snapshot_ts = max(snapshot_ts) over (partition by city) as is_last_snapshot
    from {{ ref('stg_snapshots') }}
)

select
    e.city,
    e.track_id,
    e.episode,
    e.start_ts,
    e.start_local,
    hour(e.start_local)                                                   as start_hour,
    e.zone_id,
    e.min_battery_pct,
    case
        when l.is_last_snapshot then 'ongoing'
        when e.exit_ts is null then 'left'
        when e.exit_battery_pct - e.last_battery_pct >= {{ var("swap_min_gain") }} then 'swapped'
        else 'other'
    end                                                                   as outcome,
    -- Duree d'attente : jusqu'au releve ou le scooter sort de la file (ou au dernier releve vu).
    (coalesce(e.exit_ts, e.end_ts) - e.start_ts) / 3600.0                 as wait_hours,
    f.is_first_snapshot
        or coalesce(f.seconds_since_previous, 0) > {{ var("gap_tolerance_s") }} as left_censored
from episodes e
join snapshots f on f.city = e.city and f.snapshot_ts = e.start_ts
join snapshots l on l.city = e.city and l.snapshot_ts = e.end_ts
