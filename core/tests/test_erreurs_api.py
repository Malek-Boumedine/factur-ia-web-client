"""Tests du report des erreurs API dans les formulaires Django.

Deux helpers partagés par toutes les vues à formulaire :

- `_appliquer_erreurs_api` : reporte le `detail` d'un 422 FastAPI (liste
  d'objets `{loc, msg}`) dans les champs correspondants du formulaire, avec
  repli en erreur globale pour un champ inconnu ou un détail non structuré ;
- `_appliquer_erreur_conflit` : rattache le message libre d'un 409 au champ
  concerné par recherche de mot-clé, sinon en erreur globale.

Les formulaires utilisés sont liés et validés avant l'application des
erreurs, comme dans les vues (le helper intervient après un `is_valid()`).
"""

from typing import Any

from core.forms import ClientForm
from core.views.auth import _appliquer_erreur_conflit, _appliquer_erreurs_api

# Même mapping mot-clé -> champ que la vue clients (`_CONFLICT_FIELD_KEYWORDS`).
_KEYWORDS = {"siret": "siret", "tva": "numero_tva"}


def _form_valide() -> ClientForm:
    """Formulaire client lié et validé, prêt à recevoir des erreurs API."""
    form = ClientForm(
        {"raison_sociale": "ACME SAS", "code_postal": "75001", "ville": "Paris"}
    )
    assert form.is_valid()
    return form


def _erreur_422(champ: str, msg: str) -> dict[str, Any]:
    """Construit une entrée `detail` au format HTTPValidationError de FastAPI."""
    return {"loc": ["body", champ], "msg": msg, "type": "value_error"}


class TestAppliquerErreursApi:
    def test_erreur_rattachee_au_champ_du_formulaire(self) -> None:
        form = _form_valide()
        _appliquer_erreurs_api(form, [_erreur_422("ville", "Ville inconnue.")])
        assert form.errors["ville"] == ["Ville inconnue."]

    def test_plusieurs_erreurs_reparties_sur_leurs_champs(self) -> None:
        form = _form_valide()
        _appliquer_erreurs_api(
            form,
            [
                _erreur_422("ville", "Ville inconnue."),
                _erreur_422("code_postal", "Code postal invalide."),
            ],
        )
        assert form.errors["ville"] == ["Ville inconnue."]
        assert form.errors["code_postal"] == ["Code postal invalide."]

    def test_champ_inconnu_retombe_en_erreur_globale(self) -> None:
        form = _form_valide()
        _appliquer_erreurs_api(
            form, [_erreur_422("champ_api_inconnu", "Valeur rejetée.")]
        )
        assert form.non_field_errors() == ["Valeur rejetée."]
        assert "champ_api_inconnu" not in form.errors

    def test_entree_sans_loc_retombe_en_erreur_globale(self) -> None:
        form = _form_valide()
        _appliquer_erreurs_api(form, [{"msg": "Erreur sans localisation."}])
        assert form.non_field_errors() == ["Erreur sans localisation."]

    def test_entree_sans_msg_recoit_un_libelle_par_defaut(self) -> None:
        form = _form_valide()
        _appliquer_erreurs_api(form, [{"loc": ["body", "ville"]}])
        assert form.errors["ville"] == ["Valeur invalide."]

    def test_detail_chaine_en_erreur_globale(self) -> None:
        form = _form_valide()
        _appliquer_erreurs_api(form, "Données rejetées par l'API.")
        assert form.non_field_errors() == ["Données rejetées par l'API."]

    def test_detail_absent_en_erreur_globale_generique(self) -> None:
        form = _form_valide()
        _appliquer_erreurs_api(form, None)
        assert form.non_field_errors() == ["Données invalides."]


class TestAppliquerErreurConflit:
    def test_conflit_rattache_au_champ_par_mot_cle(self) -> None:
        form = _form_valide()
        _appliquer_erreur_conflit(
            form, "Un client avec ce SIRET existe déjà.", _KEYWORDS
        )
        assert form.errors["siret"] == ["Un client avec ce SIRET existe déjà."]

    def test_second_mot_cle_rattache_a_son_champ(self) -> None:
        form = _form_valide()
        _appliquer_erreur_conflit(form, "Ce numéro de TVA est déjà utilisé.", _KEYWORDS)
        assert form.errors["numero_tva"] == ["Ce numéro de TVA est déjà utilisé."]

    def test_sans_mot_cle_reconnu_en_erreur_globale(self) -> None:
        form = _form_valide()
        _appliquer_erreur_conflit(form, "Conflit sur une autre donnée.", _KEYWORDS)
        assert form.non_field_errors() == ["Conflit sur une autre donnée."]

    def test_mot_cle_vers_champ_absent_du_formulaire_en_globale(self) -> None:
        """Le mot-clé ne suffit pas : le champ doit exister dans CE formulaire."""
        form = _form_valide()
        _appliquer_erreur_conflit(
            form, "Un client avec ce SIRET existe déjà.", {"siret": "champ_absent"}
        )
        assert form.non_field_errors() == ["Un client avec ce SIRET existe déjà."]

    def test_detail_absent_en_message_par_defaut(self) -> None:
        form = _form_valide()
        _appliquer_erreur_conflit(form, None, _KEYWORDS)
        assert form.non_field_errors() == ["Cette valeur est déjà utilisée."]
