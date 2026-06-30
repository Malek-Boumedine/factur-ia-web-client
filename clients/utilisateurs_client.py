from .base_client import BaseAPIClient


class UtilisateursClient(BaseAPIClient):
    def get_equipe(self):
        return self.get("/utilisateurs/")

    def get_roles(self):
        return self.get("/auth/roles")

    def inviter_utilisateur(self, payload):
        """Crée un membre d'équipe. `payload` est déjà validé/normalisé
        par CollaborateurForm.to_api_payload()."""
        data = {"est_actif": True, **payload}
        return self.post("/utilisateurs/", data=data)

    def update_utilisateur(self, user_id, payload):
        """Met à jour un membre via PATCH (champs partiels)."""
        return self.patch(f"/utilisateurs/{user_id}", data=payload)

    def delete_utilisateur(self, user_id):
        return self.delete(f"/utilisateurs/{user_id}")
