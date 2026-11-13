"""Gera app/seed/manifesto.json: a lista CURADA de documentos que podem ser ingeridos.

O manifesto fixa hash, domínio (setor dono), tema, classificação e setores de cada PDF.
A classificação e os setores seguem docs/CLASSIFICACAO_BBTS.md. O cabeçalho do PDF ("#interna")
nunca reduz a classificação. Rode de novo só quando o acervo ou a classificação mudar:
    python scripts/gerar_manifesto.py
"""

import hashlib
import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
BRONZE = RAIZ / "acervo" / "bronze"

TEMA = {"ferias": "ferias", "inovacao": "inovacao", "locacao": "locacao"}
DOMINIO = {
    "NG_111": "GEPEC", "PX_1111-001": "GEPEC", "FM_1111-001": "GEPEC", "TB_1111-001": "GEPEC",
    "FL_1111-001": "GEPEC", "NG_1130": "GEINOV", "PX_1130-001": "GEINOV", "RG_1100": "GEINOV",
    "NT_2026-021": "GEINOV", "CTR_2026-012": "GESUC", "NT_2026-018": "GESUC",
}
# docs/CLASSIFICACAO_BBTS.md, seção 3 e 5: (setores com acesso, motivo). Vale por código e versão;
# versão substituída é sigilosa da GEPEC (arquivo histórico), qualquer que seja o código.
SIGILOSOS = {
    "NT_2026-021": (["GEINOV", "DIRTEC", "DIRAF"],
                    "Orçamento de R$ 96 mil, alçadas de gasto e indicadores da edição anterior: "
                    "documento de decisão gerencial."),
    "NT_2026-018": (["GESUC", "GOC", "DIRAF"],
                    "Cotações de 3 fornecedores, preço de referência e alçada da contratação."),
    "CTR_2026-012": (["GESUC", "GOC", "GFI"],
                     "Valores, multas, rescisão e dados pessoais dos usuários do coworking. "
                     "GOC fiscaliza e GFI paga."),
}
SUBSTITUIDO = (["GEPEC"], "Versão substituída: a regra antiga pode levar a erro. Fica só no "
                          "arquivo histórico da GEPEC, para auditoria.")
INTERNO = ("Orienta qualquer empregado: regra, passo a passo, formulário em branco ou programa "
           "aberto.")


def classificar(codigo: str, vigente: bool) -> tuple[str, list[str], str]:
    if not vigente:
        return "Sigilosa", *SUBSTITUIDO
    if codigo in SIGILOSOS:
        return "Sigilosa", *SIGILOSOS[codigo]
    return "Interna", [DOMINIO[codigo]], INTERNO


docs = []
for pdf in sorted(BRONZE.rglob("*.pdf")):
    m = re.match(r"(?P<codigo>[A-Z]+_[\d-]+)__.*__v(?P<versao>[\d.]+)\.pdf$", pdf.name)
    codigo = m["codigo"]
    vigente = "substituidos" not in pdf.parts
    classe, setores, motivo = classificar(codigo, vigente)
    docs.append({
        "codigo": codigo,
        "versao": m["versao"],
        "arquivo": pdf.relative_to(BRONZE).as_posix(),
        "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
        "tema": TEMA[pdf.relative_to(BRONZE).parts[0]],
        "dominio": DOMINIO[codigo],
        "classificacao": classe,
        "setores": setores,
        "motivo": motivo,
        "vigente": vigente,
    })

# Documento virtual (sem PDF) para demonstrar bloqueio RBAC e resposta curada. 100% sintético.
docs.append({
    "codigo": "DOSSIE_GGC_FOLHA",
    "versao": "1.0.0",
    "arquivo": None,
    "sha256": None,
    "tema": "ferias",
    "dominio": "GEPEC",
    "classificacao": "Sigilosa",
    "setores": ["GEPEC"],
    "motivo": "Dados de folha de pagamento e exceções da unidade: sigiloso da GEPEC.",
    "vigente": True,
    "titulo": "Dossiê de exceções de ressarcimento e auditoria da folha (sintético)",
    "texto": (
        "Dossiê restrito de auditoria da folha de pagamento. Parâmetros internos de "
        "auditoria para ressarcimento de despesas não reembolsáveis em cancelamento de férias "
        "por necessidade de serviço e histórico de exceções da unidade. Conteúdo fictício "
        "criado só para demonstrar o controle de acesso."
    ),
})

destino = RAIZ / "app" / "seed" / "manifesto.json"
destino.write_text(json.dumps({"documentos": docs}, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
print(f"{len(docs)} documentos -> {destino}")
