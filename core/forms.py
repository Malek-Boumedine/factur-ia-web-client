import re

from django import forms


class SignUpForm(forms.Form):
    """Validation serveur de l'inscription publique (POST /utilisateurs/inscription).

    L'API exige `nom`, `prenom`, `email`, `password` (min 8) et `id_role`. Le
    formulaire public ne propose pas de sélecteur de rôle (`/auth/roles` exige
    une authentification) : le rôle est injecté par la vue depuis les settings.
    Un champ de confirmation garantit la ressaisie correcte du mot de passe.
    """

    nom = forms.CharField(max_length=150)
    prenom = forms.CharField(max_length=150)
    email = forms.EmailField()
    password = forms.CharField(min_length=8)
    confirm_password = forms.CharField()

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password")
        confirm = cleaned.get("confirm_password")
        if password and confirm and password != confirm:
            self.add_error(
                "confirm_password", "Les deux mots de passe ne correspondent pas."
            )
        return cleaned

    def to_api_payload(self, id_role, est_admin=True):
        """Construit le corps `UtilisateurCreate` envoyé à l'API.

        Args:
            id_role (int): Rôle attribué au compte créé (injecté par la vue
                depuis `settings.SIGNUP_DEFAULT_ROLE_ID`).
            est_admin (bool): Marque le compte comme administrateur de son
                espace (propriétaire à l'inscription). Vrai par défaut.

        Returns:
            dict: Données conformes au schéma `UtilisateurCreate`.
        """
        cd = self.cleaned_data
        return {
            "nom": cd["nom"],
            "prenom": cd["prenom"],
            "email": cd["email"],
            "password": cd["password"],
            "id_role": id_role,
            "est_admin": est_admin,
            "est_actif": True,
        }


class ForgotPasswordForm(forms.Form):
    """Validation de la demande de réinitialisation (POST /auth/mot-de-passe-oublie).

    Un seul champ email. Le comportement de la vue reste neutre (ne révèle pas
    l'existence du compte), conformément à l'API.
    """

    email = forms.EmailField()


class ResetPasswordForm(forms.Form):
    """Validation du nouveau mot de passe (POST /auth/reinitialiser-mot-de-passe).

    Le token provient de l'URL (lien email), pas du formulaire. On applique la
    même règle de robustesse que l'API (min 8 caractères) et une confirmation.
    """

    nouveau_mot_de_passe = forms.CharField(min_length=8)
    confirm_password = forms.CharField()

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("nouveau_mot_de_passe")
        confirm = cleaned.get("confirm_password")
        if password and confirm and password != confirm:
            self.add_error(
                "confirm_password", "Les deux mots de passe ne correspondent pas."
            )
        return cleaned


class CollaborateurForm(forms.Form):
    """Validation serveur de l'ajout / modification d'un collaborateur.

    Relaie ensuite vers l'API (POST /utilisateurs/ ou PATCH /utilisateurs/{id}).
    Les champs adresse sont optionnels (l'admin ne les connaît pas toujours à
    l'invitation) ; le format est validé uniquement s'ils sont renseignés.
    """

    nom = forms.CharField(max_length=150)
    prenom = forms.CharField(max_length=150)
    email = forms.EmailField()
    # Requis à la création, optionnel à l'édition (cf. __init__ / clean).
    password = forms.CharField(min_length=8, required=False)
    id_role = forms.IntegerField()
    est_admin = forms.BooleanField(required=False)

    # Champs optionnels
    adresse = forms.CharField(max_length=255, required=False)
    adresse_complement = forms.CharField(max_length=255, required=False)
    code_postal = forms.CharField(max_length=10, required=False)
    ville = forms.CharField(max_length=150, required=False)
    telephone = forms.CharField(max_length=20, required=False)

    def __init__(self, *args, is_create=True, role_ids=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_create = is_create
        # Liste blanche des rôles autorisés (récupérés de l'API).
        self.role_ids = {int(r) for r in (role_ids or [])}

    def clean_id_role(self):
        value = self.cleaned_data["id_role"]
        if self.role_ids and value not in self.role_ids:
            raise forms.ValidationError("Rôle invalide.")
        return value

    def clean_code_postal(self):
        value = (self.cleaned_data.get("code_postal") or "").strip()
        if value and not re.fullmatch(r"\d{4,10}", value):
            raise forms.ValidationError("Code postal invalide (chiffres uniquement).")
        return value

    def clean_password(self):
        value = self.cleaned_data.get("password") or ""
        if self.is_create and not value:
            raise forms.ValidationError(
                "Un mot de passe temporaire est requis à la création."
            )
        return value

    def to_api_payload(self):
        """Construit le dict envoyé à l'API à partir des données validées.

        Les champs adresse vides ne sont pas inventés : on n'envoie que ce qui
        est réellement saisi (le backend applique ses propres règles/défauts).
        """
        cd = self.cleaned_data
        payload = {
            "nom": cd["nom"],
            "prenom": cd["prenom"],
            "email": cd["email"],
            "id_role": cd["id_role"],
            "est_admin": cd["est_admin"],
        }
        if cd.get("password"):
            payload["password"] = cd["password"]

        for field in (
            "adresse",
            "adresse_complement",
            "code_postal",
            "ville",
            "telephone",
        ):
            value = (cd.get(field) or "").strip()
            if value:
                payload[field] = value

        return payload
