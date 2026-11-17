# AGENTS.md — Instructions de construction d'Authentik

Tu es un ingénieur logiciel Python senior. Tu construis **Authentik**, un logiciel de bureau Windows qui aide à repérer les certificats administratifs falsifiés (sceau et signature collés d'un autre document, papier et encre qui n'ont pas l'âge de leur année, sceau reproduit au lieu d'être tamponné). **Propriétaire : le Ministère de la Formation Professionnelle (MFP), RDC.** Langage : **Python uniquement**.

Lis ce document en entier avant d'écrire du code. Il contient les règles, l'architecture, la liste des fichiers à créer et le **contenu complet** des fichiers déjà rédigés (section 7). Ne les réécris pas : crée-les tels quels, puis travaille phase par phase (section 10).


## 0. Règles de travail

- Ne prétends jamais qu'un pourcentage de fiabilité est atteint tant qu'il n'a pas été mesuré avec le protocole de la section 9. L'objectif est **au moins 90 % des faux détectés, avec au plus 5 % de vrais documents signalés à tort**, mesuré sur un lot de test jamais vu.
- Ne présente jamais un résultat de test sur images de synthèse comme une performance réelle.
- Écris des tests pour chaque analyseur. Exécute-les avant de dire que quelque chose marche.
- Quand une information manque (section 11), pose la question à l'utilisateur au lieu de deviner.
- N'implémente pas ce que l'utilisateur a écarté : **pas de registre des certificats émis, pas de QR code signé**.
- Garde la page de résultats courte (section 2). Le détail complet est réservé au bouton « En savoir plus ».
- **Première action : crée les fichiers de la section 7 tels quels, installe les dépendances, lance `pytest`, et rapporte le résultat à l'utilisateur avant d'aller plus loin.** Ces fichiers n'ont **pas** été exécutés dans leur forme finale (voir section 7). Corrige les erreurs que tu trouves et dis lesquelles.


## 0 bis. Fiabilité : le même document donne toujours le même résultat

Exigence de l'utilisateur : un document analysé deux fois doit produire **exactement** les mêmes résultats. Règles obligatoires (le module `determinism.py`, section 7, les met en œuvre) :

1. Appeler `init_determinism()` au démarrage de l'application **et** au début de chaque analyse : graine fixe pour OpenCV (RANSAC), `random` et `numpy`, et un seul thread OpenCV.
2. Aucun hasard non fixé dans le code d'analyse. Les listes de comparaison (documents connus, spécimens) sont **triées dans un ordre fixe** avant d'être parcourues.
3. Les scores sont arrondis (`round_score`, 4 décimales) **avant** d'être comparés à un seuil.
4. Les paramètres d'extraction et de scan sont fixes (300 DPI, couleur, sans amélioration automatique). Aucune « amélioration d'image » dépendante du contenu avant les mesures.
5. **Mémoïsation** : le résultat d'une analyse est enregistré avec une clé `analysis_key` (empreinte du fichier + version du logiciel + empreintes des modèles + version des profils + paramètres). Même clé : on **renvoie le résultat enregistré** sans recalculer. Si le logiciel, un modèle, un profil de vieillissement ou un seuil change, la clé change et le résultat est recalculé : ce changement doit apparaître dans le rapport.
6. Les modèles tournent en ONNX sur CPU. PyTorch n'est pas utilisé à l'exécution. Pas d'inférence GPU (résultats non identiques d'une machine à l'autre).
7. Limite honnête : les calculs flottants peuvent différer à l'infime entre deux ordinateurs ou deux versions de bibliothèques. L'arrondi (règle 3) et la mémoïsation (règle 5) évitent que cela change un verdict sur le même poste ; une mise à jour de bibliothèque doit être suivie de `pytest` et d'une réévaluation.
8. Un test automatique (`test_determinism.py`) vérifie que deux analyses du même fichier sont identiques, même quand l'état aléatoire d'OpenCV est perturbé entre les deux.


## 1. Objectif et contraintes

- Logiciel de bureau pour Windows (priorité), macOS et Ubuntu. Un seul langage : **Python 3.11 ou 3.12**.
- **Livrable principal : un installateur Windows (`.exe` ou `.msi`)** que l'utilisateur installe par double-clic, sans installer Python. Voir la section 5 bis.
- Deux entrées : **scan direct depuis une imprimante/scanner du réseau**, ou **import d'un fichier déjà scanné** (PDF, PNG, JPEG, TIFF).
- Pas de Docker. PostgreSQL pour l'historique, les spécimens et les documents de référence.
- Traitement local : le document n'est pas envoyé à un service externe.
- Le logiciel ne décide pas seul. Au-dessus du seuil, un agent humain valide.

## 2. Comportement attendu

### Parcours
1. Écran d'accueil : deux boutons, **Scanner** et **Importer un fichier**.
2. Scanner : liste des imprimantes trouvées sur le réseau, choix, aperçu, bouton **Analyser**. Réglages de scan **fixes** : 300 DPI, couleur, sans amélioration automatique (sinon les comparaisons de vieillissement ne valent rien).
3. Année du document : lue par OCR sur la date, affichée, modifiable avant l'analyse.
4. Chargement : barre de progression avec l'étape en cours. L'analyse tourne dans un fil séparé (`QThreadPool`), la fenêtre reste réactive.
5. Page de résultats.

### Page de résultats : deux colonnes (`QSplitter`)
- **Colonne 1** : l'image scannée entière, avec des cadres de couleur sur le sceau et la signature (`QGraphicsView` + `QGraphicsRectItem`). Un clic sur une ligne de la colonne 2 met le cadre correspondant en évidence.
- **Colonne 2**, courte : le verdict (**Conforme**, **À vérifier** ou **Suspect**) avec son pourcentage, une phrase de résumé, puis **une ligne par indication**, chacune avec un mot et une couleur (vert, orange, rouge) :
  - Sceau
  - Signature
  - Vieillissement
  - Pression de l'encre
