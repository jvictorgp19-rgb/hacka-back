"""Auditoria no Neon: política de conexão, segredo fora de log e gravação em segundo plano.

Nenhum teste conecta no Neon: o CI não tem banco remoto. A gravação real é testada no SQLite;
fila, nova tentativa e encerramento usam um Gravador com função de gravação falsa.
Testes negativos seguem docs/SEGURANCA_NEON_CODEX.md (ids NEON-xx).
"""

import threading
import time

import certifi
import pytest

from app.core.config import Settings, get_settings
from app.services import audit_log
from app.services.audit_log import Gravador, _criar_engine, descrever, normalizar_url

NEON = ("postgresql://raiz_app:SENHA_SECRETA@ep-cool-123-pooler.sa-east-1.aws.neon.tech/neondb"
        "?sslmode=require&channel_binding=require")
REMOTO = "postgresql://u:p@ep-x.sa-east-1.aws.neon.tech/neondb"


# ---------- política de conexão (NEON-01, 03, 07) ----------
def test_url_do_console_vira_psycopg_com_verify_full_e_channel_binding():
    url = normalizar_url(NEON)
    assert url.drivername == "postgresql+psycopg"
    assert url.query["sslmode"] == "verify-full"  # confere certificado e nome do servidor
    assert url.query["channel_binding"] == "require"
    assert url.query["sslrootcert"] == certifi.where()


def test_esquema_postgres_curto_e_aceito():
    assert normalizar_url(NEON.replace("postgresql://", "postgres://")).drivername == \
        "postgresql+psycopg"


def test_tls_completo_e_acrescentado_quando_falta():
    url = normalizar_url(REMOTO)
    assert url.query["sslmode"] == "verify-full" and url.query["channel_binding"] == "require"


@pytest.mark.parametrize("modo", ["disable", "allow", "prefer", "qualquer"])
def test_banco_remoto_sem_tls_e_recusado(modo):
    with pytest.raises(ValueError, match="TLS"):
        normalizar_url(f"{REMOTO}?sslmode={modo}")


def test_channel_binding_desligado_e_recusado():
    with pytest.raises(ValueError, match="channel_binding"):
        normalizar_url(f"{REMOTO}?channel_binding=disable")


@pytest.mark.parametrize("query", ["sslmode=disable&sslmode=require",
                                   "sslmode=require&sslmode=disable"])
def test_parametro_repetido_e_recusado(query):
    with pytest.raises(ValueError, match="repetido"):
        normalizar_url(f"{REMOTO}?{query}")


@pytest.mark.parametrize("query", ["host=remote.invalid", "hostaddr=203.0.113.10",
                                   "password=SEGREDO", "service=x", "passfile=x",
                                   "options=-c%20x", "sslkey=x"])
def test_parametro_que_muda_destino_ou_credencial_e_recusado(query):
    """NEON-03: localhost com ?host=remoto&sslmode=disable não pode virar conexão sem TLS."""
    with pytest.raises(ValueError, match="lista permitida") as erro:
        normalizar_url(f"postgresql://u:p@localhost/db?{query}&sslmode=disable")
    assert "SEGREDO" not in str(erro.value) and "203.0.113" not in str(erro.value)


@pytest.mark.parametrize("bruta", ["postgresql://u:p@h1:5432,h2:5432/db",
                                   "postgresql://u:p@/db", "postgresql:///db"])
def test_host_ausente_ou_multiplo_e_recusado(bruta):
    with pytest.raises(ValueError):
        normalizar_url(bruta)


@pytest.mark.parametrize("variavel", ["PGHOST", "PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"])
def test_variavel_pg_que_muda_destino_e_recusada(monkeypatch, variavel):
    monkeypatch.setenv(variavel, "203.0.113.10")
    with pytest.raises(ValueError, match=variavel):
        normalizar_url("postgresql://u:p@localhost/db")


def test_postgres_local_dispensa_tls_so_fora_de_producao():
    assert "sslmode" not in normalizar_url("postgresql://u:p@localhost:5432/raiz").query
    url = normalizar_url("postgresql://u:p@localhost:5432/raiz", producao=True)
    assert url.query["sslmode"] == "verify-full"


@pytest.mark.parametrize("bruta", ["mysql://u:p@h/db", "mssql+pyodbc://u:p@h/db"])
def test_outros_bancos_sao_recusados(bruta):
    with pytest.raises(ValueError):
        normalizar_url(bruta)


def test_sem_database_url_cai_no_sqlite_so_fora_de_producao():
    assert normalizar_url("").get_backend_name() == "sqlite"
    assert normalizar_url("   ").get_backend_name() == "sqlite"
    with pytest.raises(ValueError, match="obrigatória"):
        normalizar_url("", producao=True)
    with pytest.raises(ValueError, match="SQLite"):
        normalizar_url("sqlite:///./data/app.db", producao=True)


def test_producao_sem_database_url_impede_o_startup(monkeypatch):
    monkeypatch.setattr(get_settings(), "app_env", "production")
    monkeypatch.setattr(get_settings(), "database_url", "")
    with pytest.raises(ValueError):
        audit_log.preparar()


def test_url_insegura_impede_o_startup(monkeypatch):
    monkeypatch.setattr(get_settings(), "database_url", f"{REMOTO}?sslmode=disable")
    with pytest.raises(ValueError):
        audit_log.preparar()


