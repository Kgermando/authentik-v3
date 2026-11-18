# Construire Authentik sous Windows (.exe, .msi ou .msix)

Ce kit contient tout ce qu'il faut pour reconstruire Authentik sur un poste Windows, **sans
Internet** pour la partie Python :

| Dossier / fichier | Contenu |
|---|---|
| `wheels\` | tous les paquets Python pour Windows 64 bits / Python 3.12, aux **versions exactes** testées sous Ubuntu (103 tests réussis) |
| `..\packaging\windows\requirements-windows.lock` | liste figée de ces versions, avec empreintes SHA-256 (pip refuse un fichier modifié) |
| `outils\python-3.12.10-amd64.exe` | Python 3.12 (dernière version 3.12 avec installateur Windows) |
| `outils\tesseract-ocr-w64-setup-5.5.0.20241111.exe` | OCR Tesseract 5.5.0 (même version que sous Ubuntu) |
| `outils\fra.traineddata` | données françaises de Tesseract (fichier identique à celui testé sous Ubuntu) |
| `outils\innosetup-6.7.4.exe` | Inno Setup, pour l'installateur `.exe` |
| `outils\SHA256SUMS.txt` | empreintes des outils ci-dessus |

> **Statut honnête** : les scripts Windows n'ont **pas encore été exécutés sur Windows** (le
> développement s'est fait sous Ubuntu). Ils vérifient chaque étape et s'arrêtent avec un message
> clair. En cas d'erreur, noter le message affiché.

## 1. Préparer le poste de construction (une seule fois)

Windows 10 ou 11, 64 bits.

1. **Python** : lancer `outils\python-3.12.10-amd64.exe`. Cocher **« Add python.exe to PATH »**,
   garder **« py launcher »** coché, puis *Install Now*.
2. **Tesseract** : lancer `outils\tesseract-ocr-w64-setup-5.5.0.20241111.exe`, dossier par défaut
   (`C:\Program Files\Tesseract-OCR`). Le script de construction l'embarque dans l'application et
   y ajoute `fra.traineddata` : les postes utilisateurs n'auront rien à installer.
3. **Pour le .exe** : lancer `outils\innosetup-6.7.4.exe` (options par défaut).
4. **Pour le .msi** : télécharger `wix314-binaries.zip` (WiX Toolset 3.14.1,
   https://github.com/wixtoolset/wix3/releases/tag/wix3141rtm), le décompresser dans un dossier
   (par exemple `C:\outils\wix314`) et passer ce dossier au script avec `-WixDir`. Aucune
   installation ni droit administrateur requis. La signature utilise `signtool.exe` (Windows SDK, point 5).
5. **Pour le .msix** : installer le **Windows SDK** (outils `makeappx.exe` et `signtool.exe`),
   par exemple dans PowerShell : `winget install Microsoft.WindowsSDK.10.0.26100`
   (ou depuis https://developer.microsoft.com/windows/downloads/windows-sdk/).

Vérifier les fichiers si besoin : `Get-FileHash outils\*.exe` et comparer avec `SHA256SUMS.txt`.

## 2. Construire

Ouvrir PowerShell **dans le dossier du projet** (celui qui contient `pyproject.toml`) :

```powershell
# Installateur .exe (le plus simple, recommandé)
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1

# Installateur .msi signé (déploiement en entreprise)
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 -Cible msi -Pfx C:\cles\MFP.pfx -WixDir C:\outils\wix314
#   sans question : ajouter -PfxMotDePasseFichier C:\cles\MFP.pfx.motdepasse
#   (fichier créé par creer_certificat.ps1 -MotDePasseAleatoire, lisible par ce seul compte Windows)

# Paquet .msix (signature obligatoire)
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 -Cible msix -Pfx C:\cles\MFP.pfx

# Les deux, signés
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 -Cible tous -Pfx C:\cles\MFP.pfx
```

**Numéro de version** : chaque construction l'augmente automatiquement (0.1.1 → 0.1.2), et le
remet à l'ancien numéro si la construction échoue. Options :

```powershell
... build_windows.ps1 -Version minor     # 0.1.x -> 0.2.0 (major : 1.0.0)
... build_windows.ps1 -MemeVersion       # garder le numéro (même livraison que le .deb Ubuntu)
```

Historique des versions construites : `packaging\HISTORIQUE_VERSIONS.txt`.

Le script :

1. vérifie Python, Tesseract et les outils ;
2. crée un environnement Python propre et installe les paquets **depuis `windows_kit\wheels`** ;
3. lance les **tests** (environ 10 minutes) ;
4. construit l'application (`dist\Authentik\Authentik.exe`) avec Tesseract embarqué ;
5. **vérifie l'application construite** (`Authentik.exe --verifier`) ;
6. produit `dist\Authentik-<version>-setup.exe`, `dist\Authentik-<version>.msi` et/ou
   `dist\Authentik-<version>.msix`, signés si `-Pfx`.

## 3. Certificat de signature du MFP (pour signer, obligatoire pour le .msix)

À faire **une fois**, avec l'accord écrit du MFP :

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\creer_certificat.ps1 -Dossier C:\cles
```

- `MFP.pfx` : clé privée, **secrète**, gardée par le MFP (protégée par mot de passe).
- `MFP.cer` : certificat public, à installer sur chaque poste (étape 4).

Ce certificat est auto-signé (demande de l'utilisateur) : il n'est reconnu que sur les postes où
`MFP.cer` est installé ; ailleurs Windows affiche un avertissement, et refuse le `.msix`.

## 4. Installer sur les postes des agents

**Si le logiciel est signé** : une fois par poste, PowerShell **en administrateur** :

```powershell
powershell -ExecutionPolicy Bypass -File installer_certificat.ps1 -Cer MFP.cer
```

(le script est dans `packaging\windows\` ; le copier avec `MFP.cer`).

- **.exe** : double-cliquer `Authentik-<version>-setup.exe`. Les données (base, documents) vont dans
  `C:\ProgramData\Authentik`, partagé par les utilisateurs du poste et **conservé** à la
  désinstallation.
- **.msi** : double-cliquer `Authentik-<version>.msi`, ou en silencieux (GPO, SCCM, Intune) :
  `msiexec /i Authentik-<version>.msi /qn` (ajouter `DESKTOP_SHORTCUT=0` pour ne pas créer
  de raccourci sur le bureau). Mêmes dossiers de données que le .exe (`C:\ProgramData\Authentik`,
  conservé à la désinstallation). Une version plus récente remplace l'ancienne automatiquement.
  Ne pas installer le .exe **et** le .msi sur le même poste.
- **.msix** : double-cliquer `Authentik-<version>.msix`. Attention : un paquet MSIX ne peut pas donner
  de droits sur `C:\ProgramData`. Si l'application affiche l'avertissement « Paquet MSIX : les
  données… seront effacées à la désinstallation », choisir un dossier durable dans
  **Fichier > Base de données**. Pour un déploiement sur plusieurs postes, le **.exe est plus simple**.

Après installation : `"C:\Program Files\Authentik\Authentik.exe" --verifier un_document.pdf`
(depuis une invite de commandes) vérifie OCR, pilote de scan et analyse.

## 5. À tester sur Windows (non testé sous Ubuntu)

- scan par **pilote Windows (WIA)** avec les scanners du client ;
- scan **réseau eSCL** sur les imprimantes du client ;
- installation / désinstallation sur un **Windows vierge** (machine virtuelle) ;
- `.msix` : installation, lancement, emplacement des données.
