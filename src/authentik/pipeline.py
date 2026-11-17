"""Deroulement d'une analyse : chargement -> annee -> copie du document -> memoisation -> controles.

Utilise par l'interface (dans un fil QThreadPool) et par `python -m authentik.eval`.
Aucune dependance a Qt.

Chaque resultat est enregistre (ajout seulement) avec ses signaux et les empreintes du sceau et
de la signature, qui serviront a detecter une copie dans les documents analyses ensuite.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import __version__
from .config import SETTINGS, Settings
from .determinism import analysis_key, init_determinism
from .ingest import LoadedDocument, YearReading, load_document, read_year
from .analysis import analyze_page, references_version, save_crop
from .analyzers.reference import DESCRIPTOR_VERSION
from .decision import decide, load_fusion, model_hash
from .store import AnalysisRecord, AppConfig, Database, sha256_of, store_document, verify_document
from .store.documents import DocumentAltered

Progress = Callable[[str, int], None]          # (etape affichee, pourcentage 0-100)

# Lignes de la page de resultats (AGENTS.md 2 et 8), dans l'ordre d'affichage.
ROWS = ("Sceau", "Signature", "Vieillissement", "Pression de l'encre")


def _noop(_step: str, _pct: int) -> None:
    pass


@dataclass
class Prepared:
    source: Path
    sha256: str
    doc: LoadedDocument
    year_reading: YearReading
    from_scan: bool = False


@dataclass
class Region:
    """Cadre dessine sur l'image (colonne 1)."""
    row: str                       # nom de la ligne associee (« Sceau », « Signature »)
    page: int
    rect: tuple[int, int, int, int]  # x, y, largeur, hauteur en pixels
    color: str                     # "green" | "orange" | "red"


@dataclass
class RowResult:
    name: str
    word: str                      # « Conforme », « Introuvable », « Copie »...
    color: str                     # "green" | "orange" | "red"
    reason: str = ""


@dataclass
class Outcome:
    prepared: Prepared
    year: int
    stored_path: Path
    analysis_key: str
    verdict: str | None            # None : pas de verdict (controles absents)
    score: float | None
    summary: str
    rows: list[RowResult] = field(default_factory=list)
    hidden: dict[str, str] = field(default_factory=dict)   # ligne masquee -> motif
    regions: list[Region] = field(default_factory=list)
    memoized: bool = False         # True : resultat enregistre renvoye sans recalcul
    integrity_ok: bool = True
    details: dict = field(default_factory=dict)            # tout le reste pour « En savoir plus »


def prepare(path: str | Path, from_scan: bool = False, progress: Progress = _noop) -> Prepared:
    path = Path(path)
    progress("Lecture du document", 10)
    doc = load_document(path, assumed_dpi=SETTINGS.scan_dpi if from_scan else None)
    progress("Calcul de l'empreinte du fichier", 40)
    sha = sha256_of(path)
    progress("Lecture de l'année (OCR)", 60)
    reading = read_year(doc.pages[0])
    progress("Pret", 100)
    return Prepared(path, sha, doc, reading, from_scan)


def model_hashes(cfg: AppConfig) -> dict[str, str]:
    """Empreintes de tout ce qui « decide » : descripteur de forme et modele de fusion."""
    return {"descriptor": DESCRIPTOR_VERSION, "fusion": model_hash(cfg)}


def make_key(prepared: Prepared, year: int, db: Database, cfg: AppConfig | None = None,
             settings: Settings = SETTINGS) -> str:
    params = settings.as_dict() | {"year": year}
    models = model_hashes(cfg) if cfg is not None else {"descriptor": DESCRIPTOR_VERSION}
    return analysis_key(prepared.sha256, __version__, models, references_version(db), params)


