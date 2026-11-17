"""Scan par le pilote Windows (WIA 2.0), pour les scanners USB ou reseau sans eSCL.

Utilise l'automatisation WIA (« WIA.DeviceManager ») via pywin32. Fonctionne avec tout
scanner dont le pilote du fabricant est installe sur le poste.

Reglages imposes : intention couleur, 300 DPI, 24 bits, format PNG (sans perte).
Luminosite et contraste ne sont PAS modifies (aucune amelioration ajoutee).

ATTENTION : NON TESTE sur Windows. Le developpement a eu lieu sous Linux. A valider sur un
poste Windows avec le scanner du client avant de s'y fier.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from ..config import SETTINGS
from .base import ScannerInfo
from .escl import ScanError

WIA_DEVICE_SCANNER = 1
WIA_FORMAT_PNG = "{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}"
# Identifiants de proprietes WIA
P_NAME = "Name"
P_INTENT = "6146"          # WIA_IPS_CUR_INTENT
P_XRES = "6147"            # WIA_IPS_XRES
P_YRES = "6148"            # WIA_IPS_YRES
P_DEPTH = "4104"           # WIA_IPA_DEPTH
INTENT_COLOR = 1           # WIA_INTENT_IMAGE_TYPE_COLOR


def available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import win32com.client  # noqa: F401
        return True
    except ImportError:
        return False


class _Com:
    """Initialise COM dans le fil courant (l'analyse tourne dans un fil du QThreadPool)."""

    def __enter__(self):
        import pythoncom
        pythoncom.CoInitialize()
        import win32com.client
        return win32com.client

    def __exit__(self, *exc):
        import pythoncom
        pythoncom.CoUninitialize()


def _prop(props, key):
    for p in props:
        if str(p.PropertyID) == key or p.Name == key:
            return p
    return None


def list_devices() -> list[ScannerInfo]:
    if not available():
        return []
    try:
        with _Com() as client:
            dm = client.Dispatch("WIA.DeviceManager")
            out = []
            for i in range(1, dm.DeviceInfos.Count + 1):
                info = dm.DeviceInfos.Item(i)
                if info.Type != WIA_DEVICE_SCANNER:
                    continue
                name_p = _prop(info.Properties, P_NAME)
                name = str(name_p.Value) if name_p is not None else info.DeviceID
                out.append(ScannerInfo(name, "wia", str(info.DeviceID), name, "pilote"))
            return sorted(out, key=lambda s: (s.name.lower(), s.address))
    except Exception:                                   # noqa: BLE001 - pilote absent ou en erreur
        return []


def _set(props, key: str, value) -> None:
    p = _prop(props, key)
    if p is None:
        raise ScanError(f"Le pilote WIA n'expose pas la propriété {key}.")
    try:
        p.Value = value
    except Exception as e:                              # noqa: BLE001
        raise ScanError(f"Le scanner refuse la valeur {value} pour la propriété {key}.") from e


def scan(device_id: str, folder: str | Path, dpi: int = SETTINGS.scan_dpi) -> Path:
    if not available():
        raise ScanError("Scan WIA disponible uniquement sous Windows.")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / ("scan_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".png")
    with _Com() as client:
        dm = client.Dispatch("WIA.DeviceManager")
        info = next((dm.DeviceInfos.Item(i) for i in range(1, dm.DeviceInfos.Count + 1)
                     if str(dm.DeviceInfos.Item(i).DeviceID) == device_id), None)
        if info is None:
            raise ScanError("Scanner introuvable : est-il allumé et branché ?")
        try:
            device = info.Connect()
        except Exception as e:                          # noqa: BLE001
            raise ScanError(f"Connexion au scanner impossible : {e}") from e
        item = device.Items.Item(1)
        _set(item.Properties, P_INTENT, INTENT_COLOR)   # d'abord : l'intention reinitialise le reste
        _set(item.Properties, P_XRES, dpi)
        _set(item.Properties, P_YRES, dpi)
        if _prop(item.Properties, P_DEPTH) is not None:
            _set(item.Properties, P_DEPTH, 24)
        try:
            image = item.Transfer(WIA_FORMAT_PNG)
        except Exception as e:                          # noqa: BLE001
            raise ScanError(f"Échec de la numérisation : {e}") from e
        if str(image.FormatID).upper() != WIA_FORMAT_PNG:
            # certains pilotes ignorent le format demande (BMP) : conversion SANS PERTE en PNG
            proc = client.Dispatch("WIA.ImageProcess")
            proc.Filters.Add(proc.FilterInfos.Item("Convert").FilterID)
            _set(proc.Filters.Item(1).Properties, "FormatID", WIA_FORMAT_PNG)
            image = proc.Apply(image)
        if out.exists():
            out.unlink()
        image.SaveFile(str(out))
    return out
