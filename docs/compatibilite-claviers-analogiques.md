# SDK et compatibilité des claviers analogiques

État de la recherche : 15 octobre 2026. « HE » désigne les interrupteurs Hall Effect; « analogique » signifie que le logiciel hôte peut lire une valeur de course par touche. Un clavier HE n’expose pas nécessairement cette valeur hors de son configurateur.

## Références logicielles et SDK

| Projet | Ce qu’il apporte | Portée et limites | Licence / intérêt pour ce projet |
| --- | --- | --- | --- |
| [Wooting Analog SDK](https://github.com/WootingKb/wooting-analog-sdk) | API native pour lire les valeurs analogiques, extensible par plugins C/Rust/ABI. | Wooting; peut lire d’autres marques si un plugin adéquat est installé. Sur Windows, le SDK peut être installé par Wootility ou distribué avec l’application. | MPL-2.0. C’est le connecteur déjà ajouté à ce projet. |
| [Universal Analog Plugin](https://github.com/AnalogSense/universal-analog-plugin) | Ajoute des lecteurs de claviers tiers au Wooting Analog SDK. | Razer Huntsman V2/V3 analogiques, claviers NuPhy HE, DrunkDeer, quelques Keychron HE, Lemokey et Madlions. Synapse est requis pour certains Razer; le firmware officiel de quelques modèles Keychron/Madlions peut limiter le débit. Wooting nécessite la variante du plugin qui remplace le plugin Wooting. | Extension la plus directe pour étendre le connecteur SDK actuel; les modèles et exigences varient selon la révision du plugin. |
| [DrunkDeerSDK](https://github.com/deerios/DrunkDeerSDK) | Bibliothèque .NET indépendante de lecture et configuration USB HID, avec événements et valeurs de hauteur par touche. | A75, A75 Pro, G60, G65, G75 et autres modèles listés par le projet. Le mainteneur indique que l’A75 est le seul modèle confirmé manuellement dans son tableau de validation. | MIT. Bon candidat pour un adaptateur propre si le plugin Wooting ne convient pas; ce n’est pas un SDK officiel du fabricant. |
| [Apex Analog Mapper](https://github.com/lavindeep/apex-analog-mapper) | Application Windows qui lit les profondeurs de touche SteelSeries et produit une manette Xbox. | SteelSeries Apex Pro; projet annoncé en alpha, calibrage associé au clavier et au firmware. | MIT. Référence directe pour un futur adaptateur SteelSeries; vérifier le protocole et les conditions de partage avant de réutiliser du code. |
| [HallJoy](https://github.com/PashOK7/HallJoy) | Application Windows analogique vers manette avec lecteurs natifs, SDK/plugin, détection et profils. | Liste séparée en « supported » et « experimental »; couvre de nombreux modèles DrunkDeer, Keychron, NuPhy, Razer, SteelSeries, Logitech, MCHOSE, MonsGeek, Redragon, Akko et EPOMAKER, entre autres. L’étiquette expérimentale signifie que le modèle n’a pas été testé physiquement par l’auteur. | AGPL-3.0 avec option commerciale annoncée. Ne pas incorporer son code dans une édition propriétaire sans respecter la licence ou obtenir l’autorisation correspondante. Utile comme catalogue de modèles et pistes de protocole. |
| [PadForge — clavier analogique](https://padforge.org/docs/features/analog-keyboards/) | Application Windows de remappage; sa documentation catalogue plus de 370 modèles de 101 marques et décrit les voies de lecture. | Couvre notamment ASUS, Akko, DrunkDeer, EPOMAKER, Keychron, Logitech, MCHOSE, MonsGeek, NuPhy, Razer, Redragon, SteelSeries et Wooting. Certaines voies demandent Synapse, USB filaire ou changent un réglage persistant du clavier. La documentation précise que ses lecteurs n’ont pas été validés en direct par le mainteneur; elle s’appuie sur captures et lecteurs communautaires. | CC BY-NC-SA 4.0; la documentation de licence signale aussi des lecteurs dérivés de HallJoy AGPL-3.0. Très bon catalogue de marché, mais base inadaptée à une intégration commerciale directe. |
| [libhmk](https://github.com/peppapighs/libhmk) | Firmware open source pour concevoir des claviers Hall Effect, avec entrée analogique et mode gamepad. | Utile aux fabricants/constructeurs qui contrôlent leur firmware; ce n’est pas un pilote universel pour les claviers de série. | GPL-3.0. À considérer pour des appareils personnalisés ou une piste firmware, pas comme connecteur hôte générique. |
| [AnalogSense JavaScript SDK](https://github.com/AnalogSense/JavaScript-SDK) et [Soup](https://github.com/calamity-inc/Soup) | SDK WebHID et lecteurs USB/HID utilisés comme références par des applications analogiques. | Le SDK JS documente Wooting, NuPhy, DrunkDeer, certains Razer/Keychron/Lemokey/Madlions et Redragon K709HE. Les navigateurs doivent permettre WebHID; ce n’est pas un pilote Windows embarquable directement. | MIT indiqué sur les dépôts. Soup est un lecteur natif de référence; valider ses dépendances et conditions avant réutilisation. |

### Familles de modèles communautaires à examiner

Les catalogues ci-dessous recensent bien plus de modèles que les SDK réutilisables listés plus haut. Ils servent à bâtir une matrice de compatibilité et à prioriser des essais; une entrée dans leur liste ne constitue pas une validation matérielle indépendante. PadForge annonce plus de 370 modèles/101 marques, mais précise que ses lecteurs ne sont pas tous confirmés sur matériel par son mainteneur. HallJoy sépare ses modèles pris en charge et expérimentaux. Les états pouvant changer à chaque version, conserver la date, le firmware et la source pour chaque modèle testé.

Exemples supplémentaires visibles dans ces catalogues : AJAZZ AK820 MAX HE; AULA WIN 60/68 HE et variantes; ATK Hex80; ATTACK SHARK R85 HE/X65 Pro; GravaStar Mercury V75; IROK MG75 Max/NA87; Keychron Q2/Q4/Q6/Q12 HE, K3/K4/K6/K8/K10 HE; Madlions MAD68 HE V2; MCHOSE Jet 75 II et Mix 87 III; Redragon K617 HE/K673RGB-M/K709 HE/K712 RGB-M/M68; Royal Kludge RK68 HE; Skyloong GK61/GK68/GK75 HE; SayoDevice O3C; plus les gammes Wooting, Razer, NuPhy, DrunkDeer, SteelSeries et ASUS citées ci-dessus. Consulter les liens des sources pour les références, variantes et avertissements à jour.

**Niveaux à utiliser dans notre catalogue :** `SDK officiel` (API du fabricant), `plugin communautaire` (adaptateur existant), `lecteur communautaire` (code HID indépendant), `expérimental` (non validé sur le modèle/firmware visé), `matériel analogique sans lecteur repéré`, puis `vérifié ici` uniquement après essai physique consigné. Distinguer explicitement connexion USB, dongle 2,4 GHz et Bluetooth; un chemin USB fonctionnel ne prouve pas la compatibilité sans fil.

Le SDK Wooting définit un ABI de plugin, mais ne rend pas automatiquement analogique un clavier qui ne publie pas ses mesures. Son API distribue les valeurs issues des plugins installés. Voir la [documentation d’installation](https://github.com/WootingKb/wooting-analog-sdk/blob/develop/docs/INSTALL.md) et la [documentation des plugins](https://github.com/WootingKb/wooting-analog-sdk/blob/develop/docs/PLUGINS.md).

## État des marques demandées

Le statut « dans notre application » décrit seulement le code présent ici; les catalogues tiers ne signifient pas que ces protocoles sont déjà implémentés ici.

| Marque | Modèles analogiques / piste publique repérée | Dans notre application |
| --- | --- | --- |
| Wooting | 60HE, 80HE, Two HE et autres modèles à reporting analogique; SDK officiel. | SDK/plugin optionnel ajouté. |
| SteelSeries | Apex Pro, Apex Pro Gen 3 et Apex Pro TKL; Apex Analog Mapper MIT et lecteurs communautaires. | Pas encore intégré; utiliser la voie MCHOSE/HID seulement si le clavier expose un format déjà reconnu. |
| Razer | Huntsman V2 Analog, Huntsman Mini Analog et plusieurs Huntsman V3 Pro; Universal Analog / lecteurs communautaires. Synapse peut être nécessaire. | SDK/plugin optionnel ajouté; détection dépend de l’installation du plugin et de Synapse. |
| DrunkDeer | A75/A75 Pro, G60/G65/G75 et autres; DrunkDeerSDK indépendant et Universal Analog. | SDK/plugin optionnel ajouté; le SDK direct n’est pas encore intégré. |
| MCHOSE | ACE60; des lecteurs communautaires listent notamment Jet 75, Mix 87 III et plusieurs ACE. Mix 87 III peut nécessiter le firmware 1.22 et l’activation d’un indicateur de rapport. | Protocole ACE60 intégré; autres modèles non garantis ici. |
| Endgame Gear | KB65HE (versions 8K incluses) : clavier Hall Effect confirmé, avec outil de configuration officiel. Aucun SDK public de lecture de course par touche ni lecteur tiers confirmé dans les catalogues consultés. | Non intégré; ne pas confondre réglage d’actuation dans le configurateur et accès à la profondeur analogique. |
| Keychron | Large famille HE Q/K; Universal Analog liste quelques modèles avec limitations de firmware; PadForge documente davantage de modèles et firmwares d’origine. | SDK/plugin pour les modèles exposés par Universal Analog seulement. |
| Logitech | PRO X TKL RAPID; catalogue PadForge et HallJoy expérimental indiquent une lecture de profondeur, sans SDK analogique public repéré. | SDK/plugin seulement si un plugin l’expose; aucun lecteur Logitech spécifique dans notre application. |
| Corsair | K70 MAX/MGX et gammes K70 Pro TKL/Vanguard à switches magnétiques. iCUE SDK public documente le contrôle des périphériques/éclairages, pas une API de profondeur par touche. La présence de capteurs ne garantit pas une sortie analogique accessible. | Non intégré. |
| Ducky | One X / One X Wireless : switches inductifs analogiques et réglages multi-point/rapid trigger confirmés par Ducky. Aucun SDK public ou lecteur tiers de profondeur repéré. | Non intégré; présence de capteurs analogiques ne garantit pas une interface hôte publique. |
| ASUS ROG | ROG Azoth 96 HE documenté par PadForge/HallJoy en USB; la réception sans fil n’est pas indiquée comme supportée par PadForge. | Non intégré. |
| HyperX | Aucun lecteur analogique public repéré dans les sources consultées. | HID générique si la valeur analogique est exposée; sinon non pris en charge. |
| Akko | MOD 007 V5 HE, MOD007B/S V3 HE, Ray68 HE, TAC75 HE figurent dans les catalogues communautaires. | Pas de lecteur natif ici; générique HID ou futur adaptateur validé. |
| EPOMAKER | HE108 et plusieurs modèles HE figurent dans les catalogues communautaires. | Pas de lecteur natif ici; générique HID ou futur adaptateur validé. |
| MonsGeek | FUN60, FUN68, FUN75 et séries M1/M2/M3 HE/TMR dans les catalogues communautaires. | Pas de lecteur natif ici; générique HID ou futur adaptateur validé. |
| Varmilo | Aucun SDK/lecteur analogique public repéré pour les modèles consultés. | HID générique si les mesures sont exposées. |
| NuPhy | Air60/Air75 HE, Field75 HE et autres modèles listés par le plugin et PadForge. | SDK/plugin optionnel ajouté. |
| Glorious | GMMK 3 HE et GMMK 3 PRO HE (filaire et certaines versions sans fil) : Hall Effect, rapid trigger et actuation réglable via CORE. Aucun SDK public de lecture analogique ou lecteur tiers vérifié repéré. | Non intégré; CORE est requis pour certaines fonctions HE, sans API analogique publique identifiée. |
| Turtle Beach / ROCCAT | Le marché compte des périphériques de jeu analogiques, mais aucun lecteur de clavier analogique ROCCAT/Turtle Beach correspondant n’a été confirmé dans les sources consultées. | Non intégré. |
| Cooler Master | Aucun SDK/lecteur analogique public repéré pour un clavier HE de cette marque dans les catalogues consultés. | HID générique si les mesures sont exposées. |
| Redragon | Plusieurs références apparaissent, dont K617 HE, K673RGB-M, K712 RGB-M et M68, selon les catalogues communautaires. | Pas de lecteur natif ici; générique HID ou futur adaptateur validé. |
| EVGA | Aucun SDK/lecteur de clavier analogique public repéré dans les catalogues consultés. | Non intégré. |
| Mad Catz | Aucun SDK/lecteur de clavier analogique public repéré pour cette marque. Attention : « Madlions » est une marque distincte présente dans les catalogues; ne pas les confondre. | Non intégré. |
| Trust Gaming | Aucun SDK/lecteur analogique public repéré dans les catalogues consultés. | HID générique si un modèle fournit des mesures analogiques standard. |

## Conséquences pour la feuille de route

1. Conserver le connecteur Wooting/Universal Analog déjà ajouté et améliorer son installation/détection guidées. C’est la voie la plus rapide pour Wooting, Razer ciblé, DrunkDeer, NuPhy et certains Keychron.
2. Ajouter ensuite des lecteurs isolés et testables pour SteelSeries Apex Pro et DrunkDeer, en s’appuyant sur des projets MIT ou leur protocole observable plutôt que d’importer les bases HallJoy/PadForge.
3. Construire un catalogue de modèles versionné séparément des lecteurs : `modèle → protocole → connexion USB/dongle → firmware requis → statut testé → source`. Un changement de VID/PID ou firmware ne doit jamais être assimilé automatiquement à une compatibilité.
4. Exiger un test matériel pour passer une référence de « communautaire/expérimentale » à « vérifiée ». Conserver un chemin HID standard comme détection générique, sans prétendre qu’il extrait des mesures propriétaires.

## Sources principales

- [Wooting Analog SDK](https://github.com/WootingKb/wooting-analog-sdk), [API et plugins](https://github.com/WootingKb/wooting-analog-sdk/blob/develop/docs/SDK_USAGE.md)
- [Universal Analog Plugin et modèles](https://github.com/AnalogSense/universal-analog-plugin)
- [DrunkDeerSDK, modèles et validation](https://github.com/deerios/DrunkDeerSDK)
- [SteelSeries Apex Analog Mapper](https://github.com/lavindeep/apex-analog-mapper)
- [HallJoy, listes supported/experimental et licence](https://github.com/PashOK7/HallJoy)
- [PadForge, matrice analogique](https://padforge.org/docs/features/analog-keyboards/), [internals et provenance des lecteurs](https://padforge.org/docs/reference/analog-keyboards-internals/), [licence](https://github.com/hifihedgehog/PadForge/blob/main/LICENSE)
- [Corsair K70 MAX: actuation points](https://help.corsair.com/hc/en-us/articles/18175239292173-K70-MAX-Key-Actuations-Guide), [iCUE SDK public](https://github.com/CorsairOfficial/cue-sdk)
- [Endgame Gear KB65HE](https://endgamegear.com/collections/all-products), [outil de configuration KB65HE](https://endgamegear.com/pages/kb65he-downloads)
- [Glorious GMMK 3 HE: guide officiel](https://www.gloriousgaming.com/pages/guide-gmmk3-he), [gamme officielle Hall Effect](https://www.gloriousgaming.com/collections/hall-effect-keyboards)
- [Ducky One X Wireless: switches analogiques inductifs](https://ducky.global/products/one-x-wireless)
