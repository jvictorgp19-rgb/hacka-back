"""Trilha de auditoria (LGPD art. 37): quem perguntou, que tipo de pergunta, que fontes saíram.

NÃO guarda o texto da pergunta nem da resposta (minimização, LGPD art. 6º, III).
SQLite local: serve à demo; não é armazenamento inviolável.
"""

import logging
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, create_engine, select
from sqlalchemy.engine import Engine

from app.core.config import get_settings

log = logging.getLogger("raiz.auditoria")
_meta = MetaData()
auditoria = Table(
    "auditoria", _meta,
    Column("id", Integer, primary_key=True),
    Column("momento", DateTime(timezone=True), nullable=False),
    Column("sujeito", String(40), nullable=False),
    Column("acao", String(40), nullable=False),
    Column("resultado", String(20), nullable=False),  # permitido | bloqueado | abstencao
    Column("intent", String(60), nullable=False),
    Column("fontes", String(400), nullable=False),
    Column("nivel", String(20), nullable=False),
)


@lru_cache
def _engine() -> Engine:
    url = get_settings().database_url
    if url.startswith("sqlite:///") and ":memory:" not in url:
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url)
    _meta.create_all(engine)
    return engine


def registrar(sujeito: str, acao: str, resultado: str, intent: str, fontes: list[str],
              nivel: str) -> None:
    """Falha de auditoria é registrada em log e não derruba a resposta (decisão do MVP)."""
    try:
        with _engine().begin() as conexao:
            conexao.execute(auditoria.insert().values(
                momento=datetime.now(UTC), sujeito=sujeito[:40], acao=acao[:40],
                resultado=resultado[:20], intent=intent[:60],
                fontes=",".join(dict.fromkeys(fontes))[:400], nivel=nivel[:20]))
    except Exception as erro:  # noqa: BLE001
        log.error("Falha ao gravar auditoria: %s", type(erro).__name__)


def ultimos(limite: int = 50) -> list[dict]:
    with _engine().connect() as conexao:
        linhas = conexao.execute(
            select(auditoria).order_by(auditoria.c.id.desc()).limit(limite)).mappings().all()
    return [dict(linha) for linha in linhas]
