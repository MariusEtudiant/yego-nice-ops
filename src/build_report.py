"""
Note d'analyse operationnelle (1 page A4) a partir des marts dbt.

    python src/build_report.py

Sorties : reports/note_yego_nice.html et reports/note_yego_nice.pdf (impression via Edge headless).
Les chiffres viennent de src/analysis.py, comme ceux du rapport en anglais.
"""

from __future__ import annotations

import html
import io
import pathlib
import subprocess

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from analysis import CITY, DISABLE_BATTERY_PCT, IDLE_HOURS, MIDDAY_HOURS, REPO_URL, build  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "reports"
EDGE = pathlib.Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

# Palette (categorielle, ordre fixe) et encre, fond clair.
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
SURFACE, INK, INK_2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]


# --- Graphiques ------------------------------------------------------------


def style_axes(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=7, length=0)
    ax.yaxis.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.set_xticks(range(0, 24, 3), [f"{h}h" for h in range(0, 24, 3)])
    ax.set_xlim(-0.6, 23.6)


def to_svg(fig) -> str:
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    svg = buf.getvalue()
    return svg[svg.index("<svg"):]


def chart_fleet_state(p: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(3.7, 1.9), dpi=100)
    fig.patch.set_facecolor(SURFACE)
    style_axes(ax)
    bottom = pd.Series(0.0, index=p.index)
    for col, label, color in (("available", "Disponibles", BLUE),
                              ("battery", f"Désactivés : batterie < {DISABLE_BATTERY_PCT} %", ORANGE),
                              ("other", "Désactivés : autre motif", AQUA)):
        ax.bar(p["hour"], p[col], bottom=bottom, color=color, width=0.78, edgecolor=SURFACE,
               linewidth=0.6, label=label)
        bottom += p[col]
    ax.set_ylim(0, bottom.max() * 1.08)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=3, frameon=False,
              fontsize=6.5, labelcolor=INK_2, handlelength=1, columnspacing=1)
    return to_svg(fig)


def chart_timing(p: pd.DataFrame) -> str:
    """Departs et changements de batterie par heure : deux petits graphiques empiles, un seul axe chacun."""
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(3.4, 2.1), dpi=100, sharex=True,
                                 gridspec_kw={"height_ratios": [1.3, 1], "hspace": 0.45})
    fig.patch.set_facecolor(SURFACE)
    peak = int(p.loc[p["departures"].idxmax(), "hour"])
    for ax, col, color, title in ((a1, "departures", BLUE, "Départs par heure"),
                                  (a2, "swaps", AQUA, "Changements de batterie par heure")):
        style_axes(ax)
        ax.bar(p["hour"], p[col], color=color, width=0.72, edgecolor=SURFACE, linewidth=0.6)
        ax.axvline(peak, color=MUTED, linestyle="--", linewidth=0.8)
        ax.set_title(title, fontsize=7, color=INK_2, loc="left", pad=2)
    return to_svg(fig)


# --- Rendu -----------------------------------------------------------------


def fr(x: float, d: int = 0) -> str:
    return f"{x:,.{d}f}".replace(",", " ").replace(".", ",")


def pct(x: float, d: int = 0) -> str:
    return f"{fr(100 * x, d)} %"


def names(df: pd.DataFrame) -> str:
    """Liste des zones ; celles d'une meme commune sont regroupees : "A, B et C (Cagnes-sur-Mer)"."""
    parts = [n.rsplit(" (", 1) for n in dict.fromkeys(df["name"])]
    towns = {p[1].rstrip(")") for p in parts if len(p) == 2}
    grouped = len(parts) > 1 and len(towns) == 1 and all(len(p) == 2 for p in parts)
    items = [html.escape(p[0] if grouped else " (".join(p)) for p in parts]
    joined = items[0] if len(items) == 1 else ", ".join(items[:-1]) + " et " + items[-1]
    return f"{joined} ({html.escape(towns.pop())})" if grouped else joined


