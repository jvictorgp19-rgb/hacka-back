"""Trilha de auditoria: URL do Neon, TLS obrigatório, segredo fora do log e fila assíncrona.

Nenhum teste conecta no Neon: o CI não tem banco remoto. A gravação é testada no SQLite local.
"""

import queue

import pytest

from app.core.config import get_settings
from app.services import audit_log
from app.services.audit_log import _criar_engine, descrever, normalizar_url

NEON = ("postgresql://raiz_app:SENHA_SECRETA@ep-cool-123-pooler.sa-east-1.aws.neon.tech/neondb"
        "?sslmode=require&channel_binding=require")


def test_url_do_console_do_neon_vira_psycopg_com_tls():
    url = normalizar_url(NEON)
    assert url.drivername == "postgresql+psycopg"
    assert url.query["sslmode"] == "require"
    assert url.query["channel_binding"] == "require"


def test_esquema_postgres_curto_e_aceito():
    assert normalizar_url(NEON.replace("postgresql://", "postgres://")).drivername == \
        "postgresql+psycopg"


def test_tls_e_acrescentado_quando_falta():
    url = normalizar_url("postgresql://u:p@ep-x.sa-east-1.aws.neon.tech/neondb")
    assert url.query["sslmode"] == "require"


@pytest.mark.parametrize("modo", ["disable", "allow", "prefer"])
def test_banco_remoto_sem_tls_e_recusado(modo):
    with pytest.raises(ValueError, match="sslmode"):
        normalizar_url(f"postgresql://u:p@ep-x.aws.neon.tech/neondb?sslmode={modo}")


def test_sslmode_repetido_e_recusado():
    with pytest.raises(ValueError):
        normalizar_url("postgresql://u:p@ep-x.aws.neon.tech/db?sslmode=disable&sslmode=require")


def test_postgres_local_dispensa_tls():
    url = normalizar_url("postgresql://u:p@localhost:5432/raiz")
    assert "sslmode" not in url.query


@pytest.mark.parametrize("bruta", ["mysql://u:p@h/db", "mssql+pyodbc://u:p@h/db"])
def test_outros_bancos_sao_recusados(bruta):
    with pytest.raises(ValueError):
        normalizar_url(bruta)


def test_sem_database_url_cai_no_sqlite_local():
    assert normalizar_url("").get_backend_name() == "sqlite"
    assert normalizar_url("   ").get_backend_name() == "sqlite"


def test_rotulo_de_log_nao_vaza_credencial_nem_host():
    rotulo = descrever(normalizar_url(NEON))
    assert "SENHA_SECRETA" not in rotulo and "raiz_app" not in rotulo and "neon.tech" not in rotulo


def test_repr_da_url_esconde_a_senha():
    assert "SENHA_SECRETA" not in repr(normalizar_url(NEON))
    assert "SENHA_SECRETA" not in str(normalizar_url(NEON))


def test_engine_do_neon_usa_psycopg_sem_conectar():
    engine = _criar_engine(normalizar_url(NEON))
    assert engine.dialect.name == "postgresql" and engine.dialect.driver == "psycopg"
    assert engine.pool._pre_ping is True
    engine.dispose()


def test_url_insegura_impede_o_startup(monkeypatch):
    monkeypatch.setattr(get_settings(), "database_url",
                        "postgresql://u:p@ep-x.aws.neon.tech/db?sslmode=disable")
    with pytest.raises(ValueError):
        audit_log.preparar()


def test_registro_e_gravado_sem_texto_da_pergunta(perguntar):
    perguntar("Quero férias a partir de 05/05/2027. Até quando peço?")
    audit_log.esvaziar()
    ultimo = audit_log.ultimos(1)[0]
    assert ultimo["sujeito"] == "ana" and ultimo["acao"] == "chat"
    assert "NG_111" in ultimo["fontes"]
    assert "05/05/2027" not in str(ultimo)  # minimização: a pergunta não é guardada


def test_fila_cheia_descarta_sem_travar_a_resposta(monkeypatch):
    monkeypatch.setattr(audit_log, "_fila", queue.Queue(maxsize=1))
    monkeypatch.setattr(audit_log, "_garantir_trabalhador", lambda: None)
    audit_log.registrar("ana", "chat", "permitido", "x", [], "Interna")
    audit_log.registrar("ana", "chat", "permitido", "x", [], "Interna")  # não bloqueia
    assert audit_log._fila.qsize() == 1
