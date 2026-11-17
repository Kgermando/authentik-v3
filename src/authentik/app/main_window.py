"""Fenetre principale : enchaine accueil -> scan/import -> apercu + annee -> chargement -> resultats."""
from __future__ import annotations

import tempfile
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QThreadPool, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMainWindow, QMessageBox, QStackedWidget

from .. import pipeline
from ..ingest import SUPPORTED_EXT
from ..scan import ScannerInfo, find_scanners, probe, probe_range, scan_to_file
from ..store import AppConfig, Database, load_config, save_config
from .dialogs import DetailsDialog, StorageDialog, check_storage, show_about
from .references_dialog import ReferencesDialog
from .pages import HomePage, PreparePage, ProgressPage, ResultsPage, ScanPage
from .workers import Worker, WorkerPool

FILE_FILTER = "Documents (" + " ".join(f"*{e}" for e in sorted(SUPPORTED_EXT)) + ")"


def scan_and_prepare(scanner: ScannerInfo, folder: Path, progress) -> pipeline.Prepared:
    path = scan_to_file(scanner, folder, progress)
    return pipeline.prepare(path, from_scan=True, progress=progress)


def find_other_network(text: str) -> tuple[list[ScannerInfo], str]:
    """Adresse unique ou plage (contient « / » sans « :// »). Renvoie (scanners, message)."""
    if "/" in text and "://" not in text:
        found = probe_range(text)
        return found, (f"{len(found)} scanner(s) trouvé(s) sur la plage {text}." if found else
                       f"Aucun scanner eSCL joignable sur la plage {text}.")
    s = probe(text)
    if s is None:
        return [], (f"Aucun scanner eSCL joignable à l'adresse {text}. Vérifier l'adresse, que "
                    "le scanner est allumé et que ce réseau est accessible depuis ce poste "
                    "(routeur, VPN, pare-feu).")
    return [s], f"Scanner trouvé : {s.name}. Cliquer sur « Mémoriser » pour le garder."


