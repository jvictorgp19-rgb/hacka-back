"""Trilha de auditoria (LGPD art. 37): quem perguntou, que tipo de pergunta, que fontes saíram.

NÃO guarda o texto da pergunta nem da resposta (minimização, LGPD art. 6º, III).

Banco: Neon (PostgreSQL), pela DATABASE_URL. Sem DATABASE_URL, cai num SQLite local, que serve
só para testes e desenvolvimento offline.

A gravação é assíncrona: a resposta não espera o banco. Isso importa porque o Neon desliga a
máquina quando fica ocioso e a primeira conexão depois disso demora. A fila tem tamanho máximo:
com o banco fora do ar, o excedente é descartado e contado no log, em vez de crescer sem limite.
"""

import logging
import queue
import threading
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    select,
)
from sqlalchemy.engine import URL, Engine, make_url

from app.core.config import get_settings

log = logging.getLogger("raiz.auditoria")

URL_LOCAL = "sqlite:///./data/app.db"
HOSTS_LOCAIS = {"localhost", "127.0.0.1", "::1"}
SSL_ACEITO = {"require", "verify-ca", "verify-full"}
FILA_MAX = 1000
LOTE_MAX = 50

_meta = MetaData()
auditoria = Table(
    "auditoria", _meta,
    # BIGINT no PostgreSQL; no SQLite precisa ser INTEGER para virar autoincremento.
    Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True),
    Column("momento", DateTime(timezone=True), nullable=False),
    Column("sujeito", String(40), nullable=False),
    Column("acao", String(40), nullable=False),
    Column("resultado", String(20), nullable=False),  # permitido | bloqueado | abstencao
    Column("intent", String(60), nullable=False),
    Column("fontes", String(400), nullable=False),
    Column("nivel", String(20), nullable=False),
    # Sem RETURNING: o papel da aplicação no banco só precisa de INSERT.
    implicit_returning=False,
)


# ---------- conexão ----------
def normalizar_url(bruta: str) -> URL:
    """Aceita a connection string do Neon como o console entrega.

    Troca o driver para psycopg 3 e exige TLS em banco remoto. Configuração insegura derruba o
    startup em vez de conectar sem criptografia.
    """
    url = make_url(bruta.strip() or URL_LOCAL)
    backend = url.get_backend_name()
    if backend == "sqlite":
        return url
    if backend not in ("postgresql", "postgres"):
        raise ValueError("DATABASE_URL: use PostgreSQL (Neon) ou SQLite.")
    url = url.set(drivername="postgresql+psycopg")
    if url.host not in HOSTS_LOCAIS:
        sslmode = url.query.get("sslmode", "require")
        if sslmode not in SSL_ACEITO:
            raise ValueError("DATABASE_URL: banco remoto exige sslmode=require, verify-ca "
                             "ou verify-full.")
        url = url.update_query_dict({"sslmode": sslmode})
    return url


def descrever(url: URL) -> str:
    """Rótulo para log. Nunca inclui usuário, senha nem host."""
    return "SQLite local" if url.get_backend_name() == "sqlite" else "PostgreSQL (Neon)"


def _criar_engine(url: URL) -> Engine:
    if url.get_backend_name() == "sqlite":
        if url.database and url.database != ":memory:":
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
        return create_engine(url)
    return create_engine(
        url,
        pool_pre_ping=True,  # o Neon fecha conexões quando a máquina hiberna
        pool_recycle=300,
        pool_size=2,
        max_overflow=2,
        pool_timeout=10,
        connect_args={
            "connect_timeout": 10,
            # O pooler do Neon (PgBouncer em modo transação) não combina com prepared statements.
            "prepare_threshold": None,
            "application_name": "raiz-iq",
        },
    )


@lru_cache
def _engine() -> Engine:
    """Cria a engine e a tabela. Falha não fica em cache: a próxima gravação tenta de novo."""
    engine = _criar_engine(normalizar_url(get_settings().database_url))
    _meta.create_all(engine)
    return engine


