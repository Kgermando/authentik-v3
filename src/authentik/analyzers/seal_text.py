"""Texte circulaire du sceau : deroule par cv2.warpPolar, lu par OCR, compare au texte attendu.

Le texte attendu vient des sceaux de reference (champ « texte du sceau » saisi dans le menu
References). Sans texte attendu, ou sans Tesseract, le controle n'a pas de valeur (None).
Limite : sceau tres pale ou masque. NON VALIDE sur de vrais sceaux.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

import cv2
import numpy as np

from ..determinism import round_score
from .base import Signal


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]", "", t)


def best_match(expected: str, read: str) -> float:
    """Meilleure ressemblance (0-1) entre le texte attendu et une portion du texte lu.
    Le texte d'un cercle n'a pas de debut : `read` est lu sur deux tours."""
    e, r = normalize(expected), normalize(read)
    if not e or not r:
        return 0.0
    best = 0.0
    for start in range(0, max(1, len(r) - len(e) + 1)):
        best = max(best, SequenceMatcher(None, e, r[start:start + len(e)]).ratio())
    return max(best, SequenceMatcher(None, e, r).ratio())


def unwrap(gray: np.ndarray, circle_in_crop: tuple[float, float, float],
           band: tuple[float, float] = (0.55, 1.0)) -> np.ndarray:
    """Bande circulaire deroulee en une ligne horizontale, repetee deux fois (2 tours)."""
    cx, cy, r = circle_in_crop
    h_out = int(2 * np.pi * r)                       # une ligne par pixel de circonference
    polar = cv2.warpPolar(gray, (int(r * 1.05), h_out), (cx, cy), r * 1.05,
                          cv2.WARP_POLAR_LINEAR | cv2.INTER_LINEAR)
    lo, hi = int(band[0] * polar.shape[1]), int(band[1] * polar.shape[1] / 1.05)
    strip = polar[:, lo:hi]                          # lignes = angle, colonnes = rayon
    strip = cv2.rotate(strip, cv2.ROTATE_90_COUNTERCLOCKWISE)   # angle -> horizontal
    return np.hstack([strip, strip])


def ocr_strip(strip: np.ndarray) -> str:
    import pytesseract
    texts = []
    for img in (strip, cv2.rotate(strip, cv2.ROTATE_180)):     # sens de lecture inconnu
        texts.append(pytesseract.image_to_string(img, lang="fra", config="--psm 7"))
    return " ".join(texts)


def text_risk(similarity: float, ok: float = 0.85, bad: float = 0.5) -> float:
    """>= ok : texte conforme (petites erreurs d'OCR toleres) ; <= bad : texte different."""
    return round_score(min(1.0, max(0.0, (ok - similarity) / (ok - bad))))


def seal_text_signal(gray_crop: np.ndarray, circle_in_crop, expected: str | None,
                     ocr=ocr_strip) -> Signal | None:
    if not expected or circle_in_crop is None:
        return None
    try:
        read = ocr(unwrap(gray_crop, circle_in_crop))
    except Exception:                                # noqa: BLE001 - OCR absent ou en erreur
        return None
    score = round_score(best_match(expected, read))
    risk = text_risk(score)
    conf = 0.4 if len(normalize(read)) < len(normalize(expected)) // 2 else 0.7
    return Signal(risk, conf, {"expected": expected, "read": read.strip()[:300], "similarity": score})
