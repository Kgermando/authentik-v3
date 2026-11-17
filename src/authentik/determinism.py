"""Reproductibilite : le meme fichier doit toujours donner le meme resultat.

Regles :
1. Appeler `init_determinism()` au demarrage de l'application ET au debut de chaque analyse.
2. Aucun hasard non fixe dans le code d'analyse (graine fixe partout).
3. Un seul thread pour OpenCV pendant l'analyse (l'ordre des sommes flottantes ne varie pas).
4. Les scores sont arrondis (`round_score`) AVANT toute comparaison a un seuil.
5. Le resultat d'une analyse est memorise par `analysis_key` : meme fichier + meme version
   du logiciel, des modeles et des profils => on renvoie le resultat memorise, sans recalculer.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import cv2
import numpy as np

SEED = 20240601
SCORE_DECIMALS = 4


def init_determinism() -> None:
    cv2.setNumThreads(1)
    cv2.setRNGSeed(SEED)
    random.seed(SEED)
    np.random.seed(SEED)


def round_score(x: float) -> float:
    return round(float(x), SCORE_DECIMALS)


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def analysis_key(file_sha: str, software_version: str, model_hashes: dict[str, str],
                 profile_version: str, settings_dict: dict) -> str:
    """Cle de memorisation : change des qu'un element pouvant modifier le resultat change."""
    payload = json.dumps(
        {
            "file": file_sha,
            "software": software_version,
            "models": model_hashes,
            "profiles": profile_version,
            "settings": settings_dict,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()
