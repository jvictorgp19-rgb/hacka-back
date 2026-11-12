import math
from datetime import date, datetime, timedelta
from typing import Any

from app.models import load_acervo_json

FERIADOS_NACIONAIS_FIXOS = {
    (1, 1): "Confraternização Universal",
    (4, 21): "Tiradentes",
    (5, 1): "Dia do Trabalhador",
    (9, 7): "Independência do Brasil",
    (10, 12): "Nossa Senhora Aparecida",
    (11, 2): "Finados",
    (11, 15): "Proclamação da República",
    (11, 20): "Dia de Zumbi e da Consciência Negra",
    (12, 25): "Natal",
}


def is_feriado(d: date) -> bool:
    return (d.month, d.day) in FERIADOS_NACIONAIS_FIXOS


def is_dia_util(d: date) -> bool:
    return d.weekday() < 5 and not is_feriado(d)


def dia_util_anterior(d: date) -> date:
    curr = d
    while not is_dia_util(curr):
        curr -= timedelta(days=1)
    return curr


def parse_date_flex(date_str: str) -> date:
    s = date_str.strip()
    if "/" in s:
        parts = s.split("/")
        if len(parts[0]) == 2:
            return date(int(parts[2]), int(parts[1]), int(parts[0]))
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def format_br(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def calcular_prazos_ferias(inicio: str, fracionado: bool = False) -> dict[str, Any]:
    """
    Calcula os marcos D-45, D-35, D-30, D-20, D-19 e D-3 (antecipando para dia útil anterior
    se cair em fim de semana ou feriado, como 02/05/2027 -> 30/04/2027) e valida dias vedados.
    Ref: NG_111 v3.0.0 item 4.2, 4.5 e PX_1111-001 Anexo D.
    """
    d_inicio = parse_date_flex(inicio)

    # Validação de dia útil e 2 dias úteis que antecedem feriado ou DSR (Sábado/Domingo)
    inicia_dia_util = is_dia_util(d_inicio)
    cai_2_dias_antes_dsr_ou_feriado = False
    motivo_vedacao = None

    if not inicia_dia_util:
        motivo_vedacao = "O início de gozo deve ocorrer obrigatoriamente em dia útil (NG_111 item 4.2)."
    else:
        # Sexta-feira (weekday 4) ou Quinta-feira (weekday 3) antecedem o DSR de Sábado/Domingo em 1 ou 2 dias úteis
        if d_inicio.weekday() in (3, 4):
            cai_2_dias_antes_dsr_ou_feriado = True
            motivo_vedacao = "Data vedada: cai nos 2 dias úteis que antecedem o descanso semanal remunerado (NG_111 item 4.2)."
        else:
            # Verifica se há feriado nos próximos 1 ou 2 dias úteis
            d1 = d_inicio + timedelta(days=1)
            d2 = d_inicio + timedelta(days=2)
            if is_feriado(d1) or is_feriado(d2):
                cai_2_dias_antes_dsr_ou_feriado = True
                motivo_vedacao = "Data vedada: cai nos 2 dias úteis que antecedem feriado (NG_111 item 4.2)."

    d_45 = d_inicio - timedelta(days=45)
    d_35 = d_inicio - timedelta(days=35)
    d_30 = d_inicio - timedelta(days=30)
    d_20 = d_inicio - timedelta(days=20)
    d_19 = d_inicio - timedelta(days=19)
    d_3_bruto = d_inicio - timedelta(days=3)
    d_3_efetivo = dia_util_anterior(d_3_bruto)
    antecipado_d3 = d_3_efetivo != d_3_bruto

    return {
        "inicio_gozo": format_br(d_inicio),
        "inicio_iso": d_inicio.isoformat(),
        "fracionado": fracionado,
        "regra_fracionamento": "Até 3 períodos (1º período mínimo de 14 dias; demais mínimo de 5 dias corridos - NG_111 v3.0.0)"
        if fracionado
        else "Período único",
        "data_inicio_valida": inicia_dia_util and not cai_2_dias_antes_dsr_ou_feriado,
        "motivo_vedacao": motivo_vedacao,
        "marcos": {
            "D_45_solicitacao": format_br(d_45),
            "D_35_emissao_aviso_ggc": format_br(d_35),
            "D_30_assinatura_eletronica": format_br(d_30),
            "D_20_limite_alteracao_empregado": format_br(d_20),
            "D_19_alteracao_apenas_diretor": format_br(d_19),
            "D_3_teorico": format_br(d_3_bruto),
            "D_3_pagamento_gfi": format_br(d_3_efetivo),
        },
        "pagamento_antecipado": antecipado_d3,
        "explicacao_d3": (
            f"D-3 cairia em {format_br(d_3_bruto)} (fim de semana/feriado); antecipado para o dia útil anterior {format_br(d_3_efetivo)} conforme NG_111 item 4.5 e PX_1111-001 Anexo D."
            if antecipado_d3
            else f"Pagamento até D-3 em {format_br(d_3_efetivo)} (NG_111 item 4.5)."
        ),
        "citacoes": ["NG_111 v3.0.0 (itens 4.2 e 4.5)", "PX_1111-001 v1.0.0 (Anexo D)", "FM_1111-001 v2.0.0"],
    }


def limite_ausencia(tamanho_equipe: int) -> dict[str, Any]:
    """
    Calcula o limite de 30% de ausência simultânea da equipe, arredondado para baixo
    (mínimo de 1 pessoa em equipes de 1 a 3 empregados).
    Ref: NG_111 v3.0.0 item 4.6.3 e TB_1111-001 v1.0.0 (Tabela 4).
    """
    if tamanho_equipe <= 0:
        max_pessoas = 0
    elif tamanho_equipe <= 3:
        max_pessoas = 1
    else:
        max_pessoas = math.floor(tamanho_equipe * 0.30)

    return {
        "tamanho_equipe": tamanho_equipe,
        "percentual_teto": 30,
        "calculo_exato": round(tamanho_equipe * 0.30, 2),
        "max_ferias_simultaneas": max_pessoas,
        "regra": "Máximo de 30% da equipe ao mesmo tempo, arredondado para baixo (mínimo de 1 pessoa em equipes de 1 a 3 empregados).",
        "citacoes": ["NG_111 v3.0.0 (item 4.6.3)", "TB_1111-001 v1.0.0 (Tabela 4)"],
    }


def dias_por_faltas(n: int) -> dict[str, Any]:
    """
    Retorna a quantidade de dias corridos de férias conforme o número de faltas injustificadas
    no período aquisitivo. Ref: TB_1111-001 v1.0.0 (Tabela 1) e NG_111 v3.0.0.
    """
    faltas = max(0, int(n))
    if faltas <= 5:
        dias = 30
        faixa = "Até 5 faltas injustificadas"
    elif faltas <= 14:
        dias = 24
        faixa = "De 6 a 14 faltas injustificadas"
    elif faltas <= 23:
        dias = 18
        faixa = "De 15 a 23 faltas injustificadas"
    elif faltas <= 32:
        dias = 12
        faixa = "De 24 a 32 faltas injustificadas"
    else:
        dias = 0
        faixa = "Acima de 32 faltas injustificadas (Perda do direito no período)"

    return {
        "faltas_injustificadas": faltas,
        "dias_ferias_direito": dias,
        "faixa_enquadrada": faixa,
        "abono_max_dias": min(10, dias // 3) if dias > 0 else 0,
        "citacoes": ["TB_1111-001 v1.0.0 (Tabela 1)", "NG_111 v3.0.0"],
    }


def quem_aprova(valor: float, contexto: str = "inovacao_prototipo") -> dict[str, Any]:
    """
    Determina a alçada aprovadora com base no valor financeiro (R$) e no contexto.
    Até R$ 18.000,00: Gerente / Gerente do NIN
    De R$ 18.000,01 a R$ 120.000,00: Diretor (DIRAF / DIRTEC)
    Acima de R$ 120.000,00: Comitê de Alçadas
    Ref: NG_012, NT_2026-021 v1.0.0 (item 4.3) e NT_2026-018 v1.0.0.
    """
    v = round(float(valor), 2)
    is_inovacao = "inovacao" in contexto.lower() or "prototipo" in contexto.lower()

    if v <= 18000.00:
        faixa = "Até R$ 18.000,00"
        aprovador = "Gerente do NIN" if is_inovacao else "Gerente da Unidade"
        aprovador_geral = "Gerente"
        aprovador_inovacao = "Gerente do NIN"
    elif v <= 120000.00:
        faixa = "De R$ 18.000,01 a R$ 120.000,00"
        aprovador = "Diretor da DIRTEC" if is_inovacao else "Diretor da DIRAF / Diretor da Área"
        aprovador_geral = "Diretor (ex: DIRAF / DIRTEC)"
        aprovador_inovacao = "Diretor da DIRTEC"
    else:
        faixa = "Acima de R$ 120.000,00"
        aprovador = "Comitê de Alçadas"
        aprovador_geral = "Comitê de Alçadas"
        aprovador_inovacao = "Comitê de Alçadas"

    return {
        "valor": v,
        "valor_formatado": f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        "contexto": contexto,
        "faixa": faixa,
        "aprovador_competente": aprovador,
        "aprovador_geral": aprovador_geral,
        "aprovador_inovacao_prototipo": aprovador_inovacao,
        "citacoes": ["NG_012", "NT_2026-021 v1.0.0 (item 4.3)", "NT_2026-018 v1.0.0"],
    }


def prazos_contrato(codigo: str = "CTR_2026-012", dias_sem_internet: int = 0) -> dict[str, Any]:
    """
    Retorna todos os marcos e cálculos determinísticos do contrato CTR_2026-012:
    - Vistoria obrigatória: até 25/11/2026 (5 dias antes do início em 30/11/2026)
    - Pedido de prorrogação: até 30/03/2027 (30 dias antes do fim em 29/04/2027)
    - 90º dia de vigência: 27/02/2027 (multa rescisória de R$ 3.650,00 até o 90º dia)
    - 91º dia de vigência: 28/02/2027 (isenção total de multa R$ 0,00 a partir do 91º dia, inclusive março/2027)
    - Glosa diária de internet > 4h: R$ 121,67/dia (1/30 de R$ 3.650,00)
    """
    acervo = load_acervo_json()
    loc = acervo["jornadas_por_tema"]["locacao"]["regras_simuladores"]
    desconto_unitario = loc["valores"]["desconto_diario_internet_fora_4h"]
    desconto_total = round(max(0, int(dias_sem_internet)) * desconto_unitario, 2)
    aluguel_liquido = round(max(0.0, loc["valores"]["aluguel_mensal"] - desconto_total), 2)

    return {
        "codigo": codigo,
        "nota_tecnica_vinculada": loc["nota_tecnica_codigo"],
        "locadora": loc["locadora"],
        "local": loc["local"],
        "vigencia_dias": loc["vigencia_dias"],
        "data_inicio": "30/11/2026",
        "data_fim": "29/04/2027",
        "marcos_criticos": {
            "data_limite_vistoria_goc": "25/11/2026",
            "dia_90_fim_multa_rescisoria": "27/02/2027",
            "dia_91_inicio_isencao_multa": "28/02/2027",
            "data_limite_pedido_prorrogacao": "30/03/2027",
        },
        "rescisao_marco_2027": {
            "tem_multa": False,
            "valor_multa": 0.0,
            "explicacao": "O 90º dia encerra em 27/02/2027. A partir do 91º dia (28/02/2027), portanto em todo o mês de março/2027, a rescisão é isenta de multa (R$ 0,00), exigindo aviso prévio de 30 dias.",
        },
        "financeiro": {
            "aluguel_mensal": loc["valores"]["aluguel_mensal"],
            "valor_global_5_meses": loc["valores"]["valor_global_5_meses"],
            "limite_aditivo_20_pct": loc["valores"]["limite_aditivo_20_pct"],
            "desconto_diario_internet_fora_4h": desconto_unitario,
            "dias_sem_internet_simulados": dias_sem_internet,
            "desconto_total_aplicado": desconto_total,
            "valor_liquido_atesto_goc": aluguel_liquido,
        },
        "cotacoes_nt2026_018": loc["cotacoes_mercado_nt2026_018"],
        "rotina_mensal": loc["rotina_mensal"],
        "citacoes": ["CTR_2026-012 v1.0.0", "NT_2026-018 v1.0.0"],
    }


def comparar_versoes(codigo: str = "NG_111") -> dict[str, Any]:
    """
    Compara a versão substituída/bloqueada com a versão vigente (Diff normativo).
    Suporta NG_111 (v2.0.0 vs v3.0.0), FM_1111-001 (v1.0.0 vs v2.0.0) e RG_1100 (v1.0.0 vs v2.0.0).
    """
    c = codigo.upper().strip()
    if "1100" in c or "RG" in c:
        return {
            "codigo": "RG_1100",
            "titulo": "Regulamento do Programa Ideias em Campo",
            "versao_substituida": {
                "versao": "1.0.0",
                "fase": "Versão anterior (Revogada)",
                "aprovado_em": "02/03/2026",
                "regras_antigas": [
                    "Permitia até 3 ideias por proponente",
                    "Não exigia tempo mínimo de 6 meses de casa",
                    "Não possuía sistema de gamificação por pontos",
                    "Prêmio máximo limitado a R$ 5.000,00 por ideia sem premiação cumulativa por arena",
                ],
            },
            "versao_vigente": {
                "versao": "2.0.0",
                "fase": "Vigente (Edição 2027)",
                "aprovado_em": "20/10/2026",
                "regras_atuais": [
                    "Limite reduzido para até 2 ideias por pessoa (contando individual e equipe de até 4)",
                    "Exige mínimo de 6 meses de casa na data de referência (01/02/2027)",
                    "Gamificação estruturada de até 800 pontos na jornada completa",
                    "Prêmios de R$ 8k (1º), R$ 5k (2º), R$ 3k (3º) + R$ 2k cumulativos por Arena (teto de R$ 10.000,00 em folha)",
                ],
            },
            "diferenca_critica_pegadinha": "Permitia até 3 ideias por proponente, não exigia 6 meses de casa, não tinha gamificação e pagava prêmio máximo de R$ 5.000,00 por ideia. Na v2.0.0 vigente, o limite caiu para 2 ideias, exige 6 meses de casa, tem gamificação e paga R$ 8k/5k/3k por colocação + R$ 2k cumulativo por arena.",
            "citacoes": ["RG_1100 v2.0.0", "NT_2026-021 v1.0.0"],
        }

    if "FM" in c:
        return {
            "codigo": "FM_1111-001",
            "titulo": "Formulário de Solicitação de Férias",
            "versao_substituida": {
                "versao": "1.0.0",
                "fase": "Versão anterior (Revogada)",
                "aprovado_em": "10/12/2025",
                "regras_antigas": [
                    "Antecedência de 30 dias",
                    "Sem campos eletrônicos de abono pecuniário, adiantamento de 13º e trava de dias vedados",
                ],
            },
            "versao_vigente": {
                "versao": "2.0.0",
                "fase": "Vigente",
                "aprovado_em": "10/08/2026",
                "regras_atuais": [
                    "Exige ciência de 45 dias corridos de antecedência (D-45)",
                    "Inclui campos eletrônicos no Portal Raiz para abono pecuniário (até 10 dias) e adiantamento de 13º (pedido em janeiro)",
                ],
            },
            "diferenca_critica_pegadinha": "Formulário antigo com antecedência de 30 dias e sem campos eletrônicos de abono pecuniário, adiantamento do 13º salário e validação de dias vedados.",
            "citacoes": ["FM_1111-001 v2.0.0", "NG_111 v3.0.0"],
        }

    return {
        "codigo": "NG_111",
        "titulo": "Norma Geral de Férias",
        "versao_substituida": {
            "versao": "2.0.0",
            "fase": "Versão anterior (Revogada em 03/08/2026)",
            "vigencia_impressa_pegadinha": "10/12/2025 a 10/06/2027 (Armadilha: data final futura no cabeçalho, mas revogada pela Fase: Versão anterior)",
            "regras_antigas": [
                "Exigia antecedência mínima de apenas 30 dias (item 2.3)",
                "Aprovação simples do gerente sem escalada automática em 7 dias corridos",
                "Sem regra de 30% da equipe ou ressarcimento de R$ 2.500,00",
            ],
        },
        "versao_vigente": {
            "versao": "3.0.0",
            "fase": "Vigente (03/08/2026 a 03/02/2028)",
            "regras_atuais": [
                "Antecedência mínima de 45 dias corridos (D-45)",
                "Prazos em camadas (7d gestor -> 3d úteis diretor -> D-35 aviso -> D-30 assinatura -> D-20 alteração -> D-3 pagamento)",
                "Limite de 30% da equipe ausente simultaneamente",
                "Ressarcimento de até R$ 2.500,00 por cancelamento a serviço a partir de D-19",
            ],
        },
        "diferenca_critica_pegadinha": "Exigia antecedência mínima de apenas 30 dias (item 2.3) e aprovação simples do gerente. Na v3.0.0 vigente, a antecedência passou para 45 dias corridos (D-45), com prazos em camadas, limite de 30% da equipe, abono, adiantamento de 13º e ressarcimento de até R$ 2.500,00.",
        "citacoes": ["NG_111 v3.0.0", "TB_1111-001 v1.0.0"],
    }