# ---------- gravação assíncrona ----------
_fila: queue.Queue = queue.Queue(maxsize=FILA_MAX)
_trava = threading.Lock()
_trabalhador: threading.Thread | None = None
_descartados = 0


def _gravar_lote(lote: list[dict]) -> None:
    try:
        with _engine().begin() as conexao:
            conexao.execute(auditoria.insert(), lote)
    except Exception as erro:  # noqa: BLE001
        # Só o tipo do erro: a mensagem do driver pode trazer host e usuário do banco.
        log.error("Falha ao gravar %d registro(s) de auditoria: %s", len(lote),
                  type(erro).__name__)


def _consumir() -> None:
    while True:
        item = _fila.get()
        lote = [item]
        while len(lote) < LOTE_MAX:
            try:
                lote.append(_fila.get_nowait())
            except queue.Empty:
                break
        parar = None in lote
        registros = [r for r in lote if r is not None]
        if registros:
            _gravar_lote(registros)
        for _ in lote:
            _fila.task_done()
        if parar:
            return


def _garantir_trabalhador() -> None:
    global _trabalhador
    with _trava:
        if _trabalhador is None or not _trabalhador.is_alive():
            _trabalhador = threading.Thread(target=_consumir, name="auditoria", daemon=True)
            _trabalhador.start()


def registrar(sujeito: str, acao: str, resultado: str, intent: str, fontes: list[str],
              nivel: str) -> None:
    """Enfileira o registro. Falha de auditoria vai para o log e não derruba a resposta."""
    global _descartados
    linha = {
        "momento": datetime.now(UTC), "sujeito": sujeito[:40], "acao": acao[:40],
        "resultado": resultado[:20], "intent": intent[:60],
        "fontes": ",".join(dict.fromkeys(fontes))[:400], "nivel": nivel[:20],
    }
    _garantir_trabalhador()
    try:
        _fila.put_nowait(linha)
    except queue.Full:
        _descartados += 1
        log.error("Fila de auditoria cheia: %d registro(s) descartado(s) até agora.",
                  _descartados)


def esvaziar() -> None:
    """Espera a fila ser gravada (testes e encerramento)."""
    _garantir_trabalhador()
    _fila.join()


# ---------- ciclo de vida ----------
def preparar() -> str:
    """Valida a DATABASE_URL e abre o banco no startup.

    URL insegura levanta ValueError e impede a API de subir. Banco fora do ar só vira log: o
    chat continua respondendo e a gravação tenta de novo no próximo registro.
    """
    url = normalizar_url(get_settings().database_url)
    try:
        _engine()
    except Exception as erro:  # noqa: BLE001
        log.error("Banco de auditoria indisponível no startup: %s", type(erro).__name__)
    _garantir_trabalhador()
    return descrever(url)


def encerrar(timeout_s: float = 10) -> None:
    """Grava o que falta na fila e para o trabalhador."""
    global _trabalhador
    with _trava:
        trabalhador = _trabalhador
        _trabalhador = None
    if trabalhador is not None and trabalhador.is_alive():
        _fila.put(None)
        trabalhador.join(timeout_s)


def ultimos(limite: int = 50) -> list[dict]:
    """Leitura para administração. O papel da aplicação no Neon não precisa de SELECT."""
    with _engine().connect() as conexao:
        linhas = conexao.execute(
            select(auditoria).order_by(auditoria.c.id.desc()).limit(limite)).mappings().all()
    return [dict(linha) for linha in linhas]


if __name__ == "__main__":
    # Cria a tabela. Rode uma vez com o papel DONO do banco; a aplicação roda com papel restrito.
    logging.basicConfig(level=logging.INFO)
    url = normalizar_url(get_settings().database_url)
    _meta.create_all(_criar_engine(url))
    print(f"Tabela 'auditoria' pronta em {descrever(url)}.")
