"""Contrat commun des analyseurs."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Signal:
    """Resultat d'un controle.

    risk       : 0 (conforme) a 1 (falsifie)
    confidence : fiabilite de la mesure, 0 a 1
    evidence   : details pour « En savoir plus » (JSON-serialisable)
    """
    risk: float
    confidence: float
    evidence: dict = field(default_factory=dict)


# Un analyseur qui n'a aucune valeur renvoie None (NO_SIGNAL) : la ligne correspondante
# de la page de resultats est alors MASQUEE (voir AGENTS.md, regle de masquage).
NO_SIGNAL = None
