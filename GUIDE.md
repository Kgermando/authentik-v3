# Authentik — guide d'utilisation

Ministère de la Formation Professionnelle (MFP). Le logiciel aide à repérer les certificats
falsifiés ; **la décision revient toujours à un agent habilité**.

## 1. Avant tout : enregistrer des documents de référence

Sans documents de référence, il n'y a rien à comparer.

1. Accueil > **Références** (ou menu Fichier > Références…).
2. **Ajouter des documents authentiques…** : choisir des certificats **authentiques**, scannés
   comme les documents à contrôler (300 DPI, couleur, sans amélioration automatique).
3. Indiquer l'**année** de ces documents (un lot = une année), le **signataire** et, si possible,
   le **texte écrit autour du sceau**.
4. Le logiciel extrait le sceau et la signature de chaque document et mesure le papier et l'encre.
   Le compte rendu indique ce qui a été trouvé (ex. « sceau INTROUVABLE » : vérifier le scan).

| Contrôle | Devient actif à partir de |
|---|---|
| Copie du sceau ou de la signature | 1 document de référence ou déjà analysé |
| Ressemblance aux spécimens, texte du sceau | 3 spécimens (texte : si le texte du sceau a été saisi et Tesseract installé) |
| Pression de l'encre, papier autour du sceau | 5 spécimens |
| Vieillissement (papier, encre) | 5 documents de référence **de la même année** (fiabilité réduite jusqu'à 30 : seuls les écarts nets sont signalés, et ce contrôle ne conclut jamais « Suspect » seul) |

Un document de référence ajouté par erreur se retire avec **Retirer**.

## 2. Contrôler un certificat

1. **Scanner** (imprimante du réseau, d'un autre réseau par son adresse, ou pilote du poste) ou
   **Importer un fichier** (PDF, PNG, JPEG, TIFF).
2. Vérifier l'**année** lue sur le document, puis **Analyser**.
3. Page de résultats : verdict (**Conforme**, **À vérifier**, **Suspect**) et une ligne par
   indication (Sceau, Signature, Vieillissement, Pression de l'encre). Cliquer une ligne met en
   évidence la zone sur l'image. **En savoir plus** : images comparées, mesures, rapport PDF.
4. **Décision de l'agent** : Authentique / Faux / Indéterminé. Elle est enregistrée sans modifier
   le résultat de la machine, et sert à entraîner la décision.

## 3. Décision provisoire, puis entraînée

Tant que la décision n'est pas entraînée, le logiciel ne dit **jamais « Conforme » seul** : il
conclut « Suspect » sur une preuve forte (copie, sceau reproduit…) et « À vérifier » sinon.

Quand des agents ont vérifié au moins **10 faux et 10 authentiques** : Références >
**Entraîner la décision**. Le seuil est choisi pour viser 90 % des faux signalés avec au plus 5 %
de vrais signalés à tort ; les chiffres affichés sont indicatifs.

## 4. Mesure officielle de la fiabilité

Préparer un dossier avec les documents et un fichier `labels.csv` :

```
fichier;label;annee;groupe;type
vrais/c001.pdf;authentique;2019;c001;
faux/c001_colle.png;faux;2019;c001;sceau_colle
```

Puis : `authentik --evaluer DOSSIER` (version installée) ou `python -m authentik.eval DOSSIER`.
Le rapport (`DOSSIER/rapport/evaluation.md`) donne le taux de faux détectés et de vrais signalés
à tort avec leur intervalle de confiance. Viser **200 faux et 200 authentiques** ; le lot de test
ne doit servir **qu'une fois**.

## 5. Diagnostic

`authentik --verifier un_document.pdf` vérifie l'installation (configuration, OCR, pilote de
scan, analyse) sans toucher à la base.

## Limites

- Aucun système ne garantit 100 % sur des scans.
- Un faux imprimé sur du papier d'époque de la même année passe le contrôle de vieillissement.
- La pression est mesurée sur l'encre, pas sur le relief.
- Tous les tests actuels utilisent des **images de synthèse** : la fiabilité réelle n'est connue
  qu'après l'évaluation sur vos documents.
