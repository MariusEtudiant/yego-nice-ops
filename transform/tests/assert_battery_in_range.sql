-- La batterie publiee doit etre un pourcentage valide.
select *
from {{ ref('stg_vehicle_snapshots') }}
where battery_pct < 0 or battery_pct > 100
