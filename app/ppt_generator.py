from datetime import datetime
from pathlib import Path
from typing import Any


def build_executive_slides_payload() -> dict[str, Any]:
    return {
        "tituloDeck": "Apresentação Executiva — Programa Ideias em Campo (Edição 2027)",
        "subtitulo": "Gerado via Raiz IQ Zero-Click • Fontes: RG_1100 v2.0.0, NT_2026-021 v1.0.0, NG_1130 v1.0.0",
        "geradoEm": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "slides": [
            {
                "numero": 1,
                "titulo": "Orçamento Oficial 2027 (R$ 96.000,00) & Histórico 2026",
                "destaque": "Conversão histórica de 17,8% (118 ideias -> 21 protótipos em 2026)",
                "itens": [
                    "Kits de Prototipagem: R$ 36.000,00 (37,5% do orçamento)",
                    "Semana de Imersão: R$ 30.000,00 (31,3% do orçamento)",
                    "Premiação Geral (1º R$ 8k, 2º R$ 5k, 3º R$ 3k): R$ 16.000,00 (16,7%)",
                    "Premiação Destaques por Arena (4 arenas x R$ 2.000): R$ 8.000,00 (8,3%)",
                    "Comunicação Institucional: R$ 6.000,00 (6,3%)",
                ],
                "rodapeCitacao": "Fonte auditada: NT_2026-021 v1.0.0 (Itens 2.1 e 3.2) aprovada pela DIRAF em 16/10/2026.",
            },
            {
                "numero": 2,
                "titulo": "Calendário das 7 Fases (01/02 a 30/06/2027) & Elegibilidade",
                "destaque": "Redução de 3 para 2 ideias por pessoa + mínimo de 6 meses de casa",
                "itens": [
                    "Fase 1 (Inscrição): 01/02/2027 a 28/02/2027 nas 4 Arenas (Operação, Tecnologia, Pessoas, Sustentabilidade)",
                    "Fase 2 (Triagem NIN): Até 12/03/2027 | Fase 3 (Votação Interna - Top 20, máx 6/arena): 15/03 a 26/03/2027",
                    "Fase 4 (Imersão presencial/integral): 05/04/2027 a 09/04/2027",
                    "Fase 5 (Prototipagem TRL >= 4 com 4h/semana liberadas): 12/04/2027 a 31/05/2027",
                    "Fase 6 (Banca Final - 5 membros sendo 1 DIRAF): 15/06/2027 | Fase 7 (Premiação em folha): 30/06/2027",
                ],
                "rodapeCitacao": "Fonte auditada: RG_1100 v2.0.0 (aprovado pela DIRTEC em 20/10/2026, substitui RG_1100 v1.0.0).",
            },
            {
                "numero": 3,
                "titulo": "Matriz de Alçadas de Prototipagem (NG_012) & Trava Fiscal (31/03)",
                "destaque": "R$ 18.000,00 vs R$ 18.000,01: gatilho imediato de Diretoria",
                "itens": [
                    "Até R$ 18.000,00 por protótipo: Aprovação pelo Gerente do NIN",
                    "De R$ 18.000,01 a R$ 120.000,00: Aprovação pelo Diretor da DIRTEC (NT_2026-021 item 4.3)",
                    "Acima de R$ 120.000,00: Aprovação pelo Comitê de Alçadas",
                    "Ciclo de Incentivo Fiscal (PX_1130-001): Tese até 31/01 -> TRAVA CRÍTICA de documentação em 31/03 -> Declaração DIRAF até 31/07",
                ],
                "rodapeCitacao": "Fonte auditada: NT_2026-021 v1.0.0 (Item 4.3), PX_1130-001 v1.0.0 e NG_1130 v1.0.0.",
            },
        ],
    }


def generate_ideias_em_campo_pptx() -> dict[str, Any]:
    """
    Gera o arquivo físico .pptx (usando python-pptx quando instalado, ou fallback estruturado)
    com os slides executivos do Programa Ideias em Campo 2027 e citações nas notas do apresentador.
    """
    payload = build_executive_slides_payload()
    base_dir = Path(__file__).resolve().parent.parent
    out_dir = base_dir / "reports_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    pptx_path = out_dir / "ideias_em_campo_2027_executivo.pptx"

    pptx_generated = False
    try:
        from pptx import Presentation

        prs = Presentation()
        for slide_data in payload["slides"]:
            slide_layout = prs.slide_layouts[1]  # Title and Content
            slide = prs.slides.add_slide(slide_layout)
            slide.shapes.title.text = slide_data["titulo"]

            tf = slide.placeholders[1].text_frame
            tf.text = slide_data["destaque"]
            for item in slide_data["itens"]:
                p = tf.add_paragraph()
                p.text = item
                p.level = 1

            # Citações nas notas do apresentador (Speaker Notes)
            notes_slide = slide.notes_slide
            notes_slide.notes_text_frame.text = (
                f"{slide_data['rodapeCitacao']} | Em caso de divergência, prevalece o documento oficial."
            )

        prs.save(str(pptx_path))
        pptx_generated = True
    except Exception:
        pptx_generated = False

    payload["arquivo_pptx"] = str(pptx_path.name) if pptx_generated else "fallback_json_estruturado"
    payload["pptx_fisico_gerado"] = pptx_generated
    return payload
