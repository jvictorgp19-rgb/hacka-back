"""Férias pelo que a pessoa enviou: triagem extrai faltas e o chat calcula os dias."""

import pytest
from openpyxl import Workbook

from app.services import envios
from app.services.triagem.ferias import extrair_fatos

FORM = ("FM_1111-001 Solicitação de Férias\nNome do empregado: Bruno Lima\nMatrícula: 4512398\n"
        "Data de admissão: 03/03/2024\nPeríodo aquisitivo: 03/03/2025 a 02/03/2026\n"
        "Início de gozo: 05/05/2027\nFaltas injustificadas: 8\n")
PERGUNTA = "Quantos dias de férias eu tenho?"


@pytest.fixture(autouse=True)
def _limpo(client):
    envios.limpar()
    yield
    envios.esperar()


def _enviar(client, persona: str, nome: str, corpo: bytes) -> dict:
    r = client.post("/document-jobs", files=[("files", (nome, corpo))],
                    headers={"X-Persona-Id": persona})
    assert r.status_code == 200, r.text
    assert envios.esperar()
    return client.get(f"/document-jobs/{r.json()[0]['id']}",
                      headers={"X-Persona-Id": persona}).json()


# ---------- extração ----------
def test_formulario_preenchido_vira_fatos_sem_nome_nem_cpf():
    f = extrair_fatos([FORM])
    assert f.faltas_injustificadas == 8 and f.origem_faltas == "declarado"
    assert (f.periodo_inicio, f.periodo_fim) == ("2025-03-03", "2026-03-02")
    assert f.admissao == "2024-03-03" and f.inicio_gozo == "2027-05-05"
    assert "Bruno" not in str(f.as_dict()) and "4512398" not in str(f.as_dict())


def test_formulario_em_branco_nao_gera_fato():
    assert extrair_fatos(["Período aquisitivo: [início] a [fim]\nFaltas injustificadas: ____\n"
                          "Início de gozo: [data]"]) is None


def test_espelho_de_ponto_conta_as_faltas(tmp_path):
    from app.services.triagem.extracao import extrair

    livro = Workbook()
    aba = livro.active
    aba.append(["Data", "Ocorrência"])
    for dia in range(1, 11):
        aba.append([f"{dia:02d}/04/2025", "Falta injustificada" if dia % 2 else "Presente"])
    aba.append(["Total", "Falta injustificada: ver acima"])
    livro.save(tmp_path / "ponto.xlsx")
    f = extrair_fatos(extrair(tmp_path / "ponto.xlsx", "ponto.xlsx").paginas)
    assert f.faltas_injustificadas == 5 and f.origem_faltas == "contagem"


# ---------- envio + chat ----------
def test_chat_calcula_os_dias_pelo_formulario_enviado(client, perguntar):
    item = _enviar(client, "bruno", "minhas_ferias.txt", FORM.encode())
    assert item["classificacao"]["nivel"] == "Sigilosa"
    assert item["departamento"]["sigla"] == "GEPEC"
    assert item["ferias"]["faltasInjustificadas"] == 8 and item["ferias"]["diasDeFerias"] == 24

    r = perguntar(PERGUNTA, persona="bruno")
    assert "8 faltas injustificadas" in r["answer"] and "24 dias corridos" in r["answer"]
    assert "minhas_ferias.txt" in " ".join(r["bullets"])
    assert any("provisório" in b for b in r["bullets"])  # júnior: envio ainda pendente
    assert {c["codigo"] for c in r["citations"]} >= {"TB_1111-001", "NG_111"}


def test_dados_de_ferias_so_para_a_pessoa_e_a_aprovadora(client):
    item = _enviar(client, "bruno", "minhas_ferias.txt", FORM.encode())
    ver = lambda p: client.get(f"/document-jobs/{item['id']}",  # noqa: E731
                               headers={"X-Persona-Id": p})
    assert ver("curadora_ggc").json()["ferias"]["diasDeFerias"] == 24  # aprovadora (GEPEC)
    assert ver("helena").status_code == 404  # tech lead do júnior: dado pessoal não é do GEINOV
    assert ver("fernanda").status_code == 404


