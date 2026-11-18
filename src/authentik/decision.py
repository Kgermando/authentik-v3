"""Verdict : modele de fusion entraine s'il existe, sinon regles PROVISOIRES.

Tant que le modele n'est pas entraine sur des documents verifies par des agents (menu
References > Entrainer la decision), le logiciel :
- conclut « Suspect » sur une preuve forte (copie detectee, ou un controle tres anormal) ;
- conclut « A verifier » dans TOUS les autres cas : il ne dit jamais « Conforme » seul,
  car aucun seuil n'a ete calibre (AGENTS.md 0 : ne pas pretendre a une fiabilite non mesuree).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .analyzers.base import Signal
from .config import SETTINGS, Settings
from .determinism import round_score
from .fusion import FEATURES, Fusion
from .store import AppConfig

STRONG = ("seal_copy", "sig_copy", "seal_pressure", "sig_pressure", "seal_integrity",
          "sig_integrity", "aging", "seal_text")       # *_reference seul ne rejette jamais


@dataclass
class Decision:
    score: float
    verdict: str                  # conforme | a_verifier | suspect
    calibrated: bool
    summary: str


def model_path(cfg: AppConfig) -> Path:
    return cfg.database.parent / "modeles" / "fusion.joblib"


def model_hash(cfg: AppConfig) -> str:
    p = model_path(cfg)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "provisoire"


def load_fusion(cfg: AppConfig) -> Fusion | None:
    p = model_path(cfg)
    return Fusion.load(str(p)) if p.exists() else None


def decide(signals: dict[str, Signal | None], fusion: Fusion | None,
           settings: Settings = SETTINGS, is_reference: bool = False) -> Decision:
    """`is_reference` : le document analyse est lui-meme une reference (il n'est pas compare
    a ses propres specimens) ; ne sert qu'a expliquer l'absence de controle."""
    present = {k: s for k, s in signals.items() if s is not None}
    for k in ("seal_copy", "sig_copy"):
        s = present.get(k)
        if s is not None and s.risk >= 1.0:
            what = "Le sceau" if k == "seal_copy" else "La signature"
            return Decision(1.0, "suspect", fusion is not None,
                            f"{what} est la copie d'un autre document.")
    if "unreadable" in present:
        miss = " et ".join({"seal": "le sceau", "signature": "la signature"}[m]
                           for m in present["unreadable"].evidence.get("missing", []))
        return Decision(0.5, "a_verifier", fusion is not None,
                        f"Élément attendu introuvable ({miss}) : vérification humaine nécessaire.")
    if fusion is not None:
        score, verdict = fusion.decide(present)
        text = {"conforme": "Aucune anomalie significative selon le modèle entraîné.",
                "a_verifier": "Indices à confirmer par un agent.",
                "suspect": "Plusieurs indices de falsification."}[verdict]
        return Decision(score, verdict, True, text)
    # regles provisoires
    weighted = [s.risk * s.confidence for k, s in present.items() if k in FEATURES]
    score = round_score(max(weighted, default=0.0))
    strong = [k for k in STRONG if k in present
              and round_score(present[k].risk) >= settings.suspect_threshold
              and not present[k].evidence.get("reduced_reliability")]
    if strong:
        return Decision(max(score, settings.suspect_threshold), "suspect", False,
                        "Au moins un contrôle est très anormal. Décision provisoire "
                        "(modèle non entraîné) : un agent doit confirmer.")
    if not present:
        if is_reference:
            return Decision(0.5, "a_verifier", False,
                            "Ce document est lui-même enregistré comme référence : il n'est pas "
                            "comparé à lui-même. Pour le contrôler, enregistrer d'autres documents "
                            "de référence de la même année.")
        return Decision(0.5, "a_verifier", False,
                        "Aucun contrôle n'a pu être fait : ajouter des documents de référence.")
    flagged = any(round_score(s.risk) >= settings.review_threshold for s in present.values())
    return Decision(max(score, settings.review_threshold), "a_verifier", False,
                    ("Des écarts ont été relevés. " if flagged else
                     "Aucune anomalie relevée par les contrôles disponibles. ")
                    + "Décision provisoire (modèle non entraîné) : un agent doit confirmer.")
