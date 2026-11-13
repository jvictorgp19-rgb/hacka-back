"""Cadastro de personas no servidor. O cliente informa só o id; setor, cargo e habilitação
saem daqui.

- `setor`: departamento da pessoa (app/seed/setores.json). Dá a necessidade de conhecer.
- `nivel`: habilitação. "Sigilosa" é o credenciamento para informação sigilosa dos setores da
  pessoa (LAI art. 25, § 1º). "Interna" vê só o que é interno.
- `senioridade`: decide quem precisa de aprovação e quem pode aprovar. Trabalho de júnior
  sempre passa por outra pessoa (segregação de funções).

Os ids das seis primeiras espelham PERSONAS_NOMINAIS do front (src/features/identity/personas.ts).
"""

from dataclasses import dataclass
from typing import Literal

Senioridade = Literal["junior", "pleno", "senior", "gestor", "diretor"]
APROVADORES: tuple[str, ...] = ("senior", "gestor", "diretor")


@dataclass(frozen=True)
class Persona:
    id: str
    nome: str
    papel: str
    unidade: str
    nivel: str
    # Domínios (setores donos) que a persona administra como curadora.
    cura_dominios: tuple[str, ...] = ()
    setor: str = ""
    senioridade: Senioridade = "pleno"

    @property
    def aprova(self) -> bool:
        """Pode aprovar trabalho de outras pessoas do mesmo setor."""
        return self.senioridade in APROVADORES

    @property
    def governanca(self) -> bool:
        """Vê a auditoria do acervo e os painéis de uso: curadoria ou diretoria."""
        return bool(self.cura_dominios) or self.senioridade == "diretor"


PERSONAS: dict[str, Persona] = {
    p.id: p
    for p in [
        Persona("ana", "Ana", "Analista / Empregada", "Operações / Portal Raiz", "Interna",
                setor="GOP", senioridade="pleno"),
        Persona("carlos", "Carlos", "Gestor - Equipe de 9", "Gerência Operacional", "Interna",
                setor="GOP", senioridade="gestor"),
        Persona("marina", "Marina", "Proponente - Ideias em Campo", "Operações de Campo",
                "Interna", setor="GOC", senioridade="pleno"),
        Persona("rafael", "Rafael", "Fiscal Técnico - GOC", "GOC", "Sigilosa",
                setor="GOC", senioridade="senior"),
        Persona("diretora_diraf", "Diretora da DIRAF", "Executiva", "DIRAF", "Sigilosa",
                setor="DIRAF", senioridade="diretor"),
        Persona("curadora_ggc", "Curadora da GEPEC", "Dona do Domínio", "GEPEC (GGC no acervo)",
                "Sigilosa", ("GEPEC",), setor="GEPEC", senioridade="gestor"),
        Persona("bruno", "Bruno", "Desenvolvedor Júnior", "GEINOV", "Interna",
                setor="GEINOV", senioridade="junior"),
        Persona("helena", "Helena", "Tech Lead", "GEINOV", "Sigilosa", ("GEINOV",),
                setor="GEINOV", senioridade="gestor"),
        Persona("fernanda", "Fernanda", "Analista Financeira", "GFI", "Sigilosa",
                setor="GFI", senioridade="pleno"),
        Persona("sergio", "Sérgio", "Analista de Contratos", "GESUC", "Sigilosa",
                setor="GESUC", senioridade="pleno"),
    ]
}
