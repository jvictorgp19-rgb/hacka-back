"""Extração de texto de qualquer arquivo enviado, para a triagem e para a IA.

Formatos: PDF, DOCX, XLSX, CSV e texto (TXT, MD, JSON, código-fonte). Cada formato vira a mesma
"ficha": lista de páginas (PDF), seções (DOCX), planilhas (XLSX) ou um bloco só (texto).

Defesas (docs/SEGURANCA_REVISAO_CODEX.md, SEC-15 e SEC-17):
- assinatura conferida pelo conteúdo, nunca pela extensão;
- limites de tamanho, páginas, linhas, caracteres e entradas de ZIP (bomba de descompressão);
- XML lido com defusedxml (openpyxl o usa quando instalado) e sem entidades externas;
- o parser roda num processo separado, com tempo limite: arquivo hostil não trava a API.
"""

import csv
import io
import multiprocessing as mp
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

MAX_BYTES = 20 * 1024 * 1024
MAX_PAGINAS = 200
MAX_CARACTERES = 2_000_000
MAX_ZIP_ENTRADAS = 2000
MAX_ZIP_DESCOMPACTADO = 100 * 1024 * 1024
MAX_ZIP_RAZAO = 100
MAX_LINHAS_PLANILHA = 20_000
TEMPO_LIMITE_S = 30

EXTENSOES_TEXTO = {
    ".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".xml", ".html", ".css", ".sql", ".py",
    ".js", ".ts", ".tsx", ".jsx", ".java", ".kt", ".go", ".rs", ".c", ".h", ".cpp", ".cs",
    ".rb", ".php", ".sh", ".ps1", ".ini", ".toml", ".env.example", ".log",
}
EXTENSOES_CODIGO = {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".kt", ".go", ".rs", ".c",
                    ".h", ".cpp", ".cs", ".rb", ".php", ".sh", ".ps1", ".sql"}


class ArquivoRecusado(ValueError):
    """Arquivo fora do formato, acima dos limites ou malformado. A mensagem vai para o usuário."""


@dataclass
class Extracao:
    formato: str  # pdf | docx | xlsx | csv | texto | codigo
    paginas: list[str]
    caracteres: int = 0
    avisos: list[str] = field(default_factory=list)

    @property
    def texto(self) -> str:
        return "\n".join(self.paginas)

    def as_dict(self) -> dict:
        return asdict(self)


def _extensao(nome: str) -> str:
    nome = nome.lower()
    return ".env.example" if nome.endswith(".env.example") else Path(nome).suffix


def detectar_formato(cabeca: bytes, nome: str) -> str:
    """Formato pelo conteúdo. A extensão só desempata entre DOCX/XLSX e entre os textos."""
    ext = _extensao(nome)
    if cabeca.startswith(b"%PDF-"):
        return "pdf"
    if cabeca.startswith(b"PK\x03\x04"):
        if ext == ".docx":
            return "docx"
        if ext == ".xlsx":
            return "xlsx"
        raise ArquivoRecusado("Arquivo compactado sem extensão .docx ou .xlsx.")
    if b"\x00" in cabeca:
        raise ArquivoRecusado("Formato não suportado. Envie PDF, DOCX, XLSX, CSV ou texto.")
    if ext == ".csv":
        return "csv"
    if ext in EXTENSOES_CODIGO:
        return "codigo"
    if ext in EXTENSOES_TEXTO or ext == "":
        return "texto"
    raise ArquivoRecusado("Formato não suportado. Envie PDF, DOCX, XLSX, CSV ou texto.")


def _limitar(paginas: list[str], avisos: list[str]) -> list[str]:
    total, saida = 0, []
    for pagina in paginas:
        if total + len(pagina) > MAX_CARACTERES:
            saida.append(pagina[: MAX_CARACTERES - total])
            avisos.append(f"Texto cortado em {MAX_CARACTERES} caracteres.")
            break
        saida.append(pagina)
        total += len(pagina)
    return saida


def _conferir_zip(caminho: Path, obrigatorio: str) -> None:
    try:
        with zipfile.ZipFile(caminho) as z:
            entradas = z.infolist()
            if len(entradas) > MAX_ZIP_ENTRADAS:
                raise ArquivoRecusado("Arquivo com entradas internas demais.")
            descompactado = sum(e.file_size for e in entradas)
            compactado = max(1, sum(e.compress_size for e in entradas))
            if descompactado > MAX_ZIP_DESCOMPACTADO or descompactado / compactado > MAX_ZIP_RAZAO:
                raise ArquivoRecusado("Arquivo descompactado grande demais (possível bomba de "
                                      "descompressão).")
            nomes = {e.filename for e in entradas}
            if obrigatorio not in nomes:
                raise ArquivoRecusado("Arquivo não é um documento Office válido.")
    except zipfile.BadZipFile:
        raise ArquivoRecusado("Arquivo compactado corrompido.") from None


def _pdf(caminho: Path, avisos: list[str]) -> list[str]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        leitor = PdfReader(str(caminho))
        if leitor.is_encrypted:
            raise ArquivoRecusado("PDF protegido por senha: não dá para ler o conteúdo.")
        if len(leitor.pages) > MAX_PAGINAS:
            raise ArquivoRecusado(f"PDF acima de {MAX_PAGINAS} páginas.")
        return [pagina.extract_text() or "" for pagina in leitor.pages]
    except PdfReadError:
        raise ArquivoRecusado("PDF corrompido ou malformado.") from None


