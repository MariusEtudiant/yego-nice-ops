-- Une ligne = une heure locale de la journee (0 a 23), avec un libelle et une periode.

select
    h                                       as local_hour,
    lpad(cast(h as varchar), 2, '0') || 'h' as hour_label,
    case
        when h < 7  then 'Night'
        when h < 12 then 'Morning'
        when h < 18 then 'Afternoon'
        else 'Evening'
    end                                     as day_period
from range(24) as hours(h)
