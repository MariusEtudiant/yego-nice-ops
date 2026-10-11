"""
Reconstitue un identifiant de vehicule stable a partir des snapshots GBFS.

Probleme : YEGO regenere le bike_id a chaque requete (anonymisation), on ne peut donc pas
suivre un vehicule par son identifiant.

Constat sur les donnees : entre deux snapshots a 2 min d'intervalle, 99 % des vehicules ont
un voisin a moins de 15 m dans le snapshot suivant (80 % exactement a la meme position ; le
reste est du bruit GPS d'un vehicule a l'arret).

Regle de suivi, entre deux snapshots consecutifs :
  * paires candidates : meme type de vehicule, a moins de MATCH_RADIUS_M metres ;
  * cout d'une paire : distance (m) + BATTERY_WEIGHT_M x ecart de batterie (points) ;
  * affectation optimale un-pour-un (algorithme hongrois) par groupe de vehicules proches.
Le simple "plus proche voisin reciproque" ne suffit pas : quand plusieurs scooters sont gares
cote a cote, le bruit GPS echange les voisins et coupe a tort ~10 % des suivis.
Un trou de collecte (> GAP_TOLERANCE_S) coupe tous les suivis : on ne sait pas ce qui s'est passe.

Sortie : data/tracks/city=<ville>/tracks.parquet
         (city, snapshot_ts, volatile_bike_id, track_id) -> jointure dans dbt.
"""

from __future__ import annotations

import pathlib

import duckdb
import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW_GLOB = (ROOT / "data" / "raw" / "*" / "*" / "*.parquet").as_posix()
OUT_DIR = ROOT / "data" / "tracks"

MATCH_RADIUS_M = 15.0
BATTERY_WEIGHT_M = 0.5  # 1 point de batterie d'ecart "coute" 0,5 m : simple departage
# Seconde passe sur les restes : saut GPS plus large, mais batterie quasi identique.
JUMP_RADIUS_M = 150.0
JUMP_MAX_BATTERY_DIFF = 2
GAP_TOLERANCE_S = 360
EARTH_RADIUS_M = 6_371_000

# Emprises de service : identiques a stg_vehicle_snapshots (is_valid_position).
BBOX = {
    "nice": (43.60, 43.80, 7.10, 7.40),
    "barcelona": (41.30, 41.50, 2.00, 2.30),
}


def load_city(city: str) -> pd.DataFrame:
    lat_min, lat_max, lon_min, lon_max = BBOX[city]
    return duckdb.sql(
        f"""
        select snapshot_ts, bike_id as volatile_bike_id, lat, lon, vehicle_type_id,
               current_fuel_percent as battery_pct
        from read_parquet('{RAW_GLOB}', hive_partitioning = true)
        where city = '{city}'
          and lat between {lat_min} and {lat_max}
          and lon between {lon_min} and {lon_max}
        order by snapshot_ts
        """
    ).df()


def to_xy(lat: np.ndarray, lon: np.ndarray, lat0: float) -> np.ndarray:
    """Projection equirectangulaire locale, en metres (suffisant a l'echelle d'une ville)."""
    x = EARTH_RADIUS_M * np.radians(lon) * np.cos(np.radians(lat0))
    y = EARTH_RADIUS_M * np.radians(lat)
    return np.column_stack([x, y])