def render(k: dict) -> str:
    w, p, ev, cmp_ = k["window"], k["profile"], k["evenings"], k["compare"].set_index("city")
    bcn = cmp_.loc["barcelona"] if "barcelona" in cmp_.index else None
    first, last = pd.Timestamp(k["days"][0]), pd.Timestamp(k["days"][-1])
    peaks = " ou ".join(f"{h}h" for h in sorted(set(ev["peak_hour"])))
    n_majority = int((ev["share_after_peak"] > 0.5).sum())
    t, s = k["tension"], k["surplus"]
    move_n = int(max(1, min(s["stock"].sum() - len(s), t["dep"].sum() - t["stock"].sum())))
    oa = k["out_of_area"].sort_values("city", ascending=False)
    oa_text = " ; ".join(f"un scooter de {'Nice' if r.city == 'nice' else 'Barcelone'} désactivé "
                         f"{fr(r.days)} jours à {html.escape(r.place)}" for r in oa.itertuples())
    tests = k["tests"]

    recos = [
        ("Avancer une partie de la tournée batterie en début d'après-midi",
         f"Le pic de demande tombe chaque soir à {peaks}, avec en moyenne {fr(ev['queue_at_peak'].mean())} "
         f"scooters bloqués faute de batterie. {n_majority} soirs sur {len(ev)}, la majorité des changements "
         f"arrive après ce pic. Un scooter désactivé entre {MIDDAY_HOURS[0]}h et {MIDDAY_HOURS[1] + 1}h attend "
         f"{fr(k['wait_midday'], 1)} h (médiane) la tournée du soir : le traiter entre 12h et 16h le remettrait "
         f"en circulation pour le pic."),
        (f"Repositionner environ {move_n} scooters chaque nuit",
         f"{names(t)} génèrent {fr(t['dep'].sum())} départs par jour pour {fr(t['stock'].sum(), 1)} scooters "
         f"disponibles, et figurent dans le top 10 des zones en tension au moins {int(t['days_top10'].min())} "
         f"jours sur {k['n_zone_days']} : le déséquilibre est structurel. À l'inverse, {names(s)} gardent "
         f"{fr(s['stock'].sum(), 1)} scooters pour {fr(s['dep'].sum(), 1)} départs par jour."),
        ("Passer en revue chaque jour les scooters désactivés hors batterie",
         f"Au dernier relevé, {k['other_now']} scooters sont désactivés avec une batterie correcte, dont "
         f"{k['other_now_long']} depuis plus de {IDLE_HOURS} h et {k['other_now_3d']} depuis plus de trois "
         f"jours. Les tests ont aussi repéré {oa_text}, loin de la zone de service."),
    ]
    reco_html = "".join(f"<li><b>{html.escape(a)}.</b> {b}</li>" for a, b in recos)

    cmp_rows = ""
    for city, label in ((CITY, "Nice"), ("barcelona", "Barcelone")):
        if city in cmp_.index:
            r = cmp_.loc[city]
            cmp_rows += (f"<tr><td>{label}</td><td>{fr(r.fleet)}</td><td>{pct(r.pct_available)}</td>"
                         f"<td>{pct(r.pct_battery, 1)}</td><td>{pct(r.pct_other, 1)}</td>"
                         f"<td>{fr(r.dep_per_scooter_day, 1)}</td><td>{fr(r['median'], 1)} h</td></tr>")

    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<title>YEGO Nice – Note d'analyse opérationnelle</title>
