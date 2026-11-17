# Construction de l'installateur Windows de Authentik (AGENTS.md 5 bis).
# A executer SUR WINDOWS, depuis la racine du projet :
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 -Pfx C:\cles\MFP.pfx
#
# Prerequis sur le poste de construction :
#   - Python 3.12 64 bits (py -3.12)          https://www.python.org/downloads/windows/
#   - Inno Setup 6 (ISCC.exe)                 https://jrsoftware.org/isinfo.php
#   - Tesseract 5 + donnees fra, copie dans packaging\vendor\tesseract\ (tesseract.exe, *.dll, tessdata\fra.traineddata)
#   - Optionnel : signtool.exe (Windows SDK) et MFP.pfx pour signer
#
# NON EXECUTE a ce jour : a valider sur Windows, puis tester l'installation et la
# desinstallation sur un Windows vierge (machine virtuelle).

param(
    [string]$Pfx = "",                                   # certificat MFP (.pfx) ; vide = pas de signature
    [string]$TimestampUrl = "http://timestamp.digicert.com",
    [string]$Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "Echec : $what (code $LASTEXITCODE)" } }

# 0. Verifications
Step "Verifications"
if (-not (Test-Path "src\authentik\app\main.py")) {
    throw "src\authentik\app\main.py absent : l'interface (phase 1) doit exister avant de construire l'exe."
}
$Tess = "packaging\vendor\tesseract"
if (-not (Test-Path "$Tess\tesseract.exe") -or -not (Test-Path "$Tess\tessdata\fra.traineddata")) {
    throw "Tesseract manquant : copier tesseract.exe, ses DLL et tessdata\fra.traineddata dans $Tess"
}
if (-not (Test-Path $Iscc)) { throw "Inno Setup introuvable : $Iscc" }

# 1. Environnement Python 3.12 propre
Step "Environnement Python 3.12"
if (Test-Path ".venv-build") { Remove-Item -Recurse -Force ".venv-build" }
py -3.12 -m venv .venv-build; Check "creation du venv (Python 3.12 installe ?)"
$Py = ".venv-build\Scripts\python.exe"
& $Py -m pip install --upgrade pip; Check "pip"
& $Py -m pip install -e ".[dev]"; Check "installation des dependances"

# 2. Tests (AGENTS.md 0 bis 7 : apres toute mise a jour de bibliotheque)
if (-not $SkipTests) {
    Step "Tests"
    & $Py -m pytest -q; Check "pytest"
}

# 3. PyInstaller --onedir (pas --onefile : demarrage lent et antivirus)
Step "PyInstaller"
$PiArgs = @(
    "--noconfirm", "--clean", "--onedir", "--windowed",
    "--name", "Authentik",
    "--version-file", "packaging\version_info.txt",
    "--paths", "src",
    "--add-data", "$Tess;tesseract",
    "--add-data", "src\authentik\app\resources;authentik\app\resources",
    "--exclude-module", "torch", "--exclude-module", "torchvision", "--exclude-module", "easyocr",
    "--distpath", "dist", "--workpath", "build"
)
if (Test-Path "models") { $PiArgs += @("--add-data", "models;models") }
else { Write-Warning "Dossier models\ absent : aucun modele ONNX embarque." }
if (Test-Path "packaging\authentik.ico") { $PiArgs += @("--icon", "packaging\authentik.ico") }
& $Py -m PyInstaller @PiArgs "packaging\launcher.py"; Check "PyInstaller"

# 4. Signature de Authentik.exe (certificat auto-signe du MFP, demande de l'utilisateur)
$SignTool = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
function Sign($file) {
    if (-not $Pfx) { return }
    if (-not $SignTool) { throw "signtool.exe introuvable (installer le Windows SDK)" }
    $sec = Read-Host -AsSecureString "Mot de passe de $Pfx"
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
    & $SignTool sign /f $Pfx /p $plain /fd SHA256 /tr $TimestampUrl /td SHA256 $file
    $plain = $null
    Check "signature de $file"
}
if ($Pfx) { Step "Signature de Authentik.exe"; Sign "dist\Authentik\Authentik.exe" }

# 5. Installateur Inno Setup
Step "Installateur"
$Version = (& $Py -c "import authentik; print(authentik.__version__)").Trim()
$env:AUTHENTIK_VERSION = $Version
& $Iscc "packaging\authentik.iss"; Check "Inno Setup"
$Setup = "dist\Authentik-$Version-setup.exe"
if ($Pfx) { Step "Signature de l'installateur"; Sign $Setup }

Step "Termine"
Write-Host "Installateur : $Setup"
if ($Pfx) { Write-Host "Fournir MFP.cer avec la livraison (a importer sur chaque poste, AGENTS.md 5 bis)." }
