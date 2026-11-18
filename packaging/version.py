"""Numero de version d'Authentik : source unique = src/authentik/__init__.py (__version__).

    python packaging/version.py                       affiche la version
    python packaging/version.py suivante [patch|minor|major]   augmente et affiche la nouvelle
    python packaging/version.py fixer X.Y.Z           remet une version (retour arriere)
    python packaging/version.py version-info FICHIER  metadonnees Windows de Authentik.exe
    python packaging/version.py noter PLATEFORME      ajoute la version a HISTORIQUE_VERSIONS.txt

Les scripts de construction (build_ubuntu.sh, build_windows.ps1) augmentent la version a chaque
construction et la remettent en cas d'echec. Rappel (AGENTS.md 0 bis) : la version entre dans la
cle d'analyse ; une nouvelle version re-analyse un document deja vu et le rapport le signale.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = ROOT / "src" / "authentik" / "__init__.py"
HISTORY = ROOT / "packaging" / "HISTORIQUE_VERSIONS.txt"
PATTERN = re.compile(r'^__version__ = "(\d+)\.(\d+)\.(\d+)"$', re.M)

VERSION_INFO = """# Metadonnees de Authentik.exe (proprietes du fichier). GENERE par packaging/version.py.
VSVersionInfo(
  ffi=FixedFileInfo(filevers=({a}, {b}, {c}, 0), prodvers=({a}, {b}, {c}, 0), mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040C04B0', [
      StringStruct('CompanyName', 'Ministère de la Formation Professionnelle (MFP)'),
      StringStruct('FileDescription', 'Authentik - controle des certificats administratifs'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', 'Authentik'),
      StringStruct('LegalCopyright', '© Ministère de la Formation Professionnelle (MFP), RDC'),
      StringStruct('OriginalFilename', 'Authentik.exe'),
      StringStruct('ProductName', 'Authentik'),
      StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [0x040C, 1200])])
  ]
)
"""


def read() -> tuple[int, int, int]:
    m = PATTERN.search(INIT.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit(f"__version__ introuvable ou mal forme dans {INIT}")
    return int(m[1]), int(m[2]), int(m[3])


def write(v: tuple[int, int, int]) -> str:
    s = ".".join(map(str, v))
    text = INIT.read_text(encoding="utf-8")
    INIT.write_text(PATTERN.sub(f'__version__ = "{s}"', text, count=1), encoding="utf-8")
    return s


def next_version(v: tuple[int, int, int], part: str) -> tuple[int, int, int]:
    a, b, c = v
    return {"patch": (a, b, c + 1), "minor": (a, b + 1, 0), "major": (a + 1, 0, 0)}[part]


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "afficher"
    if cmd == "afficher":
        print(".".join(map(str, read())))
    elif cmd == "suivante":
        part = argv[1] if len(argv) > 1 else "patch"
        if part not in ("patch", "minor", "major"):
            raise SystemExit("partie inconnue : patch, minor ou major")
        print(write(next_version(read(), part)))
    elif cmd == "fixer":
        if len(argv) < 2 or not re.fullmatch(r"\d+\.\d+\.\d+", argv[1]):
            raise SystemExit("usage : fixer X.Y.Z")
        print(write(tuple(int(x) for x in argv[1].split("."))))
    elif cmd == "version-info":
        a, b, c = read()
        out = Path(argv[1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(VERSION_INFO.format(a=a, b=b, c=c, v=f"{a}.{b}.{c}"), encoding="utf-8")
        print(out)
    elif cmd == "noter":
        plateforme = argv[1] if len(argv) > 1 else "?"
        with open(HISTORY, "a", encoding="utf-8") as f:
            f.write(f"{'.'.join(map(str, read()))}\t{datetime.now():%Y-%m-%d %H:%M}\t{plateforme}\n")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
