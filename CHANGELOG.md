# CHANGELOG

<!-- version list -->

## v0.9.1 (2026-07-30)

### Bug Fixes

- **administration**: Sélection de la forme juridique par libellé sur la modification
  ([`cad8083`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/cad8083f61de910be00fd76f1095b7a82ba50c18))

- **pagination**: Boutons désactivés réellement inactifs au clavier
  ([`cd08b58`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/cd08b58e1c70834ca1b33713e154c9e6c3dd00c8))

- **sidebar**: Comparaison exacte des noms d'URL pour l'état actif
  ([`029c47a`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/029c47a886b763536975d49bc1ef4e9e8c5d589d))

- **ui**: Lisibilité des pastilles de marque et d'avatar en mode sombre
  ([`0797ad6`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/0797ad69d927456ff2cbbd2092da786c6406f6f0))

- **ui**: Passe responsive mobile et harmonisation visuelle des écrans
  ([`bc3dbe8`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/bc3dbe82138e7ebe5f59d29483a72dfc379c83dc))


## v0.9.0 (2026-07-28)

### Bug Fixes

- **factures**: Sort du cul-de-sac quand le SIRET du client est déjà pris
  ([`65b36e8`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/65b36e8676126ed106f1b83b2a17704c5ce85d06))

- **navigation**: Les liens du menu public ramènent à l'accueil
  ([`58ac3a2`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/58ac3a294bf0ed4d19f552cc241049c817c93fa3))

- **session**: Affiche l'état déconnecté dès que le JWT a expiré
  ([`921528e`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/921528ea8d73c168d111b5c575698530fdfec6f3))

### Features

- **accueil**: Refonte de la vitrine avec prise en charge du thème sombre
  ([`3ae0f8a`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/3ae0f8a153e952a39d3fd12d4d5754c1b6ec9ac9))

- **administration**: Fiche détaillée d'une entreprise et actions de gestion
  ([`86a7a24`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/86a7a24626194c558288ce944e64ca1f1e2c935d))

- **administration**: Groupe Administration dans la sidebar et pages admin dans le layout dashboard
  ([`f8afd52`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/f8afd5201cddd7bafac30c512193b36b45454f87))

- **administration**: Liste des entreprises abonnées pour l'admin plateforme
  ([`b858ddd`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/b858ddd82149b6ad6838c5ece3b84c09c15fa2cd))

- **compte**: Remplace « Paramètres » par « Modifier mes accès » dans le menu profil
  ([`2c8b14d`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/2c8b14d1470a82dd7e1ef4ee150db29ed08f41e9))

- **compte**: Sépare les informations du compte et la gestion des accès
  ([`dcb2667`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/dcb26677ee532da946737118a689dfcb55fedfed))

- **documents**: Bouton vers la liste des documents sur l'écran de dépôt
  ([`c5b333d`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/c5b333ddcb94b1f4330e40a4c8742fa05cc6dba1))

- **documents**: Liste des documents uploadés et consultation des fichiers
  ([`91a3dfb`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/91a3dfb3f341e41ca2d4618d9c770cb94cce52af))

- **documents**: Suppression d'un document depuis la liste
  ([`b5726c4`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/b5726c45dfca070c4772b294ee1b2f4927946f4a))

- **factures**: Colonne Statut en badges colorés sur l'onglet validées
  ([`6832c97`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/6832c974481a60b45b37507c76b19b3a7f6990db))

- **factures**: Surlignage des champs à faible confiance et type détecté sur le récap
  ([`43635df`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/43635df6b66c25b39bf3a3d5d836b97d7dfb1089))

- **layout**: Migre les pages principales dans le layout dashboard
  ([`f52fbb5`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/f52fbb584cb5ce511321f5248982f79fd2df1cf9))

- **layout**: Squelette du layout dashboard avec barre latérale
  ([`3bae345`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/3bae3459990dc8e58ea18573d2d8091291fa06b5))

- **layout**: Étend la sidebar du dashboard à toutes les sous-pages connectées
  ([`a499733`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/a4997332700462c8a51a9a646b3f191ca808ceb4))

- **navigation**: Accès à l'administration plateforme depuis le header
  ([`da392d9`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/da392d9f250c3000b1de38c73d3f9d0462bf6fe0))

- **onboarding**: Permet à un admin plateforme de souscrire un abonnement
  ([`3b72a2e`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/3b72a2e280d622b86a51db140b6cd904dc6ff315))

- **onboarding**: Recherche SIRENE pour pré-remplir les informations de l'entreprise
  ([`e03b8d7`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/e03b8d76af4c70a99df7c2403793c0c8cd4352bf))

- **statistiques**: Page Statistiques avec sélecteur de période et chiffres de synthèse
  ([`deb311f`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/deb311f6dcf70cf766e87c6ebf3a3eb53b1e8967))

- **statistiques**: Visualisations en barres CSS — évolution mensuelle, statuts, meilleurs clients
  ([`0da1454`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/0da1454b25d7af941cff03c0c544538f4b8cef6a))

