"""Identidade do front (GET /identity): o mesmo sujeito das outras rotas, sem tela de login."""

import pytest

from app.core import auth
from app.core.config import get_settings
from app.services import envios

SEGREDO = "s" * 40


@pytest.fixture(autouse=True)
def _limpo():
    yield
    envios.esperar()


def test_sem_identificacao_e_visitante(client):
    r = client.get("/identity")
    assert r.status_code == 200 and r.headers["cache-control"] == "private, no-store"
    corpo = r.json()
    assert corpo["id"] == "anonimo" and corpo["capabilities"] == []
    assert corpo["habilitacao"] == "Pública"


def test_persona_do_demo_e_capacidades(client):
    eu = client.get("/identity", headers={"X-Persona-Id": "helena"}).json()
    assert eu["id"] == "helena" and eu["setor"] == "GEINOV"
    assert {"upload", "curate", "sigiloso"} <= set(eu["capabilities"])
    assert "approve" not in eu["capabilities"]  # sem rota de decisão, ninguém aprova pela API
    junior = client.get("/identity", headers={"X-Persona-Id": "bruno"}).json()
    assert junior["capabilities"] == ["upload"]


def test_persona_padrao_identifica_o_front_sem_cabecalho(client, monkeypatch):
    """O front não manda persona no GET /identity nem no envio: vale DEMO_DEFAULT_PERSONA."""
    monkeypatch.setattr(get_settings(), "demo_default_persona", "bruno")
    assert client.get("/identity").json()["id"] == "bruno"
    r = client.post("/document-jobs", files=[("files", ("guia.md", b"Guia interno. " * 10))])
    assert r.status_code == 200 and r.json()[0]["status"] == "processing"


def test_persona_desconhecida_e_visitante(client):
    assert client.get("/identity", headers={"X-Persona-Id": "root"}).json()["id"] == "anonimo"


def test_cookie_nao_identifica(client):
    client.cookies.set("raiz_persona", "helena")
    try:
        assert client.get("/identity").json()["id"] == "anonimo"
    finally:
        client.cookies.clear()


def test_modo_token_so_pelo_cabecalho(client, monkeypatch):
    cfg = get_settings()
    monkeypatch.setattr(cfg, "auth_mode", "token")
    monkeypatch.setattr(cfg, "auth_token_secret", SEGREDO)
    token = auth.emitir_token("rafael")
    eu = client.get("/identity", headers={"Authorization": f"Bearer {token}"})
    assert eu.json()["id"] == "rafael"
    adulterado = token[:-1] + ("0" if token[-1] != "0" else "1")
    r = client.get("/identity", headers={"Authorization": f"Bearer {adulterado}"})
    assert r.status_code == 401
    assert client.get("/identity", headers={"X-Persona-Id": "helena"}).status_code == 401
    client.cookies.set("raiz_sessao", token)
    try:
        assert client.get("/identity").status_code == 401  # token no cookie não vale
    finally:
        client.cookies.clear()
