"""Rotas de catálogo, radar, pedidos de acesso, relatórios e auditoria: contrato + ACL."""

import time
from io import BytesIO

import pytest
from pptx import Presentation

from app.core import auth
from app.core.acl import ACESSO_ANONIMO, Acesso
from app.core.config import get_settings
from app.services.acervo import get_acervo
from app.services.agent.router import get_indice

P = {"ana": {"X-Persona-Id": "ana"}, "rafael": {"X-Persona-Id": "rafael"},
     "diretora": {"X-Persona-Id": "diretora_diraf"}, "curadora": {"X-Persona-Id": "curadora_ggc"},
     "carlos": {"X-Persona-Id": "carlos"}}


def test_health_e_swagger(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/swagger").status_code == 200


def test_docs_filtra_por_nivel(client):
    anon = client.get("/docs").json()
    assert anon["vigentes"] == [] and anon["substituidos"] == [] and anon["taxonomia"] == {}

    ana = client.get("/docs", headers=P["ana"]).json()
    codigos = {d["codigo"] for d in ana["vigentes"]}
    assert "NG_111" in codigos and "CTR_2026-012" not in codigos
    assert ana["temaFiltro"] == "todos"

    rafael = client.get("/docs?tema=locacao", headers=P["rafael"]).json()
    assert {d["codigo"] for d in rafael["vigentes"]} == {"CTR_2026-012", "NT_2026-018"}
    assert client.get("/docs?tema=locacao", headers=P["ana"]).json()["vigentes"] == []


def test_docs_recusa_tema_invalido(client):
    assert client.get("/docs?tema=../../etc", headers=P["ana"]).status_code == 422


def test_persona_por_query_tambem_vale(client):
    assert client.get("/docs?personaId=ana").json()["vigentes"]


def test_radar_respeita_nivel_e_calcula_criticidade(client):
    assert client.get("/radar?hoje=2026-11-12").json() == []
    ana = client.get("/radar?hoje=2026-11-12", headers=P["ana"]).json()
    assert ana and all("CTR_2026" not in e["documento"] for e in ana)

    rafael = client.get("/radar?hoje=2026-11-12", headers=P["rafael"]).json()
    vistoria = next(e for e in rafael if "Vistoria" in e["titulo"])
    assert vistoria["dataLimite"] == "25/11/2026" and vistoria["criticidade"] == "Crítica"
    prorrogacao = next(e for e in rafael if "prorrogação" in e["titulo"])
    assert prorrogacao["dataLimite"] == "30/03/2027"
    assert set(vistoria) == {"id", "dataLimite", "titulo", "documento", "responsavel",
                             "criticidade", "detalhe"}


def test_radar_recusa_data_fora_da_faixa(client):
    assert client.get("/radar?hoje=2099-01-01", headers=P["ana"]).status_code == 422
    assert client.get("/radar?hoje=abc", headers=P["ana"]).status_code == 422


def test_pedidos_de_acesso_so_para_solicitante_e_curadora(client):
    assert client.get("/access").json() == []
    assert client.get("/access", headers=P["carlos"]).json() == []
    assert client.get("/access", headers=P["rafael"]).json() == []
    assert client.get("/access", headers=P["diretora"]).json() == []
    assert client.get("/access", headers=P["ana"]).json()[0]["id"] == "REQ-2026-089"
    assert client.get("/access", headers=P["curadora"]).json()[0]["status"] == "Pendente"


def test_auditoria_do_acervo_so_para_governanca(client):
    assert client.get("/ingest", headers=P["ana"]).json() == []
    achados = client.get("/ingest?hoje=2026-11-12", headers=P["curadora"]).json()
    severidades = {a["severidade"] for a in achados}
    assert severidades == {"Inconsistência Temporal", "Documento Referenciado Ausente",
                           "Conflito de Vigência"}
    ausentes = {a["documentosEnvolvidos"][0] for a in achados
                if a["severidade"] == "Documento Referenciado Ausente"}
    # A NG_010 só é citada pela NG_111 v2.0.0 (substituída), que fica fora desta auditoria.
    assert "NG_012" in ausentes
    temporais = [a["descricao"] for a in achados if a["severidade"] == "Inconsistência Temporal"]
    assert any("NG_1130" in t and "NT_2026-021" in t for t in temporais)
    assert any("NG_111 v2.0.0" in a["documentosEnvolvidos"][0] for a in achados
               if a["severidade"] == "Conflito de Vigência")


def test_relatorio_json(client):
    r = client.post("/reports", json={"tema": "inovacao", "personaId": "diretora_diraf"})
    deck = r.json()
    assert r.status_code == 200 and len(deck["slides"]) == 3
    assert "96.000,00" in deck["slides"][0]["titulo"]
    assert set(deck["slides"][0]) == {"numero", "titulo", "destaque", "itens", "rodapeCitacao"}


def test_relatorio_exige_acesso_a_todas_as_fontes(client):
    assert client.post("/reports", json={"tema": "inovacao"}).status_code == 403
    assert client.post("/reports", json={"tema": "locacao", "personaId": "ana"}).status_code == 403
    assert client.get("/reports/pptx?tema=locacao", headers=P["ana"]).status_code == 403
    assert client.post("/reports", json={"tema": "locacao",
                                         "personaId": "rafael"}).status_code == 200
    assert client.post("/reports", json={"tema": "../x", "personaId": "ana"}).status_code == 422


def test_pptx_valido_com_classificacao_e_citacao_nas_notas(client):
    r = client.get("/reports/pptx?tema=locacao", headers=P["rafael"])
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="contrato-coworking.pptx"'
    assert "no-store" in r.headers["cache-control"]
    prs = Presentation(BytesIO(r.content))
    assert len(prs.slides) == 4
    assert "CTR_2026-012" in prs.slides[1].notes_slide.notes_text_frame.text
    assert prs.core_properties.keywords == "classificacao:Sigilosa"


def test_limite_de_relatorios(client):
    for _ in range(3):
        assert client.post("/reports", json={"tema": "ferias", "personaId": "ana"}).status_code \
            == 200
    assert client.post("/reports", json={"tema": "ferias", "personaId": "ana"}).status_code == 429


def test_cors_so_origem_permitida(client):
    pre = {"Access-Control-Request-Method": "POST",
           "Access-Control-Request-Headers": "content-type,x-persona-id"}
    ok = client.options("/chat", headers={"Origin": "http://localhost:3000", **pre})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    ruim = client.options("/chat", headers={"Origin": "http://malicioso.example", **pre})
    assert "access-control-allow-origin" not in ruim.headers


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
    assert client.get("/docs").status_code == 401
    assert client.get("/docs", headers=P["diretora"]).status_code == 401  # header de demo ignorado
    assert client.get("/docs", headers={"Authorization": "Bearer ana.9999999999.abc"}
                      ).status_code == 401

    token = auth.emitir_token("ana")
    h = {"Authorization": f"Bearer {token}"}
    assert {d["codigo"] for d in client.get("/docs", headers=h).json()["vigentes"]} \
        >= {"NG_111"}
    # Token de Ana não vira outra persona pelo body.
    r = client.post("/chat", headers=h, json={"message": "oi", "personaId": "curadora_ggc"})
    assert r.status_code == 403

    vencido = f"ana.{int(time.time()) - 10}.{auth._assinar('ana', int(time.time()) - 10, 's' * 40)}"
    assert client.get("/docs", headers={"Authorization": f"Bearer {vencido}"}).status_code == 401
