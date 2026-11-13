"""Arquivos enviados pelo front (/document-jobs): triagem em segundo plano e aprovação.

Ciclo do envio: waiting -> processing -> ready | not_extracted | failed.

O arquivo vai para um temporário, é triado em processo separado (app/services/triagem) e é
apagado logo depois. O texto nunca é guardado. O registro tem só:
- nome, tamanho e hash do arquivo;
- a sugestão de sigilo e de setor, com os tipos de dado achados (nunca os valores);
- a decisão do aprovador.
Base: LGPD art. 6º, III (necessidade) e art. 46 (segurança).

Aprovação (docs/CLASSIFICACAO_BBTS.md; LAI art. 27: classificar é ato de autoridade):
- Precisa de aprovação:
  - o envio de desenvolvedor júnior;
  - toda sugestão que pede revisão humana: sigilosa, conteúdo não extraído ou confiança baixa.
- Pode aprovar:
  - gestor ou sênior do setor de quem enviou ou do setor dono;
  - a curadoria do setor dono;
  - o diretor da diretoria do setor dono.
  Quem enviou nunca aprova o próprio envio.
- Quem vê:
  - antes da decisão, só quem enviou e os aprovadores;
  - depois, vale a regra de acesso do nível e dos setores confirmados (app/core/acl.py).

Fatos de férias (faltas, período aquisitivo, datas) são dados pessoais de quem enviou. Só veem
quem enviou, os aprovadores do envio e a GEPEC (gestão de pessoas), mesmo depois da aprovação.
"""

import logging
import os
import re
import shutil
import tempfile
import threading
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as insert_postgres
from sqlalchemy.dialects.sqlite import insert as insert_sqlite
from sqlalchemy.engine import Engine

from app.core import acl
from app.core.banco import criar_engine, url_configurada
from app.core.config import get_settings
from app.core.personas import Persona
from app.core.setores import setores
from app.services import audit_log
from app.services.triagem.extracao import ArquivoRecusado
from app.services.triagem.servico import triar_arquivo

log = logging.getLogger("raiz.envios")

MAX_EM_MEMORIA = 1000
MAX_NOME = 120
NIVEIS_DECISAO = ("Interna", "Sigilosa")
STATUS_TRIADO = {"ready", "not_extracted"}
ID_VALIDO = re.compile(r"^[0-9a-f]{32}$")


class FilaCheia(RuntimeError):
    """Muitos arquivos esperando triagem."""


class DecisaoInvalida(ValueError):
    """Decisão fora da regra. A mensagem vai para o usuário."""


@dataclass
class Envio:
    id: str
    criado_em: datetime
    enviado_por: str
    setor_enviante: str
    junior: bool
    nome_arquivo: str
    tamanho: int
    status: str = "waiting"
    mensagem: str = "Na fila da triagem."
    sha256: str | None = None
    formato: str | None = None
    paginas: int | None = None
    nivel_sugerido: str | None = None
    setores_sugeridos: list[str] = field(default_factory=list)
    setor_dono: str | None = None
    confianca: float | None = None
    confianca_setor: float | None = None
    motivos: list[dict] = field(default_factory=list)
    resumo: str | None = None
    revisao_humana: bool = True
    aprovacao: str | None = None  # pendente | aprovado | recusado | dispensado
    nivel_final: str | None = None
    setores_finais: list[str] = field(default_factory=list)
    decidido_por: str | None = None
    decidido_em: datetime | None = None
    resposta: str | None = None
    fatos_ferias: dict | None = None


