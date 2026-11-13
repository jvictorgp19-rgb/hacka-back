"""Calendário: feriados nacionais e dias úteis.

Dia útil (NG_111 item 3.7): dia que não seja sábado, domingo ou feriado.
A sede fictícia (Vale Azul) não tem feriados locais no acervo; usamos só os nacionais.
"""

from datetime import date, timedelta
from functools import lru_cache


def _pascoa(ano: int) -> date:
    """Algoritmo de Meeus/Jones/Butcher."""
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    mes = (h + m - 7 * n + 114) // 31
    dia = (h + m - 7 * n + 114) % 31 + 1
    return date(ano, mes, dia)


@lru_cache(maxsize=64)
def feriados(ano: int) -> dict[date, str]:
    fixos = {
        (1, 1): "Confraternização Universal",
        (4, 21): "Tiradentes",
        (5, 1): "Dia do Trabalhador",
        (9, 7): "Independência",
        (10, 12): "Nossa Senhora Aparecida",
        (11, 2): "Finados",
        (11, 15): "Proclamação da República",
        (11, 20): "Consciência Negra",
        (12, 25): "Natal",
    }
    resultado = {date(ano, m, d): nome for (m, d), nome in fixos.items()}
    resultado[_pascoa(ano) - timedelta(days=2)] = "Sexta-feira Santa"
    return resultado


def feriado(d: date) -> str | None:
    return feriados(d.year).get(d)


def dia_util(d: date) -> bool:
    return d.weekday() < 5 and feriado(d) is None


def dia_util_anterior(d: date) -> date:
    """Último dia útil estritamente antes de d."""
    d -= timedelta(days=1)
    while not dia_util(d):
        d -= timedelta(days=1)
    return d


def dia_util_seguinte(d: date) -> date:
    d += timedelta(days=1)
    while not dia_util(d):
        d += timedelta(days=1)
    return d


def antecipar_para_dia_util(d: date) -> date:
    return d if dia_util(d) else dia_util_anterior(d)


def postergar_para_dia_util(d: date) -> date:
    return d if dia_util(d) else dia_util_seguinte(d)


def somar_dias_uteis(d: date, n: int) -> date:
    for _ in range(n):
        d = dia_util_seguinte(d)
    return d


DIAS_SEMANA = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira",
               "sábado", "domingo"]


def nome_dia(d: date) -> str:
    return DIAS_SEMANA[d.weekday()]


def br(d: date) -> str:
    return d.strftime("%d/%m/%Y")
