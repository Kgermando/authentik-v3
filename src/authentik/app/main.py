"""Point d'entree de l'application : `python -m authentik` ou Authentik.exe."""
from __future__ import annotations

import sys

from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
from PySide6.QtWidgets import QApplication

from .. import __version__
from ..determinism import init_determinism


def _attach_console() -> bool:
    """Windows : une application fenetree n'a pas de console. Lancee depuis une invite de
    commandes (--verifier, --evaluer), on s'y rattache pour afficher les messages."""
    if sys.platform != "win32" or sys.stdout is not None:
        return sys.stdout is not None
    import ctypes
    if not ctypes.windll.kernel32.AttachConsole(-1):        # -1 : console du processus parent
        return False
    sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
    sys.stderr = sys.stdout
    return True


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    init_determinism()                       # AGENTS.md 0 bis, regle 1 : au demarrage
    if "--evaluer" in argv or "--verifier" in argv:
        _attach_console()
    if "--evaluer" in argv:                  # evaluation officielle (AGENTS.md 9), sans interface
        from ..eval.__main__ import main as eval_main
        i = argv.index("--evaluer")
        return eval_main(argv[i + 1:])
    if "--verifier" in argv:                 # diagnostic sans interface (apres installation)
        i = argv.index("--verifier")
        if i + 1 >= len(argv):
            print("Usage : authentik --verifier <document.pdf|png|jpg|tiff>")
            return 2
        from ..selfcheck import run
        if sys.stdout is not None:
            return run(argv[i + 1])
        # Windows (application sans console) : rapport ecrit dans un fichier texte
        from ..store.config_file import config_dir
        report = config_dir() / "verification.txt"
        report.parent.mkdir(parents=True, exist_ok=True)
        with open(report, "w", encoding="utf-8") as f:
            return run(argv[i + 1], out=f)
    app = QApplication(argv)
    app.setApplicationName("Authentik")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("Ministère de la Formation Professionnelle (MFP)")
    translator = QTranslator(app)               # boutons standard de Qt en francais
    if translator.load(QLocale(QLocale.French), "qtbase", "_",
                       QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(translator)
    app.setDesktopFileName("authentik")      # Ubuntu : associe la fenetre a authentik.desktop
    icon = Path(__file__).with_name("resources") / "authentik.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    from .main_window import MainWindow     # apres QApplication
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
