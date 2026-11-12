"""Calculadoras de férias. Regras da NG_111 v3.0.0 e do TB_1111-001 v1.0.0.

Código determinístico: o LLM nunca faz estas contas.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from app.services.calculators import calendario as cal

FONTES_PRAZOS = ["NG_111", "TB_1111-001", "PX_1111-001", "FM_1111-001"]
FONTES_TABELAS = ["TB_1111-001", "NG_111"]

ANTECEDENCIA_SOLICITACAO = 45  # NG_111 4.5.1
ANTECEDENCIA_AVISO = 35  # 4.5.3
ANTECEDENCIA_ASSINATURA = 30  # 4.5.4
ANTECEDENCIA_ALTERACAO = 20  # 4.9.1
ANTECEDENCIA_PAGAMENTO = 3  # 4.5.5
TETO_RESSARCIMENTO = Decimal("2500.00")  # 4.9.3

# TB_1111-001 Tabela 1: (faltas mínimas, faltas máximas, dias de férias)
TABELA_FALTAS = [(0, 5, 30), (6, 14, 24), (15, 23, 18), (24, 32, 12)]


@dataclass
class Marco:
    marco: str
    data: date
    etapa: str
    responsavel: str
    item: str
    observacao: str = ""


@dataclass
class PrazosFerias:
    inicio: date
    inicio_valido: bool
    motivo_invalido: str
    marcos: list[Marco] = field(default_factory=list)
    fontes: list[str] = field(default_factory=lambda: list(FONTES_PRAZOS))


def validar_inicio(inicio: date) -> tuple[bool, str]:
    """NG_111 4.3.2: dia útil, fora dos 2 dias úteis que antecedem feriado ou DSR (domingo)."""
    if not cal.dia_util(inicio):
        nome = cal.feriado(inicio) or cal.nome_dia(inicio)
        return False, f"{cal.br(inicio)} não é dia útil ({nome})."
    for delta in range(1, 8):
        descanso = inicio + timedelta(days=delta)
        nome = cal.feriado(descanso) or ("domingo" if descanso.weekday() == 6 else None)
        if nome is None:
            continue
        vespera1 = cal.dia_util_anterior(descanso)
        vespera2 = cal.dia_util_anterior(vespera1)
        if inicio in (vespera1, vespera2):
            return False, (
                f"{cal.br(inicio)} ({cal.nome_dia(inicio)}) está nos 2 dias úteis que antecedem "
                f"{nome} em {cal.br(descanso)}."
            )
    return True, ""


def calcular_prazos_ferias(inicio: date) -> PrazosFerias:
    valido, motivo = validar_inicio(inicio)

    def d(n: int) -> date:
        return inicio - timedelta(days=n)

    pagamento_bruto = d(ANTECEDENCIA_PAGAMENTO)
    pagamento = cal.antecipar_para_dia_util(pagamento_bruto)
    obs_pag = ""
    if pagamento != pagamento_bruto:
        causa = cal.feriado(pagamento_bruto) or cal.nome_dia(pagamento_bruto)
        obs_pag = (
            f"D-3 cai em {cal.br(pagamento_bruto)} ({causa}); antecipado para o dia útil anterior."
        )
    marcos = [
        Marco("D-45", d(45), "Solicitação formal no Portal Raiz (FM_1111-001)", "Empregado",
              "NG_111 4.5.1"),
        Marco("D-35", d(35), "Emissão do aviso de férias", "GGC", "NG_111 4.5.3"),
        Marco("D-30", d(30), "Assinatura do aviso (até 5 dias úteis do recebimento)",
              "Empregado", "NG_111 4.5.4"),
        Marco("D-20", d(20), "Último dia para alteração ou cancelamento pelo empregado",
              "Empregado e gestor", "NG_111 4.9.1"),
        Marco("D-19", d(19), "Daqui em diante, alteração só por necessidade de serviço",
              "Diretor da área", "NG_111 4.9.2"),
        Marco("D-3", pagamento, "Pagamento das férias", "GFI", "NG_111 4.5.5", obs_pag),
    ]
    return PrazosFerias(inicio, valido, motivo, marcos)


def dias_por_faltas(faltas: int) -> int:
    """TB_1111-001 Tabela 1. Mais de 32 faltas: perda do direito (0 dias)."""
    if faltas < 0:
        raise ValueError("Número de faltas não pode ser negativo.")
    for minimo, maximo, dias in TABELA_FALTAS:
        if minimo <= faltas <= maximo:
            return dias
    return 0


def limite_ausencia(tamanho_equipe: int) -> int:
    """NG_111 4.6.3: 30% da equipe, arredondado para baixo, mínimo de 1."""
    if tamanho_equipe < 1:
        raise ValueError("A equipe precisa ter ao menos 1 empregado.")
    return max(1, tamanho_equipe * 30 // 100)


def validar_fracionamento(periodos: list[int], direito: int = 30) -> tuple[bool, str]:
    """NG_111 4.4: até 3 períodos; um com 14 dias ou mais; os demais com 5 ou mais."""
    if not periodos or len(periodos) > 3:
        return False, "As férias podem ser divididas em até 3 períodos (NG_111 4.4.1)."
    if sum(periodos) > direito:
        return False, f"A soma ({sum(periodos)} dias) passa do direito de {direito} dias."
    if max(periodos) < 14:
        return False, "Um dos períodos deve ter no mínimo 14 dias corridos (NG_111 4.4.2)."
    menores = sorted(periodos)[:-1]
    if any(p < 5 for p in menores):
        return False, "Os demais períodos devem ter no mínimo 5 dias corridos (NG_111 4.4.2)."
    return True, "Fracionamento válido (NG_111 4.4)."


def ressarcimento_cancelamento(despesa: Decimal) -> Decimal:
    """NG_111 4.9.3: ressarcimento limitado a R$ 2.500,00 por evento."""
    return min(max(despesa, Decimal(0)), TETO_RESSARCIMENTO)
