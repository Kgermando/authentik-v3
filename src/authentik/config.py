"""Seuils et parametres. Tous PROVISOIRES : a recalibrer sur de vrais documents (lot de validation).

Les valeurs ci-dessous ont ete choisies pour fonctionner sur les images de synthese des tests.
Elles ne prouvent rien sur de vrais documents.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Settings:
    # scan
    scan_dpi: int = 300
    # copie
    copy_min_inliers: int = 30
    copy_max_residual: float = 0.50     # residu <= seuil et assez d'inliers => copie numerique
    ink_level: int = 150
    # pression
    pressure_erode_seal: int = 7
    pressure_erode_signature: int = 3   # NON TESTE
    pressure_z_limit: float = 3.5
    pressure_features: tuple = ("pressure_gradient", "ink_range")
    # vieillissement
    aging_min_docs_per_year: int = 5    # decision de l'utilisateur (2026-11-17) : actif des 5
    aging_reliable_docs: int = 30       # en dessous : tolerance elargie, ne conclut pas seul
    aging_z_limit: float = 3.5
    aging_min_mad: float = 1.0
    # fusion
    review_threshold: float = 0.30
    suspect_threshold: float = 0.70

    def as_dict(self) -> dict:
        return asdict(self)


SETTINGS = Settings()
