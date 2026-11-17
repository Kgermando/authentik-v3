"""Schema SQLite et migrations (remplace PostgreSQL + alembic).

La version du schema est gardee dans `PRAGMA user_version`. Pour faire evoluer la base :
AJOUTER une entree a la fin de MIGRATIONS, ne jamais modifier une entree existante.

Regle (AGENTS.md 6 bis) : un resultat enregistre n'est jamais modifie. Des declencheurs
(triggers) refusent toute modification ou suppression dans `analyses`, `signals` et `reviews`.
La decision d'un agent s'ajoute dans `reviews`, sans toucher au resultat de la machine.
"""
from __future__ import annotations

import sqlite3

_V1 = """
CREATE TABLE specimens (            -- sceaux et signatures de reference
  id          INTEGER PRIMARY KEY,
  kind        TEXT    NOT NULL CHECK (kind IN ('seal','signature')),
  owner_name  TEXT    NOT NULL,
  year        INTEGER NOT NULL,
  image_path  TEXT    NOT NULL,
  embedding   BLOB                  -- float32 little-endian (256 valeurs), NULL si pas encore calcule
);
CREATE INDEX idx_specimens_kind_year ON specimens (kind, year);

CREATE TABLE analyses (
  id               INTEGER PRIMARY KEY,
  analysis_key     TEXT    NOT NULL UNIQUE,  -- memoisation : meme cle => meme resultat renvoye
  file_sha256      TEXT    NOT NULL,
  file_name        TEXT    NOT NULL,
  stored_path      TEXT    NOT NULL,         -- copie du document dans documents_dir
  year             INTEGER,
  score            REAL    NOT NULL,
  verdict          TEXT    NOT NULL CHECK (verdict IN ('conforme','a_verifier','suspect')),
  software_version TEXT    NOT NULL,
  result_json      TEXT    NOT NULL,         -- tout ce qu'affiche « En savoir plus »
  created_at       TEXT    NOT NULL          -- ISO 8601, UTC
);
CREATE INDEX idx_analyses_sha ON analyses (file_sha256);

CREATE TABLE signals (
  analysis_id INTEGER NOT NULL REFERENCES analyses(id),
  name        TEXT    NOT NULL,
  risk        REAL    NOT NULL,
  confidence  REAL    NOT NULL,
  evidence    TEXT    NOT NULL,              -- JSON
  PRIMARY KEY (analysis_id, name)
);

CREATE TABLE fingerprints (         -- tout sceau ou signature deja vu (detection de copie)
  id          INTEGER PRIMARY KEY,
  analysis_id INTEGER NOT NULL REFERENCES analyses(id),
  kind        TEXT    NOT NULL CHECK (kind IN ('seal','signature')),
  phash       INTEGER NOT NULL,              -- empreinte 64 bits stockee signee (voir db.to_signed64)
  crop_path   TEXT    NOT NULL
);
CREATE INDEX idx_fingerprints_phash ON fingerprints (phash);
CREATE INDEX idx_fingerprints_kind ON fingerprints (kind);

CREATE TABLE reference_docs (       -- documents authentiques de reference (vieillissement)
  id        INTEGER PRIMARY KEY,
  year      INTEGER NOT NULL,
  scanner   TEXT,
  measures  TEXT    NOT NULL,                -- JSON
  added_at  TEXT    NOT NULL
);
CREATE INDEX idx_reference_docs_year ON reference_docs (year);

CREATE TABLE year_profiles (        -- plage normale par annee et par mesure
  year    INTEGER NOT NULL,
  measure TEXT    NOT NULL,
  median  REAL    NOT NULL,
  mad     REAL    NOT NULL,
  n       INTEGER NOT NULL,
  PRIMARY KEY (year, measure)
);

CREATE TABLE reviews (              -- decision d'un agent, ajoutee sans ecraser le resultat
  id          INTEGER PRIMARY KEY,
  analysis_id INTEGER NOT NULL REFERENCES analyses(id),
  reviewed_by TEXT    NOT NULL,
  decision    TEXT    NOT NULL CHECK (decision IN ('authentique','faux','indetermine')),
  review_note TEXT,
  created_at  TEXT    NOT NULL
);
CREATE INDEX idx_reviews_analysis ON reviews (analysis_id);

CREATE TRIGGER analyses_no_update BEFORE UPDATE ON analyses
BEGIN SELECT RAISE(ABORT, 'resultat enregistre : modification interdite'); END;
CREATE TRIGGER analyses_no_delete BEFORE DELETE ON analyses
BEGIN SELECT RAISE(ABORT, 'resultat enregistre : suppression interdite'); END;
CREATE TRIGGER signals_no_update BEFORE UPDATE ON signals
BEGIN SELECT RAISE(ABORT, 'signal enregistre : modification interdite'); END;
CREATE TRIGGER signals_no_delete BEFORE DELETE ON signals
BEGIN SELECT RAISE(ABORT, 'signal enregistre : suppression interdite'); END;
CREATE TRIGGER reviews_no_update BEFORE UPDATE ON reviews
BEGIN SELECT RAISE(ABORT, 'revue enregistree : modification interdite'); END;
CREATE TRIGGER reviews_no_delete BEFORE DELETE ON reviews
BEGIN SELECT RAISE(ABORT, 'revue enregistree : suppression interdite'); END;
"""

_V2 = """
-- Documents de reference ajoutes par l'utilisateur (menu « References »)
ALTER TABLE specimens ADD COLUMN expected_text TEXT;        -- texte attendu du sceau (facultatif)
ALTER TABLE specimens ADD COLUMN source_sha256 TEXT;        -- document authentique d'origine
ALTER TABLE specimens ADD COLUMN features TEXT;             -- JSON : mesures de pression, etc.
ALTER TABLE reference_docs ADD COLUMN source_sha256 TEXT;
ALTER TABLE reference_docs ADD COLUMN stored_path TEXT;
ALTER TABLE reference_docs ADD COLUMN owner_name TEXT;
ALTER TABLE reference_docs ADD COLUMN file_name TEXT;            -- nom d'origine du fichier
CREATE UNIQUE INDEX idx_reference_docs_sha ON reference_docs (source_sha256);
CREATE INDEX idx_specimens_source ON specimens (source_sha256);
"""

MIGRATIONS: list[str] = [_V1, _V2]


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection) -> int:
    """Applique les migrations manquantes, chacune dans sa transaction. Renvoie la version finale."""
    current = schema_version(conn)
    if current > len(MIGRATIONS):
        raise RuntimeError(
            f"Base en version {current}, logiciel prevu pour {len(MIGRATIONS)} : "
            "mettre Authentik a jour avant d'ouvrir cette base.")
    for version in range(current + 1, len(MIGRATIONS) + 1):
        conn.execute("BEGIN")
        try:
            for stmt in _split(MIGRATIONS[version - 1]):
                conn.execute(stmt)
            conn.execute(f"PRAGMA user_version = {version}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return schema_version(conn)


def _split(script: str) -> list[str]:
    """Decoupe un script en instructions completes (gere les BEGIN ... END des triggers)."""
    out, buf = [], ""
    for line in script.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip():
                out.append(buf.strip())
            buf = ""
    if buf.strip():
        raise ValueError(f"Instruction SQL incomplete : {buf[:80]!r}")
    return out
