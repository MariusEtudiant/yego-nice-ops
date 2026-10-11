-- Toute observation a une position valide doit avoir recu un track_id.
-- Echoue si le suivi n'a pas ete relance apres l'arrivee de nouveaux snapshots.
select city, snapshot_ts, count(*) as n_untracked
from {{ ref('stg_vehicle_snapshots') }}
where is_valid_position and track_id is null
group by all
