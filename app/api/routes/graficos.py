"""Gráficos do site: GET /analyses/charts?panel=acervo|radar|triagem|uso.

Contagens só com o que o sujeito pode ver; o painel "uso" é da governança. Ver
app/services/graficos.py.
"""

from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response

from app.api.deps import HojeDep, SujeitoDep, sem_cache
from app.core.config import get_settings
from app.core.limites import checar_taxa
from app.schemas.api import Grafico
from app.services import audit_log, graficos

router = APIRouter()


@router.get("/analyses/charts", response_model=list[Grafico])
def charts(request: Request, response: Response, sujeito: SujeitoDep,
           panel: Literal["acervo", "radar", "triagem", "uso"],
           hoje: HojeDep = None) -> list[Grafico]:
    sem_cache(response)
    checar_taxa(request, sujeito.id, "graficos", get_settings().rate_graficos_per_min)
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
