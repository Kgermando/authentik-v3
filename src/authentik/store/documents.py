"""Copie des documents analyses dans documents_dir\\AAAA\\<sha256>.<extension>.

L'original de l'utilisateur n'est jamais deplace ni modifie. A la reouverture, l'empreinte
est reverifiee (`verify_document`) : si elle ne correspond plus, l'interface affiche une alerte.
Bibliotheque standard uniquement.
"""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path


def sha256_of(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class DocumentAltered(OSError):
    """La copie deja enregistree ne correspond plus a son empreinte : elle n'est PAS ecrasee
    (elle sert de preuve) et l'interface affiche une alerte d'integrite."""

    def __init__(self, path: Path):
        super().__init__(f"Copie enregistrée altérée : {path}")
        self.path = path


def store_document(src: str | Path, documents_dir: str | Path, year: int | None,
                   sha: str | None = None) -> tuple[str, Path]:
    """Copie `src` sans modification. Renvoie (sha256, chemin stocke). Idempotent.
    Leve DocumentAltered si une copie alteree existe deja (jamais ecrasee)."""
    src = Path(src)
    sha = sha or sha256_of(src)
    folder = Path(documents_dir) / (str(year) if year else "annee_inconnue")
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{sha}{src.suffix.lower()}"
    if dest.exists():
        if sha256_of(dest) == sha:
            return sha, dest
        raise DocumentAltered(dest)
    tmp = dest.with_name(dest.name + ".part")
    shutil.copyfile(src, tmp)
    if sha256_of(tmp) != sha:
        tmp.unlink(missing_ok=True)
        raise OSError(f"Copie altérée de {src} : empreinte différente")
    os.replace(tmp, dest)
    return sha, dest


def verify_document(path: str | Path, expected_sha: str) -> bool:
    """False si le fichier a disparu ou a ete modifie depuis l'analyse."""
    p = Path(path)
    return p.is_file() and sha256_of(p) == expected_sha
