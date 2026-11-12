"""Busca lexical (BM25) com filtro de permissão ANTES do ranking.

Cada partição (nível do sujeito, com ou sem versões substituídas) tem o próprio índice, montado
só com os trechos que aquele nível pode ver. Um trecho proibido nunca é pontuado nem devolvido.
"""

import re
import unicodedata
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from app.core.acl import NIVEIS, ordem
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
        self._particoes: dict[tuple[str, bool], _Particao] = {}
        self._restritas: dict[str, _Particao] = {}

    def _particao(self, nivel: str, substituidos: bool) -> _Particao:
        chave = (nivel, substituidos)
        if chave not in self._particoes:
            self._particoes[chave] = _Particao(self._acervo.chunks_visiveis(nivel, substituidos))
        return self._particoes[chave]

    def buscar(self, consulta: str, nivel: str, k: int = 4, tema: str | None = None,
               incluir_substituidos: bool = False) -> list[Trecho]:
        return self._particao(nivel, incluir_substituidos).buscar(consulta, k, tema)

    def dominio_bloqueado(self, consulta: str, nivel: str, melhor_score: float) -> str | None:
        """Diz qual área dona tem conteúdo RESTRITO que responderia melhor à pergunta.

        Só olha o degrau imediatamente acima do sujeito e nunca passa de Restrita: documento
        Sigiloso não tem a existência revelada. Devolve só a sigla da área, nunca o conteúdo.
        """
        degrau = ordem(nivel) + 1
        if degrau > ordem("Restrita"):
            return None
        alvo = NIVEIS[degrau]
        if alvo not in self._restritas:
            self._restritas[alvo] = _Particao(
                [c for c in self._acervo.chunks if c.nivel == alvo and c.vigente]
            )
        achados = self._restritas[alvo].buscar(consulta, 1, None)
        if achados and achados[0].score > max(melhor_score * 1.15, SCORE_BLOQUEIO):
            return achados[0].chunk.dominio
        return None
