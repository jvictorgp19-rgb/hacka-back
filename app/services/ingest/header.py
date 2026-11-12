"""Parser do cabeçalho padrão dos documentos da ACME.

Exemplo:
    #interna
    Documento: Norma Geral
    Título: Férias
    Sigla e Número: NG_111 Versão: 3.0.0
    Elaborado por: Gerência de Gente e Cultura (GGC)
    Fase: Vigente Vigência: 03/08/2026 a 03/02/2028
    Vinculado a: NG_111
"""

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime

_CLASSIFICACOES = {"publica": "Pública", "interna": "Interna", "restrita": "Restrita",
                   "sigilosa": "Sigilosa"}


@dataclass
class Cabecalho:
    codigo: str | None = None
    versao: str | None = None
    tipo: str | None = None
    titulo: str | None = None
    fase: str | None = None
    classificacao: str | None = None
    elaborado_por: str | None = None
    aprovado_por: str | None = None
    vinculado_a: str | None = None
    vigencia_inicio: str | None = None  # ISO
    vigencia_fim: str | None = None
    data_referencia: str | None = None  # aprovação, assinatura ou início da vigência

    def as_dict(self) -> dict:
        return asdict(self)


def _data(texto: str) -> date:
    return datetime.strptime(texto, "%d/%m/%Y").date()


def _campo(padrao: str, texto: str) -> str | None:
    m = re.search(padrao, texto, re.DOTALL)
    return " ".join(m.group(1).split()) if m else None


def parse_cabecalho(texto: str) -> Cabecalho:
    topo = texto[:1500]
    c = Cabecalho()
    m = re.search(r"Sigla e Número:\s*(\S+)\s+Versão:\s*([\d.]+)", topo)
    if m:
        c.codigo, c.versao = m.group(1), m.group(2)
    c.tipo = _campo(r"Documento:\s*(.+?)\n", topo)
    c.titulo = _campo(r"Título:\s*(.+?)\nSigla", topo)
    c.fase = _campo(r"Fase:\s*(Vigente|Versão anterior)", topo)
    c.elaborado_por = _campo(r"Elaborado por:\s*(.+?)\s*(?:Referência:|\nAprovado|\nFase)", topo)
    c.aprovado_por = _campo(r"Aprovado por:\s*(.+?)\nFase", topo)
    c.vinculado_a = _campo(r"(?:Vinculado a|Referência):\s*(\S+)", topo)
    m = re.search(r"^#(\w+)", topo, re.MULTILINE)
    if m:
        c.classificacao = _CLASSIFICACOES.get(m.group(1).lower())
    m = re.search(r"Vigência:\s*(\d{2}/\d{2}/\d{4})\s*a\s*(\d{2}/\d{2}/\d{4})", topo)
    if m:
        c.vigencia_inicio = _data(m.group(1)).isoformat()
        c.vigencia_fim = _data(m.group(2)).isoformat()
        c.data_referencia = c.vigencia_inicio
    m = re.search(r"(?:Aprovado em|Assinada em):\s*(\d{2}/\d{2}/\d{4})", topo)
    if m:
        c.data_referencia = _data(m.group(1)).isoformat()
    return c
