"""Ingestão Bronze -> Silver.

Bronze: PDFs originais em acervo/bronze, só os listados no manifesto curado (com hash).
Silver: texto por item numerado + metadados do cabeçalho, em data/silver.json (cache).

Regras de segurança:
- Só entra o que está no manifesto e bate com o sha256. O resto vai para quarentena.
- A classificação efetiva é a MAIOR entre o piso do manifesto e o cabeçalho do PDF.
- Limites de tamanho e de páginas por arquivo. Não há upload nem ingestão por URL.

Rodar manualmente:  python -m app.services.ingest.pipeline
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from pypdf import PdfReader

from app.core.acl import maior_nivel
from app.core.config import RAIZ
from app.services.ingest.header import parse_cabecalho

VERSAO_PARSER = "3"
BRONZE = RAIZ / "acervo" / "bronze"
MANIFESTO = RAIZ / "app" / "seed" / "manifesto.json"
SILVER = RAIZ / "data" / "silver.json"
MAX_BYTES = 20 * 1024 * 1024
MAX_PAGINAS = 200
MAX_CHUNKS = 2000

_INICIO_ITEM = re.compile(
    r"^(?:(?P<num>\d{1,2}(?:\.\d{1,2}){0,3})\.\s"
    r"|(?P<clausula>CLÁUSULA\s+[A-ZÀ-Ú]+(?:\s+[A-ZÀ-Ú]+)?)\s+—"
    r"|(?P<bloco>(?:Anexo|Apêndice)(?:\s+[A-Z])?)\s+—"
    r"|(?P<tabela>Tabela\s+\d+)\s+—"
    r"|(?P<exemplo>Exemplo\s+\d+)\s+—)"
)


@dataclass
class Chunk:
    codigo: str
    versao: str
    item: str
    texto: str
    nivel: str
    vigente: bool
    tema: str
    dominio: str


def _caminho_seguro(relativo: str) -> Path:
    """Resolve o caminho e exige que ele fique dentro de acervo/bronze."""
    caminho = (BRONZE / relativo).resolve()
    if BRONZE.resolve() not in caminho.parents or caminho.suffix.lower() != ".pdf":
        raise ValueError("caminho fora do acervo")
    if caminho.is_symlink() or not caminho.is_file():
        raise ValueError("arquivo ausente ou link simbólico")
    return caminho


def extrair_texto(caminho: Path) -> str:
    if caminho.stat().st_size > MAX_BYTES:
        raise ValueError("PDF acima do limite de tamanho")
    leitor = PdfReader(str(caminho))
    if len(leitor.pages) > MAX_PAGINAS:
        raise ValueError("PDF acima do limite de páginas")
    return "\n".join(pagina.extract_text() or "" for pagina in leitor.pages)


def fatiar(texto: str) -> list[tuple[str, str]]:
    """Divide o texto em (item, conteúdo). Subitens levam o título do item-pai como contexto."""
    partes: list[tuple[str, list[str]]] = [("cabeçalho", [])]
    bloco_atual = ""
    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha:
            continue
        m = _INICIO_ITEM.match(linha)
        if m:
            if m["bloco"] or m["clausula"]:
                bloco_atual = m["bloco"] or ""
                rotulo = m["bloco"] or m["clausula"].title()
            elif m["num"]:
                rotulo = f"{bloco_atual} item {m['num']}" if bloco_atual else m["num"]
            else:
                rotulo = m["tabela"] or m["exemplo"]
            partes.append((rotulo, [linha]))
        else:
            partes[-1][1].append(linha)

    titulos = {rotulo: linhas[0] for rotulo, linhas in partes if linhas}
    resultado = []
    for rotulo, linhas in partes:
        corpo = " ".join(linhas)
        if len(corpo) < 25 and rotulo != "cabeçalho":
            continue  # só o título de uma seção; o conteúdo está nos subitens
        pai = rotulo.rsplit(".", 1)[0] if "." in rotulo else ""
        if pai in titulos and pai != rotulo:
            corpo = f"{titulos[pai]} — {corpo}"
        resultado.append((rotulo, corpo[:4000]))
    return resultado


def _assinatura_do_manifesto() -> str:
    return hashlib.sha256(MANIFESTO.read_bytes() + VERSAO_PARSER.encode()).hexdigest()


def ingerir() -> dict:
    manifesto = json.loads(MANIFESTO.read_text(encoding="utf-8"))
    chunks: list[Chunk] = []
    cabecalhos: dict[str, dict] = {}
    quarentena: list[dict] = []

    for doc in manifesto["documentos"]:
        chave = f"{doc['codigo']}@{doc['versao']}"
        if doc["arquivo"] is None:  # documento virtual, texto vem do manifesto
            chunks.append(Chunk(doc["codigo"], doc["versao"], "resumo", doc["texto"],
                                doc["classificacao"], doc["vigente"], doc["tema"],
                                doc["dominio"]))
            continue
        try:
            caminho = _caminho_seguro(doc["arquivo"])
            if hashlib.sha256(caminho.read_bytes()).hexdigest() != doc["sha256"]:
                raise ValueError("hash diferente do manifesto")
            texto = extrair_texto(caminho)
            cab = parse_cabecalho(texto)
            if cab.codigo != doc["codigo"] or cab.versao != doc["versao"]:
                raise ValueError("cabeçalho não confere com o manifesto")
        except Exception as erro:  # noqa: BLE001 - qualquer falha manda o arquivo à quarentena
            quarentena.append({"documento": chave, "motivo": str(erro)})
            continue
        nivel = maior_nivel([doc["classificacao"], cab.classificacao or doc["classificacao"]])
        vigente = doc["vigente"] and cab.fase == "Vigente"
        cabecalhos[chave] = cab.as_dict() | {"nivel": nivel, "vigente": vigente}
        for item, corpo in fatiar(texto):
            chunks.append(Chunk(doc["codigo"], doc["versao"], item, corpo, nivel, vigente,
                                doc["tema"], doc["dominio"]))
        if len(chunks) > MAX_CHUNKS:
            raise RuntimeError("Acervo acima do limite de chunks.")

    return {
        "assinatura": _assinatura_do_manifesto(),
        "cabecalhos": cabecalhos,
        "quarentena": quarentena,
        "chunks": [asdict(c) for c in chunks],
    }


def carregar_silver() -> dict:
    """Usa o cache se o manifesto e o parser não mudaram; senão reprocessa."""
    if SILVER.is_file():
        try:
            silver = json.loads(SILVER.read_text(encoding="utf-8"))
            if silver.get("assinatura") == _assinatura_do_manifesto():
                return silver
        except (OSError, ValueError):
            pass
    silver = ingerir()
    SILVER.parent.mkdir(parents=True, exist_ok=True)
    temporario = SILVER.with_suffix(".tmp")
    temporario.write_text(json.dumps(silver, ensure_ascii=False), encoding="utf-8")
    temporario.replace(SILVER)
    return silver


if __name__ == "__main__":
    s = ingerir()
    print(f"{len(s['chunks'])} chunks, {len(s['cabecalhos'])} documentos, "
          f"{len(s['quarentena'])} em quarentena")
    for q in s["quarentena"]:
        print("QUARENTENA:", q)
