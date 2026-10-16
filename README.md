# ACE60 Gamepad for Windows

Application Windows en ligne de commande ou avec interface graphique, qui transforme un clavier HID et les mouvements de la souris en manette Xbox virtuelle ViGEmBus. Les deux éditions partagent les profils, les courbes de réponse, les réglages souris et la reconnexion HID.

## Démarrage

1. Installez Python 3.12 et le pilote ViGEmBus requis par `vgamepad`.
2. Ouvrez PowerShell dans le dossier du projet et lancez `py main.py`. Le bootstrap installe les dépendances Python absentes.
3. Choisissez le clavier et configurez les touches dans le menu texte.
4. Lancez la manette. Pendant l'exécution, F9 active/désactive le joystick souris, F12 ou Ctrl+C arrête le runtime et Échap libère immédiatement le pointeur.

Le menu permet de sélectionner rapidement un profil, d'en créer d'autres, de charger les préréglages Course/FPS, d'assigner des variantes Shift et de régler la calibration, la zone morte, l'anti-deadzone, le seuil des boutons, la courbe, le polling, la disposition et la visée. Chaque stick peut utiliser indépendamment le clavier ou la souris. Le préréglage FPS sélectionne la souris pour le stick droit. La visée transforme le déplacement relatif en déflexion proportionnelle à la vitesse, plafonnée à l’amplitude maximale du stick; la sensibilité reste stable lorsque l’intervalle de polling change. L’interface graphique propose des sensibilités X/Y séparées, une zone morte de visée, trois courbes (« Linéaire », « Précision », « Accélérée »), un lissage et trois préréglages modifiables (« Précision », « Équilibré », « Rapide »). Une zone morte plus élevée ignore les faibles déflexions; le lissage réduit les variations rapides mais ajoute un léger retard. « Retour au centre » (20–1000 ms, défaut 100 ms) règle l’amortissement à l’arrêt : une durée courte recentre vite, une durée longue conserve la visée plus longtemps. Ces options sont enregistrées dans chaque profil; les anciennes configurations conservent leur sensibilité existante et reçoivent les valeurs par défaut pour les nouveaux réglages.

La calibration s'arrête quand les valeurs ont parcouru une plage utile puis se sont stabilisées; Échap l'interrompt et un délai maximal de 30 secondes évite une attente indéfinie. Les assignations clavier sont bloquées pendant le jeu. La souris est masquée et confinée aux limites de l'écran jusqu'à Échap ou l'arrêt du runtime; le statut indique quand elle est capturée ou libérée.

### Compatibilité des claviers analogiques

La détection utilise d’abord le protocole MCHOSE ACE60, puis les rapports HID qui exposent réellement leurs valeurs analogiques. Un nouveau connecteur optionnel utilise le **Wooting Analog SDK** et ses plugins : il lit les usages HID normalisés, applique les courbes du profil et fonctionne dans l’interface comme dans le runtime partagé par la CLI.

Pour activer ce connecteur, installe le Wooting Analog SDK pour Windows, installe le plugin voulu dans `C:\Program Files\WootingAnalogPlugins`, puis ouvre **Options manuelles**, sélectionne « SDK analogique + plugins compatibles » et indique la DLL du SDK. Le bouton **Détecter les claviers** liste ensuite les périphériques exposés. Pour un clavier Wooting utilisé avec Universal Analog, installe la variante du plugin qui remplace le plugin Wooting natif. La DLL et le plugin restent des composants externes et ne sont pas redistribués par cette application. Universal Analog requiert Synapse actif pour les modèles Razer signalés ci-dessous. Certains modèles Keychron ne fonctionnent qu’avec un firmware adapté; le firmware standard peut avoir une fréquence de lecture moins réactive. Les valeurs normalisées du SDK ne nécessitent pas de calibration manuelle.

