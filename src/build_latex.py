"""
Rapport en anglais au format LaTeX (un seul fichier, a compiler sur Overleaf ou avec pdflatex).

    python src/build_latex.py   ->   reports/yego_nice_report.tex

Les graphiques sont dessines en pgfplots avec les donnees ecrites dans le .tex : aucune image a
televerser. Les chiffres viennent de src/analysis.py, comme ceux de la note en francais.
"""

from __future__ import annotations

import pathlib

import pandas as pd

from analysis import CITY, DISABLE_BATTERY_PCT, IDLE_HOURS, LATE_HOURS, MIDDAY_HOURS, REPO_URL, build

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "reports" / "yego_nice_report.tex"

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# --- Mise en forme ---------------------------------------------------------


def tex(s: str) -> str:
    """Echappe les caracteres speciaux LaTeX d'un texte venant des donnees (noms de lieux)."""
    repl = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
            "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\^{}"}
    return "".join(repl.get(c, c) for c in str(s))


def num(x: float, d: int = 0) -> str:
    return f"{x:,.{d}f}"


def pct(x: float, d: int = 0) -> str:
    return f"{100 * x:.{d}f}\\%"


def day(ts) -> str:
    return f"{DAYS[ts.weekday()]} {ts.day} {MONTHS[ts.month - 1]}"


def short_day(ts) -> str:
    return f"{DAYS[ts.weekday()][:3]} {ts.day}/{ts.month}"


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


def names(df: pd.DataFrame) -> str:
    items = [tex(n) for n in dict.fromkeys(df["name"])]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def names_by_town(df: pd.DataFrame) -> str:
    """Comme names(), mais regroupe les zones d'une meme commune : "A, B and C (all in Town)"."""
    parts = [n.rsplit(" (", 1) for n in dict.fromkeys(df["name"])]
    towns = {p[1].rstrip(")") for p in parts if len(p) == 2}
    if len(towns) == 1 and all(len(p) == 2 for p in parts):
        inner = [tex(p[0]) for p in parts]
        joined = inner[0] if len(inner) == 1 else ", ".join(inner[:-1]) + " and " + inner[-1]
        return f"{joined} (all in {tex(towns.pop())})"
    return names(df)


def coords(values) -> str:
    return " ".join(f"({i},{v:.2f})" for i, v in enumerate(values))


def fill(template: str, **values) -> str:
    for key, value in values.items():
        template = template.replace(f"<<{key}>>", str(value))
    assert "<<" not in template, "placeholder non remplace"
    return template


HOUR_LABELS = ",".join(f"{h:02d}h" if h % 3 == 0 else "" for h in range(24))


# --- Figures pgfplots ------------------------------------------------------


def figure_fleet(p: pd.DataFrame, n_days: int) -> str:
    ymax = (p["available"] + p["battery"] + p["other"]).max() * 1.12
    return fill(r"""
\begin{figure}[ht]
  \centering
  \begin{tikzpicture}
    \begin{axis}[
        ybar stacked, bar width=7pt, width=\linewidth, height=4.3cm,
        ymin=0, ymax=<<ymax>>, xmin=-0.6, xmax=23.6,
        xtick={0,...,23}, xticklabels={<<labels>>},
        tick label style={font=\scriptsize}, ylabel={Scooters},
        ylabel style={font=\small}, axis x line*=bottom, axis y line*=left,
        ymajorgrids, grid style={black!10},
        legend style={at={(0.5,-0.22)}, anchor=north, legend columns=3, draw=none, font=\scriptsize},
        legend cell align=left]
      \addplot[fill=yblue, draw=white] coordinates {<<available>>};
      \addplot[fill=yorange, draw=white] coordinates {<<battery>>};
      \addplot[fill=yaqua, draw=white] coordinates {<<other>>};
      \legend{Available, Disabled (battery below <<thr>>\%), Disabled (other reason)}
    \end{axis}
  \end{tikzpicture}
  \caption{Scooters listed in the Nice feed by hour of the day, mean over <<n_days>> complete days.
  Reserved scooters are not shown; rented scooters are not in the feed.}
  \label{fig:fleet}
\end{figure}
""", ymax=f"{ymax:.0f}", labels=HOUR_LABELS, available=coords(p["available"]),
        battery=coords(p["battery"]), other=coords(p["other"]), thr=DISABLE_BATTERY_PCT, n_days=n_days)


