# Arduino IMU Monitor

Acquisition de données d'accéléromètre sur Arduino, avec envoi sur le port série et suivi en direct depuis une interface web.

La carte mesure l'accélération à 10 Hz et envoie des trames protégées par une somme de contrôle. Un serveur FastAPI les lit, les enregistre et les affiche dans le navigateur. Deux formats de trames sont disponibles, ce qui permet de comparer leur volume de données.

## Matériel

- Carte Arduino avec IMU LSM9DS1 (par exemple une Nano 33 BLE)
- Écran OLED SSD1306 128x64 en I2C, à l'adresse `0x3C`
- LED sur `D11` et buzzer sur `A6`

## Installation

**Arduino** : téléversez `mini_sketch/mini_projet_sketch/mini_projet_sketch.ino` après avoir installé les bibliothèques `Arduino_LSM9DS1`, `Adafruit GFX Library` et `Adafruit SSD1306`.

**Python** (testé avec Python 3.13) :

```bash
python -m venv .venv
.venv\Scripts\activate
pip install fastapi uvicorn pyserial numpy matplotlib
```

## Utilisation

1. Branchez la carte et fermez le moniteur série de l'IDE Arduino, qui bloquerait le port.
2. Lancez le serveur, puis saisissez le port série demandé (par exemple `COM9`) :

   ```bash
   python main.py
   ```

3. Ouvrez <http://127.0.0.1:8000>.

| Bouton | Action |
| --- | --- |
| START / STOP | Démarre ou arrête l'acquisition |
| KF MODE | Envoie chaque mesure en valeurs complètes |
| DLT MODE | Envoie les écarts avec la mesure précédente (compression sans perte) |
| STATS | Compare la moyenne, le minimum et le maximum calculés par l'Arduino et par Python sur `n` échantillons (50 au maximum ; `0` pour tout le tampon) |
| COMPRESSION EVAL | Enregistre 30 s dans chaque mode, soit 60 s au total, puis affiche le taux de compression |

## Format des trames

```text
@seq,ms,type,mode=LOGGING,valeurs*checksum
@788,3415016,KF,mode=LOGGING,ax=504,ay=456,az=635*62
```

- Les accélérations sont exprimées en mg.
- La somme de contrôle est un XOR, en hexadécimal, des caractères situés entre `@` et `*`.
- En mode DLT, les champs sont `dax`, `day` et `daz`. Une trame KF est tout de même envoyée toutes les 10 mesures, ou dès qu'un écart dépasse 128 mg.

## Fichiers générés

Ces fichiers sont créés dans le dossier du projet et ne sont pas versionnés. **Ils sont écrasés à chaque exécution** : copiez-les ailleurs pour les conserver.

| Fichier | Contenu | Écrasé |
| --- | --- | --- |
| `log_kf.txt`, `log_dlt.txt` | Trames reçues pendant l'acquisition, selon le mode | Au lancement du serveur |
| `log_kf_only.txt`, `log_kf_dlt.txt` | Trames enregistrées par COMPRESSION EVAL | À chaque évaluation |

## Structure du projet

```text
main.py        Serveur FastAPI et lecture du port série
logger.py      Connexion série et évaluation de la compression
index.html     Interface web
mini_sketch/   Programme Arduino
```
