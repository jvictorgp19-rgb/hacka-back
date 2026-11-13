"""Identidade para o front (hacka-front: GET /identity).

No modo API, o front não escolhe a persona: ele pergunta ao servidor quem é o usuário, como faria
com um SSO. A resposta sai do mesmo sujeito das outras rotas (app/core/auth.py):
- AUTH_MODE=demo: X-Persona-Id, ?persona= ou DEMO_DEFAULT_PERSONA. Simulação, só com dados
  sintéticos.
- AUTH_MODE=token: Authorization: Bearer <token>.
"""


from fastapi import APIRouter, Response

from app.api.deps import SujeitoDep, sem_cache
from app.core.auth import Sujeito
from app.core.config import get_settings
from app.core.setores import rotulo
from app.schemas.api import Identity

router = APIRouter()


def capacidades(sujeito: Sujeito) -> list[str]:
    """O que o front pode oferecer. A autorização de verdade é refeita em cada rota."""
    p = sujeito.persona
    if p is None:
        return []
    caps = ["upload"]
    if p.aprova:
        caps.append("approve")
    if p.governanca:
        caps.append("curate")  # o front mostra a governança com 'curate'
    if sujeito.acesso.credenciado:
        caps.append("sigiloso")
    return caps


def _identidade(sujeito: Sujeito) -> Identity:
    p, modo = sujeito.persona, get_settings().auth_mode
    if p is None:
        return Identity(id=sujeito.id, name="Visitante (sem identificação)", capabilities=[],
                        modo=modo, habilitacao=sujeito.nivel)
    return Identity(id=p.id, name=p.nome, capabilities=capacidades(sujeito), modo=modo,
                    setor=p.setor, setorNome=rotulo(p.setor), cargo=p.papel,
                    senioridade=p.senioridade, habilitacao=p.nivel)


@router.get("/identity", response_model=Identity)
def identidade(sujeito: SujeitoDep, response: Response) -> Identity:
    sem_cache(response)
    return _identidade(sujeito)
