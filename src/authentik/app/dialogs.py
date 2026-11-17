"""Boites de dialogue : « En savoir plus », « Base de donnees », « A propos »."""
from __future__ import annotations

import html
import json
import tempfile
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QPushButton, QTextBrowser,
                               QVBoxLayout, QWidget)

from .. import __version__
from ..store import AppConfig, Database, save_config


def _e(x) -> str:
    return html.escape(str(x))


SIGNAL_FR = {"seal_text": "Texte du sceau", "seal_reference": "Sceau : ressemblance aux spécimens",
             "seal_copy": "Sceau : copie d'un autre document", "seal_integrity": "Sceau : papier autour",
             "sig_reference": "Signature : ressemblance aux spécimens",
             "sig_copy": "Signature : copie d'un autre document",
             "sig_integrity": "Signature : papier autour", "seal_pressure": "Pression (sceau)",
             "sig_pressure": "Pression (signature)", "aging": "Vieillissement",
             "unreadable": "Élément attendu introuvable"}


def details_html(outcome, images: list | None = None) -> str:
    """`images` : [(titre, libelle, image de comparaison presente)], ressources img://i/doc|ref."""
    p = outcome.prepared
    parts = ["<h2>Tout ce qui a été constaté</h2>"]
    if not outcome.details.get("calibrated", True) and outcome.verdict:
        parts.append("<p><i>Décision provisoire : le modèle de décision n'est pas encore entraîné "
                     "sur des documents vérifiés par des agents.</i></p>")
    for i, (title, label, has_ref) in enumerate(images or []):
        ref = (f"<img src='img://{i}/ref' width='260'><br>" if has_ref else "") + _e(label)
        parts.append(f"<h3>{_e(title)}</h3><table><tr>"
                     f"<td><img src='img://{i}/doc' width='260'><br>Ce document</td>"
                     f"<td>&nbsp;&nbsp;</td><td>{ref}</td></tr></table>")
    sigs = outcome.details.get("signals") or {}
    if sigs:
        parts.append("<h3>Confiance de chaque contrôle</h3><table cellpadding='3'>"
                     "<tr><th align='left'>Contrôle</th><th>Risque</th><th>Confiance</th></tr>")
        for k, v in sorted(sigs.items()):
            parts.append(f"<tr><td>{_e(SIGNAL_FR.get(k, k))}</td><td align='center'>{v['risk']:.2f}</td>"
                         f"<td align='center'>{v['confidence']:.2f}</td></tr>")
        parts.append("</table>")
    parts.append("<h3>Document</h3><table>")
    for k, v in (("Fichier", p.source.name),
                 ("Origine", "Scan" if p.from_scan else "Import"),
                 ("Pages", len(p.doc.pages)),
                 ("Année retenue", outcome.year),
                 ("Année lue par OCR", p.year_reading.year or "aucune"),
                 ("Empreinte SHA-256", p.sha256),
                 ("Copie enregistrée", outcome.stored_path),
                 ("Intégrité de la copie", "vérifiée" if outcome.integrity_ok else "ALTÉRÉE"),
                 ("Clé d'analyse", outcome.analysis_key),
                 ("Résultat", "déjà enregistré (non recalculé)" if outcome.memoized
                  else "calculé maintenant"),
                 ("Version du logiciel", __version__)):
        parts.append(f"<tr><td><b>{_e(k)}</b>&nbsp;&nbsp;</td><td>{_e(v)}</td></tr>")
    parts.append("</table>")
    if p.doc.warnings:
        parts.append("<h3>Avertissements</h3><ul>" +
                     "".join(f"<li>{_e(w)}</li>" for w in p.doc.warnings) + "</ul>")
    if outcome.rows:
        parts.append("<h3>Indications</h3><ul>" + "".join(
            f"<li><b>{_e(r.name)}</b> : {_e(r.word)} {('— ' + _e(r.reason)) if r.reason else ''}</li>"
            for r in outcome.rows) + "</ul>")
    if outcome.hidden:
        parts.append("<h3>Indications masquées</h3><ul>" + "".join(
            f"<li><b>{_e(k)}</b> : {_e(v)}</li>" for k, v in outcome.hidden.items()) + "</ul>")
    details = {k: v for k, v in outcome.details.items() if v}
    if details:
        parts.append("<h3>Détails techniques</h3><pre>" +
                     _e(json.dumps(details, indent=2, ensure_ascii=False, default=str)) + "</pre>")
    return "".join(parts)


