"""
Note d'analyse operationnelle (1 page A4) a partir des marts dbt.

    python src/build_report.py

Sorties : reports/note_yego_nice.html et reports/note_yego_nice.pdf (impression via Edge headless).
Les noms de quartiers viennent du reverse geocoding OpenStreetMap (Nominatim), mis en cache dans
data/static/zone_names.json pour ne pas solliciter le service a chaque execution.
"""

from __future__ import annotations

import html
import io
import json
import os
import pathlib
import subprocess
import time

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import requests  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
TRANSFORM = ROOT / "transform"
DB_PATH = ROOT / "data" / "yego.duckdb"
REPORT_DIR = ROOT / "reports"
ZONE_NAMES_CACHE = ROOT / "data" / "static" / "zone_names.json"
EDGE = pathlib.Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

CITY = "nice"
REPO_URL = "github.com/Mariuscsm06/yego-nice-ops"
DISABLE_BATTERY_PCT = 15
IDLE_HOURS = 6

# Palette (categorielle, ordre fixe) et encre, fond clair.
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
SURFACE, INK, INK_2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"


# --- Donnees ---------------------------------------------------------------


def connect() -> duckdb.DuckDBPyConnection:
    # Les vues staging lisent les Parquet en chemin relatif au dossier dbt.
    os.chdir(TRANSFORM)
    return duckdb.connect(str(DB_PATH), read_only=True)


def q(con, sql: str, **params) -> pd.DataFrame:
    return con.execute(sql, params).df() if params else con.sql(sql).df()


def zone_name(zone_id: str, lat: float, lon: float, cache: dict) -> str:
    if zone_id in cache:
        return cache[zone_id]
    name = zone_id
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 16, "accept-language": "fr"},
            headers={"User-Agent": "yego-nice-ops/1.0 (portfolio, usage ponctuel)"},
            timeout=15,
        )
        addr = r.json().get("address", {})
        for key in ("neighbourhood", "quarter", "suburb", "road", "city_district"):
            if addr.get(key):
                name = addr[key]
                break
        time.sleep(1.1)  # politique d'usage Nominatim : 1 requete / seconde
    except Exception:  # noqa: BLE001 - un nom manquant ne doit pas bloquer la note
        pass
    cache[zone_id] = name
    return name


# --- Graphiques ------------------------------------------------------------


def style_axes(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=7, length=0)
    ax.yaxis.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def to_svg(fig) -> str:
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    svg = buf.getvalue()
    return svg[svg.index("<svg"):]


def chart_fleet_state(snap: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(3.7, 1.9), dpi=100)
    fig.patch.set_facecolor(SURFACE)
    style_axes(ax)
    x = snap["snapshot_at_local"]
    layers = [
        (snap["n_available"], "Disponibles", BLUE),
        (snap["n_disabled_battery"], f"Désactivés : batterie < {DISABLE_BATTERY_PCT} %", ORANGE),
        (snap["n_disabled_other"], "Désactivés : autre motif", AQUA),
    ]
    ax.stackplot(x, *[v for v, _, _ in layers], labels=[l for _, l, _ in layers],
                 colors=[c for _, _, c in layers], edgecolor=SURFACE, linewidth=0.8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Hh"))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
    ax.set_xlim(x.min(), x.max())
    ax.set_ylim(0, snap["n_listed"].max() * 1.05)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=3, frameon=False,
              fontsize=6.5, labelcolor=INK_2, handlelength=1, columnspacing=1)
    return to_svg(fig)


