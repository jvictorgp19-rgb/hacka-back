"""Identidade do front (GET/POST /identity): cookie HttpOnly no lugar de tela de login."""

import pytest

from app.core import auth
from app.core.config import get_settings
from app.services import envios

SEGREDO = "s" * 40


@pytest.fixture(autouse=True)
def _sem_cookie(client):
    client.cookies.clear()
    yield
    client.cookies.clear()
    envios.esperar()


def test_sem_identificacao_e_visitante(client):
    r = client.get("/identity")
    assert r.status_code == 200 and r.headers["cache-control"] == "private, no-store"
    corpo = r.json()
    assert corpo["id"] == "anonimo" and corpo["capabilities"] == []
    assert corpo["habilitacao"] == "Pública"


def test_entrar_grava_cookie_httponly_e_identifica_as_proximas_chamadas(client):
    r = client.post("/identity", json={"persona": "helena"})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert "raiz_persona=helena" in cookie and "HttpOnly" in cookie
    assert "samesite=lax" in cookie.lower()
    eu = client.get("/identity").json()
    assert eu["id"] == "helena" and eu["setor"] == "GEINOV"
    assert {"upload", "approve", "curate", "sigiloso"} <= set(eu["capabilities"])


def test_capacidades_do_junior(client):
    client.post("/identity", json={"persona": "bruno"})
    assert client.get("/identity").json()["capabilities"] == ["upload"]


def test_upload_do_front_usa_so_o_cookie(client):
    client.post("/identity", json={"persona": "bruno"})
    r = client.post("/document-jobs", files=[("files", ("guia.md", b"Guia interno. " * 10))])
    assert r.status_code == 200 and r.json()[0]["status"] == "processing"


def test_persona_desconhecida_e_422(client):
    assert client.post("/identity", json={"persona": "root"}).status_code == 422
    client.cookies.set("raiz_persona", "root")
    assert client.get("/identity").json()["id"] == "anonimo"


def test_sair_apaga_o_cookie(client):
    client.post("/identity", json={"persona": "helena"})
    r = client.post("/identity/sair")
    assert r.json()["id"] == "anonimo" and 'raiz_persona=""' in r.headers["set-cookie"]


def test_entrar_de_outro_site_e_recusado(client):
    r = client.post("/identity", json={"persona": "helena"},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    mesma = client.post("/identity", json={"persona": "helena"},
                        headers={"Origin": "http://testserver"})  # Swagger da própria API
    assert mesma.status_code == 200


def test_modo_token_aceita_token_no_cookie(client, monkeypatch):
    cfg = get_settings()
    monkeypatch.setattr(cfg, "auth_mode", "token")
    monkeypatch.setattr(cfg, "auth_token_secret", SEGREDO)
    assert client.post("/identity", json={"persona": "helena"}).status_code == 422
    token = auth.emitir_token("rafael")
    r = client.post("/identity", json={"token": token})
    assert r.status_code == 200 and "raiz_sessao=" in r.headers["set-cookie"]
    assert client.get("/identity").json()["id"] == "rafael"

    client.cookies.clear()
    client.cookies.set("raiz_sessao", token[:-1] + ("0" if token[-1] != "0" else "1"))
    assert client.get("/identity").status_code == 401  # assinatura adulterada
    client.cookies.clear()
    assert client.get("/identity", headers={"X-Persona-Id": "helena"}).status_code == 401


def test_samesite_none_forca_secure(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "cookie_samesite", "none")
    cookie = client.post("/identity", json={"persona": "ana"}).headers["set-cookie"]
    assert "Secure" in cookie and "samesite=none" in cookie.lower()
