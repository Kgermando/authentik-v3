"""Point d'entree de Authentik.exe (PyInstaller)."""
from authentik.app.main import main

if __name__ == "__main__":
    raise SystemExit(main())
