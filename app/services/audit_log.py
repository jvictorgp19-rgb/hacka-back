"""Trilha de auditoria (LGPD art. 37): quem perguntou, que tipo de pergunta, que fontes saíram.

NÃO guarda o texto da pergunta nem da resposta (minimização, LGPD art. 6º, III).

Banco: Neon (PostgreSQL), pela DATABASE_URL. Sem DATABASE_URL, cai num SQLite local, que serve
só para testes e desenvolvimento offline; em produção (APP_ENV=production) isso é recusado.

Gravação em segundo plano: a resposta não espera o banco, porque o Neon hiberna e a primeira
conexão depois disso demora. Um lote que falha NÃO é descartado: fica sendo regravado, com espera
crescente, enquanto os novos registros aguardam numa fila limitada. Só se perde registro quando a
fila enche (o excedente é contado no log) ou quando a API encerra com o banco fora do ar.
A fila fica em memória: uma queda do processo perde o que ainda não foi gravado.

Revisão de segurança: docs/SEGURANCA_NEON_CODEX.md.
"""

import logging
import queue
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import insert as insert_postgres
from sqlalchemy.dialects.sqlite import insert as insert_sqlite
from sqlalchemy.engine import Engine

# A política de conexão fica em app/core/banco.py; os nomes seguem exportados daqui.
from app.core.banco import criar_engine as _criar_engine
from app.core.banco import descrever, normalizar_url, url_configurada  # noqa: F401
from app.core.banco import producao as _producao

log = logging.getLogger("raiz.auditoria")

FILA_MAX = 1000
LOTE_MAX = 50

_meta = MetaData()
auditoria = Table(
    "auditoria", _meta,
    # BIGINT no PostgreSQL; no SQLite precisa ser INTEGER para virar autoincremento.
    Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True),
    # Id do evento: regravar um lote cujo commit ficou incerto não duplica o registro.
    Column("evento_id", String(32), nullable=False, unique=True),
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
@lru_cache
def _engine() -> Engine:
    """Cria a engine e confere a tabela. Falha não fica em cache: a próxima tentativa refaz."""
    engine = _criar_engine(url_configurada())
    _meta.create_all(engine)  # com o papel restrito, só confere que a tabela existe
    return engine


def _gravar_no_banco(lote: list[dict]) -> None:
    engine = _engine()
    postgres = engine.dialect.name == "postgresql"
    instrucao = (insert_postgres if postgres else insert_sqlite)(auditoria).on_conflict_do_nothing()
    with engine.begin() as conexao:
        if postgres:
            # SET LOCAL vale só nesta transação: funciona atrás do pooler do Neon.
            conexao.execute(text("SET LOCAL statement_timeout = '5s'"))
            conexao.execute(text("SET LOCAL lock_timeout = '2s'"))
        conexao.execute(instrucao, lote)


# ---------- gravação em segundo plano ----------
class Gravador:
    """Fila limitada e uma thread que grava em lotes, regravando com espera crescente."""

    def __init__(self, gravar: Callable[[list[dict]], None], capacidade: int = FILA_MAX,
                 espera_inicial_s: float = 1.0, espera_max_s: float = 30.0) -> None:
        self._gravar = gravar
        self._fila: queue.Queue = queue.Queue(maxsize=capacidade)
        self._trava = threading.Lock()
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self._aberto = True
        self._espera_inicial_s = espera_inicial_s
        self._espera_max_s = espera_max_s
        self.gravados = 0
        self.descartados = 0
        self.falhando = False

    # Aceitar e encerrar usam a mesma trava: depois de encerrar(), nada entra na fila sem
    # alguém para consumir.
    def enfileirar(self, linha: dict) -> None:
        with self._trava:
            if not self._aberto:
                self._descartar(1, "auditoria encerrada")
                return
            self._iniciar()
            try:
                self._fila.put_nowait(linha)
            except queue.Full:
                self._descartar(1, "fila cheia")

    def abrir(self) -> None:
        with self._trava:
            self._parar.clear()
            self._aberto = True

    def encerrar(self, timeout_s: float = 10.0) -> int:
        """Para de aceitar, tenta gravar o que falta dentro do prazo e devolve os pendentes."""
        with self._trava:
            self._aberto = False
            thread = self._thread
        self._parar.set()
        if thread is not None:
            thread.join(timeout_s)
            if thread.is_alive():
                log.error("Auditoria: encerramento passou do prazo com %d registro(s) pendente(s).",
                          self._fila.unfinished_tasks)
        return self._fila.unfinished_tasks

    def esvaziar(self, timeout_s: float = 5.0) -> bool:
        """Espera a fila assentar (gravada ou descartada). False se o prazo acabar antes."""
        prazo = time.monotonic() + timeout_s
        while self._fila.unfinished_tasks:
            if time.monotonic() > prazo:
                return False
            time.sleep(0.01)
        return True

    def estado(self) -> dict:
        return {"pendentes": self._fila.unfinished_tasks, "gravados": self.gravados,
                "descartados": self.descartados, "falhando": self.falhando}

    # ---------- interno ----------
    def _iniciar(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._consumir, name="auditoria", daemon=True)
            self._thread.start()

    def _descartar(self, quantidade: int, motivo: str) -> None:
        antes = self.descartados
        self.descartados += quantidade
        # Um log no primeiro descarte e depois a cada 100: saturação não vira enxurrada de log.
        if antes == 0 or antes // 100 != self.descartados // 100:
            log.error("Auditoria (%s): %d registro(s) descartado(s) até agora.", motivo,
                      self.descartados)

    def _proximo_lote(self) -> list[dict] | None:
        try:
            lote = [self._fila.get(timeout=0.2)]
        except queue.Empty:
            return None
        while len(lote) < LOTE_MAX:
            try:
                lote.append(self._fila.get_nowait())
            except queue.Empty:
                break
        return lote

    def _concluir(self, quantidade: int) -> None:
        for _ in range(quantidade):
            self._fila.task_done()

    def _descartar_restante(self, lote: list[dict]) -> None:
        perdidos = len(lote)
        self._concluir(len(lote))
        while True:
            try:
                self._fila.get_nowait()
            except queue.Empty:
                break
            self._fila.task_done()
            perdidos += 1
        with self._trava:
            self._descartar(perdidos, "encerramento com banco indisponível")

    def _consumir(self) -> None:
        espera = self._espera_inicial_s
        while True:
            lote = self._proximo_lote()
            if lote is None:
                if self._parar.is_set():
                    return
                continue
            while True:
                try:
                    self._gravar(lote)
                except Exception as erro:  # noqa: BLE001
                    if not self.falhando:
                        # Só o tipo do erro: a mensagem do driver pode trazer host e usuário.
                        log.error("Auditoria indisponível (%s): regravando com espera crescente.",
                                  type(erro).__name__)
                    self.falhando = True
                    if self._parar.is_set():
                        self._descartar_restante(lote)
                        return
                    self._parar.wait(espera)
                    espera = min(espera * 2, self._espera_max_s)
                    continue
                if self.falhando:
                    log.warning("Auditoria voltou a gravar.")
                self.gravados += len(lote)
                self.falhando = False
                espera = self._espera_inicial_s
                self._concluir(len(lote))
                break