def chart_departures(dep: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(3.4, 1.9), dpi=100)
    fig.patch.set_facecolor(SURFACE)
    style_axes(ax)
    labels = [f"{h:%H}h" for h in dep["hour_local"]]
    ax.bar(range(len(dep)), dep["departures"], color=BLUE, width=0.72, edgecolor=SURFACE, linewidth=0.8)
    step = max(1, len(dep) // 8)
    ax.set_xticks(range(0, len(dep), step), labels[::step])
    # Libelle direct sur la seule valeur max.
    if len(dep):
        i = int(dep["departures"].idxmax())
        ax.annotate(f"{int(dep['departures'][i])}", (i, dep["departures"][i]), ha="center",
                    va="bottom", fontsize=7, color=INK, xytext=(0, 2), textcoords="offset points")
        ax.set_ylim(0, dep["departures"].max() * 1.18)
    return to_svg(fig)


# --- Calcul des indicateurs ------------------------------------------------


def build() -> dict:
    con = connect()
    p = {"city": CITY}

    window = q(con, """
        select min(snapshot_at_local) as start_at, max(snapshot_at_local) as end_at, count(*) as n_snapshots,
               count(*) filter (where seconds_since_previous > 360) as n_gaps,
               max(seconds_since_previous) as max_gap_s
        from stg_snapshots where city = $city""", **p).iloc[0]
    hours_observed = (window.end_at - window.start_at).total_seconds() / 3600

    snap = q(con, """
        select snapshot_ts, any_value(snapshot_at_local) as snapshot_at_local,
               count(*) as n_listed,
               count(*) filter (where is_available) as n_available,
               count(*) filter (where is_reserved) as n_reserved,
               count(*) filter (where unavailability_reason = 'battery') as n_disabled_battery,
               count(*) filter (where unavailability_reason = 'other') as n_disabled_other
        from stg_vehicle_snapshots where city = $city and is_valid_position
        group by snapshot_ts order by snapshot_ts""", **p)

    avg = snap.mean(numeric_only=True)
    last = snap.iloc[-1]

    stays = q(con, "select * from fct_vehicle_stays where city = $city", **p)
    departures_total = int(stays["is_departure"].sum())

    dep_hourly = q(con, """
        select date_trunc('hour', last_seen_local) as hour_local, count(*) as departures
        from fct_vehicle_stays where city = $city and is_departure
        group by 1 order by 1""", **p)

    swaps = q(con, "select * from fct_battery_swaps where city = $city and is_confirmed", **p)

    # Qualite du suivi : part des observations rattachees au vehicule du releve precedent
    # (hors premier releve et releves suivant un trou de collecte).
    tracking_rate = q(con, """
        select avg((st.first_seen_ts < o.snapshot_ts)::int) as rate
        from stg_vehicle_snapshots o
        join stg_snapshots s using (city, snapshot_ts)
        join fct_vehicle_stays st using (city, track_id)
        where o.city = $city and o.track_id is not null
          and s.seconds_since_previous <= 360""", **p).iloc[0].rate

    # Recommandation 1 : file d'attente batterie, par zone.
    battery_queue = q(con, """
        select zone_id, count(*) as n, avg(lat) as lat, avg(lon) as lon
        from stg_vehicle_snapshots
        where city = $city and is_valid_position and unavailability_reason = 'battery'
          and snapshot_ts = (select max(snapshot_ts) from stg_snapshots where city = $city)
        group by zone_id order by n desc""", **p)

    # Recommandation 2 : offre vs demande par zone, sur toute la fenetre.
    zones = q(con, """
        select zone_id, avg(zone_lat) as lat, avg(zone_lon) as lon,
               avg(avg_available) as stock, sum(departures_per_day) as departures
        from fct_zone_hourly where city = $city
        group by zone_id""", **p).dropna(subset=["lat"])
    zones["pressure"] = zones["departures"] / (zones["stock"] + 1)
    tension = zones[zones["departures"] >= 3].sort_values("pressure", ascending=False).head(3).copy()
    surplus = (zones[zones["stock"] >= 3]
               .sort_values(["departures", "stock"], ascending=[True, False]).head(3).copy())
    battery_queue_total = int(battery_queue["n"].sum())
    battery_queue = battery_queue.head(3).copy()

    # Recommandation 3 : vehicules desactives hors batterie et immobilises depuis longtemps.
    other_idle = stays[stays["still_listed"] & stays["is_disabled_at_end"]
                       & (stays["battery_end_pct"] >= DISABLE_BATTERY_PCT)]
    other_idle_long = other_idle[other_idle["stay_hours"] >= IDLE_HOURS]
    idle_all_long = stays[stays["still_listed"] & (stays["stay_hours"] >= IDLE_HOURS)]

    # Comparaison Barcelone (moyennes sur la fenetre commune).
    compare = q(con, """
        with s as (
            select city, snapshot_ts, count(*) n,
                   count(*) filter (where is_available) a,
                   count(*) filter (where unavailability_reason = 'battery') b,
                   count(*) filter (where unavailability_reason = 'other') o
            from stg_vehicle_snapshots where is_valid_position group by all),
        w as (select city, (max(snapshot_ts) - min(snapshot_ts)) / 3600.0 as h from stg_snapshots group by city),
        d as (select city, count(*) filter (where is_departure) dep from fct_vehicle_stays group by city),
        sw as (select city, count(*) filter (where is_confirmed) swaps from fct_battery_swaps group by city)
        select s.city, avg(n) fleet, avg(a) / avg(n) pct_available, avg(b) / avg(n) pct_battery,
               avg(o) / avg(n) pct_other,
               any_value(d.dep) / any_value(w.h) / avg(n) dep_per_vehicle_hour,
               coalesce(any_value(sw.swaps), 0) / any_value(w.h) swaps_per_hour
        from s join w using (city) left join d using (city) left join sw using (city)
        group by s.city order by s.city desc""")

    tests = dbt_test_summary()

    # Noms de quartiers.
    cache = json.loads(ZONE_NAMES_CACHE.read_text(encoding="utf-8")) if ZONE_NAMES_CACHE.exists() else {}
    for df in (battery_queue, tension, surplus):
        df["name"] = [zone_name(z, la, lo, cache) for z, la, lo in zip(df.zone_id, df.lat, df.lon)]
    ZONE_NAMES_CACHE.parent.mkdir(parents=True, exist_ok=True)
    ZONE_NAMES_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    return dict(
        window=window, hours_observed=hours_observed, snap=snap, avg=avg, last=last,
        departures_total=departures_total, dep_hourly=dep_hourly, swaps=swaps, tracking_rate=tracking_rate,
        battery_queue=battery_queue.assign(n=lambda d: d.n.astype(int)),
        battery_queue_total=battery_queue_total,
        tension=tension, surplus=surplus, other_idle=other_idle, other_idle_long=other_idle_long,
        idle_all_long=idle_all_long, compare=compare, tests=tests,
    )


def dbt_test_summary() -> dict:
    """Lit le dernier run_results.json de dbt pour afficher l'etat des tests dans la note."""
    path = TRANSFORM / "target" / "run_results.json"
    summary = {"pass": 0, "warn": 0, "fail": 0}
    if path.exists():
        for r in json.loads(path.read_text(encoding="utf-8"))["results"]:
            if r["unique_id"].startswith("test."):
                status = {"pass": "pass", "warn": "warn"}.get(r["status"], "fail")
                summary[status] += 1
    return summary


# --- Rendu -----------------------------------------------------------------


def fr(x: float, d: int = 0) -> str:
    s = f"{x:,.{d}f}".replace(",", " ").replace(".", ",")
    return s


def pct(x: float, d: int = 0) -> str:
    return f"{fr(100 * x, d)} %"


def names(df: pd.DataFrame) -> str:
    # Deux zones voisines peuvent porter le meme nom de quartier : on dedoublonne.
    return ", ".join(html.escape(n) for n in dict.fromkeys(df["name"])) if len(df) else "n/d"


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n > 1 else ''}"


