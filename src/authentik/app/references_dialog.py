"""Fenetre « References » : documents authentiques de comparaison et entrainement de la decision."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QProgressBar, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from ..config import SETTINGS
from ..decision import model_path
from ..ingest import SUPPORTED_EXT
from ..ingest.year import MIN_YEAR
from ..references import add_reference_documents, remove_reference_document
from ..training import MIN_PER_CLASS, reset_model, train_from_reviews
from .workers import Worker

FILE_FILTER = "Documents (" + " ".join(f"*{e}" for e in sorted(SUPPORTED_EXT)) + ")"
HELP = (
    "<b>Documents de référence</b> : des certificats <b>authentiques</b>, scannés à 300 DPI en "
    "couleur, comme les documents à contrôler. Pour chacun, le logiciel extrait le sceau et la "
    "signature (spécimens de comparaison) et mesure le papier et l'encre.<br>"
    "• Ressemblance et texte du sceau : dès 3 spécimens. Pression de l'encre et papier autour du "
    f"sceau : dès 5. Vieillissement : dès {SETTINGS.aging_min_docs_per_year} documents de la même "
    f"année (fiabilité réduite jusqu'à {SETTINGS.aging_reliable_docs}).<br>• Un sceau copié depuis l'un de ces documents (ou depuis tout document déjà analysé) "
    "est détecté.")


class AddReferencesDialog(QDialog):
    """Annee, signataire et texte du sceau pour un lot de fichiers."""

    def __init__(self, files: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ajouter des documents authentiques")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"{len(files)} fichier(s) sélectionné(s). Ils doivent tous être "
                             "authentiques et de la même année."))
        form = QFormLayout()
        self.year = QSpinBox()
        self.year.setRange(MIN_YEAR, date.today().year)
        self.year.setValue(date.today().year)
        self.owner = QLineEdit()
        self.owner.setPlaceholderText("ex. Directeur provincial (facultatif)")
        self.seal_text = QLineEdit()
        self.seal_text.setPlaceholderText("texte écrit autour du sceau (facultatif)")
        form.addRow("Année des documents :", self.year)
        form.addRow("Signataire :", self.owner)
        form.addRow("Texte du sceau :", self.seal_text)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Ajouter")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


class ReferencesDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.win = window
        self.setWindowTitle("Références")
        self.resize(900, 640)
        lay = QVBoxLayout(self)
        intro = QLabel(HELP)
        intro.setWordWrap(True)
        lay.addWidget(intro)

        lay.addWidget(QLabel("<b>Par année</b>"))
        self.years = QTableWidget(0, 5)
        self.years.setHorizontalHeaderLabels(["Année", "Documents", "Sceaux", "Signatures",
                                              "Vieillissement"])
        lay.addWidget(self.years, 1)

        lay.addWidget(QLabel("<b>Documents de référence</b>"))
        self.docs = QTableWidget(0, 4)
        self.docs.setHorizontalHeaderLabels(["Année", "Fichier", "Signataire", "Ajouté le"])
        self.docs.setSelectionBehavior(QAbstractItemView.SelectRows)
        lay.addWidget(self.docs, 2)
        for t in (self.years, self.docs):
            t.setEditTriggers(QAbstractItemView.NoEditTriggers)
            t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            t.verticalHeader().setVisible(False)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        lay.addWidget(self.bar)

        btns = QHBoxLayout()
        self.add_btn = QPushButton("Ajouter des documents authentiques…")
        self.remove_btn = QPushButton("Retirer")
        self.train_btn = QPushButton("Entraîner la décision")
        self.reset_btn = QPushButton("Décision provisoire")
        close = QPushButton("Fermer")
        for b in (self.add_btn, self.remove_btn):
            btns.addWidget(b)
        btns.addStretch()
        for b in (self.train_btn, self.reset_btn, close):
            btns.addWidget(b)
        lay.addLayout(btns)
        self.add_btn.clicked.connect(self.add_documents)
        self.remove_btn.clicked.connect(self.remove_selected)
        self.train_btn.clicked.connect(self.train)
        self.reset_btn.clicked.connect(self.reset)
        close.clicked.connect(self.accept)
        self.refresh()

    # -- affichage -------------------------------------------------------------------------------
    def refresh(self) -> None:
        db = self.win.db
        summary = db.reference_summary()
        self.years.setRowCount(len(summary))
        need = SETTINGS.aging_min_docs_per_year
        for i, s in enumerate(summary):
            n = s["with_measures"]
            aging = ("actif" if n >= SETTINGS.aging_reliable_docs else
                     f"actif, fiabilité réduite ({n}/{SETTINGS.aging_reliable_docs})" if n >= need else
                     f"{n}/{need} documents")
            for j, v in enumerate((s["year"], s["documents"], s["seals"], s["signatures"], aging)):
                self.years.setItem(i, j, QTableWidgetItem(str(v)))
        docs = db.reference_documents()
        self.docs.setRowCount(len(docs))
        for i, d in enumerate(docs):
            vals = (d["year"], d.get("file_name") or Path(d.get("stored_path") or "").name,
                    d.get("owner_name") or "",
                    d["added_at"][:10])
            for j, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                it.setData(Qt.UserRole, (d["source_sha256"], d["year"]))
                self.docs.setItem(i, j, it)
        trained = model_path(self.win.cfg).exists()
        self.reset_btn.setEnabled(trained)
        self.status.setText(
            ("Décision : <b>entraînée</b> sur les vérifications des agents." if trained else
             "Décision : <b>provisoire</b> (jamais « Conforme » seul). Pour l'entraîner, il faut "
             f"au moins {MIN_PER_CLASS} faux et {MIN_PER_CLASS} authentiques vérifiés par des "
             "agents sur la page de résultats."))

    def _busy(self, busy: bool) -> None:
        for b in (self.add_btn, self.remove_btn, self.train_btn, self.reset_btn):
            b.setEnabled(not busy)
        self.bar.setVisible(busy)

    # -- actions ---------------------------------------------------------------------------------
    def add_documents(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Certificats authentiques", "", FILE_FILTER)
        if not files:
            return
        dlg = AddReferencesDialog(files, self)
        if not dlg.exec():
            return
        self._busy(True)
        w = Worker(add_reference_documents, files, dlg.year.value(),
                   dlg.owner.text().strip() or None, dlg.seal_text.text().strip() or None,
                   self.win.cfg, self.win.db)
        w.signals.progress.connect(lambda s, p: (self.bar.setValue(p), self.status.setText(s)))
        w.signals.finished.connect(self._added)
        w.signals.failed.connect(lambda m: (self._busy(False), QMessageBox.warning(self, "Références", m)))
        self.win.pool.start(w)

    def _added(self, reports) -> None:
        self._busy(False)
        self.refresh()
        ok = sum(r.error is None for r in reports)
        QMessageBox.information(self, "Références", f"{ok}/{len(reports)} document(s) ajouté(s).\n\n"
                                + "\n".join(r.text() for r in reports))

    def remove_selected(self) -> None:
        rows = sorted({i.row() for i in self.docs.selectedIndexes()})
        if not rows:
            self.status.setText("Sélectionner un document à retirer.")
            return
        if QMessageBox.question(self, "Références", f"Retirer {len(rows)} document(s) de référence ?"
                                ) != QMessageBox.Yes:
            return
        for r in rows:
            sha, year = self.docs.item(r, 0).data(Qt.UserRole)
            remove_reference_document(sha, year, self.win.db)
        self.refresh()

    def train(self) -> None:
        self._busy(True)
        self.bar.setRange(0, 0)
        w = Worker(train_from_reviews, self.win.cfg, self.win.db, with_progress=False)
        w.signals.finished.connect(self._trained)
        w.signals.failed.connect(lambda m: (self._busy(False), QMessageBox.warning(self, "Décision", m)))
        self.win.pool.start(w)

    def _trained(self, report) -> None:
        self.bar.setRange(0, 100)
        self._busy(False)
        self.refresh()
        QMessageBox.information(self, "Entraîner la décision", report.text())

    def reset(self) -> None:
        if QMessageBox.question(self, "Décision", "Revenir à la décision provisoire ?") == QMessageBox.Yes:
            reset_model(self.win.cfg)
            self.refresh()
