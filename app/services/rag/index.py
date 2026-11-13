"""Busca lexical (BM25) com filtro de permissão ANTES do ranking.

Cada partição (perfil de acesso do sujeito: setor e credenciamento, com ou sem versões
substituídas) tem o próprio índice, montado só com os trechos que aquele perfil pode ver. Um trecho
proibido nunca é pontuado nem devolvido.
"""

import re
import unicodedata
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from app.core.acl import Acesso
from app.services.acervo import PESO_TIPO, Acervo
from app.services.ingest.pipeline import Chunk

_STOP = set(
    "a o e de da do das dos em no na nos nas um uma para por com que se ao aos as os ou "
    "como qual quais quando quem onde eu me meu minha ser sao foi tem ter ha mais ate "
    "isso esse essa este esta the sobre entre pode posso preciso quero".split()
)
SCORE_BLOQUEIO = 3.0
COBERTURA_MINIMA = 0.5
_TOKEN = re.compile(r"[a-z]+_[\d-]+|\d+(?:[.,]\d+)*|[a-z]{2,}")


def normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")


def tokenizar(texto: str) -> list[str]:
    tokens = []
    for t in _TOKEN.findall(normalizar(texto)):
        if t in _STOP:
            continue
        # Plural simples: "ferias" e "feria", "ideias" e "ideia" caem no mesmo radical.
        tokens.append(t[:-1] if len(t) > 4 and t.endswith("s") and "_" not in t else t)
    return tokens


@dataclass
class Trecho:
    chunk: Chunk
    score: float


class _Particao:
    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        corpus = [tokenizar(f"{c.codigo} {c.texto}") for c in chunks]
        self.vocabulario = [set(tokens) for tokens in corpus]
        self.bm25 = BM25Okapi(corpus) if chunks else None

    def buscar(self, consulta: str, k: int, tema: str | None) -> list[Trecho]:
        tokens = tokenizar(consulta)
        if not self.bm25 or not tokens:
            return []
        consulta_norm = normalizar(consulta)
        achados = []
        termos = set(tokens)
        scores = self.bm25.get_scores(tokens)
        for chunk, vocabulario, score in zip(self.chunks, self.vocabulario, scores, strict=True):
            # Relevância mínima: o trecho precisa conter metade dos termos da pergunta, ou ao
            # menos 2 deles (perguntas longas). Sem isso, uma palavra solta ("melhor",
            # "completo") puxaria um trecho sem relação.
            comuns = len(termos & vocabulario)
            if score <= 0 or (comuns < 2 and comuns / len(termos) < COBERTURA_MINIMA):
                continue
            score *= PESO_TIPO.get(chunk.codigo.split("_")[0], 1.0)
            if tema and chunk.tema == tema:
                score *= 1.1
            if chunk.codigo.lower() in consulta_norm:
                score *= 1.5
            achados.append(Trecho(chunk, float(score)))
        achados.sort(key=lambda t: t.score, reverse=True)
        return achados[:k]


class Indice:
    def __init__(self, acervo: Acervo) -> None:
        self._acervo = acervo
        self._particoes: dict[tuple[Acesso, bool], _Particao] = {}
        self._ocultas: dict[Acesso, _Particao] = {}

    def _particao(self, acesso: Acesso, substituidos: bool) -> _Particao:
        chave = (acesso, substituidos)
        if chave not in self._particoes:
            self._particoes[chave] = _Particao(self._acervo.chunks_visiveis(acesso, substituidos))
        return self._particoes[chave]

    def buscar(self, consulta: str, acesso: Acesso, k: int = 4, tema: str | None = None,
               incluir_substituidos: bool = False) -> list[Trecho]:
        return self._particao(acesso, incluir_substituidos).buscar(consulta, k, tema)

    def dominio_bloqueado(self, consulta: str, acesso: Acesso, melhor_score: float) -> str | None:
        """Diz qual setor dono tem conteúdo FORA do alcance do sujeito que responderia melhor.

        Devolve só a sigla do setor, nunca o código, o título ou o conteúdo do documento. Quem não
        se identificou não recebe nem isso.
        """
        if not acesso.identificado:
            return None
        if acesso not in self._ocultas:
            self._ocultas[acesso] = _Particao(self._acervo.chunks_ocultos(acesso))
        achados = self._ocultas[acesso].buscar(consulta, 1, None)
        if achados and achados[0].score > max(melhor_score * 1.15, SCORE_BLOQUEIO):
            return achados[0].chunk.dominio
        return None