- **tableau-de-bord**: Vraie page d'accueil connectée en remplacement de la démo
  ([`cc0c3e2`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/cc0c3e22e48df3102e3371ce90997f6cb03492da))

- **ui**: Bascule clair/sombre sur toute l'application
  ([`d594dff`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/d594dffa4eae3a87c8d9570aaf510a5c8cda6cdb))

- **ui**: Peuple la barre latérale du dashboard
  ([`a3cfefb`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/a3cfefba8169b90cbb0c2b611b568f7c0895bcad))

- **ui**: Refonte du header public avec menu profil et thème adaptatif
  ([`4c1eba1`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/4c1eba16240a617f16fc46513dc89eee0783ba9a))

- **ui**: Épure le header public
  ([`75f2c4c`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/75f2c4c5866a040c77d5c0fa1a0da689787be978))


## v0.8.0 (2026-07-27)

### Bug Fixes

- **factures**: Clarifie les actions du récap d'un brouillon
  ([`c7560d9`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/c7560d96a38b514f6803a28f237a36a62fe268cf))

- **factures**: Élargit l'écran d'édition d'un brouillon pour afficher toute la ligne
  ([`10821d5`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/10821d5f8d3a1a25ef1b50ab82b8b70ad2c7670b))

### Features

- **documents**: Écran d'attente asynchrone pendant l'extraction
  ([`a7c677b`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/a7c677baee62de74d1870ad3f24a53a16b5e8820))

- **factures**: Ajout et suppression de lignes à l'édition d'un brouillon
  ([`db7ee50`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/db7ee5053ff8c402e21cb0f9e45fbb9449dac2e3))

- **factures**: Alerte de divergence du SIRET émetteur dans le récap
  ([`a8e8703`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/a8e870354cf4c32670e0df4d228e8a4dace6169a))

- **factures**: Aperçu mis en forme d'une facture validée
  ([`3c84e08`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/3c84e08b4db8ec416322df40877d5798b03e10e7))

- **factures**: Bouton Annuler sur l'écran d'édition d'un brouillon
  ([`d6acf05`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/d6acf0506255c37480e4bce698fffcdf12b01ee7))

- **factures**: Correction et validation des champs extraits dans le récap
  ([`0f040ef`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/0f040efe7104c404564999c5ca97340ae32d5e84))

- **factures**: Génération d'un avoir depuis une facture validée
  ([`3b3585b`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/3b3585be5d6022bf21de917b5c6aad3b2fab05a9))

- **factures**: Liste des factures en deux onglets (brouillons et validées)
  ([`9190282`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/91902823928b92cc8dc6f81f6bb282f1ed3f28bf))

- **factures**: Rattachement ou création du client destinataire dans le récap
  ([`96e3703`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/96e37037b8723cac6ca84c2fbd0ebd2135b9e5d5))

- **factures**: Saisie des SIRET émetteur et destinataire dans le récap
  ([`497c4c4`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/497c4c4dac5e44a739db3e4f4915a6a5b28bdcd6))

- **factures**: Suppression d'un brouillon depuis la liste
  ([`363c2c9`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/363c2c9b01c836a9727f60e13129ec62e1e6850f))

- **factures**: Écran de récap human-in-the-loop des données extraites
  ([`d0eba01`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/d0eba015e5d3754f2aba83686cef5446baa8f0fd))

- **profil**: Affiche les informations de l'entreprise sur la page de profil
  ([`e7bcfbb`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/e7bcfbb2e836fe27a7bf2aa5bc8fe5191dfd08ef))


## v0.7.0 (2026-07-03)

### Features

- **accueil**: Refonte de la vitrine et garde-fou d'accès
  ([`fc5f7a3`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/fc5f7a3c6fc768edd483871eb466188281668d8b))

- **admin**: Parcours dédié pour l'admin plateforme sans entreprise
  ([`f8ccfae`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/f8ccfaeada7556a58ea9f9620b455a3b80cfcaca))

- **profil**: Page de modification du profil utilisateur
  ([`a5af5f8`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/a5af5f88a526351bc0f600094dde7750791c159e))

- **taux-tva**: Page d'administration des taux de TVA (admin plateforme)
  ([`439c2a3`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/439c2a3a26dfcc520eb0aa01b329afdda7f4bc98))


## v0.6.0 (2026-07-03)

### Bug Fixes

- **equipe**: Affichage du message de limite du plan lors de l'ajout ou la réactivation d'un membre
  ([`152c656`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/152c6566ca36febc6790f2ba38d183cc859527fa))

- **gestion**: Affichage des conflits d'unicité renvoyés par l'API
  ([`160f4da`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/160f4da82b6b5f6a0346d4a544cdfeb0304b6f4a))

### Features

- **abonnements**: Affichage des plans et gestion admin des abonnements
  ([`d9bba92`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/d9bba9256d7f8169a0976802ea1b2fba8db9d598))