def duration(hours: float) -> str:
    return f"{fr(hours * 60)} min" if hours < 2 else f"{fr(hours)} h"


def render(k: dict) -> str:
    w, avg, last = k["window"], k["avg"], k["last"]
    fleet = avg.n_listed
    unavailable = avg.n_disabled_battery + avg.n_disabled_other
    period = f"{w.start_at:%d/%m %Hh%M} → {w.end_at:%d/%m %Hh%M}"

    t, s = k["tension"], k["surplus"]
    surplus_stock = s["stock"].sum()
    tension_dep = t["departures"].sum()
    tension_stock = t["stock"].sum()
    move_n = int(max(1, min(surplus_stock - len(s), tension_dep - tension_stock)))

    bq, bq_total = k["battery_queue"], k["battery_queue_total"]
    bq_top = int(bq["n"].sum())

    if len(t):
        reposition = (
            f"Repositionner environ {plural(move_n, 'scooter')} vers les zones en tension",
            f"Les zones {names(t)} totalisent {fr(tension_dep)} départs/jour pour seulement "
            f"{fr(tension_stock, 1)} scooters disponibles en moyenne. À l'inverse, {names(s)} "
            f"immobilisent {fr(surplus_stock, 1)} scooters pour {fr(s['departures'].sum())} départs/jour. "
            f"Le volume exact est à calibrer sur plusieurs semaines.",
        )
    else:
        reposition = (
            "Surveiller les zones en surplus",
            f"{names(s)} immobilisent {fr(surplus_stock, 1)} scooters disponibles pour "
            f"{fr(s['departures'].sum())} départs/jour. La période observée est encore trop courte pour "
            f"désigner des zones en tension vers lesquelles les déplacer.",
        )

    recos = [
        (
            "Vider la file d'attente batterie en priorité",
            f"{plural(bq_total, 'scooter')} désactivé{'s' if bq_total > 1 else ''} sous {DISABLE_BATTERY_PCT} % "
            f"de batterie au dernier relevé ({pct(bq_total / last.n_listed)} de la flotte listée). "
            f"Les zones les plus chargées ({names(bq)}) en regroupent {bq_top} : une tournée ciblée de "
            f"changement de batterie y rend des véhicules disponibles plus vite qu'un passage réparti "
            f"sur toute la ville.",
        ),
        reposition,
        (
            "Traiter les désactivations hors batterie",
            f"{len(k['other_idle'])} scooters sont désactivés avec une batterie correcte, dont "
            f"{len(k['other_idle_long'])} depuis au moins {IDLE_HOURS} h. Ce motif pèse "
            f"{pct(avg.n_disabled_other / fleet)} de la flotte en moyenne : c'est une capacité "
            f"immobilisée que les seuls changements de batterie ne récupèrent pas. Une revue de leur "
            f"statut (panne, maintenance, véhicule à récupérer) est à prévoir.",
        ),
    ]

    cmp_rows = ""
    labels = {"nice": "Nice", "barcelona": "Barcelone"}
    for _, r in k["compare"].iterrows():
        cmp_rows += (
            f"<tr><td>{labels.get(r.city, r.city)}</td><td>{fr(r.fleet)}</td><td>{pct(r.pct_available)}</td>"
            f"<td>{pct(r.pct_battery)}</td><td>{pct(r.pct_other)}</td>"
            f"<td>{fr(r.dep_per_vehicle_hour, 3)}</td><td>{fr(r.swaps_per_hour, 1)}</td></tr>"
        )

    tests = k["tests"]
    reco_html = "".join(
        f"<li><b>{html.escape(title)}.</b> {body}</li>" for title, body in recos
    )

    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<title>YEGO Nice – Note d'analyse opérationnelle</title>
