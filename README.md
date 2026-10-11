# YEGO Nice — Operations Monitor

Pipeline data de bout en bout sur la flotte de scooters électriques en free-floating
de **YEGO à Nice**, construit à partir de son flux public **GBFS**.

> Objectif : analyser une semaine réelle d'exploitation de la flotte niçoise et en
> tirer des recommandations opérationnelles concrètes (repositionnement, maintenance,
> gestion de la batterie).

## Stack

`Python` (collecte) · `Parquet` + `DuckDB` (stockage / requêtes) · `dbt` (transformation)
· `H3` (découpage géographique) · `Streamlit` (dashboard) · `GitHub Actions` (orchestration)

## Architecture

```
GBFS (services.rideyego.com)
   │  collecteur Python, 1 snapshot / 2 min
   ▼
data/raw/date=YYYY-MM-DD/fbs_<epoch>.parquet      (snapshots bruts horodatés)
data/static/date=YYYY-MM-DD/*.json                (types de véhicules, zones, pricing)
   │  dbt + DuckDB
   ▼
staging  →  fait vehicle_snapshots  +  dimensions (zone H3, heure)
   │
   ▼
KPI opérationnels  →  dashboard Streamlit  +  one-pager PDF
```

## Note technique : anonymisation des identifiants

Le flux GBFS de YEGO **régénère le `bike_id` à chaque requête** : vérifié
empiriquement, **0 %** des identifiants persistent entre deux snapshots espacés de
4 min, alors que 113 véhicules étaient à une position strictement identique (donc
immobiles). Le suivi d'un véhicule par son ID est donc impossible.

Conséquence : le temps d'immobilisation et les trajets sont reconstruits par
**matching de proximité géographique** entre snapshots successifs, pas par l'ID.
Les KPI agrégés (disponibilité, batterie, véhicules désactivés) ne sont pas affectés.

## Données disponibles par véhicule

`lat` / `lon` · `current_fuel_percent` · `current_range_meters` · `vehicle_type_id`
(scooter / bike / kick) · `is_reserved` · `is_disabled` · `last_reported`.

## Lancer la collecte

```bash
pip install -r requirements.txt
python src/collector.py --loop --interval 120   # boucle, 1 snapshot / 2 min
python src/collector.py                         # une seule capture (cron / CI)
```

## Statut

🟢 Collecte en cours — en route vers 7 jours de données.
