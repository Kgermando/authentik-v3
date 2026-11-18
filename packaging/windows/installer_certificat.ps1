# Installation du certificat du MFP sur un poste (en administrateur), pour que Windows accepte
# Authentik.exe, l'installateur et le paquet .msix signes avec le certificat auto-signe du MFP.
#
#   powershell -ExecutionPolicy Bypass -File installer_certificat.ps1 -Cer MFP.cer

param([Parameter(Mandatory = $true)] [string]$Cer)

$ErrorActionPreference = "Stop"
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Write-Host "Lancer PowerShell en tant qu'administrateur." -ForegroundColor Red; exit 1 }
foreach ($magasin in @("Root", "TrustedPublisher", "TrustedPeople")) {
    Import-Certificate -FilePath $Cer -CertStoreLocation "Cert:\LocalMachine\$magasin" | Out-Null
    Write-Host "Certificat importe dans LocalMachine\$magasin"
}
