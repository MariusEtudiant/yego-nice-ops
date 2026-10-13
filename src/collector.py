"""
YEGO Nice - Operations Monitor : collecteur GBFS.

Capture le flux GBFS free-floating de YEGO (Nice, et Barcelone en comparaison) et stocke
chaque snapshot en Parquet partitionne par ville et par jour. Concu pour tourner sans surveillance pendant
plusieurs jours : il ne doit JAMAIS crasher sur une erreur reseau.

Usage :
    python collector.py              # une seule capture (test)
    python collector.py --loop       # boucle infinie, toutes les INTERVAL secondes
    python collector.py --loop --interval 120
    python collector.py --loop --minutes 55 --merge --out-dir store/data   # une heure, GitHub Actions
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import pathlib
import sys
import time

import pyarrow as pa
import pyarrow.parquet as pq
import requests

# --- Configuration --------------------------------------------------------

# Nice = terrain d'analyse principal ; Barcelone = siege de YEGO, sert de point de comparaison.
CITIES = ["nice", "barcelona"]


def base_url(city: str) -> str:
    return f"https://services.rideyego.com/gbfs/2-3/{city}/en"

# Flux dynamique : capture a chaque snapshot.
DYNAMIC_FEED = "free_bike_status"
# Flux (quasi) statiques : captures une fois au demarrage, puis 1x/jour.
STATIC_FEEDS = ["system_information", "vehicle_types", "geofencing_zones", "system_pricing_plans"]

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_RAW = ROOT / "data" / "raw"
DATA_STATIC = ROOT / "data" / "static"
LOG_DIR = ROOT / "logs"

DEFAULT_INTERVAL = 120  # secondes (ttl du flux = 85 s)
HTTP_TIMEOUT = 20
HTTP_RETRIES = 3
RETRY_BACKOFF = 5  # secondes

# Champs qu'on garde pour chaque vehicule (schema stable du mart).
BIKE_FIELDS = [
    "bike_id",
    "lat",
    "lon",
    "vehicle_type_id",
    "current_fuel_percent",
    "current_range_meters",
    "is_reserved",
    "is_disabled",
    "pricing_plan_id",
    "last_reported",
]

# --- Logging ---------------------------------------------------------------


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("yego")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(LOG_DIR / "collector.log", encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


log = setup_logging()

# --- HTTP ------------------------------------------------------------------


def fetch_json(url: str) -> dict | None:
    """GET + parse JSON, avec retries. Renvoie None en cas d'echec total."""
    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            r = requests.get(url, timeout=HTTP_TIMEOUT, headers={"User-Agent": "yego-nice-ops/1.0"})
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001 - on veut tout attraper
            log.warning("fetch %s echec (tentative %d/%d) : %s", url, attempt, HTTP_RETRIES, exc)
            if attempt < HTTP_RETRIES:
                time.sleep(RETRY_BACKOFF)
    log.error("fetch %s abandonne apres %d tentatives", url, HTTP_RETRIES)
    return None


# --- Capture ---------------------------------------------------------------


def capture_snapshot(city: str) -> pathlib.Path | None:
    """Capture un snapshot du flux dynamique. Renvoie le fichier ecrit (None si echec)."""
    snapshot_ts = int(time.time())
    payload = fetch_json(f"{base_url(city)}/{DYNAMIC_FEED}")
    if not payload:
        return None

    feed_last_updated = payload.get("last_updated")
    bikes = payload.get("data", {}).get("bikes", [])
    if not bikes:
        log.warning("%s snapshot %d : 0 vehicule dans le flux", city, snapshot_ts)
        return None

    # Construction en colonnes (une ligne = un vehicule a cet instant).
    cols: dict[str, list] = {f: [] for f in BIKE_FIELDS}
    for b in bikes:
        for f in BIKE_FIELDS:
            cols[f].append(b.get(f))

    n = len(bikes)
    table = pa.table(
        {
            "snapshot_ts": pa.array([snapshot_ts] * n, pa.int64()),
            "feed_last_updated": pa.array([feed_last_updated] * n, pa.int64()),
            "bike_id": pa.array(cols["bike_id"], pa.string()),
            "lat": pa.array(cols["lat"], pa.float64()),
            "lon": pa.array(cols["lon"], pa.float64()),
            "vehicle_type_id": pa.array(cols["vehicle_type_id"], pa.string()),
            "current_fuel_percent": pa.array(cols["current_fuel_percent"], pa.float64()),
            "current_range_meters": pa.array(cols["current_range_meters"], pa.int64()),
            "is_reserved": pa.array(cols["is_reserved"], pa.bool_()),
            "is_disabled": pa.array(cols["is_disabled"], pa.bool_()),
            "pricing_plan_id": pa.array(cols["pricing_plan_id"], pa.string()),
            "last_reported": pa.array(cols["last_reported"], pa.int64()),
        }
    )

    day = dt.datetime.utcfromtimestamp(snapshot_ts).strftime("%Y-%m-%d")
    out_dir = DATA_RAW / f"city={city}" / f"date={day}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"fbs_{snapshot_ts}.parquet"
    pq.write_table(table, out_path, compression="zstd")
    log.info("%s snapshot %d : %d vehicules -> %s", city, snapshot_ts, n, out_path.name)
    return out_path


