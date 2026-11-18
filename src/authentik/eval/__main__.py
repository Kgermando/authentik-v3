"""Commande d'evaluation : python -m authentik.eval DOSSIER [--sortie DOSSIER] [--config INI]."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..determinism import init_determinism
from ..store import load_config
from .runner import __doc__ as HELP
from .runner import evaluate, markdown


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m authentik.eval", description=HELP,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dossier", help="dossier du jeu de test (avec labels.csv)")
    ap.add_argument("--sortie", default=None, help="dossier du rapport (defaut : DOSSIER/rapport)")
    ap.add_argument("--config", default=None, help="authentik.ini a utiliser (references)")
    a = ap.parse_args(argv)
    init_determinism()
    cfg = load_config(a.config)
    out = a.sortie or str(Path(a.dossier) / "rapport")
    try:
        report = evaluate(a.dossier, cfg, out, lambda s, p: print(f"[{p:3d} %] {s}", flush=True))
    except (FileNotFoundError, ValueError) as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 2
    print()
    print(markdown(report))
    print(f"Rapport : {out}/evaluation.md, evaluation.json, roc.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
