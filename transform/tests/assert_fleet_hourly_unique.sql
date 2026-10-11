-- Une seule ligne par ville et par heure dans le mart.
select city, hour_local, count(*) as n
from {{ ref('fct_fleet_hourly') }}
group by all
having count(*) > 1