<style>
  @page {{ size: A4; margin: 11mm 12mm; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: "Segoe UI", system-ui, sans-serif; color: {INK}; font-size: 8.5pt;
         line-height: 1.36; margin: 0; background: #fff; }}
  h1 {{ font-size: 15pt; margin: 0; letter-spacing: -0.01em; }}
  h2 {{ font-size: 9.2pt; margin: 8px 0 4px; text-transform: uppercase; letter-spacing: 0.04em; color: {INK_2}; }}
  .sub {{ color: {INK_2}; font-size: 8pt; margin-top: 2px; }}
  .tiles {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-top: 8px; }}
  .tile {{ background: {SURFACE}; border: 1px solid rgba(11,11,11,0.10); border-radius: 6px; padding: 6px 8px; }}
  .tile .v {{ font-size: 15pt; font-weight: 600; }}
  .tile .l {{ color: {INK_2}; font-size: 7.3pt; }}
  .grid2 {{ display: grid; grid-template-columns: 1.08fr 1fr; gap: 10px; }}
  .fig {{ background: {SURFACE}; border: 1px solid rgba(11,11,11,0.10); border-radius: 6px; padding: 6px 8px; }}
  .fig .t {{ font-weight: 600; font-size: 8pt; }}
  .fig .n {{ color: {MUTED}; font-size: 6.8pt; }}
  .fig svg {{ width: 100%; height: auto; display: block; }}
  ol {{ margin: 0; padding-left: 16px; }} ol li {{ margin-bottom: 4px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 7.8pt; font-variant-numeric: tabular-nums; }}
  th {{ text-align: left; color: {INK_2}; font-weight: 600; border-bottom: 1px solid {AXIS}; padding: 2px 4px; }}
  td {{ border-bottom: 1px solid {GRID}; padding: 2px 4px; }}
  .method {{ color: {INK_2}; font-size: 7.5pt; }}
  .method b {{ color: {INK}; }}
  .foot {{ margin-top: 6px; color: {MUTED}; font-size: 7pt; display: flex; justify-content: space-between; }}
</style></head>
<body>
  <h1>YEGO Nice — note d'analyse opérationnelle</h1>
  <div class="sub">Flux public GBFS de YEGO · du {w.start_at:%d/%m %Hh%M} au {w.end_at:%d/%m %Hh%M} ·
  {fr(w.n_snapshots)} relevés toutes les 2 min · moyennes sur {k['n_days']} jours complets
  (du {first:%d/%m} au {last:%d/%m}) · collecte toujours en cours</div>

  <div class="tiles">
    <div class="tile"><div class="v">{pct(k['pct_battery'] + k['pct_other'], 1)}</div><div class="l">de la
      flotte désactivée en moyenne : {pct(k['pct_battery'], 1)} batterie, {pct(k['pct_other'], 1)} autre motif</div></div>
    <div class="tile"><div class="v">{fr(k['wait']['median'], 1)} h</div><div class="l">d'attente médiane avant
      changement de batterie{f" (Barcelone : {fr(bcn['median'], 1)} h)" if bcn is not None else ""}</div></div>
    <div class="tile"><div class="v">{pct(ev['share_after_peak'].mean())}</div><div class="l">des changements
      de batterie faits après le pic du soir, en moyenne sur {len(ev)} soirs</div></div>
    <div class="tile"><div class="v">{fr(k['departures_per_day'])}</div><div class="l">départs par jour
      ({fr(k['swaps_per_day'])} changements de batterie)</div></div>
  </div>

  <div class="grid2" style="margin-top:8px">
    <div class="fig"><div class="t">Journée type : état de la flotte listée</div>
      {chart_fleet_state(p)}
      <div class="n">Moyenne par heure sur {k['n_days']} jours complets. Aucun scooter actif sous
      {DISABLE_BATTERY_PCT} % : YEGO les désactive.</div></div>
    <div class="fig"><div class="t">Journée type : demande et changements de batterie</div>
      {chart_timing(p)}
      <div class="n">Pointillés : heure la plus chargée. Les changements se concentrent après le pic.</div></div>
  </div>

  <h2>Trois recommandations</h2>
  <ol>{reco_html}</ol>

  <h2>Nice et Barcelone</h2>
  <table>
    <tr><th>Ville</th><th>Flotte listée</th><th>Disponibles</th><th>Désactivés batterie</th>
        <th>Désactivés autre</th><th>Départs / scooter / jour</th><th>Attente batterie (médiane)</th></tr>
    {cmp_rows}
  </table>

  <h2>Méthode et qualité des données</h2>
  <div class="method">
    <b>Identifiants anonymisés.</b> YEGO régénère le <code>bike_id</code> à chaque requête. J'ai reconstitué
    le suivi de chaque scooter par affectation optimale entre relevés successifs (position à 15 m près, type,
    batterie) : {pct(k['tracking_rate'], 1)} des observations sont rattachées au scooter du relevé précédent.
    <b>Pipeline.</b> Collecte Python (GitHub Actions toutes les heures) → Parquet → modèles dbt sur DuckDB
    → note, rapport, modèle Power BI et API. <b>Tests dbt :</b> {tests['pass']} réussis,
    {tests['warn']} avertissement(s), {tests['fail']} échec(s) ; ils signalent notamment des batteries
    publiées à 101 % et des scooters hors zone. <b>Limites :</b> deux semaines d'octobre, sans météo ; un
    départ inclut les retraits par les équipes terrain ; une interruption de collecte de {fr(w.max_gap_h)} h
    (12–13/10), exclue des moyennes.
  </div>

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
