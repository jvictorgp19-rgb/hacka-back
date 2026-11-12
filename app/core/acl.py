"""Níveis de classificação e regra de acesso.

Ordem: Pública < Interna < Restrita < Sigilosa. Quem não se identifica vê só Pública.
"""

NIVEIS = ["Pública", "Interna", "Restrita", "Sigilosa"]
NIVEL_ANONIMO = "Pública"


def ordem(nivel: str) -> int:
    return NIVEIS.index(nivel)


def pode_ver(nivel_sujeito: str, nivel_recurso: str) -> bool:
    return ordem(nivel_sujeito) >= ordem(nivel_recurso)


def maior_nivel(niveis: list[str]) -> str:
    """High-water mark: o resultado herda a maior classificação das fontes usadas."""
    return max(niveis, key=ordem) if niveis else NIVEL_ANONIMO
