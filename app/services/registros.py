"""O que o site grava: conversas, análises salvas, feedback e pedidos de acesso.

Uma tabela só (`registro_front`), com o tipo, a persona dona do registro, a chave do front e o
JSON no formato do contrato. Gravação síncrona: o front espera a confirmação da API.

LGPD:
- a pergunta do chat é guardada mascarada (CPF, e-mail, telefone etc.; guards.mascarar);
- o registro vence em `RETENCAO_REGISTROS_DIAS` e é apagado (art. 15 e 16);
- quem lê é só a própria persona; pedido de acesso também vai para quem decide pelo setor dono.

Preparar no Neon, com o papel DONO:
    python -m app.services.registros raiz_app
"""

import logging
import threading
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    delete,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as insert_postgres
from sqlalchemy.dialects.sqlite import insert as insert_sqlite
from sqlalchemy.engine import Engine

from app.core import banco
from app.core.banco import criar_engine, url_configurada
from app.core.config import get_settings

log = logging.getLogger(__name__)
TIPOS = ("conversa", "analise", "feedback", "pedido")
LIMITE = 100

_meta = MetaData()
_JSON = JSON().with_variant(JSONB(), "postgresql")
tabela = Table(
    "registro_front", _meta,
    Column("id", String(32), primary_key=True),
    Column("tipo", String(16), nullable=False),
    Column("persona", String(40), nullable=False),
    Column("chave", String(80), nullable=False),
    Column("dono", String(16)),  # pedido de acesso: setor que decide
    Column("criado_em", DateTime(timezone=True), nullable=False),
    Column("atualizado_em", DateTime(timezone=True), nullable=False),
    Column("dados", _JSON, nullable=False),
    UniqueConstraint("tipo", "persona", "chave", name="uq_registro_front_chave"),
)


_trava_engine = threading.Lock()


@lru_cache
def _criar() -> Engine:
    engine = criar_engine(url_configurada())
    _meta.create_all(engine)  # com o papel restrito do Neon, só confere que a tabela existe
    return engine


def _engine() -> Engine:
    """Uma criação só: a retenção do startup e a primeira requisição podem chegar juntas."""
    with _trava_engine:
        return _criar()


def _agora() -> datetime:
    return datetime.now(UTC)


def salvar(tipo: str, persona: str, chave: str, dados: dict, dono: str | None = None) -> dict:
    """Cria ou substitui o registro (tipo, persona, chave). Devolve `dados`."""
    assert tipo in TIPOS
    engine = _engine()
    agora = _agora()
    inserir = insert_postgres if engine.dialect.name == "postgresql" else insert_sqlite
    comando = inserir(tabela).values(id=uuid.uuid4().hex, tipo=tipo, persona=persona,
                                     chave=chave, dono=dono, criado_em=agora,
                                     atualizado_em=agora, dados=dados)
    comando = comando.on_conflict_do_update(
        index_elements=["tipo", "persona", "chave"],
        set_={"dados": comando.excluded.dados, "dono": comando.excluded.dono,
              "atualizado_em": comando.excluded.atualizado_em})
    with engine.begin() as conexao:
        conexao.execute(comando)
    return dados


def listar(tipo: str, persona: str | None = None, donos: set[str] | None = None,
           limite: int = LIMITE) -> list[dict]:
    """Mais recentes primeiro. `persona` e `donos` somam (OU): os meus e os do meu setor."""
    filtros = []
    if persona is not None:
        filtros.append(tabela.c.persona == persona)
    if donos:
        filtros.append(tabela.c.dono.in_(sorted(donos)))
    if not filtros:
        return []
    consulta = (select(tabela.c.dados).where(tabela.c.tipo == tipo, or_(*filtros))
                .order_by(tabela.c.criado_em.desc()).limit(limite))
    with _engine().connect() as conexao:
        return [linha.dados for linha in conexao.execute(consulta)]


def obter(tipo: str, chave: str) -> tuple[str, str | None, dict] | None:
    """(persona, dono, dados) do registro com essa chave, ou None."""
    consulta = select(tabela.c.persona, tabela.c.dono, tabela.c.dados).where(
        tabela.c.tipo == tipo, tabela.c.chave == chave).limit(1)
    with _engine().connect() as conexao:
        linha = conexao.execute(consulta).first()
    return (linha.persona, linha.dono, linha.dados) if linha else None


def expurgar(agora: datetime | None = None) -> int:
    """Apaga o que passou do prazo de retenção."""
    limite = (agora or _agora()) - timedelta(days=get_settings().retencao_registros_dias)
    with _engine().begin() as conexao:
        return conexao.execute(delete(tabela).where(tabela.c.atualizado_em < limite)).rowcount


def expurgar_em_segundo_plano() -> threading.Thread:
    def tarefa() -> None:
        try:
            n = expurgar()
            if n:
                log.info("Registros do site apagados pela retenção: %d.", n)
        except Exception as erro:  # noqa: BLE001 - a mensagem do driver pode trazer host
            log.error("Falha na retenção dos registros do site: %s", type(erro).__name__)

    thread = threading.Thread(target=tarefa, name="registros-retencao", daemon=True)
    thread.start()
    return thread


def limpar() -> None:
    """Testes."""
    with _engine().begin() as conexao:
        conexao.execute(delete(tabela))


if __name__ == "__main__":
    # Com o papel DONO: cria a tabela e dá ao papel da aplicação só o que ele usa.
    import sys

    from sqlalchemy import text

    papel = banco.papel_valido(sys.argv[1] if len(sys.argv) > 1 else "raiz_app")
    try:
        engine = criar_engine(url_configurada())
        _meta.create_all(engine)
        for coluna in banco.migrar_colunas(engine, _meta):
            print(f"Coluna criada: {coluna}")
        if engine.dialect.name == "postgresql":
            with engine.begin() as c:
                c.execute(text(f"REVOKE ALL ON registro_front FROM {papel}"))
                c.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON registro_front "
                               f"TO {papel}"))
    except Exception as erro:  # noqa: BLE001 - a mensagem do driver pode trazer host e usuário
        raise SystemExit(f"Falha ao preparar a tabela: {type(erro).__name__}.") from None
    print(f"Tabela 'registro_front' pronta; {papel} com SELECT, INSERT, UPDATE e DELETE "
          "(DELETE para a retenção).")
