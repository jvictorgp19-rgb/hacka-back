"""
Suíte Oficial de Avaliação Golden FAQ — 30 Perguntas e Gabaritos do Acervo BBTS / ACME
Comprova 100% de precisão matemática, citação de documento vigente, bloqueio de versões substituídas
e Abstenção Honesta.
"""

from fastapi.testclient import TestClient

from app.main import app
from app.tools import (
    calcular_prazos_ferias,
    comparar_versoes,
    dias_por_faltas,
    limite_ausencia,
    prazos_contrato,
    quem_aprova,
)

client = TestClient(app)


# ==============================================================================
# BLOCO 1: 12 TESTES DETERMINÍSTICOS DIRETOS NAS FERRAMENTAS (tools.py)
# ==============================================================================
def test_01_ferias_05_05_2027_timeline_exata():
    res = calcular_prazos_ferias("05/05/2027")
    assert res["data_inicio_valida"] is True
    assert res["marcos"]["D_45_solicitacao"] == "21/03/2027"
    assert res["marcos"]["D_35_emissao_aviso_ggc"] == "31/03/2027"
    assert res["marcos"]["D_30_assinatura_eletronica"] == "05/04/2027"
    assert res["marcos"]["D_20_limite_alteracao_empregado"] == "15/04/2027"
    # 02/05/2027 é domingo e 01/05/2027 é feriado -> antecipa para sexta 30/04/2027
    assert res["marcos"]["D_3_pagamento_gfi"] == "30/04/2027"
    assert res["pagamento_antecipado"] is True


def test_02_ferias_faltas_0_a_5_da_30_dias():
    assert dias_por_faltas(3)["dias_ferias_direito"] == 30


def test_03_ferias_faltas_6_a_14_da_24_dias():
    assert dias_por_faltas(8)["dias_ferias_direito"] == 24


def test_04_ferias_faltas_15_a_23_da_18_dias():
    assert dias_por_faltas(18)["dias_ferias_direito"] == 18


def test_05_ferias_faltas_24_a_32_da_12_dias():
    assert dias_por_faltas(28)["dias_ferias_direito"] == 12


def test_06_ferias_faltas_acima_32_perde_direito():
    assert dias_por_faltas(35)["dias_ferias_direito"] == 0


def test_07_limite_ausencia_equipe_9_carlos():
    res = limite_ausencia(9)
    assert res["max_ferias_simultaneas"] == 2
    assert res["calculo_exato"] == 2.7


def test_08_limite_ausencia_equipe_pequena_minimo_1():
    assert limite_ausencia(2)["max_ferias_simultaneas"] == 1


def test_09_alcada_18000_gerente_nin():
    res = quem_aprova(18000.00, "inovacao_prototipo")
    assert res["aprovador_inovacao_prototipo"] == "Gerente do NIN"


def test_10_alcada_18000_01_diretor_dirtec():
    res = quem_aprova(18000.01, "inovacao_prototipo")
    assert res["aprovador_inovacao_prototipo"] == "Diretor da DIRTEC"


def test_11_alcada_acima_120k_comite():
    res = quem_aprova(135000.00, "inovacao_prototipo")
    assert res["aprovador_inovacao_prototipo"] == "Comitê de Alçadas"


def test_12_contrato_ctr_2026_012_prazos_e_glosa():
    res = prazos_contrato("CTR_2026-012", dias_sem_internet=2)
    assert res["marcos_criticos"]["data_limite_vistoria_goc"] == "25/11/2026"
    assert res["marcos_criticos"]["dia_90_fim_multa_rescisoria"] == "27/02/2027"
    assert res["marcos_criticos"]["dia_91_inicio_isencao_multa"] == "28/02/2027"
    assert res["marcos_criticos"]["data_limite_pedido_prorrogacao"] == "30/03/2027"
    assert res["rescisao_marco_2027"]["tem_multa"] is False
    assert res["financeiro"]["desconto_total_aplicado"] == 243.34


