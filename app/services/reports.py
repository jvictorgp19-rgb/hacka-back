"""Relatório executivo: deck em JSON (contrato do front) e arquivo .pptx.

Os números saem do seed de fatos e das calculadoras, não do LLM. Cada slide declara as fontes.
O relatório herda a MAIOR classificação das fontes (high-water mark) e só é gerado para quem
pode ver todas elas. O .pptx é montado em memória, com nome de arquivo fixo por tema.
"""

from datetime import datetime
from io import BytesIO

from pptx import Presentation
from pptx.util import Inches, Pt

from app.schemas.api import ReportResponse, Slide
from app.services.acervo import Acervo
from app.services.agent.handlers import brl
from app.services.calculators import calendario as cal
from app.services.calculators import contrato as ctr

FONTES = {
    "inovacao": ["RG_1100", "NT_2026-021", "PX_1130-001", "NG_1130"],
    "ferias": ["NG_111", "TB_1111-001", "PX_1111-001"],
    "locacao": ["CTR_2026-012", "NT_2026-018"],
}
ARQUIVO = {"inovacao": "ideias-em-campo-2027.pptx", "ferias": "ferias.pptx",
           "locacao": "contrato-coworking.pptx"}


def _dinheiro(valor: float) -> str:
    from decimal import Decimal
    return brl(Decimal(str(valor)))


def _inovacao(seed: dict) -> tuple[str, list[Slide]]:
    r = seed["jornadas_por_tema"]["inovacao"]["regras_simuladores"]
    orcamento = [
        f"{i['item']}: {_dinheiro(i['valor'])} ({str(i['participacao_pct']).replace('.', ',')}%)"
        for i in r["composicao_orcamento_2027"]]
    fases = [f"Fase {f['fase']} — {f['nome']}: {f['periodo']} ({f['responsavel']})"
             for f in r["calendario_fases_2027"]]
    e = r["elegibilidade_2027"]
    return "Programa Ideias em Campo — Edição 2027", [
        Slide(numero=1, titulo=f"Orçamento 2027: {_dinheiro(r['orcamento_total_2027'])}",
              destaque="Aprovado pela DIRAF; fica abaixo do limite do Comitê de Alçadas.",
              itens=orcamento,
              rodapeCitacao="Fonte: NT_2026-021 v1.0.0 (itens 3 e 4.5)."),
        Slide(numero=2, titulo="Calendário das 7 fases e elegibilidade",
              destaque=f"Até {e['limite_ideias_por_pessoa']} ideias por pessoa e mínimo de "
                       f"{e['tempo_minimo_casa_meses']} meses de casa.",
              itens=fases,
              rodapeCitacao="Fonte: RG_1100 v2.0.0 (substitui a v1.0.0 desde 20/10/2026)."),
        Slide(numero=3, titulo="Alçadas de prototipagem e ciclo de incentivo fiscal",
              destaque="R$ 18.000,00 aprova o gerente do NIN; R$ 18.000,01 já exige o diretor "
                       "da DIRTEC.",
              itens=["Até R$ 18.000,00 por ideia: gerente do NIN",
                     "De R$ 18.000,01 a R$ 120.000,00: diretor da DIRTEC",
                     "Acima de R$ 120.000,00: Comitê de Alçadas",
                     *[f"{c['data_fixa']}: {c['acao']}" for c in r["ciclo_incentivo_fiscal"]]],
              rodapeCitacao="Fontes: NT_2026-021 v1.0.0 (itens 4.2 a 4.4) e PX_1130-001 v1.0.0."),
    ]


def _ferias(seed: dict) -> tuple[str, list[Slide]]:
    return "Férias — regras vigentes (NG_111 v3.0.0)", [
        Slide(numero=1, titulo="Prazos em camadas (D = início de gozo)",
              destaque="A antecedência subiu de 30 para 45 dias em 03/08/2026.",
              itens=["Solicitação: até D-45 (empregado)",
                     "Decisão do gestor: até 7 dias corridos; sem decisão, sobe ao diretor "
                     "(3 dias úteis)",
                     "Aviso pela GGC: até D-35",
                     "Assinatura do aviso: até 5 dias úteis e nunca depois de D-30",
                     "Pagamento pela GFI: até D-3, antecipado para o dia útil anterior"],
              rodapeCitacao="Fontes: NG_111 v3.0.0 (item 4.5) e TB_1111-001 v1.0.0 (Tabela 2)."),
        Slide(numero=2, titulo="Limites e direitos",
              destaque="No máximo 30% da equipe em férias ao mesmo tempo, arredondado para baixo.",
              itens=["Faltas injustificadas: 0–5 → 30 dias; 6–14 → 24; 15–23 → 18; 24–32 → 12; "
                     "mais de 32 → perda do direito",
                     "Fracionamento: até 3 períodos; um com 14 dias ou mais, os demais com 5 ou "
                     "mais",
                     "Abono pecuniário: até 10 dias, pedido na mesma solicitação",
                     "Alteração por necessidade de serviço: ressarcimento até R$ 2.500,00 por "
                     "evento"],
              rodapeCitacao="Fontes: NG_111 v3.0.0 (itens 4.4, 4.6.3, 4.7 e 4.9) e TB_1111-001 "
                            "v1.0.0."),
        Slide(numero=3, titulo="Calendário anual",
              destaque="A programação anual não substitui a solicitação formal.",
              itens=["1º a 31 de outubro: intenção de gozo do ano seguinte (empregado)",
                     "Até 30 de novembro: consolidação da equipe (gestor)",
                     "Até 15 de dezembro: calendário institucional (GGC)",
                     "1º a 31 de janeiro: pedido de adiantamento do 13º (empregado)"],
              rodapeCitacao="Fontes: NG_111 v3.0.0 (item 4.2) e TB_1111-001 v1.0.0 (Tabela 3)."),
    ]


