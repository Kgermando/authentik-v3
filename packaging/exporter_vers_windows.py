"""Cree l'archive a copier sur le poste Windows : projet + kit (paquets Python, outils).

    python packaging/exporter_vers_windows.py            -> dist/authentik-windows-kit.zip

Exclut ce qui est propre a ce poste (environnements Python, constructions, caches).
Les fichiers deja compresses (.whl, .exe) sont stockes sans recompression.
"""
from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INCLUDE = ["src", "tests", "packaging", "windows_kit", "pyproject.toml", "requirements.txt",
           "AGENTS.md", "GUIDE.md"]
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".venv", ".venv-build", "build", "dist", "vendor",
                "authentik.egg-info"}
STORED = {".whl", ".exe", ".png", ".ico", ".zip"}


def files():
    for name in INCLUDE:
        p = ROOT / name
        if p.is_file():
            yield p
            continue
        for f in sorted(p.rglob("*")):
            if f.is_file() and not (set(f.relative_to(ROOT).parts) & EXCLUDE_DIRS):
                yield f


def main() -> int:
    out = ROOT / "dist" / "authentik-windows-kit.zip"
    out.parent.mkdir(exist_ok=True)
    wheels = list((ROOT / "windows_kit" / "wheels").glob("*.whl"))
    if not wheels:
        print("windows_kit/wheels est vide : telecharger les paquets d'abord.", file=sys.stderr)
        return 1
    n = 0
    with zipfile.ZipFile(out, "w") as z:
        for f in files():
            arc = Path("authentik") / f.relative_to(ROOT)
            mode = zipfile.ZIP_STORED if f.suffix.lower() in STORED else zipfile.ZIP_DEFLATED
            z.write(f, arc.as_posix(), compress_type=mode)
            n += 1
    h = hashlib.sha256(out.read_bytes()).hexdigest()
    (out.parent / (out.name + ".sha256")).write_text(f"{h}  {out.name}\n", encoding="utf-8")
    print(f"{out} : {n} fichiers, {out.stat().st_size / 1e6:.0f} Mo, {len(wheels)} paquets Python")
    print(f"SHA-256 : {h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
