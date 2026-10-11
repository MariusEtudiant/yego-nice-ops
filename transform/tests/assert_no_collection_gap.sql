-- Signale les trous de collecte (snapshot manquant au-dela de la tolerance).
-- En avertissement : un trou ne rend pas les donnees fausses, mais il doit etre visible.
{{ config(severity = 'warn') }}

select city, snapshot_at_local, seconds_since_previous
from {{ ref('stg_snapshots') }}
where seconds_since_previous > {{ var("gap_tolerance_s") }}
