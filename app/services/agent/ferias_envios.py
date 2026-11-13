"""Férias pelo que a pessoa enviou: "quantos dias de férias eu tenho?" sem dizer as faltas.

Usa os fatos que a triagem tirou dos arquivos da própria pessoa: faltas injustificadas, período
aquisitivo e datas (app/services/triagem/ferias.py). Regra: NG_111 4.1.1 e TB_1111-001,
Tabela 1. Só responde sobre a própria pessoa. Os dados de outra pessoa ficam com a GEPEC.
"""

from datetime import date

from app.core.auth import Sujeito
from app.services import envios
from app.services.agent.handlers import Parcial
from app.services.agent.intents import Parametros
from app.services.calculators import ferias
from app.services.calculators.calendario import br

INTENT = "ferias_meus_envios"
TABELA = ("0 a 5 faltas: 30 dias · 6 a 14: 24 dias · 15 a 23: 18 dias · 24 a 32: 12 dias · "
          "mais de 32: perda do direito.")


def casa(p: Parametros) -> bool:
    """Pergunta sobre os próprios dias de férias, sem informar as faltas.

    "Quantos dias" sozinho não basta: "quantos dias de antecedência para pedir férias?" é regra
    da NG_111, não saldo de quem pergunta.
    """
    return (p.faltas is None and p.tem("ferias") and not p.tem("antecedencia")
            and p.tem("quantos dias de ferias", "quantos dia de ferias", "tenho direito",
                      "meu direito", "meu saldo", "minhas ferias", "eu tenho", "eu teria",
                      "teria de ferias"))


def _br(iso: str | None) -> str | None:
    return br(date.fromisoformat(iso)) if iso else None


def responder(sujeito: Sujeito) -> Parcial:
    lista = envios.ferias_de(sujeito.id) if sujeito.persona else []
    com_faltas = [e for e in lista if e.fatos_ferias.get("faltas_injustificadas") is not None]
    if not com_faltas:
        bullets = [f"**TB_1111-001, Tabela 1:** {TABELA}",
                   "A regra geral está na NG_111, item 4.1.1."]
        if sujeito.persona and envios.enviou_formulario_de_outro(sujeito.id):
            bullets.insert(0, "Um formulário que você enviou está em nome de outra pessoa: ele "
                              "não entra no seu cálculo. Os dados de outro empregado ficam com a "
                              "GEPEC.")
        return Parcial(
            "**Não encontrei faltas injustificadas nos arquivos que você enviou.** Envie o "
            "formulário FM_1111-001 preenchido ou o espelho de ponto, ou diga o número de faltas "
            "(por exemplo: \"tenho 7 faltas injustificadas\").",
            bullets,
            ferias.FONTES_TABELAS, INTENT, abster_dominio="GEPEC",
            lacuna="Faltas injustificadas do período aquisitivo não constam nos seus envios.")

    envio = com_faltas[0]  # o mais recente
    f = envio.fatos_ferias
    faltas = f["faltas_injustificadas"]
    dias = ferias.dias_por_faltas(faltas)
    periodo = (f" no período aquisitivo de {_br(f['periodo_inicio'])} a {_br(f['periodo_fim'])}"
               if f.get("periodo_inicio") else " no período aquisitivo")
    origem = ("contadas no espelho de ponto" if f.get("origem_faltas") == "contagem"
              else "informadas no formulário")
    if dias:
        resposta = (f"Pelo arquivo que você enviou, você tem **{faltas} faltas injustificadas**"
                    f"{periodo}: o direito é de **{dias} dias corridos** de férias.")
    else:
        resposta = (f"Pelo arquivo que você enviou, você tem **{faltas} faltas injustificadas**"
                    f"{periodo}: mais de 32 faltas, **perda do direito** às férias nesse período.")
    bullets = [f"**Seu envio:** {envio.nome_arquivo} ({br(envio.criado_em.date())}), faltas "
               f"{origem}.",
               f"**TB_1111-001, Tabela 1:** {TABELA}",
               "A regra geral está na NG_111, item 4.1.1."]
    if f.get("admissao"):
        bullets.append(f"**Admissão:** {_br(f['admissao'])}. O período aquisitivo são 12 meses "
                       "de vínculo contados da admissão (NG_111).")
    if f.get("inicio_gozo"):
        bullets.append(f"**Início de gozo informado:** {_br(f['inicio_gozo'])}. Pergunte \"quais "
                       "os prazos para férias em DD/MM/AAAA\" para ver o cronograma.")
    if envio.aprovacao == "pendente":
        bullets.append("O envio ainda aguarda aprovação: trate o cálculo como provisório.")
    if f.get("titular") == "nao_informado":
        bullets.append("O arquivo não traz o nome do empregado: confira se ele é seu.")
    bullets.append("O número vem do que você enviou. A GEPEC confere no sistema de ponto.")
    outros = len(com_faltas) - 1
    if outros:
        bullets.append(f"Há mais {outros} envio(s) seu(s) com faltas; usei o mais recente.")
    return Parcial(resposta, bullets, ferias.FONTES_TABELAS, INTENT)