<style>
  @page {{ size: A4; margin: 11mm 12mm; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: "Segoe UI", system-ui, sans-serif; color: {INK}; font-size: 8.6pt;
         line-height: 1.38; margin: 0; background: #fff; }}
  h1 {{ font-size: 15pt; margin: 0; letter-spacing: -0.01em; }}
  h2 {{ font-size: 9.4pt; margin: 9px 0 4px; text-transform: uppercase; letter-spacing: 0.04em; color: {INK_2}; }}
  .sub {{ color: {INK_2}; font-size: 8pt; margin-top: 2px; }}
  .tiles {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-top: 9px; }}
  .tile {{ background: {SURFACE}; border: 1px solid rgba(11,11,11,0.10); border-radius: 6px; padding: 6px 8px; }}
  .tile .v {{ font-size: 15pt; font-weight: 600; }}
  .tile .l {{ color: {INK_2}; font-size: 7.4pt; }}
  .grid2 {{ display: grid; grid-template-columns: 1.08fr 1fr; gap: 10px; }}
  .fig {{ background: {SURFACE}; border: 1px solid rgba(11,11,11,0.10); border-radius: 6px; padding: 6px 8px; }}
  .fig .t {{ font-weight: 600; font-size: 8pt; }}
  .fig .n {{ color: {MUTED}; font-size: 6.8pt; }}
  .fig svg {{ width: 100%; height: auto; display: block; }}
  ol {{ margin: 0; padding-left: 16px; }} ol li {{ margin-bottom: 4px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 7.8pt; font-variant-numeric: tabular-nums; }}
  th {{ text-align: left; color: {INK_2}; font-weight: 600; border-bottom: 1px solid {AXIS}; padding: 2px 4px; }}
  td {{ border-bottom: 1px solid {GRID}; padding: 2px 4px; }}
  .method {{ color: {INK_2}; font-size: 7.6pt; }}
  .method b {{ color: {INK}; }}
  .foot {{ margin-top: 6px; color: {MUTED}; font-size: 7pt; display: flex; justify-content: space-between; }}
</style></head>
<body>
  <h1>YEGO Nice — note d'analyse opérationnelle</h1>
  <div class="sub">Flux public GBFS de YEGO · {period} · {w.n_snapshots} relevés toutes les 2 min ·
  premiers constats sur {duration(k['hours_observed'])} de données, collecte toujours en cours</div>

  <div class="tiles">
    <div class="tile"><div class="v">{fr(fleet)}</div><div class="l">scooters listés en moyenne
      (hors véhicules en location)</div></div>
    <div class="tile"><div class="v">{pct(unavailable / fleet)}</div><div class="l">désactivés en moyenne :
      {pct(avg.n_disabled_battery / fleet)} batterie, {pct(avg.n_disabled_other / fleet)} autre motif</div></div>
    <div class="tile"><div class="v">{fr(k['departures_total'])}</div><div class="l">départs observés
      (locations ou retraits terrain)</div></div>
    <div class="tile"><div class="v">{len(k['swaps'])}</div><div class="l">changements de batterie détectés
      sur place</div></div>
  </div>

  <div class="grid2" style="margin-top:8px">
    <div class="fig"><div class="t">État de la flotte listée, relevé par relevé</div>
      {chart_fleet_state(k['snap'])}
      <div class="n">Réservés (~{fr(avg.n_reserved)}) non représentés. Seuil de désactivation déduit des données :
      aucun scooter actif sous {DISABLE_BATTERY_PCT} %.</div></div>
    <div class="fig"><div class="t">Départs observés par heure</div>
      {chart_departures(k['dep_hourly'])}
      <div class="n">Un départ = un scooter qui disparaît du flux. Première et dernière heures partielles.</div></div>
  </div>

  <h2>Trois recommandations</h2>
  <ol>{reco_html}</ol>

  <h2>Nice et Barcelone</h2>
  <table>
    <tr><th>Ville</th><th>Flotte listée</th><th>Disponibles</th><th>Désactivés batterie</th>
        <th>Désactivés autre</th><th>Départs / scooter / h</th><th>Chgts batterie / h</th></tr>
    {cmp_rows}
  </table>

  <h2>Méthode et qualité des données</h2>
  <div class="method">
    <b>Identifiants anonymisés.</b> YEGO régénère le <code>bike_id</code> à chaque requête : aucun identifiant
    commun entre deux relevés, même pour un scooter immobile. J'ai donc reconstitué le suivi de chaque
    véhicule par affectation optimale entre relevés successifs (position à 15 m près, type, batterie) :
    {pct(k['tracking_rate'], 1)} des observations sont rattachées au véhicule du relevé précédent, le reste
    correspondant à des arrivées.
    <b>Pipeline.</b> Collecte Python → Parquet → modèles dbt sur DuckDB (staging, séjours, changements de
    batterie, offre et demande par zone de ~500 m). <b>Tests dbt :</b> {tests['pass']} réussis,
    {tests['warn']} avertissement(s), {tests['fail']} échec(s). Ils ont notamment détecté un scooter de
    Barcelone publié en (0, 0). <b>Limites :</b> une seule nuit et une matinée observées ; un départ inclut
    les retraits par les équipes terrain ; la durée d'immobilisation des véhicules présents au début de
    la collecte est sous-estimée. Couverture : {w.n_snapshots} relevés, {int(w.n_gaps)} interruption(s).
  </div>

  <h2>Ce que j'approfondirais avec les données internes</h2>
  <ol>
    <li><b>Séparer locations et interventions.</b> Croiser les départs observés avec les locations réelles
      pour distinguer la demande des retraits terrain, et calculer un vrai taux d'utilisation par zone.</li>
    <li><b>Mesurer le délai de changement de batterie.</b> Temps entre la désactivation sous {DISABLE_BATTERY_PCT} %
      et la remise en service, par zone et par équipe : c'est l'indicateur qui pilote la disponibilité.</li>
    <li><b>Chiffrer les recommandations.</b> Tester un repositionnement nocturne sur quelques zones et mesurer
      son effet sur les départs du matin, en comparant avec des zones témoins.</li>
  </ol>

  <div class="foot"><span>Code et données : {REPO_URL}</span>
    <span>Candidature Data Analyst – Opérations · VIE246717</span></div>
</body></html>"""


def main() -> None:
    k = build()
    REPORT_DIR.mkdir(exist_ok=True)
    html_path = REPORT_DIR / "note_yego_nice.html"
    pdf_path = REPORT_DIR / "note_yego_nice.pdf"
    html_path.write_text(render(k), encoding="utf-8")
    print(f"HTML : {html_path}")
    if EDGE.exists():
        subprocess.run(
            [str(EDGE), "--headless", "--disable-gpu", "--no-pdf-header-footer",
             f"--print-to-pdf={pdf_path}", html_path.as_uri()],
            check=True, capture_output=True, timeout=120,
        )
        print(f"PDF  : {pdf_path}")
    else:
        print("Edge introuvable : PDF non genere (ouvrir le HTML et imprimer en PDF).")


if __name__ == "__main__":
    main()
