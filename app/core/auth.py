"""Identidade do chamador.

AUTH_MODE=demo  -> simulação: aceita personaId (body, header X-Persona-Id ou query).
                   Sem persona válida, o sujeito é anônimo e vê só o nível Pública.
AUTH_MODE=token -> exige Authorization: Bearer <persona>.<exp>.<assinatura HMAC-SHA256>.

Emitir token:  python -m app.core.auth <personaId>
"""

import hashlib
import hmac
import sys
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request

from app.core.acl import ACESSO_ANONIMO, NIVEL_ANONIMO, Acesso
from app.core.config import get_settings
from app.core.personas import PERSONAS, Persona

_ERRO_TOKEN = "Token ausente ou inválido."


@dataclass(frozen=True)
class Sujeito:
    persona: Persona | None
    nivel: str

    @property
    def id(self) -> str:
        return self.persona.id if self.persona else "anonimo"

    @property
    def acesso(self) -> Acesso:
        """Setor (necessidade de conhecer) e credenciamento. Anônimo não tem setor."""
        if self.persona is None:
            return ACESSO_ANONIMO
        return Acesso(setor=self.persona.setor, credenciado=self.persona.nivel == "Sigilosa")


ANONIMO = Sujeito(None, NIVEL_ANONIMO)


def _assinar(persona_id: str, exp: int, segredo: str) -> str:
    msg = f"{persona_id}.{exp}".encode()
    return hmac.new(segredo.encode(), msg, hashlib.sha256).hexdigest()


def emitir_token(persona_id: str) -> str:
    cfg = get_settings()
    if len(cfg.auth_token_secret) < 32:
        raise ValueError("AUTH_TOKEN_SECRET precisa de pelo menos 32 caracteres.")
    if persona_id not in PERSONAS:
        raise ValueError(f"Persona desconhecida: {persona_id}")
    exp = int(time.time()) + cfg.auth_token_ttl_min * 60
    return f"{persona_id}.{exp}.{_assinar(persona_id, exp, cfg.auth_token_secret)}"


def _sujeito_do_token(request: Request) -> Sujeito:
    cfg = get_settings()
    cabecalho = request.headers.get("authorization", "")
    if not cabecalho.lower().startswith("bearer ") or len(cfg.auth_token_secret) < 32:
        raise HTTPException(401, _ERRO_TOKEN)
    partes = cabecalho[7:].strip().split(".")
    if len(partes) != 3 or not partes[1].isdigit():
        raise HTTPException(401, _ERRO_TOKEN)
    persona_id, exp, assinatura = partes[0], int(partes[1]), partes[2]
    esperado = _assinar(persona_id, exp, cfg.auth_token_secret)
    if not hmac.compare_digest(assinatura, esperado) or exp < time.time():
        raise HTTPException(401, _ERRO_TOKEN)
    persona = PERSONAS.get(persona_id)
    if persona is None:
        raise HTTPException(401, _ERRO_TOKEN)
    return Sujeito(persona, persona.nivel)


def resolver_sujeito(request: Request, persona_body: str | None = None) -> Sujeito:
    """Resolve quem chama. O nível nunca vem do cliente: sai do cadastro de personas."""
    cfg = get_settings()
    if cfg.auth_mode == "token":
        sujeito = _sujeito_do_token(request)
        if persona_body and persona_body != sujeito.id:
            raise HTTPException(403, "personaId diverge do token.")
        return sujeito

    informado = (
        persona_body
        or request.headers.get("x-persona-id")
        or request.query_params.get("personaId")
        or cfg.demo_default_persona
    )
    persona = PERSONAS.get(informado or "")
    return Sujeito(persona, persona.nivel) if persona else ANONIMO


def sujeito_da_requisicao(request: Request) -> Sujeito:
    """Dependência FastAPI para rotas sem body."""
    return resolver_sujeito(request)


if __name__ == "__main__":
    print(emitir_token(sys.argv[1]))
