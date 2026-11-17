"""Documents de reference (menu « References ») : certificats AUTHENTIQUES servant de comparaison.

Pour chaque document ajoute :
- copie sans modification dans documents_dir/references/AAAA/<sha256>.<ext> ;
- extraction du sceau et de la signature -> specimens (recadrages PNG sans perte, descripteur
  de forme, mesures de pression et d'integrite du papier, texte attendu du sceau) ;
- mesures de vieillissement (papier, encre) -> plage normale de l'annee recalculee aussitot.
Un sceau ou une signature copie depuis un de ces documents sera detecte par le controle `copy`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .analysis import page_facts, save_crop
from .analyzers.aging import MEASURES, build_profile
from .analyzers.reference import to_bytes
from .determinism import init_determinism
from .ingest import load_document
from .store import AppConfig, Database, sha256_of, store_document

Progress = Callable[[str, int], None]


def _noop(_s: str, _p: int) -> None:
    pass


@dataclass
class ReferenceReport:
    file_name: str
    year: int
    seal_found: bool
    signature_found: bool
    aging_measured: bool
    error: str | None = None

    def text(self) -> str:
        if self.error:
            return f"{self.file_name} : NON AJOUTÉ — {self.error}"
        parts = [("sceau" if self.seal_found else "sceau INTROUVABLE"),
                 ("signature" if self.signature_found else "signature introuvable"),
                 ("mesures papier/encre" if self.aging_measured else "mesures papier/encre impossibles")]
        return f"{self.file_name} ({self.year}) : " + ", ".join(parts)


def references_dir(cfg: AppConfig) -> Path:
    return cfg.documents_dir / "references"


def add_reference_document(path: str | Path, year: int, owner: str | None, seal_text: str | None,
                           cfg: AppConfig, db: Database) -> ReferenceReport:
    init_determinism()
    path = Path(path)
    try:
        doc = load_document(path)
        sha = sha256_of(path)
        _, stored = store_document(path, references_dir(cfg), year, sha)
        facts = page_facts(doc.pages[0], doc.dpi[0])
        specimens = []
        for kind, f in sorted(facts.elements.items()):
            crop = save_crop(f.color, references_dir(cfg) / "crops" / f"{sha}_{kind}.png")
            specimens.append({"kind": kind, "image_path": str(crop), "embedding": to_bytes(f.embedding),
                              "expected_text": (seal_text or None) if kind == "seal" else None,
                              "features": f.features()})
        db.add_reference(year, sha, str(stored), owner, facts.aging, specimens,
                         file_name=path.name)
    except Exception as e:                           # noqa: BLE001 - rapporte, n'arrete pas le lot
        return ReferenceReport(path.name, year, False, False, False, str(e))
    recompute_year_profile(db, year)
    return ReferenceReport(path.name, year, "seal" in facts.elements,
                           "signature" in facts.elements, facts.aging is not None)


def add_reference_documents(paths: list[str | Path], year: int, owner: str | None,
                            seal_text: str | None, cfg: AppConfig, db: Database,
                            progress: Progress = _noop) -> list[ReferenceReport]:
    out = []
    paths = sorted(Path(p) for p in paths)              # ordre fixe
    for i, p in enumerate(paths):
        progress(f"Référence {i + 1}/{len(paths)} : {p.name}", int(100 * i / max(1, len(paths))))
        out.append(add_reference_document(p, year, owner, seal_text, cfg, db))
    progress("Terminé", 100)
    return out


def recompute_year_profile(db: Database, year: int) -> dict:
    """Plage normale de l'annee (mediane, MAD avec plancher, n) a partir des references."""
    ms = db.reference_measures(year)
    if len(ms) < 2:
        db.set_year_profile(year, {})
        return {}
    prof = {}
    for m in MEASURES:
        med, mad = build_profile([x[m] for x in ms])
        prof[m] = (med, mad, len(ms))
    db.set_year_profile(year, prof)
    return prof


def remove_reference_document(sha256: str, year: int, db: Database) -> None:
    db.remove_reference(sha256)
    recompute_year_profile(db, year)
