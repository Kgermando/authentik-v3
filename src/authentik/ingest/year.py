"""Lecture de l'annee du document par OCR (Tesseract, langue fra).

L'annee lue est seulement PROPOSEE : l'utilisateur la confirme ou la corrige avant l'analyse.
Sans Tesseract, `read_year` renvoie year=None et un message ; l'annee se saisit a la main.
"""
from __future__ import annotations

import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np

MIN_YEAR = 1960
MONTHS = ("janvier|fevrier|février|mars|avril|mai|juin|juillet|aout|août|septembre|"
          "octobre|novembre|decembre|décembre")

# Ordre de preference : date complete > « annee 2019 » > annee isolee.
_FULL_NUMERIC = re.compile(r"\b(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*((?:19|20)\d{2})\b")
_FULL_TEXT = re.compile(rf"\b(\d{{1,2}}|1er)\s+({MONTHS})\s+((?:19|20)\d{{2}})\b", re.I)
_LABELLED = re.compile(r"\b(?:annee|année|exercice|promotion|session)\s*(?:academique\s*|académique\s*)?"
                       r"[:\-]?\s*((?:19|20)\d{2})\b", re.I)
_BARE = re.compile(r"(?<![\d/.\-])((?:19|20)\d{2})(?![\d/.\-])")


@dataclass
class YearReading:
    year: int | None
    candidates: list[int] = field(default_factory=list)
    source: str = ""                  # extrait du texte ou est lue l'annee
    message: str | None = None        # explication si rien n'a ete lu


def find_year(text: str, today: date | None = None) -> YearReading:
    """Choisit l'annee la plus plausible dans un texte OCR (fonction pure, testee)."""
    max_year = (today or date.today()).year
    ok = lambda y: MIN_YEAR <= y <= max_year                       # noqa: E731
    for rx, group in ((_FULL_NUMERIC, 3), (_FULL_TEXT, 3), (_LABELLED, 1)):
        found = [(int(m.group(group)), m.group(0)) for m in rx.finditer(text)
                 if ok(int(m.group(group)))]
        if found:
            years = [y for y, _ in found]
            # la date la plus recente est en general celle de delivrance (en bas du certificat)
            best = max(years)
            src = next(s for y, s in reversed(found) if y == best)
            return YearReading(best, sorted(set(years)), src.strip())
    bare = [int(m.group(1)) for m in _BARE.finditer(text) if ok(int(m.group(1)))]
    if bare:
        best = Counter(bare).most_common(1)[0][0] if len(set(bare)) > 1 else bare[0]
        return YearReading(best, sorted(set(bare)), str(best),
                           "Année isolée, sans date complète : à vérifier.")
    return YearReading(None, message="Aucune année lisible : saisir l'année à la main.")


def configure_tesseract() -> bool:
    """Utilise le Tesseract embarque (version installee) s'il existe. Renvoie True si disponible."""
    import pytesseract
    base = Path(getattr(sys, "_MEIPASS", "")) / "tesseract" if getattr(sys, "frozen", False) else None
    if base is not None:
        exe = base / ("tesseract.exe" if sys.platform == "win32" else "tesseract")
        if exe.exists():
            pytesseract.pytesseract.tesseract_cmd = str(exe)
            os.environ["TESSDATA_PREFIX"] = str(base / "tessdata")
    try:
        pytesseract.get_tesseract_version()
        return "fra" in pytesseract.get_languages(config="")
    except Exception:
        return False


def read_year(page_bgr: np.ndarray, today: date | None = None) -> YearReading:
    try:
        import pytesseract
        if not configure_tesseract():
            return YearReading(None, message="Tesseract (langue fra) n'est pas installé : "
                                             "saisir l'année à la main.")
        text = pytesseract.image_to_string(page_bgr[..., ::-1], lang="fra", config="--psm 3")
    except Exception as e:
        return YearReading(None, message=f"Lecture OCR impossible ({e}) : saisir l'année à la main.")
    return find_year(text, today)