class DetailsDialog(QDialog):
    def __init__(self, outcome, crops_dir: Path, parent=None):
        super().__init__(parent)
        from ..report import evidence_images
        from .image_view import bgr_to_qimage
        self.outcome, self.crops_dir = outcome, crops_dir
        self.setWindowTitle("En savoir plus")
        self.resize(820, 700)
        lay = QVBoxLayout(self)
        text = QTextBrowser()
        doc = text.document()
        labels = []
        for i, (title, crop, label, other) in enumerate(evidence_images(outcome, crops_dir)):
            doc.addResource(QTextDocument.ImageResource, QUrl(f"img://{i}/doc"), bgr_to_qimage(crop))
            if other is not None:
                doc.addResource(QTextDocument.ImageResource, QUrl(f"img://{i}/ref"), bgr_to_qimage(other))
            labels.append((title, label, other is not None))
        text.setHtml(details_html(outcome, labels))
        lay.addWidget(text)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        self.pdf_btn = bb.addButton("Exporter le rapport PDF…", QDialogButtonBox.ActionRole)
        self.pdf_btn.clicked.connect(self.export_pdf)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def export_pdf(self) -> None:
        from ..report import write_report
        default = f"rapport_{self.outcome.prepared.source.stem}.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Rapport PDF", default, "PDF (*.pdf)")
        if not path:
            return
        try:
            write_report(self.outcome, path, self.crops_dir)
        except Exception as e:                            # noqa: BLE001
            QMessageBox.warning(self, "Rapport PDF", f"Export impossible : {e}")
            return
        QMessageBox.information(self, "Rapport PDF", f"Rapport enregistré : {path}")


def check_storage(database: Path, documents_dir: Path) -> str | None:
    """Verifie qu'on peut ouvrir la base et ecrire dans le dossier. None = OK, sinon le probleme."""
    try:
        Database(database).schema_version()
    except Exception as e:                                # noqa: BLE001
        return f"Base de données inutilisable ({database}) : {e}"
    try:
        documents_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=documents_dir, prefix=".test_", delete=True):
            pass
    except OSError as e:
        return f"Impossible d'écrire dans {documents_dir} : {e}"
    return None


class StorageDialog(QDialog):
    """Fichier de la base SQLite et dossier des documents (authentik.ini)."""

    def __init__(self, cfg: AppConfig, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Base de données")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.db = QLineEdit(str(cfg.database))
        self.docs = QLineEdit(str(cfg.documents_dir))
        form.addRow("Fichier de la base :", self._with_browse(self.db, file=True))
        form.addRow("Dossier des documents :", self._with_browse(self.docs, file=False))
        lay.addLayout(form)
        lay.addWidget(QLabel(f"Configuration : {cfg.ini_path}"))
        warn = QLabel("Les documents contiennent des données personnelles : limiter l'accès "
                      "à ce dossier et le sauvegarder régulièrement, avec la base.")
        warn.setWordWrap(True)
        lay.addWidget(warn)
        bb = QDialogButtonBox()
        self.test_btn = bb.addButton("Tester", QDialogButtonBox.ActionRole)
        bb.addButton("Enregistrer", QDialogButtonBox.AcceptRole)
        bb.addButton(QDialogButtonBox.Cancel)
        self.test_btn.clicked.connect(self._test)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _with_browse(self, edit: QLineEdit, file: bool) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(edit, 1)
        b = QPushButton("Parcourir…")
        h.addWidget(b)

        def browse():
            if file:
                path, _ = QFileDialog.getSaveFileName(self, "Fichier de la base", edit.text(),
                                                      "Base SQLite (*.db)",
                                                      options=QFileDialog.DontConfirmOverwrite)
            else:
                path = QFileDialog.getExistingDirectory(self, "Dossier des documents", edit.text())
            if path:
                edit.setText(path)
        b.clicked.connect(browse)
        return w

    def new_config(self) -> AppConfig:
        return replace(self.cfg, database=Path(self.db.text().strip()),
                       documents_dir=Path(self.docs.text().strip()), warning=None)

    def _test(self) -> bool:
        c = self.new_config()
        problem = check_storage(c.database, c.documents_dir)
        if problem:
            QMessageBox.warning(self, "Base de données", problem)
            return False
        QMessageBox.information(self, "Base de données", "Base et dossier utilisables.")
        return True

    def _save(self) -> None:
        c = self.new_config()
        problem = check_storage(c.database, c.documents_dir)
        if problem:
            QMessageBox.warning(self, "Base de données", problem)
            return
        save_config(c)
        self.cfg = c
        self.accept()


def show_about(parent) -> None:
    QMessageBox.about(
        parent, "À propos d'Authentik",
        f"<h3>Authentik {_e(__version__)}</h3>"
        "<p>Aide au contrôle des certificats administratifs.</p>"
        "<p><b>Propriétaire et éditeur :</b> Ministère de la Formation Professionnelle (MFP), "
        "République Démocratique du Congo.</p>"
        "<p>Développement : ACATECH.</p>"
        "<p>Le logiciel donne un score et des preuves ; la décision revient à un agent habilité.</p>")
