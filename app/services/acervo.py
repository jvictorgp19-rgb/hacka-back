"""Catálogo do acervo e PONTO ÚNICO de autorização.

Todo serviço (chat, calculadoras, radar, relatórios, catálogo) pergunta aqui se o sujeito
pode usar um documento. Não existe outro caminho para chegar a um fato ou trecho.
"""

import json
from dataclasses import dataclass
from functools import lru_cache

from app.core.acl import Acesso, maior_nivel, pode_ver
from app.core.config import RAIZ
from app.core.setores import rotulo, setores
from app.services.ingest.pipeline import MANIFESTO, Chunk, carregar_silver

SEED = RAIZ / "app" / "seed" / "acervo_estruturado.json"

# Setor dono -> rótulo. Vem de app/seed/setores.json (classificação BBTS).
NOMES_DOMINIO = {sigla: rotulo(sigla) for sigla in setores()}
# Hierarquia documental: a norma geral prevalece sobre procedimento, que prevalece sobre apoio.
PESO_TIPO = {"NG": 1.15, "RG": 1.1, "CTR": 1.1, "PX": 1.05}


@dataclass(frozen=True)
class Documento:
    codigo: str
    versao: str
    titulo: str
    tema: str
    dominio: str
    nivel: str
    vigente: bool
    fase: str
    arquivo: str | None
    data_referencia: str | None
    vinculado_a: str | None
    # Setores com necessidade de conhecer (docs/CLASSIFICACAO_BBTS.md). Em documento Interno,
    # só informa o dono: a empresa toda vê.
    setores: tuple[str, ...] = ()
    motivo: str = ""

    @property
    def tipo(self) -> str:
        return self.codigo.split("_")[0]

    def citacao(self) -> dict:
        return {"codigo": self.codigo, "titulo": self.titulo, "versao": f"v{self.versao}",
                "status": self.fase}


class Acervo:
    def __init__(self) -> None:
        self.seed: dict = json.loads(SEED.read_text(encoding="utf-8"))
        manifesto = json.loads(MANIFESTO.read_text(encoding="utf-8"))["documentos"]
        silver = carregar_silver()
        self.quarentena: list[dict] = silver["quarentena"]
        self.cabecalhos: dict[str, dict] = silver["cabecalhos"]
        self.chunks: list[Chunk] = [Chunk(**c) for c in silver["chunks"]]
        self.documentos: list[Documento] = []
        for m in manifesto:
            chave = f"{m['codigo']}@{m['versao']}"
            cab = silver["cabecalhos"].get(chave)
            if m["arquivo"] is not None and cab is None:
                continue  # em quarentena: não entra no catálogo
            cab = cab or {}
            self.documentos.append(Documento(
                codigo=m["codigo"],
                versao=m["versao"],
                titulo=m.get("titulo") or cab.get("titulo") or m["codigo"],
                tema=m["tema"],
                dominio=m["dominio"],
                nivel=cab.get("nivel", m["classificacao"]),
                vigente=cab.get("vigente", m["vigente"]),
                fase=cab.get("fase") or ("Vigente" if m["vigente"] else "Versão anterior"),
                arquivo=m["arquivo"],
                data_referencia=cab.get("data_referencia"),
                vinculado_a=cab.get("vinculado_a"),
                setores=tuple(m.get("setores") or [m["dominio"]]),
                motivo=m.get("motivo", ""),
            ))
        self._por_versao = {(d.codigo, d.versao): d for d in self.documentos}

    # ---------- consultas ----------
    @staticmethod
    def pode(acesso: Acesso, doc: Documento) -> bool:
        return pode_ver(acesso, doc.nivel, doc.setores)

    def documento(self, codigo: str, versao: str) -> Documento | None:
        return self._por_versao.get((codigo, versao))

    def vigente(self, codigo: str) -> Documento | None:
        return next((d for d in self.documentos if d.codigo == codigo and d.vigente), None)

    def visiveis(self, acesso: Acesso, tema: str | None = None,
                 vigentes: bool | None = True) -> list[Documento]:
        return [
            d for d in self.documentos
            if self.pode(acesso, d)
            and (tema in (None, "todos") or d.tema == tema)
            and (vigentes is None or d.vigente == vigentes)
        ]

    def autorizado(self, codigos: list[str], acesso: Acesso) -> bool:
        """Verdadeiro só se o sujeito pode ver TODAS as fontes (vigentes) informadas."""
        for codigo in codigos:
            doc = self.vigente(codigo)
            if doc is None or not self.pode(acesso, doc):
                return False
        return True

    def nivel_das_fontes(self, codigos: list[str]) -> str:
        docs = [self.vigente(c) for c in codigos]
        return maior_nivel([d.nivel for d in docs if d])

    def citacoes(self, codigos: list[str], acesso: Acesso) -> list[dict]:
        """Citações só de documentos vigentes que o sujeito pode ver, sem repetição."""
        vistas, saida = set(), []
        for codigo in codigos:
            doc = self.vigente(codigo)
            if doc and self.pode(acesso, doc) and codigo not in vistas:
                vistas.add(codigo)
                saida.append(doc.citacao())
        return saida

    def _chunk_visivel(self, acesso: Acesso, chunk: Chunk) -> bool:
        doc = self._por_versao.get((chunk.codigo, chunk.versao))
        return doc is not None and self.pode(acesso, doc)

    def chunks_visiveis(self, acesso: Acesso, incluir_substituidos: bool = False) -> list[Chunk]:
        return [c for c in self.chunks
                if self._chunk_visivel(acesso, c) and (c.vigente or incluir_substituidos)]

    def chunks_ocultos(self, acesso: Acesso) -> list[Chunk]:
        """Trechos vigentes que o sujeito NÃO pode ver. Servem só para apontar o setor dono."""
        return [c for c in self.chunks if c.vigente and not self._chunk_visivel(acesso, c)]


@lru_cache
def get_acervo() -> Acervo:
    return Acervo()
