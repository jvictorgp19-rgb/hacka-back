"""Respostas determinísticas: cada handler reconhece um tipo de pergunta e chama uma calculadora.

Um handler devolve Parcial (com as FONTES usadas) ou None. Quem autoriza é o roteador, que
confere as fontes no acervo ANTES de executar o cálculo.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.services.agent.intents import Parametros
from app.services.calculators import alcadas, contrato, ferias
from app.services.calculators import calendario as cal


@dataclass
class Parcial:
    answer: str
    bullets: list[str]
    fontes: list[str]
    intent: str
    abster_dominio: str | None = None  # preenchido quando parte da resposta não consta
    lacuna: str = ""
    detalhes: list[str] = field(default_factory=list)


@dataclass
class Handler:
    intent: str
    fontes: list[str]
    casa: Callable[[Parametros, str], bool]
    executa: Callable[[Parametros], Parcial | None]


def brl(valor: Decimal) -> str:
    inteiro, centavos = f"{valor:,.2f}".split(".")
    return f"R$ {inteiro.replace(',', '.')},{centavos}"


# ---------- férias ----------
def _casa_timeline(p: Parametros, tema: str) -> bool:
    contrato_ = p.tem("contrato", "rescis", "coworking", "prorrog", "ctr_")
    return bool(p.datas) and not contrato_ and (
        p.tem("ferias", "gozo", "descanso") or tema == "ferias")


def _timeline(p: Parametros) -> Parcial:
    inicio = p.datas[0]
    r = ferias.calcular_prazos_ferias(inicio)
    bullets = []
    if r.inicio_valido:
        bullets.append(f"**Início em {cal.br(inicio)} ({cal.nome_dia(inicio)}):** data válida "
                       "(NG_111 4.3.2).")
    else:
        bullets.append(f"**Atenção — início não permitido:** {r.motivo_invalido} O início deve "
                       "ser em dia útil, fora dos 2 dias úteis que antecedem feriado ou descanso "
                       "semanal (NG_111 4.3.2). Os prazos abaixo valem se a data for mantida.")
    for m in r.marcos:
        obs = f" {m.observacao}" if m.observacao else ""
        bullets.append(f"**{m.marco} — {cal.br(m.data)} ({cal.nome_dia(m.data)}):** {m.etapa}. "
                       f"Responsável: {m.responsavel} ({m.item}).{obs}")
    solicitar = r.marcos[0].data
    return Parcial(
        f"Para iniciar as férias em **{cal.br(inicio)}**, solicite no Portal Raiz até "
        f"**{cal.br(solicitar)}** (45 dias corridos antes).",
        bullets, r.fontes, "ferias_prazos")


def _faltas(p: Parametros) -> Parcial:
    dias = ferias.dias_por_faltas(p.faltas)
    if dias:
        resposta = (f"Com **{p.faltas} faltas injustificadas** no período aquisitivo, o direito é "
                    f"de **{dias} dias corridos** de férias.")
    else:
        resposta = (f"Com **{p.faltas} faltas injustificadas** (mais de 32), há **perda do direito "
                    "às férias** naquele período aquisitivo.")
    tabela = "0 a 5 faltas: 30 dias · 6 a 14: 24 dias · 15 a 23: 18 dias · 24 a 32: 12 dias · " \
             "mais de 32: perda do direito."
    return Parcial(resposta, [f"**TB_1111-001, Tabela 1:** {tabela}",
                              "A regra geral está na NG_111, item 4.1.1."],
                   ferias.FONTES_TABELAS, "ferias_faltas")


def _equipe(p: Parametros) -> Parcial:
    n = p.equipe
    maximo = ferias.limite_ausencia(n)
    conta = f"30% de {n} = {n * 0.3:.1f}".replace(".", ",")
    regra = "em equipes de até 3 empregados, uma pessoa por vez" if n <= 3 \
        else f"{conta}, arredondado para baixo"
    return Parcial(
        f"Em uma equipe de **{n}**, no máximo **{maximo}** "
        f"{'pessoa pode' if maximo == 1 else 'pessoas podem'} estar de férias ao mesmo tempo.",
        [f"**Cálculo:** {regra} (NG_111 4.6.3).",
         "**Conferência:** TB_1111-001, Tabela 4 — limites de ausência simultânea."],
        ferias.FONTES_TABELAS, "ferias_limite_equipe")


def _fracionamento(p: Parametros) -> Parcial:
    valido, motivo = ferias.validar_fracionamento(p.periodos)
    divisao = ", ".join(str(x) for x in p.periodos)
    return Parcial(
        f"A divisão em **{divisao} dias** {'é **válida**' if valido else '**não é válida**'}.",
        [motivo, "Regra: até 3 períodos; um com no mínimo 14 dias corridos e os demais com no "
                 "mínimo 5 (NG_111 4.4.1 e 4.4.2).",
         "Cada período exige uma solicitação própria, com prazos contados do início dele "
         "(NG_111 4.4.3)."],
        ["NG_111"], "ferias_fracionamento")


def _ressarcimento(p: Parametros) -> Parcial:
    despesa = p.valores[0]
    valor = ferias.ressarcimento_cancelamento(despesa)
    return Parcial(
        f"Para uma despesa comprovada de {brl(despesa)}, o ressarcimento é de **{brl(valor)}**.",
        ["Vale só para alteração por necessidade de serviço, decidida pelo diretor da área "
         "(NG_111 4.9.2).",
         "A ACME ressarce despesas comprovadas e não reembolsáveis até R$ 2.500,00 por evento "
         "(NG_111 4.9.3)."],
        ["NG_111"], "ferias_ressarcimento")


# ---------- alçadas ----------
def _casa_alcada(p: Parametros, tema: str) -> bool:
    return bool(p.valores) and p.tem("aprova", "alcada", "autoriza", "quem assina", "quem decide")


def _alcada(p: Parametros) -> Parcial:
    contexto = "geral" if p.tem("contrat", "coworking", "locacao", "aluguel") else "inovacao"
    bullets, fontes, sem_resposta = [], [], None
    for valor in p.valores[:3]:
        a = alcadas.quem_aprova(valor, contexto)
        fontes += a.fontes
        if a.aprovador is None:
            sem_resposta = valor
            bullets.append(f"**{brl(valor)}:** não consta nas fontes. A faixa acima de "
                           "R$ 120.000,00 está na NG_012, que não faz parte do acervo.")
        else:
            bullets.append(f"**{brl(valor)}:** {a.aprovador} — faixa \"{a.faixa}\" ({a.item}).")
    if contexto == "inovacao":
        bullets.append("Faixas de prototipagem: até R$ 18.000,00, gerente do NIN; de R$ 18.000,01 "
                       "a R$ 120.000,00, diretor da DIRTEC; acima disso, Comitê de Alçadas "
                       "(NT_2026-021, itens 4.2 a 4.4).")
    primeiro = alcadas.quem_aprova(p.valores[0], contexto)
    resposta = (f"Um gasto de **{brl(p.valores[0])}** é aprovado por: "
                f"**{primeiro.aprovador or 'não consta nas fontes'}**.")
    parcial = Parcial(resposta, bullets, list(dict.fromkeys(fontes)), "alcada")
    if sem_resposta is not None:
        parcial.abster_dominio = "GESUC"
        parcial.lacuna = "Aprovador de gastos gerais acima de R$ 120.000,00 (NG_012)."
        parcial.detalhes = ["A NT_2026-018 (Anexo F) cita só as faixas de gerente e de diretor."]
    return parcial


# ---------- contrato ----------
def _casa_contrato(p: Parametros, tema: str) -> bool:
    assunto = p.tem("contrato", "ctr_2026", "coworking", "locacao", "aluguel", "locadora") \
        or tema == "locacao"
    return assunto and not p.tem("ferias") and p.tem(
        "rescis", "rescind", "multa", "prorrog", "vistoria", "internet", "glosa", "desconto",
        "prazo", "vence", "vigencia", "pagamento", "nota fiscal", "atesto", "este mes",
        "preciso fazer")


def _data_de_rescisao(p: Parametros) -> date | None:
    if p.datas:
        return p.datas[0]
    if p.mes_ano:
        mes, ano = p.mes_ano
        for candidato in ([ano] if ano else [2026, 2027]):
            d = date(candidato, mes, 15)
            if contrato.INICIO <= d <= contrato.FIM:
                return d
    return None


def _contrato(p: Parametros) -> Parcial:
    c = contrato
    bullets = []
    resposta = (f"O CTR_2026-012 vigora de {cal.br(c.INICIO)} a {cal.br(c.FIM)} (150 dias), com "
                f"aluguel de {brl(c.ALUGUEL)} por mês.")
    if p.tem("rescis", "rescind", "multa"):
        d = _data_de_rescisao(p)
        if d and c.INICIO <= d <= c.FIM:
            r = c.multa_rescisao(d)
            resposta = (f"**Multa de {brl(r.multa)}.** " if r.multa else "**Não há multa.** ") \
                + r.explicacao
        else:
            resposta = (f"A multa de rescisão depende da data: até o 90º dia "
                        f"({cal.br(c.ULTIMO_DIA_COM_MULTA)}) é de {brl(c.ALUGUEL)}; depois, "
                        "não há multa.")
        bullets.append("**Cláusula 13ª:** a LOCATÁRIA pode rescindir com aviso por escrito de 30 "
                       "dias corridos. Até o 90º dia de vigência, multa de um aluguel mensal; a "
                       "partir do 91º, sem multa.")
    if p.tem("prorrog", "vence", "prazo", "este mes", "preciso fazer", "vigencia"):
        bullets.append(f"**Prorrogação:** pedir até **{cal.br(c.PRORROGACAO_ATE)}** (30 dias "
                       f"corridos antes do fim). Prazo total máximo de {c.PRAZO_MAXIMO_MESES} "
                       f"meses; cada aditivo acresce até 20% do valor global, ou "
                       f"{brl(c.ADITIVO_MAXIMO)} (Cláusulas 2ª e 3ª).")
    if p.tem("vistoria", "este mes", "preciso fazer"):
        bullets.append(f"**Vistoria:** até {cal.br(c.VISTORIA_ATE)}, 5 dias corridos antes do "
                       "início, com termo assinado (Cláusula 6ª).")
    if p.tem("internet", "glosa", "desconto"):
        bullets.append(f"**Internet:** desconto de 1/30 do aluguel, ou {brl(c.GLOSA_DIARIA)}, por "
                       "dia com interrupção superior a 4 horas (Anexo, item 11).")
    if p.tem("pagamento", "nota fiscal", "atesto", "este mes", "preciso fazer"):
        bullets.append("**Rotina mensal:** nota fiscal até o dia 25; atesto do fiscal técnico em "
                       "até 5 dias úteis; pagamento pela GFI até o dia 8 do mês de uso, ou no dia "
                       "útil seguinte (Cláusulas 8ª a 10ª).")
    if not bullets:
        bullets.append(f"**Prorrogação:** pedir até {cal.br(c.PRORROGACAO_ATE)} (Cláusula 3ª).")
    return Parcial(resposta, bullets, c.FONTES, "contrato")


HANDLERS: list[Handler] = [
    Handler("contrato", contrato.FONTES, _casa_contrato, _contrato),
    Handler("ferias_fracionamento", ["NG_111"],
            lambda p, t: len(p.periodos) >= 2 and p.tem("fracion", "divid", "period", "parcel"),
            _fracionamento),
    Handler("ferias_prazos", ferias.FONTES_PRAZOS, _casa_timeline, _timeline),
    Handler("ferias_limite_equipe", ferias.FONTES_TABELAS,
            lambda p, t: p.equipe is not None and not p.tem("ideia", "premio")
            and p.tem("ferias", "junt", "simultan", "mesmo tempo", "sair", "ausen", "30%"),
            _equipe),
    Handler("ferias_faltas", ferias.FONTES_TABELAS,
            lambda p, t: p.faltas is not None and p.faltas <= 366, _faltas),
    Handler("ferias_ressarcimento", ["NG_111"],
            lambda p, t: bool(p.valores) and p.tem("ressarc", "reembols"), _ressarcimento),
    Handler("alcada_inovacao", ["NT_2026-021"],
            lambda p, t: _casa_alcada(p, t)
            and not p.tem("contrat", "coworking", "locacao", "aluguel"), _alcada),
    Handler("alcada_geral", ["NT_2026-018"],
            lambda p, t: _casa_alcada(p, t)
            and p.tem("contrat", "coworking", "locacao", "aluguel"), _alcada),
]
