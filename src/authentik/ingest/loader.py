"""Chargement d'un document (PDF, PNG, JPEG, TIFF) en pages couleur BGR (uint8).

Reglages fixes (AGENTS.md 0 bis, regle 4) : PDF rasterise a 300 DPI, en couleur, sans aucune
« amelioration » d'image. Les images sont lues telles quelles (seule l'orientation EXIF est
appliquee, car c'est une information du fichier, pas un traitement du contenu).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageOps, ImageSequence

from ..config import SETTINGS

PDF_EXT = {".pdf"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
SUPPORTED_EXT = PDF_EXT | IMAGE_EXT
MAX_PAGES = 20
MAX_PIXELS = 120_000_000          # ~ A3 a 600 DPI ; au-dela : fichier refuse


class IngestError(Exception):
    """Fichier illisible ou non pris en charge (message affiche tel quel a l'utilisateur)."""


@dataclass
class LoadedDocument:
    path: Path
    kind: str                                   # "pdf" ou "image"
    pages: list[np.ndarray]                     # BGR uint8
    dpi: list[float | None]                     # resolution de chaque page (None si inconnue)
    warnings: list[str] = field(default_factory=list)


def load_document(path: str | Path, dpi: int = SETTINGS.scan_dpi,
                  assumed_dpi: float | None = None) -> LoadedDocument:
    """`assumed_dpi` : resolution connue par ailleurs (scan aux reglages imposes) quand le
    fichier ne l'indique pas."""
    path = Path(path)
    ext = path.suffix.lower()
    if not path.is_file():
        raise IngestError(f"Fichier introuvable : {path}")
    if ext not in SUPPORTED_EXT:
        raise IngestError(f"Format non pris en charge ({ext or 'sans extension'}). "
                          "Formats acceptés : PDF, PNG, JPEG, TIFF.")
    doc = _load_pdf(path, dpi) if ext in PDF_EXT else _load_image(path)
    if not doc.pages:
        raise IngestError("Le document ne contient aucune page.")
    if assumed_dpi is not None:
        doc.dpi = [d if d is not None else float(assumed_dpi) for d in doc.dpi]
    for i, d in enumerate(doc.dpi, 1):
        if d is not None and abs(d - dpi) > 1:
            doc.warnings.append(
                f"Page {i} : résolution {d:.0f} DPI au lieu de {dpi}. "
                "Les mesures de vieillissement sont moins fiables.")
        elif d is None and doc.kind == "image":
            doc.warnings.append(f"Page {i} : résolution inconnue (attendue : {dpi} DPI).")
    if ext in {".jpg", ".jpeg"}:
        doc.warnings.append("Fichier JPEG : la compression peut masquer des traces de montage.")
    return doc


def _load_pdf(path: Path, dpi: int) -> LoadedDocument:
    try:
        pdf = pymupdf.open(path)
    except Exception as e:                      # PyMuPDF leve plusieurs types d'erreurs
        raise IngestError(f"PDF illisible : {e}") from e
    with pdf:
        if pdf.needs_pass:
            raise IngestError("PDF protégé par mot de passe.")
        if pdf.page_count > MAX_PAGES:
            raise IngestError(f"PDF de {pdf.page_count} pages (maximum {MAX_PAGES}).")
        pages = []
        for page in pdf:
            w_in, h_in = page.rect.width / 72, page.rect.height / 72
            if w_in * h_in * dpi * dpi > MAX_PIXELS:
                raise IngestError("Page PDF trop grande pour être analysée.")
            pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
            rgb = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
            pages.append(np.ascontiguousarray(rgb[..., ::-1]))      # RGB -> BGR
    return LoadedDocument(path, "pdf", pages, [float(dpi)] * len(pages))


def _load_image(path: Path) -> LoadedDocument:
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        img = Image.open(path)
    except Image.DecompressionBombError as e:
        raise IngestError("Image trop grande pour être analysée.") from e
    except Exception as e:
        raise IngestError(f"Image illisible : {e}") from e
    pages, dpis = [], []
    with img:
        for frame in ImageSequence.Iterator(img):
            if len(pages) >= MAX_PAGES:
                raise IngestError(f"Fichier de plus de {MAX_PAGES} pages.")
            dpi = frame.info.get("dpi")
            fr = ImageOps.exif_transpose(frame).convert("RGB")
            pages.append(np.ascontiguousarray(np.asarray(fr)[..., ::-1]))
            dpis.append(float(dpi[0]) if dpi and dpi[0] else None)
    return LoadedDocument(path, "image", pages, dpis)
