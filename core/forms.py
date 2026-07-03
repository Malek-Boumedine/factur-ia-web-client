import re

from django import forms

from core.constants import TYPES_PRODUIT


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


class EntrepriseForm(forms.Form):
    """Validation serveur de la création d'entreprise (POST /entreprises/).

    Écran d'onboarding : `nom_entreprise` est requis, `siret` est optionnel
    (validé à 14 chiffres exactement s'il est renseigné). `id_forme_juridique`
    est volontairement omis (aucun endpoint de référence pour lister les valeurs).
    """

    nom_entreprise = forms.CharField(max_length=255)
    siret = forms.CharField(max_length=14, required=False)

    def clean_siret(self):
        value = (self.cleaned_data.get("siret") or "").strip()
        if value and not re.fullmatch(r"\d{14}", value):
            raise forms.ValidationError(
                "Le SIRET doit comporter exactement 14 chiffres."
            )
        return value

    def to_api_payload(self):
        """Construit le corps `EntrepriseCreate` à partir des données validées.

        Le SIRET vide n'est pas envoyé (l'API applique ses propres défauts).
        """
        cd = self.cleaned_data
        payload = {"nom_entreprise": cd["nom_entreprise"]}
        siret = (cd.get("siret") or "").strip()
        if siret:
            payload["siret"] = siret
        return payload


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


class ClientForm(forms.Form):
    """Validation serveur de la création/édition d'un client (tiers facturé).

    Champs et contraintes alignés sur les schémas ClientCreate/ClientUpdate du
    contrat OpenAPI (mêmes noms, mêmes longueurs). Requis : `raison_sociale`,
    `code_postal`, `ville`. Le SIRET, optionnel, doit compter exactement
    14 chiffres s'il est renseigné. `est_actif` n'est proposé qu'en édition
    (défaut `true` côté API à la création) et couvre la réactivation.
    """

    raison_sociale = forms.CharField(max_length=255)
    siret = forms.CharField(max_length=14, required=False)
    numero_tva = forms.CharField(max_length=20, required=False)
    adresse = forms.CharField(max_length=255, required=False)
    adresse_complement = forms.CharField(max_length=255, required=False)
    code_postal = forms.CharField(max_length=10)
    ville = forms.CharField(max_length=150)
    email = forms.EmailField(max_length=255, required=False)
    telephone = forms.CharField(max_length=20, required=False)
    est_actif = forms.BooleanField(required=False)

    _OPTIONAL_FIELDS = (
        "siret",
        "numero_tva",
        "adresse",
        "adresse_complement",
        "email",
        "telephone",
    )

    def __init__(self, *args, is_edit=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_edit = is_edit
        if not is_edit:
            del self.fields["est_actif"]

    def clean_siret(self):
        value = (self.cleaned_data.get("siret") or "").strip()
        if value and not re.fullmatch(r"\d{14}", value):
            raise forms.ValidationError(
                "Le SIRET doit comporter exactement 14 chiffres."
            )
        return value

    def to_api_payload(self):
        """Construit le corps ClientCreate/ClientUpdate depuis les données validées.

        En création, les optionnels vides sont omis (l'API applique ses
        défauts). En édition, tous les champs sont envoyés — `None` pour un
        optionnel vidé, afin de pouvoir effacer une valeur (schéma nullable).
        """
        cd = self.cleaned_data
        payload = {
            "raison_sociale": cd["raison_sociale"],
            "code_postal": cd["code_postal"],
            "ville": cd["ville"],
        }
        for field in self._OPTIONAL_FIELDS:
            value = (cd.get(field) or "").strip()
            if value:
                payload[field] = value
            elif self.is_edit:
                payload[field] = None
        if self.is_edit:
            payload["est_actif"] = cd["est_actif"]
        return payload


class AbonnementForm(forms.Form):
    """Validation serveur de la création/édition d'un plan d'abonnement.

    Champs et contraintes alignés sur AbonnementCreate/AbonnementUpdate du
    contrat OpenAPI. Seul `libelle` est requis ; les autres champs portent les
    défauts du schéma (tarif 0, 1 utilisateur, 10 factures/mois). Le tarif est
    envoyé en chaîne (le schéma l'accepte) pour éviter les arrondis flottants ;
    le contrat le borne à 8 chiffres entiers et 2 décimales.
    """

    libelle = forms.CharField(max_length=100)
    description = forms.CharField(required=False)
    tarif = forms.DecimalField(min_value=0, max_digits=10, decimal_places=2, initial=0)
    nombre_max_utilisateurs = forms.IntegerField(min_value=1, initial=1)
    nombre_max_factures_mois = forms.IntegerField(min_value=1, initial=10)

    def __init__(self, *args, is_edit=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_edit = is_edit

    def to_api_payload(self):
        """Construit le corps AbonnementCreate/AbonnementUpdate depuis les données.

        En création, la description vide est omise (l'API applique ses
        défauts) ; en édition, elle est envoyée à `None` pour permettre
        l'effacement (schéma nullable).
        """
        cd = self.cleaned_data
        payload = {
            "libelle": cd["libelle"],
            "tarif": str(cd["tarif"]),
            "nombre_max_utilisateurs": cd["nombre_max_utilisateurs"],
            "nombre_max_factures_mois": cd["nombre_max_factures_mois"],
        }
        description = (cd.get("description") or "").strip()
        if description:
            payload["description"] = description
        elif self.is_edit:
            payload["description"] = None
        return payload


class CatalogueForm(forms.Form):
    """Validation serveur de la création/édition d'un produit du catalogue.

    Champs et contraintes alignés sur CatalogueCreate/CatalogueUpdate du
    contrat OpenAPI. Requis : `designation`, `prix_unitaire_ht` (≥ 0),
    `id_taux_tva`. Les taux de TVA sont injectés par la vue (choices depuis
    GET /taux-tva/?est_actif=true) : id en valeur, libellé affiché. Le prix est
    envoyé en chaîne (le schéma l'accepte) pour éviter les arrondis flottants.
    `est_actif` n'est proposé qu'en édition (défaut `true` à la création).
    """

    type_produit = forms.ChoiceField(choices=(), initial="produit")
    reference = forms.CharField(max_length=100, required=False)
    designation = forms.CharField(max_length=255)
    prix_unitaire_ht = forms.DecimalField(min_value=0, max_digits=12, decimal_places=2)
    unite = forms.CharField(max_length=50, required=False)
    id_taux_tva = forms.TypedChoiceField(choices=(), coerce=int)
    est_actif = forms.BooleanField(required=False)

    def __init__(self, *args, taux_choices=(), is_edit=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_edit = is_edit
        self.fields["type_produit"].choices = TYPES_PRODUIT
        self.fields["id_taux_tva"].choices = list(taux_choices)
        if not is_edit:
            del self.fields["est_actif"]

    def to_api_payload(self):
        """Construit le corps CatalogueCreate/CatalogueUpdate depuis les données.

        En création, les optionnels vides sont omis ; en édition, ils sont
        envoyés à `None` pour permettre l'effacement (schéma nullable).
        """
        cd = self.cleaned_data
        payload = {
            "type_produit": cd["type_produit"],
            "designation": cd["designation"],
            "prix_unitaire_ht": str(cd["prix_unitaire_ht"]),
            "id_taux_tva": cd["id_taux_tva"],
        }
        for field in ("reference", "unite"):
            value = (cd.get(field) or "").strip()
            if value:
                payload[field] = value
            elif self.is_edit:
                payload[field] = None
        if self.is_edit:
            payload["est_actif"] = cd["est_actif"]
        return payload
