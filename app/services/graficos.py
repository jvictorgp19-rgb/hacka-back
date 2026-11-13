"""Gráficos do site. O back agrega com pandas e devolve as séries em JSON; o front desenha.

O formato (`Grafico`) não depende da biblioteca de gráfico do front: tipo, eixos e séries de
pontos {x, y}.

Regras de acesso:
- A contagem só inclui o que o sujeito pode ver. Uma barra "Sigilosa: 2" revelaria que esses
  documentos existem (docs/PLANO.md).
- O painel "uso" é só da governança e agrega por dia, ação, resultado, intent e nível, nunca
  por pessoa: gráfico por usuário seria monitoramento individual (LGPD art. 6º, III).
"""

import logging
from datetime import date, datetime

import pandas as pd

from app.core.auth import Sujeito
from app.services import audit_log, envios
from app.services.acervo import get_acervo
from app.services.radar import montar_radar

log = logging.getLogger(__name__)
NADA_VISIVEL = "Nada visível para o seu perfil neste painel."
ORDEM_CRITICIDADE = ["Crítica", "Alta", "Normal"]


class SemPermissao(PermissionError):
    """Painel fora do perfil do sujeito."""


def _pontos(serie: pd.Series) -> list[dict]:
    return [{"x": str(x), "y": float(y)} for x, y in serie.items()]


def _grafico(id_: str, titulo: str, tipo: str, eixo_x: str, eixo_y: str,
             series: list[dict], nota: str | None = None) -> dict:
    vazio = not any(s["pontos"] for s in series)
    return {"id": id_, "titulo": titulo, "tipo": tipo, "eixoX": eixo_x, "eixoY": eixo_y,
            "series": series, "nota": NADA_VISIVEL if vazio and not nota else nota}


def _contagem(df: pd.DataFrame, coluna: str, nome: str = "Documentos",
              ordem: list[str] | None = None) -> list[dict]:
    if df.empty:
        return [{"nome": nome, "pontos": []}]
    serie = df.groupby(coluna).size()
    serie = serie.reindex(ordem).dropna() if ordem else serie.sort_values(ascending=False)
    return [{"nome": nome, "pontos": _pontos(serie)}]


def _cruzado(df: pd.DataFrame, linhas: str, colunas: str) -> list[dict]:
    """Uma série por valor de `colunas` (barra empilhada / heatmap)."""
    if df.empty:
        return []
    tabela = pd.crosstab(df[linhas], df[colunas])
    return [{"nome": str(c), "pontos": _pontos(tabela[c])} for c in tabela.columns]


# ---------- painéis ----------
def painel_acervo(sujeito: Sujeito) -> list[dict]:
    docs = get_acervo().visiveis(sujeito.acesso, vigentes=None)
    df = pd.DataFrame([{"tema": d.tema, "setor": d.dominio, "nivel": d.nivel,
                        "fase": "Vigente" if d.vigente else "Substituída"} for d in docs],
                      columns=["tema", "setor", "nivel", "fase"])
    return [
        _grafico("acervo-tema", "Documentos por tema", "barra", "Tema", "Documentos",
                 _contagem(df, "tema")),
        _grafico("acervo-setor", "Documentos por setor dono", "barra", "Setor", "Documentos",
                 _contagem(df, "setor")),
        _grafico("acervo-fase", "Vigentes x substituídas", "pizza", "Fase", "Documentos",
                 _contagem(df, "fase")),
        _grafico("acervo-nivel-tema", "Classificação por tema", "barra_empilhada", "Tema",
                 "Documentos", _cruzado(df, "tema", "nivel"),
                 "Só entram os documentos que o seu perfil pode ver."),
    ]


def painel_radar(sujeito: Sujeito, hoje: date) -> list[dict]:
    eventos = montar_radar(get_acervo(), sujeito, hoje)
    df = pd.DataFrame([{"criticidade": e.criticidade,
                        "mes": datetime.strptime(e.dataLimite, "%d/%m/%Y").strftime("%Y-%m")}
                       for e in eventos], columns=["criticidade", "mes"])
    por_mes = df.groupby("mes").size().sort_index() if not df.empty else pd.Series(dtype=int)
    return [
        _grafico("radar-criticidade", "Prazos por criticidade", "barra", "Criticidade",
                 "Prazos", _contagem(df, "criticidade", "Prazos", ORDEM_CRITICIDADE),
                 "Crítica: até 30 dias; Alta: até 90 dias."),
        _grafico("radar-mes", "Prazos por mês", "linha", "Mês", "Prazos",
                 [{"nome": "Prazos", "pontos": _pontos(por_mes)}]),
    ]


