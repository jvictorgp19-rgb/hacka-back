"""Conexão com o banco (Neon/PostgreSQL), compartilhada por auditoria e espelho do acervo.

Revisão de segurança: docs/SEGURANCA_NEON_CODEX.md.
"""

import os
import re
from pathlib import Path

import certifi
from sqlalchemy import MetaData, create_engine, inspect, text
from sqlalchemy.engine import URL, Engine, make_url

from app.core.config import get_settings

URL_LOCAL = "sqlite:///./data/app.db"
HOSTS_LOCAIS = {"localhost", "127.0.0.1", "::1"}
# Só estes parâmetros podem vir na query da DATABASE_URL. host, hostaddr, password, service,
# passfile, options etc. são recusados: mudariam o destino ou a política de TLS por fora.
PARAMETROS_PERMITIDOS = {"sslmode", "channel_binding", "sslrootcert"}
SSLMODE_ACEITO = {"require", "verify-ca", "verify-full"}  # em host remoto, todos viram verify-full
VARIAVEIS_PG_DE_DESTINO = ("PGHOST", "PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE")


def producao() -> bool:
    return get_settings().app_env.strip().lower() in {"production", "producao", "prod"}


def normalizar_url(bruta: str, producao: bool = False) -> URL:
    """Aceita a connection string do Neon como o console entrega e endurece a conexão.

    Banco remoto sai sempre com sslmode=verify-full (certificado E nome do servidor conferidos),
    channel_binding=require e a lista de CAs do certifi. Configuração insegura ou ambígua levanta
    ValueError com mensagem fixa, que nunca repete trechos da URL.
    """
    texto = bruta.strip()
    if not texto:
        if producao:
            raise ValueError("DATABASE_URL é obrigatória em produção (Neon).")
        texto = URL_LOCAL
    try:
        url = make_url(texto)
    except Exception:  # noqa: BLE001 - a mensagem original pode conter a senha
        raise ValueError("DATABASE_URL inválida. Confira o formato (sem repetir aqui).") from None

    backend = url.get_backend_name()
    if backend == "sqlite":
        if producao:
            raise ValueError("SQLite não é aceito em produção: configure o Neon.")
        return url
    if backend not in ("postgresql", "postgres"):
        raise ValueError("DATABASE_URL: use PostgreSQL (Neon) ou SQLite.")
    if set(url.query) - PARAMETROS_PERMITIDOS:
        raise ValueError("DATABASE_URL tem parâmetro fora da lista permitida "
                         "(sslmode, channel_binding, sslrootcert).")
    if any(isinstance(valor, tuple) for valor in url.query.values()):
        raise ValueError("DATABASE_URL tem parâmetro repetido.")
    for variavel in VARIAVEIS_PG_DE_DESTINO:
        if os.environ.get(variavel):
            raise ValueError(f"A variável {variavel} não é aceita: o destino vem só da "
                             "DATABASE_URL.")
    if not url.host or "," in url.host:
        raise ValueError("DATABASE_URL: informe exatamente um host.")

    url = url.set(drivername="postgresql+psycopg")
    if url.host in HOSTS_LOCAIS and not producao:
        return url  # PostgreSQL local de desenvolvimento
    if url.query.get("sslmode", "verify-full") not in SSLMODE_ACEITO:
        raise ValueError("DATABASE_URL: banco remoto exige TLS (sslmode=verify-full).")
    if url.query.get("channel_binding", "require") not in ("require", "prefer"):
        raise ValueError("DATABASE_URL: channel_binding=disable não é aceito.")
    return url.update_query_dict({
        "sslmode": "verify-full",
        "channel_binding": "require",
        "sslrootcert": url.query.get("sslrootcert", certifi.where()),
    })


def descrever(url: URL) -> str:
    """Rótulo para log. Nunca inclui usuário, senha nem host."""
    return "SQLite local" if url.get_backend_name() == "sqlite" else "PostgreSQL (Neon)"


def criar_engine(url: URL) -> Engine:
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
            # Rede que para de responder no meio do INSERT: o TCP desiste em ~15 s.
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 3,
            "tcp_user_timeout": 15000,
            # O pooler do Neon (PgBouncer em modo transação) não combina com prepared statements.
            "prepare_threshold": None,
            "application_name": "raiz-iq",
        },
    )


def url_configurada() -> URL:
    return normalizar_url(get_settings().database_url, producao())


# ---------- usados pelos scripts de preparo (rodam com o papel DONO) ----------
def papel_valido(papel: str) -> str:
    """Nome de papel do Postgres que pode entrar num GRANT sem aspas (vai interpolado no SQL)."""
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", papel or ""):
        raise SystemExit("Nome de papel inválido.")
    return papel


def migrar_colunas(engine: Engine, meta: MetaData) -> list[str]:
    """Cria as colunas novas em tabelas que já existiam. Só o papel DONO consegue."""
    existentes = inspect(engine)
    criadas = []
    with engine.begin() as c:
        for tabela in meta.sorted_tables:
            if not existentes.has_table(tabela.name):
                continue
            atuais = {col["name"] for col in existentes.get_columns(tabela.name)}
            for coluna in tabela.columns:
                if coluna.name in atuais:
                    continue
                tipo = coluna.type.compile(dialect=engine.dialect)
                c.execute(text(f'ALTER TABLE {tabela.name} ADD COLUMN "{coluna.name}" {tipo}'))
                criadas.append(f"{tabela.name}.{coluna.name}")
    return criadas
