"""Client HTTP pour le backoffice d'administration de la plateforme.

Couvre le domaine `administration` de l'API, réservé aux administrateurs de
plateforme :

- GET /administration/entreprises : liste paginée des entreprises abonnées.
- GET /administration/entreprises/{id} : détail (membres, historique, compteurs).
- PATCH /administration/entreprises/{id} : identité légale (raison sociale,
  SIRET, forme juridique).
- DELETE /administration/entreprises/{id} : suppression protégée.
- POST /administration/entreprises/{id}/suspendre | /reactiver.
- POST /administration/entreprises/{id}/abonnement/changer | /prolonger |
  /resilier.
- GET /administration/utilisateurs : liste paginée, toutes entreprises.
- GET /administration/utilisateurs/{id} : détail (rattachements, compteurs).
- DELETE /administration/utilisateurs/{id} : suppression protégée.
- POST /administration/utilisateurs/{id}/desactiver | /reactiver.

Ces routes sont **globales** : l'administrateur agit sur n'importe quelle
entreprise, hors de toute isolation tenant. Ce client retire donc volontairement
le header `x-entreprise-id` injecté par défaut par `BaseAPIClient`.

Les garde-fous métier de l'API (facture émise, compte protégé, dernier
administrateur, entreprise non vide) remontent en 403 ou en 409 avec un `detail`
explicite, destiné à être affiché tel quel à l'administrateur.
"""

from typing import Any

from .base_client import BaseAPIClient


