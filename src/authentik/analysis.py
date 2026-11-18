"""Analyse d'une page : extraction, controles contre les references, lignes de resultat, verdict.

Toutes les listes de comparaison sont parcourues dans un ORDRE FIXE (AGENTS.md 0 bis, regle 2)
et les scores sont arrondis avant toute comparaison a un seuil (regle 3).
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import imagehash
import numpy as np
from PIL import Image

from .analyzers import aging as aging_mod
from .analyzers.base import Signal
from .analyzers.copy import copy_signal
from .analyzers.integrity import build_profile as integrity_profile
from .analyzers.integrity import integrity_features, integrity_signal
from .analyzers.pressure import build_pressure_profile, pressure_features, pressure_signal
from .analyzers.reference import DESCRIPTOR_VERSION, embed, from_bytes, reference_signal, to_bytes
from .analyzers.seal_text import seal_text_signal
from .config import SETTINGS, Settings
from .determinism import round_score
from .extract import crop_color, crop_gray, element_mask, find_regions, paper_text_masks
from .extract.regions import Box, Element, PageRegions
from .store import Database

MIN_PRESSURE_REFS = 5
COPY_SHORTLIST = 40          # comparaisons AKAZE au plus par element (prefiltre par empreinte)
KINDS = {"seal": "Sceau", "signature": "Signature"}
ERODE = {"seal": SETTINGS.pressure_erode_seal, "signature": SETTINGS.pressure_erode_signature}


# -- mesures d'une page (communes aux references et aux documents controles) ---------------------
@dataclass
class ElementFacts:
    element: Element
    crop_box: Box                     # zone recadree (element + marge), coordonnees de la page
    gray: np.ndarray                  # recadrage, niveaux de gris « encre »
    color: np.ndarray                 # recadrage couleur (enregistre pour la detection de copie)
    phash: int
    embedding: np.ndarray
    pressure: dict | None
    integrity: dict | None

    def features(self) -> dict:
        return {"phash": str(self.phash), "pressure": self.pressure, "integrity": self.integrity,
                "box": self.element.box.as_dict(), "confidence": self.element.confidence}


@dataclass
class PageFacts:
    regions: PageRegions
    elements: dict[str, ElementFacts]
    aging: dict | None


def phash_of(gray: np.ndarray) -> int:
    return int(str(imagehash.phash(Image.fromarray(gray))), 16)


def page_facts(page: np.ndarray, dpi: float | None = None,
               settings: Settings = SETTINGS) -> PageFacts:
    regions = find_regions(page, dpi)
    paper, text = paper_text_masks(page, regions)
    elements = {}
    for kind, el in (("seal", regions.seal), ("signature", regions.signature)):
        if el is None:
            continue
        g = crop_gray(page, el)
        elements[kind] = ElementFacts(
            el, el.box.padded(24, page.shape), g, crop_color(page, el), phash_of(g), embed(g),
            pressure_features(g, ink_level=settings.ink_level, erode=ERODE[kind]),
            integrity_features(page, el.box, paper))
    aging = None
    if regions.seal is not None:
        aging = aging_mod.measures(page, paper, text, element_mask(regions, regions.seal, page.shape))
    return PageFacts(regions, elements, aging)


def save_crop(img: np.ndarray, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise OSError(f"Impossible d'encoder {path}")
    path.write_bytes(buf.tobytes())                 # PNG : sans perte
    return path


def load_gray(path: str | Path) -> np.ndarray | None:
    data = np.fromfile(str(path), np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
    return None if img is None else np.ascontiguousarray(img.min(axis=2))


# -- references ------------------------------------------------------------------------------
@dataclass
class References:
    """Tout ce qui sert de comparaison, charge une fois par analyse, dans un ordre fixe."""
    specimens: dict[str, list[dict]]            # kind -> specimens (tous les ans)
    known: dict[str, list[dict]]                # kind -> elements deja vus (analyses precedentes)
    year_profile: dict
    n_year_docs: int
    version: str
    # specimens ecartes parce qu'ils viennent du document analyse lui-meme (il est une reference)
    self_excluded: dict[str, int] = field(default_factory=dict)

    @classmethod
    def load(cls, db: Database, year: int, exclude_sha: str | None = None) -> "References":
        all_specimens = {k: db.specimens(k) for k in KINDS}
        # Un document n'est jamais compare a ses propres specimens : il serait « copie de
        # lui-meme » ou trivialement conforme. Le nombre ecarte sert a l'expliquer a l'agent.
        specimens = {k: [s for s in v if s.get("source_sha256") != exclude_sha]
                     for k, v in all_specimens.items()}
        excluded = {k: len(all_specimens[k]) - len(specimens[k]) for k in KINDS}
        known = {k: db.known_fingerprints(k, exclude_sha) for k in KINDS}
        return cls(specimens, known, db.year_profile(year), db.count_reference_docs(year),
                   references_version(db), excluded)

    @property
    def is_reference(self) -> bool:
        """Le document analyse est lui-meme enregistre comme reference."""
        return any(self.self_excluded.values())

    def expected(self, kind: str) -> bool:
        """Element attendu ? Oui par defaut ; non si les references n'en comportent jamais."""
        return True if kind == "seal" else (bool(self.specimens["signature"])
                                            or not self.specimens["seal"])