# ---------- tabela no banco (Neon). Sem texto do arquivo. ----------
_meta = MetaData()
_JSON = JSON().with_variant(JSONB(), "postgresql")
tabela = Table(
    "triagem_documento", _meta,
    Column("id", String(32), primary_key=True),
    Column("criado_em", DateTime(timezone=True), nullable=False),
    Column("enviado_por", String(40), nullable=False),
    Column("setor_enviante", String(10), nullable=False),
    Column("junior", Boolean, nullable=False),
    Column("nome_arquivo", String(MAX_NOME), nullable=False),
    Column("tamanho", BigInteger, nullable=False),
    Column("status", String(20), nullable=False),
    Column("mensagem", Text, nullable=False),
    Column("sha256", String(64)),
    Column("formato", String(10)),
    Column("paginas", Integer),
    Column("nivel_sugerido", String(20)),
    Column("setores_sugeridos", _JSON, nullable=False),
    Column("setor_dono", String(10)),
    Column("confianca", Float),
    Column("confianca_setor", Float),
    Column("motivos", _JSON, nullable=False),
    Column("resumo", Text),
    Column("revisao_humana", Boolean, nullable=False),
    Column("aprovacao", String(20)),
    Column("nivel_final", String(20)),
    Column("setores_finais", _JSON, nullable=False),
    Column("decidido_por", String(40)),
    Column("decidido_em", DateTime(timezone=True)),
    Column("resposta", Text),
    Column("fatos_ferias", _JSON),  # só números e datas; ver app/services/triagem/ferias.py
)


@lru_cache
def _engine() -> Engine:
    engine = criar_engine(url_configurada())
    _meta.create_all(engine)  # com o papel restrito do Neon, só confere que a tabela existe
    return engine


def _gravar_no_banco(linha: dict) -> None:
    engine = _engine()
    inserir = insert_postgres if engine.dialect.name == "postgresql" else insert_sqlite
    comando = inserir(tabela).values(**linha)
    comando = comando.on_conflict_do_update(
        index_elements=["id"],
        set_={c: comando.excluded[c] for c in linha if c != "id"})
    with engine.begin() as conexao:
        conexao.execute(comando)


# ---------- estado em memória ----------
_itens: dict[str, Envio] = {}
_trava = threading.Lock()
_na_fila = 0
_temporarios: dict = {}  # tarefa da fila -> arquivo temporário ainda não triado


@lru_cache
def _fila() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=get_settings().triagem_workers,
                              thread_name_prefix="triagem")


@lru_cache
def _fila_banco() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=1, thread_name_prefix="triagem-banco")  # mantém a ordem


def _persistir(envio: Envio) -> None:
    """Grava uma cópia em segundo plano. Falha do banco vira log; a memória continua valendo."""
    linha = asdict(envio)

    def tarefa() -> None:
        try:
            _gravar_no_banco(linha)
        except Exception as erro:  # noqa: BLE001 - a mensagem do driver pode trazer host
            log.error("Falha ao gravar a triagem %s no banco: %s", linha["id"],
                      type(erro).__name__)

    _fila_banco().submit(tarefa)


def _guardar(envio: Envio) -> None:
    with _trava:
        _itens[envio.id] = envio
        if len(_itens) > MAX_EM_MEMORIA:  # descarta os mais antigos já decididos ou com falha
            antigos = sorted((e for e in _itens.values()
                              if e.aprovacao != "pendente" and e.status not in ("waiting",
                                                                                 "processing")),
                             key=lambda e: e.criado_em)
            for e in antigos[:len(_itens) - MAX_EM_MEMORIA]:
                del _itens[e.id]


def obter(envio_id: str) -> Envio | None:
    if not ID_VALIDO.match(envio_id):
        return None
    with _trava:
        envio = _itens.get(envio_id)
        return replace(envio) if envio else None


def listar() -> list[Envio]:
    with _trava:
        return sorted((replace(e) for e in _itens.values()), key=lambda e: e.criado_em,
                      reverse=True)


def limpar() -> None:
    """Testes."""
    with _trava:
        _itens.clear()


# ---------- quem vê, quem aprova ----------
def _diretoria_de(sigla: str | None) -> str | None:
    setor = setores().get(sigla or "")
    return setor.diretoria if setor else None


def e_aprovador(persona: Persona | None, envio: Envio) -> bool:
    if persona is None or persona.id == envio.enviado_por:
        return False
    dono = envio.setor_dono
    if persona.aprova and persona.setor in {envio.setor_enviante, dono}:
        return True
    if dono and dono in persona.cura_dominios:
        return True
    return persona.senioridade == "diretor" and persona.setor == _diretoria_de(dono)


