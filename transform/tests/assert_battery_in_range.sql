-- La batterie publiee doit etre un pourcentage valide.
-- En avertissement : le flux publie parfois 101 % (4 scooters de Barcelone, autonomie 50,5 km
-- pour 50 km annonces). Anomalie du flux a signaler, sans effet sur les indicateurs.
{{ config(severity = 'warn') }}

select *
from {{ ref('stg_vehicle_snapshots') }}
where battery_pct < 0 or battery_pct > 100
