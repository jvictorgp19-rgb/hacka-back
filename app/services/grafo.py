"""Grafo do acervo: documentos como nós, relações entre eles como arestas.

Montado uma vez, a partir do Silver já ingerido. Sem LLM, sem rede, determinístico.
Metodologia completa em docs/METODOLOGIA_GRAFO.md.

Nós
    documento    uma versão de um documento do acervo (id "CODIGO@VERSAO")
    referencia   código citado que não se resolve na visão de quem consulta
    dominio      área dona (GGC, NIN, GCO)

Arestas
    substitui    versão vigente -> versão anterior do mesmo código
    vinculado_a  campo "Vinculado a"/"Referência" do cabeçalho do PDF
    referencia   código de documento encontrado no texto (menção detectada), com os itens
    pertence_a   documento -> área dona

Regras de segurança (revisão docs/SEGURANCA_GRAFO_CODEX.md):
- O grafo NÃO concede acesso. Cada pessoa recebe uma PROJEÇÃO: só nós de documentos que o
  nível dela pode ver e só arestas cuja evidência saiu de um documento visível.
- Alvo que não existe e alvo que existe mas é invisível ficam IGUAIS: um nó "referencia" neutro,
  só com o código que a pessoa já leu no documento de origem.
- Áreas donas, contagens e ids saem da projeção, nunca do grafo completo.
- Nenhuma aresta muda classificação, dono ou vigência de documento.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache

from app.core.acl import Acesso
from app.schemas.api import GrafoAresta, GrafoNo, GrafoResponse
from app.services.acervo import NOMES_DOMINIO, Acervo, Documento, get_acervo

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

    # ---------- construção (grafo completo, privado ao servidor) ----------
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

    # ---------- projeção (o que cada perfil de acesso enxerga) ----------
    def projetar(self, acesso: Acesso, tema: str | None = None) -> GrafoResponse:
        visiveis = {i: d for i, d in self._docs.items()
                    if Acervo.pode(acesso, d) and (tema is None or d.tema == tema)}
        # Para resolver um código citado, vale a versão vigente visível (em qualquer tema).
        vigente_visivel = {d.codigo: i for i, d in self._docs.items()
                           if d.vigente and Acervo.pode(acesso, d)}

        nos: dict[str, GrafoNo] = {}
        arestas: list[GrafoAresta] = []

        def no_documento(ident: str) -> str:
            d = self._docs[ident]
            nos.setdefault(ident, GrafoNo(
                id=ident, tipo="documento", rotulo=f"{d.codigo} v{d.versao}", codigo=d.codigo,
                versao=d.versao, titulo=d.titulo, categoria=d.tipo, tema=d.tema,
                dominio=d.dominio, nivel=d.nivel, vigente=d.vigente))
            return ident

        for ident in sorted(visiveis):
            no_documento(ident)
            dominio = visiveis[ident].dominio
            alvo = f"dominio:{dominio}"
            nos.setdefault(alvo, GrafoNo(id=alvo, tipo="dominio",
                                         rotulo=NOMES_DOMINIO.get(dominio, dominio)))
            arestas.append(GrafoAresta(origem=ident, destino=alvo, tipo="pertence_a", itens=[]))

        for a in self._arestas:
            if a.origem not in visiveis:
                continue  # evidência de documento invisível nunca aparece
            if a.tipo == "substitui":
                if a.alvo not in visiveis:
                    continue
                destino = a.alvo
            elif a.alvo in vigente_visivel:
                destino = no_documento(vigente_visivel[a.alvo])
            else:
                # Inexistente ou invisível: o mesmo nó neutro, só com o código já lido na origem.
                destino = f"ref:{a.alvo}"
                nos.setdefault(destino, GrafoNo(id=destino, tipo="referencia", rotulo=a.alvo,
                                                codigo=a.alvo))
            arestas.append(GrafoAresta(origem=a.origem, destino=destino, tipo=a.tipo,
                                       itens=list(a.itens)))

        return GrafoResponse(nos=list(nos.values()), arestas=arestas)

    # ---------- consultas pontuais (o chat/RAG não usa o grafo) ----------
    def relacoes(self) -> list[dict]:
        """Grafo completo, para o espelho no banco. NUNCA devolver isto a um cliente da API."""
        return [{"origem": a.origem, "alvo": a.alvo, "tipo": a.tipo, "itens": list(a.itens),
                 "nivel": self._docs[a.origem].nivel} for a in self._arestas]

    def versao_anterior(self, codigo: str, acesso: Acesso) -> tuple[Documento, Documento] | None:
        """(vigente, anterior) quando as DUAS versões são visíveis para o perfil de acesso."""
        for a in self._arestas:
            if a.tipo != "substitui":
                continue
            atual, antiga = self._docs[a.origem], self._docs[a.alvo]
            if atual.codigo == codigo and Acervo.pode(acesso, atual) \
                    and Acervo.pode(acesso, antiga):
                return atual, antiga
        return None


def para_mermaid(grafo: GrafoResponse) -> str:
    """Diagrama Mermaid com ids técnicos (n1, n2...) e rótulos higienizados."""
    def limpo(texto: str) -> str:
        return re.sub(r"[^\w .@()áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ/-]", "", texto)[:60]

    ids = {no.id: f"n{i}" for i, no in enumerate(grafo.nos, 1)}
    linhas = ["flowchart LR"]
    for no in grafo.nos:
        rotulo = limpo(no.rotulo)
        if no.tipo == "documento":
            forma = f'["{rotulo}"]' if no.vigente else f'[/"{rotulo} (anterior)"/]'
        elif no.tipo == "dominio":
            forma = f'(["{rotulo}"])'
        else:
            forma = f'{{{{"{rotulo} (não resolvida)"}}}}'
        linhas.append(f"    {ids[no.id]}{forma}")
    setas = {"substitui": "==>", "vinculado_a": "-->", "referencia": "-.->", "pertence_a": "---"}
    for a in grafo.arestas:
        if a.tipo == "pertence_a":
            linhas.append(f"    {ids[a.origem]} --- {ids[a.destino]}")
        else:
            linhas.append(f"    {ids[a.origem]} {setas[a.tipo]}|{a.tipo}| {ids[a.destino]}")
    return "\n".join(linhas)


@lru_cache
def get_grafo() -> Grafo:
    return Grafo(get_acervo())
