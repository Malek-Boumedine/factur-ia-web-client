from .base_client import BaseAPIClient


class UtilisateursClient(BaseAPIClient):
    def get_equipe(self):
        return self.get("/utilisateurs/")

    def get_roles(self):
        return self.get("/auth/roles")

    def inviter_utilisateur(self, user_data):
        payload = {
            "nom": user_data.get("nom", ""),
            "prenom": user_data.get("prenom", ""),
            "adresse": user_data.get("adresse", ""),
            "adresse_complement": user_data.get("adresse_complement", ""),
            "code_postal": user_data.get("code_postal", ""),
            "ville": user_data.get("ville", ""),
            "email": user_data.get("email"),
            "telephone": user_data.get("telephone", ""),
            "est_actif": user_data.get("est_actif", True),
            "password": user_data.get("password"),
            "id_role": int(user_data.get("id_role")),
            "est_admin": user_data.get("est_admin", False),
        }
        return self.post("/utilisateurs/", data=payload)

    def update_utilisateur(self, user_id, user_data):
        payload = {
            "nom": user_data.get("nom"),
            "prenom": user_data.get("prenom"),
            "adresse": user_data.get("adresse", ""),
            "adresse_complement": user_data.get("adresse_complement", ""),
            "code_postal": user_data.get("code_postal", ""),
            "ville": user_data.get("ville", ""),
            "email": user_data.get("email"),
            "telephone": user_data.get("telephone", ""),
            "est_actif": user_data.get("est_actif", True),
            "password": user_data.get("password"),
            "id_role": int(user_data.get("id_role")),
            "est_admin": user_data.get("est_admin", False),
        }
        return self.patch(f"/utilisateurs/{user_id}", data=payload)

    def delete_utilisateur(self, user_id):
        return self.delete(f"/utilisateurs/{user_id}")
