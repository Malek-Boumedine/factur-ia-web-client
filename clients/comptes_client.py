"""Client HTTP pour les parcours de compte publics (non authentifiés).

Couvre les routes accessibles sans JWT, utilisées par les pages d'auth avant
connexion :

- POST /utilisateurs/inscription : inscription publique (schéma UtilisateurCreate).
- POST /auth/mot-de-passe-oublie : demande de réinitialisation (réponse neutre).
- POST /auth/reinitialiser-mot-de-passe : application du nouveau mot de passe
  à partir d'un token reçu par email.

Hérite de `BaseAPIClient` : bien qu'aucun JWT ne soit présent en session pour
ces parcours (`auth_headers` n'ajoute alors pas d'en-tête `Authorization`), on
bénéficie de la résilience réseau et surtout du mapping `422 -> APIValidationError`,
utilisé par les vues pour reporter les erreurs de l'API dans les champs.
"""

from typing import Any

from .base_client import BaseAPIClient


class ComptesClient(BaseAPIClient):
    """Client des parcours de compte publics (inscription, mot de passe oublié/réinit)."""

    def register(self, payload: dict[str, Any]) -> Any:
        """Inscrit un nouvel utilisateur.

        Appelle POST /utilisateurs/inscription (schéma UtilisateurCreate). La
        réponse ne contient pas de token : l'utilisateur devra se connecter.

        Args:
            payload (dict): Données conformes à UtilisateurCreate, produites par
                `SignUpForm.to_api_payload()`. Obligatoire.

        Returns:
            dict: L'utilisateur créé (UtilisateurRead), tel que renvoyé par
            l'API (201).

        Raises:
            APIValidationError: En cas de réponse 422 (email déjà utilisé,
                données invalides) ; `detail` porte le message de l'API.
            APIClientError: Toute autre erreur API mappée, ou API injoignable
                (APIUnavailableError).
        """
        return self.post("/utilisateurs/inscription", data=payload)

    def forgot_password(self, email: str) -> Any:
        """Demande l'envoi d'un email de réinitialisation.

        Appelle POST /auth/mot-de-passe-oublie. L'API répond de manière neutre
        (ne révèle pas si le compte existe) ; la vue conserve ce comportement.

        Args:
            email (str): Adresse email saisie. Obligatoire.

        Returns:
            dict: Message neutre (MessageResponse) renvoyé par l'API (200).

        Raises:
            APIValidationError: En cas de réponse 422 (email mal formé).
            APIClientError: Toute autre erreur API mappée, ou API injoignable
                (APIUnavailableError).
        """
        return self.post("/auth/mot-de-passe-oublie", data={"email": email})

    def reset_password(self, token: str, nouveau_mot_de_passe: str) -> Any:
        """Applique un nouveau mot de passe à partir d'un token de reset.

        Appelle POST /auth/reinitialiser-mot-de-passe (schéma
        ReinitialisationRequest). Le token provient du lien reçu par email.

        Args:
            token (str): Token de réinitialisation issu de l'URL. Obligatoire.
            nouveau_mot_de_passe (str): Nouveau mot de passe (min 8). Obligatoire.

        Returns:
            dict: Message de confirmation (MessageResponse) renvoyé par l'API (200).

        Raises:
            APIValidationError: En cas de réponse 422 (token invalide/expiré,
                mot de passe trop faible) ; `detail` porte le message de l'API.
            APIClientError: Toute autre erreur API mappée, ou API injoignable
                (APIUnavailableError).
        """
        return self.post(
            "/auth/reinitialiser-mot-de-passe",
            data={"token": token, "nouveau_mot_de_passe": nouveau_mot_de_passe},
        )