def pode_decidir(persona: Persona | None, envio: Envio) -> bool:
    return (envio.aprovacao == "pendente" and envio.status in STATUS_TRIADO
            and e_aprovador(persona, envio))


def pode_ver(persona: Persona | None, acesso: acl.Acesso, envio: Envio) -> bool:
    if persona is None:
        return False
    if persona.id == envio.enviado_por or e_aprovador(persona, envio):
        return True
    if envio.aprovacao not in ("aprovado", "dispensado") or not envio.nivel_final:
        return False
    return acl.pode_ver(acesso, envio.nivel_final, envio.setores_finais)


def ve_dados_pessoais(persona: Persona | None, envio: Envio) -> bool:
    """Fatos de férias: quem enviou, quem aprova o envio e a GEPEC (LGPD art. 6º, III)."""
    if persona is None:
        return False
    return (persona.id == envio.enviado_por or e_aprovador(persona, envio)
            or persona.setor == "GEPEC")


def ferias_de(persona_id: str) -> list[Envio]:
    """Envios da própria pessoa com fatos de férias, do mais recente ao mais antigo."""
    return [e for e in listar() if e.enviado_por == persona_id and e.fatos_ferias
            and e.status == "ready" and e.aprovacao != "recusado"]


def quem_aprova(envio: Envio) -> str:
    setores_ = list(dict.fromkeys(s for s in (envio.setor_enviante, envio.setor_dono) if s))
    return "gestor ou sênior da " + " ou da ".join(setores_)


# ---------- recebimento e triagem ----------
def nome_seguro(nome: str) -> str:
    """Só o nome do arquivo, sem pasta nem caractere de controle."""
    base = re.split(r"[\\/]", nome or "")[-1]
    base = "".join(c for c in unicodedata.normalize("NFC", base)
                   if unicodedata.category(c)[0] != "C").strip(" .")
    if len(base) > MAX_NOME:
        raiz, ext = os.path.splitext(base)
        base = raiz[:MAX_NOME - len(ext[:20])] + ext[:20]
    return base or "arquivo"


def criar(persona: Persona, nome: str, tamanho: int) -> Envio:
    return Envio(id=uuid.uuid4().hex, criado_em=datetime.now(UTC), enviado_por=persona.id,
                 setor_enviante=persona.setor, junior=persona.senioridade == "junior",
                 nome_arquivo=nome_seguro(nome), tamanho=tamanho)


def recusar(envio: Envio, motivo: str) -> Envio:
    envio.status, envio.mensagem = "failed", motivo
    _guardar(envio)
    _persistir(envio)
    audit_log.registrar(envio.enviado_por, "envio", "bloqueado", "triagem", [envio.id], "-")
    return replace(envio)


def salvar_temporario(origem: BinaryIO) -> Path:
    descritor, caminho = tempfile.mkstemp(prefix="raiz-envio-", suffix=".bin")  # modo 0600
    try:
        with os.fdopen(descritor, "wb") as destino:
            origem.seek(0)
            shutil.copyfileobj(origem, destino, 1 << 20)
    except BaseException:
        Path(caminho).unlink(missing_ok=True)
        raise
    return Path(caminho)


def enfileirar(envio: Envio, caminho: Path) -> Envio:
    global _na_fila
    with _trava:
        if _na_fila >= get_settings().triagem_fila_max:
            caminho.unlink(missing_ok=True)
            raise FilaCheia
        _na_fila += 1
    envio.status, envio.mensagem = "processing", "Triagem em andamento."
    _guardar(envio)
    tarefa = _fila().submit(_processar, envio.id, caminho)
    with _trava:
        _temporarios[tarefa] = caminho
    tarefa.add_done_callback(lambda t: _temporarios.pop(t, None))
    return replace(envio)


