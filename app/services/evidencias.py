"""Evidências curadas (fatos) e citações no formato do hacka-front.

Os fatos vêm de app/seed/evidencias.json: cada um cita um trecho conferido no acervo, com página
achada no PDF. A área é a sigla BBTS do setor dono do documento.

Regra de acesso: o fato só sai para quem pode ver a versão do documento citado. O link do PDF
aponta para GET /documents/{id}/file, que confere o acesso de novo.
"""

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from app.core.acl import Acesso
from app.services.acervo import get_acervo
from app.services.ingest.pipeline import BRONZE, Chunk

SEED = Path(__file__).resolve().parents[1] / "seed" / "evidencias.json"
MAX_TRECHO = 400
MIN_PALAVRAS_EM_COMUM = 2
_PALAVRA = re.compile(r"[a-z0-9]{3,}")
_VAZIAS = set("para com que dos das nos nas uma por sao ate mais pode deve qual quais quando "
              "como ser tem esta este essa esse sobre entre apos antes".split())


@dataclass(frozen=True)
class Links:
    """Base pública da API. O PDF sai da própria API, com ACL (GET /documents/{id}/file)."""
    base: str

    def arquivo(self, codigo: str, versao: str) -> str | None:
        doc = get_acervo().documento(codigo, versao)
        if doc is None or not doc.arquivo:
            return None
        return f"{self.base.rstrip('/')}/documents/{quote(documento_id(codigo, versao))}/file"


@lru_cache
def _seed() -> dict:
    return json.loads(SEED.read_text(encoding="utf-8"))


def documento_id(codigo: str, versao: str) -> str:
    return f"{codigo}@{versao}"


def _compacto(texto: str) -> str:
    return "".join(c for c in _normal(texto) if c.isalnum())


@lru_cache(maxsize=32)
def _paginas_do_pdf(arquivo: str) -> tuple[str, ...]:
    from pypdf import PdfReader

    caminho = (BRONZE / arquivo).resolve()
    if BRONZE.resolve() not in caminho.parents:
        return ()
    try:
        return tuple(_compacto(p.extract_text() or "") for p in PdfReader(caminho).pages)
    except Exception:  # noqa: BLE001 - PDF ilegível: a citação sai sem página
        return ()


def pagina(codigo: str, versao: str, trecho: str) -> int | None:
    """Página do PDF em que o trecho aparece (ou None)."""
    doc = get_acervo().documento(codigo, versao)
    if doc is None or not doc.arquivo:
        return None
    paginas = _paginas_do_pdf(doc.arquivo)
    alvo = _compacto(trecho)
    for tamanho in (80, 50, 30):
        pedaco = alvo[:tamanho]
        if len(pedaco) < 20:
            break
        for numero, texto in enumerate(paginas, start=1):
            if pedaco in texto:
                return numero
    return None


def citacao(links: Links, codigo: str, versao: str, item: str, trecho: str,
            page: int | None = None) -> dict:
    acervo = get_acervo()
    doc = acervo.documento(codigo, versao) or acervo.vigente(codigo)
    saida = {
        "id": f"{codigo}@{versao}-{item}",
        "documentId": documento_id(codigo, versao),
        "codigo": codigo,
        "titulo": doc.titulo if doc else codigo,
        "versao": versao,
        "status": doc.fase if doc else "Vigente",
        "item": item,
        "trecho": trecho,
        "page": page or pagina(codigo, versao, trecho),
        "url": links.arquivo(codigo, versao),
    }
    return saida


def _pode(acesso: Acesso, codigo: str, versao: str) -> bool:
    return acesso.identificado and get_acervo().pode_versao(acesso, codigo, versao)


def _fato(links: Links, bruto: dict) -> dict:
    c = bruto["citation"]
    fato = {k: v for k, v in bruto.items() if k != "citation"}
    fato["citation"] = citacao(links, c["codigo"], c["versao"], c["item"], c["trecho"],
                               c.get("page"))
    return fato


def fatos(acesso: Acesso, links: Links) -> list[dict]:
    return [_fato(links, f) for f in _seed()["fatos"]
            if _pode(acesso, f["citation"]["codigo"], f["citation"]["versao"])]


def por_ids(ids: list[str], acesso: Acesso, links: Links) -> list[dict]:
    """Fatos pelo id, na ordem pedida, só os visíveis. Id desconhecido é ignorado."""
    visiveis = {f["id"]: f for f in fatos(acesso, links)}
    return [visiveis[i] for i in dict.fromkeys(ids) if i in visiveis]


def fontes_simulacao(acesso: Acesso, links: Links) -> list[dict]:
    return [citacao(links, c["codigo"], c["versao"], c["item"], c["trecho"], c.get("page"))
            for c in _seed()["fontes_simulacao"]
            if _pode(acesso, c["codigo"], c["versao"])]


# ---------- trechos para as respostas do chat e os prazos ----------
def _normal(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")


def palavras(texto: str) -> set[str]:
    return set(_PALAVRA.findall(_normal(texto))) - _VAZIAS


def trecho_que_apoia(codigo: str, texto: str, acesso: Acesso,
                     versao: str | None = None) -> Chunk | None:
    """Trecho visível do documento que mais se parece com `texto` (a resposta dada).

    Sem `versao`, só a vigente. Com `versao`, aquela versão (inclusive substituída), se o sujeito
    pode vê-la.
    """
    acervo = get_acervo()
    alvo = palavras(texto)
    candidatos = [c for c in acervo.chunks_visiveis(acesso, incluir_substituidos=bool(versao))
                  if c.codigo == codigo and c.item != "cabeçalho"
                  and (c.versao == versao if versao else c.vigente)]
    if not candidatos or not alvo:
        return None
    melhor = max(candidatos, key=lambda c: len(alvo & palavras(c.texto)))
    return melhor if len(alvo & palavras(melhor.texto)) >= MIN_PALAVRAS_EM_COMUM else None


def trecho_do_item(codigo: str, item: str, acesso: Acesso) -> Chunk | None:
    """O trecho vigente e visível com esse item (o primeiro, se o item se repete)."""
    return next((c for c in get_acervo().chunks_visiveis(acesso)
                 if c.codigo == codigo and c.vigente and c.item == item), None)


def recortar(texto: str) -> str:
    texto = " ".join(texto.split())
    return texto if len(texto) <= MAX_TRECHO else texto[:MAX_TRECHO - 1].rstrip() + "…"


def citacao_do_trecho(links: Links, chunk: Chunk) -> dict:
    return citacao(links, chunk.codigo, chunk.versao, chunk.item, recortar(chunk.texto),
                   pagina(chunk.codigo, chunk.versao, chunk.texto))


def relacionados(codigos: list[str], texto: str, acesso: Acesso, links: Links,
                 limite: int = 3) -> list[dict]:
    """Fatos curados dos documentos citados, os mais parecidos com a resposta primeiro."""
    alvo = palavras(texto)

    def em_comum(f: dict) -> int:
        return len(alvo & palavras(f["title"] + " " + f["text"] + " " + f["citation"]["trecho"]))

    minimo = MIN_PALAVRAS_EM_COMUM + 1
    candidatos = [f for f in fatos(acesso, links)
                  if f["citation"]["codigo"] in codigos and em_comum(f) >= minimo]
    candidatos.sort(key=em_comum, reverse=True)
    return candidatos[:limite]
