"""Tests des formulaires : validation, normalisation SIRET, payloads API.

Trois axes, alignés sur le rôle réel des formulaires du BFF :

- la normalisation du SIRET (`normalize_siret` et les `clean_siret`) : blancs
  Unicode, points et tirets retirés avant tout contrôle de format ;
- les règles de validation propres au client (confirmation de mot de passe,
  mot de passe requis à la création seulement, liste blanche des rôles) ;
- `to_api_payload` : la traduction exacte vers le contrat OpenAPI — optionnels
  omis à la création mais envoyés à `None` en édition (effacement possible),
  montants convertis en chaîne (pas d'arrondi flottant).

La validation métier profonde (unicité, cohérence) appartient à l'API et
n'est pas testée ici.
"""

from typing import Any

import pytest

from core.forms import (
    AbonnementForm,
    CatalogueForm,
    ChangementMotDePasseForm,
    ClientForm,
    CollaborateurForm,
    EntrepriseAdminForm,
    EntrepriseForm,
    ProfilForm,
    ResetPasswordForm,
    SignUpForm,
    TauxTvaForm,
)
from core.normalization import normalize_siret


class TestNormalizeSiret:
    """Nettoyage des identifiants SIREN/SIRET recopiés avec séparateurs."""

    @pytest.mark.parametrize(
        ("brut", "attendu"),
        [
            ("123 456 789 00012", "12345678900012"),
            ("123.456.789.00012", "12345678900012"),
            ("123-456-789-00012", "12345678900012"),
            # Blancs Unicode d'un copier-coller de PDF/Kbis : insécable
            # (U+00A0), fine insécable (U+202F), fine (U+2009), tabulation.
            ("123 456 789 000\t12", "12345678900012"),
            ("12345678900012", "12345678900012"),
            ("", ""),
            (None, ""),
        ],
        ids=[
            "espaces",
            "points",
            "tirets",
            "blancs-unicode",
            "deja-propre",
            "vide",
            "absent",
        ],
    )
    def test_retire_les_separateurs(self, brut: Any, attendu: str) -> None:
        assert normalize_siret(brut) == attendu


def _donnees_inscription(**surcharge: Any) -> dict[str, Any]:
    """Données valides d'inscription, surchargées champ par champ."""
    donnees: dict[str, Any] = {
        "nom": "Durand",
        "prenom": "Alice",
        "email": "alice@exemple.fr",
        "password": "motdepasse",  # pragma: allowlist secret
        "confirm_password": "motdepasse",  # pragma: allowlist secret
    }
    donnees.update(surcharge)
    return donnees


class TestSignUpForm:
    def test_payload_conforme_au_schema_utilisateur(self) -> None:
        form = SignUpForm(_donnees_inscription())
        assert form.is_valid()
        assert form.to_api_payload(id_role=3) == {
            "nom": "Durand",
            "prenom": "Alice",
            "email": "alice@exemple.fr",
            "password": "motdepasse",  # pragma: allowlist secret
            "id_role": 3,
            "est_admin": True,
            "est_actif": True,
        }

    def test_mots_de_passe_differents_refuses(self) -> None:
        form = SignUpForm(_donnees_inscription(confirm_password="autrechose"))
        assert not form.is_valid()
        assert "confirm_password" in form.errors

    def test_mot_de_passe_trop_court_refuse(self) -> None:
        form = SignUpForm(
            _donnees_inscription(
                password="court",  # pragma: allowlist secret
                confirm_password="court",  # pragma: allowlist secret
            )
        )
        assert not form.is_valid()
        assert "password" in form.errors


