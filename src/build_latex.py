"""
Rapport detaille en anglais, au format LaTeX (un seul fichier, a compiler sur Overleaf).

    python src/build_latex.py   ->   reports/yego_nice_report.tex

Les graphiques sont dessines en pgfplots avec les donnees ecrites dans le .tex : aucune image a
televerser. Les chiffres viennent des memes calculs que la note d'une page (build_report.build).
"""

from __future__ import annotations

import pathlib

import pandas as pd

from build_report import (
    DISABLE_BATTERY_PCT,
    IDLE_HOURS,
    REPO_URL,
    battery_timing_facts,
    build,
    reposition_facts,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "reports" / "yego_nice_report.tex"

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# --- Mise en forme ---------------------------------------------------------


def tex(s: str) -> str:
    """Echappe les caracteres speciaux LaTeX d'un texte venant des donnees (noms de quartiers)."""
    repl = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
            "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\^{}"}
    return "".join(repl.get(c, c) for c in str(s))


def num(x: float, d: int = 0) -> str:
    return f"{x:,.{d}f}"


def pct(x: float, d: int = 0) -> str:
    return f"{100 * x:.{d}f}\\%"


def hour(ts) -> str:
    return f"{ts:%H}h"


def day(ts) -> str:
    return f"{DAYS[ts.weekday()]} {ts.day} {MONTHS[ts.month - 1]}"


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


def names(df: pd.DataFrame) -> str:
    items = [tex(n) for n in dict.fromkeys(df["name"])]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def coords(values) -> str:
    return " ".join(f"({i},{v:.2f})" for i, v in enumerate(values))


def fill(template: str, **values) -> str:
    for key, value in values.items():
        template = template.replace(f"<<{key}>>", str(value))
    assert "<<" not in template, "placeholder non remplace"
    return template


# --- Figures pgfplots ------------------------------------------------------


def figure_fleet(h: pd.DataFrame) -> str:
    labels = ",".join(hour(t) for t in h["hour_local"])
    ymax = (h["avg_available"] + h["avg_disabled_battery"] + h["avg_disabled_other"]).max() * 1.12
    return fill(r"""
\begin{figure}[ht]
  \centering
  \begin{tikzpicture}
    \begin{axis}[
        ybar stacked, bar width=8pt, width=\linewidth, height=5.4cm,
        ymin=0, ymax=<<ymax>>, xmin=-0.6, xmax=<<xmax>>,
        xtick={0,...,<<last>>}, xticklabels={<<labels>>},
        tick label style={font=\scriptsize}, ylabel={Scooters (hourly mean)},
        ylabel style={font=\small}, axis x line*=bottom, axis y line*=left,
        ymajorgrids, grid style={black!10},
        legend style={at={(0.5,-0.2)}, anchor=north, legend columns=3, draw=none, font=\scriptsize},
        legend cell align=left]
      \addplot[fill=yblue, draw=white] coordinates {<<available>>};
      \addplot[fill=yorange, draw=white] coordinates {<<battery>>};
      \addplot[fill=yaqua, draw=white] coordinates {<<other>>};
      \legend{Available, Disabled (battery below <<thr>>\%), Disabled (other reason)}
    \end{axis}
  \end{tikzpicture}
  \caption{Composition of the scooters listed in the Nice feed, hourly mean. Reserved scooters
  (about <<reserved>> on average) are not shown. Rented scooters are not in the feed at all.}
  \label{fig:fleet}
\end{figure}
""", ymax=f"{ymax:.0f}", xmax=f"{len(h) - 0.4:.1f}", last=len(h) - 1, labels=labels,
        available=coords(h["avg_available"]), battery=coords(h["avg_disabled_battery"]),
        other=coords(h["avg_disabled_other"]), thr=DISABLE_BATTERY_PCT,
        reserved=num(h["avg_reserved"].mean()))