| Marque / modèles | Voie de lecture dans cette application | Conditions et état |
| --- | --- | --- |
| MCHOSE ACE60 | Protocole ACE60 intégré | Modèle/protocole ACE60 uniquement; les autres appareils MCHOSE doivent exposer un HID analogique standard ou être listés dans un plugin. |
| Wooting | SDK Analog + plugin Wooting | Pris en charge par le SDK; les nouveaux modèles peuvent dépendre de la version du plugin installé. |
| Razer Huntsman V2 Analog, Huntsman Mini Analog, Huntsman V3 Pro / Mini / TKL | SDK + Universal Analog Plugin | Synapse doit être installé et actif. Les claviers Razer non analogiques ne sont pas concernés. |
| DrunkDeer | SDK + Universal Analog Plugin | Le plugin annonce la gamme DrunkDeer; vérifie que le modèle et son firmware exposent bien les entrées analogiques. |
| NuPhy | SDK + Universal Analog Plugin | Le plugin annonce les claviers NuPhy compatibles analogiques/HE. |
| Keychron Q1 HE, Q3 HE, Q5 HE, K2 HE | SDK + Universal Analog Plugin | Certains modèles demandent le firmware personnalisé fourni par la communauté. |
| Lemokey P1 HE, Madlions MAD60HE / MAD68HE / MAD68R | SDK + Universal Analog Plugin | Compatibilité annoncée par le plugin; certains firmwares d’origine peuvent entraîner latence ou pertes. |
| SteelSeries, Logitech, Corsair, Ducky, ASUS ROG, HyperX, Akko, EPOMAKER, MonsGeek, Varmilo, Glorious, Turtle Beach/ROCCAT, Cooler Master, Redragon, EVGA, Mad Catz, Trust Gaming, Endgame Gear | HID analogique standard si le descripteur expose les valeurs; sinon non pris en charge automatiquement | Aucun pilote propriétaire générique n’est intégré pour ces marques. La marque seule ne garantit ni switch magnétique ni accès aux mesures analogiques. Une prise en charge expérimentale dans un logiciel tiers ne signifie pas que son protocole est disponible ici. |

