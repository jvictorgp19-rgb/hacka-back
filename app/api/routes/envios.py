"""Envio de arquivos do front (hacka-front: POST /document-jobs, GET /document-jobs/:id).

O front manda um arquivo por requisição, no campo multipart `files`, e espera a lista de itens.
A triagem roda em segundo plano: o POST responde `processing` e o GET traz o resultado.
Regras de quem vê e de quem aprova: app/services/envios.py.
"""


from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app.api.deps import SujeitoDep, sem_cache
from app.core.auth import Sujeito
from app.core.config import get_settings
from app.core.limites import checar_taxa
from app.core.setores import rotulo
from app.schemas.api import UploadItem
from app.services import envios
from app.services.calculators.ferias import dias_por_faltas
from app.services.triagem.extracao import ArquivoRecusado, detectar_formato

router = APIRouter()
NAO_ENCONTRADO = "Envio não encontrado."


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
        response=envio.resposta, ferias=_ferias(envio, sujeito))


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
    finally:
        await form.close()
    return [_item(e, sujeito) for e in itens]


@router.get("/document-jobs/{envio_id}", response_model=UploadItem)
def status(envio_id: str, sujeito: SujeitoDep, response: Response) -> UploadItem:
    sem_cache(response)
    envio = envios.obter(envio_id)
    # Sem permissão é 404, não 403: não confirma que o envio existe.
    if envio is None or not envios.pode_ver(sujeito.persona, sujeito.acesso, envio):
        raise HTTPException(404, NAO_ENCONTRADO)
    return _item(envio, sujeito)

