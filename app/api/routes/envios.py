"""Envio de arquivos do front (hacka-front: POST /document-jobs, GET /document-jobs/:id).

O front manda um arquivo por requisição, no campo multipart `files`, e espera a lista de itens.
A triagem roda em segundo plano: o POST responde `processing` e o GET traz o resultado.
Regras de quem vê e de quem aprova: app/services/envios.py.
"""


from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.exc import SQLAlchemyError
from starlette.datastructures import UploadFile

from app.api.deps import SujeitoDep, sem_cache
from app.core.auth import Sujeito
from app.core.config import get_settings
from app.core.limites import checar_taxa
from app.core.setores import rotulo
from app.schemas.api import UploadDecision, UploadItem
from app.services import envios
from app.services.calculators.ferias import dias_por_faltas
from app.services.triagem.extracao import ArquivoRecusado, detectar_formato

router = APIRouter()
NAO_ENCONTRADO = "Envio não encontrado."
BANCO_INDISPONIVEL = "Não foi possível confirmar os dados no banco. Tente novamente."


def _iso(momento) -> str | None:
    return momento.isoformat().replace("+00:00", "Z") if momento else None


def _ferias(envio: envios.Envio, sujeito: Sujeito) -> dict | None:
    f = envio.fatos_ferias
    if not f or not envios.ve_dados_pessoais(sujeito.persona, sujeito.acesso, envio):
        return None
    faltas = f.get("faltas_injustificadas")
    return {"faltasInjustificadas": faltas, "origemFaltas": f.get("origem_faltas"),
            "periodoInicio": f.get("periodo_inicio"), "periodoFim": f.get("periodo_fim"),
            "admissao": f.get("admissao"), "inicioGozo": f.get("inicio_gozo"),
            "diasDeFerias": dias_por_faltas(faltas) if faltas is not None else None,
            "paginas": f.get("paginas", [])}


def _item(envio: envios.Envio, sujeito: Sujeito) -> UploadItem:
    triado = envio.status in envios.STATUS_TRIADO
    return UploadItem(
        id=envio.id, name=envio.nome_arquivo, size=envio.tamanho, status=envio.status,
        message=envio.mensagem, createdAt=_iso(envio.criado_em), sha256=envio.sha256,
        formato=envio.formato, paginas=envio.paginas,
        classificacao={"nivel": envio.nivel_sugerido, "setores": envio.setores_sugeridos,
                       "confianca": envio.confianca, "resumo": envio.resumo,
                       "motivos": envio.motivos} if triado else None,
        departamento={"sigla": envio.setor_dono, "nome": rotulo(envio.setor_dono),
                      "confianca": envio.confianca_setor} if triado else None,
        revisaoHumana=envio.revisao_humana, aprovacao=envio.aprovacao,
        aprovadores=envios.quem_aprova(envio) if envio.aprovacao == "pendente" else None,
        nivelFinal=envio.nivel_final, setoresFinais=envio.setores_finais,
        decidedBy=envio.decidido_por, decidedAt=_iso(envio.decidido_em),
        response=envio.resposta, ferias=_ferias(envio, sujeito),
        fileAvailable=envio.arquivo_disponivel,
        canApprove=(triado and envio.aprovacao == "pendente"
                    and envio.nome_arquivo != envios.EXPURGADO
                    and envios.e_aprovador(sujeito.persona, envio)))


def _receber(arquivo: UploadFile, sujeito: Sujeito) -> envios.Envio:
    """Confere o básico na hora; o resto vai para a fila de triagem."""
    cfg = get_settings()
    envio = envios.criar(sujeito.persona, arquivo.filename or "", arquivo.size or 0)
    if not envio.tamanho:
        return envios.recusar(envio, "Arquivo vazio.")
    if envio.tamanho > cfg.max_upload_bytes:
        return envios.recusar(envio, f"Arquivo acima de {cfg.max_upload_bytes // 2**20} MiB.")
    arquivo.file.seek(0)
    cabeca = arquivo.file.read(8)
    try:
        detectar_formato(cabeca, envio.nome_arquivo)  # assinatura antes de gastar a fila
    except ArquivoRecusado as erro:
        return envios.recusar(envio, str(erro))
    try:
        return envios.enfileirar(envio, envios.salvar_temporario(arquivo.file))
    except envios.FilaCheia:
        return envios.recusar(envio, "Fila de triagem cheia. Tente de novo em instantes.")


