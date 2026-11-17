"""Ressemblance du sceau / de la signature aux specimens authentiques.

AGENTS.md prevoit des embeddings ONNX. Aucun modele ne peut etre entraine sans vos specimens :
en attendant, un DESCRIPTEUR CLASSIQUE (HOG de la forme de l'encre) est utilise. Il peut etre
remplace par un modele ONNX sans changer le reste (meme fonction `embed`).

La distance au plus proche specimen est comparee a la variation NATURELLE entre specimens
(distance de chaque specimen a son plus proche voisin). Les signatures varient naturellement :
seule, cette mesure ne rejette jamais (confiance plafonnee).
"""
from __future__ import annotations

import cv2
import numpy as np
from skimage.feature import hog

from ..determinism import round_score
from .base import Signal

DESCRIPTOR_VERSION = "hog-128-v1"
SIZE = 128
MIN_SPECIMENS = 3


def embed(gray: np.ndarray, ink_level: int = 170) -> np.ndarray:
    """Vecteur de forme normalise (float32). Meme image => meme vecteur."""
    ink = (gray < ink_level).astype(np.uint8)
    ys, xs = np.nonzero(ink)
    if len(xs) < 50:
        return np.zeros(1, np.float32)
    ink = ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = ink.shape
    side = max(h, w)
    sq = np.zeros((side, side), np.float32)
    sq[(side - h) // 2:(side - h) // 2 + h, (side - w) // 2:(side - w) // 2 + w] = ink
    sq = cv2.resize(sq, (SIZE, SIZE), interpolation=cv2.INTER_AREA)
    sq = cv2.GaussianBlur(sq, (0, 0), 1.5)
    v = hog(sq, orientations=9, pixels_per_cell=(16, 16), cells_per_block=(2, 2),
            feature_vector=True).astype(np.float32)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def to_bytes(v: np.ndarray) -> bytes:
    return np.asarray(v, "<f4").tobytes()


def from_bytes(b: bytes) -> np.ndarray:
    return np.frombuffer(b, "<f4")


def _dist(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        return 1.0
    return float(1.0 - np.dot(a, b))


def reference_signal(candidate: np.ndarray, specimens: list[tuple[str, np.ndarray]],
                     z_limit: float = 3.5) -> Signal | None:
    """`specimens` = [(identifiant, vecteur)] dans un ordre fixe. None si trop peu de specimens."""
    vecs = [(i, v) for i, v in specimens if v.size > 1]
    if len(vecs) < MIN_SPECIMENS or candidate.size <= 1:
        return None
    dists = [(_dist(candidate, v), i) for i, v in vecs]
    d_min, nearest = min(dists)
    natural = []
    for k, (_, v) in enumerate(vecs):
        natural.append(min(_dist(v, w) for j, (_, w) in enumerate(vecs) if j != k))
    med = float(np.median(natural))
    mad = max(float(np.median(np.abs(np.array(natural) - med))), 0.01)
    z = 0.6745 * (d_min - med) / mad
    risk = 0.0 if z <= 0 else min(1.0, z / (2 * z_limit))
    return Signal(round_score(risk), 0.5,
                  {"nearest_specimen": nearest, "distance": round_score(d_min),
                   "natural_median": round_score(med), "z": round_score(z),
                   "descriptor": DESCRIPTOR_VERSION, "n_specimens": len(vecs)})