def merge_files(paths: list[pathlib.Path]) -> None:
    """Fusionne les snapshots d'une meme ville et d'un meme jour en un seul Parquet
    (fbs_<premier>_<dernier>.parquet) : 24 fichiers par jour et par ville au lieu de 720."""
    by_folder: dict[pathlib.Path, list[pathlib.Path]] = {}
    for p in paths:
        by_folder.setdefault(p.parent, []).append(p)
    for folder, files in by_folder.items():
        files = sorted(files)
        if len(files) < 2:
            continue
        first, last = files[0].stem.split("_")[1], files[-1].stem.split("_")[1]
        merged = pa.concat_tables([pq.read_table(f) for f in files])
        pq.write_table(merged, folder / f"fbs_{first}_{last}.parquet", compression="zstd")
        for f in files:
            f.unlink()
        log.info("%s/%s : %d snapshots fusionnes", folder.parent.name, folder.name, len(files))


def capture_static(city: str) -> None:
    """Capture les flux statiques (system_information, vehicle_types, zones, pricing)."""
    day = dt.datetime.utcnow().strftime("%Y-%m-%d")
    out_dir = DATA_STATIC / f"city={city}" / f"date={day}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for feed in STATIC_FEEDS:
        if (out_dir / f"{feed}.json").exists():  # deja capture aujourd'hui
            continue
        payload = fetch_json(f"{base_url(city)}/{feed}")
        if payload:
            (out_dir / f"{feed}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            log.info("%s statique capture : %s", city, feed)


def capture_all_static() -> None:
    for city in CITIES:
        capture_static(city)


def capture_all_snapshots() -> list[pathlib.Path]:
    return [p for p in (capture_snapshot(city) for city in CITIES) if p is not None]


# --- Entree ----------------------------------------------------------------


def main() -> None:
    global DATA_RAW, DATA_STATIC
    parser = argparse.ArgumentParser(description="Collecteur GBFS YEGO (Nice + Barcelone)")
    parser.add_argument("--loop", action="store_true", help="boucle (infinie sauf --minutes)")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, help="secondes entre captures")
    parser.add_argument("--minutes", type=float, default=None, help="arrete la boucle apres N minutes")
    parser.add_argument("--merge", action="store_true", help="fusionne les snapshots a la fin")
    parser.add_argument("--out-dir", default=None, help="dossier data/ de sortie (defaut : data/ du projet)")
    args = parser.parse_args()
    if args.out_dir:
        DATA_RAW = pathlib.Path(args.out_dir) / "raw"
        DATA_STATIC = pathlib.Path(args.out_dir) / "static"

    log.info("=== demarrage collecteur YEGO %s (loop=%s, interval=%ds) ===", CITIES, args.loop, args.interval)
    capture_all_static()
    last_static_day = dt.datetime.utcnow().strftime("%Y-%m-%d")

    if not args.loop:
        capture_all_snapshots()
        return

    deadline = time.time() + args.minutes * 60 if args.minutes else None
    written: list[pathlib.Path] = []
    while deadline is None or time.time() < deadline:
        start = time.time()
        try:
            written += capture_all_snapshots()
            today = dt.datetime.utcnow().strftime("%Y-%m-%d")
            if today != last_static_day:
                capture_all_static()
                last_static_day = today
        except Exception as exc:  # noqa: BLE001 - la boucle ne doit jamais mourir
            log.error("erreur inattendue dans la boucle : %s", exc)
        # Dort le temps restant pour tenir la cadence, sans deriver ni depasser l'echeance.
        pause = max(1, args.interval - (time.time() - start))
        if deadline is not None and time.time() + pause >= deadline:
            break
        time.sleep(pause)

    if args.merge:
        merge_files(written)


if __name__ == "__main__":
    main()
