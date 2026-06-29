from .base_client import BaseAPIClient


class UtilisateursClient(BaseAPIClient):
    def get_equipe(self):
        """Récupère la liste des utilisateurs de l'équipe."""
        return self.get("/utilisateurs/")

    def inviter_utilisateur(self, user_data):
        """Envoie les données complètes pour créer l'utilisateur."""
        payload = {
            "nom": user_data.get("nom", ""),
            "prenom": user_data.get("prenom", ""),
            "adresse": "",
            "adresse_complement": "",
            "code_postal": "",
            "ville": "",
            "email": user_data.get("email"),
            "telephone": "",
            "est_actif": True,
            "password": user_data.get("password"),
        }
        return self.post("/utilisateurs/", data=payload)