def figure_timing(p: pd.DataFrame, n_days: int) -> str:
    peak = int(p.loc[p["departures"].idxmax(), "hour"])
    y1, y2, y3 = (p["departures"].max() * 1.2, p["battery"].max() * 1.25, p["swaps"].max() * 1.3)

    def marker(ymax: float) -> str:
        return rf"\draw[densely dashed, black!50] (axis cs:{peak},0) -- (axis cs:{peak},{ymax:.1f});"

    return fill(r"""
\begin{figure}[ht]
  \centering
  \begin{tikzpicture}
    \begin{groupplot}[
        group style={group size=1 by 3, vertical sep=0.7cm, xticklabels at=edge bottom},
        title style={font=\scriptsize, at={(0,1)}, anchor=south west, inner sep=1pt},
        width=\linewidth, height=2.8cm, xmin=-0.6, xmax=23.6,
        xtick={0,...,23}, xticklabels={<<labels>>}, ymin=0,
        tick label style={font=\scriptsize},
        axis x line*=bottom, axis y line*=left, ymajorgrids, grid style={black!10}]
      \nextgroupplot[ybar, bar width=6pt, ymax=<<y1>>, title={Departures per hour}]
        \addplot[fill=yblue, draw=none] coordinates {<<departures>>};
        <<m1>>
      \nextgroupplot[ymax=<<y2>>, title={Scooters waiting for a battery}]
        \addplot[yorange, thick, mark=*, mark size=1.2pt] coordinates {<<queue>>};
        <<m2>>
      \nextgroupplot[ybar, bar width=6pt, ymax=<<y3>>, title={Battery swaps per hour}]
        \addplot[fill=yaqua, draw=none] coordinates {<<swaps>>};
        <<m3>>
    \end{groupplot}
  \end{tikzpicture}
  \caption{Demand, battery queue and battery swaps in Nice by hour of the day, mean over
  <<n_days>> complete days. The dashed line marks the busiest hour.}
  \label{fig:timing}
\end{figure}
""", labels=HOUR_LABELS, y1=f"{y1:.0f}", y2=f"{y2:.0f}", y3=f"{y3:.1f}",
        departures=coords(p["departures"]), queue=coords(p["battery"]), swaps=coords(p["swaps"]),
        m1=marker(y1), m2=marker(y2), m3=marker(y3), n_days=n_days)


# --- Tableaux --------------------------------------------------------------


def evenings_table(ev: pd.DataFrame) -> str:
    rows = "\n".join(
        f"    {short_day(r.evening)} & {r.peak_hour}h & {r.peak_departures} & {r.queue_at_peak:.0f} & "
        f"{r.swaps} & {100 * r.share_after_peak:.0f}\\% \\\\"
        for r in ev.itertuples()
    )
    return fill(r"""
\begin{table}[ht]
  \centering
  \small
  \begin{tabular}{lrrrrr}
    \toprule
    Evening & Busiest hour & Departures & Waiting for & Battery swaps & Swaps done \\
            & (16h--22h)   & that hour  & a battery   & (until 10h)   & after the peak \\
    \midrule
<<rows>>
    \bottomrule
  \end{tabular}
  \caption{Evening by evening in Nice: the busiest hour, the scooters waiting for a battery at
  that hour, and the share of the following battery swaps that came after it.}
  \label{tab:evenings}
\end{table}
""", rows=rows)


def zone_table(tension: pd.DataFrame, surplus: pd.DataFrame, n_days: int) -> str:
    rows = []
    for df, label in ((tension, "High demand, low supply"), (surplus, "High supply, low demand")):
        rows.append(rf"    \multicolumn{{4}}{{l}}{{\emph{{{label}}}}} \\")
        for _, z in df.iterrows():
            top = f"{int(z['days_top10'])}/{n_days}" if label.startswith("High demand") else "--"
            rows.append(rf"    \quad {tex(z['name'])} & {z['stock']:.1f} & {z['dep']:.1f} & {top} \\")
    return fill(r"""
\begin{table}[ht]
  \centering
  \small
  \begin{tabular}{lrrc}
    \toprule
    Zone ($\approx$ 500\,m cell) & Available scooters & Departures & Days in top 10 \\
                                 & (mean)             & per day    & of tension     \\
    \midrule
<<rows>>
    \bottomrule
  \end{tabular}
  \caption{Zones of the Nice service area where supply and demand are most out of balance, mean
  per complete day. Names come from OpenStreetMap.}
  \label{tab:zones}
\end{table}
""", rows="\n".join(rows))


# --- Document --------------------------------------------------------------