La liste Universal Analog est maintenue par sa communauté et peut évoluer : [modèles et exigences actuels](https://github.com/AnalogSense/universal-analog-plugin). Le [SDK officiel Wooting](https://github.com/WootingKb/wooting-analog-sdk) charge les plugins depuis son répertoire dédié. Pour comparer les SDK, licences, modèles et intégrations communautaires des 24 marques demandées, consulte le [dossier de compatibilité analogique](docs/compatibilite-claviers-analogiques.md). Les catalogues externes y sont distingués des protocoles effectivement intégrés à cette application. Ce projet ne devine jamais un protocole propriétaire : un appareil non listé est utilisable seulement s’il expose un des formats de lecture supportés.

### Providers SDK fabricants

Le runtime utilise une interface commune de provider (`IKeyboardSDKProvider`) et peut charger des extensions Python installées via le point d’entrée `ace60_gamepad.keyboard_providers`. Les providers sélectionnés sont initialisés sur le worker runtime; leurs appels de lecture s’exécutent dans un worker SDK séparé avec snapshot synchronisé, de sorte qu’un appel natif lent ne bloque pas directement la mise à jour ViGEmBus. Les exceptions sont consignées et entraînent la fermeture/reconnexion du provider plutôt qu’un crash de l’application. La détection au démarrage inspecte processus, services Windows, DLL connues et extensions installées; ces vérifications ne chargent pas les DLL propriétaires.

Wooting Analog SDK est le provider analogique intégré. Razer Chroma et Corsair iCUE sont détectés à titre informatif, mais leurs API publiques repérées concernent surtout l’éclairage/contrôle périphérique et ne livrent pas un flux générique de touches. Les drapeaux `sdk_providers` enregistrés dans chaque profil permettent d’activer ou désactiver l’utilisation d’un provider sans supprimer sa configuration. Les extensions tierces, leur contrat, leur installation et l’exemple JSON sont décrits dans [docs/sdk-providers.md](docs/sdk-providers.md). Le worker réduit le risque de blocage du cycle de sortie, mais Windows et les pilotes ne sont pas temps réel : la latence inférieure à 5 ms doit être mesurée sur le matériel cible et n’est pas garantie.

### Profils, DKS et SOCD

Trois préréglages sont fournis : **FPS Compétitif**, **Sim Racing** et **Aventure / Polyvalent**. Leurs données sont dans `profiles/` et les profils actifs sont conservés dans `%LOCALAPPDATA%\ACE60Gamepad\gamepad_config.json`. Chaque profil peut définir `processes` comme liste de noms `.exe`; le runtime recherche ces processus Windows toutes les trois secondes et applique automatiquement les réglages correspondants. Pour éviter de perdre une entrée capturée, le basculement en cours de session exige que le clavier et les assignations soient identiques entre les profils. Les modifications des courbes et sensibilités sont rechargées depuis le fichier de configuration sans bloquer la boucle HID; changer les hooks ou le mapping demande un redémarrage du runtime.

Les DKS sont configurés dans chaque profil avec au plus quatre seuils par scan. Exemple :

```json
"dks": {
  "30": [
    {"threshold": 25, "action": "LS_UP", "direction": "press"},
    {"threshold": 75, "action": "RT", "direction": "press"},
    {"threshold": 75, "action": "B", "direction": "release"},
    {"threshold": 25, "action": "A", "direction": "release"}
  ]
}
```

Les actions `press` suivent la profondeur au-dessus du seuil; les actions `release` émettent une impulsion de 50 ms quand la profondeur redescend sous le seuil. Les valeurs analogiques proviennent du clavier lorsque le protocole le permet; une touche numérique ne fournit que 0 ou 100 %. Une macro séquentielle peut être déclenchée par profondeur avec `macros`: chaque étape accepte `action`, `duration_ms` (1–5000) et `delay_ms` (0–5000). Exemple :

```json
"macros": [{
  "scan": 30,
  "threshold": 60,
  "steps": [
    {"action": "A", "duration_ms": 40, "delay_ms": 0},
    {"action": "RT", "duration_ms": 120, "delay_ms": 30}
  ]
}]
```

Le SOCD utilise `socd.mode: "last_input"` et des paires d'identifiants d'action dans `socd.pairs`. Quand les deux côtés sont actifs, le dernier événement clavier gagne; la paire gauche/droite du stick gauche est le réglage du profil FPS. Utilisez `"mode": "off"` pour désactiver la résolution.


L'édition graphique présente trois onglets pour le périphérique et les sticks, les affectations de touches, puis le démarrage et les diagnostics. Elle permet de gérer les profils, la calibration et un test HID de 8 secondes. Pendant ce test, appuie et relâche les touches affectées : le programme mesure les rapports et signale les valeurs analogiques qui évoluent. Les erreurs de démarrage de l’application graphique sont affichées à l’écran et inscrites dans le journal. L’édition en ligne de commande reste disponible avec `py main.py`; l’interface graphique se lance avec `py main_gui.py`.

La configuration et les journaux sont enregistrés dans `%LOCALAPPDATA%\ACE60Gamepad`, ce qui permet d'utiliser l'application depuis un dossier protégé en écriture. Une ancienne configuration placée à côté de l'exécutable est reprise au premier lancement. Les mappings QWERTY/AZERTY et les libellés des actions sont dans `config/`; les textes du terminal sont dans `locales/terminal_fr.json` et `locales/terminal_en.json`.

Les vérifications locales peuvent être lancées avec `py -m unittest discover -s tests -v`.

## Build Windows

```powershell
py -m pip install -r requirements.txt
py -m pip install -r requirements-build.txt
py scripts/vendor_vgamepad.py
py -m PyInstaller --clean ace60_gamepad.spec
py -m PyInstaller --clean ace60_gamepad_gui.spec
```

Pour créer une release avec les deux applications, poussez un tag versionné (par exemple `v1.0.0`). GitHub Actions construit sous Python 3.12, lance les vérifications automatisées, puis publie `ACE60-Gamepad-CLI.exe` (terminal) et `ACE60-Gamepad-GUI.exe` (fenêtre) en pièces jointes. Ce sont des exécutables portables PyInstaller, pas un programme d’installation MSI; ViGEmBus doit toujours être installé séparément. Le build prépare `vgamepad` sans lancer son installateur de pilote.
