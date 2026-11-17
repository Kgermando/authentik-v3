"""Execution en arriere-plan (QThreadPool) : la fenetre reste reactive pendant l'analyse."""
from __future__ import annotations

import traceback
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, Signal


class WorkerSignals(QObject):
    progress = Signal(str, int)      # etape, pourcentage
    finished = Signal(object)        # resultat
    failed = Signal(str)             # message pour l'utilisateur


class Worker(QRunnable):
    """Execute `fn(*args, progress=..., **kwargs)` dans un fil du QThreadPool.

    Les erreurs ne font jamais planter l'application : elles sont renvoyees par `failed`.
    """

    def __init__(self, fn: Callable, *args, with_progress: bool = True, **kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.with_progress = with_progress
        self.signals = WorkerSignals()
        # Pas de suppression automatique : sinon l'objet `signals` peut etre detruit avant que
        # la fenetre ait recu `finished`/`failed` (message perdu, ecran bloque). La fenetre garde
        # une reference jusqu'a la remise du resultat (voir WorkerPool.start).
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            if self.with_progress:
                self.kwargs["progress"] = self.signals.progress.emit
            result = self.fn(*self.args, **self.kwargs)
        except Exception as e:                           # noqa: BLE001 - montre a l'utilisateur
            traceback.print_exc()
            self.signals.failed.emit(str(e) or type(e).__name__)
        else:
            self.signals.finished.emit(result)


class WorkerPool:
    """Lance des Worker et les garde en vie jusqu'a la remise de leur resultat."""

    def __init__(self, pool):
        self.pool = pool
        self._active: set[Worker] = set()

    def start(self, worker: Worker) -> Worker:
        self._active.add(worker)
        release = lambda *_: self._active.discard(worker)     # noqa: E731
        worker.signals.finished.connect(release)
        worker.signals.failed.connect(release)
        self.pool.start(worker)
        return worker

    def wait(self, msecs: int) -> bool:
        return self.pool.waitForDone(msecs)
