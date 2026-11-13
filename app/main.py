"""Entrada da API do Raiz IQ / Zero Click."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import envios as rotas_envios
from app.api.routes import front as rotas_front
from app.api.routes import identidade as rotas_identidade
from app.core.config import get_settings
from app.core.limites import LimiteDeCorpo, OrigemConfiavel
from app.services import audit_log, envios, persistencia, retencao
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
    grafo = get_grafo()
    banco = audit_log.preparar()  # DATABASE_URL insegura impede o startup
    persistencia.sincronizar_em_segundo_plano(acervo, grafo)  # espelho no banco
    envios.restaurar_em_segundo_plano()  # envios e aprovações sobrevivem ao restart
    retencao.iniciar()  # LGPD: apaga envios e registros vencidos, agora e a cada N horas
    for item in acervo.quarentena:
        log.warning("Documento em quarentena: %s (%s)", item["documento"], item["motivo"])
    log.info("Acervo: %d documentos, %d trechos. LLM %s. AUTH_MODE=%s. Auditoria: %s.",
             len(acervo.documentos), len(acervo.chunks),
             "ligado" if get_llm().ligado else "desligado (modo extrativo)", cfg.auth_mode,
             banco)
    if cfg.auth_mode != "token":
        log.warning("AUTH_MODE=demo: RBAC simulado por personaId. Use só com dados sintéticos.")
    try:
        yield
    finally:
        retencao.encerrar()
        envios.encerrar()
        audit_log.encerrar()


# Documentação interativa em /swagger (o caminho já é o que o README e o contrato citam).
app = FastAPI(title="Raiz IQ API", version="0.2.0", lifespan=lifespan,
              docs_url="/swagger", redoc_url=None)

app.add_middleware(LimiteDeCorpo)
app.add_middleware(OrigemConfiavel)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().origens_cors,
    # O front chama com credentials: 'include' (src/services/http/client.ts). Sem este
    # cabeçalho o navegador descarta a resposta. Não há cookie de sessão; as origens são exatas.
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Persona-Id"],
)
app.include_router(rotas_envios.router)
app.include_router(rotas_identidade.router)
app.include_router(rotas_front.router)
