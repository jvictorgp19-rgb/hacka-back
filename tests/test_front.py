"""Rotas do hacka-front (src/services/http/client.ts): formato do contrato e regra de acesso."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import get_settings
from app.core.setores import setores
from app.services import registros
from app.services.acervo import get_acervo
from app.services.evidencias import _compacto, _seed

CTX = {"conversationId": "c1", "tema": "todos", "area": "", "perspective": "obligations",
       "from": "", "to": "", "persona": "ana"}
CHAVES_DOC = {"id", "codigo", "titulo", "versao", "fase", "vigente", "tema", "area", "camada",
              "resumo", "vigencia"}
CHAVES_CITACAO = {"id", "documentId", "codigo", "titulo", "versao", "status", "item", "trecho"}
CHAVES_FATO = {"id", "title", "text", "tema", "area", "perspective", "citation"}
CHAVES_RESPOSTA = {"id", "query", "status", "text", "facts", "citations", "context", "origin",
                   "createdAt", "nextSteps"}


@pytest.fixture(autouse=True)
def _limpo(client):
    registros.limpar()
    client.cookies.clear()


def H(persona: str) -> dict:  # noqa: N802
    return {"X-Persona-Id": persona}


def _sem_nulos(valor) -> bool:
    """zod .optional() recusa null: nenhum campo pode vir null."""
    if isinstance(valor, dict):
        return all(v is not None and _sem_nulos(v) for v in valor.values())
    if isinstance(valor, list):
        return all(_sem_nulos(v) for v in valor)
    return True


def _perguntar(client, query: str, persona: str = "ana", **ctx) -> dict:
    r = client.post("/conversations/messages",
                    json={"query": query, "context": {**CTX, "persona": persona, **ctx}})
    assert r.status_code == 200, r.text
    resposta = r.json()
    assert CHAVES_RESPOSTA <= resposta.keys() and _sem_nulos(resposta)
    assert resposta["origin"] == "api" and resposta["context"]["persona"] == persona
    return resposta


# ---------- acervo ----------
def test_documents_formato_e_acesso(client):
    assert client.get("/documents").json() == []
    ana = client.get("/documents", headers=H("ana")).json()
    assert ana and all(CHAVES_DOC <= d.keys() for d in ana) and _sem_nulos(ana)
    assert {d["area"] for d in ana} <= set(setores())  # sigla BBTS
    ids = {d["id"] for d in ana}
    assert "NG_111@3.0.0" in ids and "CTR_2026-012@1.0.0" not in ids
    assert "NG_111@2.0.0" not in ids  # substituída é Sigilosa da GEPEC
    assert "RG_1100@1.0.0" in ids  # sem PDF: segue a vigente, e vem sem fileUrl
    assert "fileUrl" not in next(d for d in ana if d["id"] == "RG_1100@1.0.0")
    ng = next(d for d in ana if d["id"] == "NG_111@3.0.0")
    assert ng["fileUrl"].startswith("http") and ng["fileUrl"].endswith("/file")
    curadora = {d["id"] for d in client.get("/documents", headers=H("curadora_ggc")).json()}
    assert "NG_111@2.0.0" in curadora


def test_pdf_so_para_quem_ve_o_documento(client):
    r = client.get("/documents/NG_111%403.0.0/file", headers=H("ana"))
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF") and r.headers["cache-control"] == "private, no-store"
    assert client.get("/documents/CTR_2026-012%401.0.0/file", headers=H("ana")).status_code == 404
    assert client.get("/documents/NG_111%403.0.0/file").status_code == 404  # anônimo
    assert client.get("/documents/..%2F..%2Fetc@1.0.0/file", headers=H("ana")).status_code in (
        404, 422)
    r = client.get("/documents/CTR_2026-012%401.0.0/file", headers=H("rafael"))
    assert r.status_code == 200


def test_evidencias_conferem_com_o_acervo():
    acervo = get_acervo()
    for f in _seed()["fatos"] + [{"citation": c} for c in _seed()["fontes_simulacao"]]:
        c = f["citation"]
        alvo = _compacto(c["trecho"])[:60]
        assert any(alvo in _compacto(k.texto) for k in acervo.chunks
                   if k.codigo == c["codigo"] and k.versao == c["versao"]), c["codigo"]
        assert c["page"] >= 1


def test_evidence_filtra_pelo_documento_citado(client):
    assert client.get("/analyses/evidence").json() == []
    ana = client.get("/analyses/evidence", headers=H("ana")).json()
    assert ana and all(CHAVES_FATO <= f.keys() and CHAVES_CITACAO <= f["citation"].keys()
                       for f in ana) and _sem_nulos(ana)
    assert all(f["tema"] != "locacao" for f in ana)
    assert all(f["citation"]["codigo"] != "NT_2026-021" for f in ana)  # alçadas: sigilosa
    rafael = {f["id"] for f in client.get("/analyses/evidence", headers=H("rafael")).json()}
    assert {"locacao-multa", "locacao-prorroga", "locacao-vistoria"} <= rafael


def test_deadlines_com_fato_e_prioridade(client):
    rafael = client.get("/deadlines?hoje=2026-11-12", headers=H("rafael")).json()
    assert _sem_nulos(rafael)
    vistoria = next(d for d in rafael if d["date"] == "2026-11-25")
    assert vistoria["priority"] == "Crítica" and vistoria["owner"] == "GESUC"
    assert vistoria["fact"]["id"] == "locacao-vistoria"  # o fato curado do mesmo prazo
    assert all(d["fact"]["citation"]["trecho"] for d in rafael)
    ana = client.get("/deadlines?hoje=2026-11-12", headers=H("ana")).json()
    assert ana and all(d["owner"] != "GESUC" for d in ana)
    consolidacao = next(d for d in ana if d["date"] == "2026-11-30")
    assert consolidacao["fact"]["citation"]["item"] == "4.2.2"
    assert client.get("/deadlines").json() == []


def test_findings_so_governanca(client):
    assert client.get("/audit/findings?hoje=2026-11-12", headers=H("ana")).json() == []
    achados = client.get("/audit/findings?hoje=2026-11-12", headers=H("curadora_ggc")).json()
    assert achados and all(set(a) == {"id", "title", "detail", "documents"} for a in achados)
    assert "NT_2026-021" not in json.dumps(achados)


def test_simulation_rules_so_com_todas_as_fontes(client, monkeypatch):
    assert client.get("/simulation-rules").status_code == 401
    for persona in ("ana", "rafael", "helena", "diretora_diraf"):
        r = client.get("/simulation-rules", headers=H(persona))
        assert r.status_code == 403  # o pacote junta alçadas e contrato sigilosos
        assert "3650" not in r.text and "18000" not in r.text
    monkeypatch.setattr(type(get_acervo()), "autorizado", lambda *_: True)
    regras = client.get("/simulation-rules", headers=H("diretora_diraf")).json()
    assert regras["advanceDays"] == 45 and regras["absencePercent"] == 30
    assert regras["absenceTiers"][0] == {"max": 5, "days": 30}
    assert regras["rentCents"] == 365000 and regras["fineThroughDay"] == 90
    assert regras["managerCapCents"] == 1800000 and regras["globalCents"] == 1825000
    assert "2027-03-26" in regras["calendar"]["holidays"]  # Sexta-feira Santa (Páscoa 28/03)
    itens = {(c["codigo"], c["item"]) for c in regras["citations"]}
    assert ("NG_111", "4.6.3") in itens and ("TB_1111-001", "Tabela 1") in itens


# ---------- conversa ----------
def test_conversa_responde_no_formato_answer(client):
    r = _perguntar(client, "Quero férias a partir de 05/05/2027. Até quando peço?")
    assert r["status"] == "answered" and "21/03/2027" in r["text"]
    assert "**" not in r["text"]
    assert r["facts"] and r["citations"]
    assert all(CHAVES_CITACAO <= c.keys() and c["trecho"] for c in r["citations"])


def test_conversa_status_do_front(client):
    assert _perguntar(client, "Mas não eram 30 dias de antecedência?")["status"] == "conflict"
    bloqueio = _perguntar(client, "Qual o valor do aluguel do coworking?", tema="locacao")
    assert bloqueio["status"] == "access_required"
    assert bloqueio["facts"] == [] and bloqueio["citations"] == []
    assert "3.650" not in json.dumps(bloqueio) and "CTR_2026" not in json.dumps(bloqueio)
    assert bloqueio["nextSteps"][0] == "Solicitar orientação"
    lacuna = _perguntar(client, "Como o prêmio de equipe é dividido?", "marina", tema="inovacao")
    assert lacuna["status"] == "abstained"


def test_historico_por_persona_e_pergunta_mascarada(client):
    _perguntar(client, "Meu CPF é 529.982.247-25. Quantos dias de férias com 3 faltas?")
    _perguntar(client, "Equipe de 9, quantos podem sair juntos?", "carlos")
    ana = client.get("/conversations/messages?persona=ana").json()
    assert len(ana) == 1 and "529.982.247-25" not in json.dumps(ana)
    assert [m["context"]["persona"] for m in client.get(
        "/conversations/messages?persona=carlos").json()] == ["carlos"]
    assert client.get("/conversations/messages").json() == []  # anônimo


# ---------- pedidos de acesso ----------
def _pedir(client, persona: str, owner: str, reason: str = "Preciso ver o contrato inteiro."):
    return client.post("/access-requests",
                       json={"reason": reason, "persona": persona, "owner": owner})


def test_pedido_de_acesso_por_setor_dono(client):
    r = _pedir(client, "ana", "GESUC")
    assert r.status_code == 200, r.text
    pedido = r.json()
    assert pedido["status"] == "pending" and pedido["owner"] == "GESUC" and _sem_nulos(pedido)
    assert _pedir(client, "ana", "GGC").status_code == 422  # sigla ACME: o contrato é BBTS
    assert _pedir(client, "ana", "GESUC", "curto").status_code == 422
    assert client.post("/access-requests", json={"reason": "Preciso ver o contrato inteiro.",
                                                 "owner": "GESUC"}).status_code == 401
    ana = {p["id"] for p in client.get("/access-requests?persona=ana").json()}
    assert ana == {pedido["id"], "REQ-2026-089"}
    curadora = {p["id"] for p in client.get("/access-requests?persona=curadora_ggc").json()}
    assert curadora == {"REQ-2026-089"}  # o da GESUC não é com a GEPEC
    if setores()["GESUC"].diretoria == "DIRAF":
        diretora = client.get("/access-requests?persona=diretora_diraf").json()
        assert pedido["id"] in {p["id"] for p in diretora}


def test_decisao_do_pedido(client):
    url = "/access-requests/REQ-2026-089/decision"
    corpo = {"status": "curated", "response": "Use o resumo publicado da NG_111."}
    assert client.post(url, json={**corpo, "persona": "carlos"}).status_code == 404
    assert client.post(url, json={**corpo, "persona": "ana"}).status_code == 403
    assert client.post(url, json={**corpo, "response": "", "persona": "curadora_ggc"}
                       ).status_code == 422
    r = client.post(url, json={**corpo, "persona": "curadora_ggc"})
    assert r.status_code == 200, r.text
    decidido = r.json()
    assert decidido["status"] == "curated" and decidido["decidedBy"] == "Curadora da GEPEC"
    assert decidido["decidedAt"]
    assert client.post(url, json={**corpo, "persona": "curadora_ggc"}).status_code == 409
    [visto] = client.get("/access-requests?persona=ana").json()
    assert visto["status"] == "curated"
    assert client.post("/access-requests/nao-existe/decision",
                       json={**corpo, "persona": "curadora_ggc"}).status_code == 404


# ---------- análises e feedback ----------
def test_analise_salva_com_fatos_do_servidor(client):
    falso = {"id": "locacao-multa", "title": "x", "text": "Multa de R$ 0", "tema": "locacao"}
    registro = {"id": "r1", "title": "Minha análise", "kind": "analysis", "persona": "ana",
                "facts": [{"id": "ferias-pedido", "text": "adulterado"}, falso],
                "context": CTX, "createdAt": "2026-11-12T10:00:00Z"}
    r = client.post("/analyses", json=registro)
    assert r.status_code == 200, r.text
    salvo = r.json()
    assert [f["id"] for f in salvo["facts"]] == ["ferias-pedido"]  # locação: sigilosa
    assert salvo["facts"][0]["text"] != "adulterado"
    assert [a["id"] for a in client.get("/analyses?persona=ana").json()] == ["r1"]
    assert client.get("/analyses?persona=carlos").json() == []
    registro["title"] = "Renomeada"
    client.post("/analyses", json=registro)
    assert [a["title"] for a in client.get("/analyses?persona=ana").json()] == ["Renomeada"]


def test_feedback_um_por_alvo(client):
    item = {"id": "f1", "targetId": "resp-1", "persona": "ana", "useful": True, "reason": ""}
    assert client.post("/feedback", json=item).status_code == 200
    client.post("/feedback", json={**item, "id": "f2", "useful": False, "reason": "Incompleta"})
    [salvo] = client.get("/feedback?persona=ana").json()
    assert salvo["useful"] is False and salvo["reason"] == "Incompleta"
    assert client.get("/feedback?persona=carlos").json() == []


def test_retencao_apaga_registros_antigos(client):
    _perguntar(client, "Equipe de 9, quantos podem sair juntos?")
    depois = datetime.now(UTC) + timedelta(days=get_settings().retencao_registros_dias + 1)
    assert registros.expurgar(depois) == 1
    assert client.get("/conversations/messages?persona=ana").json() == []


# ---------- achados do /code-review ----------
def test_tema_todos_nao_puxa_para_ferias(client):
    """'todos' é valor do contrato (contextSchema): sem viés de tema."""
    r = _perguntar(client, "A Tese de Inovação é publicada até 31/01/2027?", "bruno")
    assert "NG_1130" in {c["codigo"] for c in r["citations"]}
    assert "Portal Raiz" not in r["text"]


def test_resposta_com_envios_nao_fica_no_historico(client):
    from app.services.front import SEM_HISTORICO

    vivo = _perguntar(client, "Quantos dias de férias eu tenho?")
    assert vivo["text"] != SEM_HISTORICO
    [guardado] = client.get("/conversations/messages?persona=ana").json()
    assert guardado["id"] == vivo["id"] and guardado["text"] == SEM_HISTORICO


def test_historico_relido_com_link_e_acesso_atuais(client):
    vivo = client.post("/conversations/messages", headers={"Host": "evil.example"},
                       json={"query": "Quero férias a partir de 05/05/2027. Até quando peço?",
                             "context": CTX}).json()
    assert any(c.get("url", "").startswith("http://evil.example") for c in vivo["citations"])
    [lido] = client.get("/conversations/messages?persona=ana").json()
    urls = [c["url"] for c in lido["citations"] if "url" in c]
    assert urls and all(u.startswith("http://testserver/") for u in urls)
    assert "evil.example" not in json.dumps(registros.listar("conversa", persona="ana"))
    # Fonte que a pessoa não vê mais (ou nunca viu): a resposta inteira fica oculta.
    citacao = {"id": "x", "documentId": "CTR_2026-012@1.0.0", "codigo": "CTR_2026-012",
               "titulo": "t", "versao": "1.0.0", "status": "Vigente", "item": "i",
               "trecho": "Multa de R$ 3.650,00"}
    registros.salvar("conversa", "ana", "velha", {**lido, "id": "velha",
                                                  "createdAt": "2026-11-13T00:00:00Z",
                                                  "citations": [citacao]})
    velha = next(m for m in client.get("/conversations/messages?persona=ana").json()
                 if m["id"] == "velha")
    assert velha["citations"] == [] and "3.650" not in json.dumps(velha)


def test_historico_em_ordem_cronologica(client):
    primeira = _perguntar(client, "Equipe de 9, quantos podem sair juntos?")
    segunda = _perguntar(client, "Quantos dias de férias com 3 faltas?")
    ids = [m["id"] for m in client.get("/conversations/messages?persona=ana").json()]
    assert ids == [primeira["id"], segunda["id"]]


def test_conversa_responde_mesmo_sem_banco(client, monkeypatch):
    from sqlalchemy.exc import OperationalError

    def cai(*_args, **_kwargs):
        raise OperationalError("x", {}, Exception("host secreto"))

    monkeypatch.setattr(registros, "salvar", cai)
    assert _perguntar(client, "Equipe de 9, quantos podem sair juntos?")["status"] == "answered"
    monkeypatch.setattr(registros, "listar", cai)
    r = client.get("/feedback?persona=ana")
    assert r.status_code == 503 and "host secreto" not in r.text


def test_decisao_concorrente_so_uma_grava(client):
    """Compare-and-set: a segunda gravação com a mesma versão lida perde."""
    item = {"id": "p1", "status": "pending"}
    assert registros.trocar("pedido", "ana", "p1", item, "GESUC", None)
    assert not registros.trocar("pedido", "ana", "p1", item, "GESUC", None)
    lido = registros.obter("pedido", "p1")
    assert registros.trocar("pedido", "ana", "p1", {**item, "status": "denied"}, "GESUC",
                            lido.versao)
    assert not registros.trocar("pedido", "ana", "p1", {**item, "status": "granted"}, "GESUC",
                                lido.versao)
    assert registros.obter("pedido", "p1").dados["status"] == "denied"


def test_vencido_some_da_leitura_antes_do_expurgo(client, monkeypatch):
    _perguntar(client, "Equipe de 9, quantos podem sair juntos?")
    monkeypatch.setattr(get_settings(), "retencao_registros_dias", -1)
    assert client.get("/conversations/messages?persona=ana").json() == []


def test_retencao_periodica_roda_envios_e_registros(client, monkeypatch):
    from app.services import retencao

    chamados = []
    monkeypatch.setattr(retencao, "TAREFAS", (("a", lambda: chamados.append("a") or 0),
                                              ("b", lambda: 1 / 0),
                                              ("c", lambda: chamados.append("c") or 1)))
    retencao.rodar_uma_vez()  # uma falha não impede as outras
    assert chamados == ["a", "c"]


def test_data_da_analise_em_utc(client):
    base = {"id": "r2", "title": "A", "kind": "analysis", "persona": "ana", "facts": [],
            "context": CTX}
    r = client.post("/analyses", json={**base, "createdAt": "0001-01-01T00:00:00+05:00"})
    assert r.status_code == 200 and r.json()["createdAt"].startswith(str(datetime.now(UTC).year))
    r = client.post("/analyses", json={**base, "createdAt": "2026-11-12T10:00:00"})
    assert r.json()["createdAt"] == "2026-11-12T10:00:00Z"  # sem fuso: UTC


def test_resposta_visivel_com_aviso_de_sigilo_nao_vira_bloqueio():
    from app.schemas.api import ChatResponse, CostBadge, RbacBlock
    from app.services.front import ORIENTACAO, _proximos_passos, _status

    bloqueio = RbacBlock(dominioResponsavel="GESUC", nivelExigido="Sigilosa", mensagem="m")
    custo = CostBadge(type="deterministic", label="", latencyMs=1, sigiloNivel="Interna")
    citacao = {"codigo": "NG_111", "titulo": "Férias", "versao": "v3.0.0", "status": "Vigente"}
    parcial = ChatResponse(answer="a", bullets=[], citations=[citacao], costBadge=custo,
                           rbacBlock=bloqueio, suggestedFollowups=[])
    assert _status(parcial) == "answered"
    assert ORIENTACAO in _proximos_passos(parcial, "answered", [])
    assert _status(parcial.model_copy(update={"citations": []})) == "access_required"


def test_citacao_de_versao_antiga_nao_herda_a_vigente():
    from app.services.evidencias import Links, citacao

    antiga = citacao(Links("http://x"), "RG_1100", "1.0.0", "4.2", "trecho")
    assert antiga["status"] != "Vigente" and "url" not in {k for k, v in antiga.items() if v}


def test_vigencia_sempre_iso(client):
    import re

    docs = client.get("/documents", headers=H("curadora_ggc")).json()
    assert docs and not any(re.search(r"\d{2}/\d{2}/\d{4}", d["vigencia"]) for d in docs)
