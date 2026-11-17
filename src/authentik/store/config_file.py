"""Fichier de configuration `authentik.ini` (base SQLite et dossier des documents).

Emplacement du fichier : %APPDATA%\\Authentik\\authentik.ini (Windows),
~/.config/authentik/authentik.ini (Linux), ~/Library/Application Support/Authentik (macOS).

Donnees par defaut (partagees par tous les utilisateurs du poste) :
%PROGRAMDATA%\\Authentik\\authentik.db et %PROGRAMDATA%\\Authentik\\documents.
L'installateur donne aux utilisateurs le droit d'ecrire dans ce dossier.

Valeurs absentes => valeurs par defaut. Fichier illisible => valeurs par defaut + `warning`
(l'application demarre quand meme et affiche le message).
"""
from __future__ import annotations

import configparser
import os
import sys
from dataclasses import dataclass
from pathlib import Path

SECTION = "storage"
SCANNERS = "scanners"     # scannerN = Nom affiche | URL eSCL


def config_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Authentik"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Authentik"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "authentik"


def default_data_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Authentik"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Authentik"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "authentik"


@dataclass(frozen=True)
class AppConfig:
    database: Path
    documents_dir: Path
    ini_path: Path
    warning: str | None = None
    scanners: tuple[tuple[str, str], ...] = ()     # scanners memorises : (nom, URL eSCL)

    @property
    def crops_dir(self) -> Path:
        return self.documents_dir / "crops"


def _defaults(ini_path: Path, warning: str | None = None) -> AppConfig:
    data = default_data_dir()
    return AppConfig(data / "authentik.db", data / "documents", ini_path, warning)


def load_config(ini_path: str | Path | None = None) -> AppConfig:
    """Lit le fichier ; le cree avec les valeurs par defaut s'il n'existe pas."""
    path = Path(ini_path) if ini_path else config_dir() / "authentik.ini"
    if not path.exists():
        cfg = _defaults(path)
        try:
            save_config(cfg)
        except OSError as e:
            return _defaults(path, f"Impossible de creer {path} : {e}")
        return cfg

    # interpolation=None : « % » est un caractere normal (%APPDATA%, URL encodees)
    parser = configparser.ConfigParser(inline_comment_prefixes=(";", "#"), interpolation=None)
    try:
        with open(path, encoding="utf-8") as f:
            parser.read_file(f)
    except (configparser.Error, OSError, UnicodeDecodeError) as e:
        return _defaults(path, f"Fichier de configuration invalide ({path}) : {e}. "
                               "Valeurs par défaut utilisées.")
    d = _defaults(path)
    sec = parser[SECTION] if parser.has_section(SECTION) else {}
    database = sec.get("database", "").strip() or str(d.database)
    documents = sec.get("documents_dir", "").strip() or str(d.documents_dir)
    scanners = []
    if parser.has_section(SCANNERS):
        for key in sorted(parser[SCANNERS], key=_scanner_order):
            name, sep, url = parser[SCANNERS][key].rpartition("|")
            if sep and name.strip() and url.strip():
                scanners.append((name.strip(), url.strip()))
    return AppConfig(Path(os.path.expandvars(database)), Path(os.path.expandvars(documents)), path,
                     scanners=tuple(scanners))


def _scanner_order(key: str) -> tuple[int, str]:
    digits = "".join(c for c in key if c.isdigit())
    return (int(digits) if digits else 0, key)


def save_config(cfg: AppConfig) -> None:
    parser = configparser.ConfigParser(interpolation=None)
    parser[SECTION] = {"database": str(cfg.database), "documents_dir": str(cfg.documents_dir)}
    if cfg.scanners:
        parser[SCANNERS] = {f"scanner{i}": f"{name} | {url}"
                            for i, (name, url) in enumerate(cfg.scanners, 1)}
    cfg.ini_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cfg.ini_path.with_suffix(".ini.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("; Configuration d'Authentik (Ministere de la Formation Professionnelle)\n")
        parser.write(f)
    os.replace(tmp, cfg.ini_path)
