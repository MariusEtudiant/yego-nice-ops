-- Une ligne = une ville couverte par la collecte.

select *
from (values
    ('nice',      'Nice',      'France', 'Europe/Paris'),
    ('barcelona', 'Barcelona', 'Spain',  'Europe/Madrid')
) as cities(city, city_name, country, timezone)