def _docx(caminho: Path, avisos: list[str]) -> list[str]:
    _conferir_zip(caminho, "word/document.xml")
    from docx import Document

    doc = Document(str(caminho))
    linhas = [p.text for p in doc.paragraphs]
    for tabela in doc.tables:
        for linha in tabela.rows:
            linhas.append(" | ".join(c.text.strip() for c in linha.cells))
    return ["\n".join(linhas)]


def _xlsx(caminho: Path, avisos: list[str]) -> list[str]:
    _conferir_zip(caminho, "xl/workbook.xml")
    from openpyxl import load_workbook

    livro = load_workbook(str(caminho), read_only=True, data_only=True)
    paginas = []
    try:
        for planilha in livro.worksheets[:MAX_PAGINAS]:
            linhas = [f"[Planilha: {planilha.title}]"]
            for i, linha in enumerate(planilha.iter_rows(values_only=True)):
                if i >= MAX_LINHAS_PLANILHA:
                    avisos.append(f"Planilha {planilha.title} cortada em {MAX_LINHAS_PLANILHA} "
                                  "linhas.")
                    break
                valores = [str(v) for v in linha if v is not None]
                if valores:
                    linhas.append(" | ".join(valores))
            paginas.append("\n".join(linhas))
    finally:
        livro.close()
    return paginas


def _texto(caminho: Path, avisos: list[str]) -> str:
    bruto = caminho.read_bytes()
    try:
        return bruto.decode("utf-8-sig")
    except UnicodeDecodeError:
        avisos.append("Texto não está em UTF-8; lido como Latin-1.")
        return bruto.decode("latin-1")


def _csv(caminho: Path, avisos: list[str]) -> list[str]:
    texto = _texto(caminho, avisos)
    linhas = []
    for i, linha in enumerate(csv.reader(io.StringIO(texto))):
        if i >= MAX_LINHAS_PLANILHA:
            avisos.append(f"CSV cortado em {MAX_LINHAS_PLANILHA} linhas.")
            break
        linhas.append(" | ".join(linha))
    return ["\n".join(linhas)]


def extrair(caminho: Path, nome: str) -> Extracao:
    """Extrai no processo atual. Use extrair_isolado() para arquivo vindo de fora."""
    tamanho = caminho.stat().st_size
    if tamanho == 0:
        raise ArquivoRecusado("Arquivo vazio.")
    if tamanho > MAX_BYTES:
        raise ArquivoRecusado("Arquivo acima de 20 MiB.")
    with caminho.open("rb") as f:
        cabeca = f.read(8)
    formato = detectar_formato(cabeca, nome)
    avisos: list[str] = []
    if formato == "pdf":
        paginas = _pdf(caminho, avisos)
    elif formato == "docx":
        paginas = _docx(caminho, avisos)
    elif formato == "xlsx":
        paginas = _xlsx(caminho, avisos)
    elif formato == "csv":
        paginas = _csv(caminho, avisos)
    else:
        paginas = [_texto(caminho, avisos)]
    paginas = _limitar(paginas, avisos)
    return Extracao(formato=formato, paginas=paginas, caracteres=sum(len(p) for p in paginas),
                    avisos=avisos)


# ---------- processo isolado ----------
def _no_filho(caminho: str, nome: str, saida) -> None:
    try:
        saida.send(("ok", extrair(Path(caminho), nome).as_dict()))
    except ArquivoRecusado as erro:
        saida.send(("recusado", str(erro)))
    except Exception as erro:  # noqa: BLE001 - qualquer falha do parser vira recusa genérica
        saida.send(("recusado", f"Não foi possível ler o arquivo ({type(erro).__name__})."))
    finally:
        saida.close()


def extrair_isolado(caminho: Path, nome: str, tempo_limite_s: float = TEMPO_LIMITE_S
                    ) -> Extracao:
    """Roda extrair() em outro processo. Estouro de tempo mata o processo e recusa o arquivo."""
    return Extracao(**rodar_isolado(_no_filho, str(caminho), nome,
                                    tempo_limite_s=tempo_limite_s))


def rodar_isolado(alvo, caminho: str, nome: str, tempo_limite_s: float = TEMPO_LIMITE_S
                  ) -> dict:
    """Roda alvo(caminho, nome, saida) em processo novo e devolve o dict enviado por ele.

    O alvo manda ("ok", dict) ou ("recusado", mensagem) pelo pipe. Estouro de tempo mata o
    processo e recusa o arquivo.
    """
    contexto = mp.get_context("spawn")
    receber, enviar = contexto.Pipe(duplex=False)
    processo = contexto.Process(target=alvo, args=(caminho, nome, enviar), daemon=True)
    processo.start()
    enviar.close()
    try:
        if not receber.poll(tempo_limite_s):
            raise ArquivoRecusado(f"A leitura passou de {int(tempo_limite_s)} s e foi "
                                  "interrompida.")
        try:
            status, valor = receber.recv()
        except EOFError:
            raise ArquivoRecusado("A leitura do arquivo falhou.") from None
    finally:
        receber.close()
        processo.join(1)
        if processo.is_alive():
            processo.kill()
            processo.join(1)
    if status != "ok":
        raise ArquivoRecusado(valor)
    return valor
