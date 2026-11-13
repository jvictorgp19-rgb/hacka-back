"""Relações entre os documentos do acervo, para o espelho no Neon (app/services/persistencia.py).

Montadas uma vez, a partir do Silver já ingerido. Sem LLM, sem rede, determinístico.
Metodologia em docs/METODOLOGIA_GRAFO.md.

Relações
    substitui    versão vigente -> versão anterior do mesmo código
    vinculado_a  campo "Vinculado a"/"Referência" do cabeçalho do PDF
    referencia   código de documento encontrado no texto (menção detectada), com os itens

Regras de segurança (revisão docs/SEGURANCA_GRAFO_CODEX.md):
- O grafo completo NUNCA sai para um cliente da API: ele só vai para o banco, com o nível do
  documento de origem em cada relação.
- Só código com a gramática completa (CODIGO) vira relação; autocitação não conta.
- Nenhuma relação muda classificação, dono ou vigência de documento.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache

from app.services.acervo import Acervo, Documento, get_acervo

# Gramática fechada de código de documento. Só o que casa por inteiro vira nó.
CODIGO = re.compile(r"\b(?:NG|PX|PP|GU|FM|TB|FL|RG|NT|CTR|DV)_\d{3,4}(?:-\d{3})?\b")
MAX_CODIGOS_POR_TRECHO = 30
MAX_ITENS_POR_ARESTA = 8
MAX_ARESTAS = 5000


@dataclass
class _Aresta:
    origem: str  # id do documento de origem ("CODIGO@VERSAO")
    alvo: str  # código citado, ou id exato quando a relação é entre versões
    tipo: str
    itens: list[str] = field(default_factory=list)  # onde a evidência aparece na origem


def _id(doc: Documento) -> str:
    return f"{doc.codigo}@{doc.versao}"


def _versao_ordenavel(versao: str) -> tuple[int, ...]:
    return tuple(int(parte) for parte in versao.split("."))


class Grafo:
    def __init__(self, acervo: Acervo) -> None:
        self._acervo = acervo
        self._docs: dict[str, Documento] = {_id(d): d for d in acervo.documentos}
        self._arestas: list[_Aresta] = []
        self._montar()

    # ---------- construção (privada ao servidor) ----------
    def _montar(self) -> None:
        acervo = self._acervo
        # 1. substitui: só quando há exatamente uma versão vigente do código.
        por_codigo: dict[str, list[Documento]] = {}
        for doc in acervo.documentos:
            por_codigo.setdefault(doc.codigo, []).append(doc)
        for versoes in por_codigo.values():
            vigentes = [d for d in versoes if d.vigente]
            if len(vigentes) != 1:
                continue  # ambíguo: não inventar relação
            atual = vigentes[0]
            for antiga in versoes:
                if not antiga.vigente and \
                        _versao_ordenavel(antiga.versao) < _versao_ordenavel(atual.versao):
                    self._arestas.append(_Aresta(_id(atual), _id(antiga), "substitui",
                                                 ["cabeçalho"]))

        # 2. vinculado_a: declarado no cabeçalho do PDF.
        for doc in acervo.documentos:
            if doc.vinculado_a and CODIGO.fullmatch(doc.vinculado_a) \
                    and doc.vinculado_a != doc.codigo:
                self._arestas.append(_Aresta(_id(doc), doc.vinculado_a, "vinculado_a",
                                             ["cabeçalho"]))

        # 3. referencia: menções no texto, com o item onde aparecem (proveniência).
        mencoes: dict[tuple[str, str], _Aresta] = {}
        for chunk in acervo.chunks:
            origem = f"{chunk.codigo}@{chunk.versao}"
            if origem not in self._docs or chunk.item == "cabeçalho":
                continue
            codigos = list(dict.fromkeys(CODIGO.findall(chunk.texto)))[:MAX_CODIGOS_POR_TRECHO]
            for codigo in codigos:
                if codigo == chunk.codigo:
                    continue  # autocitação não informa nada
                aresta = mencoes.setdefault((origem, codigo), _Aresta(origem, codigo, "referencia"))
                if chunk.item not in aresta.itens and len(aresta.itens) < MAX_ITENS_POR_ARESTA:
                    aresta.itens.append(chunk.item)
        declaradas = {(a.origem, a.alvo) for a in self._arestas if a.tipo == "vinculado_a"}
        self._arestas += [a for chave, a in sorted(mencoes.items()) if chave not in declaradas]
        if len(self._arestas) > MAX_ARESTAS:
            raise RuntimeError("Grafo acima do limite de arestas.")

    def relacoes(self) -> list[dict]:
        """Grafo completo, para o espelho no banco. NUNCA devolver isto a um cliente da API."""
        return [{"origem": a.origem, "alvo": a.alvo, "tipo": a.tipo, "itens": list(a.itens),
                 "nivel": self._docs[a.origem].nivel} for a in self._arestas]


@lru_cache
def get_grafo() -> Grafo:
    return Grafo(get_acervo())
