"""Prazos e valores do CTR_2026-012 (locação de coworking), cláusula por cláusula."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.services.calculators import calendario as cal

CODIGO = "CTR_2026-012"
FONTES = ["CTR_2026-012", "NT_2026-018"]

INICIO = date(2026, 11, 30)  # Cláusula 2ª
FIM = date(2027, 4, 29)
ALUGUEL = Decimal("3650.00")  # Cláusula 7ª
VALOR_GLOBAL = Decimal("18250.00")
PRAZO_MAXIMO_MESES = 24

VISTORIA_ATE = INICIO - timedelta(days=5)  # Cláusula 6ª -> 25/11/2026
PRORROGACAO_ATE = FIM - timedelta(days=30)  # Cláusula 3ª -> 30/03/2027
ULTIMO_DIA_COM_MULTA = INICIO + timedelta(days=89)  # 90º dia -> 27/02/2027 (Cláusula 13ª)
ADITIVO_MAXIMO = VALOR_GLOBAL * Decimal("0.20")  # Cláusula 3ª -> R$ 3.650,00
MULTA_INEXECUCAO = VALOR_GLOBAL * Decimal("0.05")  # Cláusula 15ª -> R$ 912,50
# Anexo, item 11: 1/30 do aluguel por dia com interrupção de internet superior a 4 horas.
GLOSA_DIARIA = (ALUGUEL / 30).quantize(Decimal("0.01"), ROUND_HALF_UP)  # R$ 121,67
AVISO_RESCISAO_DIAS = 30


@dataclass
class Rescisao:
    data: date
    dia_de_vigencia: int
    multa: Decimal
    explicacao: str


def dia_de_vigencia(d: date) -> int:
    return (d - INICIO).days + 1


def multa_rescisao(data_rescisao: date) -> Rescisao:
    """Cláusula 13ª: até o 90º dia, multa de um aluguel; a partir do 91º, sem multa."""
    if not INICIO <= data_rescisao <= FIM:
        raise ValueError(f"Data fora da vigência ({cal.br(INICIO)} a {cal.br(FIM)}).")
    dia = dia_de_vigencia(data_rescisao)
    if dia <= 90:
        return Rescisao(data_rescisao, dia, ALUGUEL,
                        f"{cal.br(data_rescisao)} é o {dia}º dia de vigência: até o 90º dia "
                        f"({cal.br(ULTIMO_DIA_COM_MULTA)}) a multa é de um aluguel mensal.")
    return Rescisao(data_rescisao, dia, Decimal("0.00"),
                    f"{cal.br(data_rescisao)} é o {dia}º dia de vigência: a partir do 91º dia "
                    f"({cal.br(ULTIMO_DIA_COM_MULTA + timedelta(days=1))}) não há multa.")


def glosa_internet(dias_com_queda: int) -> Decimal:
    if dias_com_queda < 0 or dias_com_queda > 31:
        raise ValueError("Informe de 0 a 31 dias.")
    return GLOSA_DIARIA * dias_com_queda


def pagamento_do_mes(ano: int, mes: int) -> date:
    """Cláusula 10ª: até o dia 8 do mês de uso; se não for dia útil, dia útil seguinte."""
    return cal.postergar_para_dia_util(date(ano, mes, 8))
