"""Client HTTP pour la gestion des membres d'équipe et des rôles.

Couvre le domaine `utilisateurs` de l'API ainsi que la liste des rôles :

- GET /utilisateurs/ : liste des membres de l'entreprise active.
- POST /utilisateurs/ : création d'un membre (schéma UtilisateurCreate).
- PATCH /utilisateurs/{user_id} : mise à jour partielle (UtilisateurTeamUpdate).
- DELETE /utilisateurs/{user_id} : suppression d'un membre.
- GET /auth/roles : liste des rôles disponibles (n'exige pas le tenant).
"""

from .base_client import BaseAPIClient


class UtilisateursClient(BaseAPIClient):
    """Client HTTP pour l'équipe (membres) et les rôles.

    Hérite de `BaseAPIClient` et réutilise ses méthodes HTTP ; le JWT et le
    header `x-entreprise-id` sont injectés automatiquement depuis la session.
    La route `/auth/roles` n'exige pas le tenant, mais le header reste transmis
    s'il est présent en session, sans effet.
    """

    def get_equipe(self):
        """Liste les membres de l'équipe de l'entreprise active.

        Appelle GET /utilisateurs/.

        Returns:
            list: Liste des membres (dictionnaires) renvoyée par l'API.

        Raises:
            TokenExpiredError: En cas de réponse 401.
            httpx.HTTPStatusError: Pour toute autre erreur HTTP.
        """
        return self.get("/utilisateurs/")

    def get_roles(self):
        """Liste les rôles attribuables aux membres.

        Appelle GET /auth/roles (ne nécessite pas le header `x-entreprise-id`).

        Returns:
            list: Liste des rôles (dictionnaires) renvoyée par l'API.

        Raises:
            TokenExpiredError: En cas de réponse 401.
            httpx.HTTPStatusError: Pour toute autre erreur HTTP.
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
            httpx.HTTPStatusError: Pour toute autre erreur HTTP (ex. 422
                validation).
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
            httpx.HTTPStatusError: Pour toute autre erreur HTTP (ex. 422
                validation).
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
            httpx.HTTPStatusError: Pour toute autre erreur HTTP.
        """
        return self.delete(f"/utilisateurs/{user_id}")
