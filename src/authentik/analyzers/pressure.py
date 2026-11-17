"""Pression et depot de l'encre : tampon a l'encre original vs reproduction sur papier.

Un scanner a plat ne mesure PAS le relief. On mesure l'effet de la pression sur l'encre :
densite inegale (pressure_gradient) et etendue des tons (ink_range). Une reproduction
(photocopie, impression puis rescan) est plus uniforme que l'encre d'un vrai tampon.

Ne voit pas un vrai sceau copie numeriquement : c'est le role de `copy`.
Valide sur images de synthese uniquement.
"""
from __future__ import annotations

import cv2
import numpy as np

from ..config import SETTINGS, Settings
from ..determinism import round_score
from .base import Signal


def pressure_features(gray: np.ndarray, ink_level: int = 150, erode: int = 7) -> dict | None:
    """Mesures a l'interieur des traits. Renvoie None si la zone d'encre est trop petite."""
    g = gray.astype(np.float32)
    ink = (g < ink_level).astype(np.uint8)
    core = cv2.erode(ink, np.ones((erode, erode), np.uint8)) > 0
    if core.sum() < 500:
        return None
    band = (cv2.dilate(ink, np.ones((5, 5), np.uint8)) - cv2.erode(ink, np.ones((5, 5), np.uint8))) > 0
    far = cv2.dilate(ink, np.ones((15, 15), np.uint8)) == 0
    if far.sum() == 0 or band.sum() == 0:
        return None
    paper = float(np.median(g[far]))
    contrast = max(paper - float(np.median(g[core])), 1.0)

    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.hypot(gx, gy)

    num = cv2.GaussianBlur(np.where(core, g, 0).astype(np.float32), (0, 0), 15)
    den = cv2.GaussianBlur(core.astype(np.float32), (0, 0), 15)
    ok = core & (den > 0.05)
    if ok.sum() == 0:
        return None
    dens = num[ok] / den[ok]

    p5, p95 = np.percentile(g[core], [5, 95])
    return {
        "ink_spread": float(g[core].std() / contrast),
        "ink_range": float((p95 - p5) / contrast),
        "edge_sharpness": float(mag[band].mean() / contrast),
        "pressure_gradient": float(dens.std() / contrast),
    }


def build_pressure_profile(feature_dicts: list[dict], min_mad: float = 0.0) -> dict:
    """Plage normale des mesures, calculee sur des tampons AUTHENTIQUES (mediane, MAD)."""
    profile = {}
    for k in feature_dicts[0]:
        v = np.array([f[k] for f in feature_dicts], dtype=float)
        med = float(np.median(v))
        mad = float(np.median(np.abs(v - med)))
        profile[k] = (med, max(mad, min_mad, 1e-6))
    return profile


def pressure_signal(gray: np.ndarray, profile: dict, erode: int | None = None,
                    settings: Settings = SETTINGS) -> Signal | None:
    """Risque = part des mesures cles anormalement FAIBLES (trop uniformes) par rapport au profil.

    Unilateral : seule une encre trop uniforme est suspecte (reproduction).
    Renvoie None si la zone est trop petite (ligne masquee).
    """
    feats = pressure_features(gray, ink_level=settings.ink_level,
                              erode=erode or settings.pressure_erode_seal)
    if feats is None:
        return None
    flagged, zs = [], {}
    for k in settings.pressure_features:
        med, mad = profile[k]
        z = 0.6745 * (feats[k] - med) / mad
        zs[k] = round_score(z)
        if z < -settings.pressure_z_limit:
            flagged.append(k)
    risk = len(flagged) / len(settings.pressure_features)
    return Signal(risk=round_score(risk), confidence=0.7,
                  evidence={"features": {k: round_score(v) for k, v in feats.items()},
                            "z": zs, "flagged": flagged})
