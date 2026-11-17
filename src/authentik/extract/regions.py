"""Extraction du sceau, de la signature et des masques papier / texte (page BGR a 300 DPI).

Principe :
- encre de couleur (sceau, signature) : pixels satures (HSV), le texte imprime noir ne l'est pas ;
- sceau : composante d'encre de couleur a peu pres ronde dont l'encre se concentre sur un anneau
  exterieur (bordure du tampon) ; la position est affinee par cv2.HoughCircles ;
- signature : plus grand groupe d'encre de couleur hors du sceau, plus large que haut ;
- repli si le sceau est noir : meme recherche sur l'encre sombre (confiance plus faible).

Reglages a 300 DPI, mis a l'echelle si la resolution differe. Valide sur images de synthese
UNIQUEMENT : a verifier et ajuster sur de vrais certificats.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import cv2
import numpy as np

from ..config import SETTINGS

SAT_MIN = 60          # saturation minimale d'une encre de couleur
VAL_MAX = 225         # au-dela : trop clair pour etre de l'encre
DARK_MAX = 110        # encre sombre (texte imprime, encre noire)


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int

    def rect(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.w, self.h

    def padded(self, pad: int, shape) -> "Box":
        H, W = shape[:2]
        x0, y0 = max(0, self.x - pad), max(0, self.y - pad)
        x1, y1 = min(W, self.x + self.w + pad), min(H, self.y + self.h + pad)
        return Box(x0, y0, x1 - x0, y1 - y0)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Element:
    kind: str                 # "seal" | "signature"
    box: Box
    confidence: float         # fiabilite de la localisation (0-1)
    colored: bool             # encre de couleur (True) ou sombre (False)
    circle: tuple[int, int, int] | None = None     # sceau : centre x, y, rayon


@dataclass
class PageRegions:
    seal: Element | None
    signature: Element | None
    color_mask: np.ndarray    # encre de couleur
    dark_mask: np.ndarray     # encre sombre (texte imprime)
    scale: float


def ink_masks(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    s, v = hsv[..., 1], hsv[..., 2]
    color = (s >= SAT_MIN) & (v <= VAL_MAX)
    dark = (v <= DARK_MAX) & ~color
    k = np.ones((3, 3), np.uint8)
    color = cv2.morphologyEx(color.astype(np.uint8), cv2.MORPH_OPEN, k) > 0
    return color, dark


def ink_gray(img: np.ndarray) -> np.ndarray:
    """Niveaux de gris qui fait ressortir toute encre (minimum des canaux) : bleu, rouge, noir."""
    return img.min(axis=2)


def _ring_score(mask: np.ndarray, cx: float, cy: float, r: float) -> float:
    """Part de l'encre situee sur l'anneau exterieur [0.82 r, 1.05 r] (bordure d'un tampon)."""
    ys, xs = np.nonzero(mask)
    if len(xs) == 0 or r <= 0:
        return 0.0
    d = np.hypot(xs - cx, ys - cy) / r
    return float(((d >= 0.82) & (d <= 1.05)).mean())


def _find_seal(mask: np.ndarray, scale: float, colored: bool) -> Element | None:
    rmin, rmax = 100 * scale, 480 * scale
    merged = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE,
                              np.ones((int(25 * scale) | 1,) * 2, np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(merged, connectivity=8)
    best = None
    for i in range(1, n):                                   # ordre fixe (etiquettes OpenCV)
        x, y, w, h, area = (int(v) for v in stats[i])
        if not (2 * rmin <= max(w, h) <= 2 * rmax + 20) or not (0.75 <= w / max(h, 1) <= 1.33):
            continue
        sub = mask[y:y + h, x:x + w] & (lab[y:y + h, x:x + w] == i)
        cx, cy, r = w / 2, h / 2, max(w, h) / 2
        score = _ring_score(sub, cx, cy, r)
        if score < 0.18 or sub.sum() < 2000 * scale * scale:
            continue
        if best is None or score > best[0]:
            best = (score, x, y, w, h, sub)
    if best is None:
        return None
    score, x, y, w, h, sub = best
    cx, cy, _ = _refine_circle(sub, scale) or (w / 2, h / 2, max(w, h) / 2)
    ys, xs = np.nonzero(sub)
    r = float(np.percentile(np.hypot(xs - cx, ys - cy), 99))   # bordure exterieure du tampon
    gx, gy, R = int(round(x + cx)), int(round(y + cy)), int(round(r))
    conf = min(1.0, score / 0.35) * (1.0 if colored else 0.6)
    box = Box(max(0, gx - R), max(0, gy - R), 2 * R, 2 * R)
    return Element("seal", box, round(conf, 4), colored, (gx, gy, R))


def _refine_circle(sub: np.ndarray, scale: float):
    img = cv2.GaussianBlur(sub.astype(np.uint8) * 255, (0, 0), 3)
    h, w = img.shape
    circles = cv2.HoughCircles(img, cv2.HOUGH_GRADIENT, dp=2, minDist=max(h, w),
                               param1=100, param2=40, minRadius=int(0.35 * min(h, w)),
                               maxRadius=int(0.6 * max(h, w)) + 2)
    if circles is None:
        return None
    cx, cy, r = (float(v) for v in circles[0, 0])
    return cx, cy, r


def _find_signature(mask: np.ndarray, seal: Element | None, scale: float,
                    colored: bool) -> Element | None:
    m = mask.copy()
    if seal is not None and seal.circle is not None:
        cx, cy, r = seal.circle
        cv2.circle(m.view(np.uint8), (cx, cy), int(r * 1.08), 0, -1)
    k = int(35 * scale) | 1
    merged = cv2.dilate(m.astype(np.uint8), np.ones((k, k), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(merged, connectivity=8)
    best = None
    for i in range(1, n):
        x, y, w, h, _ = (int(v) for v in stats[i])
        if w < 150 * scale or h < 40 * scale or w > 1600 * scale or h > 900 * scale:
            continue
        ink = int((m[y:y + h, x:x + w] & (lab[y:y + h, x:x + w] == i)).sum())
        if ink < 1200 * scale * scale:
            continue
        if best is None or ink > best[0]:
            best = (ink, x, y, w, h)
    if best is None:
        return None
    ink, x, y, w, h = (int(v) for v in best)
    pad = k // 2                                            # retire la dilatation
    box = Box(x + pad, y + pad, max(1, w - 2 * pad), max(1, h - 2 * pad))
    conf = (0.8 if colored else 0.4) * min(1.0, ink / (4000 * scale * scale))
    return Element("signature", box, round(conf, 4), colored)


def find_regions(img: np.ndarray, dpi: float | None = None) -> PageRegions:
    """Localise sceau et signature. Meme image => meme resultat (aucun hasard)."""
    scale = (dpi or SETTINGS.scan_dpi) / SETTINGS.scan_dpi
    color, dark = ink_masks(img)
    seal = _find_seal(color, scale, True) or _find_seal(dark, scale, False)
    sig = _find_signature(color, seal, scale, True)
    return PageRegions(seal, sig, color, dark, scale)


def element_mask(regions: PageRegions, el: Element, shape) -> np.ndarray:
    """Masque de l'encre de l'element (pour les mesures de vieillissement)."""
    src = regions.color_mask if el.colored else regions.dark_mask
    m = np.zeros(shape[:2], bool)
    if el.circle is not None:
        cx, cy, r = el.circle
        disk = np.zeros(shape[:2], np.uint8)
        cv2.circle(disk, (cx, cy), int(r * 1.03), 1, -1)
        m = src & (disk > 0)
    else:
        b = el.box
        m[b.y:b.y + b.h, b.x:b.x + b.w] = src[b.y:b.y + b.h, b.x:b.x + b.w]
    return m


def paper_text_masks(img: np.ndarray, regions: PageRegions) -> tuple[np.ndarray, np.ndarray]:
    """Papier vierge (loin de toute encre, hors bords du scan) et texte imprime."""
    any_ink = (regions.color_mask | regions.dark_mask).astype(np.uint8)
    k = int(31 * regions.scale) | 1
    near = cv2.dilate(any_ink, np.ones((k, k), np.uint8)) > 0
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    bright = hsv[..., 2] >= 150
    paper = bright & ~near
    H, W = img.shape[:2]
    border = int(0.03 * min(H, W))
    paper[:border], paper[-border:], paper[:, :border], paper[:, -border:] = False, False, False, False
    text = regions.dark_mask.copy()
    if regions.seal is not None:
        text &= ~element_mask(regions, regions.seal, img.shape)
    return paper, text


def crop_gray(img: np.ndarray, el: Element, pad: int = 24) -> np.ndarray:
    b = el.box.padded(pad, img.shape)
    return np.ascontiguousarray(ink_gray(img[b.y:b.y + b.h, b.x:b.x + b.w]))


def crop_color(img: np.ndarray, el: Element, pad: int = 24) -> np.ndarray:
    b = el.box.padded(pad, img.shape)
    return np.ascontiguousarray(img[b.y:b.y + b.h, b.x:b.x + b.w])
