"""Tests du dépôt et de la liste des documents.

L'upload est le seul endroit où le BFF valide lui-même des données (type et
taille du fichier, seule validation faisant autorité côté client) : un
fichier refusé ne doit JAMAIS partir vers l'API. Le succès suit le flux
asynchrone du contrat : 202 avec `id_document` → écran d'attente. La liste
vérifie la dégradation propre et la suppression son PRG (retour à la liste
dans le même état).
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from clients.documents_client import DocumentsClient
from clients.exceptions import APIUnavailableError, ResourceNotFoundError
from core.tests.conftest import ApiMocker, messages_of
from core.views.auth import _MSG_INDISPONIBLE

_UPLOAD_URL = reverse("upload_document")


def _pdf(name: str = "facture.pdf", content: bytes = b"%PDF-1.4") -> SimpleUploadedFile:
    """Fichier PDF factice accepté par la validation serveur."""
    return SimpleUploadedFile(name, content, content_type="application/pdf")


class TestUploadValidationServeur:
    def test_sans_fichier_refuse_sans_appel_api(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        calls = api_mock(DocumentsClient, "upload_document", returns={})

        response = client_connecte.post(_UPLOAD_URL, {})

        assert response.status_code == 200
        assert "Veuillez sélectionner un fichier." in messages_of(response)
        assert calls == []

    def test_format_non_supporte_refuse_sans_appel_api(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        calls = api_mock(DocumentsClient, "upload_document", returns={})
        fichier = SimpleUploadedFile(
            "script.exe", b"MZ", content_type="application/octet-stream"
        )

        response = client_connecte.post(_UPLOAD_URL, {"file": fichier})

        assert response.status_code == 200
        assert "Format non supporté (PDF, PNG ou JPEG attendu)." in messages_of(
            response
        )
        assert calls == []

    def test_succes_202_redirige_vers_l_ecran_d_attente(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(DocumentsClient, "upload_document", returns={"id_document": 12})

        response = client_connecte.post(_UPLOAD_URL, {"file": _pdf()})

        assert response.status_code == 302
        assert response["Location"] == reverse(
            "document_attente", kwargs={"document_id": 12}
        )

    def test_reponse_sans_id_retombe_sur_le_message_generique(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(DocumentsClient, "upload_document", returns={})

        response = client_connecte.post(_UPLOAD_URL, {"file": _pdf()})

        assert response.status_code == 302
        assert response["Location"] == _UPLOAD_URL
        assert "Document reçu, traitement en cours." in messages_of(response)

    def test_api_indisponible_conserve_la_page(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(DocumentsClient, "upload_document", raises=APIUnavailableError())

        response = client_connecte.post(_UPLOAD_URL, {"file": _pdf()})

        assert response.status_code == 200
        assert _MSG_INDISPONIBLE in messages_of(response)


class TestDocumentsListe:
    def test_liste_affichee(self, client_connecte: Client, api_mock: ApiMocker) -> None:
        api_mock(DocumentsClient, "list_documents", returns={"items": [], "total": 0})
        response = client_connecte.get(reverse("documents"))
        assert response.status_code == 200

    def test_api_indisponible_rend_la_page_vide_avec_message(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(DocumentsClient, "list_documents", raises=APIUnavailableError())

        response = client_connecte.get(reverse("documents"))

        assert response.status_code == 200
        assert response.context["items"] == []
        assert _MSG_INDISPONIBLE in messages_of(response)


class TestDocumentSuppression:
    def test_succes_revient_a_la_liste_dans_le_meme_etat(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        calls = api_mock(DocumentsClient, "delete_document", returns=True)

        response = client_connecte.post(
            reverse("document_delete", kwargs={"document_id": 12}),
            {"retour": "statut=traites&page=2"},
        )

        assert response.status_code == 302
        assert response["Location"].startswith(reverse("documents"))
        assert "statut=traites" in response["Location"]
        assert calls[0][0] == (12,)

    def test_document_deja_supprime_message_clair(
        self, client_connecte: Client, api_mock: ApiMocker
    ) -> None:
        api_mock(DocumentsClient, "delete_document", raises=ResourceNotFoundError())

        response = client_connecte.post(
            reverse("document_delete", kwargs={"document_id": 12}), {"retour": ""}
        )

        assert response.status_code == 302
        assert any("Document introuvable" in msg for msg in messages_of(response))
