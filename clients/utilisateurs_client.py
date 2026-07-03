"""Client HTTP pour la gestion des membres d'équipe et des rôles.

Couvre le domaine `utilisateurs` de l'API ainsi que la liste des rôles :

- GET /utilisateurs/me : profil de l'utilisateur connecté (n'exige pas le tenant).
- PATCH /utilisateurs/me : mise à jour de son propre profil (ProfilUpdate).
- POST /utilisateurs/me/changer-email : changement de son propre email
  (renvoie un nouveau token, l'email étant le sujet du JWT).
- POST /utilisateurs/me/changer-mot-de-passe : changement de son propre
  mot de passe.
- GET /utilisateurs/ : liste des membres de l'entreprise active.
- POST /utilisateurs/ : création d'un membre (schéma UtilisateurCreate).
- PATCH /utilisateurs/{user_id} : mise à jour partielle (UtilisateurTeamUpdate).
- DELETE /utilisateurs/{user_id} : suppression d'un membre.
- GET /auth/roles : liste des rôles disponibles (n'exige pas le tenant).

Les routes « soi-même » (/utilisateurs/me...) n'exigent pas le header tenant.
"""

from .base_client import BaseAPIClient


class UtilisateursClient(BaseAPIClient):
    """Client HTTP pour l'équipe (membres) et les rôles.

    Hérite de `BaseAPIClient` et réutilise ses méthodes HTTP ; le JWT et le
    header `x-entreprise-id` sont injectés automatiquement depuis la session.
    La route `/auth/roles` n'exige pas le tenant, mais le header reste transmis
    s'il est présent en session, sans effet.
    """

    def get_my_profile(self):
        """Récupère le profil de l'utilisateur connecté.

        Appelle GET /utilisateurs/me. Route « soi-même » : elle ne dépend pas du
        header `x-entreprise-id`. Le schéma `UtilisateurRead` renvoyé porte
        notamment le champ global `admin_plateforme`.

        Returns:
            dict: Le profil de l'utilisateur connecté, tel que renvoyé par l'API.

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIClientError: Toute autre erreur API mappée (404 introuvable,
                422 validation, 5xx serveur) ou API injoignable
                (APIUnavailableError).
        """
        return self.get("/utilisateurs/me")

    def update_my_profile(self, payload):
        """Met à jour les informations personnelles de l'utilisateur connecté.

        Appelle PATCH /utilisateurs/me (schéma ProfilUpdate : nom, prénom et
        coordonnées uniquement — l'email et le mot de passe passent par leurs
        routes dédiées). Route « soi-même », sans header tenant requis.

        Args:
            payload (dict): Champs du profil à mettre à jour, conformes au
                schéma ProfilUpdate. Obligatoire.

        Returns:
            dict: Le profil mis à jour, tel que renvoyé par l'API (200).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIClientError: Toute autre erreur API mappée (422 validation,
                5xx serveur) ou API injoignable (APIUnavailableError).
        """
        return self.patch("/utilisateurs/me", data=payload)

    def change_my_email(self, current_password, new_email):
        """Change l'email de connexion de l'utilisateur connecté.

        Appelle POST /utilisateurs/me/changer-email (schéma
        ChangementEmailRequest). L'email étant le sujet (`sub`) du JWT, la
        réponse contient un nouvel `access_token` : l'appelant DOIT remplacer
        le token en session par celui-ci, l'ancien devenant caduc.

        Args:
            current_password (str): Mot de passe actuel (vérifié par l'API).
                Obligatoire.
            new_email (str): Nouvel email de connexion. Obligatoire.

        Returns:
            dict: Réponse ChangementEmailResponse (`message`, `access_token`,
            `token_type`).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceConflictError: Email déjà utilisé par un autre compte
                (409, message dans `detail`).
            APIClientError: Toute autre erreur API mappée (400 mot de passe
                actuel incorrect ou email identique, 422 validation, 5xx
                serveur) ou API injoignable (APIUnavailableError).
        """
        return self.post(
            "/utilisateurs/me/changer-email",
            data={
                "mot_de_passe_actuel": current_password,
                "nouvel_email": new_email,
            },
        )

    def change_my_password(self, current_password, new_password):
        """Change le mot de passe de l'utilisateur connecté.

        Appelle POST /utilisateurs/me/changer-mot-de-passe (schéma
        ChangementMotDePasseRequest). Distinct du flux « mot de passe
        oublié » : ici l'utilisateur est authentifié et son mot de passe
        actuel est exigé. Le token en session reste valide (le sujet du JWT
        ne change pas).

        Args:
            current_password (str): Mot de passe actuel (vérifié par l'API).
                Obligatoire.
            new_password (str): Nouveau mot de passe (min 8 caractères).
                Obligatoire.

        Returns:
            dict: Réponse MessageResponse de l'API (200).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIClientError: Toute autre erreur API mappée (400 mot de passe
                actuel incorrect ou nouveau identique, 422 validation, 5xx
                serveur) ou API injoignable (APIUnavailableError).
        """
        return self.post(
            "/utilisateurs/me/changer-mot-de-passe",
            data={
                "mot_de_passe_actuel": current_password,
                "nouveau_mot_de_passe": new_password,
            },
        )

    def get_equipe(self):
        """Liste les membres de l'équipe de l'entreprise active.

        Appelle GET /utilisateurs/.

        Returns:
            list: Liste des membres (dictionnaires) renvoyée par l'API.

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIClientError: Toute autre erreur API mappée (404 introuvable,
                422 validation, 5xx serveur) ou API injoignable
                (APIUnavailableError).
        """
        return self.get("/utilisateurs/")

    def get_roles(self):
        """Liste les rôles attribuables aux membres.

        Appelle GET /auth/roles (ne nécessite pas le header `x-entreprise-id`).

        Returns:
            list: Liste des rôles (dictionnaires) renvoyée par l'API.

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIClientError: Toute autre erreur API mappée (404 introuvable,
                422 validation, 5xx serveur) ou API injoignable
                (APIUnavailableError).
        """
        return self.get("/auth/roles")

    def inviter_utilisateur(self, payload):
        """Crée un membre d'équipe. `payload` est déjà validé/normalisé
        par CollaborateurForm.to_api_payload().

        Appelle POST /utilisateurs/ (schéma UtilisateurCreate). La clé
        `est_actif` est ajoutée par défaut à `True`, mais reste écrasée par une
        valeur explicite présente dans `payload`.

        Args:
            payload (dict): Données du membre à créer, conformes au schéma
                UtilisateurCreate. Obligatoire.

        Returns:
            dict: Le membre créé, tel que renvoyé par l'API (201).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceConflictError: Limite d'utilisateurs du plan actif
                atteinte (409, message actionnable dans `detail`).
            APIClientError: Toute autre erreur API mappée (404 introuvable,
                422 validation, 5xx serveur) ou API injoignable
                (APIUnavailableError).
        """
        data = {"est_actif": True, **payload}
        return self.post("/utilisateurs/", data=data)

    def update_utilisateur(self, user_id, payload):
        """Met à jour un membre via PATCH (champs partiels).

        Appelle PATCH /utilisateurs/{user_id} (schéma UtilisateurTeamUpdate).

        Args:
            user_id (int): Identifiant du membre à modifier. Obligatoire.
            payload (dict): Champs partiels à mettre à jour, conformes au schéma
                UtilisateurTeamUpdate. Obligatoire.

        Returns:
            dict: Le membre mis à jour, tel que renvoyé par l'API (200).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            ResourceConflictError: Réactivation refusée, limite d'utilisateurs
                du plan actif atteinte (409, message actionnable dans
                `detail`).
            APIClientError: Toute autre erreur API mappée (404 introuvable,
                422 validation, 5xx serveur) ou API injoignable
                (APIUnavailableError).
        """
        return self.patch(f"/utilisateurs/{user_id}", data=payload)

    def delete_utilisateur(self, user_id):
        """Supprime un membre d'équipe.

        Appelle DELETE /utilisateurs/{user_id}.

        Args:
            user_id (int): Identifiant du membre à supprimer. Obligatoire.

        Returns:
            bool: `True` en cas de succès (réponse 204 sans contenu).

        Raises:
            TokenExpiredError: En cas de réponse 401.
            APIClientError: Toute autre erreur API mappée (404 introuvable,
                422 validation, 5xx serveur) ou API injoignable
                (APIUnavailableError).
        """
        return self.delete(f"/utilisateurs/{user_id}")
