"""Rotas do contrato com o front (hacka-front, src/lib/api.ts).

Toda rota resolve o sujeito ANTES de tocar em dados e filtra o resultado pelo nível dele.
Respostas levam Cache-Control: no-store, porque dependem de quem pergunta.
"""

from datetime import date
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Request, Response

from app.api.deps import HojeDep, SujeitoDep, sem_cache
from app.core.acl import Acesso
from app.core.auth import Sujeito, resolver_sujeito
from app.core.config import get_settings
from app.core.limites import checar_taxa
from app.schemas.api import (
    AccessRequestItem,
    ChatRequest,
    ChatResponse,
    DocsResponse,
    GrafoResponse,
    IngestAuditFinding,
    RadarEvent,
    ReportRequest,
    ReportResponse,
    Tema,
)
from app.services import audit_log, reports
from app.services.access import listar_pedidos
from app.services.acervo import get_acervo
from app.services.agent.router import responder
from app.services.grafo import get_grafo
from app.services.ingest_audit import auditar
from app.services.radar import montar_radar

router = APIRouter()


@router.post("/chat", response_model=ChatResponse, response_model_exclude_none=True)
def chat(req: ChatRequest, request: Request, response: Response) -> ChatResponse:
    cfg = get_settings()
    if len(req.message) > cfg.max_message_chars:
        raise HTTPException(422, f"Mensagem acima de {cfg.max_message_chars} caracteres.")
    sujeito = resolver_sujeito(request, req.personaId)
    checar_taxa(request, sujeito.id, "chat", cfg.rate_chat_per_min)
    sem_cache(response)
    return responder(req, sujeito)


@router.get("/docs", response_model=DocsResponse)
def docs(sujeito: SujeitoDep, response: Response,
         tema: Tema | None = None) -> DocsResponse:
    """Catálogo do acervo, só com o que o sujeito pode ver."""
    sem_cache(response)
    acervo = get_acervo()
    visiveis = {d.codigo for d in acervo.visiveis(sujeito.acesso, tema)}
    seed = acervo.seed
    # Versão substituída: vale a classificação DELA (a NG_111 v2.0.0 é Sigilosa da GEPEC),
    # não a da versão vigente com o mesmo código.
    return DocsResponse(
        vigentes=[d for d in seed["documentos_acervo"] if d["codigo"] in visiveis],
        substituidos=[d for d in seed["documentos_substituidos_bloqueados"]
                      if d["codigo"] in visiveis
                      and acervo.pode_versao(sujeito.acesso, d["codigo"], d["versao"])],
        taxonomia=seed["norma_mestra_taxonomia"] if visiveis else {},
        temaFiltro=tema or "todos",
    )


@lru_cache(maxsize=64)
def _projecao(acesso: Acesso, tema: str | None) -> GrafoResponse:
    """A projeção depende só do perfil de acesso e do tema (conjuntos fechados): cache pequeno."""
    return get_grafo().projetar(acesso, tema)


@router.get("/grafo", response_model=GrafoResponse, response_model_exclude_none=True)
def grafo(sujeito: SujeitoDep, request: Request, response: Response,
          tema: Tema | None = None) -> GrafoResponse:
    """Mapa do acervo: documentos, versões e relações, na visão do nível de quem consulta."""
    checar_taxa(request, sujeito.id, "grafo", get_settings().rate_grafo_per_min)
    sem_cache(response)
    return _projecao(sujeito.acesso, tema)


@router.get("/radar", response_model=list[RadarEvent])
def radar(sujeito: SujeitoDep, response: Response, hoje: HojeDep = None) -> list[RadarEvent]:
    sem_cache(response)
    return montar_radar(get_acervo(), sujeito, hoje or date.today())


@router.get("/access", response_model=list[AccessRequestItem], response_model_exclude_none=True)
def access(sujeito: SujeitoDep, response: Response) -> list[AccessRequestItem]:
    sem_cache(response)
    return listar_pedidos(sujeito)


@router.get("/ingest", response_model=list[IngestAuditFinding])
def ingest(sujeito: SujeitoDep, response: Response,
           hoje: HojeDep = None) -> list[IngestAuditFinding]:
    """Auditoria do acervo. Não há upload: a ingestão é offline, a partir do manifesto."""
    sem_cache(response)
    return auditar(get_acervo(), sujeito, hoje or date.today())


def _deck_autorizado(tema: str, sujeito: Sujeito, request: Request) -> ReportResponse:
    checar_taxa(request, sujeito.id, "reports", get_settings().rate_reports_per_min)
    acervo = get_acervo()
    fontes = reports.FONTES[tema]
    if not acervo.autorizado(fontes, sujeito.acesso):
        audit_log.registrar(sujeito.id, "relatorio", "bloqueado", tema, [], sujeito.nivel)
        raise HTTPException(403, "Seu perfil não tem acesso às fontes deste relatório.")
    audit_log.registrar(sujeito.id, "relatorio", "permitido", tema, fontes,
                        acervo.nivel_das_fontes(fontes))
    return reports.montar_deck(acervo, tema)


@router.post("/reports", response_model=ReportResponse)
def gerar_relatorio(req: ReportRequest, request: Request, response: Response) -> ReportResponse:
    sem_cache(response)
    return _deck_autorizado(req.tema, resolver_sujeito(request, req.personaId), request)


@router.get("/reports/pptx")
def baixar_pptx(sujeito: SujeitoDep, request: Request, tema: Tema = "inovacao") -> Response:
    deck = _deck_autorizado(tema, sujeito, request)
    nivel = get_acervo().nivel_das_fontes(reports.FONTES[tema])
    return Response(
        content=reports.montar_pptx(deck, nivel),
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{reports.ARQUIVO[tema]}"',
                 "Cache-Control": "private, no-store"},
    )
