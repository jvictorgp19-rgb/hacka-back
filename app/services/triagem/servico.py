"""Triagem de um arquivo: extrai, classifica (Interna ou Sigilosa) e sugere o setor dono.

É sugestão. Quem confirma é uma pessoa: o aprovador do setor (docs/CLASSIFICACAO_BBTS.md e
LAI art. 27, que dá a classificação a uma autoridade).
"""

import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.core.setores import rotulo
from app.services.ingest.header import parse_cabecalho
from app.services.triagem import departamento, detectores
from app.services.triagem.extracao import Extracao, extrair, extrair_isolado
from app.services.triagem.ferias import extrair_fatos

MIN_CARACTERES = 40  # abaixo disso o PDF é imagem (digitalizado): sem OCR, não há o que ler
FORMATOS_COM_IMAGEM = {"pdf", "docx", "xlsx"}  # texto puro curto é conteúdo, não digitalização

CRITERIO_INTERNO = ("Nada sigiloso encontrado: orienta qualquer empregado (classificação BBTS, "
                    "seção 2). Confira antes de publicar.")
CRITERIO_FERIAS = ("Faltas, período aquisitivo ou datas de um empregado: dado pessoal "
                   "(LGPD art. 5º, I). Formulário preenchido é sigiloso da GEPEC "
                   "(classificação BBTS).")
CRITERIO_SEM_TEXTO = ("Sem texto para ler (provável digitalização). Tratado como sigiloso do setor "
                      "até alguém conferir: o conteúdo é desconhecido.")


@dataclass
class Classificacao:
    nivel: str  # Interna | Sigilosa
    setores: list[str]
    setores_rotulo: list[str]
    confianca: float
    motivos: list[dict]
    resumo: str


@dataclass
class Triagem:
    nome: str
    formato: str
    tamanho: int
    sha256: str
    paginas: int
    caracteres: int
    status: str  # ready | not_extracted
    cabecalho: dict
    classificacao: Classificacao
    departamento: dict
    revisao_humana: bool
    avisos: list[str] = field(default_factory=list)
    texto_paginas: list[str] = field(default_factory=list)  # só para a ficha da IA; nunca persistir
    fatos_ferias: dict | None = None  # faltas e datas (sem nome/CPF): ver triagem/ferias.py

    def as_dict(self, com_texto: bool = False) -> dict:
        d = asdict(self)
        if not com_texto:
            d.pop("texto_paginas")
        return d


def sha256_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def _confianca(achados: list[detectores.Achado], nivel: str, caracteres: int) -> float:
    fortes = {"versao_obsoleta", "credencial", "codigo_fonte", "dado_bancario", "dado_sensivel",
              "marcacao_sigilo", "registro_ferias"}
    if nivel == "Sigilosa":
        if any(a.tipo in fortes for a in achados):
            return 0.95
        return 0.85 if len([a for a in achados if a.nivel == "Sigilosa"]) > 1 else 0.75
    return 0.8 if caracteres >= 1000 else 0.6


def classificar(extracao: Extracao, nome: str, caminho: Path) -> Triagem:
    texto = extracao.texto
    cab = parse_cabecalho(texto)
    fatos = extrair_fatos(extracao.paginas)
    extras = [("GEPEC", departamento.PESO_CODIGO,
               "Registro de férias preenchido: gestão de pessoas (GEPEC).")] if fatos else []
    sugestao = departamento.sugerir(texto, extracao.formato, cab.codigo, cab.vinculado_a,
                                    cab.elaborado_por, nome, extras)
    tamanho, sha = caminho.stat().st_size, sha256_arquivo(caminho)

    if extracao.caracteres < MIN_CARACTERES and extracao.formato in FORMATOS_COM_IMAGEM:
        classe = Classificacao("Sigilosa", [sugestao.sigla], [rotulo(sugestao.sigla)], 0.3, [{
            "tipo": "conteudo_nao_extraido", "rotulo": "Conteúdo não extraído",
            "nivel": "Sigilosa", "ocorrencias": 0, "paginas": [],
            "criterio": CRITERIO_SEM_TEXTO}], CRITERIO_SEM_TEXTO)
        return Triagem(nome, extracao.formato, tamanho, sha, len(extracao.paginas),
                       extracao.caracteres, "not_extracted", cab.as_dict(), classe,
                       sugestao.as_dict(), True, extracao.avisos, extracao.paginas)

    achados = detectores.detectar(extracao.paginas, extracao.formato, cab.fase)
    if fatos:
        achados.append(detectores.Achado("registro_ferias", "Registro de férias preenchido",
                                         "Sigilosa", 1, fatos.paginas, CRITERIO_FERIAS))
    sigilosos = [a for a in achados if a.nivel == "Sigilosa"]
    nivel = "Sigilosa" if sigilosos else "Interna"
    if nivel == "Sigilosa":
        lista = departamento.setores_com_acesso(sugestao.sigla, sugestao.mencoes,
                                                {a.tipo for a in sigilosos})
        resumo = "Sigiloso: " + "; ".join(a.rotulo.lower() for a in sigilosos) + "."
    else:
        lista = [sugestao.sigla]
        resumo = CRITERIO_INTERNO
    confianca = _confianca(achados, nivel, extracao.caracteres)
    classe = Classificacao(nivel, lista, [rotulo(s) for s in lista], confianca,
                           [a.as_dict() for a in achados], resumo)
    revisao = nivel == "Sigilosa" or confianca < 0.7 or sugestao.confianca < 0.5
    return Triagem(nome, extracao.formato, tamanho, sha, len(extracao.paginas),
                   extracao.caracteres, "ready", cab.as_dict(), classe, sugestao.as_dict(),
                   revisao, extracao.avisos, extracao.paginas,
                   fatos.as_dict() if fatos else None)


def triar_arquivo(caminho: Path, nome: str | None = None, isolar: bool = True) -> Triagem:
    """Triagem completa. `isolar` roda o parser em outro processo (padrão para upload)."""
    nome = nome or caminho.name
    extracao = extrair_isolado(caminho, nome) if isolar else extrair(caminho, nome)
    return classificar(extracao, nome, caminho)
