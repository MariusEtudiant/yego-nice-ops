# YEGO Nice — Operations Monitor

Analyse opérationnelle de la flotte de scooters électriques **YEGO à Nice** (et Barcelone en
comparaison), construite uniquement à partir du flux public **GBFS** de l'opérateur.

**Livrable principal : [la note d'analyse d'une page](reports/note_yego_nice.pdf)**
(disponibilité, file d'attente batterie, offre et demande par quartier, 3 recommandations).

## Ce que montrent les données

- **YEGO désactive tout scooter sous 15 % de batterie.** Aucun véhicule actif sous ce seuil, dans
  les deux villes. Les véhicules désactivés se divisent donc en deux groupes : la file d'attente
  des changements de batterie, et les désactivations pour un autre motif (maintenance, etc.).
  Ce dernier groupe, invisible si l'on ne regarde que la batterie, pèse environ 11 % de la flotte
  niçoise, avec un socle d'une vingtaine de scooters immobiles toute la nuit.
- **Les changements de batterie sont détectables depuis l'extérieur** : même véhicule, même
  emplacement, batterie qui remonte (21 % → 91 % en moyenne) et véhicule réactivé.
- **La tournée batterie arrive après le pic du soir.** Le 11 octobre à Nice, 16 scooters étaient
  bloqués faute de batterie au pic de 19h (58 départs) ; 50 des 57 changements ont eu lieu entre
  20h et 2h.
- **Offre et demande par quartier** : stock moyen de scooters disponibles et départs observés par
  zone d'environ 500 m, nommées via OpenStreetMap.

## Le problème technique : des identifiants anonymisés

Le flux GBFS de YEGO **régénère le `bike_id` à chaque requête**. Entre deux relevés espacés de
4 minutes, aucun identifiant n'est commun, alors que 113 scooters n'avaient pas bougé d'un mètre.
Impossible donc de suivre un véhicule par son identifiant.

[`src/track_vehicles.py`](src/track_vehicles.py) reconstitue un identifiant stable :

1. paires candidates entre deux relevés successifs : même type de véhicule, à moins de 15 m ;
2. coût d'une paire : distance + petit poids sur l'écart de batterie ;
3. **affectation optimale un-pour-un** (algorithme hongrois), résolue par groupe de véhicules
   proches pour rester rapide sur les 1 700 scooters de Barcelone ;
4. seconde passe pour les sauts GPS jusqu'à 150 m, à batterie quasi identique.

Pourquoi pas un simple « plus proche voisin » ? Quand plusieurs scooters sont garés côte à côte, le
bruit GPS échange les voisins et coupait à tort environ 10 % des suivis.

Un véhicule loué disparaît du flux : la fin d'un suivi est donc un **départ**, son début une **arrivée**.

## Architecture

```
GBFS YEGO (Nice, Barcelone)
  │  src/collector.py — 1 relevé toutes les 2 min, ne s'arrête jamais sur une erreur réseau
  ▼
data/raw/city=…/date=…/fbs_<epoch>.parquet
  │  src/track_vehicles.py — identifiant stable reconstruit
  ▼
transform/ (dbt + DuckDB)
  staging   stg_vehicle_snapshots, stg_snapshots
  marts     fct_fleet_hourly       état de la flotte par heure
            fct_vehicle_stays      séjours, départs, arrivées
            fct_battery_swaps      changements de batterie détectés
            fct_zone_hourly        offre et demande par zone et par heure
  │  src/build_report.py
  ▼
reports/note_yego_nice.pdf
```

## Qualité des données (tests dbt)

| Test | Rôle |
|---|---|
| `assert_coords_in_city` | position hors de la zone de service : a détecté un scooter publié en (0, 0) |
| `assert_no_collection_gap` | trou dans la collecte au-delà de 6 min |
| `assert_low_battery_vehicles_are_disabled` | vérifie que la règle des 15 % tient toujours |
| `assert_valid_positions_are_tracked` | chaque observation valide a bien un identifiant stable |
| `assert_battery_in_range`, `not_null`, `accepted_values`, `unique` | intégrité de base |

Les anomalies (GPS aberrant, trou de collecte) sont en **avertissement** : elles sont exclues des
indicateurs mais restent visibles à chaque exécution.

## Lancer le projet

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # Windows ; bin/pip sous Linux/macOS
.venv/Scripts/python src/collector.py --loop       # collecte continue
.venv/Scripts/python src/pipeline.py               # suivi → dbt build → note → export
```

Les relevés bruts ne sont pas versionnés (un fichier par relevé). Le jeu de données complet est
dans [`data/compact/`](data/compact) : un Parquet par ville, avec l'identifiant reconstruit.

## Limites

- Période courte : les recommandations sont des premiers constats, à confirmer sur plusieurs semaines.
- Un « départ » inclut les retraits par les équipes terrain, que le flux public ne distingue pas
  d'une location.
- Les durées d'immobilisation des véhicules déjà présents au début de la collecte sont sous-estimées.