def references_version(db: Database) -> str:
    """Empreinte des references (specimens + plages par annee) : entre dans `analysis_key`."""
    h = hashlib.sha256(db.profile_version().encode())
    for kind in KINDS:
        for s in db.specimens(kind):
            h.update(json.dumps([s["id"], s["kind"], s["year"], s["image_path"],
                                 s.get("expected_text"), s.get("features")],
                                sort_keys=True, default=str).encode())
    return h.hexdigest()


# -- controles -------------------------------------------------------------------------------
def _label(item: dict) -> str:
    if "owner_name" in item:                        # specimen de reference
        return f"document de référence {item['year']} ({item.get('owner_name') or 'signataire non précisé'})"
    return f"{item.get('file_name', 'document')} analysé le {str(item.get('created_at', ''))[:10]}"


def _copy(f: ElementFacts, kind: str, refs: References, settings: Settings) -> Signal | None:
    cands = []
    for i, s in enumerate(refs.specimens[kind]):
        ph = int((s.get("features") or {}).get("phash", "0"))
        cands.append((bin(ph ^ f.phash).count("1"), 0, i, s["image_path"], _label(s)))
    for i, k in enumerate(refs.known[kind]):
        cands.append((bin(k["phash"] ^ f.phash).count("1"), 1, i, k["crop_path"], _label(k)))
    if not cands:
        return None
    cands.sort()                                     # ordre fixe : distance, origine, rang
    known, paths = [], {}
    for n, (_, _, _, path, label) in enumerate(cands[:COPY_SHORTLIST]):
        g = load_gray(path)
        if g is not None:
            uid = f"{n}"                            # identifiant unique (libelles parfois identiques)
            known.append((uid, g))
            paths[uid] = (label, str(path))
    sig = copy_signal(f.gray, known, settings)
    if sig is None:
        return None
    for key in ("copy_of", "closest"):              # identifiant -> libelle lisible + image
        if sig.evidence.get(key):
            uid = sig.evidence[key]["document"]
            sig.evidence[key]["document"], sig.evidence[key]["image"] = paths[uid]
    sig.evidence["compared"] = len(known)
    return sig


def _pressure(f: ElementFacts, kind: str, refs: References, settings: Settings) -> Signal | None:
    feats = [s["features"]["pressure"] for s in refs.specimens[kind]
             if s.get("features") and s["features"].get("pressure")]
    if len(feats) < MIN_PRESSURE_REFS or f.pressure is None:
        return None
    prof = build_pressure_profile(feats)
    prof = {k: (m, max(mad, 0.05 * abs(m), 1e-4)) for k, (m, mad) in prof.items()}  # plancher relatif
    sig = pressure_signal(f.gray, prof, erode=ERODE[kind], settings=settings)
    if sig is not None:
        sig.evidence["n_references"] = len(feats)
    return sig


def _reference(f: ElementFacts, kind: str, year: int, refs: References) -> Signal | None:
    sp = [s for s in refs.specimens[kind] if s.get("embedding")]
    same_year = [s for s in sp if s["year"] == year]
    pool = same_year if len(same_year) >= 3 else sp
    sig = reference_signal(f.embedding, [(str(s["id"]), from_bytes(s["embedding"])) for s in pool])
    if sig is not None:
        sp = next(s for s in pool if str(s["id"]) == sig.evidence["nearest_specimen"])
        sig.evidence["nearest_specimen"] = _label(sp)
        sig.evidence["nearest_image"] = sp["image_path"]
    return sig


