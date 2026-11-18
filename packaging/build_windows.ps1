# Construction de Authentik pour Windows : installateur .exe (Inno Setup) et/ou paquet .msix.
#
# A executer SUR WINDOWS 10/11 64 bits, dans PowerShell, depuis la racine du projet :
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1                 # .exe
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 -Cible msix -Pfx C:\cles\MFP.pfx
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 -Cible tous -Pfx C:\cles\MFP.pfx
#
# Options :
#   -Cible exe|msix|tous   ce qu'il faut produire (defaut : exe)
#   -Pfx <fichier>         certificat de signature du MFP (.pfx). OBLIGATOIRE pour le .msix.
#   -SansTests             ne pas lancer pytest (deconseille)
#   -EnLigne               telecharger les paquets Python au lieu d'utiliser windows_kit\wheels
#   -Version patch|minor|major   partie de la version a augmenter (defaut : patch, 0.1.0 -> 0.1.1)
#   -MemeVersion           garder le numero actuel (ex. meme livraison que le .deb Ubuntu)
#
# Chaque construction AUGMENTE la version (src\authentik\__init__.py) ; en cas d'echec, l'ancien
# numero est remis. Historique : packaging\HISTORIQUE_VERSIONS.txt.
#
# Prerequis : voir windows_kit\LISEZMOI.md (Python 3.12, Tesseract + fra, Inno Setup pour le
# .exe, Windows SDK pour le .msix). Ce script n'a PAS encore ete execute sur Windows : signaler
# toute erreur avec le message affiche.

param(
    [ValidateSet("exe", "msix", "tous")] [string]$Cible = "exe",
    [string]$Pfx = "",
    [string]$TimestampUrl = "http://timestamp.digicert.com",
    [switch]$SansTests,
    [switch]$EnLigne,
    [ValidateSet("patch", "minor", "major")] [string]$Version = "patch",
    [switch]$MemeVersion
)
$Partie = $Version

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Kit = Join-Path $Root "windows_kit"
$Lock = Join-Path $Root "packaging\windows\requirements-windows.lock"
$Vendor = Join-Path $Root "packaging\vendor\tesseract"

function Etape($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
$script:AncienneVersion = $null
$script:Py = $null
function Echec($msg) {
    Write-Host "`nECHEC : $msg" -ForegroundColor Red
    if ($script:AncienneVersion) {             # construction ratee : on remet l'ancien numero
        & $script:Py (Join-Path $Root "packaging\version.py") fixer $script:AncienneVersion | Out-Null
        Write-Host "Version remise a $($script:AncienneVersion)"
    }
    exit 1
}
function Verifier($quoi) { if ($LASTEXITCODE -ne 0) { Echec "$quoi (code $LASTEXITCODE)" } }

function Trouver-Outil($nom, $motifs) {
    foreach ($m in $motifs) {
        $f = Get-ChildItem -Path $m -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
        if ($f) { return $f.FullName }
    }
    $c = Get-Command $nom -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
}

# ---------------------------------------------------------------------------------------------
Etape "0. Verifications"
if (-not [Environment]::Is64BitOperatingSystem) { Echec "Windows 64 bits requis." }

$PyVer = $null
try { $PyVer = & py -3.12 -c "import sys; print(sys.version.split()[0])" } catch { $PyVer = $null }
if ($LASTEXITCODE -ne 0 -or -not $PyVer) {
    Echec "Python 3.12 introuvable. Installer windows_kit\outils\python-3.12.10-amd64.exe (cocher « Add python.exe to PATH » et « py launcher »)."
}
Write-Host "Python $PyVer"

# Tesseract : dossier embarque dans l'application (programme + DLL + tessdata\fra)
if (-not (Test-Path (Join-Path $Vendor "tesseract.exe"))) {
    $Installe = Join-Path $env:ProgramFiles "Tesseract-OCR"
    if (Test-Path (Join-Path $Installe "tesseract.exe")) {
        Write-Host "Copie de Tesseract depuis $Installe"
        New-Item -ItemType Directory -Force -Path $Vendor | Out-Null
        Copy-Item -Path (Join-Path $Installe "*") -Destination $Vendor -Recurse -Force
    } else {
        Echec "Tesseract introuvable. Installer windows_kit\outils\tesseract-ocr-w64-setup-*.exe (dossier par defaut), puis relancer."
    }
}
$Fra = Join-Path $Vendor "tessdata\fra.traineddata"
if (-not (Test-Path $Fra)) {
    $KitFra = Join-Path $Kit "outils\fra.traineddata"
    if (Test-Path $KitFra) {
        New-Item -ItemType Directory -Force -Path (Join-Path $Vendor "tessdata") | Out-Null
        Copy-Item $KitFra $Fra
    } else { Echec "Donnees francaises de Tesseract absentes : copier fra.traineddata dans $Vendor\tessdata" }
}
# Fichiers inutiles a embarquer (documentation, desinstallateur de Tesseract)
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $Vendor "tesseract-uninstall.exe")
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $Vendor "doc")