- **abonnements**: Changement de plan depuis la page abonnements
  ([`b5bfe94`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/b5bfe94197472d34ab5828636970938ae1f0b0a4))

- **abonnements**: Prolongation de l'abonnement et affichage de l'échéance
  ([`2db228e`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/2db228e8434d6f3985d3bb92065d4e8d150d7518))

- **admins-plateforme**: Gestion des administrateurs de plateforme
  ([`9d81ac6`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/9d81ac693af68246ac146f9e003fa69260939afd))

- **equipe**: Accès à la page équipe réservé aux rôles autorisés
  ([`1b58611`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/1b5861186263f889722bed906cc13c6889a38a71))

- **equipe**: Masquage préventif de la suppression du compte protégé
  ([`45e69a5`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/45e69a51742354e7b15a12c14a4cb626a72b1094))

- **equipe**: Visualisation, désactivation et réactivation des membres
  ([`d84a2de`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/d84a2ded14e8a8199ce5c7409d91beeb02fd1fe3))

- **gestion**: CRUD des clients et du catalogue produits
  ([`9862657`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/986265792688fd0c0575d2b50f8f7d228ef702af))

- **gestion**: Réactivation des clients et produits depuis la liste
  ([`935364a`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/935364ae1efa03f4078b484411fa9c0e6bf3de11))


## v0.5.0 (2026-07-02)

### Features

- **auth**: Pages d'authentification (sign-in/up, mot de passe oublié/reset)
  ([`80e4ea0`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/80e4ea045d86ae3d8e0640f39f71702bf6ba26e1))

- **listes**: Recherche, filtres et pagination des clients et du catalogue
  ([`5b7337a`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/5b7337a0087c9a019ca018aa32324b9698e39a58))

- **onboarding**: Création d'espace de travail post-login
  ([`5f1aa16`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/5f1aa164bbc8031dbcc1878ff04c068ce67005dc))

- **ui**: Gabarit principal (header/footer) et page d'accueil
  ([`7a08add`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/7a08add8579defcc903a2fb770b4c4740c60d20f))


## v0.4.0 (2026-07-01)

### Features

- **clients**: Implémente les clients HTTP métier et documente la couche API
  ([`5f88e95`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/5f88e959155ecede28db54ef0c8696a8409eb238))

- **clients**: Résilience réseau (timeouts, retries, exceptions métier)
  ([`eef862e`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/eef862e30478c6999131f7e7488b291341697bc7))

- **documents**: Flux complet d'upload de fichiers vers l'API Data
  ([`63952ee`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/63952eea7f205204d6e7e7b66d64050f91a1d55a))

- **ui**: Intègre daisyUI + Alpine.js et refond la page équipe
  ([`dff8a57`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/dff8a5742e5504a08e36a1e2a2122da885ca7c98))


## v0.3.0 (2026-06-30)

### Bug Fixes

- **auth**: Résout l'entreprise active via /abonnements/me
  ([`2e01e77`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/2e01e7732a2dcfb7b5fff73c3276a8de4d25a25b))

### Chores

- Ignore les fichiers Claude Code et recompile le CSS Tailwind
  ([`5e7b120`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/5e7b120cb8f6187ef65eab6aae9c387f4c4c2c98))

- **contrat**: Ajoute le contrat OpenAPI et sa procédure d'export
  ([`c83a133`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/c83a133f5fd9f467a1e5695ae68e5a4e12482e69))

### Features

- **auth**: Implémentation de la connexion BFF (Backend For Frontend) via API et sessions Redis
  ([`5a3c3df`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/5a3c3df9ae1799dc2eb48ab052acdc41d58d18b2))

- **documents**: Relais d'upload de fichiers vers l'API Data
  ([`eea928e`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/eea928e6948e67781c2a0b4399ef9ab717cb749d))

- **equipe**: Ajout de l'interface d'invitation et de gestion de l'équipe
  ([`10c1d1e`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/10c1d1e986b9956cd9feee40a510596107c9506e))

- **equipe**: Ajout de la gestion complète des collaborateurs (CRUD)
  ([`0693548`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/0693548cea0695494952e116e946fda8285c18b3))

- **equipe**: Ajout de la modification des collaborateurs
  ([`a4f5773`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/a4f57738e834999ac31fa8857d0e86b3e20d2a2c))

- **equipe**: Validation serveur des formulaires et correction de l'édition
  ([`bb5770e`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/bb5770e5ef6ab42dfed7b39d188f2251efac2305))


## v0.2.0 (2026-06-07)

### Chores

- **ci**: Configuration de semantic-release pour la phase bêta (0.x.x)
  ([`891cb53`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/891cb538285e196fd168fd1529ef095dfb97c8d2))

### Features

- Déclenchement manuel de la release 0.2.0
  ([`498330f`](https://github.com/Malek-Boumedine/factur-ia-web-client/commit/498330f1034477706fc5968f1c03b36c1f2cfb8e))


## v1.0.0 (2026-06-07)

- Initial Release
