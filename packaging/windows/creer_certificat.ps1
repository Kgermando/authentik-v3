# Creation du certificat de signature auto-signe du MFP (AGENTS.md 5 bis).
#
# A FAIRE UNE SEULE FOIS, avec l'accord ecrit du MFP. La cle privee (MFP.pfx) reste sous la
# responsabilite du MFP, protegee par mot de passe. Ce choix (certificat auto-signe au nom du
# MFP) est une demande de l'utilisateur : il ne fonctionne que sur les postes ou MFP.cer est
# importe ; ailleurs, Windows affiche un avertissement.
#
#   powershell -ExecutionPolicy Bypass -File packaging\windows\creer_certificat.ps1 -Dossier C:\cles
#
# Option -MotDePasseAleatoire : pas de question ; un mot de passe aleatoire est genere et range
# CHIFFRE (DPAPI : lisible seulement par ce compte Windows, sur ce poste) dans
# <Dossier>\MFP.pfx.motdepasse. A passer ensuite a build_windows.ps1 -PfxMotDePasseFichier.
# Pour lire le mot de passe (a remettre au MFP) :
#   [Net.NetworkCredential]::new('', (Get-Content <Dossier>\MFP.pfx.motdepasse | ConvertTo-SecureString)).Password
#
# Ne PAS choisir un dossier synchronise (OneDrive, depot Git) : la cle privee doit rester locale.

param(
    [Parameter(Mandatory = $true)] [string]$Dossier,
    [switch]$MotDePasseAleatoire
)

$ErrorActionPreference = "Stop"
if (Test-Path (Join-Path $Dossier "MFP.pfx")) {
    throw "$Dossier\MFP.pfx existe deja : ne pas le remplacer (les postes ont deja son MFP.cer)."
}
New-Item -ItemType Directory -Force -Path $Dossier | Out-Null
$cert = New-SelfSignedCertificate -Type CodeSigningCert `
    -Subject "CN=Ministère de la Formation Professionnelle (MFP), O=MFP, C=CD" `
    -KeyAlgorithm RSA -KeyLength 3072 -HashAlgorithm SHA256 `
    -CertStoreLocation Cert:\CurrentUser\My -NotAfter (Get-Date).AddYears(5)
Export-Certificate -Cert $cert -FilePath (Join-Path $Dossier "MFP.cer") | Out-Null
if ($MotDePasseAleatoire) {
    $octets = New-Object byte[] 24
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($octets)   # aussi en PowerShell 5.1
    $mdp = ConvertTo-SecureString ([Convert]::ToBase64String($octets)) -AsPlainText -Force
    $mdp | ConvertFrom-SecureString | Set-Content -Encoding ASCII (Join-Path $Dossier "MFP.pfx.motdepasse")
} else {
    $mdp = Read-Host -AsSecureString "Mot de passe pour proteger MFP.pfx"
}
Export-PfxCertificate -Cert $cert -FilePath (Join-Path $Dossier "MFP.pfx") -Password $mdp | Out-Null
Write-Host "Cree : $Dossier\MFP.cer (a distribuer) et $Dossier\MFP.pfx (SECRET, a garder au MFP)."
Write-Host "Sujet : $($cert.Subject)"
