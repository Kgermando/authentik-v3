"""Certificats de synthese (page A4 a 300 DPI, BGR). Ne prouvent rien sur de vrais documents."""
import cv2
import numpy as np

from synth import make_seal, photocopy, render

A4 = (3508, 2480)                       # hauteur, largeur a 300 DPI
SEAL_INK = np.array([150, 60, 40], np.float32)       # bleu (BGR)
SIG_INK = np.array([120, 45, 25], np.float32)
SEAL_POS = (300, 2550)                  # coin haut-gauche du sceau (x, y)
SIG_BOX = (1400, 2600, 700, 300)        # zone de la signature (x, y, l, h)


def paper(seed=0, tone=(228, 236, 240), grain=2.5):
    rng = np.random.default_rng(seed)
    page = np.empty(A4 + (3,), np.float32)
    page[:] = tone
    page += rng.normal(0, grain, A4)[..., None]
    return page


def add_text(page, year=2019, seed=0):
    lines = ["REPUBLIQUE DEMOCRATIQUE DU CONGO", "MINISTERE DE LA FORMATION PROFESSIONNELLE",
             "", "CERTIFICAT D'APTITUDE PROFESSIONNELLE", "",
             "Il est certifie que M. EXEMPLE Jean a suivi avec succes",
             "la formation de technicien en electricite.", "",
             f"Fait a Kinshasa, le 12/03/{year}"]
    img = np.full(A4, 255, np.uint8)
    for i, t in enumerate(lines):
        cv2.putText(img, t, (260, 500 + i * 160), cv2.FONT_HERSHEY_SIMPLEX, 2.2, 0, 5, cv2.LINE_AA)
    a = (255 - img).astype(np.float32)[..., None] / 255
    page[:] = page * (1 - a) + np.array([30, 30, 30], np.float32) * a


def ink_layer(page, gray, x, y, color, strength=1.0):
    """Depose une encre de couleur : `gray` = rendu niveaux de gris (255 = rien)."""
    h, w = gray.shape
    a = np.clip((235 - gray.astype(np.float32)) / 220, 0, 1)[..., None] * strength
    roi = page[y:y + h, x:x + w]
    roi[:] = roi * (1 - a) + color * a


def stamp_seal(page, seed, pos=SEAL_POS, jitter=False, gray=None):
    g = gray if gray is not None else render(make_seal(), seed, jitter=jitter)
    ink_layer(page, g, pos[0], pos[1], SEAL_INK)
    return g


def signature_gray(seed):
    rng = np.random.default_rng(seed + 1000)
    x0, y0, w, h = SIG_BOX
    img = np.full((h, w), 255, np.uint8)
    pts = []
    for i in range(9):
        pts.append((int(40 + i * 75 + rng.uniform(-15, 15)), int(150 + rng.uniform(-90, 90))))
    cv2.polylines(img, [np.array(pts, np.int32)], False, 0, 7, cv2.LINE_AA)
    cv2.ellipse(img, (160, 150), (110, 70), 0, 30, 330, 0, 6, cv2.LINE_AA)
    return render_strokes(img, rng)


def render_strokes(img, rng):
    ink = (255 - img).astype(np.float32) / 255
    mod = 0.65 + 0.35 * cv2.GaussianBlur(rng.random(img.shape).astype(np.float32), (0, 0), 5)
    return np.clip(235 - ink * mod * 220, 0, 255).astype(np.uint8)


def sign(page, seed, gray=None):
    g = gray if gray is not None else signature_gray(seed)
    x, y, _, _ = SIG_BOX
    ink_layer(page, g, x, y, SIG_INK)
    return g


def certificate(seed=0, year=2019, with_seal=True, with_sig=True, seal_gray=None,
                sig_gray=None, tone=(228, 236, 240)):
    p = paper(seed, tone)
    add_text(p, year, seed)
    if with_seal:
        stamp_seal(p, seed, gray=seal_gray)
    if with_sig:
        sign(p, seed, gray=sig_gray)
    return np.clip(p, 0, 255).astype(np.uint8)


def crop(page, x, y, w, h):
    return page[y:y + h, x:x + w].copy()


def paste(page, patch, x, y):
    """Montage numerique : colle un morceau d'un autre document (avec son papier)."""
    out = page.copy()
    h, w = patch.shape[:2]
    out[y:y + h, x:x + w] = patch
    return out


def reproduced_seal_gray(seed):
    """Sceau imprime puis rescanne (photocopie) au lieu d'un vrai tampon."""
    return photocopy(render(make_seal(), seed), seed=seed)
