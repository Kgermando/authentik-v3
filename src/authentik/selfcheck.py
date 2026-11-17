"""Verification apres installation : `authentik --verifier <document>` (sans interface).

Charge le document, lit l'annee, verifie l'OCR et les pilotes de scan, puis deroule une analyse
dans un dossier TEMPORAIRE (la vraie base et le vrai dossier des documents ne sont pas touches).
Code de sortie 0 si tout fonctionne, 1 sinon.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from . import __version__


def run(document: str, out=sys.stdout) -> int:
    from . import pipeline
    from .ingest.year import configure_tesseract
    from .scan import sane, wia
    from .store import AppConfig, Database, load_config

    ok = True

    def line(label: str, value, good: bool = True) -> None:
        nonlocal ok
        ok = ok and good
        print(f"[{'OK' if good else 'ÉCHEC'}] {label} : {value}", file=out)

    print(f"Authentik {__version__} — vérification", file=out)
    cfg = load_config()
    line("Configuration", f"{cfg.ini_path}" + (f" ({cfg.warning})" if cfg.warning else ""),
         cfg.warning is None)
    line("OCR Tesseract (fra)", "disponible" if configure_tesseract() else
         "absent : l'année devra être saisie à la main", True)
    driver = "WIA" if sys.platform == "win32" else "SANE"
    has_driver = wia.available() if sys.platform == "win32" else sane.available()
    line(f"Pilote de scan {driver}", "disponible" if has_driver else "absent (scan réseau eSCL seulement)")
    try:
        prepared = pipeline.prepare(Path(document))
        h, w = prepared.doc.pages[0].shape[:2]
        line("Lecture du document", f"{len(prepared.doc.pages)} page(s), {w} x {h} pixels")
        line("Année lue", prepared.year_reading.year or prepared.year_reading.message)
        with tempfile.TemporaryDirectory(prefix="authentik_verif_") as tmp:
            t = Path(tmp)
            tcfg = AppConfig(t / "verif.db", t / "documents", t / "verif.ini")
            out_ = pipeline.run_analysis(prepared, prepared.year_reading.year or 2000, tcfg,
                                         Database(tcfg.database))
            line("Analyse (dossier temporaire)", f"verdict = {out_.verdict or 'aucun (contrôles à venir)'}"
                 f", copie intègre = {out_.integrity_ok}", out_.integrity_ok)
    except Exception as e:                                # noqa: BLE001
        line("Analyse", e, False)
    print("Résultat :", "tout fonctionne." if ok else "au moins une vérification a échoué.", file=out)
    return 0 if ok else 1
