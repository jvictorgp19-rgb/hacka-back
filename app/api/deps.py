"""Dependências comuns das rotas: sujeito resolvido, "hoje" simulado e resposta sem cache."""

from datetime import date
from typing import Annotated

from fastapi import Depends, Query, Response

from app.core.auth import Sujeito, sujeito_da_requisicao

SujeitoDep = Annotated[Sujeito, Depends(sujeito_da_requisicao)]
# "hoje" simulado só muda o que o radar, o auditor e os gráficos mostram. Nunca afeta autorização.
HojeDep = Annotated[date | None, Query(ge=date(2026, 1, 1), le=date(2028, 12, 31))]


def sem_cache(response: Response) -> None:
    """A resposta depende de quem pergunta: nenhum cache intermediário guarda."""
    response.headers["Cache-Control"] = "private, no-store"
