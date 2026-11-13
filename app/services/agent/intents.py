"""Extração determinística de parâmetros da pergunta (datas, valores, tamanhos, contagens)."""

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from app.services.rag.index import normalizar

_MESES = {m: i + 1 for i, m in enumerate(
    ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto", "setembro",
     "outubro", "novembro", "dezembro"])}
_DATA_NUM = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_DATA_EXT = re.compile(r"\b(\d{1,2})o? de (" + "|".join(_MESES) + r")(?: de (\d{4}))?")
_MES_SOLTO = re.compile(r"\bem (" + "|".join(_MESES) + r")(?: de |/)?(\d{4})?")
_VALOR = re.compile(r"r\$\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?")
_VALOR_MIL = re.compile(r"\b(\d{1,4})\s*mil\b")
_EQUIPE = re.compile(r"equipe (?:de|com) (\d{1,4})|\b(\d{1,4}) (?:pessoas|empregados|colaboradores|"
                     r"funcionarios|integrantes)")
_FALTAS = re.compile(r"\b(\d{1,3}) faltas?\b|faltas?\D{0,20}?(\d{1,3})\b|faltei (\d{1,3})")
_PERIODOS = re.compile(r"\b(\d{1,2})\s*(?:,|\+|e)\s*(\d{1,2})(?:\s*(?:,|\+|e)\s*(\d{1,2}))?"
                       r"\s*dias?")
_DIAS = re.compile(r"\b(\d{1,2}) dias?\b")


@dataclass
class Parametros:
    texto: str  # normalizado: minúsculo e sem acento
    datas: list[date] = field(default_factory=list)
    mes_ano: tuple[int, int | None] | None = None
    valores: list[Decimal] = field(default_factory=list)
    equipe: int | None = None
    faltas: int | None = None
    periodos: list[int] = field(default_factory=list)
    dias: list[int] = field(default_factory=list)

    def tem(self, *termos: str) -> bool:
        return any(t in self.texto for t in termos)


def _data(dia: int, mes: int, ano: int) -> date | None:
    try:
        d = date(ano, mes, dia)
    except ValueError:
        return None
    return d if 2020 <= d.year <= 2035 else None


def extrair(mensagem: str, hoje: date | None = None) -> Parametros:
    hoje = hoje or date.today()
    q = normalizar(mensagem)
    p = Parametros(texto=q)

    for dia, mes, ano in _DATA_NUM.findall(q):
        if d := _data(int(dia), int(mes), int(ano)):
            p.datas.append(d)
    for dia, mes, ano in _DATA_EXT.findall(q):
        if d := _data(int(dia), _MESES[mes], int(ano) if ano else hoje.year):
            if not ano and d < hoje:
                d = _data(int(dia), _MESES[mes], hoje.year + 1) or d
            p.datas.append(d)
    if m := _MES_SOLTO.search(q):
        p.mes_ano = (_MESES[m.group(1)], int(m.group(2)) if m.group(2) else None)

    for inteiro, centavos in _VALOR.findall(q):
        try:
            numero = f"{inteiro.replace('.', '')}.{(centavos or '0').ljust(2, '0')}"
            p.valores.append(Decimal(numero))
        except InvalidOperation:
            continue
    if not p.valores:
        p.valores = [Decimal(n) * 1000 for n in _VALOR_MIL.findall(q)]

    if m := _EQUIPE.search(q):
        p.equipe = int(m.group(1) or m.group(2))
    if m := _FALTAS.search(q):
        p.faltas = int(next(g for g in m.groups() if g))
    if m := _PERIODOS.search(q):
        p.periodos = [int(g) for g in m.groups() if g]
    p.dias = [int(n) for n in _DIAS.findall(q)]
    return p
