"""Zone ajoutee apres coup : le papier autour du sceau / de la signature ressemble-t-il au reste ?

Un morceau colle depuis un autre document emporte SON papier : grain (bruit), teinte et nettete
differents du papier voisin, et souvent un halo ou un bord net autour de la zone collee.

Mesures (papier vierge = pixels clairs sans encre) :
- noise_ratio : grain du papier dans la zone / grain du papier de la page (log) ;
- delta_e     : ecart de teinte (Lab) entre papier de la zone et papier de la page ;
- edge_step   : saut de luminosite le long du bord de la zone (montage rectangulaire).
Comparees aux memes mesures sur les documents AUTHENTIQUES de reference (score z robuste).
Limite : peu efficace sur un scan unique tres compresse. NON VALIDE sur de vrais documents.
"""
from __future__ import annotations

import cv2
import numpy as np

from ..determinism import round_score
from .base import Signal

MEASURES = ("noise_ratio", "delta_e", "edge_step")
MIN_REFERENCES = 5


def integrity_features(img: np.ndarray, box, paper_mask: np.ndarray, pad: int = 40) -> dict | None:
    H, W = img.shape[:2]
    x0, y0 = max(0, box.x - pad), max(0, box.y - pad)
    x1, y1 = min(W, box.x + box.w + pad), min(H, box.y + box.h + pad)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    L = lab[..., 0]
    hp = L - cv2.GaussianBlur(L, (0, 0), 2)                 # grain (haute frequence)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    blank = (hsv[..., 2] >= 150) & (hsv[..., 1] < 50)       # papier clair sans encre
    inside = np.zeros((H, W), bool)
    inside[y0:y1, x0:x1] = True
    zone = blank & inside
    zone = cv2.erode(zone.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    page = paper_mask & ~inside
    if zone.sum() < 2000 or page.sum() < 20000:
        return None
    n_zone, n_page = float(hp[zone].std()), float(hp[page].std())
    de = float(np.linalg.norm(np.median(lab[zone], axis=0) - np.median(lab[page], axis=0)))
    # saut de luminosite entre une bande juste dedans et juste dehors du bord de la zone
    outer = np.zeros((H, W), bool)
    outer[max(0, y0 - 12):min(H, y1 + 12), max(0, x0 - 12):min(W, x1 + 12)] = True
    ring_out = blank & outer & ~inside
    ring_in = blank & _inner(inside, 12)
    step = abs(float(np.median(L[ring_in])) - float(np.median(L[ring_out]))) \
        if ring_in.sum() > 200 and ring_out.sum() > 200 else 0.0
    return {"noise_ratio": float(np.log(max(n_zone, 1e-3) / max(n_page, 1e-3))),
            "delta_e": de, "edge_step": step}


def _inner(inside: np.ndarray, width: int) -> np.ndarray:
    """Bande de `width` pixels a l'interieur du bord de la zone."""
    eroded = cv2.erode(inside.astype(np.uint8), np.ones((2 * width + 1,) * 2, np.uint8)) > 0
    return inside & ~eroded


def build_profile(feature_dicts: list[dict], min_mad: dict | None = None) -> dict | None:
    feats = [f for f in feature_dicts if f]
    if len(feats) < MIN_REFERENCES:
        return None
    floors = min_mad or {"noise_ratio": 0.05, "delta_e": 0.5, "edge_step": 0.5}
    prof = {}
    for k in MEASURES:
        v = np.array([f[k] for f in feats], float)
        med = float(np.median(v))
        prof[k] = (med, max(float(np.median(np.abs(v - med))), floors[k]), len(v))
    return prof


def integrity_signal(feats: dict | None, profile: dict | None, z_limit: float = 3.5) -> Signal | None:
    if feats is None or profile is None:
        return None
    zs, flagged = {}, []
    for k in MEASURES:
        med, mad, _ = profile[k]
        z = 0.6745 * (feats[k] - med) / mad
        zs[k] = round_score(z)
        if abs(z) > z_limit:
            flagged.append(k)
    risk = len(flagged) / len(MEASURES)
    return Signal(round_score(risk), 0.6,
                  {"features": {k: round_score(v) for k, v in feats.items()}, "z": zs,
                   "flagged": flagged, "n_references": profile[MEASURES[0]][2]})
