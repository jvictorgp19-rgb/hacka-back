"""Gabaritos tirados dos próprios documentos (NG_111 Anexo C, TB_1111-001, NT_2026-021, CTR)."""

from datetime import date
from decimal import Decimal

import pytest

from app.services.calculators import alcadas, contrato, ferias
from app.services.calculators import calendario as cal


def test_timeline_do_exemplo_oficial_da_ng_111():
    r = ferias.calcular_prazos_ferias(date(2027, 5, 5))
    assert r.inicio_valido
    datas = {m.marco: m.data for m in r.marcos}
    assert datas["D-45"] == date(2027, 3, 21)
    assert datas["D-35"] == date(2027, 3, 31)
    assert datas["D-30"] == date(2027, 4, 5)
    assert datas["D-20"] == date(2027, 4, 15)
    assert datas["D-19"] == date(2027, 4, 16)
    # 02/05/2027 é domingo e 01/05 é feriado: pagamento antecipado para sexta 30/04.
    assert datas["D-3"] == date(2027, 4, 30)


@pytest.mark.parametrize(
    "inicio",
    [
        date(2027, 5, 6),  # quinta: 2 dias úteis antes do domingo
        date(2027, 5, 7),  # sexta
        date(2027, 5, 8),  # sábado: não é dia útil
        date(2027, 4, 19),  # segunda: 2 dias úteis antes de Tiradentes (quarta 21/04)
        date(2027, 4, 21),  # feriado
    ],
)
def test_inicio_vedado(inicio):
    valido, motivo = ferias.validar_inicio(inicio)
    assert not valido and motivo


def test_inicio_permitido():
    assert ferias.validar_inicio(date(2027, 5, 5))[0]
    assert ferias.validar_inicio(date(2027, 5, 3))[0]


@pytest.mark.parametrize(
    "faltas,dias", [(0, 30), (5, 30), (6, 24), (14, 24), (15, 18), (23, 18), (24, 12), (32, 12),
                    (33, 0)]
)
def test_faltas(faltas, dias):
    assert ferias.dias_por_faltas(faltas) == dias


@pytest.mark.parametrize(
    "equipe,maximo", [(1, 1), (3, 1), (4, 1), (6, 1), (7, 2), (9, 2), (10, 3), (13, 3), (14, 4),
                      (16, 4)]
)
def test_limite_ausencia_bate_com_tabela_4(equipe, maximo):
    assert ferias.limite_ausencia(equipe) == maximo


def test_fracionamento():
    assert ferias.validar_fracionamento([14, 8, 8])[0]
    assert not ferias.validar_fracionamento([10, 10, 10])[0]
    assert not ferias.validar_fracionamento([20, 6, 4])[0]
    assert not ferias.validar_fracionamento([14, 5, 5, 5])[0]


def test_ressarcimento_tem_teto():
    assert ferias.ressarcimento_cancelamento(Decimal(1800)) == Decimal(1800)
    assert ferias.ressarcimento_cancelamento(Decimal(3000)) == Decimal("2500.00")


def test_alcadas_de_inovacao():
    assert alcadas.quem_aprova(Decimal("18000.00")).aprovador == "Gerente do NIN"
    assert alcadas.quem_aprova(Decimal("18000.01")).aprovador == "Diretor da DIRTEC"
    assert alcadas.quem_aprova(Decimal("120000.00")).aprovador == "Diretor da DIRTEC"
    assert alcadas.quem_aprova(Decimal("120000.01")).aprovador == "Comitê de Alçadas"


def test_alcada_geral_acima_de_120_mil_nao_consta():
    assert alcadas.quem_aprova(Decimal(18250), "geral").aprovador == "Diretor"
    assert alcadas.quem_aprova(Decimal(200000), "geral").aprovador is None


def test_alcada_rejeita_valor_invalido():
    with pytest.raises(ValueError):
        alcadas.quem_aprova(Decimal("NaN"))
    with pytest.raises(ValueError):
        alcadas.quem_aprova(Decimal(-1))


def test_contrato_marcos():
    assert contrato.VISTORIA_ATE == date(2026, 11, 25)
    assert contrato.PRORROGACAO_ATE == date(2027, 3, 30)
    assert contrato.ULTIMO_DIA_COM_MULTA == date(2027, 2, 27)
    assert contrato.GLOSA_DIARIA == Decimal("121.67")
    assert contrato.ADITIVO_MAXIMO == Decimal("3650.00")
    assert contrato.MULTA_INEXECUCAO == Decimal("912.50")


def test_multa_de_rescisao_vira_no_91o_dia():
    assert contrato.multa_rescisao(date(2027, 2, 27)).multa == Decimal("3650.00")
    assert contrato.multa_rescisao(date(2027, 2, 28)).multa == Decimal("0.00")
    assert contrato.multa_rescisao(date(2027, 3, 15)).multa == Decimal("0.00")
    with pytest.raises(ValueError):
        contrato.multa_rescisao(date(2028, 1, 1))


def test_pagamento_dia_8_ou_dia_util_seguinte():
    assert contrato.pagamento_do_mes(2027, 1) == date(2027, 1, 8)  # sexta
    assert contrato.pagamento_do_mes(2027, 5) == date(2027, 5, 10)  # dia 8 é sábado


def test_feriado_movel():
    assert cal.feriado(date(2027, 3, 26)) == "Sexta-feira Santa"
