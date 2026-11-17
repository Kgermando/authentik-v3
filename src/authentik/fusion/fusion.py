"""Fusion des signaux en un verdict : conforme / a_verifier / suspect.

Regles dures d'abord, puis modele appris (regression logistique, deterministe).
Les seuils par defaut sont provisoires ; les calculer sur le lot de validation.
"""
from __future__ import annotations

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_curve

from ..analyzers.base import Signal
from ..config import SETTINGS
from ..determinism import round_score

FEATURES = ["seal_text", "seal_reference", "seal_copy", "seal_integrity",
            "sig_reference", "sig_copy", "sig_integrity",
            "seal_pressure", "sig_pressure", "aging"]


class Fusion:
    def __init__(self, review: float = SETTINGS.review_threshold,
                 suspect: float = SETTINGS.suspect_threshold):
        self.model = LogisticRegression(class_weight="balanced", max_iter=1000,
                                        solver="lbfgs", random_state=0)
        self.review, self.suspect = review, suspect
        self.fitted = False

    @staticmethod
    def vector(signals: dict[str, Signal]) -> list[float]:
        return [signals[k].risk * signals[k].confidence if signals.get(k) is not None else 0.0
                for k in FEATURES]

    def fit(self, signals_list: list[dict[str, Signal]], labels: list[int]) -> None:
        """labels : 1 = faux, 0 = authentique."""
        self.model.fit([self.vector(s) for s in signals_list], labels)
        self.fitted = True

    def decide(self, signals: dict[str, Signal]) -> tuple[float, str]:
        """Renvoie (score arrondi, verdict). Meme entree => meme sortie."""
        # 1. copie detectee : suspect, sans appel au modele
        for name in ("seal_copy", "sig_copy"):
            s = signals.get(name)
            if s is not None and s.risk >= 1.0:
                return 1.0, "suspect"
        # 2. element attendu mais introuvable / image illisible
        if signals.get("unreadable") is not None:
            return 0.5, "a_verifier"
        # 3. modele appris
        if not self.fitted:
            raise RuntimeError("Fusion non entrainee : appeler fit() ou charger un modele.")
        p = round_score(self.model.predict_proba([self.vector(signals)])[0, 1])
        if p >= self.suspect:
            return p, "suspect"
        return p, ("a_verifier" if p >= self.review else "conforme")

    def save(self, path: str) -> None:
        joblib.dump({"model": self.model, "review": self.review, "suspect": self.suspect}, path)

    @classmethod
    def load(cls, path: str) -> "Fusion":
        d = joblib.load(path)
        f = cls(d["review"], d["suspect"])
        f.model, f.fitted = d["model"], True
        return f


def review_threshold_from_roc(y_val, p_val, min_recall: float = 0.90,
                              max_false_reject: float = 0.05) -> float | None:
    """Seuil de revue : le plus eleve qui garde au moins `min_recall` des faux signales,
    avec au plus `max_false_reject` de vrais signales a tort.
    None => objectif hors de portee : ameliorer un controle, ne pas bouger le seuil.
    """
    fpr, tpr, thr = roc_curve(y_val, p_val)
    ok = np.where((tpr >= min_recall) & (fpr <= max_false_reject))[0]
    return float(thr[ok[0]]) if len(ok) else None