class MainWindow(QMainWindow):
    def __init__(self, cfg: AppConfig | None = None):
        super().__init__()
        self.setWindowTitle("Authentik — Ministère de la Formation Professionnelle")
        self.resize(1280, 820)
        self.pool = WorkerPool(QThreadPool.globalInstance())
        self.cfg = cfg or load_config()
        self.db: Database | None = None
        self.prepared: pipeline.Prepared | None = None
        self.outcome: pipeline.Outcome | None = None
        self.scan_dir = Path(tempfile.mkdtemp(prefix="authentik_scan_"))

        self.stack = QStackedWidget()
        self.home, self.scan, self.prep = HomePage(), ScanPage(), PreparePage()
        self.progress, self.results = ProgressPage(), ResultsPage()
        for w in (self.home, self.scan, self.prep, self.progress, self.results):
            self.stack.addWidget(w)
        self.setCentralWidget(self.stack)
        self._menus()

        self.home.import_clicked.connect(self.import_file)
        self.home.scan_clicked.connect(self.open_scan)
        self.scan.back_clicked.connect(self.go_home)
        self.scan.search_clicked.connect(self.search_scanners)
        self.scan.scan_clicked.connect(self.start_scan)
        self.scan.add_clicked.connect(self.add_other_network)
        self.scan.remember_clicked.connect(self.remember_scanner)
        self.scan.forget_clicked.connect(self.forget_scanner)
        self.prep.cancel_clicked.connect(self.go_home)
        self.prep.analyse_clicked.connect(self.analyse)
        self.results.new_clicked.connect(self.go_home)
        self.results.details_clicked.connect(self.show_details)
        self.results.review_clicked.connect(self.review)
        self.home.references_clicked.connect(self.open_references)
        self.agent_name = ""

        self._open_database()
        self._update_home()

    # -- menus et base -------------------------------------------------------------------------
    def _menus(self) -> None:
        m = self.menuBar().addMenu("&Fichier")
        for text, slot, key in (("Importer un fichier…", self.import_file, QKeySequence.Open),
                                ("Scanner…", self.open_scan, None),
                                ("Références…", self.open_references, None),
                                ("Base de données…", self.edit_storage, None),
                                ("Quitter", self.close, QKeySequence.Quit)):
            a = QAction(text, self)
            if key is not None:
                a.setShortcut(key)
            a.triggered.connect(slot)
            m.addAction(a)
        h = self.menuBar().addMenu("&Aide")
        a = QAction("À propos", self)
        a.triggered.connect(lambda: show_about(self))
        h.addAction(a)

    def _open_database(self) -> None:
        problem = check_storage(self.cfg.database, self.cfg.documents_dir)
        if problem is None:
            self.db = Database(self.cfg.database)
        msgs = [m for m in (self.cfg.warning, problem) if m]
        self.statusBar().showMessage(
            " | ".join(msgs) if msgs else f"Base : {self.cfg.database}")
        if problem:
            QMessageBox.warning(self, "Base de données",
                                problem + "\n\nCorriger dans Fichier > Base de données.")

    def edit_storage(self) -> None:
        dlg = StorageDialog(self.cfg, self)
        if dlg.exec():
            self.cfg = load_config(self.cfg.ini_path)
            self._open_database()
        self._update_home()

    # -- navigation ------------------------------------------------------------------------------
    def go_home(self) -> None:
        self._update_home()
        self.stack.setCurrentWidget(self.home)

    def _update_home(self) -> None:
        if self.db is None:
            self.home.ref_status.setText("")
            return
        s = self.db.reference_summary()
        n = sum(x["documents"] for x in s)
        self.home.ref_status.setText(
            f"{n} document(s) de référence enregistré(s)" if n else
            "Aucun document de référence : les comparaisons ne sont pas possibles. "
            "Commencer par ajouter des certificats authentiques.")

    def open_references(self) -> None:
        if self.db is None:
            QMessageBox.warning(self, "Références", "Aucune base utilisable : corriger dans "
                                                    "Fichier > Base de données.")
            return
        ReferencesDialog(self).exec()
        self._update_home()

    def review(self, decision: str) -> None:
        aid = (self.outcome.details or {}).get("analysis_id") if self.outcome else None
        if not aid or self.db is None:
            return
        name, ok = QInputDialog.getText(self, "Décision de l'agent", "Nom de l'agent :",
                                        text=self.agent_name)
        if not ok or not name.strip():
            return
        note, ok = QInputDialog.getText(self, "Décision de l'agent", "Remarque (facultatif) :")
        if not ok:
            return
        self.agent_name = name.strip()
        self.db.add_review(aid, self.agent_name, decision, note.strip() or None)
        reviews = self.db.find_analysis(self.outcome.analysis_key)["reviews"]
        self.outcome.details["reviews"] = reviews
        self.results.show_reviews(reviews)

    def _run(self, fn, *args, on_done, step: str) -> None:
        self.progress.update(step, 0)
        self.stack.setCurrentWidget(self.progress)
        w = Worker(fn, *args)
        w.signals.progress.connect(self.progress.update)
        w.signals.finished.connect(on_done)
        w.signals.failed.connect(self._failed)
        self.pool.start(w)

    def _failed(self, message: str) -> None:
        QMessageBox.warning(self, "Authentik", message)
        self.go_home()

    # -- import ------------------------------------------------------------------------------
    def import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importer un document scanné", "", FILE_FILTER)
        if path:
            self.load_path(Path(path))

    def load_path(self, path: Path, from_scan: bool = False) -> None:
        self._run(pipeline.prepare, path, from_scan, on_done=self._prepared,
                  step="Lecture du document")

    def _prepared(self, prepared: pipeline.Prepared) -> None:
        self.prepared = prepared
        self.prep.show_prepared(prepared)
        self.stack.setCurrentWidget(self.prep)

    # -- scan --------------------------------------------------------------------------------
    def open_scan(self) -> None:
        self.stack.setCurrentWidget(self.scan)
        if self.scan.list.count() == 0:
            self.search_scanners()

    def search_scanners(self) -> None:
        self.scan.set_busy(True, "Recherche des scanners (réseau local et pilotes du poste)…")
        w = Worker(find_scanners, self.cfg.scanners, with_progress=False)
        w.signals.finished.connect(lambda s: (self.scan.set_busy(False), self.scan.set_scanners(s)))
        w.signals.failed.connect(lambda m: self.scan.set_busy(False, f"Recherche impossible : {m}"))
        self.pool.start(w)

    def add_other_network(self, text: str) -> None:
        self.scan.set_busy(True, f"Recherche de scanners à « {text} »…")
        w = Worker(find_other_network, text, with_progress=False)
        w.signals.finished.connect(self._other_network_found)
        w.signals.failed.connect(lambda m: self.scan.set_busy(False, m))
        self.pool.start(w)

    def _other_network_found(self, result) -> None:
        found, message = result
        known = {s.key for s in self.scan.scanners()}
        merged = self.scan.scanners() + [s for s in found if s.key not in known]
        self.scan.set_busy(False)
        self.scan.set_scanners(merged, message)
        if found:
            for i in range(self.scan.list.count()):
                if self.scan.list.item(i).data(Qt.UserRole).key == found[0].key:
                    self.scan.list.setCurrentRow(i)

    def _save_scanners(self, scanners: tuple) -> None:
        self.cfg = replace(self.cfg, scanners=scanners)
        try:
            save_config(self.cfg)
        except OSError as e:
            QMessageBox.warning(self, "Scanners", f"Impossible d'enregistrer la liste : {e}")

    def remember_scanner(self, s: ScannerInfo) -> None:
        if any(url.rstrip("/").lower() == s.address.rstrip("/").lower()
               for _, url in self.cfg.scanners):
            return
        self._save_scanners(self.cfg.scanners + ((s.name, s.address),))
        saved = replace(s, origin="enregistré")
        self.scan.set_scanners([saved if x.key == s.key else x for x in self.scan.scanners()],
                               f"« {s.name} » mémorisé : il apparaîtra à chaque ouverture.")

    def forget_scanner(self, s: ScannerInfo) -> None:
        self._save_scanners(tuple((n, u) for n, u in self.cfg.scanners
                                  if u.rstrip("/").lower() != s.address.rstrip("/").lower()))
        self.scan.set_scanners([x for x in self.scan.scanners() if x.key != s.key],
                               f"« {s.name} » retiré de la liste.")

    def start_scan(self, scanner: ScannerInfo) -> None:
        self._run(scan_and_prepare, scanner, self.scan_dir, on_done=self._prepared,
                  step="Connexion au scanner")

    # -- analyse -----------------------------------------------------------------------------
    def analyse(self, year: int) -> None:
        if self.db is None:
            QMessageBox.warning(self, "Base de données", "Aucune base utilisable : corriger dans "
                                                         "Fichier > Base de données.")
            return
        self._run(pipeline.run_analysis, self.prepared, year, self.cfg, self.db,
                  on_done=self._analysed, step="Analyse")

    def _analysed(self, outcome: pipeline.Outcome) -> None:
        self.outcome = outcome
        self.results.show_outcome(outcome)
        self.stack.setCurrentWidget(self.results)

    def show_details(self) -> None:
        if self.outcome is not None:
            DetailsDialog(self.outcome, self.cfg.crops_dir, self).exec()

    def closeEvent(self, event):
        self.pool.wait(3000)
        super().closeEvent(event)