def painel_triagem(sujeito: Sujeito) -> list[dict]:
    vistos = [e for e in envios.listar()
              if e.status in envios.STATUS_TRIADO
              and envios.pode_ver(sujeito.persona, sujeito.acesso, e)]
    df = pd.DataFrame([{"nivel": e.nivel_sugerido, "setor": e.setor_dono,
                        "aprovacao": e.aprovacao or "-"} for e in vistos],
                      columns=["nivel", "setor", "aprovacao"])
    # Rótulo fixo do tipo ("Código-fonte"), nunca o trecho variável depois de ":".
    achados = pd.DataFrame([{"tipo": str(m.get("rotulo", "")).split(":")[0].strip() or "Outro"}
                            for e in vistos for m in e.motivos
                            if m.get("nivel") == "Sigilosa"], columns=["tipo"])
    return [
        _grafico("triagem-nivel", "Envios por classificação sugerida", "pizza", "Classificação",
                 "Envios", _contagem(df, "nivel", "Envios")),
        _grafico("triagem-setor", "Envios por setor dono sugerido", "barra", "Setor", "Envios",
                 _contagem(df, "setor", "Envios")),
        _grafico("triagem-nivel-setor", "Classificação x setor", "heatmap", "Setor", "Envios",
                 _cruzado(df, "setor", "nivel")),
        _grafico("triagem-achados", "Tipos de dado sigiloso encontrados", "barra", "Tipo",
                 "Ocorrências em envios", _contagem(achados, "tipo", "Envios")),
        _grafico("triagem-aprovacao", "Situação da aprovação", "barra", "Situação", "Envios",
                 _contagem(df, "aprovacao", "Envios")),
    ]


def painel_uso(sujeito: Sujeito, dias: int = 30) -> list[dict]:
    if sujeito.persona is None or not sujeito.persona.governanca:
        raise SemPermissao("O painel de uso é só da governança (curadoria e diretoria).")
    nota = f"Últimos {dias} dias. Agregado por dia, nunca por pessoa (LGPD art. 6º, III)."
    try:
        linhas = audit_log.resumo(dias)
    except Exception as erro:  # noqa: BLE001 - banco fora do ar não derruba a tela
        log.warning("Painel uso sem dados: %s", type(erro).__name__)
        linhas, nota = [], "Trilha de auditoria indisponível no momento."
    df = pd.DataFrame(linhas, columns=["dia", "acao", "resultado", "intent", "nivel", "total"])
    if df.empty:
        por_dia = por_intent = por_nivel = pd.Series(dtype=float)
        resultado: list[dict] = []
    else:
        por_dia = df.groupby("dia")["total"].sum().sort_index()
        por_intent = df.groupby("intent")["total"].sum().sort_values(ascending=False).head(10)
        por_nivel = df.groupby("nivel")["total"].sum()
        tabela = df.pivot_table(index="dia", columns="resultado", values="total",
                                aggfunc="sum", fill_value=0).sort_index()
        resultado = [{"nome": str(c), "pontos": _pontos(tabela[c])} for c in tabela.columns]
    return [
        _grafico("uso-dia", "Eventos por dia", "linha", "Dia", "Eventos",
                 [{"nome": "Eventos", "pontos": _pontos(por_dia)}], nota),
        _grafico("uso-resultado", "Permitido, bloqueado e abstenção por dia", "barra_empilhada",
                 "Dia", "Eventos", resultado, nota),
        _grafico("uso-intent", "Intenções mais frequentes", "barra", "Intenção", "Eventos",
                 [{"nome": "Eventos", "pontos": _pontos(por_intent)}], nota),
        _grafico("uso-nivel", "Eventos por nível de sigilo", "pizza", "Nível", "Eventos",
                 [{"nome": "Eventos", "pontos": _pontos(por_nivel)}], nota),
    ]


def montar(painel: str, sujeito: Sujeito, hoje: date) -> list[dict]:
    if painel == "acervo":
        return painel_acervo(sujeito)
    if painel == "radar":
        return painel_radar(sujeito, hoje)
    if painel == "triagem":
        return painel_triagem(sujeito)
    return painel_uso(sujeito)
