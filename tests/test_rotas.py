"""Rotas gerais: saúde, CORS, persona, prazos, auditoria e modo token. Busca filtrada por ACL."""

import time

import pytest
from pydantic import ValidationError

from app.core import auth
from app.core.acl import ACESSO_ANONIMO, Acesso
from app.core.config import Settings, get_settings
from app.services.acervo import get_acervo
from app.services.agent.router import get_indice

P = {"ana": {"X-Persona-Id": "ana"}, "rafael": {"X-Persona-Id": "rafael"},
     "diretora": {"X-Persona-Id": "diretora_diraf"}, "curadora": {"X-Persona-Id": "curadora_ggc"}}
CTX = {"conversationId": "c1", "tema": "todos", "area": "", "perspective": "obligations",
       "from": "", "to": ""}


def test_swagger(client):
    assert client.get("/swagger").status_code == 200


def test_rotas_do_contrato_antigo_nao_existem(client):
    """O front atual (hacka-front, Homolog) não usa as rotas da branch lana."""
    for metodo, rota in (("post", "/chat"), ("get", "/docs"), ("get", "/radar"),
                         ("get", "/access"), ("get", "/ingest"), ("post", "/reports"),
                         ("get", "/reports/pptx"), ("get", "/grafo")):
        assert getattr(client, metodo)(rota, headers=P["ana"]).status_code in (404, 405), rota


def test_rotas_que_o_front_nao_chama_nao_existem(client):
    """O hacka-front (Homolog, src/services/http/client.ts) não chama estas rotas."""
    envio = "0" * 32
    for metodo, rota in (("get", "/health"), ("get", "/analyses/charts?panel=acervo"),
                         ("post", "/identity"), ("post", "/identity/sair"),
                         ("post", f"/document-jobs/{envio}/forget")):
        assert getattr(client, metodo)(rota, headers=P["ana"]).status_code in (404, 405), rota


def test_persona_por_query_tambem_vale(client):
    assert client.get("/documents?personaId=ana").json()
    assert client.get("/documents?persona=ana").json()


def test_prazos_respeitam_o_acesso(client):
    assert client.get("/deadlines?hoje=2026-11-12").json() == []
    ana = client.get("/deadlines?hoje=2026-11-12", headers=P["ana"]).json()
    assert ana and all(p["fact"]["citation"]["codigo"] != "CTR_2026-012" for p in ana)

    rafael = client.get("/deadlines?hoje=2026-11-12", headers=P["rafael"]).json()
    vistoria = next(p for p in rafael if "Vistoria" in p["title"])
    assert vistoria["date"] == "2026-11-25" and vistoria["priority"] == "Crítica"
    assert next(p for p in rafael if "prorrogação" in p["title"])["date"] == "2027-03-30"


def test_prazos_recusam_data_fora_da_faixa(client):
    assert client.get("/deadlines?hoje=2099-01-01", headers=P["ana"]).status_code == 422
    assert client.get("/deadlines?hoje=abc", headers=P["ana"]).status_code == 422


def test_auditoria_do_acervo_so_para_governanca(client):
    assert client.get("/audit/findings", headers=P["ana"]).json() == []
    achados = client.get("/audit/findings?hoje=2026-11-12", headers=P["curadora"]).json()
    assert {a["title"] for a in achados} == {"Inconsistência Temporal",
                                            "Documento Referenciado Ausente",
                                            "Conflito de Vigência"}
    ausentes = {a["documents"][0] for a in achados
                if a["title"] == "Documento Referenciado Ausente"}
    # A NG_010 só é citada pela NG_111 v2.0.0 (substituída), que fica fora desta auditoria.
    assert "NG_012" in ausentes
    assert any("NG_111 v2.0.0" in a["documents"][0] for a in achados
               if a["title"] == "Conflito de Vigência")
    # A NT_2026-021 é sigilosa da GEINOV, DIRTEC e DIRAF: a curadora da GEPEC não recebe achado
    # que cite título ou data dela. A diretora da DIRAF recebe.
    assert "NT_2026-021" not in str(achados)
    diretora = client.get("/audit/findings?hoje=2026-11-12", headers=P["diretora"]).json()
    assert any("NG_1130" in a["detail"] and "NT_2026-021" in a["detail"] for a in diretora
               if a["title"] == "Inconsistência Temporal")


def test_versao_substituida_segue_a_propria_classificacao(client):
    ana = {d["id"] for d in client.get("/documents", headers=P["ana"]).json()}
    assert "NG_111@2.0.0" not in ana  # Sigilosa da GEPEC, mesmo com a v3.0.0 visível
    assert "RG_1100@1.0.0" in ana  # sem arquivo próprio: segue a versão vigente
    curadora = {d["id"] for d in client.get("/documents", headers=P["curadora"]).json()}
    assert "NG_111@2.0.0" in curadora


