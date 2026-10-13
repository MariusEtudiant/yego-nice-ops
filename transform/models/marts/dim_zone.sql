-- Une ligne = une zone de ~500 m. Le centre est recalcule a partir de l'identifiant de grille
-- (ville_i_j avec i = floor(lat / 0.0045), j = floor(lon / 0.0062)), donc toute zone citee
-- par un fait existe ici, meme sans vehicule disponible observe.

with zone_ids as (
    select city, zone_id from {{ ref('fct_zone_hourly') }}
    union
    select city, zone_id from {{ ref('fct_battery_swaps') }}
),

names as (
    unpivot (select * from read_json_auto('{{ var("zone_names_path") }}'))
    on columns(*)
    into name zone_id value zone_name
)

select
    z.city,
    z.zone_id,
    coalesce(n.zone_name, z.zone_id)                                  as zone_name,
    n.zone_name is not null                                           as has_name,
    cast((cast(split_part(z.zone_id, '_', 2) as integer) + 0.5) * 0.0045 as double)   as zone_lat,
    cast((cast(split_part(z.zone_id, '_', 3) as integer) + 0.5) * 0.0062 as double)   as zone_lon
from zone_ids z
left join names n using (zone_id)
