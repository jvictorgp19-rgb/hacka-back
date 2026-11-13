"""Sugere o setor dono de um arquivo e, se ele for sigiloso, os setores com acesso.

Sinais, do mais forte ao mais fraco:
1. "Elaborado por" do cabeçalho, com a sigla da ACME traduzida para o setor BBTS (GGC -> GEPEC).
2. Código do documento: a série da norma (NG_010) ou o tipo (CTR é da GESUC).
3. Código-fonte: setor de desenvolvimento (GEINOV).
4. Siglas de setor citadas no texto e palavras-chave de cada setor (app/seed/setores.json).

Diretoria nunca é sugerida como dona: ela aprova. Entra só na lista de setores com acesso,
quando o texto a cita.
"""

import re
from collections import Counter
from dataclasses import asdict, dataclass

from app.core.setores import Setor, por_sigla_do_acervo, setores
from app.services.triagem.detectores import normalizar

PESO_CABECALHO = 10.0
PESO_CODIGO = 6.0
PESO_CODIGO_FONTE = 8.0
MIN_MENCOES_ACESSO = 2  # setor citado ao menos 2 vezes entra na lista de acesso do sigiloso

_SIGLA_ENTRE_PARENTESES = re.compile(r"\(([A-Z]{2,8})\)")
_CODIGO = re.compile(r"\b(NG|PX|PP|GU|FM|TB|FL|RG|DV|CTR|NT)_(\d{3,4})(?:-\d{3})?\b")
_POR_TIPO = {"CTR": "GESUC"}  # contrato: elaborado por Compras e Contratos (catálogo NG_010)


@dataclass
class Candidato:
    sigla: str
    nome: str
    pontos: float

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Sugestao:
    sigla: str
    nome: str
    confianca: float
    sinais: list[str]
    alternativas: list[Candidato]
    mencoes: dict[str, int]

    def as_dict(self) -> dict:
        return {**asdict(self), "alternativas": [a.as_dict() for a in self.alternativas]}


def _departamentos() -> dict[str, Setor]:
    return {s.sigla: s for s in setores().values()
            if s.tipo == "departamento" and (s.series or s.palavras_chave)}


def _por_serie(numero: int) -> str | None:
    serie = numero // 100
    for setor in _departamentos().values():
        if serie in setor.series:
            return setor.sigla
    return None


def setor_do_codigo(codigo: str | None, vinculado_a: str | None = None) -> str | None:
    """Setor pela taxonomia. PX/FM/TB herdam o número da NG: o vínculo do cabeçalho decide."""
    for alvo in (vinculado_a, codigo):
        m = _CODIGO.search(alvo or "")
        if not m:
            continue
        tipo, numero = m.group(1), int(m.group(2))
        if tipo in _POR_TIPO:
            return _POR_TIPO[tipo]
        if tipo in ("NG", "RG"):
            return _por_serie(numero)
    return None


def mencoes(texto: str) -> Counter:
    """Quantas vezes cada setor é citado pela sigla (BBTS ou da ACME)."""
    apelidos = {}
    for s in setores().values():
        for a in (s.sigla, *s.siglas_acervo):
            apelidos[a] = s.sigla
    padrao = re.compile(r"\b(" + "|".join(sorted(apelidos, key=len, reverse=True)) + r")\b")
    return Counter(apelidos[m.group(1)] for m in padrao.finditer(texto))


def sugerir(texto: str, formato: str, codigo: str | None, vinculado_a: str | None,
            elaborado_por: str | None, nome_arquivo: str) -> Sugestao:
    pontos: Counter = Counter()
    sinais: list[str] = []
    candidatos = _departamentos()

    for sigla_acme in _SIGLA_ENTRE_PARENTESES.findall(elaborado_por or ""):
        sigla = por_sigla_do_acervo(sigla_acme)
        if sigla in candidatos:
            pontos[sigla] += PESO_CABECALHO
            sinais.append(f"Cabeçalho: elaborado por {sigla_acme} ({sigla}).")

    pelo_codigo = setor_do_codigo(codigo or nome_arquivo, vinculado_a)
    if pelo_codigo:
        pontos[pelo_codigo] += PESO_CODIGO
        sinais.append(f"Código {codigo or nome_arquivo}: série/tipo do setor {pelo_codigo} "
                      "(catálogo NG_010).")

    if formato == "codigo":
        pontos["GEINOV"] += PESO_CODIGO_FONTE
        sinais.append("Código-fonte: setor de desenvolvimento de soluções digitais (GEINOV).")

    citados = mencoes(texto)
    for sigla, n in citados.items():
        if sigla in candidatos:
            pontos[sigla] += min(n, 15) * 0.5

    normal = normalizar(texto)
    for sigla, setor in candidatos.items():
        hits = sum(min(normal.count(normalizar(p)), 5) for p in setor.palavras_chave)
        if hits:
            pontos[sigla] += hits * 0.5
    citados_txt = ", ".join(f"{s} ({n}x)" for s, n in citados.most_common(4))
    if citados_txt:
        sinais.append(f"Setores citados no texto: {citados_txt}.")

    ranking = [(s, p) for s, p in pontos.most_common() if p > 0]
    if not ranking:
        return Sugestao("GENOC", setores()["GENOC"].nome, 0.0,
                        ["Nenhum sinal de setor: encaminhar à governança documental (GENOC) para "
                         "triagem manual."], [], dict(citados))
    total = sum(p for _, p in ranking)
    dono, melhor = ranking[0]
    confianca = round(min(1.0, melhor / total * (1.0 if melhor >= PESO_CODIGO else 0.8)), 2)
    alternativas = [Candidato(s, candidatos[s].nome, round(p, 1)) for s, p in ranking[1:3]]
    return Sugestao(dono, candidatos[dono].nome, confianca, sinais, alternativas, dict(citados))


def setores_com_acesso(dono: str, citados: dict[str, int], tipos: set[str]) -> list[str]:
    """Lista de acesso sugerida para um arquivo sigiloso.

    Dado comercial: o dono mais os setores citados ao menos 2 vezes (demandante, pagamento,
    diretoria aprovadora), como nas listas da classificação BBTS. Nos demais casos (dado pessoal,
    código, versão obsoleta), só o dono.
    """
    lista = [dono]
    if "financeiro_comercial" in tipos:
        # como nas listas da classificação BBTS: departamentos, depois a diretoria do dono,
        # depois as outras diretorias
        tudo = setores()
        tipo = {s.sigla: s.tipo for s in tudo.values()}
        diretoria_do_dono = tudo[dono].diretoria if dono in tudo else None
        lista += sorted((s for s, n in citados.items() if n >= MIN_MENCOES_ACESSO and s != dono),
                        key=lambda s: (tipo.get(s) == "diretoria", s != diretoria_do_dono,
                                       -citados[s], s))
    return lista