def figure_timing(h: pd.DataFrame, peak_idx: int | None) -> str:
    labels = ",".join(hour(t) for t in h["hour_local"])
    y1, y2, y3 = (h[c].max() * 1.2 + 1 for c in ("departures", "avg_disabled_battery", "swaps"))
    marker = lambda ymax: (  # noqa: E731 - ligne verticale au pic de demande
        rf"\draw[densely dashed, black!50] (axis cs:{peak_idx},0) -- (axis cs:{peak_idx},{ymax:.1f});"
        if peak_idx is not None else ""
    )
    return fill(r"""
\begin{figure}[ht]
  \centering
  \begin{tikzpicture}
    \begin{groupplot}[
        group style={group size=1 by 3, vertical sep=0.45cm, xticklabels at=edge bottom},
        width=\linewidth, height=3.5cm, xmin=-0.6, xmax=<<xmax>>,
        xtick={0,...,<<last>>}, xticklabels={<<labels>>}, ymin=0,
        tick label style={font=\scriptsize}, ylabel style={font=\scriptsize, align=center},
        axis x line*=bottom, axis y line*=left, ymajorgrids, grid style={black!10}]
      \nextgroupplot[ybar, bar width=8pt, ymax=<<y1>>, ylabel={Departures\\per hour}]
        \addplot[fill=yblue, draw=none] coordinates {<<departures>>};
        <<m1>>
      \nextgroupplot[ymax=<<y2>>, ylabel={Scooters waiting\\for a battery}]
        \addplot[yorange, thick, mark=*, mark size=1.3pt] coordinates {<<queue>>};
        <<m2>>
      \nextgroupplot[ybar, bar width=8pt, ymax=<<y3>>, ylabel={Battery swaps\\per hour}]
        \addplot[fill=yaqua, draw=none] coordinates {<<swaps>>};
        <<m3>>
    \end{groupplot}
  \end{tikzpicture}
  \caption{Demand, battery queue and battery swaps in Nice, hour by hour. The dashed line marks
  the hour with the most departures. The first and last hours are only partially observed.}
  \label{fig:timing}
\end{figure}
""", xmax=f"{len(h) - 0.4:.1f}", last=len(h) - 1, labels=labels,
        y1=f"{y1:.0f}", y2=f"{y2:.0f}", y3=f"{y3:.0f}",
        departures=coords(h["departures"]), queue=coords(h["avg_disabled_battery"]),
        swaps=coords(h["swaps"]), m1=marker(y1), m2=marker(y2), m3=marker(y3))


# --- Tableaux --------------------------------------------------------------


def zone_table(tension: pd.DataFrame, surplus: pd.DataFrame) -> str:
    rows, seen = [], {}
    for df, label in ((tension, "high demand, low supply"), (surplus, "high supply, low demand")):
        for _, z in df.iterrows():
            seen[z["name"]] = seen.get(z["name"], 0) + 1
            name = tex(z["name"]) + (" (adjacent cell)" if seen[z["name"]] > 1 else "")
            rows.append(f"    {name} & {z['stock']:.1f} & {z['departures']:.0f} & {label} \\\\")
    return fill(r"""
\begin{table}[ht]
  \centering
  \small
  \begin{tabular}{lrrl}
    \toprule
    Zone ($\approx$ 500\,m cell) & Mean available scooters & Departures observed & Diagnosis \\
    \midrule
<<rows>>
    \bottomrule
  \end{tabular}
  \caption{Zones where supply and demand are most out of balance in Nice. Zones are named after
  the neighbourhood returned by OpenStreetMap for the centre of the cell.}
  \label{tab:zones}
\end{table}
""", rows="\n".join(rows))


def compare_table(compare: pd.DataFrame) -> str:
    labels = {"nice": "Nice", "barcelona": "Barcelona"}
    rows = "\n".join(
        f"    {labels.get(r.city, r.city)} & {num(r.fleet)} & {pct(r.pct_available)} & {pct(r.pct_battery)} "
        f"& {pct(r.pct_other)} & {r.dep_per_vehicle_hour:.3f} & {r.swaps_per_hour:.1f} \\\\"
        for r in compare.itertuples()
    )
    return fill(r"""
\begin{table}[ht]
  \centering
  \small
  \begin{tabular}{lrrrrrr}
    \toprule
    City & Listed fleet & Available & \multicolumn{2}{c}{Disabled} & Departures per & Battery swaps \\
    \cmidrule(lr){4-5}
         &              &           & battery & other & scooter per hour & per hour \\
    \midrule
<<rows>>
    \bottomrule
  \end{tabular}
  \caption{Nice and Barcelona over the same period (means over all snapshots).}
  \label{tab:cities}
\end{table}
""", rows=rows)


