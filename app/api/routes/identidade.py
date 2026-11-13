"""Identidade para o front (hacka-front: GET /identity).

No modo API, o front não escolhe a persona: ele pergunta ao servidor quem é o usuário, como faria
com um SSO. Sem tela de login, quem apresenta grava a identidade com POST /identity, pelo Swagger
(/swagger) ou pelo próprio front. O servidor guarda num cookie HttpOnly:
- AUTH_MODE=demo: o id da persona (cookie raiz_persona). Simulação, só com dados sintéticos.
- AUTH_MODE=token: o token assinado (cookie raiz_sessao), conferido a cada requisição.
"""


from fastapi import APIRouter, HTTPException, Request, Response

from app.api.deps import SujeitoDep, sem_cache
from app.core.auth import (
    ANONIMO,
    COOKIE_DEMO,
    COOKIE_SESSAO,
    Sujeito,
    validar_token,
)
from app.core.config import get_settings
from app.core.limites import checar_taxa
from app.core.personas import PERSONAS
from app.core.setores import rotulo
from app.schemas.api import Identity, IdentityLogin
from app.services import audit_log

router = APIRouter()
TENTATIVAS_POR_MINUTO = 10


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


def _gravar_cookie(response: Response, nome: str, valor: str, minutos: int) -> None:
    cfg = get_settings()
    response.set_cookie(nome, valor, max_age=minutos * 60, path="/", httponly=True,
                        secure=cfg.cookie_secure or cfg.cookie_samesite == "none",
                        samesite=cfg.cookie_samesite)


@router.get("/identity", response_model=Identity)
def identidade(sujeito: SujeitoDep, response: Response) -> Identity:
    sem_cache(response)
    return _identidade(sujeito)


@router.post("/identity", response_model=Identity)
def entrar(body: IdentityLogin, request: Request, response: Response) -> Identity:
    cfg = get_settings()
    sem_cache(response)
    checar_taxa(request, "identidade", "identidade", TENTATIVAS_POR_MINUTO)
    if cfg.auth_mode == "token":
        if not body.token:
            raise HTTPException(422, "Em AUTH_MODE=token, envie o token emitido pelo servidor.")
        sujeito = validar_token(body.token)
        _gravar_cookie(response, COOKIE_SESSAO, body.token.strip(),
                       min(cfg.auth_token_ttl_min, cfg.cookie_max_age_min))
    else:
        persona = PERSONAS.get(body.persona or "")
        if persona is None:
            raise HTTPException(422, "Persona desconhecida.")
        sujeito = Sujeito(persona, persona.nivel)
        _gravar_cookie(response, COOKIE_DEMO, persona.id, cfg.cookie_max_age_min)
    audit_log.registrar(sujeito.id, "identidade", "permitido", "entrar", [], sujeito.nivel)
    return _identidade(sujeito)


@router.post("/identity/sair", response_model=Identity)
def sair(response: Response) -> Identity:
    sem_cache(response)
    cfg = get_settings()
    for nome in (COOKIE_DEMO, COOKIE_SESSAO):  # mesmos atributos da gravação, ou o navegador ignora
        response.delete_cookie(nome, path="/", httponly=True,
                               secure=cfg.cookie_secure or cfg.cookie_samesite == "none",
                               samesite=cfg.cookie_samesite)
    return _identidade(ANONIMO)