class TestEntrepriseForm:
    def test_siret_normalise_avant_validation(self) -> None:
        form = EntrepriseForm({"nom_entreprise": "ACME", "siret": "123 456 789 00012"})
        assert form.is_valid()
        assert form.to_api_payload() == {
            "nom_entreprise": "ACME",
            "siret": "12345678900012",
        }

    @pytest.mark.parametrize(
        "siret",
        [
            "1234567890001",  # pragma: allowlist secret
            "123456789000123",  # pragma: allowlist secret
            "12345678900A12",  # pragma: allowlist secret
        ],
    )
    def test_siret_hors_format_refuse(self, siret: str) -> None:
        form = EntrepriseForm({"nom_entreprise": "ACME", "siret": siret})
        assert not form.is_valid()
        assert "siret" in form.errors

    def test_siret_vide_omis_du_payload(self) -> None:
        form = EntrepriseForm({"nom_entreprise": "ACME", "siret": ""})
        assert form.is_valid()
        assert form.to_api_payload() == {"nom_entreprise": "ACME"}


class TestResetPasswordForm:
    def test_confirmation_differente_refusee(self) -> None:
        form = ResetPasswordForm(
            {
                "nouveau_mot_de_passe": "motdepasse",  # pragma: allowlist secret
                "confirm_password": "autre",  # pragma: allowlist secret
            }
        )
        assert not form.is_valid()
        assert "confirm_password" in form.errors


class TestChangementMotDePasseForm:
    def test_confirmation_differente_refusee(self) -> None:
        form = ChangementMotDePasseForm(
            {
                "mot_de_passe_actuel": "ancien",  # pragma: allowlist secret
                "nouveau_mot_de_passe": "motdepasse",  # pragma: allowlist secret
                "confirm_password": "autre",  # pragma: allowlist secret
            }
        )
        assert not form.is_valid()
        assert "confirm_password" in form.errors


def _donnees_collaborateur(**surcharge: Any) -> dict[str, Any]:
    """Données valides d'un collaborateur, surchargées champ par champ."""
    donnees: dict[str, Any] = {
        "nom": "Martin",
        "prenom": "Paul",
        "email": "paul@exemple.fr",
        "password": "temporaire1",  # pragma: allowlist secret
        "id_role": "2",
    }
    donnees.update(surcharge)
    return donnees


class TestCollaborateurForm:
    def test_mot_de_passe_requis_a_la_creation(self) -> None:
        form = CollaborateurForm(_donnees_collaborateur(password=""), is_create=True)
        assert not form.is_valid()
        assert "password" in form.errors

    def test_mot_de_passe_optionnel_en_edition(self) -> None:
        form = CollaborateurForm(_donnees_collaborateur(password=""), is_create=False)
        assert form.is_valid()
        assert "password" not in form.to_api_payload()

    def test_role_hors_liste_blanche_refuse(self) -> None:
        form = CollaborateurForm(_donnees_collaborateur(id_role="99"), role_ids=[1, 2])
        assert not form.is_valid()
        assert "id_role" in form.errors

    def test_role_de_la_liste_blanche_accepte(self) -> None:
        form = CollaborateurForm(_donnees_collaborateur(id_role="2"), role_ids=[1, 2])
        assert form.is_valid()

    def test_sans_liste_blanche_tout_role_accepte(self) -> None:
        """Rôles indisponibles (API en échec) : la validation reste possible."""
        form = CollaborateurForm(_donnees_collaborateur(id_role="99"), role_ids=None)
        assert form.is_valid()

    def test_code_postal_non_numerique_refuse(self) -> None:
        form = CollaborateurForm(_donnees_collaborateur(code_postal="75A01"))
        assert not form.is_valid()
        assert "code_postal" in form.errors

    def test_payload_omet_les_champs_adresse_vides(self) -> None:
        form = CollaborateurForm(_donnees_collaborateur(ville="Paris"))
        assert form.is_valid()
        payload = form.to_api_payload()
        assert payload["ville"] == "Paris"
        assert payload["est_admin"] is False
        for champ in ("adresse", "adresse_complement", "code_postal", "telephone"):
            assert champ not in payload