def _integrity(f: ElementFacts, kind: str, refs: References) -> Signal | None:
    prof = integrity_profile([s["features"]["integrity"] for s in refs.specimens[kind]
                              if s.get("features") and s["features"].get("integrity")])
    return integrity_signal(f.integrity, prof)


def _seal_text(f: ElementFacts, year: int, refs: References) -> Signal | None:
    texts = [s["expected_text"] for s in refs.specimens["seal"] if s.get("expected_text")]
    same = [s["expected_text"] for s in refs.specimens["seal"]
            if s.get("expected_text") and s["year"] == year]
    pool = same or texts
    if not pool or f.element.circle is None:
        return None
    expected = sorted(Counter(pool).items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    b = f.crop_box
    cx, cy, r = f.element.circle
    return seal_text_signal(f.gray, (cx - b.x, cy - b.y, r), expected)


def _aging(facts: PageFacts, refs: References, settings: Settings) -> Signal | None:
    prof = {k: (v[0], v[1]) for k, v in refs.year_profile.items()}
    if any(k not in prof for k in aging_mod.MEASURES):
        return None
    return aging_mod.aging_signal(facts.aging, prof, refs.n_year_docs, settings)


# -- resultat --------------------------------------------------------------------------------
@dataclass
class PageAnalysis:
    signals: dict[str, Signal | None]
    rows: list[dict]
    hidden: dict[str, str]
    regions: list[dict]
    facts: PageFacts
    evidence: dict = field(default_factory=dict)


def analyze_page(page: np.ndarray, year: int, db: Database, file_sha: str | None = None,
                 dpi: float | None = None, settings: Settings = SETTINGS,
                 refs: References | None = None) -> PageAnalysis:
    facts = page_facts(page, dpi, settings)
    refs = refs or References.load(db, year, file_sha)
    sig: dict[str, Signal | None] = {}
    missing = []
    for kind, prefix in (("seal", "seal"), ("signature", "sig")):
        f = facts.elements.get(kind)
        if f is None:
            if refs.expected(kind):
                missing.append(kind)
            continue
        sig[f"{prefix}_copy"] = _copy(f, kind, refs, settings)
        sig[f"{prefix}_pressure"] = _pressure(f, kind, refs, settings)
        sig[f"{prefix}_reference"] = _reference(f, kind, year, refs)
        sig[f"{prefix}_integrity"] = _integrity(f, kind, refs)
        if kind == "seal":
            sig["seal_text"] = _seal_text(f, year, refs)
    sig["aging"] = _aging(facts, refs, settings)
    if missing:
        sig["unreadable"] = Signal(1.0, 1.0, {"missing": missing})
    rows, hidden = build_rows(sig, missing, facts, refs, year, settings)
    regions = [{"row": KINDS[k], "page": 0, "rect": list(f.element.box.rect()),
                "color": next((r["color"] for r in rows if r["name"] == KINDS[k]), "orange")}
               for k, f in sorted(facts.elements.items())]
    evidence = {"elements": {k: f.features() for k, f in sorted(facts.elements.items())},
                "aging_measures": facts.aging, "references_version": refs.version,
                "n_reference_docs_year": refs.n_year_docs, "descriptor": DESCRIPTOR_VERSION,
                "is_reference": refs.is_reference}
    return PageAnalysis(sig, rows, hidden, regions, facts, evidence)


def _color(risk: float, settings: Settings) -> str:
    r = round_score(risk)
    return "red" if r >= settings.suspect_threshold else ("orange" if r >= settings.review_threshold
                                                           else "green")


WORDS = {"Sceau": ("Conforme", "À vérifier", "Anomalie"),
         "Signature": ("Conforme", "À vérifier", "Anomalie"),
         "Vieillissement": ("Normal", "Écart", "Anomalie"),
         "Pression de l'encre": ("Normale", "Faible", "Reproduction probable")}
AGING_FR = {"paper_L": "clarté du papier", "paper_b": "jaunissement du papier",
            "paper_grain": "grain du papier", "text_contrast": "contraste du texte",
            "seal_contrast": "contraste du sceau", "seal_text_gap": "écart sceau / texte"}


def _reasons(name: str, signals: dict) -> list[str]:
    out = []
    for key, s in signals.items():
        if s is None or s.risk < SETTINGS.review_threshold:
            continue
        ev = s.evidence
        if key.endswith("_copy") and ev.get("copy_of"):
            out.append(f"copie : {ev['copy_of']['document']}")
        elif key.endswith("_pressure"):
            out.append("encre trop uniforme : sceau reproduit (photocopie, impression) ?")
        elif key.endswith("_integrity"):
            out.append("le papier autour diffère du reste de la page (zone collée ?)")
        elif key.endswith("_reference"):
            out.append("forme éloignée des spécimens de référence")
        elif key == "seal_text":
            out.append(f"texte du sceau différent de « {ev.get('expected')} »")
        elif key == "aging":
            out.append("hors de la plage normale : " + ", ".join(AGING_FR.get(m, m) for m in ev["flagged"]))
    return out


def build_rows(sig: dict, missing: list[str], facts: PageFacts, refs: References, year: int,
               settings: Settings) -> tuple[list[dict], dict[str, str]]:
    groups = {"Sceau": ["seal_text", "seal_reference", "seal_copy", "seal_integrity"],
              "Signature": ["sig_reference", "sig_copy", "sig_integrity"],
              "Vieillissement": ["aging"],
              "Pression de l'encre": ["seal_pressure", "sig_pressure"]}
    rows, hidden = [], {}
    for name, keys in groups.items():
        present = {k: sig[k] for k in keys if sig.get(k) is not None}
        kind = {"Sceau": "seal", "Signature": "signature"}.get(name)
        if kind in missing:
            rows.append({"name": name, "word": "Introuvable", "color": "orange",
                         "reason": f"{name.lower()} attendu mais non trouvé sur la page"})
            continue
        if not present:
            hidden[name] = _hidden_reason(name, kind, facts, refs, year)
            continue
        copy = next((s for k, s in present.items() if k.endswith("_copy") and s.risk >= 1.0), None)
        if copy is not None:
            rows.append({"name": name, "word": "Copie", "color": "red",
                         "reason": f"copie : {copy.evidence['copy_of']['document']}"})
            continue
        risk = max(s.risk for s in present.values())
        color = _color(risk, settings)
        reduced = [s for s in present.values() if s.evidence.get("reduced_reliability")]
        if reduced and color == "red":
            color = "orange"                   # peu de references : ecart a confirmer, pas anomalie
        words = WORDS[name]
        word = words[{"green": 0, "orange": 1, "red": 2}[color]]
        reasons = _reasons(name, present)
        if reduced:
            n = reduced[0].evidence["n_reference_docs"]
            reasons.append(f"plage établie sur {n} documents seulement : fiabilité réduite "
                           f"(pleine à partir de {settings.aging_reliable_docs})")
        rows.append({"name": name, "word": word, "color": color, "reason": "; ".join(reasons)})
    return rows, hidden


SELF_REFERENCE = "ce document est lui-même une référence : il n'est pas comparé à lui-même"


def _hidden_reason(name: str, kind: str | None, facts: PageFacts, refs: References,
                   year: int) -> str:
    if kind is not None and refs.self_excluded.get(kind) and not refs.specimens[kind] \
            and not refs.known[kind]:
        return f"{SELF_REFERENCE} ; aucune autre référence de {name.lower()} pour comparer"
    if name == "Vieillissement":
        if facts.aging is None:
            return "mesures impossibles (sceau ou papier vierge introuvable)"
        if refs.n_year_docs < SETTINGS.aging_min_docs_per_year:
            return (f"moins de {SETTINGS.aging_min_docs_per_year} documents de référence en {year} "
                    f"({refs.n_year_docs} enregistré(s))")
        return f"plage normale de {year} pas encore calculée"
    if name == "Pression de l'encre":
        n = sum(1 for s in refs.specimens["seal"] if s.get("features") and s["features"].get("pressure"))
        if n < MIN_PRESSURE_REFS:
            own = " ; le sceau de ce document n'est pas compté" if refs.self_excluded.get("seal") else ""
            return f"moins de {MIN_PRESSURE_REFS} sceaux de référence mesurables ({n}){own}"
        return "zone d'encre trop petite pour mesurer la pression"
    if kind == "signature" and not refs.expected("signature"):
        return "les documents de référence ne comportent pas de signature"
    return f"aucun {name.lower()} de référence ni document déjà analysé pour comparer"
