"""Mesures de la preuve devant le jury (voir AGENTS.md, section Evaluation)."""
from __future__ import annotations

from math import sqrt


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalle de confiance a 95 % d'une proportion k/n (methode de Wilson)."""
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    demi = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return centre - demi, centre + demi


def recall_and_false_reject(y_true, verdicts) -> dict:
    """y_true : 1 = faux, 0 = authentique. verdicts : 'conforme' | 'a_verifier' | 'suspect'.
    Un document est « signale » s'il est a_verifier ou suspect."""
    flagged = [v != "conforme" for v in verdicts]
    fakes = [f for f, y in zip(flagged, y_true) if y == 1]
    genuine = [f for f, y in zip(flagged, y_true) if y == 0]
    out = {}
    if fakes:
        k, n = sum(fakes), len(fakes)
        out["recall"] = k / n
        out["recall_ci95"] = wilson(k, n)
    if genuine:
        k, n = sum(genuine), len(genuine)
        out["false_reject"] = k / n
        out["false_reject_ci95"] = wilson(k, n)
    return out