def test_formulario_de_outro_empregado_nao_entra_no_calculo(client, perguntar):
    item = _enviar(client, "bruno", "ferias_joana.txt",
                   FORM.replace("Bruno Lima", "Joana Pereira").encode())
    assert item["ferias"]["faltasInjustificadas"] == 8  # quem enviou vê o que enviou
    r = perguntar(PERGUNTA, persona="bruno")
    assert "8 faltas" not in r["answer"]
    assert any("outra pessoa" in b for b in r["bullets"])


def test_titular_confere_o_nome_inteiro_da_persona():
    from app.services.triagem.ferias import nome_titular, titular_confere

    assert nome_titular([FORM]) == "bruno lima"
    assert titular_confere("bruno lima", "Bruno") == "proprio"
    assert titular_confere("joana pereira", "Bruno") == "outro"
    assert titular_confere(None, "Bruno") == "nao_informado"


def test_chat_nao_usa_o_envio_de_outra_pessoa(client, perguntar):
    _enviar(client, "ana", "ferias_ana.txt", FORM.encode())
    r = perguntar(PERGUNTA, persona="bruno")
    assert "Não encontrei faltas" in r["answer"] and "8 faltas" not in r["answer"]
    assert r["honestAbstention"]["donoDominio"]


def test_pergunta_com_numero_continua_na_calculadora(client, perguntar):
    _enviar(client, "bruno", "minhas_ferias.txt", FORM.encode())
    r = perguntar("Tenho 20 faltas injustificadas. Quantos dias de férias eu tenho?",
                  persona="bruno")
    assert "18 dias" in r["answer"]


def test_anonimo_nao_recebe_dado_de_envio(client, perguntar):
    _enviar(client, "bruno", "minhas_ferias.txt", FORM.encode())
    r = perguntar(PERGUNTA, persona=None)
    assert "8 faltas" not in r["answer"]


@pytest.mark.parametrize("pergunta", ["Quantos dias tenho de férias?",
                                      "Quantos dias me restam de férias?"])
def test_outras_formas_de_perguntar_o_proprio_saldo(client, perguntar, pergunta):
    _enviar(client, "bruno", "minhas_ferias.txt", FORM.encode())
    r = perguntar(pergunta, persona="bruno")
    assert "8 faltas injustificadas" in r["answer"] and "24 dias corridos" in r["answer"]


def test_encarregado_elimina_os_dados_pessoais_a_pedido(client):
    from sqlalchemy import select

    item = _enviar(client, "bruno", "minhas_ferias.txt", FORM.encode())
    assert envios.eliminar_a_pedido(item["id"]) == "eliminado"
    assert envios.esperar()
    depois = client.get(f"/document-jobs/{item['id']}", headers={"X-Persona-Id": "bruno"}).json()
    assert depois["name"] == envios.EXPURGADO and depois["ferias"] is None

    envios.limpar()  # como o script: só o banco
    assert envios.eliminar_a_pedido(item["id"]) == "eliminado"
    with envios._engine().connect() as c:
        linha = c.execute(select(envios.tabela).where(envios.tabela.c.id == item["id"])).one()
    assert linha.nome_arquivo == envios.EXPURGADO and linha.fatos_ferias is None
    assert linha.sha256 and linha.nivel_sugerido == "Sigilosa"  # metadados sem dado pessoal
    assert envios.eliminar_a_pedido("0" * 32) == "nao_encontrado"


@pytest.mark.parametrize("pergunta", ["Quantos dias de antecedência para pedir férias?",
                                      "Quantos dias de antecedência eu tenho para pedir férias?"])
def test_antecedencia_e_regra_da_norma_nao_saldo_de_envio(perguntar, pergunta):
    r = perguntar(pergunta, tema="todos")
    assert "45 dias" in r["answer"] and "faltas injustificadas" not in r["answer"]
    assert "NG_111" in {c["codigo"] for c in r["citations"]}


def test_prazo_com_dias_antes_nao_vira_saldo_de_envio(client, perguntar):
    _enviar(client, "bruno", "minhas_ferias.txt", FORM.encode())
    r = perguntar("Com quantos dias antes eu tenho que pedir férias?", persona="bruno")
    assert "faltas injustificadas" not in r["answer"] and "minhas_ferias.txt" not in str(r)
