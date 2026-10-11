-- Une ligne = un vehicule vu dans un snapshot.
-- Le bike_id GBFS est regenere a chaque requete : on ne s'en sert jamais comme cle de suivi.
-- track_id est l'identifiant stable reconstruit par src/track_vehicles.py (position + type + batterie).

with raw as (
    select *
    from read_parquet('{{ var("raw_glob") }}', hive_partitioning = true)
),

tracks as (
    select *
    from read_parquet('{{ var("tracks_glob") }}', hive_partitioning = true)
)

select
    raw.city,
    raw.snapshot_ts,
    timezone('Europe/Paris', to_timestamp(raw.snapshot_ts))           as snapshot_at_local,
    hour(timezone('Europe/Paris', to_timestamp(raw.snapshot_ts)))     as local_hour,
    raw.bike_id                                                       as volatile_bike_id,
    tracks.track_id,
    raw.vehicle_type_id                                               as vehicle_type,
    raw.lat,
    raw.lon,
    -- Zone ~ 500 m : grille reguliere, lisible et sans dependance externe.
    raw.city || '_' || cast(floor(raw.lat / 0.0045) as integer)
             || '_' || cast(floor(raw.lon / 0.0062) as integer)       as zone_id,
    raw.current_fuel_percent                                          as battery_pct,
    raw.current_range_meters / 1000.0                                 as range_km,
    raw.is_reserved,
    raw.is_disabled,
    not raw.is_reserved and not raw.is_disabled                       as is_available,
    raw.current_fuel_percent < {{ var("low_battery_pct") }}           as is_low_battery,
    case
        when not raw.is_disabled then null
        when raw.current_fuel_percent < {{ var("disable_battery_pct") }} then 'battery'
        else 'other'
    end                                                               as unavailability_reason,
    -- Emprise de service (Barcelone inclut Badalona, L'Hospitalet, Cornella).
    (raw.city = 'nice'      and raw.lat between 43.60 and 43.80 and raw.lon between 7.10 and 7.40)
    or (raw.city = 'barcelona' and raw.lat between 41.30 and 41.50 and raw.lon between 2.00 and 2.30)
                                                                      as is_valid_position,
    raw.last_reported
from raw
left join tracks
    on  tracks.city = raw.city
    and tracks.snapshot_ts = raw.snapshot_ts
    and tracks.volatile_bike_id = raw.bike_id
-- Le collecteur ecrit en continu : on s'arrete au dernier snapshot traite par le suivi,
-- pour que staging et track_id restent coherents.
where raw.snapshot_ts <= (select max(snapshot_ts) from tracks t where t.city = raw.city)
