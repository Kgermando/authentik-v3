"""Scan par le pilote SANE (Linux), via le programme `scanimage` (paquet sane-utils).

Couvre les scanners USB et reseau qui n'ont pas eSCL mais ont un pilote SANE (Epson, Canon,
Brother, HP via hplip...). Reglages imposes : 300 DPI, couleur, vitre si elle existe ;
aucune option d'amelioration n'est envoyee.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..config import SETTINGS
from .base import ScannerInfo
from .escl import ScanError

Runner = Callable[..., subprocess.CompletedProcess]
EXCLUDED_PREFIXES = ("v4l:", "test")                  # webcams et peripherique de test


def available() -> bool:
    return shutil.which("scanimage") is not None


def _run(args: list[str], run: Runner, timeout: float) -> str:
    try:
        r = run(["scanimage", *args], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as e:
        raise ScanError("Le programme scanimage (SANE) n'est pas installé.") from e
    except subprocess.TimeoutExpired as e:
        raise ScanError("Le scanner ne répond plus (délai dépassé).") from e
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip().splitlines()
        raise ScanError("Erreur du pilote SANE : " + (msg[-1] if msg else f"code {r.returncode}"))
    return r.stdout


def parse_devices(text: str) -> list[ScannerInfo]:
    out = []
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) != 4:
            continue
        dev, vendor, model, kind = (p.strip() for p in parts)
        if dev.startswith(EXCLUDED_PREFIXES) or re.search(r"camera|video|webcam", kind + model, re.I):
            continue
        name = " ".join(x for x in (vendor, model) if x and x.lower() != "noname") or dev
        out.append(ScannerInfo(name, "sane", dev, model, "pilote"))
    return sorted(out, key=lambda s: (s.name.lower(), s.address))


def list_devices(run: Runner = subprocess.run) -> list[ScannerInfo]:
    if not available() and run is subprocess.run:
        return []
    try:
        return parse_devices(_run(["-f", "%d|%v|%m|%t%n"], run, timeout=30))
    except ScanError:
        return []


def _option(text: str, name: str) -> str | None:
    m = re.search(rf"^\s+--{name}\s+(.+?)\s*(?:\[[^\]]*\])?\s*$", text, re.M)
    return m.group(1) if m else None


def parse_options(text: str) -> dict:
    """Extrait des options de `scanimage -A` : modes, resolutions, sources."""
    def values(name):
        v = _option(text, name)
        return [x.strip() for x in v.split("|")] if v else []
    res_raw = _option(text, "resolution") or ""
    res_raw = re.sub(r"\(.*?\)", "", res_raw).replace("dpi", "").strip()
    discrete, ranges = [], []
    for part in res_raw.split("|"):
        part = part.strip()
        if ".." in part:
            lo, hi = part.split("..", 1)
            try:
                ranges.append((int(float(lo)), int(float(hi))))
            except ValueError:
                pass
        elif part.replace(".", "", 1).isdigit():
            discrete.append(int(float(part)))
    return {"modes": values("mode"), "sources": values("source"),
            "resolutions": discrete, "resolution_ranges": ranges}


def choose_settings(opts: dict, dpi: int = SETTINGS.scan_dpi) -> list[str]:
    """Arguments scanimage pour les reglages imposes, ou ScanError si impossible."""
    colors = [m for m in opts["modes"] if re.search(r"colou?r|24", m, re.I)
              and not re.search(r"gray|grey|lineart", m, re.I)]
    if opts["modes"] and not colors:
        raise ScanError(f"Ce scanner ne propose pas la couleur (modes : {opts['modes']}).")
    ok_dpi = (not opts["resolutions"] and not opts["resolution_ranges"]) or dpi in opts["resolutions"] \
        or any(lo <= dpi <= hi for lo, hi in opts["resolution_ranges"])
    if not ok_dpi:
        raise ScanError(f"Ce scanner ne propose pas {dpi} DPI.")
    args = ["--resolution", str(dpi)]
    if colors:
        args += ["--mode", colors[0]]
    flatbed = [s for s in opts["sources"] if re.search(r"flatbed|platen|vitre", s, re.I)]
    if flatbed:
        args += ["--source", flatbed[0]]
    return args


def scan(device: str, folder: str | Path, run: Runner = subprocess.run) -> Path:
    opts = parse_options(_run(["-d", device, "-A"], run, timeout=60))
    args = choose_settings(opts)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / ("scan_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".png")
    _run(["-d", device, *args, "--format=png", "-o", str(out)], run, timeout=300)
    if not out.exists() or out.stat().st_size == 0:
        raise ScanError("Le pilote SANE n'a produit aucune image.")
    return out
