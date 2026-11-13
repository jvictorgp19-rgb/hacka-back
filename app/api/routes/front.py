"""Rotas que o hacka-front consome (src/services/http/client.ts, branch Dev).

Toda rota resolve o sujeito antes de tocar em dados e devolve só o que ele pode ver. As rotas com
`?persona=` (ou `persona` no corpo) exigem que a persona seja o próprio sujeito: em
AUTH_MODE=token, persona diferente do token é 403.

Mapa tela a rota: docs/CONTRATO.md, seção "Telas do hacka-front".
"""

import logging
from collections.abc import Callable
from datetime import date
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import HojeDep, SujeitoDep, sem_cache
from app.core.auth import Sujeito, resolver_sujeito
from app.core.config import get_settings
from app.core.limites import checar_taxa
from app.schemas.front import (
    Achado,
    DecisaoPedido,
    Documento,
    Fato,
    Feedback,
    FeedbackSalvo,
    NovoPedido,
    Pedido,
    Pergunta,
    Prazo,
    Registro,
    RegistroSalvo,
    RegrasSimulacao,
    Resposta,
)
from app.services import audit_log, evidencias, front
from app.services.evidencias import Links

log = logging.getLogger(__name__)
router = APIRouter()
SEM_NULOS = {"response_model_exclude_none": True}  # zod .optional() recusa null
DOC_ID = r"^[A-Z]{2,8}_[A-Z0-9_-]{1,24}@\d{1,3}\.\d{1,3}\.\d{1,3}$"
PEDIDO_ID = r"^[A-Za-z0-9-]{1,64}$"
T = TypeVar("T")


def _sujeito_da_persona(request: Request) -> Sujeito:
    """?persona= do front: em modo token, precisa ser o dono do token."""
    return resolver_sujeito(request, request.query_params.get("persona") or None)


PersonaDep = Annotated[Sujeito, Depends(_sujeito_da_persona)]


def _links(request: Request) -> Links:
    """Sem API_PUBLIC_URL, a base vem do Host da requisição: serve só para a resposta dela.
    Nada guardado leva link; o link é refeito na leitura."""
    return Links(get_settings().api_public_url or str(request.base_url))


def _identificado(sujeito: Sujeito) -> None:
    if sujeito.persona is None:
        raise HTTPException(401, "Identifique-se para continuar.")


def _gravar(funcao: Callable[[], T]) -> T:
    """Só falha do banco vira 503, com mensagem fixa (o erro do driver pode trazer o host).
    Qualquer outro erro segue como erro do servidor, para não esconder a causa."""
    try:
        return funcao()
    except SQLAlchemyError:
        log.error("Banco indisponível nas rotas do site.")
        raise HTTPException(503, "Armazenamento indisponível. Tente de novo.") from None


def _taxa(request: Request, sujeito: Sujeito) -> None:
    checar_taxa(request, sujeito.id, "registros", get_settings().rate_registros_per_min)


# ---------- acervo e evidências ----------
@router.get("/documents", response_model=list[Documento], **SEM_NULOS)
def documents(request: Request, response: Response, sujeito: SujeitoDep) -> list[dict]:
    sem_cache(response)
    return front.documentos(sujeito, _links(request))


@router.get("/documents/{doc_id}/file")
def document_file(doc_id: Annotated[str, Path(pattern=DOC_ID)],
                  sujeito: SujeitoDep) -> FileResponse:
    """PDF do acervo, com a mesma regra de acesso do catálogo. Sem acesso: 404."""
    try:
        caminho, doc = front.arquivo_do_documento(sujeito, doc_id)
    except front.NaoEncontrado:
        raise HTTPException(404, "Documento não encontrado.") from None
    audit_log.registrar(sujeito.id, "download", "permitido", doc.codigo, [doc.codigo], doc.nivel)
    return FileResponse(caminho, media_type="application/pdf", filename=caminho.name,
                        content_disposition_type="inline",
                        headers={"Cache-Control": "private, no-store",
                                 "X-Content-Type-Options": "nosniff"})


@router.get("/analyses/evidence", response_model=list[Fato], **SEM_NULOS)
def evidence(request: Request, response: Response, sujeito: SujeitoDep) -> list[dict]:
    sem_cache(response)
    return evidencias.fatos(sujeito.acesso, _links(request))


@router.get("/deadlines", response_model=list[Prazo], **SEM_NULOS)
def deadlines(request: Request, response: Response, sujeito: SujeitoDep,
              hoje: HojeDep = None) -> list[dict]:
    sem_cache(response)
    return front.prazos(sujeito, _links(request), hoje or date.today())


@router.get("/audit/findings", response_model=list[Achado])
def findings(response: Response, sujeito: SujeitoDep, hoje: HojeDep = None) -> list[dict]:
    """Só curadoria e diretoria, e só com documentos que o sujeito vê."""
    sem_cache(response)
    return front.achados(sujeito, hoje or date.today())


