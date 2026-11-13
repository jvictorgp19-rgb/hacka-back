"""Radar de prazos: detecção antecipada por regra e calendário (não é previsão por ML).

Cada evento declara as fontes; o sujeito só recebe eventos de documentos que pode ver.
"""

from dataclasses import dataclass
from datetime import date

from app.core.auth import Sujeito
from app.services.acervo import Acervo
from app.services.calculators import contrato as ctr


@dataclass
class _Evento:
    data: date
    titulo: str
    documento: str
    responsavel: str
    detalhe: str
    fontes: list[str]
    item: str = "cabeçalho"  # trecho do acervo que fundamenta o prazo (citação no front)


def _proxima(mes: int, dia: int, hoje: date) -> date:
    d = date(hoje.year, mes, dia)
    return d if d >= hoje else date(hoje.year + 1, mes, dia)


def _eventos(acervo: Acervo, hoje: date) -> list[_Evento]:
    c = ["CTR_2026-012"]
    eventos = [
        _Evento(ctr.VISTORIA_ATE, "Vistoria do espaço de coworking", "CTR_2026-012 v1.0.0",
                "GOC (fiscal técnico)",
                "Vistoria obrigatória até 5 dias corridos antes do início da vigência, com termo "
                "assinado (Cláusula 6ª).", c, "Cláusula Sexta"),
        _Evento(ctr.ULTIMO_DIA_COM_MULTA, "Último dia com multa de rescisão (90º dia)",
                "CTR_2026-012 v1.0.0", "GCO (gestor do contrato)",
                "Até esta data a rescisão pela LOCATÁRIA custa um aluguel (R$ 3.650,00). A partir "
                "do 91º dia não há multa; o aviso de 30 dias continua exigido (Cláusula 13ª).", c,
                "Cláusula Décima Terceira"),
        _Evento(ctr.PRORROGACAO_ATE, "Data-limite para pedir a prorrogação do contrato",
                "CTR_2026-012 v1.0.0", "GCO (gestor do contrato)",
                "O pedido é feito até 30 dias corridos antes do fim da vigência (29/04/2027). "
                "Prazo total máximo de 24 meses (Cláusulas 2ª e 3ª).", c,
                "Cláusula Terceira"),
        _Evento(ctr.FIM, "Fim da vigência do contrato de coworking", "CTR_2026-012 v1.0.0",
                "GCO (gestor do contrato)", "Vigência de 150 dias corridos (Cláusula 2ª).", c,
                "Cláusula Segunda"),
        _Evento(_proxima(3, 31, hoje), "Consolidação do relatório de incentivo fiscal",
                "PX_1130-001 v1.0.0", "NIN e DIRAF",
                "Projetos sem documentação técnica e financeira até 31/03 ficam fora do ciclo "
                "do ano.", ["PX_1130-001"], "8.6.4"),
        _Evento(_proxima(1, 31, hoje), "Publicação da Tese de Inovação do ano",
                "NG_1130 v1.0.0", "NIN", "Prazo anual: até 31 de janeiro (item 4.4).",
                ["NG_1130"], "4.4"),
        _Evento(_proxima(7, 31, hoje), "Declaração do incentivo fiscal", "PX_1130-001 v1.0.0",
                "DIRAF", "Prazo anual: até 31 de julho.", ["PX_1130-001"], "8.6.3"),
        _Evento(date(2027, 2, 28), "Fim das inscrições do Ideias em Campo 2027",
                "RG_1100 v2.0.0", "Proponentes e NIN",
                "Inscrições de 01/02/2027 a 28/02/2027; até 2 ideias por proponente "
                "(item 4.1.2).", ["RG_1100"], "4.2"),
        _Evento(_proxima(10, 31, hoje), "Fim do registro da intenção de férias do ano seguinte",
                "NG_111 v3.0.0", "Empregado",
                "Registro no Portal Raiz entre 1º e 31 de outubro (item 4.2.1).", ["NG_111"],
                "4.2.1"),
        _Evento(_proxima(11, 30, hoje), "Consolidação da programação de férias da equipe",
                "NG_111 v3.0.0", "Gestor imediato", "Até 30 de novembro (item 4.2.2).",
                ["NG_111"], "4.2.2"),
        _Evento(_proxima(12, 15, hoje), "Publicação do calendário institucional de férias",
                "NG_111 v3.0.0", "GGC", "Até 15 de dezembro (item 4.2.3).", ["NG_111"], "4.2.3"),
        _Evento(_proxima(1, 31, hoje), "Fim do pedido de adiantamento do 13º salário",
                "NG_111 v3.0.0", "Empregado",
                "Pedido entre 1º e 31 de janeiro, no Portal Raiz (item 4.8.1).", ["NG_111"],
                "4.8.1"),
    ]
    # Normas com vigência de 18 meses: avisar quando o fim se aproxima.
    for doc in acervo.documentos:
        cab = acervo.cabecalhos.get(f"{doc.codigo}@{doc.versao}", {})
        if doc.vigente and doc.tipo in ("NG", "PX") and cab.get("vigencia_fim"):
            eventos.append(_Evento(
                date.fromisoformat(cab["vigencia_fim"]), f"Fim da vigência da {doc.codigo}",
                f"{doc.codigo} v{doc.versao}", doc.dominio,
                "Normas e procedimentos valem 18 meses a partir da aprovação; a área dona deve "
                "revisar antes do vencimento.", [doc.codigo]))
    return eventos


def criticidade(dias: int) -> str:
    return "Crítica" if dias <= 30 else "Alta" if dias <= 90 else "Normal"


def eventos_visiveis(acervo: Acervo, sujeito: Sujeito, hoje: date) -> list[_Evento]:
    """Eventos futuros cujas fontes o sujeito pode ver, do mais próximo ao mais distante."""
    return sorted((e for e in _eventos(acervo, hoje)
                   if e.data >= hoje and acervo.autorizado(e.fontes, sujeito.acesso)),
                  key=lambda e: e.data)

