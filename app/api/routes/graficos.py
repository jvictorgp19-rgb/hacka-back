"""Gráficos do site: GET /analyses/charts?panel=acervo|radar|triagem|uso.

Contagens só com o que o sujeito pode ver; o painel "uso" é da governança. Ver
app/services/graficos.py.
"""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app.core.auth import Sujeito, sujeito_da_requisicao
from app.core.config import get_settings
from app.core.limites import checar_taxa
from app.schemas.api import Grafico
from app.services import audit_log, graficos

router = APIRouter()
SujeitoDep = Annotated[Sujeito, Depends(sujeito_da_requisicao)]
# "hoje" simulado só muda o radar. Nunca afeta autorização.
HojeDep = Annotated[date | None, Query(ge=date(2026, 1, 1), le=date(2028, 12, 31))]


@router.get("/analyses/charts", response_model=list[Grafico])
def charts(request: Request, response: Response, sujeito: SujeitoDep,
           panel: Literal["acervo", "radar", "triagem", "uso"],
           hoje: HojeDep = None) -> list[Grafico]:
    response.headers["Cache-Control"] = "private, no-store"
    checar_taxa(request, sujeito.id, "graficos", get_settings().rate_grafo_per_min)
    if panel == "uso" and sujeito.persona is None:
        raise HTTPException(401, "Identifique-se para ver o painel de uso.")
    try:
        saida = graficos.montar(panel, sujeito, hoje or date.today())
    except graficos.SemPermissao as erro:
        audit_log.registrar(sujeito.id, "graficos", "bloqueado", f"painel:{panel}", [],
                            sujeito.nivel)
        raise HTTPException(403, str(erro)) from None
    audit_log.registrar(sujeito.id, "graficos", "permitido", f"painel:{panel}", [],
                        sujeito.nivel)
    return saida