# --- Document --------------------------------------------------------------


def render(k: dict) -> str:
    w, avg, h = k["window"], k["avg"], k["hourly"].reset_index(drop=True)
    fleet = avg.n_listed
    disabled = avg.n_disabled_battery + avg.n_disabled_other
    f = battery_timing_facts(h)
    rf = reposition_facts(k)
    swaps = k["swaps"]
    n_other, n_other_long = len(k["other_idle"]), len(k["other_idle_long"])
    tests = k["tests"]
    cmp_ = k["compare"].set_index("city")

    peak_idx = int(h.index[h["hour_local"] == f["peak_hour"]][0]) if f else None

    # Pic du matin (s'il a ete observe), pour montrer que la file batterie y est deja vide.
    morning = h.iloc[1:-1]
    morning = morning[morning["hour_local"].dt.hour.between(5, 10)]
    morning_text = ""
    if len(morning) and f:
        m = morning.loc[morning["departures"].idxmax()]
        morning_text = (
            f" The morning peak looks different: at {hour(m['hour_local'])} there were "
            f"{plural(int(m['departures']), 'departure')} while only {num(m['avg_disabled_battery'])} "
            f"scooters were waiting for a battery, because the queue had been cleared during the night."
        )

    other_min = h.loc[h["avg_disabled_other"].idxmin()]
    other_max = h.loc[h["avg_disabled_other"].idxmax()]

    if f:
        timing_abstract = (
            f"(ii) at the evening demand peak ({hour(f['peak_hour'])}), {num(f['queue_at_peak'])} scooters were "
            f"waiting for a battery swap, while {f['in_window']} of the {f['n_swaps']} swaps I detected happened "
            f"between {hour(f['start'])} and {hour(f['end'])}, "
            + ("that is, after the peak; " if f["after_peak"] else "around the peak; ")
        )
        reco1 = (
            r"\item \textbf{Start the battery swap round before the evening peak.} "
            f"At {hour(f['peak_hour'])}, the busiest hour of the period ({plural(f['peak_departures'], 'departure')}), "
            f"{num(f['queue_at_peak'])} scooters ({pct(f['queue_share'])} of the listed fleet) could not be rented "
            f"because of their battery. Most swaps were done between {hour(f['start'])} and {hour(f['end'])}. "
            f"Starting the round about two hours earlier would put these scooters back on the street when "
            f"demand is highest. This should be checked over several evenings before changing the schedule."
        )
    else:
        timing_abstract = "(ii) the battery queue is small and most swaps do not compete with demand peaks; "
        reco1 = (
            r"\item \textbf{Target the battery round by zone.} "
            f"{k['battery_queue_total']} scooters were waiting for a battery at the last snapshot, mostly in "
            f"{names(k['battery_queue'])}."
        )

    if len(k["tension"]):
        reco2 = (
            rf"\item \textbf{{Move about {rf['move_n']} scooters from low-demand to high-demand zones.}} "
            f"{names(k['tension'])} had {rf['tension_departures']} departures for only "
            f"{rf['tension_stock']:.1f} available scooters on average, while {names(k['surplus'])} kept "
            f"{rf['surplus_stock']:.1f} scooters for {plural(rf['surplus_departures'], 'departure')} "
            r"(Table~\ref{tab:zones}). Night-time, when demand is lowest, is the natural moment for this. "
            "The exact number should be calibrated on several weeks of data."
        )
    else:
        reco2 = (
            r"\item \textbf{Monitor the zones with too many scooters.} "
            f"{names(k['surplus'])} kept {rf['surplus_stock']:.1f} scooters for "
            f"{plural(rf['surplus_departures'], 'departure')}."
        )

    long_text = (f", and {n_other_long} of them did not move for at least {IDLE_HOURS} hours"
                 if n_other_long else "")
    reco3 = (
        r"\item \textbf{Review the scooters disabled for reasons other than battery.} "
        f"At the last snapshot, {plural(n_other, 'scooter')} were disabled with a correct battery{long_text}. "
        f"This group is {pct(avg.n_disabled_other / fleet)} of the fleet on average and it is not reduced by "
        "battery swaps. Checking why they are disabled (breakdown, maintenance, vehicle to collect) could "
        "free part of this capacity."
    )

    swap_detail = (
        f"I detected {plural(len(swaps), 'battery swap')} in Nice. In {int(swaps['previous_is_disabled'].sum())} "
        f"of them the scooter was disabled just before, and the battery went from "
        f"{swaps['previous_battery_pct'].mean():.0f}\\% to {swaps['battery_pct'].mean():.0f}\\% on average."
        if len(swaps) else "I did not detect any battery swap in Nice over the period."
    )
    timing_detail = (
        f"Figure~\\ref{{fig:timing}} puts demand and battery operations on the same time axis. The busiest "
        f"hour was {hour(f['peak_hour'])} with {plural(f['peak_departures'], 'departure')}. At that moment "
        f"{num(f['queue_at_peak'])} scooters were disabled because of their battery. Swaps were concentrated "
        f"between {hour(f['start'])} and {hour(f['end'])} ({f['in_window']} of {f['n_swaps']}), and the queue only "
        f"reached its minimum at {hour(f['cleared'])}. In other words, the swap round worked well, but it "
        f"started {'after' if f['after_peak'] else 'around'} the moment when the scooters were most needed."
        + morning_text
        if f else "The battery queue stayed small over the period, so its timing does not seem to be an issue."
    )

    barcelona = (
        f" The same {DISABLE_BATTERY_PCT}\\% rule holds in Barcelona, where the fleet is about "
        f"{cmp_.loc['barcelona', 'fleet'] / cmp_.loc['nice', 'fleet']:.0f} times larger."
        if "barcelona" in cmp_.index and "nice" in cmp_.index else ""
    )

    start, end = w.start_at, w.end_at
    return fill(PREAMBLE + BODY,
                start=f"{day(start)} at {start:%H:%M}", end=f"{day(end)} at {end:%H:%M}",
                date=f"{end.day} {MONTHS[end.month - 1]} {end.year}",
                n_snapshots=int(w.n_snapshots), hours=f"{k['hours_observed']:.0f}",
                gaps_text="no interruption" if int(w.n_gaps) == 0 else plural(int(w.n_gaps), "interruption"),
                fleet=num(fleet), available=pct(avg.n_available / fleet), disabled=pct(disabled / fleet, 1),
                disabled_battery=pct(avg.n_disabled_battery / fleet, 1),
                disabled_other=pct(avg.n_disabled_other / fleet, 1), thr=DISABLE_BATTERY_PCT,
                departures=k["departures_total"], tracking=pct(k["tracking_rate"], 1),
                other_min=num(other_min["avg_disabled_other"]), other_max=num(other_max["avg_disabled_other"]),
                other_max_hour=hour(other_max["hour_local"]),
                n_other=n_other, n_other_long=n_other_long, idle_hours=IDLE_HOURS,
                timing_abstract=timing_abstract, swap_detail=swap_detail, timing_detail=timing_detail,
                barcelona=barcelona, reco1=reco1, reco2=reco2, reco3=reco3,
                fig_fleet=figure_fleet(h), fig_timing=figure_timing(h, peak_idx),
                table_zones=zone_table(k["tension"], k["surplus"]), table_cities=compare_table(k["compare"]),
                tests_pass=tests["pass"], tests_warn=tests["warn"], tests_fail=tests["fail"],
                repo=REPO_URL)


