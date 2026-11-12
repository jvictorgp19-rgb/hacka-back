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


class LimiteDeCorpo:
    """Middleware ASGI: recusa corpo maior que MAX_BODY_BYTES, contando os bytes na leitura."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limite = get_settings().max_body_bytes
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
