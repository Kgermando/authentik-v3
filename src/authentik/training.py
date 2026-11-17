"""Entrainement de la decision (phase 4) a partir des analyses VERIFIEES par des agents.

Chaque fois qu'un agent indique « Authentique » ou « Faux » sur la page de resultats, l'analyse
devient un exemple. Avec assez d'exemples, la regression logistique de `fusion.py` est entrainee
et le seuil de revue est choisi par validation croisee (AGENTS.md 8) :
le plus eleve qui garde >= 90 % des faux signales avec <= 5 % de vrais signales a tort.

Ces chiffres de validation croisee NE SONT PAS la mesure officielle : celle-ci se fait une seule
fois sur un lot de test jamais vu (`python -m authentik.eval`, AGENTS.md 9).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import numpy as np
from sklearn.base import clone
from sklearn.model_selection import StratifiedKFold, cross_val_predict

from .analyzers.base import Signal
from .config import SETTINGS
from .decision import model_path
from .eval.metrics import recall_and_false_reject
from .fusion import Fusion, review_threshold_from_roc
from .store import AppConfig, Database

MIN_PER_CLASS = 10
LABELS = {"faux": 1, "authentique": 0}


@dataclass
class TrainReport:
    n_fake: int
    n_genuine: int
    trained: bool
    message: str
    review_threshold: float | None = None
    cv_recall: float | None = None
    cv_false_reject: float | None = None

    def text(self) -> str:
        lines = [f"Exemples vérifiés : {self.n_fake} faux, {self.n_genuine} authentiques.", self.message]
        if self.cv_recall is not None:
            lines.append(f"Validation croisée (indicative, pas la mesure officielle) : "
                         f"{self.cv_recall:.0%} des faux signalés, "
                         f"{self.cv_false_reject:.0%} des vrais signalés à tort.")
        return "\n".join(lines)


def signals_of(saved: dict) -> dict[str, Signal]:
    return {k: Signal(v["risk"], v["confidence"], v["evidence"]) for k, v in saved["signals"].items()}


def examples(db: Database) -> tuple[list[dict[str, Signal]], list[int]]:
    X, y = [], []
    for a in db.reviewed_analyses():                 # ordre fixe (id croissant)
        if a["decision"] in LABELS:
            X.append(signals_of(a))
            y.append(LABELS[a["decision"]])
    return X, y


def train_from_reviews(cfg: AppConfig, db: Database, min_per_class: int = MIN_PER_CLASS) -> TrainReport:
    X, y = examples(db)
    n_fake, n_gen = sum(y), len(y) - sum(y)
    if n_fake < min_per_class or n_gen < min_per_class:
        return TrainReport(n_fake, n_gen, False,
                           f"Pas assez d'exemples : il faut au moins {min_per_class} faux et "
                           f"{min_per_class} authentiques vérifiés par des agents. "
                           "La décision reste provisoire.")
    f = Fusion()
    V = np.array([f.vector(s) for s in X])
    yv = np.array(y)
    folds = StratifiedKFold(n_splits=min(5, n_fake, n_gen), shuffle=True, random_state=0)
    p = cross_val_predict(clone(f.model), V, yv, cv=folds, method="predict_proba")[:, 1]
    p = np.round(p, 4)
    thr = review_threshold_from_roc(yv, p)
    if thr is None:
        msg = ("Objectif (90 % des faux, au plus 5 % de vrais signalés) hors de portée avec ces "
               "contrôles : seuils provisoires conservés. Il faut améliorer un contrôle, pas le seuil.")
        review = SETTINGS.review_threshold
    else:
        review = round(float(min(thr, 1.0)), 4)
        msg = f"Décision entraînée. Seuil de revue : {review:.2f}."
    suspect = max(review, SETTINGS.suspect_threshold)
    verdicts = ["conforme" if q < review else ("suspect" if q >= suspect else "a_verifier") for q in p]
    m = recall_and_false_reject(list(yv), verdicts)
    fusion = Fusion(review, suspect)
    fusion.fit(X, y)
    path = model_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    fusion.save(str(path))
    report = TrainReport(n_fake, n_gen, True, msg, review, m.get("recall"), m.get("false_reject"))
    info = asdict(report) | {"trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    path.with_suffix(".json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def reset_model(cfg: AppConfig) -> None:
    """Revient a la decision provisoire (supprime le modele entraine)."""
    for p in (model_path(cfg), model_path(cfg).with_suffix(".json")):
        p.unlink(missing_ok=True)
