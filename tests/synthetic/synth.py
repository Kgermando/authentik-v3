"""Images de synthese pour les tests. Ne prouvent rien sur de vrais documents."""
import cv2
import numpy as np


def make_seal(size=500):
    """Sceau a environ 300 DPI (traits epais de plusieurs dizaines de pixels)."""
    img = np.full((size, size), 255, np.uint8)
    c = size // 2
    cv2.circle(img, (c, c), 220, 0, 14)
    cv2.circle(img, (c, c), 185, 0, 8)
    cv2.putText(img, "MINISTERE", (88, 225), cv2.FONT_HERSHEY_SIMPLEX, 1.8, 0, 9)
    cv2.putText(img, "FORMATION", (88, 295), cv2.FONT_HERSHEY_SIMPLEX, 1.8, 0, 9)
    cv2.putText(img, "PROFESSION.", (118, 365), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 0, 7)
    return img


def render(seal, seed, jitter=False):
    """Simule une pose de tampon : pression irreguliere de l'encre + grain du papier."""
    rng = np.random.default_rng(seed)
    h, w = seal.shape
    ink = (255 - seal).astype(np.float32) / 255
    if jitter:  # un tampon reapose bouge un peu
        m = cv2.getRotationMatrix2D((w / 2, h / 2), rng.uniform(-2, 2), 1.0)
        m[:, 2] += rng.uniform(-3, 3, 2)
        ink = cv2.warpAffine(ink, m, (w, h))
    smooth = cv2.GaussianBlur(rng.random((h, w)).astype(np.float32), (0, 0), 6)
    smooth = (smooth - smooth.min()) / (smooth.max() - smooth.min())
    mod = 0.55 + 0.45 * smooth
    speck = np.where(rng.random((h, w)) > 0.97, 0.5, 1.0)
    paper = 235 + rng.normal(0, 3, (h, w))
    out = paper - ink * mod * speck * 220
    return np.clip(out, 0, 255).astype(np.uint8)


def paste_copy(crop, angle=3.0, scale=0.95):
    """Copie numerique : reechantillonnage puis compression JPEG."""
    h, w = crop.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, scale)
    out = cv2.warpAffine(crop, m, (w, h), borderValue=235)
    ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 75])
    return cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)


def photocopy(img, level=128, ink=30, paper=245, seed=0):
    """Reproduction imprimee : binarisation, aplats uniformes, bords nets, puis re-scan."""
    rng = np.random.default_rng(seed)
    out = np.where(img < level, ink, paper).astype(np.float32)
    out = cv2.GaussianBlur(out, (0, 0), 0.6)
    out += rng.normal(0, 2, out.shape)
    return np.clip(out, 0, 255).astype(np.uint8)


def softened(img, sigma=1.2):
    """Encre qui diffuse dans les fibres : bords plus doux."""
    return cv2.GaussianBlur(img, (0, 0), sigma)