def render(k: dict) -> str:
    w, p, ev, cmp_ = k["window"], k["profile"], k["evenings"], k["compare"].set_index("city")
    n_days = k["n_days"]
    first_day, last_day = k["days"][0], k["days"][-1]
    nice, bcn = cmp_.loc[CITY], cmp_.loc["barcelona"] if "barcelona" in cmp_.index else None
    peak_hours = sorted(set(ev["peak_hour"]))
    peak_text = " or ".join(f"{h}h" for h in peak_hours)
    t, s = k["tension"], k["surplus"]
    move_n = int(max(1, min(s["stock"].sum() - len(s), t["dep"].sum() - t["stock"].sum())))
    oa = k["out_of_area"]
    oa = oa.sort_values("city", ascending=False)   # Nice d'abord
    oa_text = "; ".join(
        f"one {'Nice' if r.city == 'nice' else 'Barcelona'} scooter stayed disabled for "
        f"{r.days:.0f} days in {tex(r.place)}" for r in oa.itertuples())
    qual = k["quality"]
    bcn_wait = (f"In Barcelona the median is only {bcn['median']:.1f}\\,h"
                f" (a quarter wait more than {bcn['p75']:.1f}\\,h)." if bcn is not None else "")

    return fill(PREAMBLE + BODY,
                date=f"{w.end_at.day} {MONTHS[w.end_at.month - 1]} {w.end_at.year}", repo=REPO_URL,
                start=f"{day(w.start_at)} at {w.start_at:%H:%M}", end=f"{day(w.end_at)} at {w.end_at:%H:%M}",
                n_snapshots=num(w.n_snapshots), n_days=n_days,
                full_from=day(pd.Timestamp(first_day)), full_to=day(pd.Timestamp(last_day)),
                gap_h=f"{w.max_gap_h:.0f}", thr=DISABLE_BATTERY_PCT,
                tracking=pct(k["tracking_rate"], 1),
                warn_text=(r" The warnings are real findings, described in Section~\ref{sec:quality}."
                           if k["tests"]["warn"] else ""),
                tests_pass=k["tests"]["pass"], tests_warn=k["tests"]["warn"], tests_fail=k["tests"]["fail"],
                fleet=num(k["fleet"]), available=pct(k["pct_available"]),
                battery=pct(k["pct_battery"], 1), other=pct(k["pct_other"], 1),
                q_min=num(k["battery_queue_min"]), q_max=num(k["battery_queue_max"]),
                dep_day=num(k["departures_per_day"]), dep_scooter=f"{nice['dep_per_scooter_day']:.1f}",
                swaps_day=num(k["swaps_per_day"]), swaps_disabled=pct(k["swaps_from_disabled"]),
                b_before=f"{k['swap_battery_before']:.0f}", b_after=f"{k['swap_battery_after']:.0f}",
                peak_text=peak_text, n_evenings=len(ev), n_majority=int((ev["share_after_peak"] > 0.5).sum()),
                q_peak=num(ev["queue_at_peak"].mean()),
                after_mean=pct(ev["share_after_peak"].mean()),
                after_min=pct(ev["share_after_peak"].min()), after_max=pct(ev["share_after_peak"].max()),
                morning_min=num(ev["morning_queue"].min()), morning_max=num(ev["morning_queue"].max()),
                w_med=f"{k['wait']['median']:.1f}", w_p75=f"{k['wait']['p75']:.1f}",
                w_p90=f"{k['wait']['p90']:.1f}", bcn_wait=bcn_wait,
                w_mid=f"{k['wait_midday']:.1f}", w_late=f"{k['wait_late']:.1f}",
                mid_from=MIDDAY_HOURS[0], mid_to=MIDDAY_HOURS[1] + 1,
                late_from=LATE_HOURS[0],
                late_to="midnight" if LATE_HOURS[1] == 23 else f"{LATE_HOURS[1] + 1}h",
                waiting_now=k["waiting_now"], waiting_max=f"{k['waiting_now_max_days']:.1f}",
                bcn_available=pct(bcn["pct_available"]) if bcn is not None else "--",
                bcn_battery=pct(bcn["pct_battery"], 1) if bcn is not None else "--",
                tension=names(t), tension_dep=num(t["dep"].sum()), tension_stock=f"{t['stock'].sum():.1f}",
                tension_days=f"{int(t['days_top10'].min())}",
                surplus=names_by_town(s), surplus_stock=f"{s['stock'].sum():.1f}", surplus_dep=f"{s['dep'].sum():.1f}",
                move_n=move_n, other_now=k["other_now"], other_long=k["other_now_long"],
                other_3d=k["other_now_3d"], other_max=f"{k['other_now_max_days']:.1f}",
                idle_hours=IDLE_HOURS, oa_text=oa_text,
                over100_obs=int(qual.over_100_obs), over100_veh=int(qual.over_100_vehicles),
                active_low=num(qual.active_low_obs), valid_obs=num(qual.valid_obs / 1e6, 0),
                fig_fleet=figure_fleet(p, n_days), fig_timing=figure_timing(p, n_days),
                table_evenings=evenings_table(ev), table_zones=zone_table(t, s, n_days))


