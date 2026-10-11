-- Chaque vehicule doit se trouver dans l'emprise de sa ville (detecte un GPS aberrant, ex. 0,0).
-- En avertissement : ces lignes sont deja exclues des marts via is_valid_position,
-- mais on veut continuer a les voir remonter.
{{ config(severity = 'warn') }}

select *
from {{ ref('stg_vehicle_snapshots') }}
where not is_valid_position