def run_analysis(prepared: Prepared, year: int, cfg: AppConfig, db: Database,
                 progress: Progress = _noop, settings: Settings = SETTINGS) -> Outcome:
    init_determinism()
    progress("Enregistrement du document", 5)
    if sha256_of(prepared.source) != prepared.sha256:
        raise RuntimeError("Le fichier a changé depuis son ouverture : recommencer l'import.")
    try:
        sha, stored = store_document(prepared.source, cfg.documents_dir, year, prepared.sha256)
        integrity_ok = True
    except DocumentAltered as e:           # copie alteree conservee comme preuve, pas ecrasee
        sha, stored, integrity_ok = prepared.sha256, e.path, False

    progress("Recherche d'un résultat déjà enregistré", 10)
    key = make_key(prepared, year, db, cfg, settings)
    saved = db.find_analysis(key)
    if saved is not None:
        progress("Résultat déjà enregistré", 100)
        return _from_saved(prepared, year, stored, key, saved)

    progress("Localisation du sceau et de la signature, contrôles", 25)
    history = db.analyses_for_file(sha)
    pa = analyze_page(prepared.doc.pages[0], year, db, sha, prepared.doc.dpi[0], settings)
    progress("Décision", 80)
    d = decide(pa.signals, load_fusion(cfg), settings)
    fingerprints = []
    for kind, f in sorted(pa.facts.elements.items()):
        crop = save_crop(f.color, cfg.crops_dir / f"{sha}_{kind}.png")
        fingerprints.append((kind, f.phash, str(crop)))
    changed = _what_changed(history, key)
    details = {"evidence": pa.evidence, "calibrated": d.calibrated,
               "signals": {k: {"risk": s.risk, "confidence": s.confidence, "evidence": s.evidence}
                           for k, s in sorted(pa.signals.items()) if s is not None},
               "previous_analyses": [{"created_at": h["created_at"], "verdict": h["verdict"],
                                      "software_version": h["software_version"]} for h in history],
               "changed_since_previous": changed}
    result = {"summary": d.summary, "rows": pa.rows, "hidden": pa.hidden,
              "regions": pa.regions, "details": details}
    progress("Enregistrement du résultat", 90)
    rec = AnalysisRecord(key, sha, prepared.source.name, str(stored), year, d.score, d.verdict,
                         __version__, result)
    aid, _ = db.save_analysis(rec, pa.signals, fingerprints)
    progress("Terminé", 100)
    return Outcome(
        prepared=prepared, year=year, stored_path=stored, analysis_key=key,
        verdict=d.verdict, score=d.score, summary=d.summary,
        rows=[RowResult(**r) for r in pa.rows], hidden=pa.hidden,
        regions=[Region(r["row"], r["page"], tuple(r["rect"]), r["color"]) for r in pa.regions],
        integrity_ok=integrity_ok, details=details | {"analysis_id": aid, "reviews": []})


def _what_changed(history: list[dict], key: str) -> str | None:
    """Pourquoi ce document est re-analyse (AGENTS.md 0 bis, regle 5)."""
    if not history:
        return None
    last = history[-1]
    if last["software_version"] != __version__:
        return f"nouvelle version du logiciel ({last['software_version']} -> {__version__})"
    return ("références, modèle de décision ou réglages modifiés depuis l'analyse du "
            f"{last['created_at'][:10]}")


def _from_saved(prepared: Prepared, year: int, stored: Path, key: str, saved: dict) -> Outcome:
    r = saved["result"]
    return Outcome(
        prepared=prepared, year=year, stored_path=Path(saved["stored_path"]), analysis_key=key,
        verdict=saved["verdict"], score=saved["score"], summary=r.get("summary", ""),
        rows=[RowResult(**x) for x in r.get("rows", [])],
        hidden=r.get("hidden", {}),
        regions=[Region(x["row"], x["page"], tuple(x["rect"]), x["color"])
                 for x in r.get("regions", [])],
        memoized=True,
        integrity_ok=verify_document(saved["stored_path"], saved["file_sha256"]),
        details=r.get("details", {}) | {"reviews": saved["reviews"], "analysis_id": saved["id"],
                                         "analysed_at": saved["created_at"]})
