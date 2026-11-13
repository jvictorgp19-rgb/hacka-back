"""Fatos de férias num arquivo enviado: faltas injustificadas, período aquisitivo e datas.

Serve para o chat responder "quantos dias de férias eu tenho?" com base no que a pessoa enviou
(formulário FM_1111-001 preenchido, espelho de ponto). Regra: NG_111 4.1.1 e TB_1111-001,
Tabela 1.

Só números e datas são guardados: nunca nome, CPF ou matrícula. Mesmo assim, são dados pessoais
(LGPD art. 5º, I). Quem pode ver está em app/services/envios.py.
O nome do empregado preenchido no formulário (nome_titular) só serve para conferir se o
arquivo é de quem enviou; ele não é guardado.
Formulário em branco ("[início] a [fim]", "____") não gera fato.
"""

import re
from dataclasses import asdict, dataclass, field
from datetime import date

from app.services.triagem.detectores import normalizar

_DATA = r"(\d{1,2})/(\d{1,2})/(\d{4})"
_ESPACO = r"[ \t]{0,3}"  # quantificador limitado: \s* encadeado é backtracking quadrático (ReDoS)
_FALTAS_TOTAL = re.compile(r"faltas? injustificadas?(?: no periodo(?: aquisitivo)?)?" + _ESPACO
                           + r"[:=\-]" + _ESPACO + r"(\d{1,3})\b")
_PERIODO = re.compile(r"periodo aquisitivo" + _ESPACO + r"[:\-]?" + _ESPACO
                      + r"(?:de[ \t]{1,3})?" + _DATA + _ESPACO + r"(?:a|ate|-)" + _ESPACO + _DATA)
_ADMISSAO = re.compile(r"(?:data de )?admissao" + _ESPACO + r"[:\-]?" + _ESPACO
                       + r"(?:em[ \t]{1,3})?" + _DATA)
_GOZO = re.compile(r"inicio d[eo] gozo" + _ESPACO + r"[:\-]?" + _ESPACO + _DATA)
_NOME = re.compile(r"\bnome(?: do empregado| completo| do titular)?" + _ESPACO + ":" + _ESPACO
                   + r"([a-z]{2,30}(?:[ \t]{1,3}[a-z]{1,30}){0,6})")


def _e_planilha_de_ponto(texto: str) -> bool:
    """Cabeçalho "Data | Ocorrência" (linha a linha, sem regex com .* encadeado)."""
    return any(linha.lstrip().startswith(("data", "dia")) and "ocorrencia" in linha
               for linha in texto.splitlines())


def _linhas_de_falta(texto: str) -> int:
    return sum(1 for linha in texto.splitlines()
               if "falta injustificada" in linha and "total" not in linha)


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
        return (self.faltas_injustificadas is None and self.periodo_inicio is None
                and self.admissao is None)

    def as_dict(self) -> dict:
        return asdict(self)


def _data(dia: str, mes: str, ano: str) -> str | None:
    try:
        d = date(int(ano), int(mes), int(dia))
    except ValueError:
        return None
    return d.isoformat() if 1950 <= d.year <= 2100 else None


def nome_titular(paginas: list[str]) -> str | None:
    """Nome do empregado preenchido (normalizado). Só para conferir; nunca guardar."""
    for pagina in paginas:
        if m := _NOME.search(normalizar(pagina)):
            return m.group(1).strip()
    return None


def titular_confere(nome_preenchido: str | None, nome_persona: str) -> str:
    """'proprio', 'outro' ou 'nao_informado'. Todos os nomes da persona precisam aparecer."""
    if not nome_preenchido:
        return "nao_informado"
    da_persona = set(normalizar(nome_persona.split("(")[0]).split())
    return "proprio" if da_persona and da_persona <= set(nome_preenchido.split()) else "outro"


def extrair_fatos(paginas: list[str]) -> FatosFerias | None:
    fatos = FatosFerias()
    vistas: set[int] = set()
    contagem = 0
    for numero, pagina in enumerate(paginas, start=1):
        texto = normalizar(pagina)
        if fatos.faltas_injustificadas is None and (m := _FALTAS_TOTAL.search(texto)):
            fatos.faltas_injustificadas, fatos.origem_faltas = int(m.group(1)), "declarado"
            vistas.add(numero)
        if _e_planilha_de_ponto(texto):  # espelho de ponto: uma linha por ocorrência
            n = _linhas_de_falta(texto)
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