@router.get("/simulation-rules", response_model=RegrasSimulacao, **SEM_NULOS)
def simulation_rules(request: Request, response: Response, sujeito: SujeitoDep) -> dict:
    sem_cache(response)
    _identificado(sujeito)
    try:
        return front.regras_simulacao(sujeito, _links(request))
    except front.SemPermissao as erro:
        raise HTTPException(403, str(erro)) from None


# ---------- conversa ----------
@router.get("/conversations/messages", response_model=list[Resposta], **SEM_NULOS)
def messages(request: Request, response: Response, sujeito: PersonaDep) -> list[dict]:
    sem_cache(response)
    return _gravar(lambda: front.conversas(sujeito, _links(request)))


@router.post("/conversations/messages", response_model=Resposta, **SEM_NULOS)
def ask(body: Pergunta, request: Request, response: Response) -> dict:
    cfg = get_settings()
    sem_cache(response)
    if len(body.query) > cfg.max_message_chars:
        raise HTTPException(422, f"Mensagem acima de {cfg.max_message_chars} caracteres.")
    sujeito = resolver_sujeito(request, body.context.persona or None)
    checar_taxa(request, sujeito.id, "chat", cfg.rate_chat_per_min)
    resposta, copia = front.perguntar(body.query, body.context, sujeito, _links(request))
    if copia is not None:
        try:
            front.guardar_conversa(sujeito, copia)
        except SQLAlchemyError:  # a resposta vale mesmo sem histórico
            log.error("Conversa não guardada: banco indisponível.")
    return resposta


# ---------- pedidos de acesso ----------
@router.get("/access-requests", response_model=list[Pedido], **SEM_NULOS)
def access_requests(response: Response, sujeito: PersonaDep) -> list[dict]:
    sem_cache(response)
    return _gravar(lambda: front.pedidos(sujeito))


@router.post("/access-requests", response_model=Pedido, **SEM_NULOS)
def create_access_request(body: NovoPedido, request: Request, response: Response) -> dict:
    sem_cache(response)
    sujeito = resolver_sujeito(request, body.persona)
    _identificado(sujeito)
    _taxa(request, sujeito)
    try:
        item = _gravar(lambda: front.criar_pedido(sujeito, body.reason, body.owner))
    except front.Invalido as erro:
        raise HTTPException(422, str(erro)) from None
    # `intent` leva só o setor dono; o id do pedido vai em `fontes`, como nas outras rotas.
    audit_log.registrar(sujeito.id, "pedido_acesso", "permitido", f"dono:{item['owner']}",
                        [f"pedido:{item['id']}"], sujeito.nivel)
    return item


@router.post("/access-requests/{pedido_id}/decision", response_model=Pedido, **SEM_NULOS)
def decide_access_request(pedido_id: Annotated[str, Path(pattern=PEDIDO_ID)],
                          body: DecisaoPedido, request: Request, response: Response) -> dict:
    sem_cache(response)
    sujeito = resolver_sujeito(request, body.persona)
    _identificado(sujeito)
    _taxa(request, sujeito)
    try:
        item = _gravar(lambda: front.decidir_pedido(sujeito, pedido_id, body.status,
                                                    body.response))
    except front.NaoEncontrado:
        raise HTTPException(404, "Pedido não encontrado.") from None
    except front.SemPermissao as erro:
        raise HTTPException(403, str(erro)) from None
    except front.Conflito as erro:
        raise HTTPException(409, str(erro)) from None
    audit_log.registrar(sujeito.id, "decisao_pedido", "permitido", body.status,
                        [f"pedido:{pedido_id}"], sujeito.nivel)
    return item


# ---------- análises salvas e feedback ----------
@router.get("/analyses", response_model=list[RegistroSalvo], **SEM_NULOS)
def records(request: Request, response: Response, sujeito: PersonaDep) -> list[dict]:
    sem_cache(response)
    return _gravar(lambda: front.analises(sujeito, _links(request)))


@router.post("/analyses", response_model=RegistroSalvo, **SEM_NULOS)
def save_record(body: Registro, request: Request, response: Response) -> dict:
    sem_cache(response)
    sujeito = resolver_sujeito(request, body.persona)
    _identificado(sujeito)
    _taxa(request, sujeito)
    return _gravar(lambda: front.salvar_analise(sujeito, body, _links(request)))


@router.get("/feedback", response_model=list[FeedbackSalvo])
def feedback(response: Response, sujeito: PersonaDep) -> list[dict]:
    sem_cache(response)
    return _gravar(lambda: front.feedbacks(sujeito))


@router.post("/feedback", response_model=FeedbackSalvo)
def save_feedback(body: Feedback, request: Request, response: Response) -> dict:
    sem_cache(response)
    sujeito = resolver_sujeito(request, body.persona)
    _identificado(sujeito)
    _taxa(request, sujeito)
    return _gravar(lambda: front.salvar_feedback(sujeito, body))