def _aplicar_triagem(envio: Envio, triagem) -> None:
    c, d = triagem.classificacao, triagem.departamento
    envio.status = triagem.status
    envio.sha256, envio.formato, envio.paginas = triagem.sha256, triagem.formato, triagem.paginas
    envio.nivel_sugerido, envio.setores_sugeridos = c.nivel, list(c.setores)
    envio.setor_dono, envio.confianca_setor = d["sigla"], d["confianca"]
    envio.confianca, envio.motivos, envio.resumo = c.confianca, list(c.motivos), c.resumo
    envio.revisao_humana = triagem.revisao_humana
    envio.fatos_ferias = triagem.fatos_ferias
    if envio.junior or envio.revisao_humana:
        envio.aprovacao = "pendente"
    else:  # Interna, confiança boa, quem enviou não é júnior: segue a sugestão
        envio.aprovacao = "dispensado"
        envio.nivel_final, envio.setores_finais = c.nivel, list(c.setores)
    envio.mensagem = _mensagem(envio)


def _mensagem(envio: Envio) -> str:
    texto = f"Sugestão: {envio.nivel_sugerido}, setor dono {envio.setor_dono}"
    if envio.nivel_sugerido == "Sigilosa":
        texto += f"; acesso: {', '.join(envio.setores_sugeridos)}"
    texto += f". {envio.resumo}"
    if envio.aprovacao == "pendente":
        motivo = "envio de desenvolvedor júnior" if envio.junior else "classificação a confirmar"
        return f"{texto} Aguarda aprovação ({motivo}): {quem_aprova(envio)}."
    return f"{texto} Liberado sem aprovação."


def _processar(envio_id: str, caminho: Path) -> None:
    global _na_fila
    try:
        with _trava:
            original = _itens.get(envio_id)
            envio = replace(original) if original else None  # leitores nunca veem meio-termo
        if envio is None:
            return
        try:
            triagem = triar_arquivo(caminho, envio.nome_arquivo,
                                    isolar=get_settings().triagem_isolar)
        except ArquivoRecusado as erro:
            envio.status, envio.mensagem = "failed", str(erro)
        except Exception as erro:  # noqa: BLE001 - falha interna não pode derrubar a fila
            log.error("Falha na triagem %s: %s", envio_id, type(erro).__name__)
            envio.status, envio.mensagem = "failed", "Não foi possível processar o arquivo."
        else:
            _aplicar_triagem(envio, triagem)
        with _trava:
            _itens[envio_id] = envio
        _persistir(envio)
        audit_log.registrar(envio.enviado_por, "envio",
                            "permitido" if envio.status != "failed" else "bloqueado",
                            f"triagem:{envio.status}", [envio.id], envio.nivel_sugerido or "-")
    finally:
        caminho.unlink(missing_ok=True)  # o arquivo nunca fica no servidor
        with _trava:
            _na_fila -= 1


# ---------- decisão ----------
def decidir(envio_id: str, persona: Persona, aprovado: bool, resposta: str,
            nivel: str | None = None, setores_: list[str] | None = None) -> Envio:
    with _trava:
        envio = _itens.get(envio_id)
        if envio is None or not pode_decidir(persona, envio):
            raise DecisaoInvalida("Envio não está aguardando a sua aprovação.")
        if aprovado:
            nivel = nivel or envio.nivel_sugerido
            if nivel not in NIVEIS_DECISAO:
                raise DecisaoInvalida("Nível deve ser Interna ou Sigilosa.")
            lista = list(dict.fromkeys(setores_ or envio.setores_sugeridos))
            desconhecidos = [s for s in lista if s not in setores()]
            if desconhecidos or not lista or len(lista) > 10:
                raise DecisaoInvalida("Setores inválidos: use as siglas da classificação BBTS.")
            envio.aprovacao, envio.nivel_final, envio.setores_finais = "aprovado", nivel, lista
            envio.setor_dono = lista[0]
            detalhe = nivel + (f"; acesso: {', '.join(lista)}" if nivel == "Sigilosa"
                               else f", setor dono {lista[0]}")
            envio.mensagem = f"Aprovado por {persona.nome}: {detalhe}."
        else:
            envio.aprovacao, envio.nivel_final, envio.setores_finais = "recusado", None, []
            envio.mensagem = f"Recusado por {persona.nome}."
        envio.decidido_por, envio.decidido_em = persona.id, datetime.now(UTC)
        envio.resposta = resposta
        if resposta:
            envio.mensagem += f" {resposta}"
        copia = replace(envio)
    _persistir(copia)
    audit_log.registrar(persona.id, "aprovacao_envio", "permitido", copia.aprovacao, [copia.id],
                        copia.nivel_final or "-")
    return copia


