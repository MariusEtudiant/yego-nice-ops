"""
Enchaine tout le traitement sur les donnees deja collectees :
suivi des vehicules -> dbt build (modeles + tests) -> note d'analyse -> export compact.

    python src/pipeline.py
"""

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable
DBT = pathlib.Path(PY).with_name("dbt.exe" if sys.platform == "win32" else "dbt")


def step(title: str, cmd: list[str], cwd: pathlib.Path = ROOT) -> None:
    print(f"\n=== {title} ===", flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


if __name__ == "__main__":
    step("Suivi des vehicules", [PY, "src/track_vehicles.py"])
    # dbt build echoue sur un test en erreur ; les avertissements (trous, GPS aberrants) passent.
    step("dbt build", [str(DBT), "build", "--profiles-dir", "."], cwd=ROOT / "transform")
    step("Note d'analyse", [PY, "src/build_report.py"])
    step("Rapport LaTeX (anglais)", [PY, "src/build_latex.py"])
    step("Export du jeu de donnees compact", [PY, "src/export_dataset.py"])
