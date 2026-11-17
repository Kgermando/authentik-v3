"""Detection de copie : un sceau ou une signature colle depuis un autre document.

Principe : aligner le candidat sur un element deja vu (AKAZE + RANSAC), puis mesurer la
correlation de l'encre a l'interieur des traits. Residu proche de 0 = meme texture d'encre =
copie numerique. Residu proche de 1 = tampon reapose (meme forme, autre depot d'encre).

Valide sur images de synthese uniquement. Seuils a calibrer sur de vraies paires.
"""
from __future__ import annotations

import cv2
import numpy as np

from ..config import SETTINGS, Settings
from ..determinism import SEED, round_score
from .base import Signal


def _ncc(u: np.ndarray, v: np.ndarray) -> float:
    u = u - u.mean()
    v = v - v.mean()
    return float((u * v).sum() / (np.sqrt((u * u).sum() * (v * v).sum()) + 1e-9))


def align_and_compare(a: np.ndarray, b: np.ndarray, ratio: float = 0.75,
                      ink_level: int = 150) -> tuple[int, float]:
    """Aligne `a` (niveaux de gris) sur `b`. Renvoie (inliers, residu)."""
    cv2.setRNGSeed(SEED)  # RANSAC : meme graine a chaque appel
    akaze = cv2.AKAZE_create()
    ka, da = akaze.detectAndCompute(a, None)
    kb, db = akaze.detectAndCompute(b, None)
    if da is None or db is None:
        return 0, 1.0
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(da, db, k=2)
    good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < ratio * p[1].distance]
    if len(good) < 4:
        return len(good), 1.0
    src = np.float32([ka[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kb[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    if H is None:
        return 0, 1.0
    inliers = int(mask.sum())
    size = (b.shape[1], b.shape[0])
    warped = cv2.warpPerspective(a, H, size)
    inside = cv2.warpPerspective(np.ones_like(a), H, size)
    ink = (b < ink_level).astype(np.uint8) & (warped < ink_level).astype(np.uint8)
    core = cv2.erode(ink & inside, np.ones((7, 7), np.uint8)) > 0
    if core.sum() < 500:
        return inliers, 1.0
    corr = _ncc(warped[core].astype(np.float32), b[core].astype(np.float32))
    return inliers, 1.0 - max(0.0, corr)


def copy_signal(candidate: np.ndarray, known: list[tuple[str, np.ndarray]],
                settings: Settings = SETTINGS) -> Signal | None:
    """Compare `candidate` aux elements deja vus `known` = [(id_document, image), ...].

    Renvoie None s'il n'y a rien a comparer (ligne masquee), sinon un Signal.
    risk = 1.0 si une copie numerique est trouvee (regle dure de la fusion).
    """
    if not known:
        return None
    best = None
    for doc_id, img in known:                      # ordre fixe : liste triee par l'appelant
        inliers, residual = align_and_compare(candidate, img, ink_level=settings.ink_level)
        if inliers >= settings.copy_min_inliers and (best is None or residual < best["residual"]):
            best = {"document": doc_id, "inliers": inliers, "residual": round_score(residual)}
    if best is not None and best["residual"] <= settings.copy_max_residual:
        return Signal(risk=1.0, confidence=1.0, evidence={"copy_of": best})
    return Signal(risk=0.0, confidence=0.8, evidence={"closest": best})