def match(xy, types, batt, prev_xy, prev_types, prev_batt,
          radius=MATCH_RADIUS_M, max_batt_diff=np.inf) -> tuple[np.ndarray, np.ndarray]:
    """Appariement un-pour-un entre snapshot courant et precedent. Renvoie (idx_cur, idx_prev)."""
    empty = np.array([], dtype=np.int64)
    if len(xy) == 0 or len(prev_xy) == 0:
        return empty, empty
    pairs = cKDTree(xy).sparse_distance_matrix(cKDTree(prev_xy), radius, output_type="ndarray")
    i, j, dist = pairs["i"], pairs["j"], pairs["v"]
    keep = (types[i] == prev_types[j]) & (np.abs(batt[i] - prev_batt[j]) <= max_batt_diff)
    i, j, dist = i[keep], j[keep], dist[keep]
    if len(i) == 0:
        return i, j
    cost = dist + BATTERY_WEIGHT_M * np.abs(batt[i] - prev_batt[j])

    # Graphe biparti des paires candidates : on resout chaque groupe connexe separement.
    n_cur, n_prev = len(xy), len(prev_xy)
    graph = coo_matrix((np.ones(len(i)), (i, n_cur + j)), shape=(n_cur + n_prev,) * 2)
    _, labels = connected_components(graph, directed=False)
    comp = labels[i]

    out_i, out_j = [], []
    order = np.argsort(comp, kind="stable")
    bounds = np.flatnonzero(np.diff(comp[order])) + 1
    for edges in np.split(order, bounds):
        if len(edges) == 1:  # cas tres majoritaire : un seul candidat
            out_i.append(i[edges]); out_j.append(j[edges])
            continue
        ci, ri = np.unique(i[edges], return_inverse=True)
        cj, rj = np.unique(j[edges], return_inverse=True)
        m = np.full((len(ci), len(cj)), 1e9)
        m[ri, rj] = cost[edges]
        a, b = linear_sum_assignment(m)
        ok = m[a, b] < 1e9
        out_i.append(ci[a[ok]]); out_j.append(cj[b[ok]])
    return np.concatenate(out_i), np.concatenate(out_j)


def track_city(city: str) -> pd.DataFrame:
    df = load_city(city)
    if df.empty:
        return df
    lat0 = df["lat"].mean()
    lat, lon = df["lat"].to_numpy(), df["lon"].to_numpy()
    all_types = df["vehicle_type_id"].to_numpy()
    all_batt = df["battery_pct"].to_numpy(dtype=float)
    track_ids = np.empty(len(df), dtype=np.int64)
    next_id = 0

    prev = None  # (ts, xy, types, batt, ids)
    for ts, rows in df.groupby("snapshot_ts", sort=True).indices.items():
        xy = to_xy(lat[rows], lon[rows], lat0)
        types, batt = all_types[rows], all_batt[rows]
        ids = np.full(len(rows), -1, dtype=np.int64)

        if prev is not None and ts - prev[0] <= GAP_TOLERANCE_S:
            p_xy, p_types, p_batt, p_ids = prev[1:]
            cur, prv = match(xy, types, batt, p_xy, p_types, p_batt)
            ids[cur] = p_ids[prv]
            # Seconde passe sur les vehicules restes sans partenaire des deux cotes.
            rc = np.setdiff1d(np.arange(len(xy)), cur)
            rp = np.setdiff1d(np.arange(len(p_xy)), prv)
            c2, p2 = match(xy[rc], types[rc], batt[rc], p_xy[rp], p_types[rp], p_batt[rp],
                           radius=JUMP_RADIUS_M, max_batt_diff=JUMP_MAX_BATTERY_DIFF)
            ids[rc[c2]] = p_ids[rp[p2]]

        new = ids == -1
        ids[new] = np.arange(next_id, next_id + new.sum())
        next_id += int(new.sum())
        track_ids[rows] = ids
        prev = (ts, xy, types, batt, ids)

    return pd.DataFrame(
        {
            "city": city,
            "snapshot_ts": df["snapshot_ts"],
            "volatile_bike_id": df["volatile_bike_id"],
            "track_id": [f"{city}-{t}" for t in track_ids],
        }
    )


def main() -> None:
    for city in BBOX:
        tracks = track_city(city)
        out = OUT_DIR / f"city={city}"
        out.mkdir(parents=True, exist_ok=True)
        tracks.drop(columns="city").to_parquet(out / "tracks.parquet", index=False)
        n_obs = len(tracks)
        n_tracks = tracks["track_id"].nunique() if n_obs else 0
        print(f"{city}: {n_obs} observations -> {n_tracks} vehicules suivis")


if __name__ == "__main__":
    main()
