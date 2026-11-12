"""Guardas do chat: mascaramento de dados pessoais, regras revogadas e lacunas conhecidas."""

import re
from dataclasses import dataclass

from app.services.agent.intents import Parametros

# ---------- dados pessoais (LGPD art. 6º, III e art. 46) ----------
_PII = [
    (re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"), "[CPF]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"), "[E-MAIL]"),
    (re.compile(r"(matr[ií]cula)\s*:?\s*\d+", re.IGNORECASE), r"\1 [MATRÍCULA]"),
    (re.compile(r"\(?\b\d{2}\)?\s?9?\d{4}-?\d{4}\b"), "[TELEFONE]"),
]


def mascarar(texto: str) -> str:
    """Remove identificadores diretos antes de qualquer envio ao LLM."""
    for padrao, troca in _PII:
        texto = padrao.sub(troca, texto)
    return texto


# ---------- saída do modelo ----------
_URL = re.compile(r"!?\[[^\]]*\]\([^)]*\)|https?://\S+|<[^>]+>")


def limpar_saida(texto: str) -> str:
    """Tira links, imagens e HTML da resposta do modelo (evita exfiltração e phishing)."""
    return _URL.sub("", texto).strip()


# ---------- regras revogadas ("pegadinhas" de versão) ----------
@dataclass
class Revogada:
    fontes: list[str]
    codigo: str
    versao_revogada: str
    substituido_por: str
    pegadinha: str
    resposta: str


def regra_revogada(p: Parametros) -> Revogada | None:
    ferias = p.tem("ferias", "antecedencia", "solicit", "pedir", "pedido")
    if (30 in p.dias and ferias and not p.tem("aviso", "assin")) or p.tem("ng_111 v2", "v2.0.0"):
        return Revogada(
            fontes=["NG_111", "TB_1111-001"],
            codigo="NG_111 v2.0.0",
            versao_revogada="v2.0.0 (Fase: Versão anterior, embora o cabeçalho traga vigência "
                            "até 10/06/2027)",
            substituido_por="NG_111 v3.0.0 (em 03/08/2026)",
            pegadinha="A v2.0.0 exigia 30 dias de antecedência (item 2.3). A v3.0.0 vigente exige "
                      "45 dias corridos (item 4.5.1).",
            resposta="**Eram 30 dias na NG_111 v2.0.0, que foi substituída em 03/08/2026.** "
                     "Hoje vale a v3.0.0: a solicitação precisa de **45 dias corridos** de "
                     "antecedência.",
        )
    if p.tem("3 ideias", "tres ideias") or (p.tem("ideia") and p.tem("2026", "ano passado",
                                                                    "antes", "v1")):
        return Revogada(
            fontes=["RG_1100"],
            codigo="RG_1100 v1.0.0",
            versao_revogada="v1.0.0 (edição 2026, aprovada em 02/03/2026)",
            substituido_por="RG_1100 v2.0.0 (em 20/10/2026)",
            pegadinha="A edição 2026 permitia até 3 ideias por proponente. A edição 2027 permite "
                      "até 2, contando as de equipe (item 4.1.2).",
            resposta="**Não. Na edição 2027 são até 2 ideias por proponente**, contando as "
                     "inscritas em equipe (RG_1100 v2.0.0, item 4.1.2). O limite de 3 ideias era "
                     "da v1.0.0, substituída em 20/10/2026.",
        )
    return None


# ---------- lacunas conhecidas (abstenção honesta) ----------
@dataclass
class Lacuna:
    fontes: list[str]  # documentos que o sujeito precisa enxergar para receber esta resposta
    dominio: str
    lacuna: str
    detalhes: list[str]
    resposta: str


def lacuna_conhecida(p: Parametros) -> Lacuna | None:
    premio = p.tem("premio", "premiacao")
    if premio and p.tem("divid", "divis", "rate", "equipe", "cada integrante", "quem recebe"):
        return Lacuna(
            fontes=["RG_1100"],
            dominio="NIN",
            lacuna="Divisão do prêmio em dinheiro entre os integrantes de uma ideia de equipe.",
            detalhes=[
                "O RG_1100 v2.0.0 fixa os valores dos prêmios e o pagamento em folha em até 30 "
                "dias (item 4.5.4), mas não define como dividir o valor entre até 4 integrantes.",
            ],
            resposta="**Não consta nas fontes.** O RG_1100 v2.0.0 fixa os valores dos prêmios, "
                     "mas não diz como dividi-los entre os integrantes de uma equipe.",
        )
    if p.tem("afastad", "afastament", "licenca") and p.tem("ideia", "inscri", "programa",
                                                         "inovacao"):
        return Lacuna(
            fontes=["NT_2026-021"],
            dominio="NIN",
            lacuna="Participação de empregado afastado na data da inscrição do Ideias em Campo.",
            detalhes=["A NT_2026-021 (item 5.4) diz que não trata desse caso e manda consultar "
                      "o NIN."],
            resposta="**Não consta nas fontes.** A NT_2026-021 (item 5.4) registra que não trata "
                     "de empregados afastados na data da inscrição e orienta consultar o NIN.",
        )
    if p.tem("ng_012", "ng_010", "ng 012", "ng 010"):
        return Lacuna(
            fontes=["NT_2026-021"],
            dominio="NIN",
            lacuna="Texto integral da NG_010 e da NG_012.",
            detalhes=[
                "A NG_010 (gestão de documentos) e a NG_012 (alçadas) são citadas por vários "
                "documentos, mas não fazem parte do acervo disponível.",
                "As faixas de alçada que constam nas fontes estão na NT_2026-021 (itens 4.2 a "
                "4.4) e na NT_2026-018 (Anexo F).",
            ],
            resposta="**A NG_010 e a NG_012 não estão no acervo.** Só posso informar o que outros "
                     "documentos citam delas.",
        )
    return None