_gravador = Gravador(_gravar_no_banco)


def registrar(sujeito: str, acao: str, resultado: str, intent: str, fontes: list[str],
              nivel: str) -> None:
    """Enfileira o registro. Falha de auditoria vai para o log e não derruba a resposta."""
    _gravador.enfileirar({
        "evento_id": uuid.uuid4().hex, "momento": datetime.now(UTC),
        "sujeito": sujeito[:40], "acao": acao[:40], "resultado": resultado[:20],
        "intent": intent[:60], "fontes": ",".join(dict.fromkeys(fontes))[:400],
        "nivel": nivel[:20],
    })


def esvaziar(timeout_s: float = 5.0) -> bool:
    """Espera a fila ser gravada (testes)."""
    return _gravador.esvaziar(timeout_s)


def estado() -> dict:
    """Pendentes, gravados, descartados e se o banco está falhando. Sem destino nem credencial."""
    return _gravador.estado()


# ---------- ciclo de vida ----------
def preparar() -> str:
    """Valida a DATABASE_URL no startup, sem conectar.

    URL insegura levanta ValueError e impede a API de subir. A conexão e a conferência da
    tabela ficam com o gravador, em segundo plano: Neon hibernado não atrasa o startup.
    """
    url = url_configurada()
    if _producao() and ".sa-east-1." not in (url.host or ""):
        log.warning("Banco de auditoria fora da região São Paulo: avalie a transferência "
                    "internacional (LGPD art. 33).")
    _gravador.abrir()
    return descrever(url)


def encerrar(timeout_s: float = 10.0) -> None:
    pendentes = _gravador.encerrar(timeout_s)
    estado_final = _gravador.estado()
    log.info("Auditoria encerrada: %d gravado(s), %d descartado(s), %d pendente(s).",
             estado_final["gravados"], estado_final["descartados"], pendentes)


def ultimos(limite: int = 50) -> list[dict]:
    """Leitura para administração. O papel da aplicação no Neon não tem SELECT."""
    with _engine().connect() as conexao:
        linhas = conexao.execute(
            select(auditoria).order_by(auditoria.c.id.desc()).limit(limite)).mappings().all()
    return [dict(linha) for linha in linhas]


if __name__ == "__main__":
    # Cria a tabela. Rode uma vez com o papel DONO do banco; a aplicação roda com papel restrito.
    try:
        url_dono = url_configurada()
    except ValueError as erro:
        raise SystemExit(f"Configuração recusada: {erro}") from None
    try:
        engine_dono = _criar_engine(url_dono)
        _meta.create_all(engine_dono)
        if engine_dono.dialect.name == "postgresql":
            # A view do painel de gráficos saiu junto com a rota: o papel da aplicação perde o
            # SELECT que tinha nela (LGPD art. 46, menor privilégio).
            with engine_dono.begin() as c:
                c.execute(text("DROP VIEW IF EXISTS auditoria_resumo"))
    except SystemExit:
        raise
    except Exception as erro:  # noqa: BLE001 - a mensagem do driver pode trazer host e usuário
        raise SystemExit(f"Falha ao criar a tabela: {type(erro).__name__}.") from None
    print(f"Tabela 'auditoria' pronta em {descrever(url_dono)}.")
