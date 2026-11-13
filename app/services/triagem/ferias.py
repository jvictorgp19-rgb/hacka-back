"""Fatos de férias num arquivo enviado: faltas injustificadas, período aquisitivo e datas.

Serve para o chat responder "quantos dias de férias eu tenho?" com base no que a pessoa enviou
(formulário FM_1111-001 preenchido, espelho de ponto). Regra: NG_111 4.1.1 e TB_1111-001,
Tabela 1.

Só números e datas saem daqui: nunca nome, CPF ou matrícula. Mesmo assim, são dados pessoais de
quem enviou (LGPD art. 5º, I). Quem pode ver está em app/services/envios.py.
Formulário em branco ("[início] a [fim]", "____") não gera fato.
"""

import re
from dataclasses import asdict, dataclass, field
from datetime import date

from app.services.triagem.detectores import normalizar

_DATA = r"(\d{1,2})/(\d{1,2})/(\d{4})"
_FALTAS_TOTAL = re.compile(r"faltas? injustificadas?(?: no periodo(?: aquisitivo)?)?\s*[:=\-]\s*"
                           r"(\d{1,3})\b")
_FALTA_LINHA = re.compile(r"^(?!.*\btotal\b).*\bfalta injustificada\b", re.MULTILINE)
_PERIODO = re.compile(r"periodo aquisitivo\s*[:\-]?\s*(?:de\s+)?" + _DATA
                      + r"\s*(?:a|ate|-)\s*" + _DATA)
_ADMISSAO = re.compile(r"(?:data de )?admissao\s*[:\-]?\s*(?:em\s+)?" + _DATA)
_GOZO = re.compile(r"inicio d[eo] gozo\s*[:\-]?\s*" + _DATA)
_CABECALHO_PLANILHA = re.compile(r"^\s*(?:data|dia)\b.*\bocorrencia\b", re.MULTILINE)


@dataclass
class FatosFerias:
    faltas_injustificadas: int | None = None
    origem_faltas: str | None = None  # declarado (campo do formulário) | contagem (ponto)
    periodo_inicio: str | None = None  # ISO
    periodo_fim: str | None = None
    admissao: str | None = None
    inicio_gozo: str | None = None
    paginas: list[int] = field(default_factory=list)

    def vazio(self) -> bool:
        return self.faltas_injustificadas is None and self.periodo_inicio is None \
            and self.admissao is None

    def as_dict(self) -> dict:
        return asdict(self)


def _data(dia: str, mes: str, ano: str) -> str | None:
    try:
        d = date(int(ano), int(mes), int(dia))
    except ValueError:
        return None
    return d.isoformat() if 1950 <= d.year <= 2100 else None


def extrair_fatos(paginas: list[str]) -> FatosFerias | None:
    fatos = FatosFerias()
    vistas: set[int] = set()
    contagem = 0
    for numero, pagina in enumerate(paginas, start=1):
        texto = normalizar(pagina)
        if fatos.faltas_injustificadas is None and (m := _FALTAS_TOTAL.search(texto)):
            fatos.faltas_injustificadas, fatos.origem_faltas = int(m.group(1)), "declarado"
            vistas.add(numero)
        if _CABECALHO_PLANILHA.search(texto):  # espelho de ponto: uma linha por ocorrência
            n = len(_FALTA_LINHA.findall(texto))
            if n:
                contagem += n
                vistas.add(numero)
        if fatos.periodo_inicio is None and (m := _PERIODO.search(texto)):
            inicio, fim = _data(*m.group(1, 2, 3)), _data(*m.group(4, 5, 6))
            if inicio and fim and inicio < fim:
                fatos.periodo_inicio, fatos.periodo_fim = inicio, fim
                vistas.add(numero)
        if fatos.admissao is None and (m := _ADMISSAO.search(texto)):
            fatos.admissao = _data(*m.groups())
            vistas.add(numero)
        if fatos.inicio_gozo is None and (m := _GOZO.search(texto)):
            fatos.inicio_gozo = _data(*m.groups())
            vistas.add(numero)
    if fatos.faltas_injustificadas is None and contagem:
        fatos.faltas_injustificadas, fatos.origem_faltas = contagem, "contagem"
    fatos.paginas = sorted(vistas)
    return None if fatos.vazio() else fatos
