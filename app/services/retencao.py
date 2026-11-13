"""Retenção periódica (LGPD art. 15 e 16): apaga o que venceu enquanto a API está no ar.

Roda logo no startup e depois a cada `RETENCAO_INTERVALO_H` horas, numa thread daemon:
- envios: elimina nome do arquivo, resposta do aprovador e fatos de férias
  (`RETENCAO_ENVIOS_DIAS`);
- registros do site: apaga conversas, análises, feedback e pedidos (`RETENCAO_REGISTROS_DIAS`).

A leitura já esconde o que venceu; o expurgo apaga de fato.
"""

import logging
import threading
from collections.abc import Callable

from app.core.config import get_settings
from app.services import envios, registros

log = logging.getLogger(__name__)
TAREFAS: tuple[tuple[str, Callable[[], int]], ...] = (
    ("envios", lambda: envios.expurgar()),
    ("registros do site", lambda: registros.expurgar()),
)

_parar = threading.Event()


def rodar_uma_vez() -> None:
    for nome, expurgar in TAREFAS:
        try:
            n = expurgar()
            if n:
                log.info("Retenção: %d %s eliminados.", n, nome)
        except Exception as erro:  # noqa: BLE001 - a mensagem do driver pode trazer host
            log.error("Falha na retenção de %s: %s", nome, type(erro).__name__)


def iniciar() -> threading.Thread:
    intervalo_s = max(1, get_settings().retencao_intervalo_h) * 3600
    _parar.clear()

    def laco() -> None:
        while True:
            rodar_uma_vez()
            if _parar.wait(intervalo_s):
                return

    thread = threading.Thread(target=laco, name="retencao", daemon=True)
    thread.start()
    return thread


def encerrar() -> None:
    _parar.set()
