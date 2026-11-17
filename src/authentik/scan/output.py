"""Enregistre les pages recues du scanner dans UN fichier, ensuite traite comme un import.

Une page : octets du scanner ecrits tels quels. Plusieurs pages : PDF fusionnes, ou images
regroupees en un TIFF multipage sans perte (LZW) a 300 DPI.
"""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import pymupdf
from PIL import Image

from ..config import SETTINGS
from .escl import ScanError, ScannedPage


def save_scan(pages: list[ScannedPage], folder: str | Path) -> Path:
    if not pages:
        raise ScanError("Aucune page à enregistrer.")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stem = "scan_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    if len(pages) == 1:
        out = folder / (stem + pages[0].extension)
        out.write_bytes(pages[0].data)
        return out
    if all(p.content_type == "application/pdf" for p in pages):
        merged = pymupdf.open()
        for p in pages:
            with pymupdf.open(stream=p.data, filetype="pdf") as src:
                merged.insert_pdf(src)
        out = folder / (stem + ".pdf")
        merged.save(out)
        merged.close()
        return out
    if any(p.content_type == "application/pdf" for p in pages):
        raise ScanError("Pages de formats différents reçues du scanner.")
    images = [Image.open(io.BytesIO(p.data)).convert("RGB") for p in pages]
    out = folder / (stem + ".tiff")
    dpi = (SETTINGS.scan_dpi, SETTINGS.scan_dpi)
    images[0].save(out, save_all=True, append_images=images[1:], compression="tiff_lzw", dpi=dpi)
    return out