@router.post("/document-jobs", response_model=list[UploadItem])
async def enviar(request: Request, response: Response, sujeito: SujeitoDep) -> list[UploadItem]:
    cfg = get_settings()
    sem_cache(response)
    if sujeito.persona is None:
        raise HTTPException(401, "Identifique-se para enviar arquivos.")
    checar_taxa(request, sujeito.id, "upload", cfg.rate_upload_per_min)
    if not request.headers.get("content-type", "").startswith("multipart/form-data"):
        raise HTTPException(415, "Envie os arquivos em multipart/form-data, no campo 'files'.")
    form = await request.form(max_files=cfg.max_upload_files,
                              max_fields=cfg.max_upload_files, max_part_size=1024)
    try:
        arquivos = [v for k, v in form.multi_items()
                    if k == "files" and isinstance(v, UploadFile)]
        if not arquivos:
            raise HTTPException(422, "Nenhum arquivo no campo 'files'.")
        itens = [await run_in_threadpool(_receber, a, sujeito) for a in arquivos]
    except (SQLAlchemyError, envios.PersistenciaIndisponivel):
        raise HTTPException(503, BANCO_INDISPONIVEL) from None
    finally:
        await form.close()
    return [_item(e, sujeito) for e in itens]


@router.get("/document-jobs", response_model=list[UploadItem])
def listar(sujeito: SujeitoDep, response: Response,
           limit: int = Query(default=100, ge=1, le=500),
           offset: int = Query(default=0, ge=0)) -> list[UploadItem]:
    sem_cache(response)
    if sujeito.persona is None:
        raise HTTPException(401, "Identifique-se para consultar seus arquivos.")
    try:
        visiveis = [e for e in envios.listar()
                    if envios.pode_ver(sujeito.persona, sujeito.acesso, e)]
    except SQLAlchemyError:
        raise HTTPException(503, BANCO_INDISPONIVEL) from None
    return [_item(e, sujeito) for e in visiveis[offset:offset + limit]]


def _visivel(envio_id: str, sujeito: Sujeito) -> envios.Envio:
    try:
        envio = envios.obter(envio_id)
    except SQLAlchemyError:
        raise HTTPException(503, BANCO_INDISPONIVEL) from None
    # Sem permissão é 404, não 403: não confirma que o envio existe.
    if envio is None or not envios.pode_ver(sujeito.persona, sujeito.acesso, envio):
        raise HTTPException(404, NAO_ENCONTRADO)
    return envio


@router.get("/document-jobs/{envio_id}", response_model=UploadItem)
def status(envio_id: str, sujeito: SujeitoDep, response: Response) -> UploadItem:
    sem_cache(response)
    return _item(_visivel(envio_id, sujeito), sujeito)


@router.get("/document-jobs/{envio_id}/file")
def baixar(envio_id: str, sujeito: SujeitoDep) -> Response:
    envio = _visivel(envio_id, sujeito)
    # O original pode conter dados pessoais que não saem na resposta resumida da triagem.
    if envio.fatos_ferias and not envios.ve_dados_pessoais(sujeito.persona, sujeito.acesso, envio):
        raise HTTPException(404, NAO_ENCONTRADO)
    try:
        original = envios.conteudo(envio)
    except SQLAlchemyError:
        raise HTTPException(503, BANCO_INDISPONIVEL) from None
    if original is None:
        raise HTTPException(404, "Original indisponível para este envio.")
    return Response(original, media_type="application/octet-stream", headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(envio.nome_arquivo)}"})


@router.post("/document-jobs/{envio_id}/decision", response_model=UploadItem)
def decidir(envio_id: str, body: UploadDecision, sujeito: SujeitoDep,
            response: Response) -> UploadItem:
    sem_cache(response)
    envio = _visivel(envio_id, sujeito)
    if envio.nome_arquivo == envios.EXPURGADO:
        raise HTTPException(409, "Os dados deste envio já foram eliminados.")
    try:
        decidido = envios.decidir(envio, sujeito.persona, body.status, body.response)
    except PermissionError:
        raise HTTPException(403, "Seu perfil não pode aprovar este envio.") from None
    except envios.DecisaoConflitante:
        raise HTTPException(409, "Este envio não está pendente de aprovação.") from None
    except SQLAlchemyError:
        raise HTTPException(503, BANCO_INDISPONIVEL) from None
    return _item(decidido, sujeito)