# ---------- ciclo de vida ----------
def restaurar() -> int:
    """Recarrega do banco os envios recentes (a API pode ter reiniciado)."""
    with _engine().connect() as conexao:
        linhas = conexao.execute(select(tabela).order_by(tabela.c.criado_em.desc())
                                 .limit(MAX_EM_MEMORIA)).mappings().all()
    restaurados = 0
    for linha in linhas:
        envio = Envio(**dict(linha))
        if envio.criado_em.tzinfo is None:  # SQLite não guarda o fuso
            envio.criado_em = envio.criado_em.replace(tzinfo=UTC)
        if envio.status in ("waiting", "processing"):
            envio.status = "failed"
            envio.mensagem = "Processamento interrompido pela reinicialização. Envie de novo."
            _persistir(envio)
        with _trava:
            if envio.id not in _itens:
                _itens[envio.id] = envio
                restaurados += 1
    return restaurados


def restaurar_em_segundo_plano() -> threading.Thread:
    def tarefa() -> None:
        try:
            n = restaurar()
            log.info("Envios restaurados do banco: %d.", n)
        except Exception as erro:  # noqa: BLE001
            log.error("Falha ao restaurar envios do banco: %s", type(erro).__name__)

    thread = threading.Thread(target=tarefa, name="envios-restaurar", daemon=True)
    thread.start()
    return thread


def esperar(timeout_s: float = 30.0) -> bool:
    """Espera a fila de triagem e a gravação no banco (testes)."""
    import time

    limite = time.monotonic() + timeout_s
    while time.monotonic() < limite:
        with _trava:
            ocupado = _na_fila > 0
        if not ocupado:
            _fila_banco().submit(lambda: None).result(max(0.1, limite - time.monotonic()))
            return True
        time.sleep(0.05)
    return False


def encerrar() -> None:
    """Cancela o que ainda não começou e apaga esses temporários. O que está rodando termina."""
    _fila().shutdown(wait=False, cancel_futures=True)
    with _trava:
        pendentes = list(_temporarios.items())
    for tarefa, caminho in pendentes:
        if tarefa.cancelled():
            caminho.unlink(missing_ok=True)
    _fila_banco().shutdown(wait=True)
    _fila.cache_clear()
    _fila_banco.cache_clear()


if __name__ == "__main__":
    # Com o papel DONO: cria a tabela e dá ao papel da aplicação só o que ele usa.
    import sys

    from sqlalchemy import inspect, text

    papel = sys.argv[1] if len(sys.argv) > 1 else "raiz_app"
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", papel):
        raise SystemExit("Nome de papel inválido.")
    try:
        engine = criar_engine(url_configurada())
        _meta.create_all(engine)
        atuais = {c["name"] for c in inspect(engine).get_columns("triagem_documento")}
        with engine.begin() as c:
            for coluna in tabela.columns:  # colunas novas em tabela que já existia
                if coluna.name not in atuais:
                    tipo = coluna.type.compile(dialect=engine.dialect)
                    c.execute(text(f'ALTER TABLE triagem_documento ADD COLUMN "{coluna.name}" '
                                   f"{tipo}"))
                    print(f"Coluna criada: {coluna.name}")
        if engine.dialect.name == "postgresql":
            with engine.begin() as c:
                c.execute(text(f"REVOKE ALL ON triagem_documento FROM {papel}"))
                c.execute(text(f"GRANT SELECT, INSERT, UPDATE ON triagem_documento TO {papel}"))
    except Exception as erro:  # noqa: BLE001 - a mensagem do driver pode trazer host e usuário
        raise SystemExit(f"Falha ao preparar a tabela: {type(erro).__name__}.") from None
    print(f"Tabela 'triagem_documento' pronta; {papel} com SELECT, INSERT e UPDATE.")
