"""Classificação e regra de acesso.

A classificação segue docs/CLASSIFICACAO_BBTS.md:
- **Interna**: documento que orienta qualquer empregado. Toda pessoa identificada vê.
- **Sigilosa**: documento do departamento. Traz dados financeiros, comerciais, de terceiros ou
  pessoais, ou é uma versão obsoleta. Só vê quem cumpre DUAS condições (LAI art. 25, § 1º):
  1. necessidade de conhecer: o setor da pessoa está na lista de setores do documento;
  2. credenciamento: a pessoa tem habilitação Sigilosa.

Pública e Restrita continuam na escala, para documentos de fora do acervo:
- Pública: qualquer um, inclusive quem não se identificou.
- Restrita: setor listado, sem exigir credenciamento.

Ordem da escala: Pública < Interna < Restrita < Sigilosa.
"""

from collections.abc import Iterable
from dataclasses import dataclass

NIVEIS = ["Pública", "Interna", "Restrita", "Sigilosa"]
NIVEL_ANONIMO = "Pública"


@dataclass(frozen=True)
class Acesso:
    """O que pesa na decisão de acesso: setor (necessidade de conhecer) e credenciamento.

    É imutável e comparável: serve de chave para os caches por perfil de acesso (busca, grafo).
    """

    setor: str | None = None  # None: quem chama não se identificou
    credenciado: bool = False  # habilitação para informação Sigilosa

    @property
    def identificado(self) -> bool:
        return self.setor is not None


ACESSO_ANONIMO = Acesso()


def ordem(nivel: str) -> int:
    return NIVEIS.index(nivel)


def pode_ver(acesso: Acesso, nivel: str, setores: Iterable[str] = ()) -> bool:
    """Decide se quem tem `acesso` pode ver um recurso de `nivel` com a lista `setores`."""
    if nivel == "Pública":
        return True
    if not acesso.identificado:
        return False
    if nivel == "Interna":
        return True
    if acesso.setor not in set(setores):
        return False
    return nivel == "Restrita" or acesso.credenciado


def maior_nivel(niveis: list[str]) -> str:
    """High-water mark: o resultado herda a maior classificação das fontes usadas."""
    return max(niveis, key=ordem) if niveis else NIVEL_ANONIMO