$Iscc = $null
if ($Cible -ne "msix") {
    $Iscc = Trouver-Outil "iscc.exe" @("${env:ProgramFiles(x86)}\Inno Setup *\ISCC.exe", "$env:ProgramFiles\Inno Setup *\ISCC.exe")
    if (-not $Iscc) { Echec "Inno Setup introuvable : installer windows_kit\outils\innosetup-*.exe" }
    Write-Host "Inno Setup : $Iscc"
}
$MakeAppx = $null
if ($Cible -ne "exe") {
    if (-not $Pfx) { Echec "Le .msix doit etre signe : indiquer -Pfx <certificat MFP .pfx> (voir packaging\windows\creer_certificat.ps1)." }
    $MakeAppx = Trouver-Outil "makeappx.exe" @("${env:ProgramFiles(x86)}\Windows Kits\10\bin\10.*\x64\makeappx.exe")
    if (-not $MakeAppx) { Echec "makeappx.exe introuvable : installer le Windows SDK (outils de signature et d'empaquetage)." }
    Write-Host "MakeAppx : $MakeAppx"
}
$SignTool = $null
$PfxMdp = $null
$Cert = $null
if ($Pfx) {
    if (-not (Test-Path $Pfx)) { Echec "Certificat introuvable : $Pfx" }
    $SignTool = Trouver-Outil "signtool.exe" @("${env:ProgramFiles(x86)}\Windows Kits\10\bin\10.*\x64\signtool.exe")
    if (-not $SignTool) { Echec "signtool.exe introuvable : installer le Windows SDK." }
    $sec = Read-Host -AsSecureString "Mot de passe du certificat $Pfx"
    $PfxMdp = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
    $Cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($Pfx, $PfxMdp)
    Write-Host "Certificat : $($Cert.Subject) (valable jusqu'au $($Cert.NotAfter))"
}

# ---------------------------------------------------------------------------------------------
Etape "1. Environnement Python 3.12 (versions figees)"
$Venv = Join-Path $Root ".venv-build"
if (Test-Path $Venv) { Remove-Item -Recurse -Force $Venv }
& py -3.12 -m venv $Venv; Verifier "creation de l'environnement Python"
$Py = Join-Path $Venv "Scripts\python.exe"
$script:Py = $Py
$Wheels = Join-Path $Kit "wheels"
if ((Test-Path $Wheels) -and -not $EnLigne) {
    Write-Host "Installation hors ligne depuis $Wheels"
    & $Py -m pip install --disable-pip-version-check --no-index --find-links $Wheels --require-hashes -r $Lock
} else {
    Write-Host "Installation en ligne"
    & $Py -m pip install --disable-pip-version-check --require-hashes -r $Lock
}
Verifier "installation des paquets Python"

# ---------------------------------------------------------------------------------------------
if (-not $SansTests) {
    Etape "2. Tests"
    $env:QT_QPA_PLATFORM = "offscreen"
    & $Py -m pytest -q
    Verifier "tests (pytest)"
    Remove-Item Env:\QT_QPA_PLATFORM
}

# ---------------------------------------------------------------------------------------------
Etape "3. Version"
$Ancienne = (& $Py packaging\version.py).Trim()
if ($MemeVersion) {
    $Version = $Ancienne
    Write-Host "Version inchangee : $Version"
} else {
    $Version = (& $Py packaging\version.py suivante $Partie).Trim()
    Verifier "changement de version"
    $script:AncienneVersion = $Ancienne
    Write-Host "Version : $Ancienne -> $Version"
}
$VersionInfo = Join-Path $Root "build\windows\version_info.txt"
& $Py packaging\version.py version-info $VersionInfo | Out-Null; Verifier "metadonnees de version"

