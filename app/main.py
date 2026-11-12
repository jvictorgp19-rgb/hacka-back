"""Entrada da API do Raiz IQ / Zero Click."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.contrato import router
from app.core.config import get_settings
from app.core.limites import LimiteDeCorpo
from app.services.acervo import get_acervo
from app.services.agent.router import get_indice
from app.services.grafo import get_grafo
from app.services.llm.client import get_llm

log = logging.getLogger("raiz")


@asynccontextmanager
async def lifespan(_: FastAPI):
    cfg = get_settings()
    acervo = get_acervo()  # carrega o Silver (ou ingere os PDFs do manifesto)
    get_indice()
    get_grafo()
    for item in acervo.quarentena:
        log.warning("Documento em quarentena: %s (%s)", item["documento"], item["motivo"])
    log.info("Acervo: %d documentos, %d trechos. LLM %s. AUTH_MODE=%s.",
             len(acervo.documentos), len(acervo.chunks),
             "ligado" if get_llm().ligado else "desligado (modo extrativo)", cfg.auth_mode)
    if cfg.auth_mode != "token":
        log.warning("AUTH_MODE=demo: RBAC simulado por personaId. Use só com dados sintéticos.")
    yield


# O Swagger fica em /swagger porque GET /docs é rota do contrato com o front (catálogo).
app = FastAPI(title="Raiz IQ API", version="0.2.0", lifespan=lifespan,
              docs_url="/swagger", redoc_url=None)

app.add_middleware(LimiteDeCorpo)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().origens_cors,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Persona-Id"],
)
app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok"}
