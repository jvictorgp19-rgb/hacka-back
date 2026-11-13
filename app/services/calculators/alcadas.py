"""Alçadas de aprovação.

Fontes no acervo: NT_2026-021 itens 4.2 a 4.4 (protótipos de inovação) e NT_2026-018 Anexo F
(contratações). A norma-mãe NG_012 é citada, mas NÃO está no acervo: acima de R$ 120.000,00
fora do contexto de inovação, a resposta correta é abster-se.
"""

from dataclasses import dataclass
from decimal import Decimal

LIMITE_GERENTE = Decimal("18000.00")
LIMITE_DIRETOR = Decimal("120000.00")


@dataclass
class Alcada:
    valor: Decimal
    aprovador: str | None  # None = não consta nas fontes
    faixa: str
    item: str
    fontes: list[str]


def quem_aprova(valor: Decimal, contexto: str = "inovacao") -> Alcada:
    if not valor.is_finite() or valor < 0 or valor > Decimal("1e12"):
        raise ValueError("Valor inválido.")
    inovacao = contexto == "inovacao"
    fontes = ["NT_2026-021"] if inovacao else ["NT_2026-018"]
    if valor <= LIMITE_GERENTE:
        aprovador = "Gerente do NIN" if inovacao else "Gerente"
        return Alcada(valor, aprovador, "Até R$ 18.000,00",
                      "NT_2026-021 4.2" if inovacao else "NT_2026-018 Anexo F", fontes)
    if valor <= LIMITE_DIRETOR:
        aprovador = "Diretor da DIRTEC" if inovacao else "Diretor"
        return Alcada(valor, aprovador, "De R$ 18.000,01 a R$ 120.000,00",
                      "NT_2026-021 4.3" if inovacao else "NT_2026-018 Anexo F", fontes)
    if inovacao:
        return Alcada(valor, "Comitê de Alçadas", "Acima de R$ 120.000,00", "NT_2026-021 4.4",
                      fontes)
    return Alcada(valor, None, "Acima de R$ 120.000,00", "NG_012 (fora do acervo)", fontes)