class TestProfilForm:
    def test_optionnels_vides_envoyes_a_none(self) -> None:
        """Le schéma est nullable : vider un champ doit effacer la valeur."""
        form = ProfilForm({"nom": "Durand", "prenom": "Alice", "ville": "  "})
        assert form.is_valid()
        payload = form.to_api_payload()
        assert payload["nom"] == "Durand"
        for champ in (
            "adresse",
            "adresse_complement",
            "code_postal",
            "ville",
            "telephone",
        ):
            assert payload[champ] is None

    def test_optionnels_renseignes_transmis(self) -> None:
        form = ProfilForm(
            {
                "nom": "Durand",
                "prenom": "Alice",
                "ville": "Paris",
                "code_postal": "75001",
            }
        )
        assert form.is_valid()
        payload = form.to_api_payload()
        assert payload["ville"] == "Paris"
        assert payload["code_postal"] == "75001"


def _donnees_client(**surcharge: Any) -> dict[str, Any]:
    """Données valides d'un client facturé, surchargées champ par champ."""
    donnees: dict[str, Any] = {
        "raison_sociale": "ACME SAS",
        "code_postal": "75001",
        "ville": "Paris",
    }
    donnees.update(surcharge)
    return donnees


class TestClientForm:
    def test_creation_sans_champ_est_actif(self) -> None:
        """`est_actif` n'existe qu'en édition (défaut appliqué par l'API)."""
        form = ClientForm(_donnees_client())
        assert "est_actif" not in form.fields
        assert "est_actif" in ClientForm(_donnees_client(), is_edit=True).fields

    def test_siret_normalise_puis_valide(self) -> None:
        form = ClientForm(_donnees_client(siret="123.456.789-00012"))
        assert form.is_valid()
        assert form.to_api_payload()["siret"] == "12345678900012"

    def test_siret_hors_format_refuse(self) -> None:
        form = ClientForm(_donnees_client(siret="123"))
        assert not form.is_valid()
        assert "siret" in form.errors

    def test_payload_creation_omet_les_optionnels_vides(self) -> None:
        form = ClientForm(_donnees_client())
        assert form.is_valid()
        assert form.to_api_payload() == {
            "raison_sociale": "ACME SAS",
            "code_postal": "75001",
            "ville": "Paris",
        }

    def test_payload_edition_efface_les_optionnels_vides(self) -> None:
        form = ClientForm(_donnees_client(email="acme@exemple.fr"), is_edit=True)
        assert form.is_valid()
        payload = form.to_api_payload()
        assert payload["email"] == "acme@exemple.fr"
        assert payload["est_actif"] is False
        for champ in (
            "siret",
            "numero_tva",
            "adresse",
            "adresse_complement",
            "telephone",
        ):
            assert payload[champ] is None


class TestAbonnementForm:
    def test_payload_creation_tarif_en_chaine(self) -> None:
        """Le tarif part en chaîne décimale : pas d'arrondi flottant."""
        form = AbonnementForm(
            {
                "libelle": "Pro",
                "tarif": "29.90",
                "nombre_max_utilisateurs": "5",
                "nombre_max_factures_mois": "100",
            }
        )
        assert form.is_valid()
        assert form.to_api_payload() == {
            "libelle": "Pro",
            "tarif": "29.90",
            "nombre_max_utilisateurs": 5,
            "nombre_max_factures_mois": 100,
        }

    def test_payload_edition_efface_la_description_vide(self) -> None:
        form = AbonnementForm(
            {
                "libelle": "Pro",
                "tarif": "0",
                "nombre_max_utilisateurs": "1",
                "nombre_max_factures_mois": "10",
            },
            is_edit=True,
        )
        assert form.is_valid()
        assert form.to_api_payload()["description"] is None

    def test_tarif_negatif_refuse(self) -> None:
        form = AbonnementForm(
            {
                "libelle": "Pro",
                "tarif": "-1",
                "nombre_max_utilisateurs": "1",
                "nombre_max_factures_mois": "10",
            }
        )
        assert not form.is_valid()
        assert "tarif" in form.errors


class TestTauxTvaForm:
    def test_payload_creation_taux_en_chaine(self) -> None:
        form = TauxTvaForm({"taux": "20.00", "libelle": "Taux normal"})
        assert form.is_valid()
        assert form.to_api_payload() == {"taux": "20.00", "libelle": "Taux normal"}

    def test_payload_edition_efface_le_code_comptable_vide(self) -> None:
        form = TauxTvaForm({"taux": "20", "libelle": "Taux normal"}, is_edit=True)
        assert form.is_valid()
        assert form.to_api_payload()["code_comptable"] is None

    def test_taux_superieur_a_cent_refuse(self) -> None:
        form = TauxTvaForm({"taux": "101", "libelle": "Invalide"})
        assert not form.is_valid()
        assert "taux" in form.errors