def _locacao(seed: dict) -> tuple[str, list[Slide]]:
    return "Contrato de coworking CTR_2026-012", [
        Slide(numero=1, titulo="Objeto, prazo e valor",
              destaque=f"Valor global de {brl(ctr.VALOR_GLOBAL)}: alçada de diretor (DIRAF).",
              itens=["8 estações de trabalho e sala de reunião (até 40 horas mensais)",
                     f"Vigência: {cal.br(ctr.INICIO)} a {cal.br(ctr.FIM)} (150 dias corridos)",
                     f"Aluguel mensal: {brl(ctr.ALUGUEL)}, com condomínio, internet, energia e "
                     "limpeza",
                     "Prazo total máximo, com prorrogações: 24 meses"],
              rodapeCitacao="Fontes: CTR_2026-012 v1.0.0 (Cláusulas 1ª, 2ª e 7ª) e NT_2026-018 "
                            "v1.0.0."),
        Slide(numero=2, titulo="Marcos e riscos de prazo",
              destaque=f"Pedido de prorrogação até {cal.br(ctr.PRORROGACAO_ATE)}.",
              itens=[f"Vistoria até {cal.br(ctr.VISTORIA_ATE)}",
                     f"Rescisão até {cal.br(ctr.ULTIMO_DIA_COM_MULTA)} (90º dia): multa de "
                     f"{brl(ctr.ALUGUEL)}; depois, sem multa",
                     f"Cada aditivo acresce até 20% do valor global ({brl(ctr.ADITIVO_MAXIMO)})",
                     f"Inexecução: multa de 5% do valor global ({brl(ctr.MULTA_INEXECUCAO)})"],
              rodapeCitacao="Fonte: CTR_2026-012 v1.0.0 (Cláusulas 3ª, 6ª, 13ª e 15ª)."),
        Slide(numero=3, titulo="Rotina mensal",
              destaque="Sem atesto do fiscal técnico, não há pagamento.",
              itens=["Nota fiscal até o dia 25, referente ao mês seguinte",
                     "Atesto do fiscal técnico (GOC) em até 5 dias úteis",
                     "Pagamento pela GFI até o dia 8 do mês de uso, ou dia útil seguinte",
                     f"Internet fora do ar por mais de 4 horas: desconto de "
                     f"{brl(ctr.GLOSA_DIARIA)} por dia"],
              rodapeCitacao="Fonte: CTR_2026-012 v1.0.0 (Cláusulas 8ª a 10ª e Anexo, item 11)."),
    ]


_MONTADORES = {"inovacao": _inovacao, "ferias": _ferias, "locacao": _locacao}


def montar_deck(acervo: Acervo, tema: str) -> ReportResponse:
    titulo, slides = _MONTADORES[tema](acervo.seed)
    versoes = ", ".join(f"{d.codigo} v{d.versao}" for c in FONTES[tema]
                        if (d := acervo.vigente(c)))
    nivel = acervo.nivel_das_fontes(FONTES[tema])
    return ReportResponse(
        tituloDeck=f"Apresentação Executiva — {titulo}",
        subtitulo=f"Gerado pelo Raiz IQ • Classificação: {nivel} • Fontes: {versoes}",
        geradoEm=datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        slides=slides,
    )


def montar_pptx(deck: ReportResponse, nivel: str) -> bytes:
    prs = Presentation()
    capa = prs.slides.add_slide(prs.slide_layouts[0])
    capa.shapes.title.text = deck.tituloDeck
    capa.placeholders[1].text = deck.subtitulo
    for s in deck.slides:
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = s.titulo
        corpo = slide.placeholders[1].text_frame
        corpo.text = s.destaque
        corpo.paragraphs[0].font.bold = True
        for item in s.itens:
            paragrafo = corpo.add_paragraph()
            paragrafo.text = item
            paragrafo.level = 1
            paragrafo.font.size = Pt(16)
        rodape = slide.shapes.add_textbox(Inches(0.5), Inches(6.9), Inches(9), Inches(0.4))
        rodape.text_frame.text = f"Classificação: {nivel} • {s.rodapeCitacao}"
        rodape.text_frame.paragraphs[0].font.size = Pt(10)
        slide.notes_slide.notes_text_frame.text = (
            f"{s.rodapeCitacao}\nEm caso de divergência, prevalece o documento oficial.")
    prs.core_properties.title = deck.tituloDeck
    prs.core_properties.author = "Raiz IQ"
    prs.core_properties.keywords = f"classificacao:{nivel}"
    saida = BytesIO()
    prs.save(saida)
    return saida.getvalue()
