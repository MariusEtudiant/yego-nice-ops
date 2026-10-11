-- Regle metier observee : YEGO desactive tout vehicule sous disable_battery_pct de batterie.
-- Un vehicule actif sous ce seuil signale soit un changement de regle, soit un defaut du flux.
{{ config(severity = 'warn') }}

select *
from {{ ref('stg_vehicle_snapshots') }}
where not is_disabled
  and battery_pct < {{ var("disable_battery_pct") }}
