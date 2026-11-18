"""Vieillissement : papier et encre compares aux documents AUTHENTIQUES de la MEME annee.

Conditions de validite :
- memes reglages de scan pour les references et les documents controles (300 DPI, couleur,
  sans amelioration automatique) ;
- au moins `aging_min_docs_per_year` documents authentiques par annee (5), sinon ligne masquee ;
- entre 5 et `aging_reliable_docs` (30) documents : la plage normale est mal connue. La limite
  de score z est elargie (x (30 / n) ** 0.3 : 6,0 pour 5 documents) : en simulation, moins de
  5 % de documents authentiques signales a tort. Confiance reduite ; signal marque
  `reduced_reliability`.

Risque : une seule mesure nettement hors plage suffit a demander une verification (0,5) ;
chaque mesure supplementaire l'augmente (6 mesures -> 1,0). Le calcul fourni a l'origine
(part des mesures signalees) laissait une anomalie nette isolee en dessous du seuil de revue.
Limite : un faux imprime sur du papier d'epoque de la meme annee passe ce controle seul.
"""
from __future__ import annotations

import cv2
import numpy as np

from ..config import SETTINGS, Settings
from ..determinism import round_score
from .base import Signal

MEASURES = ["paper_L", "paper_b", "paper_grain", "text_contrast", "seal_contrast", "seal_text_gap"]


def measures(img_bgr: np.ndarray, paper_mask: np.ndarray, text_mask: np.ndarray,
             seal_mask: np.ndarray) -> dict | None:
    """Masques booleens (papier = marges vierges, texte imprime, sceau). Lab d'OpenCV."""
    if min(paper_mask.sum(), text_mask.sum(), seal_mask.sum()) < 100:
        return None
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    L, b = lab[..., 0], lab[..., 2]
    paper_L = float(np.median(L[paper_mask]))
    text_c = paper_L - float(np.median(L[text_mask]))
    seal_c = paper_L - float(np.median(L[seal_mask]))
    return {
        "paper_L": paper_L,
        "paper_b": float(np.median(b[paper_mask])),
        "paper_grain": float(L[paper_mask].std()),
        "text_contrast": text_c,
        "seal_contrast": seal_c,
        "seal_text_gap": abs(seal_c - text_c),
    }


def build_profile(values, min_mad: float = SETTINGS.aging_min_mad) -> tuple[float, float]:
    """(mediane, MAD) avec un plancher : bruit de mesure du scanner.

    Sans plancher, une mesure parfaitement stable (ecart nul) ne pourrait jamais etre signalee.
    """
    v = np.asarray(values, dtype=float)
    med = float(np.median(v))
    mad = float(np.median(np.abs(v - med)))
    return med, max(mad, min_mad)


def robust_z(x: float, med: float, mad: float) -> float:
    return 0.6745 * (x - med) / mad


def aging_signal(m: dict | None, profiles: dict, n_docs: int,
                 settings: Settings = SETTINGS) -> Signal | None:
    """None (ligne masquee) si l'annee a trop peu de references ou si les mesures manquent."""
    if m is None or n_docs < settings.aging_min_docs_per_year:
        return None
    reduced = n_docs < settings.aging_reliable_docs
    limit = settings.aging_z_limit * ((settings.aging_reliable_docs / n_docs) ** 0.3 if reduced else 1.0)
    zs = {k: round_score(robust_z(m[k], *profiles[k])) for k in MEASURES}
    flagged = [k for k in MEASURES if abs(zs[k]) > limit]
    risk = 0.0 if not flagged else 0.5 + 0.5 * (len(flagged) - 1) / (len(MEASURES) - 1)
    conf = min(1.0, n_docs / 100)           # plus l'annee est documentee, plus on s'y fie
    return Signal(risk=round_score(risk), confidence=round_score(conf),
                  evidence={"flagged": flagged, "z": zs, "z_limit": round_score(limit),
                            "n_reference_docs": n_docs, "reduced_reliability": reduced})