# ==============================================================================
# BLOCO 2: 18 PERGUNTAS DE CHAT E ROTAS DA API (/chat, /docs, /radar, /access, /reports, /ingest)
# ==============================================================================
GOLDEN_CHAT_QUESTIONS = [
    ("Quero sair de férias em 05/05/2027. Qual o meu cronograma D-n?", "NG_111", "30/04/2027"),
    ("Posso pedir férias com 30 dias de antecedência?", "NG_111", "45 dias"),
    ("Tive 8 faltas injustificadas, quantos dias de férias tenho direito?", "TB_1111-001", "24 dias"),
    ("Carlos tem equipe de 9 pessoas: quantas podem sair juntas?", "TB_1111-001", "2 empregado"),
    ("Qual o valor máximo de ressarcimento se minhas férias forem canceladas em D-19?", "NG_111", "2.500,00"),
    ("Posso inscrever 3 ideias no programa Ideias em Campo 2027?", "RG_1100", "2 ideias"),
    ("Qual a pontuação máxima da gamificação no Ideias em Campo 2027?", "RG_1100", "800"),
    ("Qual o orçamento total do Ideias em Campo 2027 e a trava de incentivo fiscal?", "NT_2026-021", "96.000,00"),
    ("Quem aprova um protótipo de R$ 18.000,00 vs R$ 18.000,01?", "NT_2026-021", "Diretor da DIRTEC"),
    ("Como o prêmio é dividido em equipe no Ideias em Campo e se alguém for afastado?", "RG_1100", "Não consta"),
    ("Qual o desconto se a internet do coworking cair por mais de 4h?", "CTR_2026-012", "121,67"),
    ("Se rescindirmos o contrato CTR_2026-012 em março de 2027, pagamos multa?", "CTR_2026-012", "28/02/2027"),
    ("Qual a data-limite para pedir prorrogação do contrato CTR_2026-012?", "CTR_2026-012", "30/03/2027"),
    ("Quais foram as 3 cotações comparadas na NT_2026-018?", "NT_2026-018", "Hub Jacarandá"),
    ("Como funciona a desambiguação do campo vinculado_a na NG_010?", "NG_111", "vinculado_a"),
    ("Qual o dossiê restrito de auditoria da folha para ressarcimento D-15?", "NG_111", "RESTRITA"),
]


import pytest


@pytest.mark.parametrize("pergunta,doc_esperado,trecho_esperado", GOLDEN_CHAT_QUESTIONS)
def test_13_a_28_golden_faq_chat_16_perguntas(pergunta: str, doc_esperado: str, trecho_esperado: str):
    response = client.post("/chat", json={"message": pergunta, "tema": "ferias", "personaId": "ana"})
    assert response.status_code == 200
    data = response.json()
    codigos_citados = [c["codigo"] for c in data["citations"]]
    assert doc_esperado in codigos_citados, f"Esperava {doc_esperado} em {codigos_citados} para '{pergunta}'"
    texto_completo = data["answer"] + " " + " ".join(data["bullets"])
    assert trecho_esperado.lower() in texto_completo.lower(), (
        f"Esperava '{trecho_esperado}' na resposta para '{pergunta}'"
    )


def test_29_rotas_docs_radar_e_ingest_medalhao():
    r_docs = client.get("/docs")
    assert r_docs.status_code == 200
    assert len(r_docs.json()["vigentes"]) == 11
    assert len(r_docs.json()["substituidos"]) == 3

    r_radar = client.get("/radar")
    assert r_radar.status_code == 200
    assert len(r_radar.json()) >= 4

    r_ingest = client.post("/ingest")
    assert r_ingest.status_code == 200
    assert r_ingest.json()["resumo_camadas"]["gold_documentos_vigentes"] == 11


def test_30_fluxo_rbac_resposta_curada_e_relatorio_pptx():
    r_decide = client.post(
        "/access/decide",
        json={
            "id": "REQ-2026-089",
            "status": "Aprovado via Resposta Curada",
            "respostaCurada": "Orientação oficial curada pela GGC sem expor o PDF restrito.",
            "aprovadoPor": "Curadora da GGC",
        },
    )
    assert r_decide.status_code == 200
    assert r_decide.json()["status"] == "Aprovado via Resposta Curada"

    r_rep = client.post("/reports", json={"tema": "inovacao"})
    assert r_rep.status_code == 200
    assert len(r_rep.json()["slides"]) == 3
    assert comparar_versoes("NG_111")["versao_vigente"]["versao"] == "3.0.0"
