"""Cadastro de personas no servidor. O cliente informa só o id; papel e nível saem daqui.

Os ids espelham PERSONAS_NOMINAIS do front (src/lib/api.ts).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Persona:
    id: str
    nome: str
    papel: str
    unidade: str
    nivel: str
    # Domínios (áreas donas) que a persona administra como curadora.
    cura_dominios: tuple[str, ...] = ()


PERSONAS: dict[str, Persona] = {
    p.id: p
    for p in [
        Persona("ana", "Ana", "Analista / Empregada", "Operações", "Interna"),
        Persona("carlos", "Carlos", "Gestor - Equipe de 9", "Gerência Operacional", "Interna"),
        Persona("marina", "Marina", "Proponente - Ideias em Campo", "Operações de Campo", "Interna"),
        Persona("rafael", "Rafael", "Fiscal Técnico - GOC", "GOC", "Restrita"),
        Persona("diretora_diraf", "Diretora da DIRAF", "Executiva", "DIRAF", "Sigilosa"),
        Persona("curadora_ggc", "Curadora da GGC", "Dona do Domínio", "GGC", "Sigilosa", ("GGC",)),
    ]
}
