"""Description commune d'un scanner, quel que soit le moyen d'y acceder.

backend :
- "escl" : imprimante reseau AirScan/eSCL (address = URL, ex. http://10.0.2.15:80/eSCL) ;
- "wia"  : pilote Windows (address = identifiant WIA du peripherique) ;
- "sane" : pilote Linux (address = nom SANE du peripherique).
"""
from __future__ import annotations

from dataclasses import dataclass

BACKEND_LABELS = {"escl": "réseau (eSCL)", "wia": "pilote Windows", "sane": "pilote SANE"}


@dataclass(frozen=True)
class ScannerInfo:
    name: str
    backend: str
    address: str
    model: str = ""
    origin: str = ""          # « réseau local », « enregistré », « plage 10.0.2.0/24 », « pilote »

    @property
    def label(self) -> str:
        where = self.address if self.backend == "escl" else BACKEND_LABELS.get(self.backend, "")
        extra = f" — {self.origin}" if self.origin else ""
        return f"{self.name}    ({where}){extra}"

    @property
    def key(self) -> tuple[str, str]:
        return self.backend, self.address.rstrip("/").lower()
