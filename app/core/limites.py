"""Limites de uso: tamanho do corpo da requisição e taxa por sujeito + IP.

Contador em memória: suficiente para um processo na demo. Em produção, usar o proxy/Redis.
"""

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings

_janelas: dict[str, deque[float]] = defaultdict(deque)


def checar_taxa(request: Request, sujeito_id: str, grupo: str, por_minuto: int) -> None:
    ip = request.client.host if request.client else "?"
    chave = f"{grupo}:{sujeito_id}:{ip}"
    agora = time.monotonic()
    janela = _janelas[chave]
    while janela and agora - janela[0] > 60:
        janela.popleft()
    if len(janela) >= por_minuto:
        espera = int(60 - (agora - janela[0])) + 1
        raise HTTPException(429, "Muitas requisições. Tente de novo em instantes.",
                            headers={"Retry-After": str(espera)})
    janela.append(agora)
    if len(_janelas) > 10_000:  # evita crescimento sem limite
        _janelas.clear()


def zerar_taxas() -> None:
    _janelas.clear()


MARGEM_MULTIPART = 64 * 1024  # cabeçalhos das partes do multipart
ROTAS_DE_ENVIO = {("POST", "/document-jobs")}


def limite_do_corpo(metodo: str, caminho: str) -> int:
    """16 KiB em geral. Só a rota de envio de arquivo aceita até MAX_UPLOAD_BYTES."""
    cfg = get_settings()
    if (metodo, caminho.rstrip("/")) in ROTAS_DE_ENVIO:
        return cfg.max_upload_bytes + MARGEM_MULTIPART
    return cfg.max_body_bytes


class OrigemConfiavel:
    """Middleware ASGI contra CSRF.

    Em AUTH_MODE=demo, um POST sem persona vira DEMO_DEFAULT_PERSONA: um site qualquer
    agiria em nome dela. Por isso, requisição que altera estado e traz Origin só passa se a
    origem estiver em CORS_ORIGINS. Cliente fora do navegador (curl, testes) não manda Origin
    e segue normal.
    """

    METODOS = {"POST", "PUT", "PATCH", "DELETE"}

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    @staticmethod
    def _permitida(origem: str, scope: Scope) -> bool:
        if origem in get_settings().origens_cors:
            return True
        # Mesma origem (o Swagger em /swagger). O navegador não deixa outro site forjar o Host.
        host = dict(scope.get("headers") or []).get(b"host", b"").decode("latin-1")
        return bool(host) and origem == f"{scope.get('scheme', 'http')}://{host}"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in self.METODOS:
            origem = dict(scope.get("headers") or []).get(b"origin")
            if origem is not None and not self._permitida(
                    origem.decode("latin-1").rstrip("/"), scope):
                corpo = b'{"detail":"Origem nao permitida."}'
                await send({"type": "http.response.start", "status": 403,
                            "headers": [(b"content-type", b"application/json"),
                                        (b"content-length", str(len(corpo)).encode())]})
                await send({"type": "http.response.body", "body": corpo})
                return
        await self.app(scope, receive, send)


class LimiteDeCorpo:
    """Middleware ASGI: recusa corpo acima do limite da rota, contando os bytes na leitura."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limite = limite_do_corpo(scope["method"], scope["path"])
        cabecalhos = dict(scope.get("headers") or [])
        declarado = cabecalhos.get(b"content-length", b"0")
        if declarado.isdigit() and int(declarado) > limite:
            await self._recusar(send)
            return
        lidos = 0

        async def receber() -> Message:
            nonlocal lidos
            mensagem = await receive()
            if mensagem["type"] == "http.request":
                lidos += len(mensagem.get("body", b""))
                if lidos > limite:
                    raise HTTPException(413, "Corpo da requisição acima do limite.")
            return mensagem

        await self.app(scope, receber, send)

    @staticmethod
    async def _recusar(send: Send) -> None:
        corpo = b'{"detail":"Corpo da requisicao acima do limite."}'
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(corpo)).encode())]})
        await send({"type": "http.response.body", "body": corpo})