PREAMBLE = r"""\documentclass[11pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage[margin=2cm]{geometry}
\usepackage{amsmath}
\usepackage{booktabs}
\usepackage{xcolor}
\usepackage{enumitem}
\usepackage{pgfplots}
\usepgfplotslibrary{groupplots}
\pgfplotsset{compat=1.18}
\usepackage[font=small,labelfont=bf,skip=4pt]{caption}
\usepackage[hidelinks]{hyperref}

\definecolor{yblue}{HTML}{2A78D6}
\definecolor{yorange}{HTML}{EB6834}
\definecolor{yaqua}{HTML}{1BAF7A}

\setlist{itemsep=2pt, topsep=3pt}
\setlength{\textfloatsep}{10pt}

\newcommand{\myname}{Marius Casamian}
"""

BODY = r"""
\begin{document}

\begin{center}
  {\Large\bfseries Monitoring the YEGO scooter fleet in Nice with public GBFS data}\\[4pt]
  \myname\ --- application for the Data Analyst -- Operations position (V.I.E.\ 246717)\\
  <<date>> \quad $\cdot$ \quad Code and data: \url{https://<<repo>>}
\end{center}

\begin{abstract}
\noindent YEGO publishes the position and battery level of its scooters in real time through the
General Bikeshare Feed Specification (GBFS). I collected this feed every two minutes in Nice and
Barcelona from <<start>> to <<end>> (<<n_snapshots>> snapshots for Nice, including <<n_days>>
complete days) and computed operational indicators with dbt. Three findings stand out for Nice:
(i) on <<n_majority>> of the <<n_evenings>> evenings observed, most battery swaps came after the demand peak,
while about <<q_peak>> scooters were waiting for a battery at that peak; (ii) a scooter disabled
for low battery waits <<w_med>>\,h (median) before its swap, about twice as long as in Barcelona;
(iii) <<other>> of the fleet is disabled for reasons other than battery, often for days.
\end{abstract}

\section{Data and method}

\textbf{Data.} For every scooter that is parked and not rented, the feed \cite{gbfs} gives its
position, battery level and two flags, \texttt{is\_reserved} and \texttt{is\_disabled}. A Python
collector, first on my computer and then on GitHub Actions every hour, stores each snapshot as a
Parquet file. The collection has one interruption of <<gap_h>>\,h (12--13 October) and is complete
from <<full_from>> to <<full_to>>; daily averages below use only these <<n_days>> complete days.

\textbf{Anonymised identifiers.} The \texttt{bike\_id} field is regenerated at every request, so a
scooter cannot be followed through its identifier. I match the scooters of two consecutive snapshots:
a pair $(i,j)$ is a candidate if both have the same type and are less than 15\,m apart, with cost
\begin{equation}
  c_{ij} = d_{ij} + \lambda\,\lvert b_i - b_j \rvert, \qquad \lambda = 0.5\ \text{m per battery point},
\end{equation}
where $d_{ij}$ is the distance and $b$ the battery level. I keep the one-to-one matching with the
lowest total cost (Hungarian algorithm \cite{kuhn1955}), plus a second pass for GPS jumps up to
150\,m when the battery is unchanged. <<tracking>> of the observations are linked to a scooter of
the previous snapshot.

\textbf{Events and quality checks.} A \emph{departure} is a scooter that disappears from the feed
(rented, or picked up by the staff). A \emph{battery swap} is a rise of at least 20 battery points on
the same scooter. A \emph{battery wait} runs from the moment a scooter is disabled for low battery
to the moment it leaves this state. Everything is modelled with dbt on DuckDB \cite{duckdb}, with
data tests on keys, relationships, positions, collection gaps and business rules
(<<tests_pass>> passed, <<tests_warn>> warnings, <<tests_fail>> failed).<<warn_text>>

\section{Results}

\textbf{Fleet availability.} On average <<fleet>> scooters were listed in Nice and <<available>>
were available (Figure~\ref{fig:fleet}). <<battery>> were disabled because of their battery and
<<other>> for another reason. No active scooter had less than <<thr>>\% battery, apart from a few
transient cases in Barcelona, so YEGO disables scooters under this threshold. The battery queue
never empties: between <<q_min>> and <<q_max>> scooters are waiting at any hour of an average day.
In Barcelona, <<bcn_available>> of the scooters are available and only <<bcn_battery>> wait for
a battery. Nice has about <<dep_scooter>> departures per scooter and per day (<<dep_day>> in
total).

<<fig_fleet>>

\textbf{Battery swaps and demand.} I detected <<swaps_day>> battery swaps per day in Nice;
<<swaps_disabled>> of them on a disabled scooter, whose battery went from <<b_before>>\% to
<<b_after>>\% on average. Demand peaks at the end of the afternoon, and every evening the busiest
hour was <<peak_text>> (Table~\ref{tab:evenings}). Swaps, however, are concentrated between 20h and
2h (Figure~\ref{fig:timing}): on average <<after_mean>> of the swaps of an evening and night
came after its peak (from <<after_min>> to <<after_max>> depending on the evening). The queue is
also not emptied by the morning: <<morning_min>> to <<morning_max>> scooters were still waiting
between 5h and 9h.

<<fig_timing>>

<<table_evenings>>

\textbf{Battery waiting time.} Once disabled for low battery, a scooter in Nice waits
<<w_med>>\,h before its swap (median); a quarter wait more than <<w_p75>>\,h and a tenth more than
<<w_p90>>\,h. <<bcn_wait>> The hour matters: scooters disabled between <<mid_from>>h and
<<mid_to>>h wait <<w_mid>>\,h (median), because they are only handled by the evening round, against
<<w_late>>\,h for scooters disabled between <<late_from>>h and <<late_to>>. At the last snapshot,
<<waiting_now>> scooters were waiting, one of them for <<waiting_max>> days.

\textbf{Supply and demand by zone.} The same central zones are short of scooters almost every day,
while zones in the west of the service area keep scooters that are rarely rented
(Table~\ref{tab:zones}).

<<table_zones>>

\subsection{Data quality findings}
\label{sec:quality}

The tests flagged several things that an Operations team would want to know: <<oa_text>>, far
outside the service area; <<over100_obs>> observations of <<over100_veh>> Barcelona scooters show a
battery of 101\%; and <<active_low>> of <<valid_obs>> million observations show an active scooter
below <<thr>>\%, always for a few minutes only. One Barcelona scooter is also published at latitude
0, longitude 0 in every snapshot.

\section{Recommendations}

\begin{enumerate}
  \item \textbf{Move part of the evening battery round to the early afternoon.} Scooters disabled
  around midday wait until the evening round, and about <<q_peak>> scooters are unavailable at the
  daily peak (<<peak_text>>). Swapping them between 12h and 16h would put them back on the street
  for the peak, and would bring Nice closer to Barcelona's waiting time.
  \item \textbf{Move about <<move_n>> scooters from low-demand to high-demand zones every night.}
  <<tension>> generate <<tension_dep>> departures per day for <<tension_stock>> available scooters,
  and were in the top 10 of tension on at least <<tension_days>> of the <<n_days>> days: the
  imbalance is structural. <<surplus>> keep <<surplus_stock>> scooters for <<surplus_dep>>
  departures per day.
  \item \textbf{Review the scooters disabled for other reasons every day.} At the last snapshot,
  <<other_now>> scooters were disabled with a correct battery, <<other_long>> of them for more than
  <<idle_hours>>\,h and <<other_3d>> for more than three days. A daily list built from the data,
  including the scooters outside the service area, would free part of this capacity.
\end{enumerate}

\section{Limitations and next steps}

The study covers two weeks of October, without weather data, so seasonal effects are not measured.
A departure can be a rental or a pick-up by the staff, rides shorter than about four minutes are
invisible, and the tracking can make mistakes in dense parking spots. With YEGO's internal data, I
would first join departures with real rentals to measure true demand, then compare the battery
waiting time per team and per shift, and finally test the recommendations on a few zones against
similar zones left unchanged.

{\small
\begin{thebibliography}{9}
\setlength{\itemsep}{0pt}
\bibitem{gbfs} MobilityData. \emph{General Bikeshare Feed Specification (GBFS)}, v2.3.
  \url{https://github.com/MobilityData/gbfs}.
\bibitem{kuhn1955} H.~W. Kuhn. The Hungarian method for the assignment problem.
  \emph{Naval Research Logistics Quarterly}, 2(1--2):83--97, 1955.
\bibitem{duckdb} M.~Raasveldt and H.~M\"uhleisen. DuckDB: an embeddable analytical database.
  \emph{SIGMOD}, 2019.
\end{thebibliography}
}

\end{document}
"""


def main() -> None:
    k = build()
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(render(k), encoding="utf-8")
    print(f"LaTeX : {OUT}")


if __name__ == "__main__":
    main()
