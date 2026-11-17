#!/usr/bin/env bash
# Construction du paquet Ubuntu (.deb) de Authentik.
#
# A executer SUR UBUNTU, depuis la racine du projet :
#   bash packaging/build_ubuntu.sh            # tests + construction
#   bash packaging/build_ubuntu.sh --skip-tests
#
# Resultat : dist/authentik_<version>_<ubuntu>_amd64.deb
# Installation sur un poste :  sudo apt install ./authentik_<version>_<ubuntu>_amd64.deb
#   (apt installe aussi Tesseract + francais et les bibliotheques d'affichage necessaires)
#
# IMPORTANT : construire sur la PLUS ANCIENNE version d'Ubuntu a prendre en charge.
# Un paquet construit sur Ubuntu 26.04 ne fonctionne pas sur 24.04 ou 22.04 (bibliotheque C
# plus recente). Le nom du paquet indique la version d'Ubuntu de construction.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
SKIP_TESTS=0
[[ "${1:-}" == "--skip-tests" ]] && SKIP_TESTS=1

step() { printf '\n=== %s ===\n' "$1"; }

# 0. Verifications
step "Verifications"
[[ "$(uname -m)" == "x86_64" ]] || { echo "Architecture non prise en charge : $(uname -m)"; exit 1; }
command -v dpkg-deb >/dev/null || { echo "dpkg-deb introuvable (systeme Debian/Ubuntu requis)"; exit 1; }
PY="$ROOT/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
    command -v uv >/dev/null || { echo "Python 3.12 absent : installer uv (https://docs.astral.sh/uv/)"; exit 1; }
    uv venv --python 3.12 .venv
fi
"$PY" -c 'import sys; assert sys.version_info[:2] in ((3, 11), (3, 12)), sys.version' \
    || { echo "Python 3.11 ou 3.12 requis dans .venv"; exit 1; }

# 1. Dependances (installation identique a pyproject.toml)
step "Dependances"
if command -v uv >/dev/null; then
    UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT:-300}" uv pip install --python "$PY" -e ".[dev]"
else
    "$PY" -m pip install -e ".[dev]"
fi

VERSION="$("$PY" -c 'import authentik; print(authentik.__version__)')"
# ne pas « sourcer » /etc/os-release : il definit aussi VERSION (conflit avec la version du logiciel)
DISTRO="ubuntu$( (. /etc/os-release && echo "$VERSION_ID") )"
DEB="dist/authentik_${VERSION}_${DISTRO}_amd64.deb"

# 2. Tests
if [[ $SKIP_TESTS -eq 0 ]]; then
    step "Tests"
    QT_QPA_PLATFORM=offscreen "$PY" -m pytest -q
fi

# 3. PyInstaller --onedir
step "PyInstaller"
BUILD="$ROOT/build/ubuntu"
rm -rf "$BUILD"
ARGS=(--noconfirm --clean --onedir --windowed --name authentik
      --paths "$ROOT/src"
      --add-data "$ROOT/src/authentik/app/resources:authentik/app/resources"
      --exclude-module torch --exclude-module torchvision --exclude-module easyocr
      --distpath "$BUILD/dist" --workpath "$BUILD/work" --specpath "$BUILD")
if [[ -d models ]]; then ARGS+=(--add-data "$ROOT/models:models"); else echo "AVERTISSEMENT : models/ absent, aucun modele ONNX embarque."; fi
"$PY" -m PyInstaller "${ARGS[@]}" packaging/launcher.py

# 4. Arborescence du paquet
step "Paquet .deb"
PKG="$BUILD/pkg"
mkdir -p "$PKG/DEBIAN" "$PKG/opt" "$PKG/usr/bin" "$PKG/usr/share/applications" \
         "$PKG/usr/share/icons/hicolor/256x256/apps" "$PKG/usr/share/doc/authentik"
cp -a "$BUILD/dist/authentik" "$PKG/opt/authentik"
ln -s /opt/authentik/authentik "$PKG/usr/bin/authentik"
install -m 644 packaging/authentik.png "$PKG/usr/share/icons/hicolor/256x256/apps/authentik.png"
install -m 644 GUIDE.md "$PKG/usr/share/doc/authentik/GUIDE.md"

cat > "$PKG/usr/share/applications/authentik.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Authentik
GenericName=Contrôle des certificats administratifs
Comment=Aide au contrôle des certificats (Ministère de la Formation Professionnelle)
Exec=/opt/authentik/authentik
Icon=authentik
Terminal=false
Categories=Graphics;Scanning;
StartupWMClass=authentik
EOF

cat > "$PKG/usr/share/doc/authentik/copyright" <<EOF
Authentik ${VERSION}
Propriétaire et éditeur : Ministère de la Formation Professionnelle (MFP),
République Démocratique du Congo. Tous droits réservés.
Développement : ACATECH.
EOF

SIZE_KB="$(du -sk "$PKG" | cut -f1)"
cat > "$PKG/DEBIAN/control" <<EOF
Package: authentik
Version: ${VERSION}
Section: graphics
Priority: optional
Architecture: amd64
Maintainer: Ministère de la Formation Professionnelle (MFP)
Installed-Size: ${SIZE_KB}
Depends: tesseract-ocr, tesseract-ocr-fra, libgl1, libegl1, libfontconfig1, libdbus-1-3,
 libxkbcommon-x11-0, libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1,
 libxcb-randr0, libxcb-render-util0, libxcb-shape0, libxcb-xinerama0, libxcb-xkb1,
 libglib2.0-0t64 | libglib2.0-0
Recommends: sane-utils
Description: Aide au contrôle des certificats administratifs
 Authentik aide à repérer les certificats falsifiés (sceau ou signature collés,
 sceau reproduit, papier et encre qui n'ont pas l'âge du document).
 Le logiciel donne un score et des preuves ; un agent habilité décide.
 Scan réseau (eSCL/AirScan), pilotes SANE, ou import de fichiers PDF et images.
EOF

# Mise a jour des menus et icones a l'installation / desinstallation
for script in postinst postrm; do
cat > "$PKG/DEBIAN/$script" <<'EOF'
#!/bin/sh
set -e
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
exit 0
EOF
chmod 755 "$PKG/DEBIAN/$script"
done

# droits standard : lecture pour tous, ecriture pour root seulement
chmod -R u=rwX,go=rX "$PKG"
chmod 755 "$PKG/DEBIAN/postinst" "$PKG/DEBIAN/postrm"

mkdir -p dist
dpkg-deb --root-owner-group -Zxz --build "$PKG" "$DEB"

step "Termine"
dpkg-deb --info "$DEB" | sed -n '1,12p'
ls -lh "$DEB"
echo
echo "Installation :  sudo apt install ./$DEB"
echo "Lancement    :  menu des applications > Authentik, ou commande « authentik »"
echo "Vérification :  authentik --verifier <un document scanné>"