PREAMBLE = r"""\documentclass[11pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage[margin=2.3cm]{geometry}
\usepackage{amsmath}
\usepackage{booktabs}
\usepackage{xcolor}
\usepackage{pgfplots}
\usepgfplotslibrary{groupplots}
\pgfplotsset{compat=1.18}
\usepackage[font=small,labelfont=bf]{caption}
\usepackage[hidelinks]{hyperref}

\definecolor{yblue}{HTML}{2A78D6}
\definecolor{yorange}{HTML}{EB6834}
\definecolor{yaqua}{HTML}{1BAF7A}

% Replace with your full name.
\newcommand{\myname}{Marius}

\title{Monitoring the YEGO scooter fleet in Nice\\with public GBFS data}
\author{\myname\\[2pt]\small Application for the Data Analyst -- Operations position (V.I.E.\ 246717)}
\date{<<date>>}
"""

BODY = r"""
\begin{document}
\maketitle

\begin{abstract}
YEGO publishes the position and battery level of its shared electric scooters in real time through
the General Bikeshare Feed Specification (GBFS). I collected this feed every two minutes for Nice and
Barcelona from <<start>> to <<end>> (<<n_snapshots>> snapshots for Nice), rebuilt the movements of
each scooter even though the feed anonymises vehicle identifiers, and computed operational indicators
with a dbt pipeline. Three findings stand out for Nice: (i) YEGO disables every scooter below
<<thr>>\% battery; <<timing_abstract>>(iii) about <<disabled_other>> of the fleet is disabled for
reasons other than battery. I finish with three recommendations and with the limits of a study based
on a single evening and night.
\end{abstract}

\section{Introduction}

The job offer describes an analyst who helps the Operations team understand vehicle availability,
battery swaps, repositioning and data quality. Before applying, I wanted to see how much of this can
already be measured from the outside, using only the public data that YEGO publishes. I focused on
three questions:
\begin{enumerate}
  \item How available is the fleet, and why are some scooters not available?
  \item When are batteries swapped compared to when people want to ride?
  \item Where is the supply of scooters not aligned with the demand?
\end{enumerate}
The code, the dbt models and the collected data are available at \url{https://<<repo>>}.

\section{Data}

The GBFS feed \cite{gbfs} gives, for every scooter that is parked and not rented, its position,
battery level (in percent and in remaining range), type, and two flags: \texttt{is\_reserved} and
\texttt{is\_disabled}. A scooter that is being ridden is not listed. I wrote a small Python collector
that downloads the feed every two minutes for Nice and for Barcelona (YEGO's home city) and stores
each snapshot as a Parquet file. Over the <<hours>> hours studied here the collection had
<<gaps_text>>. In practice the feed itself refreshes the positions about every four
minutes, so this is the real time resolution of the study. Both cities only contain electric mopeds.

\section{Method}

\subsection{The identifier problem}

The first surprise was that the \texttt{bike\_id} field is regenerated at every request. Comparing
two snapshots taken four minutes apart, no identifier was shared, although 113 scooters were at
exactly the same coordinates. This is a privacy measure allowed by GBFS, but it means that a scooter
cannot be followed through its identifier, which is needed for durations, departures and battery
swaps.

\subsection{Rebuilding vehicle tracks}

I rebuilt a stable identifier by matching the scooters of two consecutive snapshots. A pair
$(i,j)$ is a candidate if both scooters have the same type and are less than 15\,m apart. Its cost is
\begin{equation}
  c_{ij} = d_{ij} + \lambda\,\lvert b_i - b_j \rvert, \qquad \lambda = 0.5\ \text{m per battery point},
\end{equation}
where $d_{ij}$ is the distance in metres and $b$ the battery level. I then choose the one-to-one
matching with the lowest total cost, using the Hungarian algorithm \cite{kuhn1955}. To keep it fast
on the 1{,}700 scooters of Barcelona, the problem is solved separately for each group of scooters
that are close to each other. A second pass accepts jumps of up to 150\,m when the battery is
almost unchanged (at most 2 points), which handles GPS noise.

A simple nearest-neighbour rule was my first attempt, but it failed when several scooters are
parked side by side: GPS noise swaps the neighbours and about 10\% of the tracks were broken. With
the assignment approach, <<tracking>> of the observations are linked to a scooter of the previous
snapshot; the rest are new arrivals.

\subsection{Events and zones}

From the tracks I derive three events. A \emph{departure} is a scooter that disappears from the
feed (it was rented, or picked up by the staff). An \emph{arrival} is a scooter that appears. A
\emph{battery swap} is a rise of at least 20 battery points on the same scooter; I only keep it if
the scooter was disabled just before or did not move more than 5\,m. To study zones, the city is
divided into cells of about 500\,m, named with OpenStreetMap \cite{nominatim}.

\subsection{Pipeline and data quality}

The data flows from the Parquet files into dbt models running on DuckDB \cite{duckdb}: two staging
models and four marts (fleet state per hour, vehicle stays, battery swaps, supply and demand per
zone). The pipeline has data tests on null values, accepted values, coordinates inside the service
area, gaps in the collection and the battery rule described below. In the last run,
<<tests_pass>> tests passed, <<tests_warn>> gave a warning and <<tests_fail>> failed. The warning
is a real finding: one Barcelona scooter is published at latitude 0 and longitude 0 in every
snapshot. It is excluded from the indicators but still reported.

\section{Results}

\subsection{Fleet availability}

On average <<fleet>> scooters were listed in Nice, of which <<available>> were available
(Figure~\ref{fig:fleet}). <<disabled>> were disabled: <<disabled_battery>> because of their
battery and <<disabled_other>> for another reason. No enabled scooter ever had a battery below
<<thr>>\%, which shows that YEGO automatically disables scooters under this threshold.<<barcelona>>
The ``other reason'' group behaves differently: it has a stable base of about <<other_min>>
scooters, and it rises to <<other_max>> around <<other_max_hour>>, which may correspond to scooters
being handled during the evening operations.

<<fig_fleet>>

\subsection{Battery swaps and demand}

<<swap_detail>> <<timing_detail>>

<<fig_timing>>

\subsection{Supply and demand by zone}

Table~\ref{tab:zones} compares the mean number of available scooters with the departures observed
in each zone. Some central zones have many departures and few scooters, while others keep many
scooters that are almost never rented.

<<table_zones>>

\subsection{Comparison with Barcelona}

Table~\ref{tab:cities} shows that the two cities have very similar shares of available and disabled
scooters, even though the fleets have very different sizes.

<<table_cities>>

\section{Recommendations}

\begin{enumerate}
  <<reco1>>
  <<reco2>>
  <<reco3>>
\end{enumerate}

\section{Limitations}

\begin{itemize}
  \item The study covers one evening and one night. The patterns described here must be confirmed
        over several weeks before taking decisions; the collector is still running for this reason.
  \item A departure can be a rental or a pick-up by the staff, which the public feed does not
        distinguish.
  \item Rides shorter than the refresh period of the feed (about four minutes) are not visible.
  \item For scooters already parked when the collection started, parking durations are
        underestimated.
  \item The track rebuilding can still make mistakes in very dense parking spots.
\end{itemize}

\section{What I would do next with internal data}

\begin{enumerate}
  \item \textbf{Separate rentals from operations.} Joining the observed departures with the real
        rentals would give the true demand and a utilisation rate per zone.
  \item \textbf{Measure the battery swap delay.} The time between the moment a scooter is disabled
        under <<thr>>\% and the moment it is back in service, per zone and per team, is the indicator
        that drives availability.
  \item \textbf{Test the recommendations.} For example, move scooters at night in a few zones only,
        and compare their morning departures with similar zones where nothing was changed.
\end{enumerate}

\begin{thebibliography}{9}
\bibitem{gbfs} MobilityData. \emph{General Bikeshare Feed Specification (GBFS)}, version 2.3.
  \url{https://github.com/MobilityData/gbfs}.
\bibitem{kuhn1955} H.~W. Kuhn. The Hungarian method for the assignment problem.
  \emph{Naval Research Logistics Quarterly}, 2(1--2):83--97, 1955.
\bibitem{duckdb} M.~Raasveldt and H.~M\"uhleisen. DuckDB: an embeddable analytical database.
  In \emph{Proceedings of the 2019 International Conference on Management of Data (SIGMOD)}, 2019.
\bibitem{nominatim} OpenStreetMap contributors. \emph{Nominatim}, reverse geocoding service.
  \url{https://nominatim.org}.
\end{thebibliography}

\end{document}
"""


def main() -> None:
    k = build()
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(render(k), encoding="utf-8")
    print(f"LaTeX : {OUT}")


if __name__ == "__main__":
    main()