class AdministrationClient(BaseAPIClient):
    """Client HTTP du backoffice d'administration (`/administration/...`).

    Hérite de `BaseAPIClient` (JWT injecté depuis la session) mais surcharge
    `auth_headers` pour **ne pas** transmettre `x-entreprise-id` : ces routes
    sont hors tenant. Chaque méthode correspond exactement à une route du
    contrat OpenAPI.
    """

    @property
    def auth_headers(self) -> dict[str, str]:
        """En-têtes d'authentification sans le tenant `x-entreprise-id`.

        Reprend les en-têtes de `BaseAPIClient` (dont `Authorization: Bearer`)
        et retire l'éventuel `x-entreprise-id` : l'administrateur de plateforme
        agit sur n'importe quelle entreprise, pas seulement la sienne.

        Returns:
            dict[str, str]: En-têtes d'authentification sans le header de tenant.
        """
        return {k: v for k, v in super().auth_headers.items() if k != "x-entreprise-id"}

    # --- Entreprises -----------------------------------------------------

    def list_entreprises(
        self,
        recherche: str | None = None,
        est_actif: bool | None = None,
        statut_abonnement: str | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> Any:
        """Liste les entreprises abonnées (paginé, filtrable).

        Appelle GET /administration/entreprises. Les filtres ne sont transmis
        que s'ils sont fournis.

        Args:
            recherche (str | None): Recherche sur la raison sociale ou le SIRET.
                Optionnel.
            est_actif (bool | None): Filtre sur l'état d'activité
                (`False` = suspendue). `None` = toutes. Optionnel.
            statut_abonnement (str | None): Filtre sur le statut de la
                souscription courante (enum StatutSouscription : `actif`,
                `expiré`, `suspendu`, `annulé`). Optionnel.
            skip (int): Offset de pagination. Défaut 0.
            limit (int): Taille de page (max 100 côté API). Défaut 20.

        Returns:
            dict: Page paginée (schéma Page[EntrepriseAdminListItem]) avec
            `items`, `total`, `skip` et `limit`.

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIClientError: Toute autre erreur API mappée (403 accès refusé si
                l'appelant n'est pas admin plateforme, 422 validation, 5xx
                serveur) ou API injoignable (APIUnavailableError).
        """
        params: dict[str, Any] = {"skip": skip, "limit": limit}
        if recherche:
            params["recherche"] = recherche
        if est_actif is not None:
            params["est_actif"] = est_actif
        if statut_abonnement:
            params["statut_abonnement"] = statut_abonnement
        return self.get("/administration/entreprises", params=params)

    def get_entreprise(self, entreprise_id: int) -> Any:
        """Récupère le détail complet d'une entreprise.

        Appelle GET /administration/entreprises/{entreprise_id}. Les compteurs
        renseignent directement sur ce qui bloquerait une suppression.

        Args:
            entreprise_id (int): Identifiant de l'entreprise. Obligatoire.

        Returns:
            dict: Détail (schéma EntrepriseAdminDetail) : identité, `membres`,
            `souscriptions` (du plus récent au plus ancien) et `compteurs`.

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceNotFoundError: Entreprise introuvable (404).
            APIClientError: Toute autre erreur API mappée (403 accès refusé,
                5xx serveur) ou API injoignable (APIUnavailableError).
        """
        return self.get(f"/administration/entreprises/{entreprise_id}")

    def update_entreprise(self, entreprise_id: int, payload: dict[str, Any]) -> Any:
        """Modifie l'identité légale d'une entreprise.

        Appelle PATCH /administration/entreprises/{entreprise_id} (schéma
        EntrepriseAdminUpdate : `nom_entreprise`, `siret`, `id_forme_juridique`,
        tous optionnels). La correction ne vaut que pour l'avenir : les factures
        déjà émises conservent l'instantané figé de leur émetteur.

        Args:
            entreprise_id (int): Identifiant de l'entreprise. Obligatoire.
            payload (dict[str, Any]): Champs partiels à modifier. Obligatoire.

        Returns:
            dict: L'entreprise mise à jour (schéma EntrepriseAdminRead, allégé :
            ni libellé de forme juridique, ni souscription).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceNotFoundError: Entreprise introuvable (404).
            ResourceConflictError: SIRET déjà rattaché à une autre entreprise (409).
            APIValidationError: SIRET invalide, ou forme juridique inconnue ou
                inactive (422).
            APIClientError: Toute autre erreur API mappée (403 accès refusé,
                5xx serveur) ou API injoignable (APIUnavailableError).
        """
        return self.patch(f"/administration/entreprises/{entreprise_id}", data=payload)

    def delete_entreprise(self, entreprise_id: int) -> Any:
        """Supprime une entreprise vierge de toute donnée.

        Appelle DELETE /administration/entreprises/{entreprise_id}. Réservé aux
        doublons, comptes de test et inscriptions abandonnées : une seule
        facture émise rend la suppression définitivement impossible (403), toute
        autre donnée la bloque en 409. Dans les deux cas, la suspension est la
        voie à suivre.

        Args:
            entreprise_id (int): Identifiant de l'entreprise. Obligatoire.

        Returns:
            bool: `True` en cas de succès (réponse 204 sans contenu).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceNotFoundError: Entreprise introuvable (404).
            ResourceConflictError: Entreprise contenant encore des données (409,
                message explicite conservé dans `detail`).
            APIClientError: Entreprise porteuse de factures émises (403, message
                explicite conservé dans `detail`), autre erreur mappée, ou API
                injoignable (APIUnavailableError).
        """
        return self.delete(f"/administration/entreprises/{entreprise_id}")

    def suspend_entreprise(self, entreprise_id: int, motif: str | None = None) -> Any:
        """Suspend une entreprise (mesure réversible et sans perte).

        Appelle POST /administration/entreprises/{entreprise_id}/suspendre
        (schéma SuspensionRequest). Les membres reçoivent alors un 403 sur
        toutes les routes tenant et la souscription courante passe en
        `SUSPENDU`. Le corps est requis par l'API : il est envoyé vide si aucun
        motif n'est fourni.

        Args:
            entreprise_id (int): Identifiant de l'entreprise. Obligatoire.
            motif (str | None): Raison de la suspension (255 caractères max),
                conservée pour le support. Optionnel.

        Returns:
            dict: L'entreprise suspendue (schéma EntrepriseAdminRead, allégé).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceNotFoundError: Entreprise introuvable (404).
            APIValidationError: Motif invalide (422).
            APIClientError: Toute autre erreur API mappée (403 accès refusé,
                5xx serveur) ou API injoignable (APIUnavailableError).
        """
        payload: dict[str, Any] = {}
        if motif:
            payload["motif"] = motif
        return self.post(
            f"/administration/entreprises/{entreprise_id}/suspendre", data=payload
        )

    def reactivate_entreprise(self, entreprise_id: int) -> Any:
        """Réactive une entreprise suspendue.

        Appelle POST /administration/entreprises/{entreprise_id}/reactiver :
        rétablit l'accès et restitue un abonnement actif (réactivé, ou rouvert
        sur le plan gratuit s'il avait été résilié).

        Args:
            entreprise_id (int): Identifiant de l'entreprise. Obligatoire.

        Returns:
            dict: L'entreprise réactivée (schéma EntrepriseAdminRead, allégé).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceNotFoundError: Entreprise introuvable (404).
            APIClientError: Toute autre erreur API mappée (403 accès refusé,
                5xx serveur) ou API injoignable (APIUnavailableError).
        """
        return self.post(f"/administration/entreprises/{entreprise_id}/reactiver")

    def change_plan(self, entreprise_id: int, id_abonnement: int) -> Any:
        """Change le plan d'abonnement d'une entreprise ciblée.

        Appelle POST /administration/entreprises/{entreprise_id}/abonnement/
        changer (schéma ChangementPlanAdminRequest). Même logique métier que la
        voie utilisateur `/abonnements/me/changer` : seule l'origine de
        l'entreprise diffère.

        Args:
            entreprise_id (int): Identifiant de l'entreprise. Obligatoire.
            id_abonnement (int): Identifiant du plan cible. Obligatoire.

        Returns:
            dict: La souscription résultante (schéma EntrepriseAbonnementRead).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceNotFoundError: Entreprise ou plan cible introuvable (404).
            ResourceConflictError: Déjà sur ce plan, ou trop d'utilisateurs
                actifs pour le plan cible (409, message conservé dans `detail`).
            APIValidationError: Corps invalide (422).
            APIClientError: Toute autre erreur API mappée (403 accès refusé,
                5xx serveur) ou API injoignable (APIUnavailableError).
        """
        return self.post(
            f"/administration/entreprises/{entreprise_id}/abonnement/changer",
            data={"id_abonnement": id_abonnement},
        )

    def extend_subscription(self, entreprise_id: int) -> Any:
        """Prolonge d'un mois l'abonnement payant d'une entreprise.

        Appelle POST /administration/entreprises/{entreprise_id}/abonnement/
        prolonger (sans corps).

        Args:
            entreprise_id (int): Identifiant de l'entreprise. Obligatoire.

        Returns:
            dict: La souscription prolongée (schéma EntrepriseAbonnementRead).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceNotFoundError: Entreprise introuvable, ou aucune
                souscription active à prolonger (404).
            ResourceConflictError: Le plan gratuit n'expire pas et ne peut pas
                être prolongé (409, message conservé dans `detail`).
            APIClientError: Toute autre erreur API mappée (403 accès refusé,
                5xx serveur) ou API injoignable (APIUnavailableError).
        """
        return self.post(
            f"/administration/entreprises/{entreprise_id}/abonnement/prolonger"
        )

    def cancel_subscription(self, entreprise_id: int, motif: str | None = None) -> Any:
        """Résilie l'abonnement d'une entreprise et coupe son accès.

        Appelle POST /administration/entreprises/{entreprise_id}/abonnement/
        resilier (schéma SuspensionRequest). À la différence de la suspension —
        mesure temporaire — la résiliation clôt la relation commerciale. Aucune
        donnée n'est touchée : `reactivate_entreprise` rouvre le service sur le
        plan gratuit. Le corps est requis par l'API : il est envoyé vide si
        aucun motif n'est fourni.

        Args:
            entreprise_id (int): Identifiant de l'entreprise. Obligatoire.
            motif (str | None): Raison de la résiliation (255 caractères max),
                conservée pour le support. Optionnel.

        Returns:
            dict: La souscription résiliée (schéma EntrepriseAbonnementRead).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceNotFoundError: Entreprise introuvable, ou aucune
                souscription à résilier (404).
            ResourceConflictError: Souscription déjà résiliée (409, message
                conservé dans `detail`).
            APIValidationError: Motif invalide (422).
            APIClientError: Toute autre erreur API mappée (403 accès refusé,
                5xx serveur) ou API injoignable (APIUnavailableError).
        """
        payload: dict[str, Any] = {}
        if motif:
            payload["motif"] = motif
        return self.post(
            f"/administration/entreprises/{entreprise_id}/abonnement/resilier",
            data=payload,
        )

    # --- Utilisateurs ----------------------------------------------------

    def list_utilisateurs(
        self,
        recherche: str | None = None,
        entreprise_id: int | None = None,
        est_actif: bool | None = None,
        admin_plateforme: bool | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> Any:
        """Liste les utilisateurs, toutes entreprises confondues (paginé).

        Appelle GET /administration/utilisateurs. Les filtres ne sont transmis
        que s'ils sont fournis.

        Args:
            recherche (str | None): Recherche sur l'email, le nom ou le prénom.
                Optionnel.
            entreprise_id (int | None): Restreint aux membres de cette
                entreprise. Optionnel.
            est_actif (bool | None): Filtre sur l'état d'activité du compte.
                `None` = tous. Optionnel.
            admin_plateforme (bool | None): Filtre sur le statut d'admin
                plateforme. `None` = tous. Optionnel.
            skip (int): Offset de pagination. Défaut 0.
            limit (int): Taille de page (max 100 côté API). Défaut 20.

        Returns:
            dict: Page paginée (schéma Page[UtilisateurAdminListItem]) avec
            `items`, `total`, `skip` et `limit`.

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIClientError: Toute autre erreur API mappée (403 accès refusé,
                422 validation, 5xx serveur) ou API injoignable
                (APIUnavailableError).
        """
        params: dict[str, Any] = {"skip": skip, "limit": limit}
        if recherche:
            params["recherche"] = recherche
        if entreprise_id is not None:
            params["entreprise_id"] = entreprise_id
        if est_actif is not None:
            params["est_actif"] = est_actif
        if admin_plateforme is not None:
            params["admin_plateforme"] = admin_plateforme
        return self.get("/administration/utilisateurs", params=params)

    def get_utilisateur(self, utilisateur_id: int) -> Any:
        """Récupère le détail complet d'un utilisateur.

        Appelle GET /administration/utilisateurs/{utilisateur_id}. La volumétrie
        des données créées conditionne la suppression du compte.

        Args:
            utilisateur_id (int): Identifiant de l'utilisateur. Obligatoire.

        Returns:
            dict: Détail (schéma UtilisateurAdminDetail) : identité,
            `entreprises` de rattachement et `compteurs`.

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceNotFoundError: Utilisateur introuvable (404).
            APIClientError: Toute autre erreur API mappée (403 accès refusé,
                5xx serveur) ou API injoignable (APIUnavailableError).
        """
        return self.get(f"/administration/utilisateurs/{utilisateur_id}")

    def delete_utilisateur(self, utilisateur_id: int) -> Any:
        """Supprime physiquement un compte utilisateur (dernier recours).

        Appelle DELETE /administration/utilisateurs/{utilisateur_id}. En
        pratique réservé aux comptes créés puis jamais utilisés : l'API refuse
        la suppression d'un compte protégé, du sien, du dernier administrateur
        de plateforme, du seul administrateur d'une entreprise peuplée, ou d'un
        auteur de données comptables. La désactivation est la voie recommandée.

        Args:
            utilisateur_id (int): Identifiant de l'utilisateur. Obligatoire.

        Returns:
            bool: `True` en cas de succès (réponse 204 sans contenu).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceNotFoundError: Utilisateur introuvable (404).
            ResourceConflictError: Dernier administrateur de plateforme, seul
                administrateur d'une entreprise peuplée, ou auteur de données
                comptables (409, message conservé dans `detail`).
            APIClientError: Compte protégé ou auto-suppression (403, message
                conservé dans `detail`), autre erreur mappée, ou API injoignable
                (APIUnavailableError).
        """
        return self.delete(f"/administration/utilisateurs/{utilisateur_id}")

    def deactivate_utilisateur(self, utilisateur_id: int) -> Any:
        """Désactive un compte utilisateur (voie recommandée, réversible).

        Appelle POST /administration/utilisateurs/{utilisateur_id}/desactiver.
        L'effet est immédiat : un compte inactif est refusé à l'authentification
        quel que soit le jeton présenté. Un administrateur ne peut pas se
        désactiver lui-même et le compte racine protégé reste intouchable.

        Args:
            utilisateur_id (int): Identifiant de l'utilisateur. Obligatoire.

        Returns:
            dict: L'utilisateur désactivé (schéma UtilisateurAdminDetail).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceNotFoundError: Utilisateur introuvable (404).
            APIClientError: Auto-désactivation ou compte protégé (403, message
                conservé dans `detail`), autre erreur mappée, ou API injoignable
                (APIUnavailableError).
        """
        return self.post(f"/administration/utilisateurs/{utilisateur_id}/desactiver")

    def reactivate_utilisateur(self, utilisateur_id: int) -> Any:
        """Réactive un compte utilisateur.

        Appelle POST /administration/utilisateurs/{utilisateur_id}/reactiver.
        N'est pas soumise à la limite d'utilisateurs du plan : l'administrateur
        de plateforme agit en support.

        Args:
            utilisateur_id (int): Identifiant de l'utilisateur. Obligatoire.

        Returns:
            dict: L'utilisateur réactivé (schéma UtilisateurAdminDetail).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceNotFoundError: Utilisateur introuvable (404).
            APIClientError: Toute autre erreur API mappée (403 accès refusé,
                5xx serveur) ou API injoignable (APIUnavailableError).
        """
        return self.post(f"/administration/utilisateurs/{utilisateur_id}/reactiver")
