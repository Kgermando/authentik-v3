"""Point d'entree unique du scan : liste des scanners et numerisation, quel que soit l'acces.

Ordre de la liste (fixe) : scanners enregistres, puis reseau local (mDNS), puis pilotes du poste.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

from . import sane, wia
from .base import ScannerInfo
from .discovery import discover_scanners
from .escl import EsclClient, ScanError
from .output import save_scan

Progress = Callable[[str, int], None]


def saved_scanners(saved: list[tuple[str, str]] | tuple) -> list[ScannerInfo]:
    """Scanners memorises dans authentik.ini : [(nom, URL eSCL)]."""
    return [ScannerInfo(name, "escl", url, "", "enregistré") for name, url in saved]


def local_drivers() -> list[ScannerInfo]:
    if sys.platform == "win32":
        return wia.list_devices()
    return sane.list_devices()


def find_scanners(saved=(), timeout: float = 4.0,
                  discover: Callable[[float], list[ScannerInfo]] = discover_scanners,
                  drivers: Callable[[], list[ScannerInfo]] = local_drivers) -> list[ScannerInfo]:
    groups = [saved_scanners(saved)]
    for fn, args in ((discover, (timeout,)), (drivers, ())):
        try:
            groups.append(fn(*args))
        except Exception:                              # noqa: BLE001 - une source en panne
            groups.append([])                          # n'empeche pas les autres
    out, seen = [], set()
    for group in groups:
        for s in group:
            if s.key not in seen:
                seen.add(s.key)
                out.append(s)
    return out


def scan_to_file(scanner: ScannerInfo, folder: str | Path, progress: Progress) -> Path:
    progress(f"Connexion à {scanner.name}", 10)
    if scanner.backend == "escl":
        with EsclClient(scanner.address) as client:
            progress("Numérisation en cours (300 DPI, couleur)", 30)
            pages = client.scan()
        progress("Enregistrement du scan", 90)
        return save_scan(pages, folder)
    progress("Numérisation en cours (300 DPI, couleur)", 30)
    if scanner.backend == "sane":
        return sane.scan(scanner.address, folder)
    if scanner.backend == "wia":
        return wia.scan(scanner.address, folder)
    raise ScanError(f"Type de scanner inconnu : {scanner.backend}")