def test_cors_so_origem_permitida(client):
    pre = {"Access-Control-Request-Method": "POST",
           "Access-Control-Request-Headers": "content-type,x-persona-id"}
    rota = "/conversations/messages"
    ok = client.options(rota, headers={"Origin": "http://localhost:3000", **pre})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    ruim = client.options(rota, headers={"Origin": "http://malicioso.example", **pre})
    assert "access-control-allow-origin" not in ruim.headers


def test_auth_mode_desconhecido_derruba_o_startup():
    """GRAFO-20: erro de digitação não pode cair num modo permissivo."""
    with pytest.raises(ValidationError):
        Settings(auth_mode="tokn")


# ---------- busca: filtro antes do ranking ----------
def test_indice_nao_devolve_trecho_sigiloso_fora_do_setor():
    indice = get_indice()
    for perfil in (ACESSO_ANONIMO, Acesso("GOP"), Acesso("GOC"), Acesso("GEPEC", True)):
        achados = indice.buscar("aluguel mensal coworking contrato locação", perfil, k=20)
        assert all(t.chunk.nivel != "Sigilosa" for t in achados)
    assert indice.buscar("aluguel mensal coworking", Acesso("GOC", True), k=5)
    assert indice.buscar("férias antecedência solicitação", ACESSO_ANONIMO, k=5) == []


def test_versao_substituida_fora_da_busca_comum():
    indice = get_indice()
    gepec = Acesso("GEPEC", True)
    comum = indice.buscar("solicitação antecedência mínima dias férias", gepec, k=30)
    assert all(t.chunk.vigente for t in comum)
    historico = indice.buscar("solicitação antecedência mínima 30 dias", gepec, k=30,
                              incluir_substituidos=True)
    assert any(t.chunk.versao == "2.0.0" and t.chunk.codigo == "NG_111" for t in historico)
    # Fora da GEPEC, a versão substituída não aparece nem pedindo o histórico.
    ana = indice.buscar("solicitação antecedência mínima 30 dias", Acesso("GOP"), k=30,
                        incluir_substituidos=True)
    assert all(t.chunk.vigente for t in ana)


def test_bloqueio_nao_confirma_valor_sigiloso():
    indice = get_indice()
    gop = Acesso("GOP")
    base = indice.dominio_bloqueado("aluguel mensal coworking", gop, 0.0)
    for valor in ("3.650", "3.650,00", "9.999", "20%", "12/2027"):
        assert indice.dominio_bloqueado(f"aluguel mensal coworking {valor}", gop, 0.0) == base
    assert indice.dominio_bloqueado("3.650", gop, 0.0) is None  # só o número: nada


def test_bloqueio_revela_so_o_setor_e_nunca_para_anonimo():
    indice = get_indice()
    pergunta = "aluguel mensal coworking multa rescisão"
    assert indice.dominio_bloqueado(pergunta, ACESSO_ANONIMO, 0.0) is None
    assert indice.dominio_bloqueado(pergunta, Acesso("GOP"), 0.0) == "GESUC"
    assert indice.dominio_bloqueado(pergunta, Acesso("GOC", True), 0.0) is None


def test_acervo_integro():
    acervo = get_acervo()
    assert acervo.quarentena == []
    assert acervo.vigente("NG_111").versao == "3.0.0"
    contrato = acervo.vigente("CTR_2026-012")
    assert contrato.nivel == "Sigilosa"  # classificação BBTS > "#interna" impresso no PDF
    assert contrato.setores == ("GESUC", "GOC", "GFI")
    assert not acervo.autorizado(["NG_111", "CTR_2026-012"], Acesso("GOP"))
    assert acervo.autorizado(["NG_111", "CTR_2026-012"], Acesso("GFI", True))
    assert not acervo.autorizado(["NAO_EXISTE"], Acesso("GESUC", True))


# ---------- modo token ----------
@pytest.fixture
def modo_token(monkeypatch):
    cfg = get_settings()
    monkeypatch.setattr(cfg, "auth_mode", "token")
    monkeypatch.setattr(cfg, "auth_token_secret", "s" * 40)
    return cfg


def test_modo_token_exige_bearer_valido(client, modo_token):
    assert client.get("/documents").status_code == 401
    assert client.get("/documents", headers=P["diretora"]).status_code == 401  # demo ignorado
    assert client.get("/documents", headers={"Authorization": "Bearer ana.9999999999.abc"}
                      ).status_code == 401

    token = auth.emitir_token("ana")
    h = {"Authorization": f"Bearer {token}"}
    assert "NG_111@3.0.0" in {d["id"] for d in client.get("/documents", headers=h).json()}
    # Token de Ana não vira outra persona pelo corpo.
    r = client.post("/conversations/messages", headers=h,
                    json={"query": "oi", "context": {**CTX, "persona": "curadora_ggc"}})
    assert r.status_code == 403

    vencido = f"ana.{int(time.time()) - 10}.{auth._assinar('ana', int(time.time()) - 10, 's' * 40)}"
    assert client.get("/documents", headers={"Authorization": f"Bearer {vencido}"}
                      ).status_code == 401