_FORMES_JURIDIQUES = [(1, "SAS"), (2, "SARL")]


class TestEntrepriseAdminForm:
    def test_forme_juridique_choisie_coercee_en_entier(self) -> None:
        form = EntrepriseAdminForm(
            {"nom_entreprise": "ACME", "id_forme_juridique": "2"},
            forme_juridique_choices=_FORMES_JURIDIQUES,
        )
        assert form.is_valid()
        assert form.to_api_payload()["id_forme_juridique"] == 2

    def test_champs_vides_envoyes_a_none(self) -> None:
        """SIRET et forme juridique vidés : `None` efface la donnée (nullable)."""
        form = EntrepriseAdminForm(
            {"nom_entreprise": "ACME", "siret": "", "id_forme_juridique": ""},
            forme_juridique_choices=_FORMES_JURIDIQUES,
        )
        assert form.is_valid()
        assert form.to_api_payload() == {
            "nom_entreprise": "ACME",
            "siret": None,
            "id_forme_juridique": None,
        }

    def test_siret_normalise_puis_valide(self) -> None:
        form = EntrepriseAdminForm(
            {"nom_entreprise": "ACME", "siret": "123 456 789 00012"},
            forme_juridique_choices=_FORMES_JURIDIQUES,
        )
        assert form.is_valid()
        assert form.to_api_payload()["siret"] == "12345678900012"

    def test_siret_hors_format_refuse(self) -> None:
        form = EntrepriseAdminForm(
            {"nom_entreprise": "ACME", "siret": "123"},
            forme_juridique_choices=_FORMES_JURIDIQUES,
        )
        assert not form.is_valid()
        assert "siret" in form.errors


_TAUX_CHOICES = [(1, "20 %"), (2, "10 %")]


def _donnees_catalogue(**surcharge: Any) -> dict[str, Any]:
    """Données valides d'un produit du catalogue, surchargées champ par champ."""
    donnees: dict[str, Any] = {
        "type_produit": "prestation",
        "designation": "Audit annuel",
        "prix_unitaire_ht": "1500.00",
        "id_taux_tva": "1",
    }
    donnees.update(surcharge)
    return donnees


class TestCatalogueForm:
    def test_creation_sans_champ_est_actif(self) -> None:
        form = CatalogueForm(_donnees_catalogue(), taux_choices=_TAUX_CHOICES)
        assert "est_actif" not in form.fields

    def test_payload_creation_prix_en_chaine_et_optionnels_omis(self) -> None:
        form = CatalogueForm(_donnees_catalogue(), taux_choices=_TAUX_CHOICES)
        assert form.is_valid()
        assert form.to_api_payload() == {
            "type_produit": "prestation",
            "designation": "Audit annuel",
            "prix_unitaire_ht": "1500.00",
            "id_taux_tva": 1,
        }

    def test_payload_edition_efface_les_optionnels_vides(self) -> None:
        form = CatalogueForm(
            _donnees_catalogue(), taux_choices=_TAUX_CHOICES, is_edit=True
        )
        assert form.is_valid()
        payload = form.to_api_payload()
        assert payload["reference"] is None
        assert payload["unite"] is None
        assert payload["est_actif"] is False

    def test_taux_hors_liste_refuse(self) -> None:
        form = CatalogueForm(
            _donnees_catalogue(id_taux_tva="99"), taux_choices=_TAUX_CHOICES
        )
        assert not form.is_valid()
        assert "id_taux_tva" in form.errors

    def test_type_produit_hors_enum_refuse(self) -> None:
        form = CatalogueForm(
            _donnees_catalogue(type_produit="licence"), taux_choices=_TAUX_CHOICES
        )
        assert not form.is_valid()
        assert "type_produit" in form.errors