- Toutes les indications sont visibles d'emblée, côte à côte. **Aucune n'est cachée derrière « En savoir plus ».**
- Bouton **En savoir plus** : ouvre tout ce qui a été constaté (sceau et signature agrandis à côté du spécimen le plus proche, document avec lequel une copie a été trouvée, mesures de vieillissement sur la plage normale de l'année, profil de pression, confiance de chaque contrôle, indications masquées avec leur motif) et l'export en rapport PDF.

### Règle de masquage
Une ligne n'apparaît que si elle a **au moins une mesure valide**. Sans valeur, la ligne disparaît et les autres se répartissent l'espace.
- Vieillissement : masqué quand l'année compte moins de 30 documents de référence.
- Pression de l'encre : masquée si la zone d'encre est trop petite pour mesurer (`pressure_features` renvoie `None`), ou si le document est déclaré comme copie certifiée.
- Signature : masquée si le type de certificat n'en comporte pas.
- Si un élément est **attendu mais absent**, la ligne reste affichée avec « Introuvable » : c'est un constat, pas une absence de valeur.
- Quand une ligne disparaît, les lignes restantes affichent une courte raison en dessous (par exemple « copie d'un document du 12 mars »). Les lignes masquées et leur motif (par exemple « moins de 30 documents de référence en 2019 ») sont consultables dans « En savoir plus ».

## 3. Les contrôles

La ressemblance d'un sceau à sa référence ne prouve rien : un faux porte souvent un **vrai** sceau copié d'un autre document. Le point décisif est la **preuve de copie**, complétée par la **pression de l'encre** et le **vieillissement**.

| Analyseur | Détecte | Méthode | Limite connue |
| --- | --- | --- | --- |
| `seal_text` | Sceau dont le texte circulaire est faux | `cv2.warpPolar` pour dérouler le cercle, OCR, comparaison au texte attendu | Sceau très pâle ou masqué |
| `reference` | Forme ou tracé qui s'écarte des spécimens de l'année | Embeddings ONNX, distance cosinus (pgvector) | Les signatures varient naturellement : seule, cette mesure ne rejette jamais |
| `copy` | Sceau ou signature collés depuis un autre document | AKAZE + RANSAC, puis corrélation de l'encre à l'intérieur des traits | Copie très dégradée par un second scan |
| `integrity` | Zone ajoutée après coup | Bruit, netteté et couleur comparés au papier voisin, halo de contour | Peu efficace sur un scan unique très compressé |
| `pressure` | Sceau reproduit sur papier (photocopie, impression puis rescan) au lieu d'un tampon d'encre original | Densité d'encre, étendue des tons, netteté des bords | Ne voit pas un vrai sceau copié numériquement (rôle de `copy`) ; **le relief n'est pas mesuré sur un scan à plat** |
| `aging` | Papier ou encre qui n'ont pas l'âge de leur année ; sceau ou signature qui n'ont pas vieilli comme le texte | Mesures Lab, score z modifié contre les documents authentiques de la même année | Un faux imprimé sur papier d'époque passe ce contrôle seul |

**Extraction.** Sceau : segmentation HSV puis `cv2.HoughCircles`. Signature : binarisation d'Otsu et composantes connexes dans la zone attendue.

**Pourquoi `copy` et `pressure` se complètent.** `copy` attrape un vrai sceau copié numériquement (il garde sa pression d'origine, donc `pressure` ne le voit pas). `pressure` attrape un sceau reproduit sur papier puis scanné.

**Vieillissement.** Chaque document est comparé aux documents **authentiques de la même année**. Un sceau ou une signature collés sur un vieux papier gardent l'encre, la netteté et le grain du document d'origine : ils ne vieillissent pas comme le reste de la page.

## 4. Stack

| Besoin | Bibliothèque |
| --- | --- |
| Interface | `PySide6` |
| Découverte des scanners | `zeroconf` |
| Pilote de scan | `httpx`, `xml.etree` (client eSCL/AirScan) |
| PDF | `PyMuPDF` (rasterisation 300 DPI) |
| Vision | `opencv-python-headless>=4.10,<5`, `scikit-image`, `numpy`, `scipy` |
| OCR | `pytesseract` (Tesseract 5, données `fra`) ; `easyocr` ou `paddleocr` en secours |
| IA entraînement | `torch`, `torchvision` (poste de dev uniquement) |
| IA exécution | `onnxruntime` |
| Fusion | `scikit-learn` |
| Empreintes | `imagehash` |
| Base de données | `psycopg` (v3), `pgvector`, `alembic` |
| Stockage local et mot de passe | `sqlite3` (bibliothèque standard), `configparser`, `keyring` |
| Rapport PDF | `reportlab` |
| Configuration | `pydantic-settings` |
| Tests | `pytest` |
| Livraison | `pyinstaller` |

**Pièges à respecter**
- **OpenCV : figer `opencv-python-headless>=4.10,<5`.** En 5.0, `cv2.AKAZE_create` n'existe plus dans le module principal (vérifié).
- `pytesseract` n'est qu'une enveloppe : le programme Tesseract doit être installé ou embarqué dans l'installateur.
- PyTorch ne sert qu'à l'entraînement. Ne pas l'embarquer dans l'installateur : exporter le modèle en ONNX.
- PyInstaller : construire chaque version sur le système cible.

**Scan réseau (eSCL).** Découvrir les imprimantes via mDNS (`_uscan._tcp` et `_uscans._tcp`). Le chemin racine est dans l'enregistrement TXT `rs` (souvent `eSCL`). Lire `ScannerCapabilities`, créer un travail avec `POST …/ScanJobs` (XML `ScanSettings` : 300 DPI, couleur), puis récupérer les pages avec `GET …/ScanJobs/{id}/NextDocument`. **Je n'ai pas vérifié ce protocole sur une imprimante réelle : teste-le sur celle du client avant de t'appuyer dessus.** Si elle ne gère pas eSCL, l'import de fichier reste la voie de repli ; WIA (Windows, `pywin32`) ou SANE (Linux) peuvent s'ajouter.


## 5. Structure du projet et fichiers à créer

```text
authentik/
├── pyproject.toml
├── requirements.txt
├── src/authentik/
│   ├── determinism.py        # fourni
│   ├── config.py             # fourni : seuils provisoires
│   ├── app/                  # PySide6 : fenêtre, scan, page de résultats
│   ├── scan/                 # découverte zeroconf, client eSCL
│   ├── ingest/               # PDF, image, année par OCR
│   ├── extract/              # sceau, signature, masques papier et texte
│   ├── analyzers/            # base, copy, pressure, aging (fournis) ; seal_text, reference, integrity (à écrire)
│   ├── fusion/               # fusion.py (fourni)
│   ├── store/                # schema.sql (fourni) ; psycopg et alembic (à écrire)
│   ├── report/               # rapport PDF (reportlab)
│   └── eval/                 # metrics.py (fourni) ; __main__.py (à écrire)
├── models/                   # embeddings ONNX
├── tests/synthetic/          # synth.py + 5 fichiers de tests (fournis)
└── packaging/                # PyInstaller, installateur, signature
```

Contrat commun des analyseurs : chacun renvoie un `Signal(risk, confidence, evidence)` (`risk` de 0 conforme à 1 falsifié), ou **`None` quand il n'a aucune valeur** : c'est ce qui masque la ligne correspondante sur la page de résultats.

| Fichier(s) | Statut |
| --- | --- |

| `pyproject.toml`, `requirements.txt` | Fourni (section 7) |
| `src/authentik/determinism.py`, `config.py` | Fourni |
| `src/authentik/analyzers/{base,copy,pressure,aging}.py` | Fourni |
| `src/authentik/fusion/fusion.py` | Fourni |
| `src/authentik/eval/metrics.py` | Fourni (la commande `python -m authentik.eval` reste à écrire) |
| `src/authentik/store/schema.sql` | Fourni (accès base et migrations alembic à écrire) |
| `tests/synthetic/*.py` (6 fichiers) | Fourni |
| `src/authentik/scan/` (zeroconf, client eSCL) | **À écrire** (phase 1) |
| `src/authentik/ingest/` (PDF, image, année par OCR) | **À écrire** (phase 1) |
| `src/authentik/extract/` (sceau, signature, masques) | **À écrire** (phase 2) |
| `src/authentik/analyzers/{seal_text,reference,integrity}.py` | **À écrire** (phase 2) |
| `src/authentik/store/` (`config_file.py`, `local_sqlite.py`, `postgres.py`, `sync.py`, migrations alembic) | **À écrire** (phase 1 pour la connexion et SQLite, voir 6 bis) |
| `src/authentik/app/` (PySide6 : fenêtre, scan, page de résultats, écran « Connexion à la base ») | **À écrire** (phases 1 et 4) |
| `src/authentik/report/` (rapport PDF reportlab) | **À écrire** (phase 4) |
| `src/authentik/eval/__main__.py` (commande d'évaluation) | **À écrire** (phase 5) |
| `models/` (embeddings ONNX) | **À produire** (phase 2) |
| `packaging/` (PyInstaller, Inno Setup ou WiX, signature, `build_windows.ps1`) | **À écrire** (phase 5, voir 5 bis) |



## 5 bis. Livraison Windows (.exe / .msi)

Construire sur une machine Windows, en deux étapes :
1. **PyInstaller en mode `--onedir`** (pas `--onefile`, plus lent au démarrage et plus souvent bloqué par les antivirus) : produit `Authentik.exe` et ses dépendances dans un dossier. Embarquer le programme Tesseract et les données `fra`, ainsi que les modèles ONNX du dossier `models/`.
2. **Installateur** autour de ce dossier :
   - `.exe` : Inno Setup (le plus simple : raccourci bureau, menu Démarrer, désinstallation) ; ou
   - `.msi` : WiX Toolset, si le client exige un `.msi` pour un déploiement en entreprise.
   Livrer **l'un ou l'autre selon la demande du client** (question à poser, section 11).

Points à traiter :
- PostgreSQL n'est pas embarqué par défaut : soit l'installateur demande l'adresse d'un serveur existant, soit il installe PostgreSQL en option. Choix à faire avec l'utilisateur.
- **Propriétaire et éditeur : le Ministère de la Formation Professionnelle (MFP)**, pas ACATECH. Le nom affiché à l'installation, les métadonnées du `.exe` (CompanyName, LegalCopyright), l'installateur et les écrans « À propos » portent le nom du MFP. ACATECH peut figurer comme développeur dans « À propos » seulement.
- **Signature de code auto-signée** (certificat du MFP). Elle fonctionne uniquement sur les postes où le certificat est installé : le certificat est importé à la main dans « Autorités de certification racines de confiance » et « Éditeurs approuvés ». Sur un autre poste, Windows affichera l'avertissement.
  - Cette approche (nom du MFP comme éditeur, certificat auto-signé) est **une demande de l'utilisateur**, pas une recommandation de l'agent.
  - Créer le certificat **avec l'accord écrit du MFP**, et garder la clé privée (`.pfx`) sous la responsabilité du MFP, protégée par mot de passe.
  - Génération (PowerShell, à valider) :
    ```powershell
    $cert = New-SelfSignedCertificate -Type CodeSigningCert `
      -Subject "CN=Ministère de la Formation Professionnelle (MFP), O=MFP, C=CD" `
      -KeyAlgorithm RSA -KeyLength 3072 -HashAlgorithm SHA256 `
      -CertStoreLocation Cert:\CurrentUser\My -NotAfter (Get-Date).AddYears(5)
    Export-Certificate -Cert $cert -FilePath MFP.cer
    Export-PfxCertificate -Cert $cert -FilePath MFP.pfx -Password (Read-Host -AsSecureString)
    ```
  - Installation sur chaque poste (administrateur) :
    ```powershell
    Import-Certificate -FilePath MFP.cer -CertStoreLocation Cert:\LocalMachine\Root
    Import-Certificate -FilePath MFP.cer -CertStoreLocation Cert:\LocalMachine\TrustedPublisher
    ```
  - Signature avec `signtool`, avec horodatage, de `Authentik.exe` **et** de l'installateur :
    ```powershell
    signtool sign /f MFP.pfx /p <motdepasse> /fd SHA256 /tr <url_horodatage> /td SHA256 Authentik.exe
    ```
  - Intégrer ces étapes à `packaging/build_windows.ps1` et fournir `MFP.cer` avec la livraison.
- Tester l'installation et la désinstallation sur un Windows vierge (machine virtuelle), pas seulement sur le poste de développement.
- Automatiser la construction dans un script (`packaging/build_windows.ps1`).
- Je n'ai pas exécuté cette chaîne de construction ici : à valider sur Windows.


> **État d'avancement (2026-11-17).** Phases 1 à 5 écrites et testées **sur images de synthèse uniquement** (aucune mesure sur de vrais documents). Écarts assumés par rapport au texte ci-dessous :
> - `reference` utilise un descripteur classique (HOG, `analyzers/reference.py`) au lieu d'embeddings ONNX : aucun modèle ne peut être entraîné sans les spécimens du client. Remplaçable via `embed()`.
> - Tant que la fusion n'est pas entraînée (menu Références > Entraîner la décision, à partir des décisions d'agents), `decision.py` applique des règles **provisoires** et ne rend jamais « Conforme » seul.
> - Documents de référence : menu **Références** (`references.py`), qui crée les spécimens, les empreintes pour la détection de copie et les plages de vieillissement.
> - Évaluation : `python -m authentik.eval DOSSIER` ou `authentik --evaluer DOSSIER` ; « objectif atteint » reste « non établi » sous 200 faux et 200 authentiques dans le test.
> - **Décision de l'utilisateur (2026-11-17) : vieillissement actif dès 5 documents par année** (au lieu de 30). De 5 à 29 : limite z élargie (× √(30/n)), ligne jamais rouge, ne conclut pas « Suspect » seul (`aging_reliable_docs = 30`).
> - Guide utilisateur : `GUIDE.md`. Diagnostic : `authentik --verifier <document>`.

> **Décision de l'utilisateur (2026-11-17) : SQLite (`sqlite3`) remplace PostgreSQL.** Les sections 6 et 6 bis ci-dessous sont **remplacées** par l'implémentation de `src/authentik/store/` : `migrations.py` (schéma SQLite, version dans `PRAGMA user_version`, à la place d'alembic), `db.py` (mémoïsation par `analysis_key`, ajout seulement grâce à des triggers, revues dans la table `reviews`), `documents.py`, `config_file.py` (`authentik.ini`, section `[storage]` : `database`, `documents_dir`). Plus de `psycopg`, `pgvector`, `alembic`, `keyring`, ni de file de synchronisation. Embeddings : stockés en BLOB float32, recherche du plus proche voisin en numpy. Limite : la détection de copie ne compare qu'aux documents analysés **sur la même base**. Livrable : installateur **`.exe` Inno Setup** (`packaging/`).

## 6. Base de données (PostgreSQL + pgvector)

Le schéma complet est dans `src/authentik/store/schema.sql` (section 7). Tables : `specimens` (sceaux et signatures de référence, vecteur pgvector), `fingerprints` (tout sceau ou signature déjà vu, pour la détection de copie), `reference_docs` et `year_profiles` (vieillissement), `analyses` (avec `analysis_key` **unique** : sert à la mémoïsation de la section 0 bis) et `signals`. Gérer les évolutions avec alembic.


## 6 bis. Stockage local, connexion PostgreSQL, résultats et documents

Tout ce qui est analysé est **enregistré** : le résultat, les signaux, et le document lui-même.

### Fichier de connexion `authentik.ini`
Dossier : `%APPDATA%\Authentik\authentik.ini` (créé au premier lancement). L'utilisateur peut aussi le modifier depuis l'écran **« Connexion à la base »** de l'application (champs, bouton **Tester la connexion**, bouton **Enregistrer**).

```ini
[postgres]
host = 192.168.1.10
port = 5432
dbname = authentik
user = authentik
password_source = keyring    ; le mot de passe n'est PAS écrit dans ce fichier

[storage]
documents_dir = C:\ProgramData\Authentik\documents   ; dossier des documents scannés

[sync]
retry_seconds = 60
```

- Le mot de passe PostgreSQL est conservé dans le **Gestionnaire d'identifiants Windows** (bibliothèque `keyring`), jamais en clair dans le `.ini` ni dans les journaux.
- Lecture avec `configparser` ; valeurs absentes = valeurs par défaut ; fichier invalide = message clair, l'application démarre quand même en mode local.

### Base locale SQLite (`%APPDATA%\Authentik\local.db`)
Rôles : (1) **mémoire locale** des résultats, ce qui garantit le même résultat pour le même document (section 0 bis) ; (2) **file d'attente** quand PostgreSQL est inaccessible ; (3) consultation des résultats **hors ligne**.

```sql
CREATE TABLE local_analyses (
  analysis_key TEXT PRIMARY KEY,      -- meme cle que dans PostgreSQL
  file_sha256  TEXT NOT NULL,
  file_name    TEXT NOT NULL,
  stored_path  TEXT NOT NULL,         -- copie du document dans documents_dir
  year         INTEGER,
  score        REAL NOT NULL,
  verdict      TEXT NOT NULL,
  result_json  TEXT NOT NULL,         -- signaux + preuves, tels qu'affiches dans « En savoir plus »
  created_at   TEXT NOT NULL,
  synced       INTEGER NOT NULL DEFAULT 0   -- 0 = pas encore envoye a PostgreSQL
);
CREATE INDEX idx_local_sha ON local_analyses (file_sha256);
CREATE INDEX idx_local_synced ON local_analyses (synced);
```

### Documents
- Chaque document analysé (scan ou import) est **copié sans modification** dans `documents_dir\AAAA\<sha256>.<extension>`. L'original de l'utilisateur n'est jamais déplacé ni modifié.
- La base garde le chemin (`stored_path`) et l'empreinte `sha256`. À la réouverture, l'empreinte est **revérifiée** : si elle ne correspond plus, afficher une alerte d'intégrité.
- Les recadrages de sceaux et de signatures servant à la détection de copie (`fingerprints.crop_path`) sont rangés dans `documents_dir\crops\`.
- Si plusieurs postes partagent le même PostgreSQL, `documents_dir` doit être un **dossier réseau partagé**, sinon les documents restent sur le poste qui les a scannés (question 11).

### Déroulement d'un enregistrement
1. Avant l'analyse : chercher `analysis_key` dans SQLite, puis dans PostgreSQL. Si trouvée, **renvoyer le résultat enregistré** sans recalculer.
2. Après l'analyse : copier le document, puis écrire le résultat dans SQLite (une transaction), `synced = 0`.
3. Tenter l'écriture dans PostgreSQL (une transaction : `analyses`, `signals`, `fingerprints`). Si elle réussit, `synced = 1`.
4. Si PostgreSQL est inaccessible : le résultat reste en attente. Nouvelle tentative au démarrage puis toutes les `retry_seconds`. L'interface affiche discrètement « Hors ligne : N résultats en attente » et **n'empêche jamais** d'analyser.
5. L'envoi est **idempotent** : `analysis_key` est unique des deux côtés, donc aucun doublon même en cas de reprise.

### Règles
- Un résultat enregistré n'est **jamais modifié** (ajout seulement). Si le logiciel, un modèle ou un profil de vieillissement change, une nouvelle analyse crée une **nouvelle ligne** liée au même `file_sha256`, et le rapport indique ce qui a changé.
- La décision d'un agent (`reviewed_by`, `review_note`) s'ajoute à l'analyse sans écraser le résultat de la machine.
- Les documents contiennent des données personnelles : limiter les droits du dossier `documents_dir` aux utilisateurs du logiciel, et prévoir la sauvegarde de PostgreSQL et de ce dossier (à signaler à l'utilisateur).
- Fichiers à écrire : `store/config_file.py`, `store/local_sqlite.py`, `store/postgres.py`, `store/sync.py`, `app/connection_dialog.py`, avec des tests (SQLite en mémoire pour la file d'attente ; PostgreSQL à tester avec une vraie base).

## 7. Fichiers fournis (contenu complet)

**Statut honnête.** Les algorithmes de base (`align_and_compare`, `pressure_features`, les mesures et le plancher de MAD du vieillissement) ont été exécutés avant, dans des scripts séparés, sur des **images de synthèse** : copie numérique ≈ 0,2 de résidu contre ≈ 1,0 pour un tampon réapposé ; `pressure_gradient` 0,037 contre 0,007 et `ink_range` 0,238 contre 0,135 entre tampon original et reproduction. **Les fichiers ci-dessous, tels qu'assemblés ici (profil de pression, signaux, fusion, déterminisme, tests), n'ont pas été exécutés.** Ils peuvent contenir des erreurs : lance `pytest`, corrige, et dis ce que tu as changé. Aucun de ces résultats ne prouve quoi que ce soit sur de vrais documents ; les seuils de `config.py` sont provisoires.

Points de conception à connaître :
- `copy` mesure le résidu **à l'intérieur des traits**, loin des bords (une première version sur l'image entière ne séparait pas les cas).
- `pressure` mesure l'effet de la pression sur l'encre, pas le relief (un scanner à plat ne mesure pas le relief). `edge_sharpness` et `ink_spread` ne séparaient pas les cas sur la synthèse : ils sont calculés mais non utilisés par défaut. Le cas de la **signature** (`erode=3`) n'a pas été testé.
- `aging` : le plancher `min_mad` est indispensable (sans lui un sceau trop foncé passait inaperçu quand les références étaient quasi identiques).
- OpenCV est figé `>=4.10,<5` (`cv2.AKAZE_create` absent en 5.0).


### `pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "authentik"
version = "0.1.0"
description = "Detection de certificats administratifs falsifies (Ministere de la Formation Professionnelle, RDC)"
requires-python = ">=3.11,<3.13"
dependencies = [
  "PySide6>=6.6",
  "zeroconf>=0.130",
  "httpx>=0.27",
  "PyMuPDF>=1.24",
  "opencv-python-headless>=4.10,<5",
  "scikit-image>=0.22",
  "numpy>=1.26,<3",
  "scipy>=1.11",
  "pytesseract>=0.3.10",
  "onnxruntime>=1.17",
  "scikit-learn>=1.4",
  "joblib>=1.3",
  "imagehash>=4.3",
  "psycopg[binary]>=3.1",
  "pgvector>=0.2",
  "alembic>=1.13",
  "reportlab>=4.1",
  "pydantic-settings>=2.2",
  "keyring>=25",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pyinstaller>=6.5"]
train = ["torch>=2.2", "torchvision>=0.17", "easyocr>=1.7"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src", "tests/synthetic"]
```


### `requirements.txt`

```text
PySide6>=6.6
zeroconf>=0.130
httpx>=0.27
PyMuPDF>=1.24
opencv-python-headless>=4.10,<5
scikit-image>=0.22
numpy>=1.26,<3
scipy>=1.11
pytesseract>=0.3.10
onnxruntime>=1.17
scikit-learn>=1.4
joblib>=1.3
imagehash>=4.3
psycopg[binary]>=3.1
pgvector>=0.2
alembic>=1.13
reportlab>=4.1
pydantic-settings>=2.2
keyring>=25
pytest>=8
```


### `src/authentik/__init__.py`

```python
"""Authentik : detection de certificats administratifs falsifies."""

__version__ = "0.1.0"
```


### `src/authentik/determinism.py`

```python
"""Reproductibilite : le meme fichier doit toujours donner le meme resultat.

Regles :
1. Appeler `init_determinism()` au demarrage de l'application ET au debut de chaque analyse.
2. Aucun hasard non fixe dans le code d'analyse (graine fixe partout).
3. Un seul thread pour OpenCV pendant l'analyse (l'ordre des sommes flottantes ne varie pas).
4. Les scores sont arrondis (`round_score`) AVANT toute comparaison a un seuil.
5. Le resultat d'une analyse est memorise par `analysis_key` : meme fichier + meme version
   du logiciel, des modeles et des profils => on renvoie le resultat memorise, sans recalculer.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import cv2
import numpy as np

SEED = 20240601
SCORE_DECIMALS = 4


def init_determinism() -> None:
    cv2.setNumThreads(1)
    cv2.setRNGSeed(SEED)
    random.seed(SEED)
    np.random.seed(SEED)


def round_score(x: float) -> float:
    return round(float(x), SCORE_DECIMALS)


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def analysis_key(file_sha: str, software_version: str, model_hashes: dict[str, str],
                 profile_version: str, settings_dict: dict) -> str:
    """Cle de memorisation : change des qu'un element pouvant modifier le resultat change."""
    payload = json.dumps(
        {
            "file": file_sha,
            "software": software_version,
            "models": model_hashes,
            "profiles": profile_version,
            "settings": settings_dict,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()
```


### `src/authentik/config.py`

```python
"""Seuils et parametres. Tous PROVISOIRES : a recalibrer sur de vrais documents (lot de validation).

Les valeurs ci-dessous ont ete choisies pour fonctionner sur les images de synthese des tests.
Elles ne prouvent rien sur de vrais documents.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Settings:
    # scan
    scan_dpi: int = 300
    # copie
    copy_min_inliers: int = 30
    copy_max_residual: float = 0.50     # residu <= seuil et assez d'inliers => copie numerique
    ink_level: int = 150
    # pression
    pressure_erode_seal: int = 7
    pressure_erode_signature: int = 3   # NON TESTE
    pressure_z_limit: float = 3.5
    pressure_features: tuple = ("pressure_gradient", "ink_range")
    # vieillissement
    aging_min_docs_per_year: int = 30
    aging_z_limit: float = 3.5
    aging_min_mad: float = 1.0
    # fusion
    review_threshold: float = 0.30
    suspect_threshold: float = 0.70

    def as_dict(self) -> dict:
        return asdict(self)


SETTINGS = Settings()
```


### `src/authentik/analyzers/__init__.py`

```python
from .base import Signal, NO_SIGNAL

__all__ = ["Signal", "NO_SIGNAL"]
```


### `src/authentik/analyzers/base.py`

```python
"""Contrat commun des analyseurs."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Signal:
    """Resultat d'un controle.

    risk       : 0 (conforme) a 1 (falsifie)
    confidence : fiabilite de la mesure, 0 a 1
    evidence   : details pour « En savoir plus » (JSON-serialisable)
    """
    risk: float
    confidence: float
    evidence: dict = field(default_factory=dict)


# Un analyseur qui n'a aucune valeur renvoie None (NO_SIGNAL) : la ligne correspondante
# de la page de resultats est alors MASQUEE (voir AGENTS.md, regle de masquage).
NO_SIGNAL = None
```


### `src/authentik/analyzers/copy.py`

```python
"""Detection de copie : un sceau ou une signature colle depuis un autre document.

Principe : aligner le candidat sur un element deja vu (AKAZE + RANSAC), puis mesurer la
correlation de l'encre a l'interieur des traits. Residu proche de 0 = meme texture d'encre =
copie numerique. Residu proche de 1 = tampon reapose (meme forme, autre depot d'encre).

Valide sur images de synthese uniquement. Seuils a calibrer sur de vraies paires.
"""
from __future__ import annotations

import cv2
import numpy as np

from ..config import SETTINGS, Settings
from ..determinism import SEED, round_score
from .base import Signal


def _ncc(u: np.ndarray, v: np.ndarray) -> float:
    u = u - u.mean()
    v = v - v.mean()
    return float((u * v).sum() / (np.sqrt((u * u).sum() * (v * v).sum()) + 1e-9))


def align_and_compare(a: np.ndarray, b: np.ndarray, ratio: float = 0.75,
                      ink_level: int = 150) -> tuple[int, float]:
    """Aligne `a` (niveaux de gris) sur `b`. Renvoie (inliers, residu)."""
    cv2.setRNGSeed(SEED)  # RANSAC : meme graine a chaque appel
    akaze = cv2.AKAZE_create()
    ka, da = akaze.detectAndCompute(a, None)
    kb, db = akaze.detectAndCompute(b, None)
    if da is None or db is None:
        return 0, 1.0
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(da, db, k=2)
    good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < ratio * p[1].distance]
    if len(good) < 4:
        return len(good), 1.0
    src = np.float32([ka[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kb[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    if H is None:
        return 0, 1.0
    inliers = int(mask.sum())
    size = (b.shape[1], b.shape[0])
    warped = cv2.warpPerspective(a, H, size)
    inside = cv2.warpPerspective(np.ones_like(a), H, size)
    ink = (b < ink_level).astype(np.uint8) & (warped < ink_level).astype(np.uint8)
    core = cv2.erode(ink & inside, np.ones((7, 7), np.uint8)) > 0
    if core.sum() < 500:
        return inliers, 1.0
    corr = _ncc(warped[core].astype(np.float32), b[core].astype(np.float32))
    return inliers, 1.0 - max(0.0, corr)


def copy_signal(candidate: np.ndarray, known: list[tuple[str, np.ndarray]],
                settings: Settings = SETTINGS) -> Signal | None:
    """Compare `candidate` aux elements deja vus `known` = [(id_document, image), ...].

    Renvoie None s'il n'y a rien a comparer (ligne masquee), sinon un Signal.
    risk = 1.0 si une copie numerique est trouvee (regle dure de la fusion).
    """
    if not known:
        return None
    best = None
    for doc_id, img in known:                      # ordre fixe : liste triee par l'appelant
        inliers, residual = align_and_compare(candidate, img, ink_level=settings.ink_level)
        if inliers >= settings.copy_min_inliers and (best is None or residual < best["residual"]):
            best = {"document": doc_id, "inliers": inliers, "residual": round_score(residual)}
    if best is not None and best["residual"] <= settings.copy_max_residual:
        return Signal(risk=1.0, confidence=1.0, evidence={"copy_of": best})
    return Signal(risk=0.0, confidence=0.8, evidence={"closest": best})
```


### `src/authentik/analyzers/pressure.py`

```python
"""Pression et depot de l'encre : tampon a l'encre original vs reproduction sur papier.

Un scanner a plat ne mesure PAS le relief. On mesure l'effet de la pression sur l'encre :
densite inegale (pressure_gradient) et etendue des tons (ink_range). Une reproduction
(photocopie, impression puis rescan) est plus uniforme que l'encre d'un vrai tampon.

Ne voit pas un vrai sceau copie numeriquement : c'est le role de `copy`.
Valide sur images de synthese uniquement.
"""
from __future__ import annotations

import cv2
import numpy as np

from ..config import SETTINGS, Settings
from ..determinism import round_score
from .base import Signal


def pressure_features(gray: np.ndarray, ink_level: int = 150, erode: int = 7) -> dict | None:
    """Mesures a l'interieur des traits. Renvoie None si la zone d'encre est trop petite."""
    g = gray.astype(np.float32)
    ink = (g < ink_level).astype(np.uint8)
    core = cv2.erode(ink, np.ones((erode, erode), np.uint8)) > 0
    if core.sum() < 500:
        return None
    band = (cv2.dilate(ink, np.ones((5, 5), np.uint8)) - cv2.erode(ink, np.ones((5, 5), np.uint8))) > 0
    far = cv2.dilate(ink, np.ones((15, 15), np.uint8)) == 0
    if far.sum() == 0 or band.sum() == 0:
        return None
    paper = float(np.median(g[far]))
    contrast = max(paper - float(np.median(g[core])), 1.0)

    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.hypot(gx, gy)

    num = cv2.GaussianBlur(np.where(core, g, 0).astype(np.float32), (0, 0), 15)
    den = cv2.GaussianBlur(core.astype(np.float32), (0, 0), 15)
    ok = core & (den > 0.05)
    if ok.sum() == 0:
        return None
    dens = num[ok] / den[ok]

    p5, p95 = np.percentile(g[core], [5, 95])
    return {
        "ink_spread": float(g[core].std() / contrast),
        "ink_range": float((p95 - p5) / contrast),
        "edge_sharpness": float(mag[band].mean() / contrast),
        "pressure_gradient": float(dens.std() / contrast),
    }


def build_pressure_profile(feature_dicts: list[dict], min_mad: float = 0.0) -> dict:
    """Plage normale des mesures, calculee sur des tampons AUTHENTIQUES (mediane, MAD)."""
    profile = {}
    for k in feature_dicts[0]:
        v = np.array([f[k] for f in feature_dicts], dtype=float)
        med = float(np.median(v))
        mad = float(np.median(np.abs(v - med)))
        profile[k] = (med, max(mad, min_mad, 1e-6))
    return profile


def pressure_signal(gray: np.ndarray, profile: dict, erode: int | None = None,
                    settings: Settings = SETTINGS) -> Signal | None:
    """Risque = part des mesures cles anormalement FAIBLES (trop uniformes) par rapport au profil.

    Unilateral : seule une encre trop uniforme est suspecte (reproduction).
    Renvoie None si la zone est trop petite (ligne masquee).
    """
    feats = pressure_features(gray, ink_level=settings.ink_level,
                              erode=erode or settings.pressure_erode_seal)
    if feats is None:
        return None
    flagged, zs = [], {}
    for k in settings.pressure_features:
        med, mad = profile[k]
        z = 0.6745 * (feats[k] - med) / mad
        zs[k] = round_score(z)
        if z < -settings.pressure_z_limit:
            flagged.append(k)
    risk = len(flagged) / len(settings.pressure_features)
    return Signal(risk=round_score(risk), confidence=0.7,
                  evidence={"features": {k: round_score(v) for k, v in feats.items()},
                            "z": zs, "flagged": flagged})
```


### `src/authentik/analyzers/aging.py`

```python
"""Vieillissement : papier et encre compares aux documents AUTHENTIQUES de la MEME annee.

Conditions de validite :
- memes reglages de scan pour les references et les documents controles (300 DPI, couleur,
  sans amelioration automatique) ;
- au moins `aging_min_docs_per_year` documents authentiques par annee, sinon la ligne est masquee.
Limite : un faux imprime sur du papier d'epoque de la meme annee passe ce controle seul.
"""
from __future__ import annotations

import cv2
import numpy as np

from ..config import SETTINGS, Settings
from ..determinism import round_score
from .base import Signal

MEASURES = ["paper_L", "paper_b", "paper_grain", "text_contrast", "seal_contrast", "seal_text_gap"]


def measures(img_bgr: np.ndarray, paper_mask: np.ndarray, text_mask: np.ndarray,
             seal_mask: np.ndarray) -> dict | None:
    """Masques booleens (papier = marges vierges, texte imprime, sceau). Lab d'OpenCV."""
    if min(paper_mask.sum(), text_mask.sum(), seal_mask.sum()) < 100:
        return None
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    L, b = lab[..., 0], lab[..., 2]
    paper_L = float(np.median(L[paper_mask]))
    text_c = paper_L - float(np.median(L[text_mask]))
    seal_c = paper_L - float(np.median(L[seal_mask]))
    return {
        "paper_L": paper_L,
        "paper_b": float(np.median(b[paper_mask])),
        "paper_grain": float(L[paper_mask].std()),
        "text_contrast": text_c,
        "seal_contrast": seal_c,
        "seal_text_gap": abs(seal_c - text_c),
    }


def build_profile(values, min_mad: float = SETTINGS.aging_min_mad) -> tuple[float, float]:
    """(mediane, MAD) avec un plancher : bruit de mesure du scanner.

    Sans plancher, une mesure parfaitement stable (ecart nul) ne pourrait jamais etre signalee.
    """
    v = np.asarray(values, dtype=float)
    med = float(np.median(v))
    mad = float(np.median(np.abs(v - med)))
    return med, max(mad, min_mad)


def robust_z(x: float, med: float, mad: float) -> float:
    return 0.6745 * (x - med) / mad


def aging_signal(m: dict | None, profiles: dict, n_docs: int,
                 settings: Settings = SETTINGS) -> Signal | None:
    """None (ligne masquee) si l'annee a trop peu de references ou si les mesures manquent."""
    if m is None or n_docs < settings.aging_min_docs_per_year:
        return None
    flagged = [k for k in MEASURES
               if abs(robust_z(m[k], *profiles[k])) > settings.aging_z_limit]
    risk = len(flagged) / len(MEASURES)
    conf = min(1.0, n_docs / 100)           # plus l'annee est documentee, plus on s'y fie
    return Signal(risk=round_score(risk), confidence=round_score(conf),
                  evidence={"flagged": flagged,
                            "z": {k: round_score(robust_z(m[k], *profiles[k])) for k in MEASURES},
                            "n_reference_docs": n_docs})
```


### `src/authentik/fusion/__init__.py`

```python
from .fusion import FEATURES, Fusion, review_threshold_from_roc

__all__ = ["FEATURES", "Fusion", "review_threshold_from_roc"]
```


### `src/authentik/fusion/fusion.py`

```python
"""Fusion des signaux en un verdict : conforme / a_verifier / suspect.

Regles dures d'abord, puis modele appris (regression logistique, deterministe).
Les seuils par defaut sont provisoires ; les calculer sur le lot de validation.
"""
from __future__ import annotations

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_curve

from ..analyzers.base import Signal
from ..config import SETTINGS
from ..determinism import round_score

FEATURES = ["seal_text", "seal_reference", "seal_copy", "seal_integrity",
            "sig_reference", "sig_copy", "sig_integrity",
            "seal_pressure", "sig_pressure", "aging"]


class Fusion:
    def __init__(self, review: float = SETTINGS.review_threshold,
                 suspect: float = SETTINGS.suspect_threshold):
        self.model = LogisticRegression(class_weight="balanced", max_iter=1000,
                                        solver="lbfgs", random_state=0)
        self.review, self.suspect = review, suspect
        self.fitted = False

    @staticmethod
    def vector(signals: dict[str, Signal]) -> list[float]:
        return [signals[k].risk * signals[k].confidence if signals.get(k) is not None else 0.0
                for k in FEATURES]

    def fit(self, signals_list: list[dict[str, Signal]], labels: list[int]) -> None:
        """labels : 1 = faux, 0 = authentique."""
        self.model.fit([self.vector(s) for s in signals_list], labels)
        self.fitted = True

    def decide(self, signals: dict[str, Signal]) -> tuple[float, str]:
        """Renvoie (score arrondi, verdict). Meme entree => meme sortie."""
        # 1. copie detectee : suspect, sans appel au modele
        for name in ("seal_copy", "sig_copy"):
            s = signals.get(name)
            if s is not None and s.risk >= 1.0:
                return 1.0, "suspect"
        # 2. element attendu mais introuvable / image illisible
        if signals.get("unreadable") is not None:
            return 0.5, "a_verifier"
        # 3. modele appris
        if not self.fitted:
            raise RuntimeError("Fusion non entrainee : appeler fit() ou charger un modele.")
        p = round_score(self.model.predict_proba([self.vector(signals)])[0, 1])
        if p >= self.suspect:
            return p, "suspect"
        return p, ("a_verifier" if p >= self.review else "conforme")

    def save(self, path: str) -> None:
        joblib.dump({"model": self.model, "review": self.review, "suspect": self.suspect}, path)

    @classmethod
    def load(cls, path: str) -> "Fusion":
        d = joblib.load(path)
        f = cls(d["review"], d["suspect"])
        f.model, f.fitted = d["model"], True
        return f


def review_threshold_from_roc(y_val, p_val, min_recall: float = 0.90,
                              max_false_reject: float = 0.05) -> float | None:
    """Seuil de revue : le plus eleve qui garde au moins `min_recall` des faux signales,
    avec au plus `max_false_reject` de vrais signales a tort.
    None => objectif hors de portee : ameliorer un controle, ne pas bouger le seuil.
    """
    fpr, tpr, thr = roc_curve(y_val, p_val)
    ok = np.where((tpr >= min_recall) & (fpr <= max_false_reject))[0]
    return float(thr[ok[0]]) if len(ok) else None
```


### `src/authentik/eval/__init__.py`

```python
from .metrics import wilson

__all__ = ["wilson"]
```


### `src/authentik/eval/metrics.py`

```python
"""Mesures de la preuve devant le jury (voir AGENTS.md, section Evaluation)."""
from __future__ import annotations

from math import sqrt


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalle de confiance a 95 % d'une proportion k/n (methode de Wilson)."""
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    demi = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return centre - demi, centre + demi


def recall_and_false_reject(y_true, verdicts) -> dict:
    """y_true : 1 = faux, 0 = authentique. verdicts : 'conforme' | 'a_verifier' | 'suspect'.
    Un document est « signale » s'il est a_verifier ou suspect."""
    flagged = [v != "conforme" for v in verdicts]
    fakes = [f for f, y in zip(flagged, y_true) if y == 1]
    genuine = [f for f, y in zip(flagged, y_true) if y == 0]
    out = {}
    if fakes:
        k, n = sum(fakes), len(fakes)
        out["recall"] = k / n
        out["recall_ci95"] = wilson(k, n)
    if genuine:
        k, n = sum(genuine), len(genuine)
        out["false_reject"] = k / n
        out["false_reject_ci95"] = wilson(k, n)
    return out
```


### `src/authentik/store/schema.sql`

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE specimens (            -- sceaux et signatures de reference
  id          BIGSERIAL PRIMARY KEY,
  kind        TEXT NOT NULL CHECK (kind IN ('seal','signature')),
  owner_name  TEXT NOT NULL,
  year        INT  NOT NULL,
  image_path  TEXT NOT NULL,
  embedding   vector(256)
);

CREATE TABLE fingerprints (         -- tout sceau ou signature deja vu (detection de copie)
  id          BIGSERIAL PRIMARY KEY,
  analysis_id BIGINT NOT NULL,
  kind        TEXT NOT NULL,
  phash       BIGINT NOT NULL,
  crop_path   TEXT NOT NULL
);
CREATE INDEX ON fingerprints (phash);

CREATE TABLE reference_docs (       -- documents authentiques de reference (vieillissement)
  id        BIGSERIAL PRIMARY KEY,
  year      INT NOT NULL,
  scanner   TEXT,
  measures  JSONB NOT NULL,
  added_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE year_profiles (        -- plage normale par annee et par mesure
  year    INT  NOT NULL,
  measure TEXT NOT NULL,
  median  REAL NOT NULL,
  mad     REAL NOT NULL,
  n       INT  NOT NULL,
  PRIMARY KEY (year, measure)
);

CREATE TABLE analyses (
  id           BIGSERIAL PRIMARY KEY,
  file_sha256  TEXT NOT NULL,
  analysis_key TEXT NOT NULL UNIQUE,   -- cle de memorisation : meme cle => meme resultat renvoye
  file_name    TEXT NOT NULL,
  stored_path  TEXT NOT NULL,          -- copie du document dans documents_dir
  year         INT,
  score        REAL NOT NULL,
  verdict      TEXT NOT NULL CHECK (verdict IN ('conforme','a_verifier','suspect')),
  reviewed_by  TEXT,
  review_note  TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE signals (
  analysis_id BIGINT REFERENCES analyses(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  risk        REAL NOT NULL,
  confidence  REAL NOT NULL,
  evidence    JSONB NOT NULL,
  PRIMARY KEY (analysis_id, name)
);
```


### `tests/synthetic/synth.py`

```python
"""Images de synthese pour les tests. Ne prouvent rien sur de vrais documents."""
import cv2
import numpy as np


def make_seal(size=500):
    """Sceau a environ 300 DPI (traits epais de plusieurs dizaines de pixels)."""
    img = np.full((size, size), 255, np.uint8)
    c = size // 2
    cv2.circle(img, (c, c), 220, 0, 14)
    cv2.circle(img, (c, c), 185, 0, 8)
    cv2.putText(img, "MINISTERE", (88, 225), cv2.FONT_HERSHEY_SIMPLEX, 1.8, 0, 9)
    cv2.putText(img, "FORMATION", (88, 295), cv2.FONT_HERSHEY_SIMPLEX, 1.8, 0, 9)
    cv2.putText(img, "PROFESSION.", (118, 365), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 0, 7)
    return img


def render(seal, seed, jitter=False):
    """Simule une pose de tampon : pression irreguliere de l'encre + grain du papier."""
    rng = np.random.default_rng(seed)
    h, w = seal.shape
    ink = (255 - seal).astype(np.float32) / 255
    if jitter:  # un tampon reapose bouge un peu
        m = cv2.getRotationMatrix2D((w / 2, h / 2), rng.uniform(-2, 2), 1.0)
        m[:, 2] += rng.uniform(-3, 3, 2)
        ink = cv2.warpAffine(ink, m, (w, h))
    smooth = cv2.GaussianBlur(rng.random((h, w)).astype(np.float32), (0, 0), 6)
    smooth = (smooth - smooth.min()) / (smooth.max() - smooth.min())
    mod = 0.55 + 0.45 * smooth
    speck = np.where(rng.random((h, w)) > 0.97, 0.5, 1.0)
    paper = 235 + rng.normal(0, 3, (h, w))
    out = paper - ink * mod * speck * 220
    return np.clip(out, 0, 255).astype(np.uint8)


def paste_copy(crop, angle=3.0, scale=0.95):
    """Copie numerique : reechantillonnage puis compression JPEG."""
    h, w = crop.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, scale)
    out = cv2.warpAffine(crop, m, (w, h), borderValue=235)
    ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 75])
    return cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)


def photocopy(img, level=128, ink=30, paper=245, seed=0):
    """Reproduction imprimee : binarisation, aplats uniformes, bords nets, puis re-scan."""
    rng = np.random.default_rng(seed)
    out = np.where(img < level, ink, paper).astype(np.float32)
    out = cv2.GaussianBlur(out, (0, 0), 0.6)
    out += rng.normal(0, 2, out.shape)
    return np.clip(out, 0, 255).astype(np.uint8)


def softened(img, sigma=1.2):
    """Encre qui diffuse dans les fibres : bords plus doux."""
    return cv2.GaussianBlur(img, (0, 0), sigma)
```


### `tests/synthetic/test_copy.py`

```python
from synth import make_seal, paste_copy, render

from authentik.analyzers.copy import align_and_compare, copy_signal
from authentik.determinism import init_determinism


def test_copy_vs_restamp_separate():
    init_determinism()
    seal = make_seal()
    for seed in range(1, 6):
        original = render(seal, seed)
        copy = paste_copy(original)
        restamp = render(seal, seed + 100, jitter=True)
        ci, cr = align_and_compare(copy, original)
        ri, rr = align_and_compare(restamp, original)
        assert ci >= 30 and cr < 0.5, (seed, ci, cr)     # copie numerique
        assert rr > 0.8, (seed, ri, rr)                  # tampon reapose


def test_copy_signal_rules():
    init_determinism()
    seal = make_seal()
    original = render(seal, 1)
    assert copy_signal(original, []) is None                       # rien a comparer : ligne masquee
    s = copy_signal(paste_copy(original), [("doc-1", original)])
    assert s.risk == 1.0 and s.evidence["copy_of"]["document"] == "doc-1"
    s = copy_signal(render(seal, 101, jitter=True), [("doc-1", original)])
    assert s.risk == 0.0
```


### `tests/synthetic/test_pressure.py`

```python
import numpy as np
from synth import make_seal, photocopy, render, softened

from authentik.analyzers.pressure import build_pressure_profile, pressure_features, pressure_signal


def _original(seal, seed):
    return softened(render(seal, seed))


def _reproduction(seal, seed):
    return photocopy(render(seal, seed), seed=seed)


def test_features_separate_cases():
    seal = make_seal()
    o = [pressure_features(_original(seal, s)) for s in range(1, 6)]
    r = [pressure_features(_reproduction(seal, s)) for s in range(1, 6)]
    for k in ("pressure_gradient", "ink_range"):
        assert np.mean([f[k] for f in o]) > 1.5 * np.mean([f[k] for f in r]), k


def test_too_small_ink_returns_none():
    blank = np.full((300, 300), 240, np.uint8)
    assert pressure_features(blank) is None            # ligne masquee
    assert pressure_signal(blank, {}) is None


def test_signal_flags_reproductions_not_originals():
    seal = make_seal()
    profile = build_pressure_profile(
        [pressure_features(_original(seal, s)) for s in range(1, 21)])
    orig_risk = [pressure_signal(_original(seal, s), profile).risk for s in range(21, 41)]
    repr_risk = [pressure_signal(_reproduction(seal, s), profile).risk for s in range(21, 41)]
    assert np.mean(orig_risk) <= 0.1      # tres peu de vrais tampons signales
    assert np.mean(repr_risk) >= 0.9      # presque toutes les reproductions signalees
```


### `tests/synthetic/test_aging.py`

```python
import numpy as np

from authentik.analyzers.aging import MEASURES, aging_signal, build_profile, robust_z


def _refs(n, rng):
    base = {"paper_L": 200, "paper_b": 135, "paper_grain": 2.0,
            "text_contrast": 120, "seal_contrast": 100, "seal_text_gap": 20}
    return [{k: v + rng.normal(0, 1.5) for k, v in base.items()} for _ in range(n)]


def _profiles(refs):
    return {k: build_profile([r[k] for r in refs]) for k in MEASURES}


def test_mad_floor_catches_too_dark_seal():
    # references quasi identiques : MAD = 0 sans plancher
    p = build_profile([100.0] * 40)
    assert p[1] >= 1.0
    assert abs(robust_z(130.0, *p)) > 3.5         # sceau trop fonce : signale


def test_normal_doc_passes_abnormal_flagged():
    rng = np.random.default_rng(0)
    refs = _refs(60, rng)
    prof = _profiles(refs)
    normal = _refs(1, rng)[0]
    s = aging_signal(normal, prof, 60)
    assert s.risk <= 0.2
    bad = dict(normal, paper_L=normal["paper_L"] + 40, seal_contrast=normal["seal_contrast"] + 60)
    s = aging_signal(bad, prof, 60)
    assert s.risk >= 0.3 and "paper_L" in s.evidence["flagged"]


def test_not_enough_references_masks_row():
    rng = np.random.default_rng(0)
    refs = _refs(10, rng)
    assert aging_signal(refs[0], _profiles(refs), 10) is None
    assert aging_signal(None, _profiles(refs), 60) is None
```


### `tests/synthetic/test_fusion_eval.py`

```python
import numpy as np
import pytest

from authentik.analyzers.base import Signal
from authentik.eval.metrics import recall_and_false_reject, wilson
from authentik.fusion import FEATURES, Fusion, review_threshold_from_roc


def _sig(rng, fake):
    s = {}
    for k in FEATURES:
        if k.endswith("copy"):
            s[k] = Signal(0.0, 0.8)
        else:
            s[k] = Signal(float(np.clip(rng.normal(0.7 if fake else 0.15, 0.15), 0, 1)), 0.9)
    return s


def _data(n, seed):
    rng = np.random.default_rng(seed)
    y = [i % 2 for i in range(n)]
    return [_sig(rng, bool(v)) for v in y], y


def test_copy_rule_overrides_model():
    f = Fusion()
    sig = {"seal_copy": Signal(1.0, 1.0)}
    assert f.decide(sig) == (1.0, "suspect")          # sans meme avoir entraine le modele


def test_unfitted_model_raises():
    with pytest.raises(RuntimeError):
        Fusion().decide({"aging": Signal(0.1, 1.0)})


def test_same_input_same_output_and_roundtrip(tmp_path):
    X, y = _data(200, 1)
    f = Fusion()
    f.fit(X, y)
    a = f.decide(X[3])
    assert a == f.decide(X[3])
    f.save(str(tmp_path / "f.joblib"))
    assert Fusion.load(str(tmp_path / "f.joblib")).decide(X[3]) == a


def test_threshold_and_metrics():
    X, y = _data(400, 2)
    f = Fusion()
    f.fit(X[:200], y[:200])
    p_val = [f.decide(s)[0] for s in X[200:]]
    thr = review_threshold_from_roc(y[200:], p_val)
    assert thr is not None
    verdicts = [f.decide(s)[1] for s in X[200:]]
    m = recall_and_false_reject(y[200:], verdicts)
    assert m["recall"] >= 0.9 and m["false_reject"] <= 0.1


def test_wilson_matches_documented_widths():
    lo, hi = wilson(184, 200)                         # rappel 92 % sur 200 faux
    assert abs((hi - lo) / 2 - 0.038) < 0.005
    lo, hi = wilson(46, 50)
    assert abs((hi - lo) / 2 - 0.078) < 0.01
```


### `tests/synthetic/test_determinism.py`

```python
"""Meme document => meme resultat, toujours."""
import cv2
import numpy as np
from synth import make_seal, paste_copy, render, softened

from authentik import __version__
from authentik.analyzers.copy import align_and_compare
from authentik.analyzers.pressure import pressure_features
from authentik.determinism import analysis_key, file_sha256, init_determinism, round_score


def test_copy_analysis_repeatable_even_if_rng_state_changes():
    init_determinism()
    seal = make_seal()
    o = render(seal, 3)
    c = paste_copy(o)
    ref = align_and_compare(c, o)
    for junk in range(10):
        cv2.setRNGSeed(junk * 7919)            # on perturbe l'etat aleatoire d'OpenCV
        np.random.seed(junk)
        assert align_and_compare(c, o) == ref  # identique au bit pres


def test_pressure_repeatable():
    g = softened(render(make_seal(), 4))
    a = pressure_features(g)
    for _ in range(5):
        assert pressure_features(g) == a


def test_rounding_and_keys(tmp_path):
    assert round_score(0.123456789) == 0.1235
    f = tmp_path / "doc.bin"
    f.write_bytes(b"abc")
    sha = file_sha256(f)
    k1 = analysis_key(sha, __version__, {"emb": "h1"}, "p1", {"a": 1})
    assert k1 == analysis_key(sha, __version__, {"emb": "h1"}, "p1", {"a": 1})
    assert k1 != analysis_key(sha, __version__, {"emb": "h2"}, "p1", {"a": 1})   # modele change
    assert k1 != analysis_key(sha, __version__, {"emb": "h1"}, "p2", {"a": 1})   # profils changes
```


## 8. Fusion et règles de décision

Chaque ligne de la page de résultats vient d'un groupe de signaux :
- **Sceau** : `seal_text`, `seal_reference`, `seal_copy`, `seal_integrity`
- **Signature** : `sig_reference`, `sig_copy`, `sig_integrity`
- **Vieillissement** : `aging`
- **Pression de l'encre** : `seal_pressure`, `sig_pressure`

| Ordre | Règle | Verdict |
| --- | --- | --- |
| 1 | `copy` détectée (sceau ou signature identique à celui d'un autre document après alignement) | Suspect |
| 2 | Sceau ou signature attendu mais introuvable, ou image trop floue pour mesurer | À vérifier (ligne « Introuvable ») |
| 3 | Moins de 30 documents de référence pour l'année | Ligne Vieillissement masquée, motif dans « En savoir plus » |
| 4 | Sinon : probabilité du modèle appris | Conforme, À vérifier ou Suspect selon les seuils |

Modèle : régression logistique `scikit-learn`, entrées `risk × confidence` de chaque signal (0 si le signal est absent), `class_weight="balanced"`. Code : voir `fusion/fusion.py` (**non exécuté**).

**Seuils.** Les valeurs 0,30 et 0,70 sont provisoires. On les calcule sur le **lot de validation**. Un document est « signalé » quand il est À vérifier ou Suspect, donc à partir du seuil de revue : on prend le seuil le plus élevé qui garde au moins 90 % des faux signalés, puis on vérifie que les vrais signalés à tort restent sous 5 %. Si les deux ne tiennent pas ensemble, c'est que les signaux ne suffisent pas : améliorer un contrôle, ne pas bouger le seuil.

_(Le code correspondant est dans `fusion/fusion.py`, section 7.)_


## 9. Évaluation (preuve devant le jury)

Commande : `python -m authentik.eval ./dataset`. Elle analyse tout le jeu de test et produit le rapport.

| Lot | Part | Usage |
| --- | --- | --- |
| Entraînement | 60 % | Poids de fusion, éventuel affinage du modèle d'embeddings |
| Validation | 20 % | Seuils de revue et de suspect, seuils d'alignement et de vieillissement |
| Test final | 20 % | Mesure officielle, utilisée **une seule fois** |

Règles :
- Un même certificat source n'apparaît que dans **un seul lot**, faux dérivés compris (`GroupShuffleSplit`, groupé par certificat source). Les documents de référence du vieillissement sont exclus du test.
- Les scans varient : plusieurs scanners, 150 et 300 DPI, PDF et JPEG, photos de téléphone.
- Types de faux à fabriquer : sceau copié-collé, signature déplacée, texte modifié sous un vrai sceau, faux imprimé puis rescanné, export JPEG de basse qualité.
- Les authentiques incluent des cas difficiles : tampon de travers, scan pâle, annotations manuscrites légitimes.
- Taille du test : **200 faux et 200 vrais** minimum. Avec 200 faux, un rappel de 92 % est connu à environ ±3,8 points ; avec 50 faux, à environ ±7,8 points.

_(Fonction `wilson` dans `eval/metrics.py`, section 7.)_

Rapport : rappel global avec intervalle (objectif ≥ 90 %), taux de faux rejets (objectif ≤ 5 %), rappel par type de faux (tout type sous 80 % est déclaré comme limite), part des documents envoyés en revue manuelle, courbe ROC, matrice de confusion.


## 10. Phases (travaille dans cet ordre, un critère de sortie vérifiable par phase)

1. **Scan et import.** Découverte des imprimantes (zeroconf), client eSCL, import PDF et image, lecture de l'année par OCR, interface PySide6 à deux colonnes avec chargement, fichier `authentik.ini`, SQLite local, enregistrement des documents et synchronisation PostgreSQL (section 6 bis). *Sortie : un document scanné depuis l'imprimante du client apparaît dans la colonne image.*
2. **Sceau et signature.** Extraction des zones, `copy` (`analyzers/copy.py`), `pressure` (`analyzers/pressure.py`), conformité aux spécimens (embeddings ONNX + pgvector). *Sortie : les copies collées du lot de validation sont signalées, les sceaux réapposés passent.*
3. **Vieillissement.** Base de références par année, mesures (`analyzers/aging.py`), plages normales, comparaison interne, règle de masquage. *Sortie : plage calculée pour chaque année qui compte au moins 30 documents.*
4. **Fusion et résultats.** Modèle appris, seuils, page de résultats courte avec lignes masquables, « En savoir plus », rapport PDF. *Sortie : seuils fixés sur le lot de validation.*
5. **Preuve.** `python -m authentik.eval` sur le test final, démonstration de 5 minutes (vrai certificat, faux copié-collé, faux imprimé puis rescanné, rapport). *Sortie : rappel et faux rejets mesurés avec leurs intervalles.*

## 11. Questions à poser à l'utilisateur (avant la phase concernée)

- Le modèle d'imprimante du client gère-t-il AirScan/eSCL ? (phase 1)
- Combien de documents authentiques par année, et quelles années couvrir ? Il en faut au moins 30 par année. (phase 3)
- Combien de vrais et de faux saisis sont disponibles pour le test ? Viser 200 de chaque. (phase 5)
- Combien de spécimens de sceau et de signature par signataire et par année ? 5 à 10 pour démarrer. (phase 2)
- Les documents à contrôler sont-ils des **originaux** (tampon à l'encre posé directement) ou peuvent-ils être des **copies certifiées** légitimes ? Dans le second cas, la reproduction est normale et `pressure` ne peut pas servir tel quel. (phase 2)
- Les sceaux ont-ils un **relief** (sceau sec) ? Si oui, prévoir un scan recto verso. (phase 2)
- PostgreSQL : une base par poste, ou un serveur partagé ? Le serveur partagé est bien plus utile pour repérer un sceau copié d'un document scanné ailleurs. (phase 1)
- Le client veut-il un installateur `.exe` ou un `.msi` ? PostgreSQL doit-il être installé avec le logiciel ou fourni par un serveur existant ? (phase 1 et 5)
- Où stocker les documents ? Sur chaque poste, ou dans un dossier réseau partagé ? Qui administre le serveur PostgreSQL et fait les sauvegardes ? (phase 1)
- Réglages de scan standard à imposer sur tous les postes : 300 DPI, couleur, sans amélioration automatique. (phase 1)

## 12. Limites connues (à rappeler dans le rapport final)

- Aucun système ne garantit 100 % sur des scans. Le logiciel donne un score et des preuves visuelles ; un agent habilité décide.
- Un faux imprimé sur du papier d'époque de la même année passe le contrôle de vieillissement : il doit être attrapé par les autres contrôles.
- `pressure` mesure l'effet de la pression sur l'encre, pas le relief.
- Tous les résultats de test fournis dans ce brief viennent d'images de synthèse.

