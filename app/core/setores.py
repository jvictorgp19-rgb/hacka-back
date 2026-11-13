"""Setores (departamentos e diretorias) da classificação BBTS: app/seed/setores.json."""

import json
from dataclasses import dataclass
from functools import lru_cache

from app.core.config import RAIZ

ARQUIVO = RAIZ / "app" / "seed" / "setores.json"


@dataclass(frozen=True)
class Setor:
    sigla: str
    nome: str
    tipo: str  # departamento | diretoria
    unidade_acervo: str  # nome da unidade equivalente nos PDFs da ACME
    siglas_acervo: tuple[str, ...]
    diretoria: str
    missao: str
    series: tuple[int, ...]
    palavras_chave: tuple[str, ...]

    @property
    def rotulo(self) -> str:
        return f"{self.sigla} ({self.nome})"


@lru_cache
def setores() -> dict[str, Setor]:
    dados = json.loads(ARQUIVO.read_text(encoding="utf-8"))["setores"]
    return {
        s["sigla"]: Setor(
            sigla=s["sigla"], nome=s["nome"], tipo=s["tipo"], unidade_acervo=s["unidadeAcervo"],
            siglas_acervo=tuple(s["siglasAcervo"]), diretoria=s["diretoria"],
            missao=s["missao"], series=tuple(s["series"]),
            palavras_chave=tuple(s["palavrasChave"]))
        for s in dados
    }


def rotulo(sigla: str) -> str:
    """'GEPEC (Gestão de Pessoas e Carreira)'. Sigla desconhecida volta como veio."""
    setor = setores().get(sigla)
    return setor.rotulo if setor else sigla


def por_sigla_do_acervo(sigla_acme: str) -> str | None:
    """Traduz a sigla impressa nos PDFs da ACME (GGC, NIN, GCO...) para o setor BBTS."""
    alvo = sigla_acme.upper()
    for setor in setores().values():
        if alvo == setor.sigla or alvo in setor.siglas_acervo:
            return setor.sigla
    return None
