"""Gera app/seed/manifesto.json: a lista CURADA de documentos que podem ser ingeridos.

O manifesto fixa hash, domínio (área dona), tema e o PISO de classificação de cada PDF.
O cabeçalho do PDF nunca reduz esse piso. Rode de novo só quando o acervo mudar:
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
    "NG_111": "GGC", "PX_1111-001": "GGC", "FM_1111-001": "GGC", "TB_1111-001": "GGC",
    "FL_1111-001": "GGC", "NG_1130": "NIN", "PX_1130-001": "NIN", "RG_1100": "NIN",
    "NT_2026-021": "NIN", "CTR_2026-012": "GCO", "NT_2026-018": "GCO",
}
# Piso de classificação acima do "#interna" impresso no PDF (decisão de curadoria da demo).
PISO = {"CTR_2026-012": "Restrita", "NT_2026-018": "Restrita"}

docs = []
for pdf in sorted(BRONZE.rglob("*.pdf")):
    m = re.match(r"(?P<codigo>[A-Z]+_[\d-]+)__.*__v(?P<versao>[\d.]+)\.pdf$", pdf.name)
    codigo = m["codigo"]
    docs.append({
        "codigo": codigo,
        "versao": m["versao"],
        "arquivo": pdf.relative_to(BRONZE).as_posix(),
        "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
        "tema": TEMA[pdf.relative_to(BRONZE).parts[0]],
        "dominio": DOMINIO[codigo],
        "classificacao": PISO.get(codigo, "Interna"),
        "vigente": "substituidos" not in pdf.parts,
    })

# Documento virtual (sem PDF) para demonstrar bloqueio RBAC e resposta curada. 100% sintético.
docs.append({
    "codigo": "DOSSIE_GGC_FOLHA",
    "versao": "1.0.0",
    "arquivo": None,
    "sha256": None,
    "tema": "ferias",
    "dominio": "GGC",
    "classificacao": "Restrita",
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