Etape "4. PyInstaller (dossier, pas fichier unique)"
$env:PYTHONPATH = Join-Path $Root "src"
$PiArgs = @(
    "--noconfirm", "--clean", "--onedir", "--windowed",
    "--name", "Authentik",
    "--icon", "packaging\authentik.ico",
    "--version-file", $VersionInfo,
    "--paths", "src",
    "--add-data", "$Vendor;tesseract",
    "--add-data", "src\authentik\app\resources;authentik\app\resources",
    "--exclude-module", "torch", "--exclude-module", "torchvision", "--exclude-module", "easyocr",
    "--distpath", "dist", "--workpath", "build\windows"
)
if (Test-Path "models") { $PiArgs += @("--add-data", "models;models") }
& $Py -m PyInstaller @PiArgs "packaging\launcher.py"; Verifier "PyInstaller"
$Exe = Join-Path $Root "dist\Authentik\Authentik.exe"

Etape "5. Verification de l'application construite"
$Echantillon = Join-Path $Root "build\windows\echantillon.png"
& $Py -c "import sys; from PIL import Image, ImageDraw; im = Image.new('RGB', (2480, 3508), (236, 236, 228)); d = ImageDraw.Draw(im); d.text((300, 600), 'Fait a Kinshasa, le 12/03/2019', fill=(30, 30, 30)); im.save(sys.argv[1], dpi=(300, 300))" $Echantillon
Verifier "creation du document d'essai"
$p = Start-Process -FilePath $Exe -ArgumentList @("--verifier", "`"$Echantillon`"") -Wait -NoNewWindow -PassThru
if ($p.ExitCode -ne 0) { Echec "Authentik.exe --verifier a echoue (code $($p.ExitCode)). Voir le message ci-dessus." }

function Signer($fichier) {
    if (-not $Pfx) { return }
    & $SignTool sign /f $Pfx /p $PfxMdp /fd SHA256 /tr $TimestampUrl /td SHA256 $fichier
    Verifier "signature de $fichier"
}
if ($Pfx) { Etape "6. Signature de Authentik.exe"; Signer $Exe }

# ---------------------------------------------------------------------------------------------
if ($Cible -ne "msix") {
    Etape "7. Installateur .exe (Inno Setup)"
    $env:AUTHENTIK_VERSION = $Version
    & $Iscc "packaging\authentik.iss"; Verifier "Inno Setup"
    $Setup = Join-Path $Root "dist\Authentik-$Version-setup.exe"
    Signer $Setup
    Write-Host "Installateur : $Setup" -ForegroundColor Green
}

if ($Cible -ne "exe") {
    Etape "8. Paquet .msix"
    $Layout = Join-Path $Root "build\msix\layout"
    if (Test-Path $Layout) { Remove-Item -Recurse -Force $Layout }
    New-Item -ItemType Directory -Force -Path $Layout | Out-Null
    Copy-Item -Path (Join-Path $Root "dist\Authentik\*") -Destination $Layout -Recurse
    Copy-Item -Path (Join-Path $Root "packaging\windows\msix\Assets") -Destination $Layout -Recurse
    $Publisher = [Security.SecurityElement]::Escape($Cert.Subject)     # identique au certificat
    $Manifest = Get-Content -Raw -Encoding UTF8 (Join-Path $Root "packaging\windows\msix\AppxManifest.template.xml")
    $Manifest = $Manifest.Replace("__PUBLISHER__", $Publisher).Replace("__VERSION__", "$Version.0")
    [IO.File]::WriteAllText((Join-Path $Layout "AppxManifest.xml"), $Manifest, (New-Object Text.UTF8Encoding($false)))
    $Msix = Join-Path $Root "dist\Authentik-$Version.msix"
    & $MakeAppx pack /o /d $Layout /p $Msix; Verifier "MakeAppx"
    Signer $Msix
    Write-Host "Paquet MSIX : $Msix" -ForegroundColor Green
    Write-Host "Sur chaque poste : packaging\windows\installer_certificat.ps1 -Cer MFP.cer (administrateur), puis double-cliquer le .msix."
}

$PfxMdp = $null
& $Py packaging\version.py noter "windows ($Cible)" | Out-Null
$script:AncienneVersion = $null                 # succes : on garde la nouvelle version
Etape "Termine"
Write-Host "Authentik $Version"
if ($Pfx) { Write-Host "Fournir MFP.cer avec la livraison (voir windows_kit\LISEZMOI.md)." }
