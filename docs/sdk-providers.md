# Providers SDK clavier

L’application expose un contrat commun dans `gamepad_app.hid.providers.IKeyboardSDKProvider`. Le runtime charge le provider uniquement dans son worker et publie son dernier snapshot au cycle de conversion manette. Une erreur d’initialisation ou de lecture ferme le provider, journalise la cause et arrête seulement la voie analogique SDK; l’application et les entrées clavier classiques restent utilisables.

## État intégré

- **Wooting Analog SDK** est le seul provider natif de lecture analogique actuellement intégré. Il lit les usages HID et valeurs normalisées 0–1; les plugins compatibles Wooting SDK peuvent ajouter les autres modèles qu’ils prennent effectivement en charge.
- **Razer Chroma**, **Corsair iCUE** et **Logitech G** sont détectés à titre diagnostique par processus, service Windows ou DLL connue. Les API publiques repérées pour Chroma/iCUE concernent surtout l’éclairage et le contrôle périphérique, pas un flux générique des pressions. La détection n’active donc pas faussement ces SDK comme source de touches. Le clavier continue d’utiliser la voie existante.
- Les extensions tierces peuvent ajouter de vrais lecteurs via le point d’entrée Python décrit ci-dessous. Ne jamais supposer que la présence du logiciel fabricant implique une API de lecture clavier.

Références : [Wooting Analog SDK](https://github.com/WootingKb/wooting-analog-sdk/blob/develop/docs/SDK_USAGE.md), [API Razer Chroma](https://assets.razerzone.com/dev_portal/docs/_rz_chroma_s_d_k_8h.html), [iCUE SDK officiel](https://github.com/CorsairOfficial/cue-sdk), [SDK Logitech G officiels](https://www.logitechg.com/en-us/programs/developer-alliance). Logitech publie notamment les SDK LED, G-Key Macro, GamePanel et volant; le G-Key Macro sert aux touches macro dédiées et ne constitue pas un flux portable de toutes les touches.

## Contrat d’extension

Un provider doit avoir un identifiant, annoncer ses capacités, puis implémenter ces trois méthodes :

```python
class MyProvider:
    provider_id = "my_vendor"
    capabilities = frozenset({"digital_keys", "analog_travel"})

    def initialize(self, settings: dict) -> None:
        # Charger la DLL ici. Lever une exception claire si SDK/service absent.
        ...

    def read_keys(self) -> dict[int, float]:
        # Usage HID -> valeur analogique normalisée dans [0.0, 1.0].
        # Les valeurs nulles signalent le relâchement d’une touche.
        ...

    def close(self) -> None:
        # Décharger proprement le SDK et retirer callbacks/handles.
        ...
```

Distribuer l’extension comme paquet Python avec un point d’entrée :

```toml
[project.entry-points."ace60_gamepad.keyboard_providers"]
my_vendor = "my_package.provider:MyProvider"
```

L’identifiant apparaît dans **Options manuelles → Provider SDK actif**. Les valeurs transmises à `initialize` comprennent `library`, `device_id`, `keyboard` et le `profile`; un provider peut ignorer les options qui ne le concernent pas. `read_keys` est exécuté dans un thread daemon distinct environ toutes les millisecondes. Toute exception est remontée sous forme de diagnostic runtime, pas laissée sortir du thread. `close` s’exécute sur ce thread après l’arrêt de la lecture afin d’éviter de décharger une DLL pendant un appel natif.

Les appels d’initialisation se font sur le worker runtime, jamais sur l’interface. Les lectures asynchrones évitent de bloquer le cycle de mise à jour manette; elles ne constituent pas une garantie temps réel. La latence de bout en bout dépend du SDK, de son service, de l’ordonnanceur Windows, du pilote ViGEmBus et du jeu. Une cible inférieure à 5 ms doit être mesurée sur les machines et firmwares visés.

## Configuration par profil

Extrait conservé dans chaque profil :

```json
{
  "sdk_providers": {
    "wooting": true,
    "razer_chroma": false,
    "corsair_icue": false,
    "logitech_g": false,
    "plugin:my_vendor": true
  },
  "keyboard": {
    "protocol": "sdk_provider",
    "sdk_provider": "plugin:my_vendor",
    "sdk_library": "",
    "sdk_device_id": null
  }
}
```

Les anciennes configurations reçoivent les fournisseurs par défaut à la migration. `wooting_sdk` reste accepté pour les profils existants. Un provider désactivé, manquant, incompatible ou en erreur n’empêche pas le démarrage de l’application; le journal explique le repli.

## Ajouter une marque correctement

1. Vérifier qu’il existe une API documentée pour lire les touches (pas seulement RGB, macros ou réglages d’actuation).
2. Vérifier si le flux fournit des valeurs analogiques continues ou seulement des événements pressé/relâché.
3. Tester les modèles, versions de firmware, modes USB/dongle/Bluetooth et logiciel fabricant requis.
4. Garder le SDK comme dépendance externe lorsque sa licence ou ses redistributions l’exigent; ne pas extraire les DLL propriétaires dans le binaire.
5. Tester arrêt, déconnexion, service arrêté, DLL incompatible et exception de lecture. Les états ne doivent jamais rester bloqués en sortie.