# ---------- segredo fora de log e erro (NEON-06) ----------
def test_senha_malformada_nao_aparece_no_erro_nem_no_traceback():
    with pytest.raises(ValueError) as erro:
        normalizar_url("postgresql://u:prefixo@senha:SUFIXO_FICTICIO@remote.invalid/db")
    assert "SUFIXO_FICTICIO" not in str(erro.value)
    assert erro.value.__suppress_context__  # "from None": o erro original não vai ao traceback


def test_rotulo_de_log_nao_vaza_credencial_nem_host():
    rotulo = descrever(normalizar_url(NEON))
    assert "SENHA_SECRETA" not in rotulo and "raiz_app" not in rotulo and "neon.tech" not in rotulo


def test_repr_da_url_e_das_settings_escondem_segredos():
    assert "SENHA_SECRETA" not in repr(normalizar_url(NEON))
    assert "SENHA_SECRETA" not in str(normalizar_url(NEON))
    cfg = Settings(database_url=NEON, llm_api_key="CHAVE_LLM", auth_token_secret="X" * 40)
    assert "SENHA_SECRETA" not in repr(cfg) and "CHAVE_LLM" not in repr(cfg)
    assert "X" * 40 not in repr(cfg)


def test_engine_do_neon_usa_psycopg_sem_conectar():
    engine = _criar_engine(normalizar_url(NEON))
    assert engine.dialect.name == "postgresql" and engine.dialect.driver == "psycopg"
    engine.dispose()


# ---------- gravação real (SQLite) ----------
def test_registro_e_gravado_sem_texto_da_pergunta(perguntar):
    perguntar("Quero férias a partir de 05/05/2027. Até quando peço?")
    assert audit_log.esvaziar()
    ultimo = audit_log.ultimos(1)[0]
    assert ultimo["sujeito"] == "ana" and ultimo["acao"] == "chat"
    assert "NG_111" in ultimo["fontes"]
    assert "05/05/2027" not in str(ultimo)  # minimização: a pergunta não é guardada


def test_regravar_o_mesmo_lote_nao_duplica(client):
    linha = {"evento_id": "e" * 32, "momento": audit_log.datetime.now(audit_log.UTC),
             "sujeito": "ana", "acao": "chat", "resultado": "permitido", "intent": "teste",
             "fontes": "", "nivel": "Interna"}
    audit_log._gravar_no_banco([linha])
    audit_log._gravar_no_banco([linha])  # commit incerto + nova tentativa
    assert sum(r["evento_id"] == "e" * 32 for r in audit_log.ultimos(500)) == 1


# ---------- fila, nova tentativa e encerramento (NEON-02, 04) ----------
def _linha(i: int) -> dict:
    return {"evento_id": f"{i:032d}"}


def test_lote_que_falha_e_regravado_e_nao_se_perde():
    """NEON-02: banco fora do ar não descarta o lote; ele volta a ser gravado."""
    gravados, falhas = [], [2]

    def gravar(lote):
        if falhas[0]:
            falhas[0] -= 1
            raise ConnectionError("fora do ar")
        gravados.extend(lote)

    g = Gravador(gravar, espera_inicial_s=0.01)
    for i in range(5):
        g.enfileirar(_linha(i))
    assert g.esvaziar(2)
    assert [r["evento_id"] for r in gravados] == [f"{i:032d}" for i in range(5)]
    assert g.descartados == 0 and not g.falhando
    g.encerrar(1)


def test_fila_cheia_descarta_o_excedente_sem_travar():
    liberar, chamado = threading.Event(), threading.Event()

    def gravar(_lote):
        chamado.set()
        liberar.wait(5)

    g = Gravador(gravar, capacidade=3)
    g.enfileirar(_linha(0))
    assert chamado.wait(2)  # o consumidor pegou o primeiro e está preso no banco
    inicio = time.monotonic()
    for i in range(1, 7):
        g.enfileirar(_linha(i))  # 3 cabem, 3 são descartados
    assert time.monotonic() - inicio < 0.5
    assert g.descartados == 3
    liberar.set()
    assert g.esvaziar(2) and g.gravados == 4
    g.encerrar(1)


def test_encerrar_com_banco_travado_respeita_o_prazo():
    """NEON-04: fila cheia e banco preso não podem segurar o desligamento da API."""
    liberar = threading.Event()
    g = Gravador(lambda _lote: liberar.wait(10), capacidade=2)
    for i in range(5):
        g.enfileirar(_linha(i))
    inicio = time.monotonic()
    pendentes = g.encerrar(timeout_s=0.3)
    assert time.monotonic() - inicio < 1.5
    assert pendentes > 0
    liberar.set()


def test_registro_depois_de_encerrar_e_contado_e_nao_fica_orfao():
    g = Gravador(lambda _lote: None)
    g.encerrar(1)
    g.enfileirar(_linha(1))
    assert g.descartados == 1 and g.estado()["pendentes"] == 0


def test_encerrar_com_banco_fora_do_ar_descarta_contando_e_termina():
    def gravar(_lote):
        raise ConnectionError("fora do ar")

    g = Gravador(gravar, espera_inicial_s=0.01)
    for i in range(3):
        g.enfileirar(_linha(i))
    assert g.encerrar(timeout_s=2) == 0
    assert g.descartados == 3 and g.gravados == 0
